import os
from sqlalchemy import create_engine

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:password@localhost:5432/enterprise_docs"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
