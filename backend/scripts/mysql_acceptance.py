"""只在独立 _test 库执行 MySQL 验收，并脱敏所有子进程输出。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote, unquote

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def inspect_database(url: str, expected_database: str, *, migrated=False, show_ddl=False):
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    from app.persistence.database import create_mysql_engine

    parsed = make_url(url)
    if parsed.drivername != 'mysql+pymysql' or parsed.database != expected_database or not expected_database.endswith('_test'):
        raise ValueError('必须显式指定名称以 _test 结尾、且与 URL 一致的独立测试库')
    engine = create_mysql_engine(url)
    try:
        with engine.connect() as db:
            row = db.execute(text('SELECT DATABASE(), VERSION(), @@transaction_isolation, '
                                  '@@character_set_client, @@character_set_connection, '
                                  '@@character_set_results, @@collation_connection')).one()
            print('实际数据库/版本/隔离/会话:', tuple(row))
            assert row[0] == expected_database and row[0].endswith('_test')
            assert row[1].startswith('8.4.') and row[2] == 'REPEATABLE-READ'
            assert tuple(row[3:]) == ('utf8mb4', 'utf8mb4', 'utf8mb4', 'utf8mb4_general_ci')
            schema = db.execute(text('SELECT DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME '
                                     'FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=DATABASE()')).one()
            assert tuple(schema) == ('utf8mb4', 'utf8mb4_general_ci')
            version_table = db.scalar(text("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='alembic_version'"))
            revision = db.scalar(text('SELECT version_num FROM alembic_version')) if version_table else None
            assert revision in (None, '0008_session_digest', '0009_operation_receipt')
            if revision is None:
                assert db.scalar(text('SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()')) == 0, '无迁移记录时只允许全新空测试库'
            print('实际数据库字符集/排序规则:', tuple(schema), '迁移版本:', revision)
            mismatches = db.scalar(text('''SELECT COUNT(*) FROM information_schema.KEY_COLUMN_USAGE k
                JOIN information_schema.COLUMNS c ON c.TABLE_SCHEMA=k.TABLE_SCHEMA AND c.TABLE_NAME=k.TABLE_NAME AND c.COLUMN_NAME=k.COLUMN_NAME
                JOIN information_schema.COLUMNS r ON r.TABLE_SCHEMA=k.REFERENCED_TABLE_SCHEMA AND r.TABLE_NAME=k.REFERENCED_TABLE_NAME AND r.COLUMN_NAME=k.REFERENCED_COLUMN_NAME
                WHERE k.TABLE_SCHEMA=DATABASE() AND k.REFERENCED_TABLE_NAME IS NOT NULL
                AND (c.COLUMN_TYPE<>r.COLUMN_TYPE OR NOT(c.CHARACTER_SET_NAME<=>r.CHARACTER_SET_NAME) OR NOT(c.COLLATION_NAME<=>r.COLLATION_NAME))'''))
            assert mismatches == 0
            print('现有外键类型/字符集/排序规则不兼容数:', mismatches)
            if not migrated:
                exists = db.scalar(text("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='operation_receipt'"))
                print('回执表已存在:', bool(exists), '；0009 仅新增表，无已有字符串唯一键/外键/比较语义转换')
                return
            assert revision == '0009_operation_receipt'
            table = db.execute(text("SELECT ENGINE,TABLE_COLLATION FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='operation_receipt'")).one()
            assert tuple(table) == ('InnoDB', 'utf8mb4_general_ci')
            columns = db.execute(text("SELECT COLUMN_NAME,CHARACTER_SET_NAME,COLLATION_NAME,COLUMN_COMMENT FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='operation_receipt' ORDER BY ORDINAL_POSITION")).all()
            assert len(columns) == 19
            for name, charset, collation, comment in columns:
                assert comment and any('\u4e00' <= char <= '\u9fff' for char in comment)
                if charset is not None:
                    assert charset == 'utf8mb4'
                    assert collation == ('utf8mb4_bin' if name in {'operation_id', 'idempotency_key', 'actor_id', 'run_id', 'case_id', 'job_id', 'before_epoch', 'committed_epoch'} else 'utf8mb4_general_ci')
            print('实际回执表:', tuple(table), '；19 列中文注释和逐列排序规则验证通过')
            ddl = db.execute(text('SHOW CREATE TABLE operation_receipt')).one()[1]
            assert 'UNIQUE KEY `uq_operation_receipt_idempotency` (`actor_id`,`environment`,`idempotency_key`)' in ddl
            assert 'FOREIGN KEY' not in ddl
            if show_ddl:
                print(ddl)
    finally:
        engine.dispose()


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['preflight', 'migrate', 'capability', 'integration', 'backend', 'without-database'])
    parser.add_argument('--credentials', type=Path)
    parser.add_argument('--expected-database')
    args = parser.parse_args()
    credentials = args.credentials.resolve() if args.credentials else None
    # 单元 HTTP 测试不得继承真实数据库或飞书配置。
    for key in list(os.environ):
        if key.upper().startswith('ORG_'):
            del os.environ[key]
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    os.environ['PYTHONUTF8'] = '1'
    os.chdir(BACKEND)
    secrets = []

    def redact(value):
        for secret in secrets:
            if secret:
                value = value.replace(secret, '[REDACTED]')
        return re.sub(r'mysql\+pymysql://[^\s\'\"]+', '[REDACTED_DATABASE_URL]', value)

    try:
        if args.phase != 'without-database':
            if not args.credentials or not args.expected_database:
                parser.error('该阶段要求 --credentials 和 --expected-database')
            url = json.loads(credentials.read_text(encoding='utf-8'))['database_url']
            from sqlalchemy.engine import make_url
            password = make_url(url).password or ''
            secrets.extend([url, password, unquote(password), quote(password, safe='')])
            inspect_database(url, args.expected_database, migrated=args.phase not in {'preflight', 'migrate'})
            os.environ['ORG_TEST_DATABASE_URL'] = url
        if args.phase == 'preflight':
            return 0
        if args.phase == 'migrate':
            os.environ['ORG_DATABASE_URL'] = url
            command = [sys.executable, '-m', 'alembic', 'upgrade', 'head']
        else:
            target = {'capability': 'tests/integration/test_capability_mysql.py', 'integration': 'tests/integration',
                      'backend': 'tests', 'without-database': 'tests/integration/test_capability_mysql.py'}[args.phase]
            command = [sys.executable, '-m', 'pytest', target, '-q', '-rs']
        print('执行:', ' '.join(command), flush=True)
        result = subprocess.run(command, env=os.environ.copy(), capture_output=True, text=True, encoding='utf-8', errors='replace')
        print(redact(result.stdout), end='')
        print(redact(result.stderr), end='')
        print('退出码:', result.returncode)
        if result.returncode == 0 and args.phase == 'migrate':
            inspect_database(url, args.expected_database, migrated=True, show_ddl=True)
        return result.returncode
    except Exception:
        import traceback
        print('验收失败:', redact(traceback.format_exc()), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
