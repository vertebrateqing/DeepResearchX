#!/bin/bash
# Usage:
#   ./eval.sh           # run all 100 queries + evaluate
#   ./eval.sh 8         # run query id=8 + evaluate
#   ./eval.sh 8,12,15   # run multiple ids + evaluate

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BENCH_DIR="$SCRIPT_DIR/deep_research_bench"
PYTHON="$SCRIPT_DIR/backend/.venv/bin/python"
RAW="$BENCH_DIR/data/test_data/raw_data/DeepResearchX.jsonl"
CLEANED="$BENCH_DIR/data/test_data/cleaned_data/DeepResearchX.jsonl"

IDS="${1:-}"

# --- Step 1: Generate reports ---
echo "=== Step 1: Generating reports ==="
if [ -n "$IDS" ]; then
    $PYTHON "$SCRIPT_DIR/run_drx_bench.py" --ids "$IDS" --concurrency 1
else
    $PYTHON "$SCRIPT_DIR/run_drx_bench.py" --concurrency 2
fi

# --- Validate generation results ---
if [ ! -f "$RAW" ] || [ "$(wc -l < "$RAW")" -eq 0 ]; then
    echo "ERROR: No articles generated. Aborting evaluation."
    exit 1
fi
if grep -q '"article": "\[ERROR' "$RAW" 2>/dev/null; then
    echo "WARNING: Some articles contain errors:"
    grep '"article": "\[ERROR' "$RAW" | python3 -c "import sys,json; [print('  id:', json.loads(l)['id'], json.loads(l)['article'][:80]) for l in sys.stdin]"
    echo "Aborting evaluation. Fix errors before evaluating."
    exit 1
fi

# --- Step 2: Sync raw -> cleaned ---
echo "=== Step 2: Syncing raw -> cleaned ==="
mkdir -p "$BENCH_DIR/data/test_data/cleaned_data"
cp "$RAW" "$CLEANED"

# --- Step 3: Run RACE evaluation ---
echo "=== Step 3: Running RACE evaluation ==="
cd "$BENCH_DIR"
$PYTHON deepresearch_bench_race.py DeepResearchX --skip_cleaning

echo ""
echo "=== Results ==="
cat "$BENCH_DIR/results/race/DeepResearchX/race_result.txt" 2>/dev/null || \
    echo "Result file not found, check logs above."
