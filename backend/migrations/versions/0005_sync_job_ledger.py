"""补全同步任务账本与对象明细。

执行前检查：确认当前 revision 为 0004，且 sync_job 不存在同名新增列；在生产执行前
备份数据库并确认任务 worker 已停止。执行后验证：检查新增列的中文 COMMENT、
sync_job_detail 的唯一约束和外键，并运行同步账本回归测试。失败恢复：在未写入新任务
期间回退本 revision；若已产生新任务，先停止 worker、保留审计与备份，再按 downgrade
删除明细表及新增列，禁止直接删除已有 sync_job 数据。
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_sync_job_ledger"
down_revision = "0004_organization_fields"
branch_labels = None
depends_on = None
SID = sa.String(191, collation="utf8mb4_bin")
T = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


def upgrade():
    for name, typ, comment in [
        ("name", sa.String(255), "同步任务名称"), ("trigger_source", sa.String(32), "任务触发来源"),
        ("description", sa.Text(), "同步任务业务说明"), ("execution_count", sa.Integer(), "任务执行次数"),
        ("retry_count", sa.Integer(), "任务重试次数"), ("total_count", sa.Integer(), "任务对象总数，未知时为空"),
        ("success_count", sa.Integer(), "任务成功对象数"), ("failure_count", sa.Integer(), "任务失败对象数"),
        ("started_at", sa.DateTime(), "任务开始时间"), ("finished_at", sa.DateTime(), "任务结束时间")]:
        required = name in {"execution_count", "retry_count", "success_count", "failure_count"}
        op.add_column("sync_job", sa.Column(name, typ, nullable=not required, server_default="0" if required else None, comment=comment))
    op.create_table("sync_job_detail",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="任务明细自增标识"),
        sa.Column("job_id", SID, sa.ForeignKey("sync_job.id"), nullable=False, comment="所属同步任务标识"),
        sa.Column("object_type", sa.String(32), nullable=False, comment="任务对象类型"),
        sa.Column("object_id", SID, nullable=False, comment="任务对象稳定标识"),
        sa.Column("object_name", sa.String(255), comment="任务对象名称快照"),
        sa.Column("status", sa.String(32), nullable=False, comment="对象处理状态"),
        sa.Column("error_code", sa.String(64), comment="对象错误编码"),
        sa.Column("error_message", sa.Text(), comment="对象错误摘要"),
        sa.Column("attempt", sa.Integer(), nullable=False, comment="对象处理尝试次数"),
        sa.Column("started_at", sa.DateTime(), comment="对象处理开始时间"),
        sa.Column("finished_at", sa.DateTime(), comment="对象处理结束时间"),
        sa.Column("change_log_id", sa.BigInteger(), comment="关联变更日志标识"),
        sa.UniqueConstraint("job_id", "object_type", "object_id", name="uq_sync_job_detail_object"), **T)
    op.create_index("ix_sync_job_detail_job_id", "sync_job_detail", ["job_id"])


def downgrade():
    op.drop_index("ix_sync_job_detail_job_id", table_name="sync_job_detail")
    op.drop_table("sync_job_detail")
    for name in ("finished_at", "started_at", "success_count", "failure_count", "total_count", "retry_count", "execution_count", "description", "trigger_source", "name"):
        op.drop_column("sync_job", name)
