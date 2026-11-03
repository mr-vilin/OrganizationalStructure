"""使用冻结定义对齐注释和排序规则；在线先预检，保留其余元数据。

回退依赖目标库原始快照，禁止推测已有库的排序规则。MySQL DDL 非原子；
中断后停写并重跑在线升级，已完成列可安全重复应用。
"""
from alembic import context, op
import sqlalchemy as sa
from migrations.schema_20261022 import SCHEMA, checked_definitions, check_data, column_sql, quote

revision = "0007_schema_alignment"
down_revision = "0006_column_comments"
branch_labels = None
depends_on = None


def upgrade():
    definitions = None
    if not context.is_offline_mode():
        definitions = checked_definitions(op.get_bind())
        check_data(op.get_bind())
    # 不指定库名时 MySQL 修改当前连接选择的数据库；离线执行必须明确 USE 目标库。
    op.execute(sa.text("ALTER DATABASE CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"))
    for table, spec in SCHEMA.items():
        op.execute(sa.text(f"ALTER TABLE `{table}` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT = {quote(spec['comment'])}"))
        for name in spec['columns']:
            op.execute(sa.text(column_sql(table, name, 'comment', definitions, align=True)))


def downgrade():
    raise RuntimeError("0007_schema_alignment 不自动回退；停写后使用目标库迁移前结构快照和经审查的恢复脚本")
