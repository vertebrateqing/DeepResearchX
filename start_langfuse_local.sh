#!/bin/bash
# Start Langfuse locally using PostgreSQL (no Docker required)
# Requires: postgresql@15 (brew install postgresql@15), node 18+

set -e

LANGFUSE_DIR="$HOME/.langfuse-server"
PG_BIN="/opt/homebrew/opt/postgresql@15/bin"
PG_DATA="$HOME/.langfuse-postgres"
LANGFUSE_PORT=3000
PG_PORT=5433  # Use 5433 to avoid conflicts

echo "=== Langfuse Local Server ==="

# 1. Start PostgreSQL
if ! "$PG_BIN/pg_isready" -p $PG_PORT -q 2>/dev/null; then
  echo "[1/4] Initializing PostgreSQL..."
  if [ ! -d "$PG_DATA" ]; then
    "$PG_BIN/initdb" -D "$PG_DATA" --no-locale --encoding=UTF8
    echo "port = $PG_PORT" >> "$PG_DATA/postgresql.conf"
  fi
  echo "[1/4] Starting PostgreSQL on port $PG_PORT..."
  "$PG_BIN/pg_ctl" -D "$PG_DATA" -l "$PG_DATA/postgres.log" start
  sleep 2
fi

# Create langfuse database if not exists
"$PG_BIN/createdb" -p $PG_PORT langfuse 2>/dev/null || true
"$PG_BIN/psql" -p $PG_PORT -d langfuse -c "SELECT 1" -q > /dev/null 2>&1
echo "[1/4] PostgreSQL ready"

# 2. Clone or update langfuse
if [ ! -d "$LANGFUSE_DIR" ]; then
  echo "[2/4] Cloning Langfuse..."
  git clone --depth=1 --branch v2.94.3 https://github.com/langfuse/langfuse.git "$LANGFUSE_DIR"
else
  echo "[2/4] Langfuse already cloned"
fi

# 3. Install dependencies
cd "$LANGFUSE_DIR"
if [ ! -d "node_modules" ]; then
  echo "[3/4] Installing npm dependencies..."
  npm install --legacy-peer-deps
fi

# 4. Configure and start
echo "[4/4] Starting Langfuse on port $LANGFUSE_PORT..."
export DATABASE_URL="postgresql://$(whoami)@localhost:$PG_PORT/langfuse"
export NEXTAUTH_URL="http://localhost:$LANGFUSE_PORT"
export NEXTAUTH_SECRET="langfuse-local-dev-secret"
export SALT="langfuse-local-salt"
export PORT=$LANGFUSE_PORT
export NODE_ENV=development

# Run prisma migrate
npx prisma migrate deploy 2>/dev/null || npx prisma db push 2>/dev/null || true

# Build and start
npm run build 2>/dev/null || true
npm run start
