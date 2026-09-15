#!/usr/bin/env bash
# Load development environment variables for Skill-Loop-CSP.
# Usage:
#   source scripts/dev_env.sh

# Core Python/module path
export PYTHONPATH="${PYTHONPATH:-src}"

# Local LLM endpoint defaults
export LLM_BASE_URL="${LLM_BASE_URL:-http://localhost:1234/v1}"
export LLM_API_KEY="${LLM_API_KEY:-local-key}"
export LLM_MODEL="${LLM_MODEL:-zai-org/glm-4.7-flash}"

# Live LLM eval defaults
export RUN_LIVE_LLM_TESTS="${RUN_LIVE_LLM_TESTS:-1}"
export LIVE_LLM_TIMEOUT_S="${LIVE_LLM_TIMEOUT_S:-90}"
export LIVE_LLM_TRIALS="${LIVE_LLM_TRIALS:-2}"
export LIVE_LLM_MIN_PASS_RATE="${LIVE_LLM_MIN_PASS_RATE:-0.66}"

# MCP server command defaults (used by doctor/run in --mode live)
export CRYSTALDB_MCP_CMD="${CRYSTALDB_MCP_CMD:-python -m mcp_server.server}"
export SPP_MCP_CMD="${SPP_MCP_CMD:-python -m spp_mcp.server}"
export QLIP_MCP_CMD="${QLIP_MCP_CMD:-python -m qlip_mcp.server}"

# Convenience helpers
sok_eval_live() {
  python -m sok_llm_orchestrator.cli \
    --workspace .sokllm_workspace \
    eval live-llm \
    --trials "${1:-3}" \
    --min-pass-rate "${2:-0.80}" \
    --timeout-s "${3:-90}"
}

sok_test_live() {
  pytest -q -m live_llm
}

sok_doctor_live() {
  python -m sok_llm_orchestrator.cli --workspace .sokllm_workspace doctor --mode live
}

sok_run_live() {
  python -m sok_llm_orchestrator.cli \
    --workspace .sokllm_workspace \
    run --mode live \
    --query "${1:-TiO2 rutile-like}" \
    --with-spp "${2:-true}"
}

echo "Loaded dev env:"
echo "  PYTHONPATH=${PYTHONPATH}"
echo "  LLM_BASE_URL=${LLM_BASE_URL}"
echo "  LLM_MODEL=${LLM_MODEL}"
