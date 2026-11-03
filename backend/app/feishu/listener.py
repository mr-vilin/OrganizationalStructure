"""SDK 1.7.3 同步长连接独立进程。回调仅校验和短事务入箱。"""
import json
from datetime import datetime, timezone
from app.feishu.events import receive, EVENT_TYPES
from app.feishu.health import observe
from app.persistence.repositories import SqlSyncJobRepository


class Listener:
    def __init__(self,sessions,settings): self.sessions,self.settings=sessions,settings

    def starting(self):
        observe(self.sessions,'degraded')
        self._reconcile('listener:startup')

    def _reconcile(self,reason):
        try:
            SqlSyncJobRepository(self.sessions).submit('reconcile',None,reason,datetime.now(timezone.utc).replace(tzinfo=None))
        except RuntimeError as exc:
            # 初始化前不提交普通核对，但保持监听以接收授权范围变化等事件。
            # 由仓储在锁内判断状态，避免先查状态再提交的竞态。
            if str(exc) != 'INITIALIZATION_INCOMPLETE':
                raise

    def reconnecting(self): observe(self.sessions,'degraded')

    def reconnected(self):
        self._reconcile('listener:reconnected')
        observe(self.sessions,'connected')

    def receive(self,payload):
        result=receive(self.sessions,payload,self.settings.feishu_app_id,self.settings.feishu_tenant_key)
        observe(self.sessions,'connected')
        return result


def main():
    from app.config import get_settings
    from app.dependencies import get_runtime
    settings,runtime=get_settings(),get_runtime()
    if not runtime or not settings.feishu_app_id or not settings.feishu_app_secret or not settings.feishu_tenant_key:
        raise SystemExit('长连接未配置：需要数据库、会话密钥、飞书应用与租户配置')
    from app.feishu.binding import bind_connection
    bind_connection(runtime.sessions,settings.feishu_app_id,settings.feishu_tenant_key)
    import lark_oapi as lark
    listener=Listener(runtime.sessions,settings)
    def callback(data):
        # SDK 模型序列化后提取白名单字段，绝不在此执行远程查询。
        listener.receive(json.loads(lark.JSON.marshal(data)))
    builder=lark.EventDispatcherHandler.builder('','')
    for name in EVENT_TYPES:
        getattr(builder,'register_p2_'+name.replace('.','_'))(callback)
    client=lark.ws.Client(settings.feishu_app_id,settings.feishu_app_secret.get_secret_value(),event_handler=builder.build(),log_level=lark.LogLevel.ERROR)
    client.on_reconnecting=listener.reconnecting
    client.on_reconnected=listener.reconnected
    listener.starting()
    # 首次连接没有公开通知；不读取私有字段，也不虚报 connected。
    client.start()


if __name__=='__main__': main()
