"""
Password hashing.

Uses bcrypt via passlib — salted, slow-by-design hashing, replacing the
earlier unsalted hashlib.sha256 scheme (flagged as a known limitation
when this was a single seeded demo user; no longer acceptable now that
real named users are involved).
"""

from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd_context.verify(plain, hashed)
    except ValueError:
        # Hash isn't a recognised bcrypt hash at all (e.g. a leftover
        # sha256 hex digest from before this migration) — treat as a
        # failed verification rather than raising.
        return False
