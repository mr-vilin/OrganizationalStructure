import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from sqlalchemy import delete, select
from app.persistence.models import OAuthState, LoginIdentity, AdminAllowlist, AdminSession, Employee, ChangeLog


class OAuthService:
    def __init__(self, sessions, settings, api):
        from app.feishu.binding import bind_connection
        bind_connection(sessions,settings.feishu_app_id,settings.feishu_tenant_key)
        self.sessions, self.settings, self.api = sessions, settings, api

    def begin(self):
        state = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self.sessions.begin() as db:
            db.execute(delete(OAuthState).where(OAuthState.expires_at < now))
            db.add(OAuthState(digest=hashlib.sha256(state.encode()).hexdigest(), expires_at=now + timedelta(minutes=10)))
        return state

    def complete(self, state, cookie, code):
        if not state or not cookie or not hmac.compare_digest(state, cookie):
            raise ValueError('OAUTH_STATE_INVALID')
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self.sessions.begin() as db:
            record = db.scalar(select(OAuthState).where(OAuthState.digest == hashlib.sha256(state.encode()).hexdigest()).with_for_update())
            if not record or record.expires_at <= now:
                raise ValueError('OAUTH_STATE_INVALID')
            db.delete(record)
        identity = self.api.login(code)
        if identity.get('tenant_key') != self.settings.feishu_tenant_key or not identity.get('open_id') or not identity.get('user_id'):
            raise ValueError('OAUTH_IDENTITY_MISMATCH')
        csrf = secrets.token_urlsafe(32)
        failure = None
        with self.sessions.begin() as db:
            if db.scalar(select(AdminAllowlist).where(AdminAllowlist.open_id == identity['open_id']).with_for_update()) is None:
                raise ValueError('ADMIN_NOT_ALLOWED')
            existing = db.scalar(select(LoginIdentity).where(LoginIdentity.open_id==identity['open_id']).with_for_update())
            employee = db.scalar(select(Employee).where(Employee.feishu_user_id==identity['user_id']).with_for_update())
            if existing and (existing.user_id!=identity['user_id'] or existing.tenant_key!=identity['tenant_key']):
                failure='LOGIN_IDENTITY_MISMATCH'
            elif employee and employee.status=='inactive':
                failure='EMPLOYEE_INACTIVE'
            if failure:
                db.add(ChangeLog(object_type='security',object_id=identity['open_id'],source='oauth',actor=None,before_data=None,after_data={'error_code':failure},committed_at=now))
            else:
                if existing is None: db.add(LoginIdentity(open_id=identity['open_id'],user_id=identity['user_id'],tenant_key=identity['tenant_key']))
                session_token = secrets.token_urlsafe(32)
                session = AdminSession(
                    id=secrets.token_urlsafe(16),
                    token_digest=hashlib.sha256(session_token.encode()).hexdigest(),
                    open_id=identity['open_id'],
                    csrf_hash=hmac.new(self.settings.session_secret.get_secret_value().encode(), csrf.encode(), hashlib.sha256).hexdigest(),
                    expires_at=now+timedelta(hours=12),
                )
                db.add(session)
        # 先提交安全事件，再拒绝；不要随业务异常回滚审计。
        if failure: raise ValueError(failure)
        return session, csrf, session_token
