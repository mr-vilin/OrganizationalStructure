"""扩展组织字段与飞书连接自定义字段映射。"""
from alembic import op
import sqlalchemy as sa

revision = "0004_organization_fields"
down_revision = "0003_pending_fact"
branch_labels = None
depends_on = None
SID = sa.String(191, collation="utf8mb4_bin")


def upgrade():
    op.add_column("department", sa.Column("leader_user_id", SID, nullable=True, comment="部门负责人对应的飞书用户稳定标识"))
    op.add_column("employee", sa.Column("employee_type_id", SID, nullable=True, comment="员工类型枚举选项稳定标识"))
    op.add_column("employee", sa.Column("employee_type_name", sa.String(255), nullable=True, comment="员工类型枚举当前展示值"))
    op.add_column("employee", sa.Column("job_title", sa.String(255), nullable=True, comment="员工当前职务"))
    op.add_column("employee", sa.Column("leader_user_id", SID, nullable=True, comment="直属上级对应的飞书用户稳定标识"))
    op.add_column("employee", sa.Column("permission_role_id", SID, nullable=True, comment="权限角色自定义字段选项标识"))
    op.add_column("employee", sa.Column("permission_role_name", sa.String(255), nullable=True, comment="权限角色自定义字段展示值"))
    op.add_column("employee", sa.Column("store_attribute_id", SID, nullable=True, comment="门店属性自定义字段选项标识"))
    op.add_column("employee", sa.Column("store_attribute_name", sa.String(255), nullable=True, comment="门店属性自定义字段展示值"))
    op.add_column("feishu_connection", sa.Column("custom_attrs", sa.JSON(), nullable=False, server_default=sa.text("('{}')"), comment="按飞书连接保存的自定义字段映射与选项定义"))


def downgrade():
    op.drop_column("feishu_connection", "custom_attrs")
    for name in ("store_attribute_name", "store_attribute_id", "permission_role_name", "permission_role_id", "leader_user_id", "job_title", "employee_type_name", "employee_type_id"):
        op.drop_column("employee", name)
    op.drop_column("department", "leader_user_id")
