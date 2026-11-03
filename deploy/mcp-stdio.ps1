# 受信本机 MCP 客户端入口。令牌留在容器环境中，不写入参数或 stdout。
$ErrorActionPreference = 'Stop'
$repository = Split-Path -Parent $PSScriptRoot
& docker compose --project-directory $repository -f (Join-Path $repository 'compose.yaml') --profile agent exec -T mcp python -m app.mcp --transport stdio
exit $LASTEXITCODE
