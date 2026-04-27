# =============================================================================
# Financial DeepResearch — 开发环境一键启动脚本
# 适用于：Windows PowerShell / Windows Terminal
# 用法：右键点击 → 使用 PowerShell 运行，或在终端中执行 .\dev-start.ps1
# =============================================================================

# 如果脚本执行策略阻止运行，先执行：Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

$PROJECT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$BACKEND_DIR = Join-Path $PROJECT_DIR "backend"
$FRONTEND_DIR = Join-Path $PROJECT_DIR "frontend"
$BACKEND_LOG = Join-Path $PROJECT_DIR "backend.log"
$FRONTEND_LOG = Join-Path $PROJECT_DIR "frontend.log"
$BACKEND_PID = Join-Path $PROJECT_DIR ".backend.pid"
$FRONTEND_PID = Join-Path $PROJECT_DIR ".frontend.pid"

function Write-Banner {
    Write-Host ""
    Write-Host "╔══════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║     Financial DeepResearch — 启动开发环境           ║" -ForegroundColor Cyan
    Write-Host "╚══════════════════════════════════════════════════════╝" -ForegroundColor Cyan
    Write-Host ""
}

function Test-PortInUse {
    param([int]$Port)
    $connection = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    return $null -ne $connection
}

function Write-Status {
    param([string]$Message, [string]$Type = "info")
    switch ($Type) {
        "ok"    { Write-Host "  ✓ $Message" -ForegroundColor Green }
        "warn"  { Write-Host "  ⚠ $Message" -ForegroundColor Yellow }
        "error" { Write-Host "  ✗ $Message" -ForegroundColor Red }
        "info"  { Write-Host "  $Message" -ForegroundColor Gray }
    }
}

Write-Banner

# 检查目录
Write-Host "[1/5] 检查项目结构..." -ForegroundColor Yellow
if (-not (Test-Path $BACKEND_DIR)) {
    Write-Status "找不到 backend 目录" "error"
    exit 1
}
if (-not (Test-Path $FRONTEND_DIR)) {
    Write-Status "找不到 frontend 目录" "error"
    exit 1
}
Write-Status "项目结构正常" "ok"

# 检查 Python
Write-Host "[2/5] 检查 Python 环境..." -ForegroundColor Yellow
$PYTHON_CMD = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $PYTHON_CMD = "python"
} elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    $PYTHON_CMD = "python3"
} else {
    Write-Status "未找到 Python，请先安装 Python 3.10+" "error"
    exit 1
}
$PYTHON_VERSION = & $PYTHON_CMD --version 2>&1
Write-Status "$PYTHON_VERSION ($PYTHON_CMD)" "ok"

# 检查虚拟环境
$VENV_ACTIVATED = $false
$VENV_PATHS = @(
    (Join-Path $BACKEND_DIR "venv\Scripts\Activate.ps1"),
    (Join-Path $BACKEND_DIR ".venv\Scripts\Activate.ps1")
)
foreach ($venv in $VENV_PATHS) {
    if (Test-Path $venv) {
        & $venv
        $VENV_ACTIVATED = $true
        break
    }
}
if ($VENV_ACTIVATED) {
    Write-Status "虚拟环境已激活" "ok"
} else {
    Write-Status "未检测到虚拟环境，使用系统 Python" "warn"
    Write-Status "建议创建：cd backend && $PYTHON_CMD -m venv venv" "warn"
}

# 检查后端依赖
Write-Host "[3/5] 检查后端依赖..." -ForegroundColor Yellow
try {
    & $PYTHON_CMD -c "import fastapi" 2>$null
    Write-Status "后端依赖已就绪" "ok"
} catch {
    Write-Status "后端依赖未安装，正在安装..." "warn"
    $REQ = Join-Path $BACKEND_DIR "requirements.txt"
    if (Test-Path $REQ) {
        & $PYTHON_CMD -m pip install -r $REQ -q
        Write-Status "后端依赖安装完成" "ok"
    } else {
        Write-Status "找不到 requirements.txt" "error"
        exit 1
    }
}

# 检查前端依赖
Write-Host "[4/5] 检查前端环境..." -ForegroundColor Yellow
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Status "未找到 npm，请先安装 Node.js 20+" "error"
    exit 1
}
$NODE_VERSION = & node --version 2>$null
Write-Status "Node.js $NODE_VERSION" "ok"

if (-not (Test-Path (Join-Path $FRONTEND_DIR "node_modules"))) {
    Write-Status "前端依赖未安装，正在安装..." "warn"
    Push-Location $FRONTEND_DIR
    npm install
    Pop-Location
    Write-Status "前端依赖安装完成" "ok"
} else {
    Write-Status "前端依赖已就绪" "ok"
}

# 启动后端
Write-Host "[5/5] 启动服务..." -ForegroundColor Yellow
Write-Host ""

if (Test-PortInUse 8000) {
    Write-Status "端口 8000 已被占用，后端可能已在运行" "warn"
} else {
    $BACKEND_PROC = Start-Process -FilePath $PYTHON_CMD -ArgumentList "-m", "uvicorn", "main:app", "--reload", "--host", "0.0.0.0", "--port", "8000" -WorkingDirectory $BACKEND_DIR -RedirectStandardOutput $BACKEND_LOG -RedirectStandardError $BACKEND_LOG -WindowStyle Hidden -PassThru
    $BACKEND_PROC.Id | Out-File $BACKEND_PID -Encoding UTF8
    Start-Sleep -Seconds 2
    if (Test-PortInUse 8000) {
        Write-Status "后端已启动  → http://localhost:8000" "ok"
    } else {
        Write-Status "后端启动失败，请检查 backend.log" "error"
    }
}

# 启动前端
if (Test-PortInUse 5173) {
    Write-Status "端口 5173 已被占用，前端可能已在运行" "warn"
} else {
    $FRONTEND_PROC = Start-Process -FilePath "npm" -ArgumentList "run", "dev" -WorkingDirectory $FRONTEND_DIR -RedirectStandardOutput $FRONTEND_LOG -RedirectStandardError $FRONTEND_LOG -WindowStyle Hidden -PassThru
    $FRONTEND_PROC.Id | Out-File $FRONTEND_PID -Encoding UTF8
    Start-Sleep -Seconds 3
    if (Test-PortInUse 5173) {
        Write-Status "前端已启动  → http://localhost:5173" "ok"
    } else {
        Write-Status "前端启动失败，请检查 frontend.log" "error"
    }
}

Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║           🚀 开发环境启动完成！                      ║" -ForegroundColor Green
Write-Host "╠══════════════════════════════════════════════════════╣" -ForegroundColor Green
Write-Host "║  前端页面   http://localhost:5173/                   ║" -ForegroundColor Green
Write-Host "║  后端 API   http://localhost:8000                    ║" -ForegroundColor Green
Write-Host "║  API 文档   http://localhost:8000/docs               ║" -ForegroundColor Green
Write-Host "╠══════════════════════════════════════════════════════╣" -ForegroundColor Green
Write-Host "║  后端日志   Get-Content backend.log -Wait            ║" -ForegroundColor Green
Write-Host "║  前端日志   Get-Content frontend.log -Wait           ║" -ForegroundColor Green
Write-Host "║  关闭服务   .\dev-stop.ps1                           ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════════════════════════════╝" -ForegroundColor Green
