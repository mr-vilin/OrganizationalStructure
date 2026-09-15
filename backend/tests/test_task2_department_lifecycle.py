import pytest
from sqlalchemy import select,event
from test_sync_persistence import sessions
from test_task2_review_fixes import seed_admin
from app.persistence.models import Department,Employee,EmployeeDepartment,EmployeeStore,StoreProfile,AdminSession,ChangeLog,DatasetState,PendingFact
from app.sync.collector import Candidate,Collector,normalize_department,normalize_user
from app.sync.publisher import Publisher
from app.stores.service import StoreAdminService


def seed(sessions):
    seed_admin(sessions)
    with sessions.begin() as db:
        for identifier,parent in [('s',None),('d','s'),('child','d'),('part',None)]:
            db.add(Department(id=identifier,feishu_department_id=identifier,name=identifier,parent_id=parent,sync_quality='complete'));db.flush()
        db.add(StoreProfile(department_id='s',is_store=True))
        db.add(StoreProfile(department_id='part',is_store=True))
        db.get(Employee,'u').primary_department_id='d'
        db.add(EmployeeDepartment(employee_id='u',department_id='d',is_primary=True))
        db.add(EmployeeDepartment(employee_id='u',department_id='part'))
        db.add(Employee(id='v',feishu_user_id='v',name='子部门员工',primary_department_id='child',sync_quality='complete'));db.flush()
        db.add(EmployeeDepartment(employee_id='v',department_id='child',is_primary=True));db.flush()
        StoreAdminService._rebuild_projection(db)


def deleted(parent='s'):
    return normalize_department({'open_department_id':'d','name':'新的名字','parent_department_id':parent,'status':{'is_deleted':True}})


@pytest.mark.parametrize('parent',['s','missing',None])
def test_department_delete_ends_only_direct_relationship_and_does_not_revoke_employee(sessions,parent):
    seed(sessions)
    Publisher(sessions).publish(Candidate(departments={'d':deleted(parent)}))
    with sessions() as db:
        assert db.get(Department,'d').status=='inactive'
        assert db.get(EmployeeDepartment,('u','d')).active is False
        assert db.get(EmployeeDepartment,('u','part')).active is True
        assert db.get(Employee,'u').status=='active'
        assert db.get(AdminSession,'session').revoked_at is None
        assert db.get(EmployeeStore,('u','s')) is None
        assert db.get(EmployeeStore,('u','part')) is not None
        assert db.get(EmployeeStore,('v','s')) is None
        assert db.get(Department,'child').status=='active'
        assert db.get(Employee,'v').primary_store_status=='unknown'
        if parent!='s':
            assert db.get(Department,'d').parent_id=='s'
            assert db.get(Department,'d').name=='d'


def test_employee_recheck_does_not_reactivate_deleted_department_until_explicit_restore(sessions):
    seed(sessions)
    Publisher(sessions).publish(Candidate(departments={'d':deleted()}))
    user=normalize_user({'user_id':'u','name':'员工','department_ids':['d','part'],'orders':[{'department_id':'d','is_primary_dept':True}],'status':{'is_resigned':False}})
    Publisher(sessions).publish(Candidate(employees={'u':user}))
    with sessions() as db:assert db.get(EmployeeDepartment,('u','d')).active is False
    restored=normalize_department({'open_department_id':'d','name':'d','parent_department_id':'s','status':{'is_deleted':False}})
    Publisher(sessions).publish(Candidate(departments={'d':restored}))
    with sessions() as db:assert db.get(EmployeeDepartment,('u','d')).active is False
    Publisher(sessions).publish(Candidate(employees={'u':user}))
    with sessions() as db:assert db.get(EmployeeDepartment,('u','d')).active is True


@pytest.mark.parametrize('raw',[
    {'open_department_id':'d','name':'d','parent_department_id':'s'},
    {'open_department_id':'d','name':'d','status':{'is_deleted':False}},
    {'open_department_id':'different','name':'d','parent_department_id':'s','status':{'is_deleted':True}},
])
def test_missing_fields_or_wrong_source_never_guess_department_deletion(sessions,raw):
    seed(sessions)
    class API:
        def detail(self,kind,identifier): return raw
    Publisher(sessions).publish(Collector(API()).event('contact.department.deleted_v3','d'))
    with sessions() as db:
        assert db.get(Department,'d').status=='active'
        assert db.get(EmployeeDepartment,('u','d')).active is True
        assert db.get(AdminSession,'session').revoked_at is None


def test_department_delete_relation_audit_failure_rolls_back_all(sessions):
    seed(sessions)
    def reject(mapper,connection,target):
        if target.object_type=='membership':raise RuntimeError('audit-failed')
    event.listen(ChangeLog,'before_insert',reject)
    try:
        with pytest.raises(RuntimeError,match='audit-failed'):Publisher(sessions).publish(Candidate(departments={'d':deleted()}))
    finally:event.remove(ChangeLog,'before_insert',reject)
    with sessions() as db:
        assert db.get(Department,'d').status=='active'
        assert db.get(EmployeeDepartment,('u','d')).active is True
        assert db.get(EmployeeStore,('u','s')) is not None
        assert db.get(DatasetState,1).data_version==1


def test_repeated_inactive_detail_does_not_increment_version(sessions):
    seed(sessions)
    candidate=Candidate(departments={'d':deleted('missing')})
    Publisher(sessions).publish(candidate)
    with sessions() as db:first=db.get(DatasetState,1).data_version
    Publisher(sessions).publish(candidate)
    with sessions() as db:assert db.get(DatasetState,1).data_version==first


def test_valid_other_membership_path_does_not_cross_deleted_ancestor(sessions):
    seed(sessions)
    with sessions.begin() as db:db.add(EmployeeDepartment(employee_id='v',department_id='s'))
    Publisher(sessions).publish(Candidate(departments={'d':deleted()}))
    with sessions() as db:
        assert db.get(EmployeeStore,('v','s')).path==['s']
        assert db.get(EmployeeStore,('v','s')).is_primary is False


def test_new_deleted_department_without_parent_stays_pending_not_fake_root(sessions):
    value=normalize_department({'open_department_id':'new','name':'删除部门','status':{'is_deleted':True}})
    Publisher(sessions).publish(Candidate(departments={'new':value}))
    with sessions() as db:
        assert db.get(Department,'new') is None
        assert db.get(PendingFact,('department','new')).normalized_data['status']=='inactive'
