from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


TABLE_ARGS = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}
SOURCE_ID = String(191, collation="utf8mb4_bin")


class Base(DeclarativeBase):
    pass


class OAuthState(Base):
    __tablename__ = "oauth_state"
    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    __table_args__ = TABLE_ARGS


class LoginIdentity(Base):
    __tablename__ = "login_identity"
    open_id: Mapped[str] = mapped_column(SOURCE_ID, primary_key=True)
    user_id: Mapped[str] = mapped_column(SOURCE_ID)
    tenant_key: Mapped[str] = mapped_column(SOURCE_ID)
    __table_args__ = TABLE_ARGS


class WorkerLease(Base):
    __tablename__ = "worker_lease"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner: Mapped[str | None] = mapped_column(SOURCE_ID)
    generation: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = TABLE_ARGS


class PendingFact(Base):
    __tablename__ = 'pending_fact'
    object_type: Mapped[str] = mapped_column(String(32),primary_key=True)
    source_id: Mapped[str] = mapped_column(SOURCE_ID,primary_key=True)
    normalized_data: Mapped[dict] = mapped_column(JSON)
    error_code: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    __table_args__ = TABLE_ARGS


class DatasetState(Base):
    __tablename__ = "dataset_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_epoch: Mapped[str] = mapped_column(SOURCE_ID)
    data_version: Mapped[int] = mapped_column(BigInteger, default=0)
    initialization_status: Mapped[str] = mapped_column(String(32), default="pending")
    coverage_status: Mapped[str] = mapped_column(String(32), default="unknown")
    last_full_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = TABLE_ARGS


class SystemSetting(Base):
    __tablename__ = "system_setting"
    key: Mapped[str] = mapped_column(String(128, collation="utf8mb4_bin"), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    __table_args__ = TABLE_ARGS


class Department(Base):
    __tablename__ = "department"
    id: Mapped[str] = mapped_column(SOURCE_ID, primary_key=True)
    feishu_department_id: Mapped[str] = mapped_column(SOURCE_ID, unique=True)
    parent_id: Mapped[str | None] = mapped_column(SOURCE_ID, ForeignKey("department.id"))
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="active")
    sync_quality: Mapped[str] = mapped_column(String(32), default="unknown")
    is_virtual_root: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = TABLE_ARGS


class Employee(Base):
    __tablename__ = "employee"
    id: Mapped[str] = mapped_column(SOURCE_ID, primary_key=True)
    feishu_user_id: Mapped[str] = mapped_column(SOURCE_ID, unique=True)
    open_id: Mapped[str | None] = mapped_column(SOURCE_ID, unique=True)
    name: Mapped[str] = mapped_column(String(255))
    employee_no: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="active")
    sync_quality: Mapped[str] = mapped_column(String(32), default="unknown")
    primary_department_id: Mapped[str | None] = mapped_column(SOURCE_ID, ForeignKey("department.id"))
    primary_store_status: Mapped[str] = mapped_column(String(32), default="unknown")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = TABLE_ARGS


class EmployeeDepartment(Base):
    __tablename__ = "employee_department"
    employee_id: Mapped[str] = mapped_column(SOURCE_ID, ForeignKey("employee.id"), primary_key=True)
    department_id: Mapped[str] = mapped_column(SOURCE_ID, ForeignKey("department.id"), primary_key=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = TABLE_ARGS


class StoreProfile(Base):
    __tablename__ = "store_profile"
    department_id: Mapped[str] = mapped_column(SOURCE_ID, ForeignKey("department.id"), primary_key=True)
    is_store: Mapped[bool] = mapped_column(Boolean, default=False)
    store_code: Mapped[str | None] = mapped_column(String(128, collation="utf8mb4_bin"), unique=True)
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = TABLE_ARGS


class StoreCodeReservation(Base):
    __tablename__ = "store_code_reservation"
    store_code: Mapped[str] = mapped_column(String(128, collation="utf8mb4_bin"), primary_key=True)
    department_id: Mapped[str] = mapped_column(SOURCE_ID, ForeignKey("department.id"))
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = TABLE_ARGS


class EmployeeStore(Base):
    __tablename__ = "employee_store"
    employee_id: Mapped[str] = mapped_column(SOURCE_ID, ForeignKey("employee.id"), primary_key=True)
    store_id: Mapped[str] = mapped_column(SOURCE_ID, ForeignKey("department.id"), primary_key=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    path: Mapped[list] = mapped_column(JSON)
    __table_args__ = TABLE_ARGS


class FeishuConnection(Base):
    __tablename__ = "feishu_connection"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_key: Mapped[str | None] = mapped_column(SOURCE_ID, unique=True)
    app_id: Mapped[str] = mapped_column(SOURCE_ID)
    status: Mapped[str] = mapped_column(String(32))
    coverage_status: Mapped[str] = mapped_column(String(32), default="unknown")
    __table_args__ = TABLE_ARGS


class AdminAllowlist(Base):
    __tablename__ = "admin_allowlist"
    open_id: Mapped[str] = mapped_column(SOURCE_ID, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = TABLE_ARGS


class AdminSession(Base):
    __tablename__ = "admin_session"
    id: Mapped[str] = mapped_column(SOURCE_ID, primary_key=True)
    open_id: Mapped[str] = mapped_column(SOURCE_ID, index=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = TABLE_ARGS


class ApiClient(Base):
    __tablename__ = "api_client"
    id: Mapped[str] = mapped_column(SOURCE_ID, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    secret_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = TABLE_ARGS


class SyncJob(Base):
    __tablename__ = "sync_job"
    id: Mapped[str] = mapped_column(SOURCE_ID, primary_key=True)
    type: Mapped[str] = mapped_column(String(32))
    root_department_id: Mapped[str | None] = mapped_column(SOURCE_ID)
    requested_by: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), index=True)
    phase: Mapped[str | None] = mapped_column(String(64))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    lease_generation: Mapped[int] = mapped_column(Integer, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_sync_job_scope", "type", "root_department_id", "status"), TABLE_ARGS)


class EventInbox(Base):
    __tablename__ = "event_inbox"
    event_id: Mapped[str] = mapped_column(SOURCE_ID, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(128))
    object_id: Mapped[str | None] = mapped_column(SOURCE_ID)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = TABLE_ARGS


class SyncStaging(Base):
    __tablename__ = "sync_staging"
    job_id: Mapped[str] = mapped_column(SOURCE_ID, ForeignKey("sync_job.id"), primary_key=True)
    object_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_id: Mapped[str] = mapped_column(SOURCE_ID, primary_key=True)
    normalized_data: Mapped[dict] = mapped_column(JSON)
    __table_args__ = TABLE_ARGS


class ChangeLog(Base):
    __tablename__ = "change_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    object_type: Mapped[str] = mapped_column(String(32))
    object_id: Mapped[str] = mapped_column(SOURCE_ID)
    source: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str | None] = mapped_column(String(255))
    job_id: Mapped[str | None] = mapped_column(SOURCE_ID)
    before_data: Mapped[dict | None] = mapped_column(JSON)
    after_data: Mapped[dict | None] = mapped_column(JSON)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    __table_args__ = TABLE_ARGS
