from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.config import settings

_bearer = HTTPBearer(auto_error=False)


class TokenPayload(BaseModel):
    user_id: int
    username: str


def create_access_token(user_id: int, username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        hours=settings.AUTH_TOKEN_EXPIRE_HOURS
    )
    payload = {
        "sub": str(user_id),
        "username": username,
        "exp": expire,
    }
    return jwt.encode(payload, settings.AUTH_SECRET_KEY, algorithm="HS256")


def decode_access_token(token: str) -> TokenPayload:
    try:
        payload = jwt.decode(
            token, settings.AUTH_SECRET_KEY, algorithms=["HS256"]
        )
        user_id = int(payload["sub"])
        username = payload.get("username", "")
        return TokenPayload(user_id=user_id, username=username)
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
        ) from exc


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> TokenPayload:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )
    return decode_access_token(credentials.credentials)


def assert_user_matches_token(
    request_user_id: int, token_user: TokenPayload
) -> None:
    if request_user_id != token_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user_id does not match authenticated user",
        )
