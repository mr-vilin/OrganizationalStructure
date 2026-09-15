# Task4 new files (no Git baseline)

## Dockerfile
```
FROM node:24-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/srv/backend:/srv
WORKDIR /srv/backend
COPY backend/ ./
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps .
COPY --from=frontend /build/dist /srv/frontend/dist
COPY deploy/ /srv/deploy/
RUN useradd --create-home --uid 10001 organization
USER organization
EXPOSE 8000
CMD ["python", "-m", "deploy.supervise"]

```

## compose.yaml
```
name: organization-directory
services:
  mysql:
    image: mysql:8.4
    restart: unless-stopped
    environment:
      MYSQL_DATABASE: organization
      MYSQL_USER: organization
      MYSQL_PASSWORD: ${MYSQL_PASSWORD:?请配置 MYSQL_PASSWORD}
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD:?请配置 MYSQL_ROOT_PASSWORD}
    command: ["--character-set-server=utf8mb4", "--collation-server=utf8mb4_0900_as_cs"]
    volumes:
      - mysql-data:/var/lib/mysql
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "127.0.0.1", "--silent"]
      interval: 5s
      timeout: 5s
      retries: 30
  migrate:
    build: .
    env_file: .env
    command: ["python", "-m", "alembic", "upgrade", "head"]
    depends_on:
      mysql:
        condition: service_healthy
  app:
    build: .
    env_file: .env
    restart: unless-stopped
    ports:
      - "127.0.0.1:${ORG_PORT:-8000}:8000"
    depends_on:
      migrate:
        condition: service_completed_successfully
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=4)"]
      interval: 15s
      timeout: 5s
      retries: 3
    stop_grace_period: 20s
volumes:
  mysql-data:

```

## .env.example
```
# 复制为 .env 后填写；不提交 .env。密码建议使用密码管理器生成的随机字母数字。
MYSQL_PASSWORD=
MYSQL_ROOT_PASSWORD=
# 与 MYSQL_PASSWORD 一致；若使用其他字符，URL 中需要百分号编码。
ORG_DATABASE_URL=mysql+pymysql://organization:REPLACE_PASSWORD@mysql:3306/organization?charset=utf8mb4
# 至少 32 字符随机值，禁止使用示例固定值。
ORG_SESSION_SECRET=
ORG_FEISHU_APP_ID=
ORG_FEISHU_APP_SECRET=
ORG_FEISHU_REDIRECT_URI=https://organization.example.com/admin/auth/callback
# 使用同一飞书应用下的 open_id，逗号分隔；不是姓名、手机号或工号。
ORG_INITIAL_ADMIN_OPEN_IDS=
ORG_PORT=8000

```

## .dockerignore
```
.git
.env
.env.*
.cache
.tools
**/.venv
**/node_modules
**/__pycache__
**/.pytest_cache
**/.pip-cache
**/*.egg-info
**/dist
backups
docs/ui

```

## deploy\asgi.py
```
"""生产同源入口；开发时前端由 Vite 提供。"""
from pathlib import Path

from app.main import app
from deploy.web import mount_frontend

mount_frontend(app, Path(__file__).resolve().parents[1] / 'frontend' / 'dist')

```

## deploy\compose.mysql-test.yaml
```
name: organization-tests
services:
  mysql:
    image: mysql:8.4
    environment:
      MYSQL_DATABASE: organization_test
      MYSQL_USER: organization_test
      MYSQL_PASSWORD: local-integration-only
      MYSQL_ROOT_PASSWORD: local-root-integration-only
    ports:
      - "127.0.0.1:13306:3306"
    command: ["--character-set-server=utf8mb4", "--collation-server=utf8mb4_0900_as_cs"]
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "127.0.0.1", "--silent"]
      interval: 5s
      timeout: 5s
      retries: 30
    tmpfs:
      - /var/lib/mysql

```

## deploy\README.md
```
# 部署说明

## 准备配置

在项目根目录将 `.env.example` 复制为 `.env`，填写随机数据库密码、至少 32 字符的会话密钥、飞书企业自建应用信息和同应用初始管理员 `open_id`。数据库 URL 的密码与 `MYSQL_PASSWORD` 一致。部署地址需要 HTTPS，登录回调固定为 `/admin/auth/callback`。

`.env` 不进入镜像或版本控制。MySQL 容器不映射公网端口，应用默认仅监听宿主机 `127.0.0.1:8000`，由部署方的 HTTPS 入口转发。

```powershell
Copy-Item -LiteralPath .env.example -Destination .env
# 用本机编辑器填好 .env 后执行：
docker compose up -d --build
docker compose ps
```

Compose 先等待 MySQL 就绪，再运行 Alembic 迁移，迁移成功后启动应用。应用进程监督器负责 HTTP、同步 worker 与飞书长连接三个独立进程；任一必要进程意外退出时终止其余进程，由容器重启恢复。长连接回调仅快速持久入箱，远程回查由 worker 执行；启动和断线恢复后安排全量核对。

## 飞书应用配置

1. 配置通讯录部门和员工基础资料读取权限、主部门字段权限、全员通讯录范围与管理员登录权限。
2. 订阅 `contact.department.created_v3`、`contact.department.updated_v3`、`contact.department.deleted_v3`、`contact.user.created_v3`、`contact.user.updated_v3`、`contact.user.deleted_v3` 六类事件。
3. 启用长连接；应用服务器允许出网访问飞书。登录重定向地址与部署 URL 保持一致。
4. 使用实际授权样本验证根节点、无部门人员、全部分页和 `orders` 主部门标识，不将 SDK 字段存在当作企业联调完成。
5. 首次登录必须属于受控初始白名单；禁止首个访问者自动成为管理员。

## 一致性备份

业务运行期间不执行数据库 DDL。下列命令示例在 Bash 环境执行；密码由容器内部环境传入，不打印秘密到日志：

```bash
mkdir -p backups
docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction --routines --triggers --events --set-gtid-purged=OFF --no-tablespaces organization' > backups/organization.sql
```

备份文件包含员工资料、会话哈希和审计信息，应使用受限存储并加密备份。配置与密钥独立备份；备份轮换由部署方的受控任务实施。

## 恢复演练

恢复操作覆盖目标库，只在明确选择的恢复环境执行，并先停止应用。先保留目标库现状备份，再导入备份文件。恢复后、重新开放读 API 前必须：

- 生成新的 `dataset_epoch`，禁止沿用备份中的旧世代。
- 撤销旧会话，重新核验管理员资格。
- 撤销备份恢复出的所有 API 凭据，避免已撤销凭据重新生效；重新生成并分发给下游。
- 全量核对飞书，并确认本地门店标记、编码保留与备注。
- 让下游按新世代重新拉取完整一致版本。

导入完成且应用已停止后，执行以下命令完成上述世代与凭据重置（不执行备份导入）：

```powershell
docker compose stop app
docker compose run --rm --no-deps app python -m deploy.recovery --application-stopped --actor "恢复责任人"
docker compose up -d app
```

该命令以单事务重置世代、隔离旧事件与未完成任务、撤销 OAuth state/会话/API 凭据，并写审计。门店资料与来源事实保留；初始化变为 pending，全量核对成功前读取数据返回 503。责任人参数必须填写实际标识。

如果备份中已无可用管理员，可在该命令中明确追加 `--admin-open-id ou_实际标识`，把经线下核验的同应用人员加入白名单并写审计。环境变量中的初始白名单只在首次初始化生效，重启不会自动恢复被删除的管理员。

真实 MySQL 恢复演练尚未执行，不将本说明视为恢复已验证。

## 数据库集成测试

`compose.mysql-test.yaml` 是可丢弃的独立本机测试环境，使用公开的测试密码和 tmpfs，不用于正式部署。用户提供数据库环境后执行真实 MySQL 事务、并发、迁移与恢复验证。

```

## deploy\recovery.py
```
"""备份导入后、所有应用进程停止期间重置安全与数据世代。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import delete, select, update

from app.config import get_settings
from app.persistence.database import create_mysql_engine, session_factory
from app.persistence.models import AdminAllowlist, AdminSession, ApiClient, ChangeLog, DatasetState, EventInbox, SyncJob, SystemSetting


def reset_restored_state(sessions, *, actor: str, admin_open_id: str | None = None) -> str:
    from app.persistence.models import OAuthState, WorkerLease
    now = datetime.now(timezone.utc)
    new_epoch = str(uuid4())
    with sessions.begin() as session:
        state = session.scalar(select(DatasetState).where(DatasetState.id == 1).with_for_update())
        if state is None:
            raise RuntimeError('数据库迁移尚未完成，无法重置恢复状态')
        old_epoch = state.dataset_epoch
        state.dataset_epoch = new_epoch
        state.data_version = 0
        state.initialization_status = 'pending'
        state.coverage_status = 'unknown'
        state.last_full_sync_at = None
        session.execute(update(AdminSession).where(AdminSession.revoked_at.is_(None)).values(revoked_at=now))
        session.execute(update(ApiClient).where(ApiClient.revoked_at.is_(None)).values(revoked_at=now))
        session.execute(update(SyncJob).where(SyncJob.status.in_(['queued', 'running'])).values(
            status='failed', error_code='RESTORE_REQUIRES_RECONCILIATION', error_detail=None,
            lease_generation=SyncJob.lease_generation + 1, lease_expires_at=None, updated_at=now))
        session.execute(update(EventInbox).where(EventInbox.status.in_(['queued', 'failed', 'running'])).values(status='ignored_restored'))
        session.execute(delete(OAuthState))
        session.execute(update(WorkerLease).values(owner=None, expires_at=None, generation=WorkerLease.generation + 1))
        session.execute(delete(SystemSetting).where(SystemSetting.key == 'reconcile_last_day'))
        if admin_open_id and session.get(AdminAllowlist, admin_open_id) is None:
            session.add(AdminAllowlist(open_id=admin_open_id, created_at=now))
            session.add(ChangeLog(object_type='admin_allowlist', object_id=admin_open_id, source='recovery',
                                  actor=actor, before_data=None, after_data={'open_id': admin_open_id}, committed_at=now))
        session.add(ChangeLog(object_type='dataset', object_id='1', source='recovery', actor=actor,
                              before_data={'dataset_epoch': old_epoch},
                              after_data={'dataset_epoch': new_epoch, 'initialization_status': 'pending',
                                          'sessions_revoked': True, 'api_clients_revoked': True}, committed_at=now))
    return new_epoch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--application-stopped', action='store_true', required=True,
                        help='确认 HTTP、worker 和长连接进程均已停止')
    parser.add_argument('--actor', required=True, help='恢复操作责任人标识，写入审计')
    parser.add_argument('--admin-open-id', help='可选：经线下核验的同应用恢复管理员 open_id，明确添加到白名单')
    args = parser.parse_args()
    if not args.actor.strip() or len(args.actor) > 255:
        parser.error('actor 必须是 1～255 个字符')
    if args.admin_open_id and (not args.admin_open_id.startswith('ou_') or len(args.admin_open_id) > 191):
        parser.error('恢复管理员必须是同应用的 ou_ 开头 open_id')
    settings = get_settings()
    if not settings.database_url:
        parser.error('未配置 ORG_DATABASE_URL')
    engine = create_mysql_engine(settings.database_url)
    try:
        epoch = reset_restored_state(session_factory(engine), actor=args.actor.strip(), admin_open_id=args.admin_open_id)
        print(f'恢复世代已重置：{epoch}；启动应用后执行全量核对，重新创建只读客户端凭据。')
    finally:
        engine.dispose()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

```

## deploy\supervise.py
```
"""单应用容器的进程监督：任何必要子进程退出都停止整个实例。"""
from __future__ import annotations

import logging
import signal
import subprocess
import sys
import time
from collections.abc import Sequence

log = logging.getLogger(__name__)


def supervise(commands: Sequence[Sequence[str]], poll_interval: float = 0.5) -> int:
    children: list[subprocess.Popen] = []
    try:
        for command in commands:
            children.append(subprocess.Popen(command))
        while children:
            for child in children:
                code = child.poll()
                if code is not None:
                    log.error('必要子进程退出，退出码：%s', code)
                    return code if code > 0 else 1
            time.sleep(poll_interval)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        deadline = time.monotonic() + 10
        for child in children:
            if child.poll() is None:
                try:
                    child.wait(timeout=max(0.1, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


def main() -> int:
    def shutdown(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, shutdown)
    logging.basicConfig(level=logging.INFO)
    return supervise([
        [sys.executable, '-m', 'uvicorn', 'deploy.asgi:app', '--host', '0.0.0.0', '--port', '8000', '--no-access-log'],
        [sys.executable, '-m', 'app.sync.worker'],
        [sys.executable, '-m', 'app.feishu.listener'],
    ])


if __name__ == '__main__':
    raise SystemExit(main())

```

## deploy\web.py
```
"""为管理前端提供同源静态资源，不将不存在的 API 伪装成网页。"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def mount_frontend(app: FastAPI, directory: Path) -> bool:
    index = directory / 'index.html'
    if not index.is_file():
        return False
    assets = directory / 'assets'
    if assets.is_dir():
        app.mount('/assets', StaticFiles(directory=assets), name='assets')

    @app.get('/{page:path}', include_in_schema=False)
    def frontend(page: str):
        if page.split('/')[0] in {'admin', 'api', 'health', 'assets', 'docs', 'redoc', 'openapi.json'}:
            raise HTTPException(404, detail={'code': 'NOT_FOUND', 'message': '接口不存在'})
        return FileResponse(index, headers={'Cache-Control': 'no-cache'})

    return True

```

## deploy\tests\test_supervise.py
```
"""验证应用子进程退出后，容器监督进程不会继续假装健康。"""
import subprocess
import sys
import unittest
from unittest.mock import patch

from deploy.supervise import supervise


class SupervisionTests(unittest.TestCase):
    def test_child_failure_stops_sibling_and_propagates_error(self):
        children = []
        actual_popen = subprocess.Popen

        def start(*args, **kwargs):
            process = actual_popen(*args, **kwargs)
            children.append(process)
            return process

        with patch('deploy.supervise.subprocess.Popen', side_effect=start):
            result = supervise([
                [sys.executable, '-c', 'import time; time.sleep(60)'],
                [sys.executable, '-c', 'raise SystemExit(7)'],
            ], poll_interval=0.02)
        self.assertEqual(result, 7)
        self.assertTrue(all(child.poll() is not None for child in children))

    def test_unexpected_clean_exit_is_failure(self):
        self.assertEqual(supervise([[sys.executable, '-c', 'pass']], poll_interval=0.02), 1)

    def test_startup_error_stops_already_started_child(self):
        children = []
        actual_popen = subprocess.Popen

        def start(*args, **kwargs):
            process = actual_popen(*args, **kwargs)
            children.append(process)
            return process

        with patch('deploy.supervise.subprocess.Popen', side_effect=start):
            with self.assertRaises(FileNotFoundError):
                supervise([
                    [sys.executable, '-c', 'import time; time.sleep(60)'],
                    ['organization-nonexistent-test-executable'],
                ], poll_interval=0.02)
        self.assertTrue(all(child.poll() is not None for child in children))


if __name__ == '__main__':
    unittest.main()

```

## deploy\tests\test_web.py
```
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from deploy.web import mount_frontend


class FrontendServingTests(unittest.TestCase):
    def test_spa_navigation_and_assets_work_but_unknown_api_stays_404(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'assets').mkdir()
            (root / 'index.html').write_text('<html>organization app</html>', encoding='utf-8')
            (root / 'assets' / 'app.js').write_text('export const app = true', encoding='utf-8')
            app = FastAPI()
            mount_frontend(app, root)
            with TestClient(app) as client:
                self.assertIn('organization app', client.get('/organization').text)
                self.assertEqual(client.get('/assets/app.js').status_code, 200)
                self.assertEqual(client.get('/api/v1/missing').status_code, 404)
                self.assertEqual(client.get('/admin/api/missing').status_code, 404)
                self.assertEqual(client.get('/health/missing').status_code, 404)

    def test_absent_build_does_not_claim_to_serve_app(self):
        app = FastAPI()
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(mount_frontend(app, Path(directory)))


if __name__ == '__main__':
    unittest.main()

```

## backend\tests\integration\conftest.py
```
"""真实 MySQL 测试夹具：数据库由部署者提供，各用例以外层事务回滚。"""
import os
import uuid

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.database import create_mysql_engine
from app.persistence.models import DatasetState


@pytest.fixture
def mysql_sessions():
    url = os.environ.get('ORG_TEST_DATABASE_URL')
    if not url:
        pytest.skip('未提供 ORG_TEST_DATABASE_URL；真实 MySQL 验收尚未执行')
    parsed = make_url(url)
    if parsed.drivername != 'mysql+pymysql' or not (parsed.database or '').endswith('_test'):
        pytest.fail('集成测试仅允许 mysql+pymysql 且数据库名以 _test 结尾的独立测试库')
    engine = create_mysql_engine(url)

    class IntegrationSession(Session):
        pass

    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            sessions = sessionmaker(bind=connection, class_=IntegrationSession, expire_on_commit=False, join_transaction_mode='create_savepoint')
            try:
                with sessions.begin() as db:
                    state = db.get(DatasetState, 1)
                    if state is None:
                        pytest.fail('请先对独立测试库执行 alembic upgrade head')
                    state.dataset_epoch = 'test-' + uuid.uuid4().hex
                    state.data_version = 1
                    state.initialization_status = 'complete'
                yield sessions
            finally:
                if transaction.is_active:
                    transaction.rollback()
    finally:
        engine.dispose()

```

## backend\tests\integration\test_mysql_recovery.py
```
"""恢复操作必须在真实 MySQL 上验证；缺少测试库时明确跳过。"""
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, select

from app.persistence.models import AdminAllowlist, AdminSession, ApiClient, ChangeLog, DatasetState
from deploy.recovery import reset_restored_state


def seed_credentials(sessions):
    token = uuid4().hex
    now = datetime(2026, 9, 15)
    with sessions.begin() as db:
        old_epoch = db.get(DatasetState, 1).dataset_epoch
        db.add(AdminSession(id=token, open_id='ou_restore', csrf_hash='x' * 64,
                            expires_at=now + timedelta(days=1)))
        db.add(ApiClient(id=token, name='恢复测试', secret_hash='x' * 64, created_at=now))
    return token, old_epoch


def test_restore_requires_new_epoch_initialization_and_new_credentials(mysql_sessions):
    token, old_epoch = seed_credentials(mysql_sessions)
    recovery_admin = 'ou_recovery_' + uuid4().hex
    new_epoch = reset_restored_state(mysql_sessions, actor='integration-restore', admin_open_id=recovery_admin)
    with mysql_sessions() as db:
        state = db.get(DatasetState, 1)
        assert state.dataset_epoch == new_epoch != old_epoch
        assert state.initialization_status == 'pending'
        assert state.data_version == 0
        assert state.coverage_status == 'unknown'
        assert state.last_full_sync_at is None
        assert db.get(AdminSession, token).revoked_at is not None
        assert db.get(ApiClient, token).revoked_at is not None
        assert db.get(AdminAllowlist, recovery_admin) is not None
        log = db.scalar(select(ChangeLog).where(ChangeLog.source == 'recovery', ChangeLog.object_type == 'dataset').order_by(ChangeLog.id.desc()))
        assert log.after_data['dataset_epoch'] == new_epoch


def test_recovery_audit_failure_rolls_back_epoch_and_revocations(mysql_sessions):
    token, old_epoch = seed_credentials(mysql_sessions)

    def fail_audit(db, _context, _instances):
        if any(isinstance(row, ChangeLog) and row.source == 'recovery' for row in db.new):
            raise RuntimeError('injected recovery audit failure')

    event.listen(mysql_sessions.class_, 'before_flush', fail_audit)
    try:
        with pytest.raises(RuntimeError, match='injected recovery audit failure'):
            reset_restored_state(mysql_sessions, actor='integration-restore')
    finally:
        event.remove(mysql_sessions.class_, 'before_flush', fail_audit)
    with mysql_sessions() as db:
        assert db.get(DatasetState, 1).dataset_epoch == old_epoch
        assert db.get(AdminSession, token).revoked_at is None
        assert db.get(ApiClient, token).revoked_at is None

```

## backend\tests\integration\test_mysql_transactions.py
```
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, select

from app.persistence.models import AdminSession, ApiClient, ChangeLog, DatasetState, Department, Employee, EmployeeDepartment, EmployeeStore, StoreProfile
from app.persistence.read_service import SqlReadService
from app.persistence.repositories import SqlIdentityRepository
from app.stores.domain import StorePatch
from app.stores.service import StoreAdminService


def test_admin_removal_preserves_revoked_session_and_denies_authentication(mysql_sessions):
    now = datetime(2026, 9, 15, 3, 0)
    identity = SqlIdentityRepository(mysql_sessions, 't' * 32)
    open_id = 'ou_test_' + uuid4().hex
    identity.add_admin(open_id, 'integration', now)
    issued = identity.create_session(open_id, 'csrf', now + timedelta(hours=1), now)
    assert identity.authenticate_session(issued.id, now).open_id == open_id
    identity.remove_admin(open_id, 'integration', now)
    assert identity.authenticate_session(issued.id, now) is None
    with mysql_sessions() as db:
        assert db.get(AdminSession, issued.id).revoked_at == now


def test_failed_rotation_rolls_back_revocation_and_audit(mysql_sessions):
    now = datetime(2026, 9, 15, 3, 0)
    identity = SqlIdentityRepository(mysql_sessions, 't' * 32)
    old, secret = identity.create_api_key('test-' + uuid4().hex, 'integration', now)

    def fail_replacement(db, _context, _instances):
        if any(isinstance(row, ApiClient) and row.id != old.id for row in db.new):
            raise RuntimeError('injected write failure')

    event.listen(mysql_sessions.class_, 'before_flush', fail_replacement)
    try:
        with pytest.raises(RuntimeError, match='injected write failure'):
            identity.rotate_api_key(old.id, 'integration', now)
    finally:
        event.remove(mysql_sessions.class_, 'before_flush', fail_replacement)
    assert identity.authenticate_api_key(old.id, secret) is not None
    with mysql_sessions() as db:
        logs = list(db.scalars(select(ChangeLog).where(ChangeLog.object_id == old.id)))
        assert len(logs) == 1
        assert secret not in str(logs[0].after_data)


def test_store_marking_and_cancellation_publish_projection_with_version(mysql_sessions):
    now = datetime(2026, 9, 15, 3, 0)
    prefix = 'test_' + uuid4().hex
    shop, kitchen, user = prefix + '_shop', prefix + '_kitchen', prefix + '_user'
    with mysql_sessions.begin() as db:
        db.add(Department(id=shop, feishu_department_id=shop, name='测试店', status='active', sync_quality='verified', is_virtual_root=False))
        db.flush()
        db.add(Department(id=kitchen, feishu_department_id=kitchen, parent_id=shop, name='后厨', status='active', sync_quality='verified', is_virtual_root=False))
        db.flush()
        db.add(Employee(id=user, feishu_user_id=user, name='测试员工', status='active', sync_quality='verified', primary_department_id=kitchen))
        db.flush()
        db.add(EmployeeDepartment(employee_id=user, department_id=kitchen, active=True, is_primary=True))
    stores = StoreAdminService(mysql_sessions)
    stores.apply([StorePatch(shop, True, prefix, '保留备注')], 1, 'integration', now)
    with mysql_sessions() as db:
        assert db.get(DatasetState, 1).data_version == 2
        assert db.get(EmployeeStore, (user, shop)).is_primary is True
    stores.apply([StorePatch(shop, False)], 2, 'integration', now)
    with mysql_sessions() as db:
        assert db.get(DatasetState, 1).data_version == 3
        assert db.get(StoreProfile, shop).store_code == prefix
        assert db.get(StoreProfile, shop).notes == '保留备注'
        assert db.get(EmployeeStore, (user, shop)) is None


def test_cross_page_version_change_is_rejected(mysql_sessions):
    reads = SqlReadService(mysql_sessions, 'c' * 32)
    prefix = 'test_' + uuid4().hex
    with mysql_sessions.begin() as db:
        db.add_all([Department(id=prefix + str(n), feishu_department_id=prefix + str(n), name='测试部门', status='active', sync_quality='verified', is_virtual_root=False) for n in range(2)])
    _, meta = reads.list_departments(limit=1)
    assert meta['next_cursor']
    with mysql_sessions.begin() as db:
        db.get(DatasetState, 1).data_version += 1
    with pytest.raises(RuntimeError, match='DATASET_CHANGED'):
        reads.list_departments(limit=1, cursor=meta['next_cursor'])

```
