#!/bin/bash
# =============================================================================
# Financial DeepResearch — 开发环境一键关闭脚本
# 适用于：Linux / macOS / WSL (Windows Subsystem for Linux)
# =============================================================================

G='\033[0;32m'
Y='\033[1;33m'
R='\033[0;31m'
B='\033[0;34m'
C='\033[0;36m'
N='\033[0m'

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PID="$PROJECT_DIR/.backend.pid"
FRONTEND_PID="$PROJECT_DIR/.frontend.pid"
BACKEND_LOG="$PROJECT_DIR/backend.log"
FRONTEND_LOG="$PROJECT_DIR/frontend.log"

echo -e "${C}╔══════════════════════════════════════════════════════╗${N}"
echo -e "${C}║     Financial DeepResearch — 关闭开发环境           ║${N}"
echo -e "${C}╚══════════════════════════════════════════════════════╝${N}"
echo ""

# 通过 PID 文件关闭
kill_by_pidfile() {
    local pidfile=$1
    local name=$2
    if [ -f "$pidfile" ]; then
        local pid
        pid=$(cat "$pidfile")
        if kill "$pid" 2>/dev/null; then
            rm -f "$pidfile"
            echo -e "${G}  ✓ $name (PID $pid) 已关闭${N}"
            return 0
        else
            rm -f "$pidfile"
        fi
    fi
    return 1
}

# 通过端口关闭
kill_by_port() {
    local port=$1
    local name=$2
    local pids=""

    if command -v lsof &>/dev/null; then
        pids=$(lsof -t -i:"$port" 2>/dev/null)
    elif command -v ss &>/dev/null; then
        pids=$(ss -tlnp 2>/dev/null | grep ":$port " | grep -oP 'pid=\K[0-9]+' | sort -u)
    elif command -v netstat &>/dev/null; then
        pids=$(netstat -tlnp 2>/dev/null | grep ":$port " | awk '{print $7}' | grep -oP '^[0-9]+')
    fi

    if [ -n "$pids" ]; then
        echo "$pids" | xargs -r kill -9 2>/dev/null
        echo -e "${G}  ✓ $name (端口 $port) 已关闭${N}"
        return 0
    else
        echo -e "${Y}  ⚠ $name (端口 $port) 未运行${N}"
        return 1
    fi
}

# 尝试通过 PID 文件关闭
BACKEND_KILLED=false
FRONTEND_KILLED=false

if kill_by_pidfile "$BACKEND_PID" "后端"; then
    BACKEND_KILLED=true
fi

if kill_by_pidfile "$FRONTEND_PID" "前端"; then
    FRONTEND_KILLED=true
fi

# PID 文件失败时，通过端口关闭
if [ "$BACKEND_KILLED" = false ]; then
    if kill_by_port 8000 "后端"; then
        BACKEND_KILLED=true
    fi
fi

if [ "$FRONTEND_KILLED" = false ]; then
    if kill_by_port 5173 "前端"; then
        FRONTEND_KILLED=true
    fi
fi

# 清理日志文件
if [ "$BACKEND_KILLED" = true ] && [ "$FRONTEND_KILLED" = true ]; then
    echo ""
    echo -e "${Y}  是否清理日志文件？(backend.log / frontend.log)${N}"
    echo -e "${Y}  输入 y 确认，其他键跳过：${N}\c"
    read -r confirm
    if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
        rm -f "$BACKEND_LOG" "$FRONTEND_LOG"
        echo -e "${G}  ✓ 日志文件已清理${N}"
    fi
fi

echo ""
echo -e "${G}╔══════════════════════════════════════════════════════╗${N}"
echo -e "${G}║           👋 开发环境已关闭                          ║${N}"
echo -e "${G}╚══════════════════════════════════════════════════════╝${N}"
