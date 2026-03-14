import json
import os
import re
import uuid
import tempfile
from datetime import datetime, timezone
from typing import Dict, List

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from auth import ALGORITHM, JWT_SECRET, create_access_token, verify_password
from db import engine
from indexing_workers import process_document, process_zip_package, es, ensure_index, rebuild_search_index
from schemas import DocumentMetadata, sanitize_metadata

STORAGE_DIR = os.getenv("STORAGE_DIR", "./storage")
STORAGE_PATH = STORAGE_DIR
ELASTICSEARCH_INDEX = os.getenv("ELASTICSEARCH_INDEX", "enterprise_docs")
MAX_FILE_SIZE = 50 * 1024 * 1024
MAX_PACKAGE_SIZE = 500 * 1024 * 1024
ALLOWED_TYPES = {"application/pdf"}
ZIP_TYPES = {
    "application/zip",
    "application/x-zip-compressed",
    "multipart/x-zip",
}
security = HTTPBearer()

os.makedirs(STORAGE_DIR, exist_ok=True)


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)

    def disconnect(self, websocket: WebSocket, user_id: str):
        try:
            if user_id in self.active_connections:
                self.active_connections[user_id].remove(websocket)
                if not self.active_connections[user_id]:
                    del self.active_connections[user_id]
        except ValueError:
            pass

    async def notify_user(self, user_id: str, message: dict):
        connections = self.active_connections.get(user_id, [])
        disconnected = []

        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)

        for conn in disconnected:
            self.disconnect(conn, user_id)


manager = ConnectionManager()
app = FastAPI(title="Enterprise Document API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", name or "")
    return cleaned or "document.pdf"


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        role = payload.get("role")
        if not user_id or not role:
            raise HTTPException(status_code=401, detail="Invalid token")
        return {"id": user_id, "role": role}
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


def require_roles(*roles):
    def inner(user=Depends(get_current_user)):
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="Forbidden")
        return user
    return inner


def check_db() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def queue_document(document_id: str, file_path: str, metadata_obj: dict):
    process_document.delay(
        document_id,
        file_path,
        {
            **metadata_obj,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        },
    )


@app.on_event("startup")
def startup():
    ensure_index()


@app.post("/auth/login")
def login(email: str = Form(...), password: str = Form(...)):
    with engine.connect() as conn:
        user = conn.execute(
            text("SELECT id, password_hash, role FROM users WHERE email = :email"),
            {"email": email},
        ).mappings().first()
    if not user or not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {
        "access_token": create_access_token(str(user["id"]), user["role"]),
        "role": user["role"],
        "token_type": "bearer",
    }


@app.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    metadata: str = Form("{}"),
    user=Depends(require_roles("admin", "editor")),
):
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported file type")

    try:
        metadata_raw = json.loads(metadata or "{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid metadata JSON")

    metadata_obj = DocumentMetadata.sanitize(metadata_raw)
    metadata_obj = {**metadata_obj, **sanitize_metadata(metadata_raw)}
    metadata_obj["source"] = "web_upload"

    safe_name = safe_filename(file.filename)
    size = 0
    chunks = []
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail="File exceeds 50MB limit")
        chunks.append(chunk)

    try:
        with engine.begin() as conn:
            existing = conn.execute(
                text("""
                SELECT id, current_version
                  FROM documents
                 WHERE filename = :filename AND owner_id = CAST(:owner_id AS UUID)
                 ORDER BY created_at DESC
                 LIMIT 1
                """),
                {"filename": safe_name, "owner_id": user["id"]},
            ).mappings().first()

            if existing:
                document_id = str(existing["id"])
                version = int(existing["current_version"]) + 1
                metadata_obj["version"] = version
                conn.execute(
                    text("""
                    UPDATE documents
                       SET current_version = :version,
                           status = 'PENDING',
                           updated_at = NOW(),
                           metadata = CAST(:metadata AS JSONB),
                           error_message = NULL
                     WHERE id = :id
                    """),
                    {"version": version, "id": document_id, "metadata": json.dumps(metadata_obj)},
                )
            else:
                document_id = str(uuid.uuid4())
                version = 1
                metadata_obj["version"] = version
                conn.execute(
                    text("""
                    INSERT INTO documents (
                        id, filename, current_version, storage_path, mime_type, file_size,
                        status, owner_id, metadata, created_at, updated_at
                    ) VALUES (
                        :id, :filename, :current_version, :storage_path, :mime_type, :file_size,
                        'PENDING', CAST(:owner_id AS UUID), CAST(:metadata AS JSONB), NOW(), NOW()
                    )
                    """),
                    {
                        "id": document_id,
                        "filename": safe_name,
                        "current_version": version,
                        "storage_path": "",
                        "mime_type": file.content_type,
                        "file_size": size,
                        "owner_id": user["id"],
                        "metadata": json.dumps(metadata_obj),
                    },
                )

            versioned_name = f"{document_id}_v{version}_{safe_name}"
            file_path = os.path.join(STORAGE_DIR, versioned_name)
            with open(file_path, "wb") as buffer:
                for chunk in chunks:
                    buffer.write(chunk)

            conn.execute(
                text("""
                UPDATE documents
                   SET storage_path = :storage_path,
                       file_size = :file_size
                 WHERE id = :id
                """),
                {"storage_path": file_path, "file_size": size, "id": document_id},
            )

            conn.execute(
                text("""
                INSERT INTO document_versions (
                    document_id, version_number, storage_path, file_hash, metadata, status
                ) VALUES (
                    CAST(:document_id AS UUID), :version_number, :storage_path, '', CAST(:metadata AS JSONB), 'PENDING'
                )
                ON CONFLICT (document_id, version_number) DO UPDATE
                SET storage_path = EXCLUDED.storage_path,
                    metadata = EXCLUDED.metadata,
                    status = EXCLUDED.status
                """),
                {
                    "document_id": document_id,
                    "version_number": version,
                    "storage_path": file_path,
                    "metadata": json.dumps(metadata_obj),
                },
            )

        queue_document(document_id, file_path, metadata_obj)

        return {
            "document_id": document_id,
            "filename": safe_name,
            "version": version,
            "status": "PENDING",
        }
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/upload-package")
async def upload_zip(
    file: UploadFile = File(...),
    user=Depends(require_roles("admin", "editor")),
):
    if file.content_type not in ZIP_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported package type")

    temp_zip = os.path.join(tempfile.gettempdir(), f"temp_{uuid.uuid4()}.zip")
    size = 0

    try:
        with open(temp_zip, "wb") as buffer:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_PACKAGE_SIZE:
                    raise HTTPException(status_code=413, detail="ZIP exceeds size limit")
                buffer.write(chunk)

        zip_id = str(uuid.uuid4())
        task = process_zip_package.delay(zip_id, temp_zip)

        return {
            "zip_id": zip_id,
            "status": "PENDING",
            "task_id": task.id,
            "package": file.filename,
        }
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/documents")
def get_documents(user=Depends(require_roles("admin", "editor", "viewer"))):
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
            SELECT id, filename, current_version AS version, status, updated_at, file_size, metadata
              FROM documents
             WHERE owner_id = CAST(:owner_id AS UUID) OR :role = 'admin'
             ORDER BY updated_at DESC
            """),
            {"owner_id": user["id"], "role": user["role"]},
        ).mappings().all()
    return rows


@app.get("/documents/search")
def search_documents(
    q: str = Query("", min_length=0),
    status: str = "all",
    user=Depends(require_roles("admin", "editor", "viewer")),
):
    ensure_index()
    try:
        if q.strip():
            query_body = {
                "query": {
                    "bool": {
                        "must": [{
                            "multi_match": {
                                "query": q,
                                "fields": [
                                    "filename.ngram^2",
                                    "content.ngram",
                                    "metadata.*"
                                ],
                                "fuzziness": "AUTO"
                            }
                        }],
                        "filter": (
                            ([{"term": {"status": status}}] if status != "all" else []) +
                            ([{"term": {"owner_id": user["id"]}}] if user["role"] != "admin" else [])
                        )
                    }
                },
                "highlight": {
                    "pre_tags": ["<mark>"],
                    "post_tags": ["</mark>"],
                    "fields": {"content": {"fragment_size": 150, "number_of_fragments": 1}, "filename": {}}
                },
                "aggs": {
                    "statuses": {"terms": {"field": "status"}},
                    "mime_types": {"terms": {"field": "mime_type"}}
                }
            }
        else:
            query_body = {
                "query": {
                    "bool": {
                        "must": [{"match_all": {}}],
                        "filter": (
                            ([{"term": {"status": status}}] if status != "all" else []) +
                            ([{"term": {"owner_id": user["id"]}}] if user["role"] != "admin" else [])
                        )
                    }
                },
                "aggs": {
                    "statuses": {"terms": {"field": "status"}},
                    "mime_types": {"terms": {"field": "mime_type"}}
                }
            }

        results = es.search(index=ELASTICSEARCH_INDEX, body=query_body, size=50)

        return {
            "items": [
                {
                    "id": hit["_id"],
                    "doc_id": hit["_source"].get("document_id") or hit["_id"],
                    "score": hit.get("_score"),
                    "filename": hit["_source"].get("filename"),
                    "metadata": hit["_source"].get("metadata"),
                    "highlight": hit.get("highlight", {}),
                    "status": hit["_source"].get("status"),
                    "version": hit["_source"].get("version"),
                }
                for hit in results["hits"]["hits"]
            ],
            "facets": results.get("aggregations", {}),
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Search engine unavailable: {str(e)}")


@app.get("/search")
async def search(q: str = Query(..., min_length=3), user=Depends(require_roles("admin", "editor", "viewer"))):
    try:
        search_query = {
            "query": {
                "bool": {
                    "must": [{
                        "multi_match": {
                            "query": q,
                            "fields": ["content.ngram", "filename.ngram", "metadata.*"],
                            "fuzziness": "AUTO"
                        }
                    }],
                    "filter": ([{"term": {"owner_id": user["id"]}}] if user["role"] != "admin" else [])
                }
            },
            "highlight": {
                "pre_tags": ["<mark>"],
                "post_tags": ["</mark>"],
                "fields": {"content": {"fragment_size": 150, "number_of_fragments": 1}}
            }
        }

        response = es.search(index=ELASTICSEARCH_INDEX, body=search_query, size=50)
        hits = response["hits"]["hits"]

        return [
            {
                "doc_id": hit["_source"].get("document_id") or hit["_id"],
                "filename": hit["_source"].get("filename"),
                "score": hit.get("_score"),
                "highlight": hit.get("highlight", {}).get("content", ["No preview available"])[0]
            }
            for hit in hits
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/documents/{document_id}/versions")
def get_versions(document_id: str, user=Depends(require_roles("admin", "editor", "viewer"))):
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
            SELECT version_number, storage_path, status, created_at, metadata
              FROM document_versions
             WHERE document_id = CAST(:document_id AS UUID)
             ORDER BY version_number DESC
            """),
            {"document_id": document_id},
        ).mappings().all()
    return rows


@app.post("/admin/rebuild-index")
def rebuild_index(user=Depends(require_roles("admin"))):
    task = rebuild_search_index.delay()
    return {"status": "started", "task_id": task.id}


@app.get("/health")
def health_check():
    db_online = check_db()
    try:
        es_online = es.ping()
    except Exception:
        es_online = False

    return {
        "database": "online" if db_online else "offline",
        "elasticsearch": "online" if es_online else "offline",
        "storage_writable": os.path.isdir(STORAGE_PATH) and os.access(STORAGE_PATH, os.W_OK),
    }


@app.websocket("/ws/notifications/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await manager.connect(websocket, user_id)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)
