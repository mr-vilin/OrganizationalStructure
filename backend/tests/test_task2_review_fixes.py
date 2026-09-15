import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from sqlalchemy import select, event
from sqlalchemy.exc import OperationalError
from fastapi.testclient import TestClient
from test_sync_persistence import sessions
from app.persistence.models import Department, Employee, EmployeeDepartment, LoginIdentity, AdminAllowlist, AdminSession, ChangeLog, SystemSetting, SyncJob, DatasetState, WorkerLease
from app.sync.collector import Candidate, normalize_user
from app.sync.publisher import Publisher
from app.feishu.oauth import OAuthService
from app.config import Settings


def oauth(sessions, user_id='u'):
    class API:
        def login(self, code): return {'open_id':'ou','user_id':user_id,'tenant_key':'t'}
    return OAuthService(sessions,Settings(session_secret='s'*32,feishu_app_id='a',feishu_app_secret='s',feishu_tenant_key='t'),API())


def seed_admin(sessions,status='active'):
    with sessions.begin() as db:
        db.add(AdminAllowlist(open_id='ou',created_at=datetime.now()))
        db.add(LoginIdentity(open_id='ou',user_id='u',tenant_key='t'))
        db.add(Employee(id='u',feishu_user_id='u',name='员工',status=status,sync_quality='complete'))
        db.add(AdminSession(id='session',open_id='ou',csrf_hash='hash',expires_at=datetime.now()+timedelta(days=1)))


def test_oauth_binding_mismatch_preserves_mapping_and_commits_safe_audit(sessions):
    seed_admin(sessions)
    service=oauth(sessions,'different-user'); state=service.begin()
    with pytest.raises(ValueError,match='LOGIN_IDENTITY_MISMATCH'): service.complete(state,state,'sensitive-code')
    with sessions() as db:
        assert db.get(LoginIdentity,'ou').user_id=='u'
        rows=list(db.scalars(select(ChangeLog)))
        assert rows[-1].after_data=={'error_code':'LOGIN_IDENTITY_MISMATCH'}
        assert 'sensitive-code' not in str(rows[-1].after_data)
        assert len(list(db.scalars(select(AdminSession))))==1


def test_unknown_department_and_dependent_employee_are_deferred_without_fake_facts(sessions):
    employee=normalize_user({'user_id':'new','name':'新员工','department_ids':['missing'],'status':{'is_resigned':False}})
    Publisher(sessions).publish(Candidate(employees={'new':employee},pending=[('department','missing')]))
    with sessions() as db:
        assert db.get(Department,'missing') is None
        assert db.get(Employee,'new') is None
        from app.persistence.models import PendingFact
        assert db.get(PendingFact,('employee','new')).normalized_data['department_ids']==['missing']


def test_existing_employee_retains_relations_when_new_ancestor_unreadable(sessions):
    with sessions.begin() as db:
        db.add(Department(id='old',feishu_department_id='old',name='旧部门',sync_quality='complete'));db.flush()
        db.add(Employee(id='u',feishu_user_id='u',name='员工',primary_department_id='old'));db.flush()
        db.add(EmployeeDepartment(employee_id='u',department_id='old'))
    employee=normalize_user({'user_id':'u','name':'员工','department_ids':['missing'],'status':{'is_resigned':False}})
    Publisher(sessions).publish(Candidate(employees={'u':employee},pending=[('department','missing')]))
    with sessions() as db:
        assert db.get(Employee,'u').primary_department_id=='old'
        assert db.get(Employee,'u').sync_quality=='pending_verification'
        assert db.get(EmployeeDepartment,('u','old')) is not None


def test_inactive_publication_revokes_session_and_blocks_new_login(sessions):
    from app.persistence.repositories import SqlIdentityRepository
    seed_admin(sessions)
    employee=normalize_user({'user_id':'u','name':'员工','department_ids':[],'status':{'is_resigned':True}})
    Publisher(sessions).publish(Candidate(employees={'u':employee}))
    with sessions() as db: assert db.get(AdminSession,'session').revoked_at is not None
    assert SqlIdentityRepository(sessions,'s'*32).authenticate_session('session',datetime.now()) is None
    service=oauth(sessions);state=service.begin()
    with pytest.raises(ValueError,match='EMPLOYEE_INACTIVE'):service.complete(state,state,'code')


def test_existing_inactive_mapping_blocks_unrevoked_session_but_pending_does_not(sessions):
    from app.persistence.repositories import SqlIdentityRepository
    seed_admin(sessions,'inactive')
    repo=SqlIdentityRepository(sessions,'s'*32)
    assert repo.authenticate_session('session',datetime.now()) is None
    with sessions.begin() as db:
        row=db.get(Employee,'u');row.status='active';row.sync_quality='pending_verification'
    assert repo.authenticate_session('session',datetime.now()) is not None


def test_inactive_revocation_rolls_back_with_publication_failure(sessions,monkeypatch):
    from app.stores.service import StoreAdminService
    seed_admin(sessions)
    def fail(db):
        assert db.get(AdminSession,'session').revoked_at is not None
        raise RuntimeError('injected')
    monkeypatch.setattr(StoreAdminService,'_rebuild_projection',fail)
    employee=normalize_user({'user_id':'u','name':'员工','department_ids':[],'status':{'is_resigned':True}})
    with pytest.raises(RuntimeError):Publisher(sessions).publish(Candidate(employees={'u':employee}))
    with sessions() as db:
        assert db.get(Employee,'u').status=='active'
        assert db.get(AdminSession,'session').revoked_at is None
        assert db.get(DatasetState,1).data_version==1


def test_coverage_reacceptance_records_evidence_clears_marker_and_queues_atomically(sessions):
    from app.sync.coverage import CoverageService
    with sessions.begin() as db: db.add(SystemSetting(key='coverage_invalidated',value='true'))
    service=CoverageService(sessions)
    result=service.accept('验收记录-2026-09','operator:ops',True,True)
    with sessions() as db:
        assert db.get(SystemSetting,'coverage_invalidated') is None
        assert json.loads(db.get(SystemSetting,'coverage_acceptance').value)['reference']=='验收记录-2026-09'
        assert db.get(SyncJob,result['job_id']).type=='reconcile'
        assert db.get(DatasetState,1).coverage_status!='complete'
        assert list(db.scalars(select(ChangeLog)))[-1].object_id=='coverage_acceptance'
    assert service.verified() is True


def test_database_error_and_framework_routes_use_safe_json():
    from app.main import app
    from app.dependencies import get_public_identity,get_read_service
    class Reads:
        def status(self): raise OperationalError('SELECT secret',{'password':'sensitive'},Exception('sensitive'))
    app.dependency_overrides[get_public_identity]=lambda: object()
    app.dependency_overrides[get_read_service]=lambda: Reads()
    try:
        client=TestClient(app,raise_server_exceptions=False)
        response=client.get('/api/v1/status')
        assert response.status_code==503
        assert response.json()['error']['code']=='DATABASE_UNAVAILABLE'
        assert 'sensitive' not in response.text and 'SELECT' not in response.text
        for response in (client.get('/nonexistent'),client.post('/health/live')):
            assert response.status_code in (404,405)
            assert 'error' in response.json()
    finally:app.dependency_overrides.clear()


def test_engine_hides_query_parameters_without_opening_database():
    from app.persistence.database import create_mysql_engine
    engine=create_mysql_engine('mysql+pymysql://unused:unused@localhost/unused')
    try: assert engine.hide_parameters is True
    finally:engine.dispose()


def test_missing_field_error_code_survives_worker_failure(sessions):
    from app.sync.worker import Worker,utcnow
    from app.persistence.repositories import SqlSyncJobRepository
    with sessions.begin() as db: db.add(WorkerLease(id=1,generation=0))
    job,_=SqlSyncJobRepository(sessions).submit('full',None,'test',utcnow())
    worker=Worker(sessions,None);worker.acquire(utcnow())
    job=worker.jobs.claim_next(utcnow(),utcnow()+timedelta(minutes=2))
    worker._fail_job(job,RuntimeError('FEISHU_PARENT_UNREADABLE'))
    with sessions() as db: assert db.get(SyncJob,job.id).error_code=='FEISHU_PARENT_UNREADABLE'


def test_coverage_audit_failure_rolls_back_marker_evidence_and_queue(sessions):
    from app.sync.coverage import CoverageService
    with sessions.begin() as db: db.add(SystemSetting(key='coverage_invalidated',value='true'))
    def reject_audit(mapper,connection,target):
        if target.object_id=='coverage_acceptance': raise RuntimeError('audit-failed')
    event.listen(ChangeLog,'before_insert',reject_audit)
    try:
        with pytest.raises(RuntimeError,match='audit-failed'): CoverageService(sessions).accept('evidence','operator',True,True)
    finally:event.remove(ChangeLog,'before_insert',reject_audit)
    with sessions() as db:
        assert db.get(SystemSetting,'coverage_invalidated') is not None
        assert db.get(SystemSetting,'coverage_acceptance') is None
        assert list(db.scalars(select(SyncJob)))==[]


def test_pending_employee_publishes_after_authoritative_ancestor_resolution(sessions):
    from app.persistence.models import PendingFact
    employee=normalize_user({'user_id':'u','name':'员工','department_ids':['a'],'status':{'is_resigned':False}})
    Publisher(sessions).publish(Candidate(employees={'u':employee},pending=[('department','a')]))
    department={'id':'a','feishu_department_id':'a','parent_id':None,'name':'已确认部门','status':'active','sync_quality':'complete','is_virtual_root':False}
    Publisher(sessions).publish(Candidate(departments={'a':department},employees={'u':employee}))
    with sessions() as db:
        assert db.get(Department,'a').name=='已确认部门'
        assert db.get(EmployeeDepartment,('u','a')) is not None
        assert list(db.scalars(select(PendingFact)))==[]


def test_coverage_cli_uses_bound_config_and_outputs_queued_job(sessions,monkeypatch,capsys):
    from app.sync.coverage import main
    monkeypatch.setattr('app.dependencies.get_runtime',lambda:SimpleNamespace(sessions=sessions))
    monkeypatch.setattr('app.config.get_settings',lambda:Settings(feishu_app_id='a',feishu_tenant_key='t'))
    main(['--reference','accepted-2026','--actor','ops','--all-members-verified','--departmentless-verified'])
    output=json.loads(capsys.readouterr().out)
    assert output['status']=='queued'
    with sessions() as db: assert db.get(SyncJob,output['job_id']) is not None


def test_old_collection_cannot_restore_complete_after_new_acceptance(sessions):
    from app.sync.coverage import CoverageService
    CoverageService(sessions).accept('new-evidence','ops',True,True)
    candidate=Candidate(full=True,coverage_status='complete')
    Publisher(sessions).publish(candidate)
    with sessions() as db: assert db.get(DatasetState,1).coverage_status=='unknown'


def test_new_verified_collection_can_restore_complete(sessions):
    from app.sync.coverage import CoverageService
    CoverageService(sessions).accept('new-evidence','ops',True,True)
    Publisher(sessions).publish(Candidate(full=True,coverage_status='complete',collection_started_at=datetime.now(timezone.utc).isoformat()))
    with sessions() as db: assert db.get(DatasetState,1).coverage_status=='complete'


def test_existing_department_with_unknown_new_parent_retains_fact_and_projects_unknown(sessions):
    with sessions.begin() as db:
        db.add(Department(id='a',feishu_department_id='a',name='真实部门',sync_quality='complete'));db.flush()
        db.add(Employee(id='u',feishu_user_id='u',name='员工',primary_department_id='a',sync_quality='complete'));db.flush()
        db.add(EmployeeDepartment(employee_id='u',department_id='a'))
    department={'id':'a','feishu_department_id':'a','parent_id':'missing','name':'改名部门','status':'active','sync_quality':'complete','is_virtual_root':False}
    Publisher(sessions).publish(Candidate(departments={'a':department},pending=[('department','missing')]))
    with sessions() as db:
        assert db.get(Department,'a').name=='真实部门'
        assert db.get(Department,'a').parent_id is None
        assert db.get(Employee,'u').primary_store_status=='unknown'
