#!/bin/bash
# Start Langfuse locally using embedded PostgreSQL (pgserver)
# Works on: Linux / macOS / WSL
# Requires: Python 3.10+, Node.js 20+, npm

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
LANGFUSE_DIR="$HOME/langfuse-server"
PGDATA="$HOME/.langfuse-postgres-pgserver"
LANGFUSE_PORT=3000

# Colors
G='\033[0;32m'
Y='\033[1;33m'
R='\033[0;31m'
B='\033[0;34m'
N='\033[0m'

echo -e "${B}=== Langfuse Local Server ===${N}"

# Check prerequisites
check_cmd() {
    if ! command -v "$1" &> /dev/null; then
        echo -e "${R}✗ $1 not found${N}"
        return 1
    fi
    echo -e "${G}✓ $1 found${N}"
    return 0
}

echo ""
echo -e "${Y}[1/5] Checking prerequisites...${N}"
check_cmd python3 || exit 1
check_cmd node || exit 1
check_cmd npm || exit 1

# Activate project virtual environment or create one
VENV_PYTHON="$BACKEND_DIR/venv/bin/python"
if [ ! -f "$VENV_PYTHON" ]; then
    echo -e "${Y}  Creating virtual environment...${N}"
    python3 -m venv "$BACKEND_DIR/venv"
fi

# Ensure pgserver is installed
if ! "$VENV_PYTHON" -c "import pgserver" 2>/dev/null; then
    echo -e "${Y}[2/5] Installing pgserver (embedded PostgreSQL)...${N}"
    "$VENV_PYTHON" -m pip install pgserver -q
fi

echo -e "${G}  ✓ pgserver ready${N}"

# Start PostgreSQL via pgserver
echo -e "${Y}[3/5] Starting embedded PostgreSQL...${N}"
PG_PORT=$("$VENV_PYTHON" -c "
import pgserver, pathlib
pgdata = pathlib.Path('$PGDATA')
s = pgserver.get_server(pgdata, cleanup_mode=None)
s.ensure_pgdata_inited()
s.ensure_postgres_running()
# Extract port from URI
uri = s.get_uri()
print(uri)
" 2>/dev/null | grep -oP 'port=\K[0-9]+' || echo "")

if [ -z "$PG_PORT" ]; then
    # Unix socket mode, no TCP port
    echo -e "${G}  ✓ PostgreSQL running (unix socket)${N}"
else
    echo -e "${G}  ✓ PostgreSQL running on port $PG_PORT${N}"
fi

# Create langfuse database
"$VENV_PYTHON" -c "
import pgserver, pathlib
pgdata = pathlib.Path('$PGDATA')
s = pgserver.get_server(pgdata, cleanup_mode=None)
s.ensure_postgres_running()
try:
    s.psql('CREATE DATABASE langfuse;')
except Exception:
    pass  # DB may already exist
print('Langfuse database ready')
" > /dev/null 2>&1

# Get connection URI for Langfuse
PG_URI=$("$VENV_PYTHON" -c "
import pgserver, pathlib
pgdata = pathlib.Path('$PGDATA')
s = pgserver.get_server(pgdata, cleanup_mode=None)
uri = s.get_uri()
# Replace postgres DB with langfuse DB
uri = uri.replace('/postgres?', '/langfuse?')
print(uri)
")

echo -e "${G}  ✓ Database ready${N}"
echo -e "    URI: ${PG_URI}"

# Clone or update langfuse
echo -e "${Y}[4/5] Checking Langfuse server...${N}"
if [ ! -d "$LANGFUSE_DIR" ]; then
    echo -e "${Y}  Cloning Langfuse (v2.95.12)...${N}"
    git clone --depth=1 --branch v2.95.12 https://github.com/langfuse/langfuse.git "$LANGFUSE_DIR"
else
    echo -e "${G}  ✓ Langfuse already cloned${N}"
fi

# Check for pnpm
PNPM_CMD=""
if command -v pnpm &> /dev/null; then
    PNPM_CMD="pnpm"
else
    echo -e "${Y}  ⚠ pnpm not found. Attempting to install dependencies with npm...${N}"
    echo -e "${Y}    Note: Langfuse is a monorepo that prefers pnpm.${N}"
    echo -e "${Y}    Install pnpm for best results: npm install -g pnpm${N}"
fi

# Install dependencies
if [ -n "$PNPM_CMD" ]; then
    if [ ! -d "$LANGFUSE_DIR/node_modules" ]; then
        echo -e "${Y}  Installing dependencies with pnpm...${N}"
        cd "$LANGFUSE_DIR"
        $PNPM_CMD install
    fi
else
    if [ ! -d "$LANGFUSE_DIR/node_modules" ]; then
        echo -e "${Y}  Installing dependencies with npm (may have issues)...${N}"
        cd "$LANGFUSE_DIR"
        npm install --ignore-scripts
    fi
fi

# Configure environment
echo -e "${Y}[5/5] Configuring and starting Langfuse...${N}"
cd "$LANGFUSE_DIR"

# Write .env file
cat > .env <<EOF
DATABASE_URL="$PG_URI"
DIRECT_URL="$PG_URI"
NEXTAUTH_SECRET="langfuse-local-dev-secret"
NEXTAUTH_URL="http://localhost:$LANGFUSE_PORT"
SALT="langfuse-local-salt"
LANGFUSE_ENABLE_EXPERIMENTAL_FEATURES="false"
ENCRYPTION_KEY=0000000000000000000000000000000000000000000000000000000000000000
EOF

echo -e "${G}  ✓ Environment configured${N}"

# Run database migrations
echo -e "${Y}  Running database migrations...${N}"
if [ -n "$PNPM_CMD" ]; then
    cd "$LANGFUSE_DIR/packages/shared"
    $PNPM_CMD run db:push 2>/dev/null || npx prisma db push --schema=prisma/schema.prisma 2>/dev/null || true
else
    npx prisma db push --schema=packages/shared/prisma/schema.prisma 2>/dev/null || true
fi

echo ""
echo -e "${G}══════════════════════════════════════════════════════${N}"
echo -e "${G}  Langfuse is configured and ready to start${N}"
echo -e "${G}══════════════════════════════════════════════════════${N}"
echo -e "${G}  Database:   ${B}$PG_URI${N}"
echo -e "${G}  Web UI:     ${B}http://localhost:$LANGFUSE_PORT${N}"
echo -e "${G}══════════════════════════════════════════════════════${N}"
echo ""

if [ -n "$PNPM_CMD" ]; then
    echo -e "${Y}To start Langfuse, run:${N}"
    echo -e "  ${B}cd $LANGFUSE_DIR && pnpm run dev${N}"
    echo ""
    echo -e "${Y}Or for production build:${N}"
    echo -e "  ${B}cd $LANGFUSE_DIR && pnpm run build && pnpm run start${N}"
else
    echo -e "${R}⚠ pnpm is required to build and run Langfuse properly.${N}"
    echo -e "${R}  Please install pnpm:${N} ${B}npm install -g pnpm${N}"
    echo ""
    echo -e "${Y}Once pnpm is installed, run:${N}"
    echo -e "  ${B}cd $LANGFUSE_DIR && pnpm install && pnpm run dev${N}"
fi

echo ""
echo -e "${Y}To use Langfuse with DeepResearchX, set in your .env:${N}"
echo -e "  ${B}LANGFUSE_ENABLED=true${N}"
echo -e "  ${B}LANGFUSE_PUBLIC_KEY=pk-lf-local-dev${N}"
echo -e "  ${B}LANGFUSE_SECRET_KEY=sk-lf-local-dev${N}"
echo -e "  ${B}LANGFUSE_HOST=http://localhost:$LANGFUSE_PORT${N}"
