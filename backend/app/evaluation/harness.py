"""真实官方 MCP → 内部 HTTP → MySQL 与生产同步 Worker 的可信生命周期。"""
import asyncio
import secrets
import threading
import time
from types import SimpleNamespace

import httpx
from fastapi import FastAPI
from mcp import Client
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.capabilities.observations import ObservationService
from app.capabilities.receipts import ReceiptRepository
from app.capabilities.router import router
from app.capabilities.service import OrganizationCapabilities
from app.config import Settings, get_settings
from app.dependencies import get_runtime
from app.mcp import policy
from app.mcp.client import CapabilityHttpClient
from app.mcp.models import AgentPrincipal
from app.mcp.server import build_server
from app.mcp.trace import Tracer
from app.persistence.models import WorkerLease, SyncJob, EventInbox
from app.persistence.read_service import SqlReadService
from app.persistence.repositories import SqlSyncJobRepository
from app.stores.service import StoreAdminService
from app.sync.collector import Collector
from app.sync.worker import Worker, utcnow
from .evidence import independent_reader
from .fake_feishu import FakeFeishu
from .fixtures import evaluation_database, seed_case


class SystemHarness:
    """每 case 新实例。超时保留此对象，调用 quiesce/close 可显式安全恢复。

    进程内 Python Worker 是能力隔离协议，不是抵御恶意 Python 反射的沙箱。
    官方内存 MCP transport 不验证网络入站认证；内部 HTTP 身份认证保持真实。
    """
    def __init__(self, database_url, case, context):
        self._url, self._case, self._context = database_url, case, context
        self._database = None
        self._sessions = None
        self._worker = None
        self._background = None
        self._bridge = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._bridge_failed = False
        self._background_failed = False
        self._loop = self._sdk = self._exit = None
        self._event_sequence = 0
        self._closed = False
        self.fake = FakeFeishu(**case.fixture['fake_feishu'])
        self._internal_token, self._inbound_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        password = make_url(database_url).password
        self.sensitive_values = tuple(v for v in (database_url, password, self._internal_token, self._inbound_token) if v)

    def open(self):
        self._database = evaluation_database(self._url)
        self._sessions = self._database.__enter__()
        seed_case(self._sessions, self._case)
        # 夹具事务已提交且 schedule 已关闭，才可启动生产 Worker。
        self._worker = Worker(self._sessions, Collector(self.fake), owner=self._context.run_id)
        if not self._worker.acquire(utcnow()): raise RuntimeError('EVALUATION_LEASE_UNAVAILABLE')
        self._background = threading.Thread(target=self._work, name='evaluation-sync', daemon=True)
        self._background.start()
        self._bridge = threading.Thread(target=self._serve, name='evaluation-mcp', daemon=True)
        self._bridge.start()
        if not self._ready.wait(5) or self._bridge_failed:
            raise RuntimeError('EVALUATION_MCP_START_FAILED')

    def _backend(self):
        from app.main import app as production_app
        backend = FastAPI(exception_handlers=dict(production_app.exception_handlers))
        backend.include_router(router)
        sessions = self._sessions
        reads = SqlReadService(sessions, secrets.token_urlsafe(32))
        capabilities = OrganizationCapabilities(sessions, reads, StoreAdminService(sessions),
            SqlSyncJobRepository(sessions), ReceiptRepository(), ObservationService(), environment='test')
        settings = Settings(_env_file=None, agent_service_token=self._internal_token, agent_environment='test')
        backend.dependency_overrides[get_settings] = lambda: settings
        backend.dependency_overrides[get_runtime] = lambda: SimpleNamespace(capabilities=capabilities)
        # get_agent_context 与 get_agent_capabilities 完整保留。
        return backend

    def _serve(self):
        async def serve():
            self._loop = asyncio.get_running_loop()
            self._exit = asyncio.Event()
            upstream = CapabilityHttpClient('http://evaluation-internal', SecretStr(self._internal_token),
                environment='test', transport=httpx.ASGITransport(app=self._backend()))
            principal = AgentPrincipal(actor_type='ci_agent', actor_id=self._context.actor_id,
                environment='test', run_id=self._context.run_id, case_id=self._context.case_id)
            server = build_server(upstream, policy, Tracer(), principal=principal,
                inbound_token=SecretStr(self._inbound_token), environment='test')
            try:
                async with Client(server, mode='legacy') as sdk:
                    self._sdk = sdk
                    self._ready.set()
                    await self._exit.wait()
            finally:
                await upstream.aclose()
        try:
            asyncio.run(serve())
        except Exception:
            self._bridge_failed = True
        finally:
            self._ready.set()

    def call_tool(self, name, arguments):
        if self._sdk is None or self._bridge_failed or self._closed:
            raise RuntimeError('EVALUATION_MCP_UNAVAILABLE')
        # Future 不设伪取消：调用与 ASGI 后台线程必须真正返回才算静止。
        future = asyncio.run_coroutine_threadsafe(self._sdk.call_tool(name, arguments), self._loop)
        return future.result()

    def _work(self):
        try:
            while not self._stop.is_set():
                self._inject_events()
                if not self._worker.step(): self._stop.wait(.02)
        except Exception:
            self._background_failed = True

    def _inject_events(self):
        pending = [e for e in self.fake.events if e['sequence'] > self._event_sequence]
        if not pending: return
        with self._sessions.begin() as db:
            for event in pending:
                db.add(EventInbox(event_id=f'{self._context.run_id}-{event["sequence"]}',
                    event_type=event['event_type'], object_id=event['identifier'], payload={},
                    status='queued', attempts=0, received_at=utcnow()))
        self._event_sequence = pending[-1]['sequence']

    def snapshot(self):
        with independent_reader(self._url) as reader:
            return reader.snapshot()

    def fake_writes(self):
        return {'count': self.fake.write_attempt_count, 'by_method': self.fake.write_attempts_by_method}

    def quiesce(self, timeout):
        self._stop.set()
        if self._background:
            self._background.join(timeout=max(0, timeout))
            if self._background.is_alive(): return False
        # 未被本 owner 完成的 running job 仍阻止清理，不凭过期租约推断静止。
        if self._sessions is not None:
            with self._sessions() as db:
                if db.scalar(select(SyncJob.id).where(SyncJob.status == 'running').limit(1)): return False
        return True

    def close(self):
        if self._closed: return
        if not self.quiesce(0): raise RuntimeError('EVALUATION_WORKER_NOT_QUIET')
        if self._bridge and self._bridge.is_alive():
            if self._loop and self._exit: self._loop.call_soon_threadsafe(self._exit.set)
            self._bridge.join(timeout=5)
            if self._bridge.is_alive(): raise RuntimeError('EVALUATION_MCP_NOT_QUIET')
        if self._sessions is not None and self._worker is not None:
            with self._sessions.begin() as db:
                lease = db.scalar(select(WorkerLease).where(WorkerLease.id == 1).with_for_update())
                if lease and lease.owner is not None:
                    if lease.owner != self._worker.owner or lease.generation != self._worker.generation:
                        raise RuntimeError('EVALUATION_LEASE_OWNER_CHANGED')
                    lease.owner, lease.expires_at = None, None
        if self._database is not None:
            self._database.__exit__(None, None, None)
            self._database = None
        self._closed = True
        if self._background_failed or self._bridge_failed:
            raise RuntimeError('EVALUATION_SYSTEM_FAILED')
