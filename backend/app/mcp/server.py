"""官方 SDK 工厂；本阶段只建立协议边界。"""

from mcp.server import MCPServer


def build_server(client: object, policy: object, tracer: object) -> MCPServer:
    """创建独立的 SDK server，不访问数据库或启动网络监听。

    三个位置参数为后续内部 HTTP client、策略和追踪依赖保留。
    Task 4 完成依赖接线后才注册业务工具；当前返回空目录的协议骨架，
    不能作为生产 sidecar 启动。
    """
    return MCPServer(
        name="organization-capabilities",
        version="0.1.0",
        instructions="协议骨架：业务工具与可信身份尚未接通，不能用于生产调用。",
    )
