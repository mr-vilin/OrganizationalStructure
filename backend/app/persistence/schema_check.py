"""只读结构验收和迁移预检；输出仅含元数据、数量和错误位置。"""
import argparse
import json
import re
import sys

from sqlalchemy import String, Text, UniqueConstraint

from app.config import get_settings
from app.persistence.database import CURRENT_SCHEMA_HEAD, create_mysql_engine, schema_snapshot
from app.persistence.models import Base


def _type(value):
    value = str(value).lower().split(' collate ')[0]
    value = value.replace('boolean', 'tinyint(1)').replace('bool', 'tinyint(1)').replace('integer', 'int')
    return re.sub(r'\b(bigint|int|smallint)\(\d+\)', r'\1', value)


def _default(value):
    # 仅识别实库返回的空对象表达式，不泛化移除字面值中的反斜杠。
    if str(value).lower() == r"_utf8mb4\'{}\'":
        return '{}'
    return None if value is None else re.sub('_utf8mb4', '', str(value), flags=re.I).strip("()'\" ")


def check_schema(engine):
    snapshot = schema_snapshot(engine)
    errors = []
    is_mysql = engine.dialect.name == 'mysql'
    if snapshot['versions'] != [CURRENT_SCHEMA_HEAD]:
        errors.append('schema.version')
    if is_mysql:
        if snapshot['database'] != {'charset': 'utf8mb4', 'collation': 'utf8mb4_general_ci'}:
            errors.append('schema.database_defaults')
        for key, value in {
            'character_set_client': 'utf8mb4', 'character_set_connection': 'utf8mb4',
            'character_set_results': 'utf8mb4', 'collation_connection': 'utf8mb4_general_ci',
            'time_zone': '+00:00', 'transaction_isolation': 'REPEATABLE-READ',
        }.items():
            if snapshot['session'].get(key) != value:
                errors.append('session.' + key)
    for name in sorted(set(snapshot['tables']) - set(Base.metadata.tables)):
        errors.append(name + '.unexpected_table')
    for table in Base.metadata.tables.values():
        actual = snapshot['tables'].get(table.name)
        if actual is None:
            errors.append(table.name + '.missing_table')
            continue
        columns = {c['name']: c for c in actual['columns']}
        if set(columns) != set(table.columns.keys()):
            errors.append(table.name + '.columns')
        if is_mysql:
            if actual['comment'] != table.comment:
                errors.append(table.name + '.comment')
            if actual['options'] != {'engine': 'InnoDB', 'collation': 'utf8mb4_general_ci'}:
                errors.append(table.name + '.options')
            for index in actual['index_metadata']:
                if (index['SUB_PART'] is not None or index['COLLATION'] != 'A'
                        or index['INDEX_TYPE'] != 'BTREE' or index['IS_VISIBLE'] != 'YES'
                        or index['EXPRESSION'] is not None):
                    errors.append(table.name + '.index_definition.' + index['INDEX_NAME'])
        for col in table.columns:
            observed = columns.get(col.name)
            if observed is None:
                continue
            expected = {'type': _type(col.type.compile(dialect=engine.dialect)), 'nullable': col.nullable,
                        'default': _default(col.server_default.arg) if col.server_default is not None else None}
            values = dict(observed, type=_type(observed['type']), default=_default(observed['default']))
            if is_mysql:
                expected.update(comment=col.comment, autoincrement=table.autoincrement_column is col, computed=None)
                if isinstance(col.type, (String, Text)):
                    expected.update(collation=col.type.collation or 'utf8mb4_general_ci', charset='utf8mb4')
                if (observed.get('extra') or '').lower().replace('auto_increment', '').replace('default_generated', '').strip():
                    errors.append(f'{table.name}.{col.name}.extra')
            for key, value in expected.items():
                if values.get(key) != value:
                    errors.append(f'{table.name}.{col.name}.{key}')
        if actual['primary_key']['constrained_columns'] != [c.name for c in table.primary_key]:
            errors.append(table.name + '.primary_key')
        uniques = {tuple(c.columns.keys()) for c in table.constraints if isinstance(c, UniqueConstraint)}
        uniques |= {tuple(c.name for c in i.columns) for i in table.indexes if i.unique}
        observed_uniques = {tuple(c['column_names']) for c in actual['unique_constraints']}
        observed_uniques |= {tuple(i['column_names']) for i in actual['indexes'] if i['unique']}
        if uniques != observed_uniques:
            errors.append(table.name + '.unique_constraints')
        indexes = {(i.name, tuple(c.name for c in i.columns)) for i in table.indexes if not i.unique}
        observed_indexes = {(i['name'], tuple(i['column_names'])) for i in actual['indexes'] if not i['unique']}
        # InnoDB 为外键自动建索引；仅豁免以列名命名的既有单列关联索引。
        implicit = {(fk['constrained_columns'][0], tuple(fk['constrained_columns'])) for fk in actual['foreign_keys'] if len(fk['constrained_columns']) == 1}
        if not indexes <= observed_indexes or observed_indexes - indexes - implicit:
            errors.append(table.name + '.indexes')
        foreign_keys = {(tuple(c.name for c in fk.columns), tuple(e.column.table.name for e in fk.elements),
                         tuple(e.column.name for e in fk.elements)) for fk in table.foreign_key_constraints}
        observed_fks = {(tuple(fk['constrained_columns']), tuple([fk['referred_table']] * len(fk['referred_columns'])),
                         tuple(fk['referred_columns'])) for fk in actual['foreign_keys']}
        if (foreign_keys != observed_fks or any(fk.get('options') for fk in actual['foreign_keys'])
                or any(fk.get('referred_schema') not in (None, engine.url.database) for fk in actual['foreign_keys'])):
            errors.append(table.name + '.foreign_keys')
    return {'errors': sorted(set(errors)), 'snapshot': snapshot}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot-only', action='store_true', help='只采集结构，用于受限保存迁移前快照')
    parser.add_argument('--preflight', action='store_true', help='校验 0005/0006 结构及排序规则转换安全性，不写库')
    parser.add_argument('--offline-baseline', action='store_true', help='配合 --preflight，要求普通文本列精确匹配离线 ai_ci 基线')
    args = parser.parse_args()
    if args.offline_baseline and not args.preflight:
        parser.error('--offline-baseline 必须与 --preflight 同用')
    settings = get_settings()
    if not settings.database_url:
        print(json.dumps({'error': 'DATABASE_NOT_CONFIGURED'}))
        return 2
    engine = None
    try:
        engine = create_mysql_engine(settings.database_url)
        if args.snapshot_only:
            result = {'snapshot': schema_snapshot(engine), 'errors': []}
        elif args.preflight:
            from migrations.schema_20261022 import checked_definitions, check_data, comparison_samples
            result = {'snapshot': schema_snapshot(engine), 'errors': []}
            if result['snapshot']['versions'] not in (['0005_sync_job_ledger'], ['0006_column_comments']):
                result['errors'].append('preflight.unsupported_revision')
            else:
                with engine.connect() as connection:
                    checked_definitions(connection)
                    check_data(connection)
                    result['comparison_samples'] = comparison_samples(connection)
                if args.offline_baseline:
                    from migrations.schema_20261022 import SCHEMA
                    for table, spec in SCHEMA.items():
                        for column in result['snapshot']['tables'][table]['columns']:
                            if column['charset'] and column['collation'] != (spec['columns'][column['name']]['collation'] or 'utf8mb4_0900_ai_ci'):
                                result['errors'].append(f"{table}.{column['name']}.offline_baseline")
        else:
            result = check_schema(engine)
        print(json.dumps(result, ensure_ascii=False, default=str, sort_keys=True))
        return 1 if result['errors'] else 0
    except Exception:
        # 连接异常可能含用户名、地址或驱动参数，不打印原始异常。
        print(json.dumps({'error': 'SCHEMA_CHECK_FAILED', 'message': '结构检查失败，请核对目标连接、迁移前结构与约束'}, ensure_ascii=False))
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == '__main__':
    sys.exit(main())
