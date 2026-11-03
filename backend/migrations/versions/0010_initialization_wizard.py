"""一次性切换到严格初始化向导；业务数据在管理员重来时才清理。

不新增表或字段，沿用现有中文字段注释、字符集、索引与约束。
执行前须停止旧应用写入及 worker，备份数据并记录 0009 状态。
失败恢复采用迁移前备份；本迁移不自动降级已经由新流程提交的数据。
"""
from alembic import op

revision = '0010_initialization_wizard'
down_revision = '0009_operation_receipt'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        INSERT INTO system_setting (`key`, value)
        SELECT 'initialization_flow', JSON_OBJECT(
            'flow_id', REPLACE(UUID(), '-', ''),
            'phase', CASE WHEN ds.initialization_status = 'complete'
                OR EXISTS (SELECT 1 FROM department)
                OR EXISTS (SELECT 1 FROM employee)
                OR EXISTS (SELECT 1 FROM sync_job)
                THEN 'cleanup_required' ELSE 'pending' END,
            'checks', JSON_ARRAY(), 'evidence', NULL)
        FROM dataset_state AS ds WHERE ds.id = 1
        ON DUPLICATE KEY UPDATE value = VALUES(value)
    """)
    op.execute("UPDATE dataset_state AS ds SET ds.initialization_status='pending', ds.coverage_status='unknown' WHERE ds.id=1")
    op.execute("""UPDATE sync_job AS sj SET sj.status='failed', sj.phase='superseded',
        sj.error_code='INITIALIZATION_FLOW_CHANGED', sj.error_detail='切换到新初始化流程，请在向导中重新初始化',
        sj.lease_generation=sj.lease_generation+1, sj.lease_expires_at=NULL,
        sj.updated_at=UTC_TIMESTAMP(), sj.finished_at=UTC_TIMESTAMP()
        WHERE sj.status IN ('queued','running')""")
    op.execute("UPDATE event_inbox AS ei SET ei.status='superseded' WHERE ei.status='queued'")
    op.execute("UPDATE worker_lease AS wl SET wl.generation=wl.generation+1, wl.owner=NULL, wl.expires_at=NULL WHERE wl.id=1")
    op.execute("""INSERT INTO change_log
        (object_type, object_id, source, actor, before_data, after_data, committed_at)
        VALUES ('initialization', 'flow-switch', 'migration', 'migration:0010', NULL,
                JSON_OBJECT('action','require_new_initialization'), UTC_TIMESTAMP())""")


def downgrade():
    raise RuntimeError('0010 不自动恢复旧完成标记；请停写后使用迁移前备份及经审查的恢复方案')
