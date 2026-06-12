#!/usr/bin/env bash
# Ablation sweep: 6 RAG-stack configs against local stack (http://localhost:8000).
# Throwaway orchestration glue for the Qwen×GigaChat ablation experiment.
set -u
BASE="${ADAPTA_REPO_ROOT:-/Users/teterinsa/Projects/adapta-ai}"
cd "$BASE/backend" || exit 1
PY="$BASE/data/rag_eval/.venv/bin/python"
EVAL="scripts/eval_rag.py"
URL="http://localhost:8000"
GOLDEN_HI="$BASE/data/rag_eval/golden_set_hi.yaml"
GOLDEN_RU="$BASE/data/rag_eval/golden_set.yaml"
RUNS="$BASE/data/rag_eval/runs"
PW="$(grep -E '^ADAPTA_DEMO_PASSWORD=' "$BASE/infra/.env" | cut -d= -f2-)"

run_arm () {
  local label="$1"; shift
  local golden="$1"; shift
  local lang="$1"; shift
  local rundir="$RUNS/ablation_${label}"
  echo "==================== ARM: $label ($lang) ===================="
  echo "extra: $*"
  "$PY" "$EVAL" run \
    --prod-url "$URL" \
    --demo-password "$PW" \
    --golden-set "$golden" \
    --lang "$lang" \
    --label "$label" \
    --run-dir "$rundir" \
    "$@"
  echo "ARM $label exit=$? rundir=$rundir"
}

echo "### SWEEP START"
run_arm ru_baseline   "$GOLDEN_RU" ru
run_arm both_hi       "$GOLDEN_HI" hi
run_arm qwen_only_72b "$GOLDEN_HI" hi --pipeline-mode qwen_only --qwen-model qwen/qwen-2.5-72b-instruct
run_arm gigachat_only "$GOLDEN_HI" hi --pipeline-mode gigachat_only
run_arm qwen3_235b    "$GOLDEN_HI" hi --pipeline-mode qwen_only --qwen-model qwen/qwen3-235b-a22b
run_arm qwen_max      "$GOLDEN_HI" hi --pipeline-mode qwen_only --qwen-model qwen/qwen3-max
echo "### SWEEP DONE"
