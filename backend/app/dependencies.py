import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

from fastapi import Cookie, Depends, Header, HTTPException, Request

from .config import get_settings
from .persistence.database import create_mysql_engine, session_factory
from .persistence.read_service import SqlReadService
from .persistence.repositories import SqlIdentityRepository, SqlSyncJobRepository
from .services import UninitializedReadService


@dataclass(frozen=True)
class Runtime:
    engine: object
    sessions: object
    reads: SqlReadService
    identities: SqlIdentityRepository
    jobs: SqlSyncJobRepository


@lru_cache
def get_runtime() -> Runtime | None:
    settings = get_settings()
    if not settings.database_url or not settings.session_secret:
        return None
    engine = create_mysql_engine(settings.database_url)
    sessions = session_factory(engine)
    pepper = settings.session_secret.get_secret_value()
    return Runtime(engine, sessions, SqlReadService(sessions, pepper), SqlIdentityRepository(sessions, pepper), SqlSyncJobRepository(sessions))


def get_read_service():
    runtime = get_runtime()
    return runtime.reads if runtime else UninitializedReadService()


def get_public_identity(authorization: str | None = Header(default=None), runtime: Runtime | None = Depends(get_runtime)):
    if runtime is not None and authorization and authorization.startswith("Bearer "):
        try:
            client_id, secret = authorization[7:].split(".", 1)
        except ValueError:
            pass
        else:
            identity = runtime.identities.authenticate_api_key(client_id, secret)
            if identity is not None:
                return identity
    raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED", "message": "只读 API 凭据无效"})


def get_admin_identity(org_session: str | None = Cookie(default=None), runtime: Runtime | None = Depends(get_runtime)):
    if runtime is not None and org_session:
        identity = runtime.identities.authenticate_session(org_session, datetime.now(timezone.utc).replace(tzinfo=None))
        if identity is not None:
            return identity
    raise HTTPException(status_code=401, detail={"code": "ADMIN_SESSION_REQUIRED", "message": "需要管理员会话"})


def require_admin_write(identity=Depends(get_admin_identity), x_csrf_token: str | None = Header(default=None), settings=Depends(get_settings)):
    secret = settings.session_secret.get_secret_value() if settings.session_secret else ""
    digest = hmac.new(secret.encode(), (x_csrf_token or "").encode(), hashlib.sha256).hexdigest()
    if not x_csrf_token or not hmac.compare_digest(identity.csrf_hash, digest):
        raise HTTPException(status_code=403, detail={"code": "CSRF_REQUIRED", "message": "缺少 CSRF 令牌"})
    return identity, x_csrf_token
