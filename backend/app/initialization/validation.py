"""初始化使用严格校验；缺失字段不能悄悄降为待核实事实。"""
from app.sync.collector import Collector, normalize_department, normalize_user


class InitializationFailure(RuntimeError):
    def __init__(self, code, message, issues=None):
        super().__init__(code)
        self.code, self.message, self.issues = code, message, issues or []


def invalid(kind, identifier, field, message):
    raise InitializationFailure('INITIALIZATION_DATA_INVALID', message, [
        {'object_type': kind, 'object_id': identifier, 'field': field, 'message': message},
    ])


def required_text(raw, key, kind, identifier):
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        invalid(kind, identifier, key, f'{key} 缺失或格式错误')
    if len(value) > (255 if key == 'name' else 191):
        invalid(kind, identifier, key, f'{key} 超出存储长度限制')
    return value


def optional_text(raw, key, kind, identifier):
    if key not in raw:
        invalid(kind, identifier, key, f'{key} 未返回，无法证明字段可读；请检查飞书字段权限')
    if raw[key] is not None and not isinstance(raw[key], str):
        invalid(kind, identifier, key, f'{key} 应为文本或合法空值')
    limit = 128 if key == 'employee_no' else 255 if key == 'job_title' else 191
    if isinstance(raw[key], str) and len(raw[key]) > limit:
        invalid(kind, identifier, key, f'{key} 超出存储长度限制')


def validate_department(raw):
    identifier = required_text(raw, 'open_department_id', 'department', '')
    required_text(raw, 'name', 'department', identifier)
    optional_text(raw, 'leader_user_id', 'department', identifier)
    try:
        value = normalize_department(raw)
    except (RuntimeError, KeyError, TypeError):
        invalid('department', identifier, 'status/parent_department_id', '部门状态或父级不可读')
    if value.get('parent_unreadable'):
        invalid('department', identifier, 'parent_department_id', '部门父级不可读')
    return value


def validate_definitions(definitions, mappings):
    by_id = {item.get('id'): item for item in definitions}
    for key in ('permission_role', 'store_attribute'):
        identifier = mappings.get(key)
        definition = by_id.get(identifier)
        if key == 'store_attribute' and definition and definition.get('type') == 'TEXT':
            continue
        if not identifier or not definition or definition.get('type') != 'ENUMERATION':
            message = '门店属性必须映射到可读取的飞书文本或单选字段' if key == 'store_attribute' else '权限角色必须映射到可读取的飞书单选字段'
            raise InitializationFailure('INITIALIZATION_FIELD_MAPPING', message)
        options = definition.get('options', {}).get('options')
        if (not isinstance(options, list) or any(not isinstance(o, dict) or not isinstance(o.get('id'), str)
                or not o['id'] or len(o['id']) > 191 or not isinstance(o.get('value'), str)
                or not o['value'].strip() or len(o['value']) > 255 for o in options)
                or len({o['id'] for o in options}) != len(options)):
            raise InitializationFailure('INITIALIZATION_FIELD_MAPPING', f'{key} 的选项定义不可读')
    return {mappings[key]: by_id[mappings[key]] for key in ('permission_role', 'store_attribute')}


def validate_user(raw, mappings, definitions):
    identifier = required_text(raw, 'user_id', 'employee', '')
    required_text(raw, 'name', 'employee', identifier)
    for key in ('employee_no', 'job_title'):
        optional_text(raw, key, 'employee', identifier)
    # 飞书会省略未配置的直属上级；不能用每个人员是否返回此键判断权限。
    if 'leader_user_id' in raw:
        optional_text(raw, 'leader_user_id', 'employee', identifier)
    if raw.get('open_id') is not None and (not isinstance(raw['open_id'], str) or not raw['open_id']):
        invalid('employee', identifier, 'open_id', 'open_id 格式错误')
    if isinstance(raw.get('open_id'), str) and len(raw['open_id']) > 191:
        invalid('employee', identifier, 'open_id', 'open_id 超出存储长度限制')
    departments = raw.get('department_ids')
    if (not isinstance(departments, list) or any(not isinstance(d, str) or not d or len(d) > 191 for d in departments)
            or len(set(departments)) != len(departments)):
        invalid('employee', identifier, 'department_ids', '部门关系未返回或格式错误')
    orders = raw.get('orders')
    if orders is not None and (not isinstance(orders, list) or any(not isinstance(o, dict) for o in orders)):
        invalid('employee', identifier, 'orders', '主部门标记格式错误')
    if departments and (not isinstance(orders, list) or any(not isinstance(o, dict) for o in orders)):
        invalid('employee', identifier, 'orders', '有部门人员缺少可读取的主部门标记')
    if any(type(o.get('is_primary_dept')) is not bool or o.get('department_id') not in departments for o in (orders or [])):
        invalid('employee', identifier, 'orders', '部门顺序中的主部门标记或部门引用格式错误')
    status = raw.get('status')
    if isinstance(status, dict) and any(type(status[key]) is not bool for key in ('is_resigned', 'is_exited') if key in status):
        invalid('employee', identifier, 'status', '人员状态格式错误')
    primaries = [o.get('department_id') for o in (orders or []) if isinstance(o, dict) and o.get('is_primary_dept') is True]
    if (departments and (len(primaries) != 1 or primaries[0] not in departments)) or (not departments and primaries):
        invalid('employee', identifier, 'primary_department', '有部门人员必须有有效的唯一主部门；无部门人员不能具有主部门')
    if 'employee_type' not in raw:
        invalid('employee', identifier, 'employee_type', '员工类型未返回，无法证明字段可读')
    type_value = raw['employee_type']
    if type_value not in (None, '') and (type(type_value) not in (str, int)):
        invalid('employee', identifier, 'employee_type', '员工类型必须是枚举标识或合法空值')
    type_id = str(type_value) if type_value not in (None, '') else None
    type_options = mappings.get('employee_type_options') or {}
    if type_id and type_id not in type_options:
        invalid('employee', identifier, 'employee_type', '员工类型未在选项配置中定义')
    attrs = raw.get('custom_attrs')
    if not isinstance(attrs, list) or any(not isinstance(a, dict) for a in attrs):
        invalid('employee', identifier, 'custom_attrs', '自定义字段值未返回或格式错误')
    selected = {}
    for key in ('permission_role', 'store_attribute'):
        field_id = mappings[key]
        matches = [a for a in attrs if a.get('id') == field_id]
        if len(matches) != 1:
            invalid('employee', identifier, key, '自定义字段必须明确返回一次；缺失不能当作未填写')
        attr = matches[0]
        if key == 'store_attribute' and definitions[field_id]['type'] == 'TEXT':
            if attr.get('type') != 'TEXT' or not isinstance(attr.get('value'), dict) or 'text' not in attr['value']:
                invalid('employee', identifier, key, '门店属性需要明确返回文本字段及 text 值')
            text = attr['value']['text']
            if text is not None and (not isinstance(text, str) or len(text) > 255):
                invalid('employee', identifier, key, '门店属性必须为不超过 255 字符的文本或合法空值')
            selected[key] = (None, text)
            continue
        if attr.get('type') != 'ENUMERATION' or not isinstance(attr.get('value'), dict):
            invalid('employee', identifier, key, '需要单选字段对象，不能截取多选值或猜测格式')
        option_id, option_name = attr['value'].get('option_id'), attr['value'].get('option_value')
        if any(v is not None and not isinstance(v, str) for v in (option_id, option_name)):
            invalid('employee', identifier, key, '单选字段的标识和名称必须为文本')
        choices = {o['id']: o['value'] for o in definitions[field_id]['options']['options']}
        if option_id:
            if option_id not in choices or (option_name and choices[option_id] != option_name):
                invalid('employee', identifier, key, '未知选项或选项名称与定义不一致')
            selected[key] = (option_id, choices[option_id])
        else:
            if option_name:
                invalid('employee', identifier, key, '选项名称存在但缺少标识')
            selected[key] = (None, None)
    try:
        value = normalize_user(raw, mappings, set(type_options))
    except (RuntimeError, KeyError, TypeError):
        invalid('employee', identifier, 'status', '人员状态不可读或格式错误')
    value['employee_type_id'], value['employee_type_name'] = type_id, type_options.get(type_id)
    for key, (option_id, option_name) in selected.items():
        value[key + '_id'], value[key + '_name'] = option_id, option_name
    value['sync_quality'] = 'complete'
    return value


def validate_candidate(candidate):
    if not candidate.full or candidate.pending:
        raise InitializationFailure('INITIALIZATION_DATA_INVALID', '存在未读取成功或待核实的对象', [
            {'object_type': k, 'object_id': i, 'message': '对象读取失败'} for k, i in candidate.pending[:100]
        ])
    actual = set(candidate.employees)
    open_ids = {}
    for identifier, employee in candidate.employees.items():
        open_id = employee.get('open_id')
        if open_id and open_id in open_ids:
            invalid('employee', identifier, 'open_id', '不同人员返回了相同的 open_id')
        if open_id:
            open_ids[open_id] = identifier
    for identifier, department in candidate.departments.items():
        visited, current = set(), identifier
        while current is not None:
            if current in visited or current not in candidate.departments:
                invalid('department', identifier, 'parent_department_id', '部门层级存在环或断链')
            visited.add(current)
            current = candidate.departments[current]['parent_id']
        leader = department.get('leader_user_id')
        if leader and leader not in actual:
            invalid('department', identifier, 'leader_user_id', '部门负责人不在全量人员中')
    for identifier, employee in candidate.employees.items():
        if set(employee['department_ids']) - set(candidate.departments):
            invalid('employee', identifier, 'department_ids', '人员引用了未读取的部门')
        visited, current = set(), identifier
        while current:
            if current in visited or current not in actual:
                invalid('employee', identifier, 'leader_user_id', '直属上级关系存在环或无效引用')
            visited.add(current)
            current = candidate.employees[current].get('leader_user_id')
    candidate.coverage_status = 'complete'


class InitializationCollector(Collector):
    def __init__(self, api, mappings, definitions, progress):
        super().__init__(api, coverage_verified=True, progress=progress, custom_mappings=mappings)
        self.definitions = definitions

    def _progress(self, phase, result):
        if self.progress:
            departments = sum(not d.get('is_virtual_root') for d in result.departments.values())
            known = phase in ('validating', 'publishing')
            self.progress(phase=phase, departments_processed=departments, employees_processed=len(result.employees),
                          departments_total=departments if known else None,
                          employees_total=len(result.employees) if known else None)

    def _department(self, identifier):
        value = validate_department(self.api.detail('department', identifier))
        if value['id'] != identifier:
            invalid('department', identifier, 'id', '部门响应标识不一致')
        return value

    def _user(self, result, identifier):
        value = validate_user(self.api.detail('user', identifier), self.custom_mappings, self.definitions)
        if value['id'] != identifier:
            invalid('employee', identifier, 'id', '人员响应标识不一致')
        result.employees[identifier] = value

    def run(self):
        # 根部门接口成功才证明全员权限；不能由本地布尔配置替代。
        next(self.api.pages('users', department_id='0'))
        result = self.collect()
        self._progress('validating', result)
        validate_candidate(result)
        # 对象遍历期间出现变化时，重新确认根部门读取权限。
        next(self.api.pages('users', department_id='0'))
        return result
