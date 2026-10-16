"""只接收目标、受限 MCP 客户端和运行身份的 Worker 适配器。"""
from dataclasses import dataclass
from copy import deepcopy
import os
import re
import time
from typing import Any, Callable, Protocol

from .models import AgentRun, AgentRunContext


class WorkerAgent(Protocol):
    def run(self, goal: str, mcp_client, context: AgentRunContext) -> AgentRun: ...


@dataclass(frozen=True)
class ToolStep:
    tool_name: str
    arguments: dict | Callable[[tuple[dict, ...], AgentRunContext], dict]
    until: Callable[[dict], bool] | None = None
    max_attempts: int = 1
    interval: float = .05


class ScriptedWorkerAgent:
    """显式脚本仅用于契约 smoke；动态参数只能读取之前的 MCP 返回。"""
    def __init__(self, steps=None):
        self.steps = steps

    def run(self, goal, mcp_client, context):
        steps = self.steps(goal, context) if callable(self.steps) else self.steps
        if steps is None:
            # 默认只读 smoke 从目标原文取得合成员工 ID，不读取 case 或 expected。
            match = re.search(r'\beval_employee_[A-Za-z0-9_]+\b', goal)
            if not match:
                raise ValueError('SCRIPT_REQUIRED')
            steps = [ToolStep('get_employee', {'employee_id': match.group()})]
        results = []
        for step in steps:
            if step.max_attempts < 1 or step.interval < 0:
                raise ValueError('SCRIPT_INVALID')
            arguments = step.arguments(tuple(results), context) if callable(step.arguments) else step.arguments
            for attempt in range(step.max_attempts):
                result = mcp_client.call_tool(step.tool_name, deepcopy(arguments))
                results.append(result)
                if step.until is None or step.until(result):
                    break
                if attempt + 1 == step.max_attempts:
                    raise RuntimeError('SCRIPT_POLL_UNCONFIRMED')
                time.sleep(step.interval)
        return AgentRun('脚本已结束，结果由独立断言判定。', (), {})


class ModelProvider(Protocol):
    def run(self, *, goal: str, mcp_client, context: AgentRunContext,
            model_alias: str, max_tokens: int) -> AgentRun: ...


class ProviderWorkerAgent:
    """模型实现必须显式注入；本模块不创建网络客户端或读取提供商密钥。"""
    def __init__(self, provider: ModelProvider, *, model_alias=None, max_tokens=None):
        self.provider = provider
        self.model_alias = model_alias or os.getenv('ORG_EVALUATION_MODEL_ALIAS', '')
        self.max_tokens = max_tokens if max_tokens is not None else int(os.getenv('ORG_EVALUATION_MAX_TOKENS', '2048'))
        if (not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', self.model_alias)
                or type(self.max_tokens) is not int or self.max_tokens < 1):
            raise ValueError('EVALUATION_MODEL_CONFIGURATION_REQUIRED')

    def run(self, goal, mcp_client, context):
        return self.provider.run(goal=goal, mcp_client=mcp_client, context=context,
                                 model_alias=self.model_alias, max_tokens=self.max_tokens)
