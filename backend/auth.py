"""
Authentication for GRADEOPS: password hashing (bcrypt) and JWT-based
sessions. Uses bcrypt directly rather than passlib -- passlib's bcrypt
wrapper has a known compatibility issue with bcrypt>=4.1, so calling bcrypt
directly avoids that footgun entirely.
"""

import os
import bcrypt
import jwt
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, Header
from dotenv import load_dotenv
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

import database

load_dotenv()

JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24 * 7  # 1 week
bearer_scheme = HTTPBearer()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(user_id: int) -> str:
    if not JWT_SECRET_KEY:
        raise EnvironmentError(
            "JWT_SECRET_KEY not set\n"

        )
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> int:
    """Returns the user_id encoded in a valid token, or raises HTTPException."""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return int(payload["sub"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired, please log in again.")
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid authentication token.")


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):

    user_id = decode_access_token(credentials.credentials)

    user = database.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists.")

    return user