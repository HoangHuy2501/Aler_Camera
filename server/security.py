import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet

from config import env

PASSWORDS = PasswordHasher()


def password_matches(encoded: str, password: str) -> bool:
    try:
        return PASSWORDS.verify(encoded, password)
    except (InvalidHashError, VerificationError):
        return False


def token() -> str:
    return secrets.token_urlsafe(32)


def digest(value: str) -> bytes:
    return hashlib.sha256(value.encode()).digest()


def cipher() -> Fernet:
    key = env("CAMERA_SECRET_KEY")
    if not key:
        raise RuntimeError("Cần cấu hình CAMERA_SECRET_KEY.")
    return Fernet(key.encode())


def encrypt(value: str | None) -> bytes | None:
    return cipher().encrypt(value.encode()) if value else None


def decrypt(value: bytes | None) -> str:
    return cipher().decrypt(value).decode() if value else ""
