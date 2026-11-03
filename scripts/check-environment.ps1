[CmdletBinding()]
param(
    [switch]$DatabaseIntegration,
    [switch]$Frontend
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$checks = [System.Collections.Generic.List[object]]::new()
$errors = [System.Collections.Generic.List[string]]::new()

function Add-Check([string]$Name, [string]$Status, [string]$Detail) {
    $checks.Add([pscustomobject]@{ name = $Name; status = $Status; detail = $Detail })
}

function Add-RequiredCommand([string]$Name, [string]$DisplayName) {
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        $errors.Add("缺少 $DisplayName（命令：$Name）")
        Add-Check $DisplayName 'missing' "未找到 $Name"
        return $false
    }
    Add-Check $DisplayName 'ready' $command.Source
    return $true
}

$pythonPath = Join-Path $repoRoot 'backend\.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $pythonPath) {
    Add-Check 'Python' 'ready' 'backend/.venv/Scripts/python.exe'
} elseif (Add-RequiredCommand 'python' 'Python') {
    $pythonPath = 'python'
}

if ($Frontend) {
    [void](Add-RequiredCommand 'npm.cmd' 'Node/npm')
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot 'frontend\package-lock.json'))) {
        $errors.Add('缺少 frontend/package-lock.json')
    }
}

if ($DatabaseIntegration) {
    $dockerReady = Add-RequiredCommand 'docker.exe' 'Docker CLI'
    $composeFile = Join-Path $repoRoot 'compose.mysql-test.yaml'
    if (-not (Test-Path -LiteralPath $composeFile)) {
        $errors.Add('缺少 compose.mysql-test.yaml')
    } else {
        Add-Check 'MySQL test compose' 'ready' 'compose.mysql-test.yaml'
    }
    if ($dockerReady) {
        $dockerInfo = & docker info --format '{{.ServerVersion}}' 2>$null
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($dockerInfo -join ''))) {
            $errors.Add('当前进程无法访问 Docker daemon；请检查引擎状态及沙箱/命名管道访问权限')
            Add-Check 'Docker daemon' 'blocked' 'docker info 未返回服务端版本'
        } else {
            Add-Check 'Docker daemon' 'ready' (($dockerInfo -join '').Trim())
        }
        $composeCheck = & docker compose -f $composeFile config --quiet 2>$null
        if ($LASTEXITCODE -ne 0) {
            $errors.Add('compose.mysql-test.yaml 无法通过 Docker Compose 配置检查')
            Add-Check 'Docker Compose config' 'blocked' 'docker compose config --quiet 失败'
        } else {
            Add-Check 'Docker Compose config' 'ready' '配置可解析'
        }
    }
}

[pscustomobject]@{
    status = if ($errors.Count -eq 0) { 'ready' } else { 'blocked' }
    scope = if ($DatabaseIntegration) { 'database-integration' } else { 'local' }
    checks = $checks
    errors = $errors
} | ConvertTo-Json -Depth 4
if ($errors.Count -gt 0) { exit 1 }
exit 0
