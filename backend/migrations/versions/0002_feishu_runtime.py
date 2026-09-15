"""飞书登录状态、身份映射与单 worker 租约。"""
from alembic import op
import sqlalchemy as sa

revision = '0002_feishu_runtime'
down_revision = '0001_initial'
branch_labels = None
depends_on = None
T = {'mysql_engine':'InnoDB','mysql_charset':'utf8mb4'}
SID = sa.String(191,collation='utf8mb4_bin')


def upgrade():
    op.create_table('oauth_state', sa.Column('digest',sa.String(64),primary_key=True),sa.Column('expires_at',sa.DateTime(),nullable=False),**T)
    op.create_table('login_identity',sa.Column('open_id',SID,primary_key=True),sa.Column('user_id',SID,nullable=False),sa.Column('tenant_key',SID,nullable=False),**T)
    op.create_table('worker_lease',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('owner',SID),sa.Column('generation',sa.Integer(),nullable=False),sa.Column('expires_at',sa.DateTime()),**T)
    op.bulk_insert(sa.table('worker_lease',sa.column('id',sa.Integer()),sa.column('generation',sa.Integer())),[{'id':1,'generation':0}])


def downgrade():
    for table in ('worker_lease','login_identity','oauth_state'): op.drop_table(table)
