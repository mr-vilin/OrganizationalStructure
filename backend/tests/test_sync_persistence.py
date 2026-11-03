"""SQLite 仅验证事务业务；不替代 MySQL 行锁并发验收。"""
from datetime import datetime, timedelta
import pytest
from sqlalchemy import select
from app.persistence.models import DatasetState, Department, Employee, EmployeeDepartment, StoreProfile, EmployeeStore, SyncJob


@pytest.fixture
def sessions(sqlite_sessions):
    return sqlite_sessions


def test_preview_counts_descendant_changes_but_excludes_nested_store(sessions):
    from app.stores.service import StoreAdminService
    from app.stores.domain import StorePatch
    with sessions.begin() as db:
        for identifier, parent in [('a', None), ('b', 'a'), ('c', 'b')]:
            db.add(Department(id=identifier, feishu_department_id=identifier, parent_id=parent, name=identifier, sync_quality='complete'))
            db.flush()
        db.add(StoreProfile(department_id='c', is_store=True))
        for identifier, department in [('u', 'b'), ('v', 'c')]:
            db.add(Employee(id=identifier, feishu_user_id=identifier, name=identifier, primary_department_id=department, sync_quality='complete'))
            db.flush()
            db.add(EmployeeDepartment(employee_id=identifier, department_id=department))
    assert StoreAdminService(sessions).preview([StorePatch('a', True)], 1)['affected_employee_count'] == 1
    StoreAdminService(sessions).apply([StorePatch('a', True)], 1, 'admin:a', datetime.now())
    with sessions() as db:
        assert db.get(EmployeeStore, ('u', 'a')).path == ['b', 'a']


def test_publication_is_atomic_preserves_missing_and_noop_version(sessions):
    from app.sync.publisher import Publisher
    from app.sync.collector import Candidate
    with sessions.begin() as db:
        db.add(SyncJob(id='job', type='full', requested_by='test', status='running', lease_generation=1, lease_expires_at=datetime.now()+timedelta(hours=1), created_at=datetime.now(), updated_at=datetime.now()))
    candidate = Candidate(departments={'a': {'id':'a', 'feishu_department_id':'a', 'parent_id':None, 'name':'门店', 'status':'active', 'sync_quality':'complete', 'is_virtual_root':False}}, full=True)
    publisher = Publisher(sessions)
    publisher.publish(candidate, 'job', 1)
    with sessions() as db:
        assert db.get(DatasetState, 1).data_version == 2
        assert db.get(SyncJob, 'job').status == 'succeeded'
    with sessions.begin() as db:
        job=db.get(SyncJob,'job'); job.status='running'; job.lease_expires_at=datetime.now()+timedelta(hours=1)
    publisher.publish(candidate, 'job', 1)
    with sessions() as db:
        assert db.get(DatasetState, 1).data_version == 2
    with pytest.raises(ValueError, match='STALE_LEASE'):
        publisher.publish(Candidate(), 'job', 0)


def test_schedule_default_validation_and_daily_deduplication(sessions):
    from app.sync.settings import ScheduleService
    schedule = ScheduleService(sessions)
    assert schedule.get()['local_time'] == '03:00'
    assert schedule.due(datetime(2026,9,14,19,0)) is True
    assert schedule.due(datetime(2026,9,14,19,1)) is False
    with pytest.raises(ValueError):
        schedule.put({'enabled': True, 'local_time':'25:00', 'timezone':'Asia/Shanghai'}, 'admin')


def test_oauth_state_single_use_bound_to_browser_and_identity(sessions):
    from app.feishu.oauth import OAuthService
    from app.config import Settings
    from app.persistence.models import AdminAllowlist
    settings=Settings(session_secret='s'*32, feishu_app_id='a', feishu_app_secret='secret', feishu_redirect_uri='https://example/admin/auth/callback', feishu_tenant_key='t')
    class API:
        def login(self, code): return {'open_id':'ou', 'user_id':'u', 'tenant_key':'t'}
    with sessions.begin() as db: db.add(AdminAllowlist(open_id='ou', created_at=datetime.now()))
    service=OAuthService(sessions, settings, API())
    state=service.begin()
    with pytest.raises(ValueError): service.complete(state, 'wrong', 'code')
    session, csrf, token=service.complete(state, state, 'code')
    assert session.open_id == 'ou' and csrf
    assert token != session.token_digest
    with pytest.raises(ValueError): service.complete(state, state, 'code')


def test_employee_detail_explains_store_path_and_department_notes(sessions):
    from app.persistence.read_service import SqlReadService
    with sessions.begin() as db:
        db.add(Department(id='a',feishu_department_id='a',name='门店',sync_quality='complete')); db.flush()
        db.add(StoreProfile(department_id='a',is_store=True,notes='备注'))
        db.add(Employee(id='u',feishu_user_id='u',name='员工',primary_department_id='a')); db.flush()
        db.add(EmployeeDepartment(employee_id='u',department_id='a'))
        db.add(EmployeeStore(employee_id='u',store_id='a',is_primary=True,path=['a']))
    reads=SqlReadService(sessions,'s'*32)
    assert reads.get_department('a')[0]['notes']=='备注'
    employee=reads.get_employee('u')[0]
    assert employee['stores'][0]['path']==['a']
    assert employee['stores'][0]['name']=='门店'
    assert employee['departments'][0]['path']==['门店']


def test_change_log_filters_actor_action_and_utc_bounds(sessions):
    from app.admin.router import change_logs
    from app.persistence.models import ChangeLog
    from types import SimpleNamespace
    from datetime import timezone
    with sessions.begin() as db:
        db.add(ChangeLog(object_type='store',object_id='a',source='admin',actor='admin:a',before_data=None,after_data={'is_store':True},committed_at=datetime(2026,9,15,1)))
        db.add(ChangeLog(object_type='store',object_id='b',source='admin',actor='admin:b',before_data={},after_data={},committed_at=datetime(2026,9,15,2)))
    data=change_logs(actor='admin:a',action='create',committed_after=datetime(2026,9,15,tzinfo=timezone.utc),committed_before=None,limit=100,cursor=None,identity=None,runtime=SimpleNamespace(sessions=sessions))
    assert [row['object_id'] for row in data['data']]==['a']


def test_failed_events_are_visible_and_retry_rejects_missing_identifier(sessions):
    from app.admin.router import list_events, retry_event
    from app.persistence.models import EventInbox
    from types import SimpleNamespace
    from fastapi import HTTPException
    with sessions.begin() as db:
        db.add(EventInbox(event_id='e',event_type='contact.user.deleted_v3',object_id=None,payload={'error_code':'EVENT_OBJECT_ID_MISSING'},status='failed',received_at=datetime.now()))
    runtime=SimpleNamespace(sessions=sessions)
    result=list_events(status='failed',limit=100,cursor=None,identity=None,runtime=runtime)
    assert result['data'][0]['error_code']=='EVENT_OBJECT_ID_MISSING'
    with pytest.raises(HTTPException): retry_event('e',(SimpleNamespace(open_id='admin'),None),runtime)


def test_publication_cycle_failure_rolls_back_all_facts_and_version(sessions):
    from app.sync.publisher import Publisher
    from app.sync.collector import Candidate
    def department(identifier,parent): return {'id':identifier,'feishu_department_id':identifier,'parent_id':parent,'name':identifier,'status':'active','sync_quality':'complete','is_virtual_root':False}
    candidate=Candidate(departments={'safe':department('safe',None),'a':department('a','b'),'b':department('b','a')})
    with pytest.raises(RuntimeError,match='DEPARTMENT_CYCLE'): Publisher(sessions).publish(candidate)
    with sessions() as db:
        assert list(db.scalars(select(Department)))==[]
        assert db.get(DatasetState,1).data_version==1


def test_database_connection_binding_rejects_different_application_or_tenant(sessions):
    from app.feishu.binding import bind_connection
    bind_connection(sessions,'app','tenant')
    bind_connection(sessions,'app','tenant')
    with pytest.raises(RuntimeError,match='CONFIG_BINDING_MISMATCH'): bind_connection(sessions,'other','tenant')
    with pytest.raises(RuntimeError,match='CONFIG_BINDING_MISMATCH'): bind_connection(sessions,'app','other')


def test_partial_department_update_cannot_create_cycle_with_existing_parent(sessions):
    from app.sync.publisher import Publisher
    from app.sync.collector import Candidate
    with sessions.begin() as db:
        db.add(Department(id='a',feishu_department_id='a',name='a',sync_quality='complete'));db.flush()
        db.add(Department(id='b',feishu_department_id='b',name='b',parent_id='a',sync_quality='complete'))
    candidate=Candidate(departments={'a':{'id':'a','feishu_department_id':'a','parent_id':'b','name':'a','status':'active','sync_quality':'complete','is_virtual_root':False}})
    with pytest.raises(RuntimeError,match='DEPARTMENT_CYCLE'): Publisher(sessions).publish(candidate)
    with sessions() as db: assert db.get(Department,'a').parent_id is None
