from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text as sql_text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


TABLE_ARGS = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_general_ci"}

def _table_args(comment: str) -> dict:
    return {**TABLE_ARGS, "comment": comment}
SOURCE_ID = String(191, collation="utf8mb4_bin")


class Base(DeclarativeBase):
    pass


class OAuthState(Base):
    __tablename__ = "oauth_state"
    digest: Mapped[str] = mapped_column(String(64), primary_key=True, comment="OAuth 状态摘要")
    expires_at: Mapped[datetime] = mapped_column(DateTime, comment="OAuth 状态过期时间")
    __table_args__ = _table_args("OAuth 登录状态记录")


class LoginIdentity(Base):
    __tablename__ = "login_identity"
    open_id: Mapped[str] = mapped_column(SOURCE_ID, primary_key=True, comment="飞书开放标识")
    user_id: Mapped[str] = mapped_column(SOURCE_ID, comment="飞书用户标识")
    tenant_key: Mapped[str] = mapped_column(SOURCE_ID, comment="飞书租户标识")
    __table_args__ = _table_args("飞书登录身份映射")


class WorkerLease(Base):
    __tablename__ = "worker_lease"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="worker 租约单例标识")
    owner: Mapped[str | None] = mapped_column(SOURCE_ID, comment="当前 worker 标识")
    generation: Mapped[int] = mapped_column(Integer, default=0, comment="租约世代号")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, comment="租约过期时间")
    __table_args__ = _table_args("同步 Worker 租约")


class PendingFact(Base):
    __tablename__ = 'pending_fact'
    object_type: Mapped[str] = mapped_column(String(32),primary_key=True, comment="待核实对象类型")
    source_id: Mapped[str] = mapped_column(SOURCE_ID,primary_key=True, comment="待核实来源标识")
    normalized_data: Mapped[dict] = mapped_column(JSON, comment="待核实规范化数据")
    error_code: Mapped[str] = mapped_column(String(64), comment="待核实错误编码")
    updated_at: Mapped[datetime] = mapped_column(DateTime, comment="待核实记录更新时间")
    __table_args__ = _table_args("待核实同步事实")


class DatasetState(Base):
    __tablename__ = "dataset_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="数据集状态单例标识")
    dataset_epoch: Mapped[str] = mapped_column(SOURCE_ID, comment="数据集世代标识")
    data_version: Mapped[int] = mapped_column(BigInteger, default=0, comment="已提交数据版本号")
    initialization_status: Mapped[str] = mapped_column(String(32), default="pending", comment="初始化状态")
    coverage_status: Mapped[str] = mapped_column(String(32), default="unknown", comment="通讯录覆盖状态")
    last_full_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="最近一次全量同步时间")
    __table_args__ = _table_args("组织数据集状态单例")


class SystemSetting(Base):
    __tablename__ = "system_setting"
    key: Mapped[str] = mapped_column(String(128, collation="utf8mb4_bin"), primary_key=True, comment="系统设置键名")
    value: Mapped[str] = mapped_column(Text, comment="系统设置值")
    __table_args__ = _table_args("系统设置")


class Department(Base):
    __tablename__ = "department"
    id: Mapped[str] = mapped_column(SOURCE_ID, primary_key=True, comment="内部部门稳定标识")
    feishu_department_id: Mapped[str] = mapped_column(SOURCE_ID, unique=True, comment="飞书部门标识")
    parent_id: Mapped[str | None] = mapped_column(SOURCE_ID, ForeignKey("department.id"), comment="父部门标识")
    name: Mapped[str] = mapped_column(String(255), comment="部门名称")
    leader_user_id: Mapped[str | None] = mapped_column(SOURCE_ID, comment="部门负责人用户标识")
    status: Mapped[str] = mapped_column(String(32), default="active", comment="部门状态")
    sync_quality: Mapped[str] = mapped_column(String(32), default="unknown", comment="部门同步质量")
    is_virtual_root: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否为虚拟根部门")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="最近一次从飞书看到的时间")
    __table_args__ = _table_args("飞书部门目录")


class Employee(Base):
    __tablename__ = "employee"
    id: Mapped[str] = mapped_column(SOURCE_ID, primary_key=True, comment="内部员工稳定标识")
    feishu_user_id: Mapped[str] = mapped_column(SOURCE_ID, unique=True, comment="飞书用户标识")
    open_id: Mapped[str | None] = mapped_column(SOURCE_ID, unique=True, comment="飞书用户开放标识")
    name: Mapped[str] = mapped_column(String(255), comment="员工姓名")
    employee_no: Mapped[str | None] = mapped_column(String(128), comment="员工工号")
    employee_type_id: Mapped[str | None] = mapped_column(SOURCE_ID, comment="员工类型枚举选项标识")
    employee_type_name: Mapped[str | None] = mapped_column(String(255), comment="员工类型展示名称")
    job_title: Mapped[str | None] = mapped_column(String(255), comment="员工职务")
    leader_user_id: Mapped[str | None] = mapped_column(SOURCE_ID, comment="直属上级用户标识")
    permission_role_id: Mapped[str | None] = mapped_column(SOURCE_ID, comment="权限角色选项标识")
    permission_role_name: Mapped[str | None] = mapped_column(String(255), comment="权限角色展示名称")
    store_attribute_id: Mapped[str | None] = mapped_column(SOURCE_ID, comment="门店属性选项标识")
    store_attribute_name: Mapped[str | None] = mapped_column(String(255), comment="门店属性展示名称")
    status: Mapped[str] = mapped_column(String(32), default="active", comment="员工状态")
    sync_quality: Mapped[str] = mapped_column(String(32), default="unknown", comment="员工同步质量")
    primary_department_id: Mapped[str | None] = mapped_column(SOURCE_ID, ForeignKey("department.id"), comment="主部门标识")
    primary_store_status: Mapped[str] = mapped_column(String(32), default="unknown", comment="主门店解析状态")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="最近一次从飞书看到的时间")
    __table_args__ = _table_args("飞书员工目录")


class EmployeeDepartment(Base):
    __tablename__ = "employee_department"
    employee_id: Mapped[str] = mapped_column(SOURCE_ID, ForeignKey("employee.id"), primary_key=True, comment="员工标识")
    department_id: Mapped[str] = mapped_column(SOURCE_ID, ForeignKey("department.id"), primary_key=True, comment="部门标识")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否为主部门关系")
    active: Mapped[bool] = mapped_column(Boolean, default=True, comment="关系是否有效")
    __table_args__ = _table_args("员工部门关系")


class StoreProfile(Base):
    __tablename__ = "store_profile"
    department_id: Mapped[str] = mapped_column(SOURCE_ID, ForeignKey("department.id"), primary_key=True, comment="门店对应部门标识")
    is_store: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否标记为门店")
    store_code: Mapped[str | None] = mapped_column(String(128, collation="utf8mb4_bin"), unique=True, comment="门店编码")
    notes: Mapped[str | None] = mapped_column(Text, comment="门店备注")
    __table_args__ = _table_args("门店资料")


class StoreCodeReservation(Base):
    __tablename__ = "store_code_reservation"
    store_code: Mapped[str] = mapped_column(String(128, collation="utf8mb4_bin"), primary_key=True, comment="预留门店编码")
    department_id: Mapped[str] = mapped_column(SOURCE_ID, ForeignKey("department.id"), comment="占用该编码的部门标识")
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="编码预留时间")
    __table_args__ = _table_args("门店编码预留")


class EmployeeStore(Base):
    __tablename__ = "employee_store"
    employee_id: Mapped[str] = mapped_column(SOURCE_ID, ForeignKey("employee.id"), primary_key=True, comment="员工标识")
    store_id: Mapped[str] = mapped_column(SOURCE_ID, ForeignKey("department.id"), primary_key=True, comment="门店部门标识")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否为主门店关系")
    path: Mapped[list] = mapped_column(JSON, comment="门店路径标识列表")
    __table_args__ = _table_args("员工门店关系")


class FeishuConnection(Base):
    __tablename__ = "feishu_connection"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="飞书连接单例标识")
    tenant_key: Mapped[str | None] = mapped_column(SOURCE_ID, unique=True, comment="飞书租户标识")
    app_id: Mapped[str] = mapped_column(SOURCE_ID, comment="飞书应用标识")
    status: Mapped[str] = mapped_column(String(32), comment="连接状态")
    coverage_status: Mapped[str] = mapped_column(String(32), default="unknown", comment="连接覆盖状态")
    custom_attrs: Mapped[dict] = mapped_column(JSON, default=dict, server_default=sql_text("('{}')"), comment="自定义字段映射与选项定义")
    __table_args__ = _table_args("飞书连接配置")


class AdminAllowlist(Base):
    __tablename__ = "admin_allowlist"
    open_id: Mapped[str] = mapped_column(SOURCE_ID, primary_key=True, comment="管理员飞书开放标识")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="加入白名单时间")
    __table_args__ = _table_args("管理员白名单")


class AdminSession(Base):
    __tablename__ = "admin_session"
    id: Mapped[str] = mapped_column(SOURCE_ID, primary_key=True, comment="管理员会话内部标识")
    token_digest: Mapped[str] = mapped_column(String(64, collation="utf8mb4_bin"), comment="管理员会话令牌 SHA-256 摘要")
    open_id: Mapped[str] = mapped_column(SOURCE_ID, index=True, comment="管理员飞书开放标识")
    csrf_hash: Mapped[str] = mapped_column(String(64), comment="CSRF 令牌摘要")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="会话过期时间")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="会话撤销时间")
    __table_args__ = (UniqueConstraint("token_digest", name="uq_admin_session_token_digest"), _table_args("管理员登录会话"))


class ApiClient(Base):
    __tablename__ = "api_client"
    id: Mapped[str] = mapped_column(SOURCE_ID, primary_key=True, comment="API 客户端标识")
    name: Mapped[str] = mapped_column(String(255), comment="API 客户端名称")
    secret_hash: Mapped[str] = mapped_column(String(255), comment="客户端密钥摘要")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="创建时间")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="撤销时间")
    __table_args__ = _table_args("只读 API 客户端")


class SyncJob(Base):
    __tablename__ = "sync_job"
    id: Mapped[str] = mapped_column(SOURCE_ID, primary_key=True, comment="同步任务标识")
    type: Mapped[str] = mapped_column(String(32), comment="同步任务类型")
    name: Mapped[str | None] = mapped_column(String(255), comment="同步任务名称")
    trigger_source: Mapped[str | None] = mapped_column(String(32), comment="任务触发来源")
    description: Mapped[str | None] = mapped_column(Text, comment="同步任务说明")
    root_department_id: Mapped[str | None] = mapped_column(SOURCE_ID, comment="子树同步根部门标识")
    requested_by: Mapped[str] = mapped_column(String(255), comment="任务请求方")
    status: Mapped[str] = mapped_column(String(32), index=True, comment="任务状态")
    phase: Mapped[str | None] = mapped_column(String(64), comment="任务阶段")
    attempt: Mapped[int] = mapped_column(Integer, default=1, comment="任务尝试次数")
    execution_count: Mapped[int] = mapped_column(Integer, default=0, server_default=sql_text("0"), comment="任务执行次数")
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default=sql_text("0"), comment="任务重试次数")
    total_count: Mapped[int | None] = mapped_column(Integer, comment="任务对象总数")
    success_count: Mapped[int] = mapped_column(Integer, default=0, server_default=sql_text("0"), comment="任务成功对象数")
    failure_count: Mapped[int] = mapped_column(Integer, default=0, server_default=sql_text("0"), comment="任务失败对象数")
    lease_generation: Mapped[int] = mapped_column(Integer, default=0, comment="任务租约世代号")
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="任务租约过期时间")
    error_code: Mapped[str | None] = mapped_column(String(64), comment="任务错误编码")
    error_detail: Mapped[str | None] = mapped_column(Text, comment="任务错误详情")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="任务创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="任务更新时间")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="任务开始时间")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="任务结束时间")
    __table_args__ = (Index("ix_sync_job_scope", "type", "root_department_id", "status"), _table_args("同步任务"))


class SyncJobDetail(Base):
    __tablename__ = "sync_job_detail"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="任务明细自增标识")
    job_id: Mapped[str] = mapped_column(SOURCE_ID, ForeignKey("sync_job.id"), index=True, comment="所属同步任务标识")
    object_type: Mapped[str] = mapped_column(String(32), comment="任务对象类型")
    object_id: Mapped[str] = mapped_column(SOURCE_ID, comment="任务对象标识")
    object_name: Mapped[str | None] = mapped_column(String(255), comment="任务对象名称快照")
    status: Mapped[str] = mapped_column(String(32), comment="对象处理状态")
    error_code: Mapped[str | None] = mapped_column(String(64), comment="对象错误编码")
    error_message: Mapped[str | None] = mapped_column(Text, comment="对象错误摘要")
    attempt: Mapped[int] = mapped_column(Integer, default=1, comment="对象处理尝试次数")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="对象处理开始时间")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="对象处理结束时间")
    change_log_id: Mapped[int | None] = mapped_column(BigInteger, comment="关联变更日志标识")
    __table_args__ = (UniqueConstraint("job_id", "object_type", "object_id", name="uq_sync_job_detail_object"), _table_args("同步任务明细"))


class EventInbox(Base):
    __tablename__ = "event_inbox"
    event_id: Mapped[str] = mapped_column(SOURCE_ID, primary_key=True, comment="飞书事件标识")
    event_type: Mapped[str] = mapped_column(String(128), comment="飞书事件类型")
    object_id: Mapped[str | None] = mapped_column(SOURCE_ID, comment="事件对象标识")
    payload: Mapped[dict] = mapped_column(JSON, comment="事件原始载荷")
    status: Mapped[str] = mapped_column(String(32), index=True, comment="事件处理状态")
    attempts: Mapped[int] = mapped_column(Integer, default=0, comment="事件处理尝试次数")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="事件接收时间")
    __table_args__ = _table_args("飞书事件收件箱")


class SyncStaging(Base):
    __tablename__ = "sync_staging"
    job_id: Mapped[str] = mapped_column(SOURCE_ID, ForeignKey("sync_job.id"), primary_key=True, comment="所属同步任务标识")
    object_type: Mapped[str] = mapped_column(String(32), primary_key=True, comment="暂存对象类型")
    source_id: Mapped[str] = mapped_column(SOURCE_ID, primary_key=True, comment="来源对象标识")
    normalized_data: Mapped[dict] = mapped_column(JSON, comment="规范化对象数据")
    __table_args__ = _table_args("同步暂存数据")


class ChangeLog(Base):
    __tablename__ = "change_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="变更日志自增标识")
    object_type: Mapped[str] = mapped_column(String(32), comment="变更对象类型")
    object_id: Mapped[str] = mapped_column(SOURCE_ID, comment="变更对象标识")
    source: Mapped[str] = mapped_column(String(32), comment="变更来源")
    actor: Mapped[str | None] = mapped_column(String(255), comment="操作主体")
    job_id: Mapped[str | None] = mapped_column(SOURCE_ID, comment="关联同步任务标识")
    before_data: Mapped[dict | None] = mapped_column(JSON, comment="变更前数据")
    after_data: Mapped[dict | None] = mapped_column(JSON, comment="变更后数据")
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, comment="变更提交时间")
    __table_args__ = _table_args("数据变更审计日志")
