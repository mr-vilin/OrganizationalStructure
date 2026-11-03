"""将管理员会话令牌迁移为 SHA-256 摘要并撤销旧会话。

执行前必须停止应用、worker 和事件监听，完成备份与 admin_session 外键检查。
迁移只记录数量和状态，不输出任何旧令牌、新令牌或摘要。该迁移不可逆；失败重试
使用已增加的摘要列继续完成转换，不把摘要还原为旧令牌。
"""
from alembic import context, op
import sqlalchemy as sa


revision = "0008_session_digest"
down_revision = "0007_schema_alignment"
branch_labels = None
depends_on = None


TOKEN_TYPE = sa.String(64, collation="utf8mb4_bin")


def _has_column(bind, table: str, column: str) -> bool:
    return any(row["COLUMN_NAME"] == column for row in bind.execute(sa.text("""
        SELECT COLUMN_NAME
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table
    """), {"table": table}).mappings())


def _has_index(bind, table: str, index: str) -> bool:
    return bind.execute(sa.text("""
        SELECT 1
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table AND INDEX_NAME = :index
        LIMIT 1
    """), {"table": table, "index": index}).first() is not None


def upgrade():
    bind = op.get_bind()
    offline = context.is_offline_mode()
    before_count = None
    if not offline:
        references = bind.execute(sa.text("""
            SELECT COUNT(*)
            FROM information_schema.KEY_COLUMN_USAGE
            WHERE ((TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'admin_session')
               OR (REFERENCED_TABLE_SCHEMA = DATABASE() AND REFERENCED_TABLE_NAME = 'admin_session'))
              AND REFERENCED_TABLE_NAME IS NOT NULL
        """)).scalar_one()
        if references:
            raise RuntimeError("admin_session 存在外键引用，不能替换内部标识")
        before_count = bind.execute(sa.text("SELECT COUNT(*) FROM admin_session")).scalar_one()
        if _has_column(bind, 'admin_session', 'token_digest'):
            row = bind.execute(sa.text("""
                SELECT COLUMN_TYPE, COLLATION_NAME, COLUMN_DEFAULT, EXTRA
                FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = 'admin_session' AND COLUMN_NAME = 'token_digest'
            """)).one()
            if tuple(row) != ('varchar(64)', 'utf8mb4_bin', None, ''):
                raise RuntimeError('摘要列与迁移定义不符，停止重试')
        if _has_index(bind, 'admin_session', 'uq_admin_session_token_digest'):
            rows = bind.execute(sa.text("""
                SELECT COLUMN_NAME, NON_UNIQUE, SUB_PART FROM information_schema.STATISTICS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'admin_session'
                AND INDEX_NAME = 'uq_admin_session_token_digest' ORDER BY SEQ_IN_INDEX
            """)).all()
            if [tuple(row) for row in rows] != [('token_digest', 0, None)]:
                raise RuntimeError('摘要唯一索引与迁移定义不符，停止重试')
    if offline or not _has_column(bind, "admin_session", "token_digest"):
        op.add_column("admin_session", sa.Column("token_digest", TOKEN_TYPE, nullable=True, comment="管理员会话令牌 SHA-256 摘要"))

    op.execute(sa.text("UPDATE admin_session SET token_digest = SHA2(id, 256) WHERE token_digest IS NULL"))
    op.execute(sa.text("UPDATE admin_session SET id = REPLACE(UUID(), '-', '') WHERE token_digest = SHA2(id, 256)"))
    op.execute(sa.text("UPDATE admin_session SET revoked_at = COALESCE(revoked_at, UTC_TIMESTAMP())"))

    if not offline:
        null_count = bind.execute(sa.text("SELECT COUNT(*) FROM admin_session WHERE token_digest IS NULL")).scalar_one()
        duplicate_count = bind.execute(sa.text("""
            SELECT COUNT(*) - COUNT(DISTINCT token_digest)
            FROM admin_session
            WHERE token_digest IS NOT NULL
        """)).scalar_one()
        after_count = bind.execute(sa.text("SELECT COUNT(*) FROM admin_session")).scalar_one()
        unsafe_count = bind.execute(sa.text("""
            SELECT COUNT(*) FROM admin_session
            WHERE revoked_at IS NULL OR token_digest = SHA2(id, 256)
               OR token_digest NOT REGEXP '^[0-9a-f]{64}$'
        """)).scalar_one()
        if null_count or duplicate_count or unsafe_count or before_count != after_count:
            raise RuntimeError("会话摘要迁移校验失败")

    op.alter_column("admin_session", "token_digest", existing_type=TOKEN_TYPE, nullable=False, comment="管理员会话令牌 SHA-256 摘要")
    if context.is_offline_mode() or not _has_index(bind, "admin_session", "uq_admin_session_token_digest"):
        op.create_index("uq_admin_session_token_digest", "admin_session", ["token_digest"], unique=True)


def downgrade():
    raise RuntimeError("0008_session_digest 不可逆；保持停写并正向重试。恢复备份后也须完成摘要迁移再开放登录")
