import pytest


def test_partial_page_failure_never_returns_candidate():
    from app.sync.collector import Collector
    class API:
        def pages(self, resource, **params):
            yield {"department_ids": ["a"], "user_ids": [], "group_ids": []}
            raise RuntimeError("PERMISSION_DENIED")
    with pytest.raises(RuntimeError, match="PERMISSION_DENIED"):
        Collector(API()).collect()


def test_missing_primary_and_conflicting_orders_are_not_inferred():
    from app.sync.collector import normalize_user
    raw = {"user_id": "u", "name": "员工", "department_ids": ["a", "b"], "status": {"is_resigned": False}}
    assert normalize_user(raw)["primary_department_id"] is None
    raw["orders"] = [{"department_id": "a", "is_primary_dept": True}, {"department_id": "b", "is_primary_dept": True}]
    assert normalize_user(raw)["sync_quality"] == "inconsistent"


def test_unreadable_details_are_pending_and_deleted_event_cannot_override_current_fact():
    from app.sync.collector import Collector
    class API:
        def detail(self, kind, identifier):
            if identifier == "missing":
                raise RuntimeError("PERMISSION_DENIED")
            return {"user_id": identifier, "name": "恢复员工", "department_ids": [], "status": {"is_resigned": False}}
    candidate = Collector(API()).event("contact.user.deleted_v3", "restored")
    assert candidate.employees["restored"]["status"] == "active"
    assert Collector(API()).event("contact.user.deleted_v3", "missing").pending == [("employee", "missing")]


def test_unreadable_ancestor_and_inconsistent_primary_stay_unknown():
    from app.directory.domain import Department, Employee, Membership, resolve_employee_stores
    departments = {"a": Department("a", None, False, sync_quality="pending_verification")}
    assert resolve_employee_stores(Employee("u", "active", "a"), [Membership("u", "a")], departments).primary_store_status == "unknown"
    assert resolve_employee_stores(Employee("u", "active", None, "inconsistent"), [Membership("u", "a")], departments).primary_store_status == "inconsistent"


def test_full_collection_traverses_root_and_event_closes_virtual_root():
    from app.sync.collector import Collector
    class API:
        def pages(self,resource,**params):
            if resource=='scopes': yield {'department_ids':[], 'user_ids':[], 'group_ids':[]}
            elif resource=='children': yield {'items':[{'open_department_id':'a'}] if params['department_id']=='0' else []}
            else: yield {'items':[{'user_id':'u'}] if params['department_id']=='a' else []}
        def detail(self,kind,identifier):
            if kind=='user': return {'user_id':'u','name':'员工','department_ids':['a'],'status':{'is_resigned':False}}
            assert identifier=='a'
            return {'open_department_id':'a','parent_department_id':'0','name':'部门','status':{'is_deleted':False}}
    assert set(Collector(API()).collect().employees)=={'u'}
    assert Collector(API()).event('contact.user.updated_v3','u').departments['0']['parent_id'] is None


def test_collection_reports_real_counts_with_unknown_totals():
    from app.sync.collector import Collector
    class API:
        def pages(self,resource,**params):
            yield {'department_ids':[], 'user_ids':[], 'group_ids':[]} if resource=='scopes' else {'items':[]}
    observations=[]
    collector=Collector(API(),progress=lambda **value: observations.append(value))
    collector.collect()
    assert observations[-1]['departments_processed']==1
    assert observations[-1]['employees_processed']==0
    assert observations[-1]['departments_total'] is None


def test_missing_department_field_is_unreadable_not_empty_membership():
    from app.sync.collector import Collector
    class API:
        def detail(self,kind,identifier): return {'user_id':'u','name':'员工'}
    result=Collector(API()).event('contact.user.updated_v3','u')
    assert result.employees=={}
    assert result.pending==[('employee','u')]


def test_subtree_rechecks_former_members_after_move_and_keeps_other_memberships():
    from app.sync.collector import Collector
    class API:
        def pages(self,resource,**params):
            yield {'department_ids':['old'],'user_ids':[],'group_ids':[]} if resource=='scopes' else {'items':[]}
        def detail(self,kind,identifier):
            if kind=='user': return {'user_id':'u','name':'移动员工','department_ids':['new','other'],'status':{'is_resigned':False}}
            return {'open_department_id':identifier,'parent_department_id':'new' if identifier=='moved' else '0','name':identifier,'status':{'is_deleted':False}}
    result=Collector(API()).collect('old',previous_departments={'moved'},previous_users={'u'})
    assert result.employees['u']['department_ids']==['new','other']
    assert result.departments['moved']['parent_id']=='new'


def test_missing_lifecycle_or_parent_is_not_inferred_as_active_or_root():
    from app.sync.collector import normalize_user, normalize_department
    with pytest.raises(RuntimeError): normalize_user({'user_id':'u','name':'员工','department_ids':[]})
    with pytest.raises(RuntimeError): normalize_department({'open_department_id':'a','name':'部门','status':{'is_deleted':False}})
