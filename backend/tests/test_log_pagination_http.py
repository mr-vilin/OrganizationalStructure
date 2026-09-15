from datetime import datetime
from types import SimpleNamespace
from sqlalchemy import create_engine,event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from test_sync_persistence import sqlite_integer
from app.persistence.models import Base,ChangeLog
from app.dependencies import get_admin_identity,get_runtime
from app.main import app
from fastapi.testclient import TestClient


def test_http_log_cursor_is_string_and_all_pages_have_no_gaps():
    engine=create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False})
    @event.listens_for(engine,'connect')
    def configure(connection,_):
        connection.create_collation('utf8mb4_bin',lambda a,b:(a>b)-(a<b))
    Base.metadata.create_all(engine)
    sessions=sessionmaker(engine,expire_on_commit=False)
    with sessions.begin() as db:
        for index in range(1,206):
            db.add(ChangeLog(id=index,object_type='department',object_id=str(index),source='feishu',actor='sync',before_data=None,after_data={'name':str(index)},committed_at=datetime(2026,9,15)))
    app.dependency_overrides[get_admin_identity]=lambda:SimpleNamespace(open_id='admin')
    app.dependency_overrides[get_runtime]=lambda:SimpleNamespace(sessions=sessions)
    try:
        client=TestClient(app)
        ids=[];cursor=None
        for page in range(3):
            response=client.get('/admin/api/change-logs',params={'limit':100,**({'cursor':cursor} if cursor else {})})
            assert response.status_code==200 and response.headers['content-type'].startswith('application/json')
            body=response.json();ids.extend(item['id'] for item in body['data'])
            cursor=body['meta']['next_cursor']
            assert cursor is None or isinstance(cursor,str)
        assert cursor is None
        assert ids==list(range(205,0,-1))
    finally:
        app.dependency_overrides.clear();engine.dispose()
