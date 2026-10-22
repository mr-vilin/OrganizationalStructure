"""0005—0007 专用冻结快照；禁止随当前 ORM 演进而更新。

在线保留 SHOW CREATE TABLE 中的完整列定义，只修改本次授权的注释/排序规则。
离线 SQL 采用 0005 历史定义（普通文本 utf8mb4_0900_ai_ci）；已有库必须先预检。
"""
import json
import re
from pathlib import Path

import sqlalchemy as sa


SCHEMA = json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))
COMMENT = re.compile(r"\s+COMMENT\s+'(?:[^'\\]|\\.|'')*'", re.I)


def quote(value):
    return "'" + str(value).replace("\\", "\\\\").replace("'", "''") + "'"


def identifier(value):
    return '`' + value.replace('`', '``') + '`'


def normalize_type(value):
    value = str(value).lower().split(' collate ')[0]
    value = value.replace('boolean', 'tinyint(1)').replace('bool', 'tinyint(1)').replace('integer', 'int')
    return re.sub(r'\b(bigint|int|smallint)\(\d+\)', r'\1', value)


def normalize_default(value):
    if value is None:
        return None
    value = re.sub(r'_utf8mb4', '', str(value), flags=re.I)
    return value.strip("()'\" ")


def checked_definitions(bind):
    """先检查全表，任何意外差异都在第一条 DDL 前停止。"""
    definitions = {}
    for table, spec in SCHEMA.items():
        rows = bind.execute(sa.text('''
            SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT, EXTRA,
                   CHARACTER_SET_NAME, COLLATION_NAME, GENERATION_EXPRESSION, COLUMN_COMMENT
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table
        '''), {'table': table}).mappings().all()
        if {r['COLUMN_NAME'] for r in rows} != set(spec['columns']):
            raise RuntimeError(f'迁移预检失败：{table} 字段集合与冻结快照不符')
        for row in rows:
            name = row['COLUMN_NAME']
            expected = spec['columns'][name]
            extra = (row['EXTRA'] or '').lower()
            valid = (
                normalize_type(row['COLUMN_TYPE']) == normalize_type(expected['type'])
                and (row['IS_NULLABLE'] == 'YES') == expected['nullable']
                and normalize_default(row['COLUMN_DEFAULT']) == normalize_default(expected['default'])
                and ('auto_increment' in extra) == expected['autoincrement']
                and not row['GENERATION_EXPRESSION']
                and extra.replace('auto_increment', '').replace('default_generated', '').strip() == ''
                and row['COLUMN_COMMENT'] in {expected['baseline_comment'], expected['comment_0006'], expected['comment']}
            )
            if row['CHARACTER_SET_NAME']:
                allowed = {expected['collation']} if expected['collation'] else {
                    'utf8mb4_0900_ai_ci', 'utf8mb4_0900_as_cs', 'utf8mb4_general_ci'}
                valid = valid and row['CHARACTER_SET_NAME'] == 'utf8mb4' and row['COLLATION_NAME'] in allowed
            if not valid:
                raise RuntimeError(f'迁移预检失败：{table}.{name} 存在未预期元数据差异')
        create_sql = bind.execute(sa.text(f'SHOW CREATE TABLE {identifier(table)}')).one()[1]
        definitions[table] = {}
        for line in create_sql.splitlines():
            match = re.match(r'\s*`([^`]+)`\s+(.+?)(?:,)?$', line)
            if match and match[1] in spec['columns']:
                definitions[table][match[1]] = identifier(match[1]) + ' ' + match[2]
        if set(definitions[table]) != set(spec['columns']):
            raise RuntimeError(f'迁移预检失败：无法完整读取 {table} 字段定义')
    return definitions


def column_sql(table, name, comment_key, definitions=None, align=False):
    column = SCHEMA[table]['columns'][name]
    definition = definitions[table][name] if definitions else column['definition']
    definition = COMMENT.sub('', definition)
    is_text = normalize_type(column['type']).startswith(('varchar', 'char', 'text'))
    if is_text and (align or definitions is None):
        collation = column['collation'] or ('utf8mb4_general_ci' if align else 'utf8mb4_0900_ai_ci')
        definition = re.sub(r'\s+(?:CHARACTER SET|COLLATE)\s+`?\w+`?', '', definition, flags=re.I)
        definition = re.sub(r'((?:VAR)?CHAR\(\d+\)|TEXT)',
                            rf'\1 CHARACTER SET utf8mb4 COLLATE {collation}', definition, count=1, flags=re.I)
    return f'ALTER TABLE {identifier(table)} MODIFY COLUMN {definition} COMMENT {quote(column[comment_key])}'


def check_data(bind):
    """仅返回阻断原因，不返回业务键或任何会话值。"""
    inspector = sa.inspect(bind)
    incoming = bind.execute(sa.text('''
        SELECT COUNT(*) FROM information_schema.KEY_COLUMN_USAGE
        WHERE REFERENCED_TABLE_SCHEMA = DATABASE() AND TABLE_SCHEMA <> DATABASE()
    ''')).scalar_one()
    if incoming:
        raise RuntimeError('外键预检失败：存在来自其他数据库的关联')
    for table, spec in SCHEMA.items():
        keys = [inspector.get_pk_constraint(table)['constrained_columns']]
        keys += [index['column_names'] for index in inspector.get_indexes(table) if index['unique']]
        for columns in keys:
            if not columns:
                continue
            expressions = []
            for name in columns:
                column = spec['columns'][name]
                expression = identifier(name)
                if normalize_type(column['type']).startswith(('varchar', 'char', 'text')):
                    expression += ' COLLATE ' + (column['collation'] or 'utf8mb4_general_ci')
                expressions.append(expression)
            where = ' AND '.join(identifier(name) + ' IS NOT NULL' for name in columns)
            query = f'SELECT 1 FROM {identifier(table)} WHERE {where} GROUP BY ' + ', '.join(expressions) + ' HAVING COUNT(*) > 1 LIMIT 1'
            if bind.execute(sa.text(query)).first():
                raise RuntimeError(f'排序规则预检失败：{table} 存在唯一键冲突')
        for fk in inspector.get_foreign_keys(table):
            if fk.get('referred_schema') not in (None, bind.engine.url.database):
                raise RuntimeError(f'外键预检失败：{table} 存在跨库关联')
            target = fk['referred_table']
            conditions = []
            for source, referred in zip(fk['constrained_columns'], fk['referred_columns']):
                left = spec['columns'][source]
                right = SCHEMA[target]['columns'][referred]
                if (left['type'], left['collation']) != (right['type'], right['collation']):
                    raise RuntimeError(f'外键预检失败：{table} 类型或排序规则不兼容')
                conditions.append(f'c.{identifier(source)} = p.{identifier(referred)}')
            present = ' AND '.join(f'c.{identifier(name)} IS NOT NULL' for name in fk['constrained_columns'])
            query = f'SELECT 1 FROM {identifier(table)} c WHERE {present} AND NOT EXISTS (SELECT 1 FROM {identifier(target)} p WHERE ' + ' AND '.join(conditions) + ') LIMIT 1'
            if bind.execute(sa.text(query)).first():
                raise RuntimeError(f'外键预检失败：{table} 存在孤儿记录')


def comparison_samples(bind):
    """记录固定样本的比较语义，帮助审核大小写、重音和尾空格变化。"""
    report = {}
    for collation in ('utf8mb4_0900_ai_ci', 'utf8mb4_0900_as_cs', 'utf8mb4_general_ci', 'utf8mb4_bin'):
        report[collation] = dict(bind.execute(sa.text(f'''
            SELECT _utf8mb4'A' COLLATE {collation} = _utf8mb4'a' AS case_equal,
                   _utf8mb4'é' COLLATE {collation} = _utf8mb4'e' AS accent_equal,
                   _utf8mb4'a' COLLATE {collation} = _utf8mb4'a ' AS trailing_space_equal
        ''')).mappings().one())
    return report
