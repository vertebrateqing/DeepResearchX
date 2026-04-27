#!/bin/bash
# =============================================================================
# Financial DeepResearch — 开发环境一键启动脚本
# 适用于：Linux / macOS / WSL (Windows Subsystem for Linux)
# =============================================================================

set -e

# 颜色定义
G='\033[0;32m'  # Green
Y='\033[1;33m'  # Yellow
R='\033[0;31m'  # Red
B='\033[0;34m'  # Blue
C='\033[0;36m'  # Cyan
N='\033[0m'     # Reset

# 项目目录（脚本所在目录）
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"
BACKEND_LOG="$PROJECT_DIR/backend.log"
FRONTEND_LOG="$PROJECT_DIR/frontend.log"
BACKEND_PID="$PROJECT_DIR/.backend.pid"
FRONTEND_PID="$PROJECT_DIR/.frontend.pid"

echo -e "${C}╔══════════════════════════════════════════════════════╗${N}"
echo -e "${C}║     Financial DeepResearch — 启动开发环境           ║${N}"
echo -e "${C}╚══════════════════════════════════════════════════════╝${N}"
echo ""

# 检测操作系统
OS="unknown"
case "$(uname -s)" in
    Linux*)     OS="linux";;
    Darwin*)    OS="macos";;
    CYGWIN*|MINGW*|MSYS*) OS="windows";;
esac
echo -e "${B}  操作系统：${N}$OS"

# 检查端口是否被占用
check_port() {
    local port=$1
    if command -v lsof &> /dev/null; then
        lsof -i :"$port" &> /dev/null
    elif command -v ss &> /dev/null; then
        ss -tlnp 2>/dev/null | grep -q ":$port "
    elif command -v netstat &> /dev/null; then
        netstat -tlnp 2>/dev/null | grep -q ":$port "
    else
        return 1
    fi
}

# 检查目录
echo -e "${Y}[1/5] 检查项目结构...${N}"
if [ ! -d "$BACKEND_DIR" ]; then
    echo -e "${R}  ✗ 找不到 backend 目录${N}"
    exit 1
fi
if [ ! -d "$FRONTEND_DIR" ]; then
    echo -e "${R}  ✗ 找不到 frontend 目录${N}"
    exit 1
fi
echo -e "${G}  ✓ 项目结构正常${N}"

# 检查 Python
echo -e "${Y}[2/5] 检查 Python 环境...${N}"
PYTHON_CMD=""
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo -e "${R}  ✗ 未找到 Python，请先安装 Python 3.10+${N}"
    exit 1
fi
PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
echo -e "${G}  ✓ Python $PYTHON_VERSION ($PYTHON_CMD)${N}"

# 激活虚拟环境（如果存在）
VENV_ACTIVATED=false
if [ -f "$BACKEND_DIR/venv/bin/activate" ]; then
    # shellcheck source=/dev/null
    source "$BACKEND_DIR/venv/bin/activate"
    VENV_ACTIVATED=true
elif [ -f "$BACKEND_DIR/.venv/bin/activate" ]; then
    # shellcheck source=/dev/null
    source "$BACKEND_DIR/.venv/bin/activate"
    VENV_ACTIVATED=true
fi

if [ "$VENV_ACTIVATED" = true ]; then
    echo -e "${G}  ✓ 虚拟环境已激活${N}"
else
    echo -e "${Y}  ⚠ 未检测到虚拟环境，使用系统 Python${N}"
    echo -e "${Y}      建议创建：cd backend && $PYTHON_CMD -m venv venv${N}"
fi

# 检查后端依赖
echo -e "${Y}[3/5] 检查后端依赖...${N}"
if ! $PYTHON_CMD -c "import fastapi" 2>/dev/null; then
    echo -e "${Y}  ⚠ 后端依赖未安装，正在安装...${N}"
    cd "$BACKEND_DIR"
    if [ -f "requirements.txt" ]; then
        if [ "$VENV_ACTIVATED" = true ]; then
            pip install -r requirements.txt -q
        else
            $PYTHON_CMD -m pip install -r requirements.txt -q
        fi
        echo -e "${G}  ✓ 后端依赖安装完成${N}"
    else
        echo -e "${R}  ✗ 找不到 requirements.txt${N}"
        exit 1
    fi
else
    echo -e "${G}  ✓ 后端依赖已就绪${N}"
fi

# 检查前端依赖
echo -e "${Y}[4/5] 检查前端依赖...${N}"
if ! command -v npm &> /dev/null; then
    echo -e "${R}  ✗ 未找到 npm，请先安装 Node.js 20+${N}"
    exit 1
fi
NODE_VERSION=$(node --version 2>/dev/null || echo "unknown")
echo -e "${G}  ✓ Node.js $NODE_VERSION${N}"

if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    echo -e "${Y}  ⚠ 前端依赖未安装，正在安装...${N}"
    cd "$FRONTEND_DIR"
    npm install
    echo -e "${G}  ✓ 前端依赖安装完成${N}"
else
    echo -e "${G}  ✓ 前端依赖已就绪${N}"
fi

# 启动后端
echo -e "${Y}[5/5] 启动服务...${N}"
echo ""

if check_port 8000; then
    echo -e "${Y}  ⚠ 端口 8000 已被占用，后端可能已在运行${N}"
else
    cd "$BACKEND_DIR"
    nohup $PYTHON_CMD -m uvicorn main:app --reload --host 0.0.0.0 --port 8000 > "$BACKEND_LOG" 2>&1 &
    echo $! > "$BACKEND_PID"
    sleep 2
    if check_port 8000; then
        echo -e "${G}  ✓ 后端已启动  → ${B}http://localhost:8000${N}"
    else
        echo -e "${R}  ✗ 后端启动失败，请检查 backend.log${N}"
    fi
fi

# 启动前端
if check_port 5173; then
    echo -e "${Y}  ⚠ 端口 5173 已被占用，前端可能已在运行${N}"
else
    cd "$FRONTEND_DIR"
    nohup npm run dev > "$FRONTEND_LOG" 2>&1 &
    echo $! > "$FRONTEND_PID"
    sleep 3
    if check_port 5173; then
        echo -e "${G}  ✓ 前端已启动  → ${B}http://localhost:5173${N}"
    else
        echo -e "${R}  ✗ 前端启动失败，请检查 frontend.log${N}"
    fi
fi

echo ""
echo -e "${G}╔══════════════════════════════════════════════════════╗${N}"
echo -e "${G}║           🚀 开发环境启动完成！                      ║${N}"
echo -e "${G}╠══════════════════════════════════════════════════════╣${N}"
echo -e "${G}║${N}  前端页面   ${B}http://localhost:5173/${N}               ${G}║${N}"
echo -e "${G}║${N}  后端 API   ${B}http://localhost:8000${N}                 ${G}║${N}"
echo -e "${G}║${N}  API 文档   ${B}http://localhost:8000/docs${N}            ${G}║${N}"
echo -e "${G}╠══════════════════════════════════════════════════════╣${N}"
echo -e "${G}║${N}  后端日志   ${C}tail -f backend.log${N}                  ${G}║${N}"
echo -e "${G}║${N}  前端日志   ${C}tail -f frontend.log${N}                 ${G}║${N}"
echo -e "${G}║${N}  关闭服务   ${C}./dev-stop.sh${N}                        ${G}║${N}"
echo -e "${G}╚══════════════════════════════════════════════════════╝${N}"
