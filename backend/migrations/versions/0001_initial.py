"""创建组织目录首版冻结表结构。"""

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


T = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}
SID = sa.String(191, collation="utf8mb4_bin")


def upgrade():
    op.create_table("dataset_state", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("dataset_epoch", SID, nullable=False), sa.Column("data_version", sa.BigInteger(), nullable=False), sa.Column("initialization_status", sa.String(32), nullable=False), sa.Column("coverage_status", sa.String(32), nullable=False), sa.Column("last_full_sync_at", sa.DateTime()), **T)
    op.create_table("system_setting", sa.Column("key", sa.String(128, collation="utf8mb4_bin"), primary_key=True), sa.Column("value", sa.Text(), nullable=False), **T)
    op.create_table("department", sa.Column("id", SID, primary_key=True), sa.Column("feishu_department_id", SID, nullable=False, unique=True), sa.Column("parent_id", SID, sa.ForeignKey("department.id")), sa.Column("name", sa.String(255), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("sync_quality", sa.String(32), nullable=False), sa.Column("is_virtual_root", sa.Boolean(), nullable=False), sa.Column("last_seen_at", sa.DateTime()), **T)
    op.create_table("feishu_connection", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("tenant_key", SID, unique=True), sa.Column("app_id", SID, nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("coverage_status", sa.String(32), nullable=False), **T)
    op.create_table("admin_allowlist", sa.Column("open_id", SID, primary_key=True), sa.Column("created_at", sa.DateTime(), nullable=False), **T)
    op.create_table("admin_session", sa.Column("id", SID, primary_key=True), sa.Column("open_id", SID, nullable=False), sa.Column("csrf_hash", sa.String(64), nullable=False), sa.Column("expires_at", sa.DateTime(), nullable=False), sa.Column("revoked_at", sa.DateTime()), **T)
    op.create_index("ix_admin_session_open_id", "admin_session", ["open_id"])
    op.create_table("api_client", sa.Column("id", SID, primary_key=True), sa.Column("name", sa.String(255), nullable=False), sa.Column("secret_hash", sa.String(255), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("revoked_at", sa.DateTime()), **T)
    op.create_table("sync_job", sa.Column("id", SID, primary_key=True), sa.Column("type", sa.String(32), nullable=False), sa.Column("root_department_id", SID), sa.Column("requested_by", sa.String(255), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("phase", sa.String(64)), sa.Column("attempt", sa.Integer(), nullable=False), sa.Column("lease_generation", sa.Integer(), nullable=False), sa.Column("lease_expires_at", sa.DateTime()), sa.Column("error_code", sa.String(64)), sa.Column("error_detail", sa.Text()), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False), **T)
    op.create_index("ix_sync_job_status", "sync_job", ["status"])
    op.create_index("ix_sync_job_scope", "sync_job", ["type", "root_department_id", "status"])
    op.create_table("event_inbox", sa.Column("event_id", SID, primary_key=True), sa.Column("event_type", sa.String(128), nullable=False), sa.Column("object_id", SID), sa.Column("payload", sa.JSON(), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("received_at", sa.DateTime(), nullable=False), **T)
    op.create_index("ix_event_inbox_status", "event_inbox", ["status"])
    op.create_table("change_log", sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True), sa.Column("object_type", sa.String(32), nullable=False), sa.Column("object_id", SID, nullable=False), sa.Column("source", sa.String(32), nullable=False), sa.Column("actor", sa.String(255)), sa.Column("job_id", SID), sa.Column("before_data", sa.JSON()), sa.Column("after_data", sa.JSON()), sa.Column("committed_at", sa.DateTime(), nullable=False), **T)
    op.create_index("ix_change_log_committed_at", "change_log", ["committed_at"])
    op.create_table("employee", sa.Column("id", SID, primary_key=True), sa.Column("feishu_user_id", SID, nullable=False, unique=True), sa.Column("open_id", SID, unique=True), sa.Column("name", sa.String(255), nullable=False), sa.Column("employee_no", sa.String(128)), sa.Column("status", sa.String(32), nullable=False), sa.Column("sync_quality", sa.String(32), nullable=False), sa.Column("primary_department_id", SID, sa.ForeignKey("department.id")), sa.Column("primary_store_status", sa.String(32), nullable=False), sa.Column("last_seen_at", sa.DateTime()), **T)
    op.create_table("store_profile", sa.Column("department_id", SID, sa.ForeignKey("department.id"), primary_key=True), sa.Column("is_store", sa.Boolean(), nullable=False), sa.Column("store_code", sa.String(128, collation="utf8mb4_bin"), unique=True), sa.Column("notes", sa.Text()), **T)
    op.create_table("store_code_reservation", sa.Column("store_code", sa.String(128, collation="utf8mb4_bin"), primary_key=True), sa.Column("department_id", SID, sa.ForeignKey("department.id"), nullable=False), sa.Column("reserved_at", sa.DateTime(), nullable=False), **T)
    op.create_table("sync_staging", sa.Column("job_id", SID, sa.ForeignKey("sync_job.id"), primary_key=True), sa.Column("object_type", sa.String(32), primary_key=True), sa.Column("source_id", SID, primary_key=True), sa.Column("normalized_data", sa.JSON(), nullable=False), **T)
    op.create_table("employee_department", sa.Column("employee_id", SID, sa.ForeignKey("employee.id"), primary_key=True), sa.Column("department_id", SID, sa.ForeignKey("department.id"), primary_key=True), sa.Column("is_primary", sa.Boolean(), nullable=False), sa.Column("active", sa.Boolean(), nullable=False), **T)
    op.create_table("employee_store", sa.Column("employee_id", SID, sa.ForeignKey("employee.id"), primary_key=True), sa.Column("store_id", SID, sa.ForeignKey("department.id"), primary_key=True), sa.Column("is_primary", sa.Boolean(), nullable=False), sa.Column("path", sa.JSON(), nullable=False), **T)
    op.bulk_insert(sa.table("dataset_state", sa.column("id", sa.Integer()), sa.column("dataset_epoch", SID), sa.column("data_version", sa.BigInteger()), sa.column("initialization_status", sa.String()), sa.column("coverage_status", sa.String())), [{"id": 1, "dataset_epoch": "pending", "data_version": 0, "initialization_status": "pending", "coverage_status": "unknown"}])
    op.bulk_insert(sa.table("system_setting", sa.column("key", sa.String()), sa.column("value", sa.Text())), [{"key": "task_queue_lock", "value": "1"}])


def downgrade():
    for table in ("employee_store", "employee_department", "sync_staging", "store_code_reservation", "store_profile", "employee", "change_log", "event_inbox", "sync_job", "api_client", "admin_session", "admin_allowlist", "feishu_connection", "department", "system_setting", "dataset_state"):
        op.drop_table(table)
