"""受运维主机权限约束的覆盖重新验收 CLI；不直接发布 complete。"""
import argparse
import json
import secrets
from datetime import datetime,timezone
from sqlalchemy import select,delete
from app.persistence.models import SystemSetting,DatasetState,SyncJob,ChangeLog


class CoverageService:
    def __init__(self,sessions): self.sessions=sessions

    def get(self):
        with self.sessions() as db:
            row=db.get(SystemSetting,'coverage_acceptance')
            return json.loads(row.value) if row else None

    def verified(self,fallback=False):
        with self.sessions() as db:
            if db.get(SystemSetting,'coverage_invalidated'): return False
            row=db.get(SystemSetting,'coverage_acceptance')
            if row is None: return fallback
            value=json.loads(row.value)
            return bool(value.get('reference') and value.get('all_members_verified') is True and value.get('departmentless_verified') is True)

    def accept(self,reference,actor,all_members_verified,departmentless_verified):
        if not reference or not reference.strip() or len(reference)>2000 or not actor or not actor.strip() or len(actor)>255 or all_members_verified is not True or departmentless_verified is not True:
            raise ValueError('COVERAGE_ACCEPTANCE_INVALID')
        now=datetime.now(timezone.utc).replace(tzinfo=None)
        with self.sessions.begin() as db:
            lock=db.scalar(select(SystemSetting).where(SystemSetting.key=='task_queue_lock').with_for_update())
            if lock is None: raise RuntimeError('DATABASE_SCHEMA_INCOMPLETE')
            state=db.scalar(select(DatasetState).where(DatasetState.id==1).with_for_update())
            if state is None: raise RuntimeError('DATABASE_SCHEMA_INCOMPLETE')
            row=db.get(SystemSetting,'coverage_acceptance')
            before=json.loads(row.value) if row else None
            after={'reference':reference.strip(),'all_members_verified':True,'departmentless_verified':True,'accepted_by':actor.strip(),'updated_at':now.isoformat()+'+00:00'}
            db.merge(SystemSetting(key='coverage_acceptance',value=json.dumps(after,ensure_ascii=False)))
            db.execute(delete(SystemSetting).where(SystemSetting.key=='coverage_invalidated'))
            state.coverage_status='unknown'
            # 不复用正在执行的旧采集；始终保存一个验收后的全量核对。
            job=SyncJob(id=secrets.token_urlsafe(12),type='reconcile',requested_by=actor.strip(),status='queued',created_at=now,updated_at=now)
            db.add(job)
            db.add(ChangeLog(object_type='settings',object_id='coverage_acceptance',source='cli',actor=actor.strip(),job_id=job.id,before_data=before,after_data=after,committed_at=now))
            return {'job_id':job.id,**after}


def main(argv=None):
    parser=argparse.ArgumentParser(description='记录企业覆盖重新验收依据，并安排全量核对')
    parser.add_argument('--reference',required=True,help='验收记录编号或摘要，禁止填写秘密')
    parser.add_argument('--actor',required=True,help='运维操作人标识')
    parser.add_argument('--all-members-verified',action='store_true',required=True)
    parser.add_argument('--departmentless-verified',action='store_true',required=True)
    args=parser.parse_args(argv)
    from app.dependencies import get_runtime
    from app.config import get_settings
    from app.feishu.binding import bind_connection
    runtime,settings=get_runtime(),get_settings()
    if not runtime: parser.error('数据库与会话密钥尚未配置')
    try:
        bind_connection(runtime.sessions,settings.feishu_app_id,settings.feishu_tenant_key)
        result=CoverageService(runtime.sessions).accept(args.reference,args.actor,args.all_members_verified,args.departmentless_verified)
    except Exception:
        # CLI 不输出 SQL、异常原文或配置。
        raise SystemExit('覆盖验收操作失败；未确认提交，请检查配置及数据库状态') from None
    print(json.dumps({'job_id':result['job_id'],'status':'queued'},ensure_ascii=False))


if __name__=='__main__': main()
