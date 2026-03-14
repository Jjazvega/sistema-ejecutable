from jose import jwt

from auth import ALGORITHM, JWT_SECRET, create_access_token, hash_password, verify_password


def test_hash_and_verify_password():
    raw = "admin123"
    hashed = hash_password(raw)

    assert hashed != raw
    assert verify_password(raw, hashed) is True
    assert verify_password("wrong", hashed) is False


def test_create_access_token_contains_subject_and_role():
    token = create_access_token("user-123", "admin")
    payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])

    assert payload["sub"] == "user-123"
    assert payload["role"] == "admin"
    assert "exp" in payload
