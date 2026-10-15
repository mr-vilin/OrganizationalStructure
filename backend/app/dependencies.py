import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

from fastapi import Cookie, Depends, Header, HTTPException, Request

from .capabilities.contracts import AgentContext
from .capabilities.service import OrganizationCapabilities
from .capabilities.receipts import ReceiptRepository
from .capabilities.observations import ObservationService
from .stores.service import StoreAdminService
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
    capabilities: OrganizationCapabilities


@lru_cache
def get_runtime() -> Runtime | None:
    settings = get_settings()
    if not settings.database_url or not settings.session_secret:
        return None
    engine = create_mysql_engine(settings.database_url)
    sessions = session_factory(engine)
    pepper = settings.session_secret.get_secret_value()
    reads = SqlReadService(sessions, pepper)
    jobs = SqlSyncJobRepository(sessions)
    capabilities = OrganizationCapabilities(sessions, reads, StoreAdminService(sessions), jobs, ReceiptRepository(), ObservationService(), environment=settings.agent_environment)
    return Runtime(engine, sessions, reads, SqlIdentityRepository(sessions, pepper), jobs, capabilities)


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


def get_agent_context(request: Request, settings=Depends(get_settings)) -> AgentContext:
    """Only trusted sidecars holding the dedicated service token may assert identity."""
    def unauthorized():
        raise HTTPException(401, {"code": "AGENT_SERVICE_UNAUTHORIZED", "message": "内部能力服务身份无效"})

    names = ("authorization", "x-agent-actor-type", "x-agent-actor-id", "x-agent-environment",
             "x-agent-run-id", "x-agent-case-id", "x-agent-approved")
    if any(len(request.headers.getlist(name)) > 1 for name in names):
        unauthorized()
    secret = settings.agent_service_token.get_secret_value() if settings.agent_service_token else ""
    authorization = request.headers.get("authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if (not secret.strip() or not separator or scheme.lower() != "bearer" or not token
            or any(char.isspace() for char in token)
            or not hmac.compare_digest(token.encode("utf-8"), secret.encode("utf-8"))):
        unauthorized()
    actor_type = request.headers.get("x-agent-actor-type")
    actor_id = request.headers.get("x-agent-actor-id")
    environment = request.headers.get("x-agent-environment")
    approved = request.headers.get("x-agent-approved", "false")
    run_id = request.headers.get("x-agent-run-id")
    case_id = request.headers.get("x-agent-case-id")
    def valid_identifier(value):
        return bool(value) and len(value) <= 191 and all(char.isprintable() and not char.isspace() for char in value)
    if (actor_type not in {"human_agent", "ci_agent"} or not valid_identifier(actor_id)
            or environment != settings.agent_environment or approved not in {"true", "false"}
            or any(value is not None and not valid_identifier(value) for value in (run_id, case_id))):
        unauthorized()
    return AgentContext(actor_type, actor_id, environment, run_id, case_id, approved == "true")


def get_agent_capabilities(context: AgentContext = Depends(get_agent_context), runtime=Depends(get_runtime)):
    # Dependency order authenticates before Runtime construction or business data access.
    if runtime is None:
        raise HTTPException(503, {"code": "DATABASE_NOT_CONFIGURED", "message": "数据库尚未配置"})
    return runtime.capabilities
