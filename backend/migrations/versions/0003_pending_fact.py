"""保留未解析事实，不创建活动部门占位。"""
from alembic import op
import sqlalchemy as sa

revision='0003_pending_fact'
down_revision='0002_feishu_runtime'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('pending_fact',sa.Column('object_type',sa.String(32),primary_key=True),sa.Column('source_id',sa.String(191,collation='utf8mb4_bin'),primary_key=True),sa.Column('normalized_data',sa.JSON(),nullable=False),sa.Column('error_code',sa.String(64),nullable=False),sa.Column('updated_at',sa.DateTime(),nullable=False),mysql_engine='InnoDB',mysql_charset='utf8mb4')


def downgrade():
    op.drop_table('pending_fact')
