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
    leader_user_id: Mapped[str | None] = mapped_column(SOURCE_ID, comment="部门负责人对应的飞书用户稳定标识")
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
    employee_type_id: Mapped[str | None] = mapped_column(SOURCE_ID, comment="员工类型枚举选项稳定标识")
    employee_type_name: Mapped[str | None] = mapped_column(String(255), comment="员工类型枚举当前展示值")
    job_title: Mapped[str | None] = mapped_column(String(255), comment="员工当前职务")
    leader_user_id: Mapped[str | None] = mapped_column(SOURCE_ID, comment="直属上级对应的飞书用户稳定标识")
    permission_role_id: Mapped[str | None] = mapped_column(SOURCE_ID, comment="权限角色自定义字段选项标识")
    permission_role_name: Mapped[str | None] = mapped_column(String(255), comment="权限角色自定义字段展示值")
    store_attribute_id: Mapped[str | None] = mapped_column(SOURCE_ID, comment="门店属性自定义字段选项标识")
    store_attribute_name: Mapped[str | None] = mapped_column(String(255), comment="门店属性自定义字段展示值")
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
    custom_attrs: Mapped[dict] = mapped_column(JSON, default=dict, comment="按飞书连接保存的自定义字段映射与选项定义")
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
    name: Mapped[str | None] = mapped_column(String(255), comment="同步任务名称")
    trigger_source: Mapped[str | None] = mapped_column(String(32), comment="任务触发来源")
    description: Mapped[str | None] = mapped_column(Text, comment="同步任务业务说明")
    root_department_id: Mapped[str | None] = mapped_column(SOURCE_ID)
    requested_by: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), index=True)
    phase: Mapped[str | None] = mapped_column(String(64))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    execution_count: Mapped[int] = mapped_column(Integer, default=0, comment="任务执行次数")
    retry_count: Mapped[int] = mapped_column(Integer, default=0, comment="任务重试次数")
    total_count: Mapped[int | None] = mapped_column(Integer, comment="任务对象总数，未知时为空")
    success_count: Mapped[int] = mapped_column(Integer, default=0, comment="任务成功对象数")
    failure_count: Mapped[int] = mapped_column(Integer, default=0, comment="任务失败对象数")
    lease_generation: Mapped[int] = mapped_column(Integer, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="任务开始时间")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="任务结束时间")
    __table_args__ = (Index("ix_sync_job_scope", "type", "root_department_id", "status"), TABLE_ARGS)


class SyncJobDetail(Base):
    __tablename__ = "sync_job_detail"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="任务明细自增标识")
    job_id: Mapped[str] = mapped_column(SOURCE_ID, ForeignKey("sync_job.id"), index=True)
    object_type: Mapped[str] = mapped_column(String(32), comment="任务对象类型")
    object_id: Mapped[str] = mapped_column(SOURCE_ID, comment="任务对象稳定标识")
    object_name: Mapped[str | None] = mapped_column(String(255), comment="任务对象名称快照")
    status: Mapped[str] = mapped_column(String(32), comment="对象处理状态")
    error_code: Mapped[str | None] = mapped_column(String(64), comment="对象错误编码")
    error_message: Mapped[str | None] = mapped_column(Text, comment="对象错误摘要")
    attempt: Mapped[int] = mapped_column(Integer, default=1, comment="对象处理尝试次数")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="对象处理开始时间")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="对象处理结束时间")
    change_log_id: Mapped[int | None] = mapped_column(BigInteger, comment="关联变更日志标识")
    __table_args__ = (UniqueConstraint("job_id", "object_type", "object_id", name="uq_sync_job_detail_object"), TABLE_ARGS)


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

class OperationReceipt(Base):
    """Agent 能力调用的一次操作回执。"""

    __tablename__ = "operation_receipt"
    operation_id: Mapped[str] = mapped_column(
        SOURCE_ID, primary_key=True, comment="Agent 能力调用的一次操作稳定标识"
    )
    idempotency_key: Mapped[str] = mapped_column(
        SOURCE_ID, nullable=False, comment="用于防止重复提交的幂等键"
    )
    capability: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="被调用的能力名称"
    )
    actor_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="调用主体类型，例如人工、Agent 或 CI"
    )
    actor_id: Mapped[str] = mapped_column(
        SOURCE_ID, nullable=False, comment="调用主体的稳定身份标识"
    )
    environment: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="操作运行环境，例如 production 或 test"
    )
    run_id: Mapped[str | None] = mapped_column(
        SOURCE_ID, comment="关联的 Agent 运行标识"
    )
    case_id: Mapped[str | None] = mapped_column(
        SOURCE_ID, comment="关联的 Evaluation 用例标识"
    )
    request_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="规范化请求内容的摘要"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="操作回执状态"
    )
    job_id: Mapped[str | None] = mapped_column(
        SOURCE_ID, comment="关联的同步任务标识"
    )
    before_epoch: Mapped[str] = mapped_column(
        SOURCE_ID, nullable=False, comment="请求开始时的数据集世代标识"
    )
    before_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="请求开始时的数据版本号"
    )
    committed_epoch: Mapped[str | None] = mapped_column(
        SOURCE_ID, comment="业务提交后的数据集世代标识"
    )
    committed_version: Mapped[int | None] = mapped_column(
        BigInteger, comment="业务提交后的数据版本号"
    )
    result_summary: Mapped[dict | None] = mapped_column(
        JSON, comment="脱敏后的结构化结果摘要"
    )
    error_code: Mapped[str | None] = mapped_column(
        String(64), comment="最近一次失败的稳定错误编码"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="操作回执创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="操作回执最近更新时间"
    )
    __table_args__ = (
        UniqueConstraint(
            "actor_id", "environment", "idempotency_key", name="uq_operation_receipt_idempotency"
        ),
        Index("ix_operation_receipt_capability", "capability"),
        Index("ix_operation_receipt_actor_id", "actor_id"),
        Index("ix_operation_receipt_environment", "environment"),
        Index("ix_operation_receipt_run_id", "run_id"),
        Index("ix_operation_receipt_case_id", "case_id"),
        Index("ix_operation_receipt_status", "status"),
        Index("ix_operation_receipt_job_id", "job_id"),
        Index("ix_operation_receipt_error_code", "error_code"),
        Index("ix_operation_receipt_created_at", "created_at"),
        {**TABLE_ARGS, "mysql_collate": "utf8mb4_0900_as_cs", "comment": "Agent 操作回执记录"},
    )
