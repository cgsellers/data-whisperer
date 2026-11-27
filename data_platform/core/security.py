"""Auth JWT simple + rate limit middleware"""
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from .config import settings
from .observability import get_logger
from .redis import check_rate_limit

logger = get_logger(__name__)
security = HTTPBearer(auto_error=False)
_security_dep = Depends(security)


async def verify_token(credentials: HTTPAuthorizationCredentials = _security_dep) -> dict:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    try:
        return jwt.decode(
            credentials.credentials,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM]
        )
    except JWTError as e:
        logger.warning("invalid_token", error=str(e))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from None


async def rate_limit_middleware(request: Request, call_next):
    """Rate limit por client_id (header) + source_id (query)"""
    client_id = request.headers.get("X-Client-ID", "anonymous")
    source_id = request.query_params.get("source_id", "default")
    identifier = f"{client_id}:{source_id}"

    allowed, remaining = await check_rate_limit(identifier, limit=100, window_seconds=60)

    response = await call_next(request)
    response.headers["X-RateLimit-Remaining"] = str(remaining)

    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded"
        )
    return response


def require_scope(required_scope: str):
    def checker(payload: dict = _security_dep):  # type: ignore[assignment]
        scopes = payload.get("scopes", [])
        if required_scope not in scopes and "admin" not in scopes:
            raise HTTPException(status_code=403, detail=f"Scope '{required_scope}' required")
        return payload
    return checker

