from sqlalchemy import text
from db import engine
from auth import hash_password

schema = """
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

DO $$ BEGIN
    CREATE TYPE document_status AS ENUM ('PENDING','PROCESSING','INDEXED','FAILED');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role VARCHAR(20) NOT NULL CHECK (role IN ('admin','editor','viewer')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY,
    filename TEXT NOT NULL,
    current_version INTEGER NOT NULL DEFAULT 1,
    storage_path TEXT NOT NULL,
    mime_type VARCHAR(255) NOT NULL,
    file_size BIGINT NOT NULL,
    status document_status NOT NULL DEFAULT 'PENDING',
    owner_id UUID REFERENCES users(id),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_archived BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS document_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    storage_path TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    status document_status NOT NULL DEFAULT 'PENDING',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(document_id, version_number)
);

CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_documents_owner ON documents(owner_id);
CREATE INDEX IF NOT EXISTS idx_documents_metadata ON documents USING GIN(metadata);
"""

seed = [
    ("admin@example.com", "admin123", "admin"),
    ("editor@example.com", "editor123", "editor"),
    ("viewer@example.com", "viewer123", "viewer"),
]

with engine.begin() as conn:
    conn.execute(text(schema))
    for email, password, role in seed:
        conn.execute(
            text("""
            INSERT INTO users (email, password_hash, role)
            VALUES (:email, :password_hash, :role)
            ON CONFLICT (email) DO NOTHING
            """),
            {"email": email, "password_hash": hash_password(password), "role": role},
        )
