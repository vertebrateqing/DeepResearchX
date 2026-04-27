# =============================================================================
# Financial DeepResearch — 开发环境一键关闭脚本
# 适用于：Windows PowerShell / Windows Terminal
# =============================================================================

$PROJECT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$BACKEND_PID = Join-Path $PROJECT_DIR ".backend.pid"
$FRONTEND_PID = Join-Path $PROJECT_DIR ".frontend.pid"
$BACKEND_LOG = Join-Path $PROJECT_DIR "backend.log"
$FRONTEND_LOG = Join-Path $PROJECT_DIR "frontend.log"

function Write-Banner {
    Write-Host ""
    Write-Host "╔══════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║     Financial DeepResearch — 关闭开发环境           ║" -ForegroundColor Cyan
    Write-Host "╚══════════════════════════════════════════════════════╝" -ForegroundColor Cyan
    Write-Host ""
}

function Stop-ByPidFile {
    param([string]$PidFile, [string]$Name)
    if (Test-Path $PidFile) {
        $pid = Get-Content $PidFile -Raw
        try {
            Stop-Process -Id $pid -Force -ErrorAction Stop
            Remove-Item $PidFile
            Write-Host "  ✓ $Name (PID $pid) 已关闭" -ForegroundColor Green
            return $true
        } catch {
            Remove-Item $PidFile
        }
    }
    return $false
}

function Stop-ByPort {
    param([int]$Port, [string]$Name)
    try {
        $proc = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($proc) {
            Stop-Process -Id $proc.OwningProcess -Force
            Write-Host "  ✓ $Name (端口 $Port) 已关闭" -ForegroundColor Green
            return $true
        }
    } catch {
        # Fallback: try netstat
        $netstat = netstat -ano | Select-String ":$Port " | Select-Object -First 1
        if ($netstat) {
            $parts = $netstat -split '\s+'
            $pid = $parts[-1]
            if ($pid -match '^\d+$') {
                taskkill /PID $pid /F 2>$null | Out-Null
                Write-Host "  ✓ $Name (端口 $Port) 已关闭" -ForegroundColor Green
                return $true
            }
        }
    }
    Write-Host "  ⚠ $Name (端口 $Port) 未运行" -ForegroundColor Yellow
    return $false
}

Write-Banner

$BACKEND_KILLED = Stop-ByPidFile $BACKEND_PID "后端"
$FRONTEND_KILLED = Stop-ByPidFile $FRONTEND_PID "前端"

if (-not $BACKEND_KILLED) {
    $BACKEND_KILLED = Stop-ByPort 8000 "后端"
}
if (-not $FRONTEND_KILLED) {
    $FRONTEND_KILLED = Stop-ByPort 5173 "前端"
}

if ($BACKEND_KILLED -and $FRONTEND_KILLED) {
    Write-Host ""
    $confirm = Read-Host "  是否清理日志文件？输入 y 确认"
    if ($confirm -eq "y" -or $confirm -eq "Y") {
        Remove-Item $BACKEND_LOG -ErrorAction SilentlyContinue
        Remove-Item $FRONTEND_LOG -ErrorAction SilentlyContinue
        Write-Host "  ✓ 日志文件已清理" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║           👋 开发环境已关闭                          ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════════════════════════════╝" -ForegroundColor Green
