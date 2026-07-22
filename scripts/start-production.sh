#!/usr/bin/env bash
set -euo pipefail

dry_run=false
deploy_mode=""
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry_run=true ;;
    --images) deploy_mode=images ;;
    --build) deploy_mode=build ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

if docker compose version >/dev/null 2>&1; then
  compose=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  compose=(docker-compose)
else
  echo "Docker Compose is required." >&2
  exit 1
fi

env_value() {
  local key="$1" fallback="$2" value="${!1-}"
  if [[ -z "$value" && -f .env ]]; then
    value="$(sed -n "s/^${key}=//p" .env | tail -1 | sed 's/^['\"'\'']//;s/['\"'\'']$//')"
  fi
  printf '%s' "${value:-$fallback}"
}

policy="$(env_value LLM_RUNTIME_POLICY auto)"
deploy_mode="${deploy_mode:-$(env_value CERTIPROOF_DEPLOY_MODE build)}"
app_env="$(env_value APP_ENV development)"
version="$(env_value CERTIPROOF_VERSION latest)"
if [[ "$deploy_mode" == "images" && "$app_env" =~ ^(prod|production)$ ]]; then
  [[ "$version" != "latest" && "$version" != replace-with-* ]] || {
    echo "Production image deployments require an immutable CERTIPROOF_VERSION." >&2
    exit 1
  }
fi
gpu=false
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  gpu=true
fi
export LLM_GPU_AVAILABLE="$gpu"

profiles=(--profile production)
case "$policy" in
  auto)
    if $gpu; then
      export VLLM_MODEL="$(env_value VLLM_MODEL Qwen/Qwen3-14B)"
      profiles+=(--profile gpu)
    fi
    ;;
  local)
    if $gpu; then
      export VLLM_MODEL="$(env_value VLLM_MODEL Qwen/Qwen3-14B)"
      profiles+=(--profile gpu)
    else
      export LLAMA_CPP_MODEL="$(env_value LLAMA_CPP_MODEL qwen3-14b)"
      model_dir="$(env_value LLM_MODEL_DIR ./models/llm)"
      model_file="$(env_value LLAMA_CPP_MODEL_FILE qwen3-14b-q4_k_m.gguf)"
      test -f "$model_dir/$model_file" || { echo "Missing llama.cpp model: $model_dir/$model_file" >&2; exit 1; }
      profiles+=(--profile cpu-local)
    fi
    ;;
  cloud|ollama)
    ;;
  vllm)
    $gpu || { echo "LLM_RUNTIME_POLICY=vllm requires an NVIDIA GPU." >&2; exit 1; }
    export VLLM_MODEL="$(env_value VLLM_MODEL Qwen/Qwen3-14B)"
    profiles+=(--profile gpu)
    ;;
  llama_cpp)
    export LLAMA_CPP_MODEL="$(env_value LLAMA_CPP_MODEL qwen3-14b)"
    model_dir="$(env_value LLM_MODEL_DIR ./models/llm)"
    model_file="$(env_value LLAMA_CPP_MODEL_FILE qwen3-14b-q4_k_m.gguf)"
    test -f "$model_dir/$model_file" || { echo "Missing llama.cpp model: $model_dir/$model_file" >&2; exit 1; }
    profiles+=(--profile cpu-local)
    ;;
  *)
    echo "Unsupported LLM_RUNTIME_POLICY: $policy" >&2
    exit 1
    ;;
esac

case "$deploy_mode" in
  build)
    command=("${compose[@]}" "${profiles[@]}" up -d --build --remove-orphans)
    ;;
  images)
    pull_command=("${compose[@]}" "${profiles[@]}" pull)
    command=("${compose[@]}" "${profiles[@]}" up -d --no-build --remove-orphans)
    ;;
  *)
    echo "Unsupported CERTIPROOF_DEPLOY_MODE: $deploy_mode" >&2
    exit 1
    ;;
esac

echo "Deploy mode=$deploy_mode inference policy=$policy gpu=$gpu profiles=${profiles[*]}"
if $dry_run; then
  if [[ "$deploy_mode" == "images" ]]; then
    printf 'Pull command:'; printf ' %q' "${pull_command[@]}"; printf '\n'
  fi
  printf 'Start command:'; printf ' %q' "${command[@]}"; printf '\n'
  exit 0
fi
if [[ "$deploy_mode" == "images" ]]; then
  "${pull_command[@]}"
fi
exec "${command[@]}"
