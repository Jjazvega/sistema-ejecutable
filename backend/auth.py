import os
from datetime import datetime, timedelta, timezone
from jose import jwt
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
JWT_SECRET = os.getenv("JWT_SECRET", "change-me")
ALGORITHM = "HS256"

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)

def create_access_token(subject: str, role: str) -> str:
    expires = datetime.now(timezone.utc) + timedelta(hours=12)
    payload = {"sub": subject, "role": role, "exp": expires}
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)
