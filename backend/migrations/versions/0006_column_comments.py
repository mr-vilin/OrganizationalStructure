"""为 0005 冻结结构补充中文注释；回退只恢复历史注释。"""
from alembic import context, op
import sqlalchemy as sa
from migrations.schema_20261022 import SCHEMA, checked_definitions, column_sql

revision = "0006_column_comments"
down_revision = "0005_sync_job_ledger"
branch_labels = None
depends_on = None


def _apply(comment_key):
    definitions = None if context.is_offline_mode() else checked_definitions(op.get_bind())
    for table, spec in SCHEMA.items():
        for name in spec['columns']:
            op.execute(sa.text(column_sql(table, name, comment_key, definitions)))


def upgrade():
    _apply('comment_0006')


def downgrade():
    _apply('baseline_comment')
