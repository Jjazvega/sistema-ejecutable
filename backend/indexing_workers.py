import hashlib
import json
import logging
import os
import shutil
import uuid
import zipfile
from datetime import datetime, timezone

import fitz
from celery import Celery
from elasticsearch import Elasticsearch
from elasticsearch.exceptions import ElasticsearchException
from sqlalchemy import text

from db import engine
from zip_utils import safe_extract, validate_zip_limits

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
ELASTICSEARCH_URL = os.getenv("ELASTICSEARCH_URL", "http://localhost:9200")
ELASTICSEARCH_INDEX = os.getenv("ELASTICSEARCH_INDEX", "enterprise_docs")

celery_app = Celery("indexing_workers", broker=REDIS_URL)
es = Elasticsearch(ELASTICSEARCH_URL)


def ensure_index() -> None:
    if es.indices.exists(index=ELASTICSEARCH_INDEX):
        return
    es.indices.create(
        index=ELASTICSEARCH_INDEX,
        settings={
            "analysis": {
                "tokenizer": {
                    "ngram_tokenizer": {
                        "type": "ngram",
                        "min_gram": 3,
                        "max_gram": 10,
                        "token_chars": ["letter", "digit"],
                    }
                },
                "analyzer": {
                    "ngram_analyzer": {
                        "type": "custom",
                        "tokenizer": "ngram_tokenizer",
                        "filter": ["lowercase"],
                    }
                }
            }
        },
        mappings={
            "properties": {
                "document_id": {"type": "keyword"},
                "filename": {
                    "type": "text",
                    "fields": {
                        "keyword": {"type": "keyword"},
                        "ngram": {"type": "text", "analyzer": "ngram_analyzer"},
                    },
                },
                "content": {
                    "type": "text",
                    "fields": {
                        "ngram": {"type": "text", "analyzer": "ngram_analyzer"},
                    },
                },
                "status": {"type": "keyword"},
                "mime_type": {"type": "keyword"},
                "version": {"type": "integer"},
                "owner_id": {"type": "keyword"},
                "metadata": {"type": "object", "dynamic": True},
                "indexed_at": {"type": "date"},
            }
        },
    )


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_pdf_text(path: str) -> str:
    text_parts = []
    with fitz.open(path) as doc:
        for page in doc:
            text_parts.append(page.get_text("text"))
    return "\n".join(text_parts).strip()


def update_db_status(doc_id: str, status: str, error_message: str | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("""
            UPDATE documents
               SET status = :status,
                   updated_at = NOW(),
                   error_message = :error_message
             WHERE id = CAST(:doc_id AS UUID)
            """),
            {"doc_id": doc_id, "status": status, "error_message": error_message},
        )


@celery_app.task(
    bind=True,
    autoretry_for=(ElasticsearchException,),
    retry_backoff=60,
    retry_kwargs={"max_retries": 5},
    retry_jitter=True
)
def index_to_es(self, doc_id: str, body: dict):
    try:
        es.index(index=ELASTICSEARCH_INDEX, id=doc_id, document=body, refresh="wait_for")
        update_db_status(doc_id, "INDEXED", None)
        return {"doc_id": doc_id, "status": "INDEXED"}
    except ElasticsearchException as exc:
        logger.error("Error indexando %s en Elasticsearch: %s", doc_id, str(exc))
        update_db_status(doc_id, "FAILED", "Error temporal en motor de búsqueda")
        raise self.retry(exc=exc)


@celery_app.task(bind=True, autoretry_for=(ElasticsearchException,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def process_document(self, doc_id: str, file_path: str, metadata: dict):
    try:
        ensure_index()
        update_db_status(doc_id, "PROCESSING", None)
        text_content = extract_pdf_text(file_path)
        file_hash = sha256_file(file_path)

        with engine.begin() as conn:
            row = conn.execute(
                text("""
                SELECT filename, mime_type, owner_id, current_version, metadata
                  FROM documents
                 WHERE id = CAST(:id AS UUID)
                """),
                {"id": doc_id},
            ).mappings().first()

            merged_metadata = dict(row["metadata"] or {})
            merged_metadata.update(metadata or {})
            merged_metadata["word_count"] = len(text_content.split())
            version = int(merged_metadata.get("version") or row["current_version"] or 1)

            conn.execute(
                text("""
                UPDATE documents
                   SET status = 'PROCESSING',
                       metadata = CAST(:metadata AS JSONB),
                       updated_at = NOW()
                 WHERE id = CAST(:id AS UUID)
                """),
                {"id": doc_id, "metadata": json.dumps(merged_metadata)},
            )

            conn.execute(
                text("""
                UPDATE document_versions
                   SET status = 'PROCESSING',
                       file_hash = :file_hash,
                       metadata = CAST(:metadata AS JSONB)
                 WHERE document_id = CAST(:document_id AS UUID) AND version_number = :version
                """),
                {
                    "document_id": doc_id,
                    "version": version,
                    "file_hash": file_hash,
                    "metadata": json.dumps(merged_metadata),
                },
            )

        body = {
            "document_id": doc_id,
            "filename": row["filename"],
            "content": text_content,
            "status": "INDEXED",
            "mime_type": row["mime_type"],
            "version": version,
            "owner_id": str(row["owner_id"]) if row["owner_id"] else None,
            "metadata": merged_metadata,
            "indexed_at": datetime.now(timezone.utc).isoformat(),
        }

        result = index_to_es.delay(doc_id, body)

        with engine.begin() as conn:
            conn.execute(
                text("""
                UPDATE document_versions
                   SET status = 'INDEXED',
                       file_hash = :file_hash,
                       metadata = CAST(:metadata AS JSONB)
                 WHERE document_id = CAST(:document_id AS UUID) AND version_number = :version
                """),
                {
                    "document_id": doc_id,
                    "version": version,
                    "file_hash": file_hash,
                    "metadata": json.dumps(merged_metadata),
                },
            )

        return {"status": "queued_for_index", "document_id": doc_id, "task_id": result.id}

    except ElasticsearchException as e:
        logger.error("Elasticsearch caído. Reintentando tarea para %s", doc_id)
        update_db_status(doc_id, "FAILED", "Buscador temporalmente fuera de servicio")
        raise self.retry(exc=e)


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def process_zip_package(self, zip_id: str, zip_path: str):
    extract_to = os.path.join("./storage/extracted", zip_id)
    os.makedirs(extract_to, exist_ok=True)

    processed = 0
    failed = 0

    try:
        validate_zip_limits(zip_path)

        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            safe_extract(zip_ref, extract_to)

        for root, _, files in os.walk(extract_to):
            for file_name in files:
                file_full_path = os.path.join(root, file_name)

                try:
                    process_document.delay(
                        str(uuid.uuid4()),
                        file_full_path,
                        {"zip_id": zip_id}
                    )
                    processed += 1
                except Exception as exc:
                    logger.error("Error encolando %s: %s", file_full_path, str(exc))
                    failed += 1

        return {
            "zip_id": zip_id,
            "files_queued": processed,
            "files_failed": failed
        }

    except Exception as e:
        logger.error("Error procesando paquete %s: %s", zip_id, str(e))
        raise

    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)

        if os.path.exists(extract_to):
            shutil.rmtree(extract_to, ignore_errors=True)


@celery_app.task(bind=True)
def rebuild_search_index(self):
    reindexed = 0
    skipped = 0

    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT id, filename, storage_path
                FROM documents
                WHERE status != 'FAILED'
            """)
        )

        for row in result:
            doc_id = str(row.id)
            path = row.storage_path

            if not os.path.exists(path):
                skipped += 1
                continue

            try:
                process_document.delay(
                    doc_id,
                    path,
                    {
                        "action": "reindex",
                        "version": 1
                    }
                )
                reindexed += 1
            except Exception:
                skipped += 1

    return {
        "status": "started",
        "documents_queued": reindexed,
        "documents_skipped": skipped
    }
