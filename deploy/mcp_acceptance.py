"""MCP 部署验收：真实协议读取与拒绝写入，不批准任何业务修改。"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from uuid import uuid4

from app.mcp.config import MCPSettings
from app.mcp.policy import TOOL_LEVELS


async def verify(config: MCPSettings) -> dict:
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client
    from mcp.types import ElicitResult

    if config.agent_environment != 'production' or config.mcp_actor_type != 'human_agent':
        raise ValueError('验收要求生产策略下的人工 Agent 身份')
    host = config.mcp_host
    if host in {'0.0.0.0', '::'}:
        host = '127.0.0.1' if host == '0.0.0.0' else '[::1]'
    elif ':' in host:
        host = f'[{host}]'
    endpoint = f'http://{host}:{config.mcp_port}/mcp'
    headers = {'Authorization': 'Bearer ' + config.mcp_service_token.get_secret_value()}
    async with asyncio.timeout(30):
        async with httpx2.AsyncClient(timeout=3, trust_env=False) as http:
            assert (await http.get(endpoint)).status_code == 401
            assert (await http.get(endpoint, headers={'Authorization': 'Bearer ' + config.agent_service_token.get_secret_value()})).status_code == 401
            assert (await http.post(endpoint, headers={**headers, 'Host': 'untrusted.invalid'}, json={})).status_code == 421
            assert (await http.post(endpoint, headers={**headers, 'Origin': 'https://untrusted.invalid'}, json={})).status_code == 403
        modes = []
        for mode in ('legacy', 'auto'):
            questions = []

            async def decline(_context, params):
                questions.append(params)
                return ElicitResult(action='decline')

            async with httpx2.AsyncClient(headers=headers, timeout=8, trust_env=False) as http:
                async with Client(streamable_http_client(endpoint, http_client=http),
                                  mode=mode, elicitation_callback=decline) as client:
                    tools = (await client.list_tools()).tools
                    assert len(tools) == len(TOOL_LEVELS)
                    assert {tool.name for tool in tools} == set(TOOL_LEVELS)
                    status = (await client.call_tool('get_system_status', {})).structured_content
                    assert status and status.get('error') is None
                    assert status['observation'] and isinstance(status['data'], dict)
                    denied = (await client.call_tool('request_sync', {
                        'job_type': 'initialize', 'idempotency_key': 'deployment-declined-' + uuid4().hex,
                    })).structured_content
                    assert questions, '服务必须实际发起人工确认'
                    assert denied['error']['code'] == 'CONFIRMATION_REQUIRED'
                    assert denied['operation_id'] is None
                    modes.append(mode)
        return {'result': 'MCP_ACCEPTANCE_PASSED', 'tool_count': len(TOOL_LEVELS),
                'protocol_modes': modes, 'backend_read': True, 'unauthenticated_rejected': True,
                'separate_tokens': True, 'host_origin_protected': True,
                'declined_write_rejected': True}


def main() -> int:
    # 固定诊断信息，禁止 SDK、HTTP 或配置异常原文泄露凭据与业务载荷。
    logging.disable(logging.CRITICAL)
    try:
        report = asyncio.run(verify(MCPSettings()))
    except Exception:
        print('MCP_ACCEPTANCE_FAILED', file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
