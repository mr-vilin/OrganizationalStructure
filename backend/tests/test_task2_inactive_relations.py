from datetime import datetime
import pytest
from sqlalchemy import select,event
from test_sync_persistence import sessions
from test_task2_review_fixes import seed_admin
from app.sync.collector import Candidate,Collector,normalize_user
from app.sync.publisher import Publisher
from app.persistence.models import Department,Employee,EmployeeDepartment,EmployeeStore,StoreProfile,AdminSession,PendingFact,ChangeLog,DatasetState


def seed_relations(sessions):
    seed_admin(sessions)
    with sessions.begin() as db:
        db.add(Department(id='old',feishu_department_id='old',name='旧部门',sync_quality='complete'));db.flush()
        db.add(StoreProfile(department_id='old',is_store=True))
        db.get(Employee,'u').primary_department_id='old'
        db.add(EmployeeDepartment(employee_id='u',department_id='old',is_primary=True))
        db.add(EmployeeStore(employee_id='u',store_id='old',is_primary=True,path=['old']))


def inactive():
    return normalize_user({'user_id':'u','name':'上游新姓名','department_ids':['missing'],'status':{'is_resigned':True}})


def test_confirmed_inactive_with_unreadable_department_revokes_and_ends_current_relations(sessions):
    seed_relations(sessions)
    Publisher(sessions).publish(Candidate(employees={'u':inactive()},pending=[('department','missing')]))
    with sessions() as db:
        assert db.get(Employee,'u').status=='inactive'
        assert db.get(Employee,'u').name=='员工'
        assert db.get(EmployeeDepartment,('u','old')).active is False
        assert db.get(EmployeeStore,('u','old')) is None
        assert db.get(AdminSession,'session').revoked_at is not None
        assert db.get(Department,'missing') is None
        assert db.get(PendingFact,('employee','u')).normalized_data['department_ids']==['missing']


def test_missing_membership_field_does_not_discard_explicit_inactive(sessions):
    seed_relations(sessions)
    class API:
        def detail(self,kind,identifier): return {'user_id':'u','name':'员工','status':{'is_exited':True}}
    candidate=Collector(API()).event('contact.user.updated_v3','u')
    Publisher(sessions).publish(candidate)
    with sessions() as db:
        assert db.get(Employee,'u').status=='inactive'
        assert db.get(AdminSession,'session').revoked_at is not None
        assert db.get(EmployeeDepartment,('u','old')).active is False


@pytest.mark.parametrize('raw',[
    {'user_id':'u','name':'员工','department_ids':[]},
    {'user_id':'u','name':'员工','status':{'is_resigned':'true'}},
    {'user_id':'other','name':'员工','status':{'is_resigned':True}},
])
def test_unreadable_lifecycle_or_wrong_source_id_cannot_revoke(sessions,raw):
    seed_relations(sessions)
    class API:
        def detail(self,kind,identifier):return raw
    Publisher(sessions).publish(Collector(API()).event('contact.user.deleted_v3','u'))
    with sessions() as db:
        assert db.get(Employee,'u').status=='active'
        assert db.get(AdminSession,'session').revoked_at is None
        assert db.get(EmployeeDepartment,('u','old')).active is True


@pytest.mark.parametrize('failure_target',['membership','security'])
def test_inactive_relations_and_revocation_roll_back_on_audit_failure(sessions,failure_target):
    seed_relations(sessions)
    def reject(mapper,connection,target):
        if target.object_type==failure_target: raise RuntimeError('injected-audit-failure')
    event.listen(ChangeLog,'before_insert',reject)
    try:
        with pytest.raises(RuntimeError,match='injected-audit-failure'):
            Publisher(sessions).publish(Candidate(employees={'u':inactive()},pending=[('department','missing')]))
    finally:event.remove(ChangeLog,'before_insert',reject)
    with sessions() as db:
        assert db.get(Employee,'u').status=='active'
        assert db.get(EmployeeDepartment,('u','old')).active is True
        assert db.get(EmployeeStore,('u','old')) is not None
        assert db.get(AdminSession,'session').revoked_at is None
        assert db.get(DatasetState,1).data_version==1


def test_new_inactive_employee_with_incomplete_relations_has_no_fake_department(sessions):
    Publisher(sessions).publish(Candidate(employees={'u':inactive()},pending=[('department','missing')]))
    with sessions() as db:
        employee=db.get(Employee,'u')
        assert employee is not None and employee.status=='inactive'
        assert employee.primary_department_id is None
        assert list(db.scalars(select(Department)))==[]
        assert list(db.scalars(select(EmployeeDepartment)))==[]


def test_parent_field_missing_does_not_block_user_exit(sessions):
    seed_relations(sessions)
    class API:
        def detail(self,kind,identifier):
            if kind=='user':return {'user_id':'u','name':'员工','department_ids':['new'],'status':{'is_resigned':True}}
            return {'open_department_id':'new','name':'新部门','status':{'is_deleted':False}}
    Publisher(sessions).publish(Collector(API()).event('contact.user.updated_v3','u'))
    with sessions() as db:
        assert db.get(Employee,'u').status=='inactive'
        assert db.get(Department,'new') is None
        assert db.get(AdminSession,'session').revoked_at is not None


def test_relation_write_failure_rolls_back_employee_and_sessions(sessions):
    seed_relations(sessions)
    def reject(mapper,connection,target):raise RuntimeError('relation-failed')
    event.listen(EmployeeDepartment,'before_update',reject)
    try:
        with pytest.raises(RuntimeError,match='relation-failed'):
            Publisher(sessions).publish(Candidate(employees={'u':inactive()},pending=[('department','missing')]))
    finally:event.remove(EmployeeDepartment,'before_update',reject)
    with sessions() as db:
        assert db.get(Employee,'u').status=='active'
        assert db.get(EmployeeDepartment,('u','old')).active is True
        assert db.get(AdminSession,'session').revoked_at is None
        assert db.get(DatasetState,1).data_version==1
