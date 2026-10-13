"""为现有表字段补充中文说明，不改变字段类型、约束或数据。"""
from alembic import op
import sqlalchemy as sa

revision = "0006_column_comments"
down_revision = "0005_sync_job_ledger"
branch_labels = None
depends_on = None

COMMENTS = {
    "dataset_state": {"id":"数据集状态单例标识","dataset_epoch":"数据集世代标识","data_version":"已提交数据版本号","initialization_status":"初始化状态","coverage_status":"通讯录覆盖状态","last_full_sync_at":"最近一次全量同步时间"},
    "system_setting": {"key":"系统设置键名","value":"系统设置值"},
    "department": {"id":"内部部门稳定标识","feishu_department_id":"飞书部门标识","parent_id":"父部门标识","name":"部门名称","leader_user_id":"部门负责人用户标识","status":"部门状态","sync_quality":"部门同步质量","is_virtual_root":"是否为虚拟根部门","last_seen_at":"最近一次从飞书看到的时间"},
    "employee": {"id":"内部员工稳定标识","feishu_user_id":"飞书用户标识","open_id":"飞书用户开放标识","name":"员工姓名","employee_no":"员工工号","employee_type_id":"员工类型枚举选项标识","employee_type_name":"员工类型展示名称","job_title":"员工职务","leader_user_id":"直属上级用户标识","permission_role_id":"权限角色选项标识","permission_role_name":"权限角色展示名称","store_attribute_id":"门店属性选项标识","store_attribute_name":"门店属性展示名称","status":"员工状态","sync_quality":"员工同步质量","primary_department_id":"主部门标识","primary_store_status":"主门店解析状态","last_seen_at":"最近一次从飞书看到的时间"},
    "employee_department": {"employee_id":"员工标识","department_id":"部门标识","is_primary":"是否为主部门关系","active":"关系是否有效"},
    "store_profile": {"department_id":"门店对应部门标识","is_store":"是否标记为门店","store_code":"门店编码","notes":"门店备注"},
    "store_code_reservation": {"store_code":"预留门店编码","department_id":"占用该编码的部门标识","reserved_at":"编码预留时间"},
    "employee_store": {"employee_id":"员工标识","store_id":"门店部门标识","is_primary":"是否为主门店关系","path":"门店路径标识列表"},
    "feishu_connection": {"id":"飞书连接单例标识","tenant_key":"飞书租户标识","app_id":"飞书应用标识","status":"连接状态","coverage_status":"连接覆盖状态","custom_attrs":"自定义字段映射与选项定义"},
    "oauth_state": {"digest":"OAuth 状态摘要","expires_at":"OAuth 状态过期时间"},
    "login_identity": {"open_id":"飞书开放标识","user_id":"飞书用户标识","tenant_key":"飞书租户标识"},
    "worker_lease": {"id":"worker 租约单例标识","owner":"当前 worker 标识","generation":"租约世代号","expires_at":"租约过期时间"},
    "admin_allowlist": {"open_id":"管理员飞书开放标识","created_at":"加入白名单时间"},
    "admin_session": {"id":"管理员会话标识","open_id":"管理员飞书开放标识","csrf_hash":"CSRF 令牌摘要","expires_at":"会话过期时间","revoked_at":"会话撤销时间"},
    "api_client": {"id":"API 客户端标识","name":"API 客户端名称","secret_hash":"客户端密钥摘要","created_at":"创建时间","revoked_at":"撤销时间"},
    "sync_job": {"id":"同步任务标识","type":"同步任务类型","name":"同步任务名称","trigger_source":"任务触发来源","description":"同步任务说明","root_department_id":"子树同步根部门标识","requested_by":"任务请求方","status":"任务状态","phase":"任务阶段","attempt":"任务尝试次数","execution_count":"任务执行次数","retry_count":"任务重试次数","total_count":"任务对象总数","success_count":"任务成功对象数","failure_count":"任务失败对象数","lease_generation":"任务租约世代号","lease_expires_at":"任务租约过期时间","error_code":"任务错误编码","error_detail":"任务错误详情","created_at":"任务创建时间","updated_at":"任务更新时间","started_at":"任务开始时间","finished_at":"任务结束时间"},
    "sync_job_detail": {"id":"任务明细自增标识","job_id":"所属同步任务标识","object_type":"任务对象类型","object_id":"任务对象标识","object_name":"任务对象名称快照","status":"对象处理状态","error_code":"对象错误编码","error_message":"对象错误摘要","attempt":"对象处理尝试次数","started_at":"对象处理开始时间","finished_at":"对象处理结束时间","change_log_id":"关联变更日志标识"},
    "event_inbox": {"event_id":"飞书事件标识","event_type":"飞书事件类型","object_id":"事件对象标识","payload":"事件原始载荷","status":"事件处理状态","attempts":"事件处理尝试次数","received_at":"事件接收时间"},
    "sync_staging": {"job_id":"所属同步任务标识","object_type":"暂存对象类型","source_id":"来源对象标识","normalized_data":"规范化对象数据"},
    "pending_fact": {"object_type":"待核实对象类型","source_id":"待核实来源标识","normalized_data":"待核实规范化数据","error_code":"待核实错误编码","updated_at":"待核实记录更新时间"},
    "change_log": {"id":"变更日志自增标识","object_type":"变更对象类型","object_id":"变更对象标识","source":"变更来源","actor":"操作主体","job_id":"关联同步任务标识","before_data":"变更前数据","after_data":"变更后数据","committed_at":"变更提交时间"},
}

def _quote(value):
    return "'" + str(value).replace("'", "''") + "'"

def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table, columns in COMMENTS.items():
        if table not in inspector.get_table_names():
            continue
        rows = {row[0]: row for row in bind.execute(sa.text(f"SHOW FULL COLUMNS FROM `{table}`"))}
        for name, comment in columns.items():
            row = rows.get(name)
            if not row:
                continue
            # SHOW FULL COLUMNS: Field, Type, Collation, Null, Key, Default, Extra, Privileges, Comment
            typ = row[1]
            collation = row[2]
            nullable = "NULL" if row[3] == "YES" else "NOT NULL"
            default = row[5]
            extra = row[6] or ""
            pieces = [f"ALTER TABLE `{table}` MODIFY COLUMN `{name}` {typ}"]
            if collation and any(token in typ.lower() for token in ("char", "text", "enum", "set")):
                pieces.append(f"CHARACTER SET utf8mb4 COLLATE `{collation}`")
            pieces.append(nullable)
            if default is not None:
                default_text = str(default)
                if typ.lower() == "json":
                    # MySQL SHOW FULL COLUMNS 对 JSON 默认值可能返回带字符集前缀的转义文本；
                    # 这里使用等价且合法的 JSON 表达式，避免重复转义。
                    pieces.append("DEFAULT ('{}')")
                elif (default_text.upper() in {"CURRENT_TIMESTAMP", "CURRENT_TIMESTAMP()"}
                        or default_text.startswith("(")
                        or default_text.startswith("_utf8mb4'")
                        or default_text.startswith("b'")):
                    pieces.append(f"DEFAULT {default_text}")
                else:
                    pieces.append(f"DEFAULT {_quote(default_text)}")
            if "auto_increment" in extra:
                pieces.append("AUTO_INCREMENT")
            if "on update" in extra.lower():
                pieces.append(extra[extra.lower().index("on update"):])
            pieces.append(f"COMMENT {_quote(comment)}")
            op.execute(sa.text(" ".join(pieces)))

def downgrade():
    # 字段备注回退为空，不触碰字段定义和数据。
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table, columns in COMMENTS.items():
        if table not in inspector.get_table_names():
            continue
        rows = {row[0]: row for row in bind.execute(sa.text(f"SHOW FULL COLUMNS FROM `{table}`"))}
        for name in columns:
            row = rows.get(name)
            if row:
                op.execute(sa.text(f"ALTER TABLE `{table}` MODIFY COLUMN `{name}` {row[1]} {('NULL' if row[3] == 'YES' else 'NOT NULL')} COMMENT ''"))
