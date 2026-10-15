"""新增 Agent 操作回执表。"""
from alembic import op
import sqlalchemy as sa

revision = "0007_operation_receipt"
down_revision = "0006_column_comments"
branch_labels = None
depends_on = None

SID = sa.String(191, collation="utf8mb4_bin")
T = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_0900_as_cs", "comment": "Agent 操作回执记录"}


def upgrade():
    op.create_table(
        "operation_receipt",
        sa.Column("operation_id", SID, primary_key=True, nullable=False, comment="Agent 能力调用的一次操作稳定标识"),
        sa.Column("idempotency_key", SID, nullable=False, comment="用于防止重复提交的幂等键"),
        sa.Column("capability", sa.String(128), nullable=False, comment="被调用的能力名称"),
        sa.Column("actor_type", sa.String(32), nullable=False, comment="调用主体类型，例如人工、Agent 或 CI"),
        sa.Column("actor_id", SID, nullable=False, comment="调用主体的稳定身份标识"),
        sa.Column("environment", sa.String(32), nullable=False, comment="操作运行环境，例如 production 或 test"),
        sa.Column("run_id", SID, nullable=True, comment="关联的 Agent 运行标识"),
        sa.Column("case_id", SID, nullable=True, comment="关联的 Evaluation 用例标识"),
        sa.Column("request_hash", sa.String(64), nullable=False, comment="规范化请求内容的摘要"),
        sa.Column("status", sa.String(32), nullable=False, comment="操作回执状态"),
        sa.Column("job_id", SID, nullable=True, comment="关联的同步任务标识"),
        sa.Column("before_epoch", SID, nullable=False, comment="请求开始时的数据集世代标识"),
        sa.Column("before_version", sa.BigInteger(), nullable=False, comment="请求开始时的数据版本号"),
        sa.Column("committed_epoch", SID, nullable=True, comment="业务提交后的数据集世代标识"),
        sa.Column("committed_version", sa.BigInteger(), nullable=True, comment="业务提交后的数据版本号"),
        sa.Column("result_summary", sa.JSON(), nullable=True, comment="脱敏后的结构化结果摘要"),
        sa.Column("error_code", sa.String(64), nullable=True, comment="最近一次失败的稳定错误编码"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, comment="操作回执创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, comment="操作回执最近更新时间"),
        sa.UniqueConstraint("actor_id", "environment", "idempotency_key", name="uq_operation_receipt_idempotency"),
        **T,
    )
    for name, column in (
        ("ix_operation_receipt_capability", "capability"),
        ("ix_operation_receipt_actor_id", "actor_id"),
        ("ix_operation_receipt_environment", "environment"),
        ("ix_operation_receipt_run_id", "run_id"),
        ("ix_operation_receipt_case_id", "case_id"),
        ("ix_operation_receipt_status", "status"),
        ("ix_operation_receipt_job_id", "job_id"),
        ("ix_operation_receipt_error_code", "error_code"),
        ("ix_operation_receipt_created_at", "created_at"),
    ):
        op.create_index(name, "operation_receipt", [column])


def downgrade():
    for name in (
        "ix_operation_receipt_created_at",
        "ix_operation_receipt_error_code",
        "ix_operation_receipt_job_id",
        "ix_operation_receipt_status",
        "ix_operation_receipt_case_id",
        "ix_operation_receipt_run_id",
        "ix_operation_receipt_environment",
        "ix_operation_receipt_actor_id",
        "ix_operation_receipt_capability",
    ):
        op.drop_index(name, table_name="operation_receipt")
    op.drop_table("operation_receipt")
