#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKSPACE_ROOT="$(cd "${PROJECT_ROOT}/../../.." && pwd)"
WINCTL="${WINCTL:-}"
if [[ -z "${WINCTL}" ]]; then
  for candidate in \
    "${WORKSPACE_ROOT}/lcc-platform/scripts/windows-control/winctl.sh" \
    "${WORKSPACE_ROOT}/lcc-skills/oss/windows-ssh-control-skill/scripts/winctl.sh"
  do
    if [[ -x "${candidate}" ]]; then
      WINCTL="${candidate}"
      break
    fi
  done
fi

WIN_QPY_TOOLKIT_DIR="${WIN_QPY_TOOLKIT_DIR:-D:/litechiptech/embedded/tools/lcc-qpy-host-tools}"
WIN_QPY_RUNTIME_DIR="${WIN_QPY_RUNTIME_DIR:-D:/litechiptech/embedded/staging/lcc-claw-node-qpy/usr_mirror}"
WIN_QPY_PORT="${WIN_QPY_PORT:-COM6}"
WIN_QPY_BAUD="${WIN_QPY_BAUD:-921600}"

usage() {
  cat <<'EOF'
Windows resident QuecPython toolkit wrapper

Usage:
  ./scripts/windows_qpyctl.sh doctor
  ./scripts/windows_qpyctl.sh install [--no-runtime]
  ./scripts/windows_qpyctl.sh sync-runtime [app/runtime_state.py ...]
  ./scripts/windows_qpyctl.sh deploy [--file app/command_worker.py ...] [--skip-sync] [--timeout 60]
  ./scripts/windows_qpyctl.sh start [--port COM6 | --auto-port]
  ./scripts/windows_qpyctl.sh snapshot [--port COM6 | --auto-port]
  ./scripts/windows_qpyctl.sh cleanup-tmp [--port COM6 | --auto-port] [--apply] [--json]
  ./scripts/windows_qpyctl.sh fs --json --port COM6 ls --path /usr

Environment:
  WINCTL              Absolute path to the Windows SSH control wrapper.
  WIN_QPY_TOOLKIT_DIR  Remote toolkit directory on Windows.
  WIN_QPY_RUNTIME_DIR  Remote runtime staging directory on Windows.
  WIN_QPY_PORT         Default REPL port, default COM6.
  WIN_QPY_BAUD         Default REPL baud, default 921600.
EOF
}

need_winctl() {
  if [[ ! -x "${WINCTL}" ]]; then
    echo "missing winctl: ${WINCTL}" >&2
    exit 1
  fi
}

ps_escape() {
  printf "%s" "$1" | sed "s/'/''/g"
}

ps_path() {
  printf "%s" "$1" | sed 's#/#\\#g'
}

run_ps() {
  need_winctl
  "${WINCTL}" ps "$1"
}

copy_to_win() {
  need_winctl
  "${WINCTL}" copy-to "$1" "$2"
}

ensure_remote_dir() {
  local win_dir="$1"
  run_ps "New-Item -ItemType Directory -Force '$(ps_escape "$(ps_path "$win_dir")")' | Out-Null"
}

toolkit_script_path() {
  printf "%s" "$(ps_path "${WIN_QPY_TOOLKIT_DIR}")\\windows_qpyctl.ps1"
}

invoke_toolkit() {
  local command="$1"
  shift || true
  local ps_cmd
  ps_cmd="& '$(ps_escape "$(toolkit_script_path)")' '$(ps_escape "$command")'"
  local item
  for item in "$@"; do
    ps_cmd="${ps_cmd} '$(ps_escape "$item")'"
  done
  run_ps "$ps_cmd"
}

normalize_runtime_rel() {
  local value="$1"
  value="${value#./}"
  value="${value#usr_mirror/}"
  value="${value#/}"
  if [[ -z "$value" ]]; then
    echo "empty runtime path" >&2
    exit 1
  fi
  if [[ ! -f "${PROJECT_ROOT}/usr_mirror/${value}" ]]; then
    echo "runtime file not found: ${PROJECT_ROOT}/usr_mirror/${value}" >&2
    exit 1
  fi
  printf "%s" "$value"
}

collect_runtime_files() {
  if [[ $# -gt 0 ]]; then
    local arg
    for arg in "$@"; do
      normalize_runtime_rel "$arg"
      printf '\n'
    done
    return 0
  fi

  find "${PROJECT_ROOT}/usr_mirror" -type f | LC_ALL=C sort | while IFS= read -r path; do
    path="${path#${PROJECT_ROOT}/usr_mirror/}"
    printf "%s\n" "$path"
  done
}

sync_runtime_files() {
  ensure_remote_dir "${WIN_QPY_RUNTIME_DIR}"

  local rel remote_path remote_dir
  if [[ $# -gt 0 ]]; then
    while IFS= read -r rel; do
      [[ -n "$rel" ]] || continue
      remote_path="${WIN_QPY_RUNTIME_DIR}/${rel}"
      remote_dir="${remote_path%/*}"
      ensure_remote_dir "${remote_dir}"
      copy_to_win "${PROJECT_ROOT}/usr_mirror/${rel}" "${remote_path}"
    done < <(collect_runtime_files "$@")
    return 0
  fi

  while IFS= read -r rel; do
    [[ -n "$rel" ]] || continue
    remote_path="${WIN_QPY_RUNTIME_DIR}/${rel}"
    remote_dir="${remote_path%/*}"
    ensure_remote_dir "${remote_dir}"
    copy_to_win "${PROJECT_ROOT}/usr_mirror/${rel}" "${remote_path}"
  done < <(collect_runtime_files)
}

install_toolkit() {
  local sync_runtime=1
  local runtime_files=()

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --no-runtime)
        sync_runtime=0
        shift
        ;;
      --runtime-file)
        runtime_files+=("$2")
        shift 2
        ;;
      *)
        echo "unknown install option: $1" >&2
        exit 1
        ;;
    esac
  done

  ensure_remote_dir "${WIN_QPY_TOOLKIT_DIR}"
  ensure_remote_dir "${WIN_QPY_RUNTIME_DIR}"

  local toolkit_files=(
    "host_tools/qpy_debug_snapshot.py"
    "host_tools/qpy_device_fs_cli.py"
    "host_tools/qpy_incremental_deploy.py"
    "host_tools/qpy_runtime_start.py"
    "host_tools/qpy_tmp_cleanup.py"
    "host_tools/qpy_tool_paths.py"
    "host_tools/runtime_manifest.json"
    "scripts/windows_qpyctl.ps1"
  )

  local rel src dst
  for rel in "${toolkit_files[@]}"; do
    src="${PROJECT_ROOT}/${rel}"
    dst="${WIN_QPY_TOOLKIT_DIR}/$(basename "${rel}")"
    copy_to_win "${src}" "${dst}"
  done

  if [[ "${sync_runtime}" -eq 1 ]]; then
    if [[ "${#runtime_files[@]}" -gt 0 ]]; then
      sync_runtime_files "${runtime_files[@]}"
    else
      sync_runtime_files
    fi
  fi
}

deploy_runtime() {
  local auto_port=0
  local port="${WIN_QPY_PORT}"
  local baud="${WIN_QPY_BAUD}"
  local config_mode="auto"
  local config_file=""
  local start_runtime=0
  local snapshot=0
  local json_mode=1
  local skip_sync=0
  local fail_on_tmp=0
  local timeout_sec=35
  local files=()

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --file)
        files+=("$2")
        shift 2
        ;;
      --config-mode)
        config_mode="$2"
        shift 2
        ;;
      --config-file)
        config_file="$2"
        shift 2
        ;;
      --start-runtime)
        start_runtime=1
        shift
        ;;
      --snapshot)
        snapshot=1
        shift
        ;;
      --json)
        json_mode=1
        shift
        ;;
      --no-json)
        json_mode=0
        shift
        ;;
      --skip-sync)
        skip_sync=1
        shift
        ;;
      --fail-on-tmp)
        fail_on_tmp=1
        shift
        ;;
      --timeout)
        timeout_sec="$2"
        shift 2
        ;;
      --port)
        port="$2"
        auto_port=0
        shift 2
        ;;
      --auto-port)
        auto_port=1
        shift
        ;;
      --baud)
        baud="$2"
        shift 2
        ;;
      *)
        echo "unknown deploy option: $1" >&2
        exit 1
        ;;
    esac
  done

  local normalized_files=()
  local item
  if [[ "${#files[@]}" -gt 0 ]]; then
    for item in "${files[@]}"; do
      normalized_files+=("$(normalize_runtime_rel "$item")")
    done
  fi

  if [[ "${skip_sync}" -eq 0 ]]; then
    if [[ "${#normalized_files[@]}" -gt 0 ]]; then
      sync_runtime_files "${normalized_files[@]}"
    else
      sync_runtime_files
    fi
  fi

  local args=(
    "--runtime-root" "${WIN_QPY_RUNTIME_DIR}"
    "--manifest" "${WIN_QPY_TOOLKIT_DIR}/runtime_manifest.json"
    "--baud" "${baud}"
    "--timeout" "${timeout_sec}"
    "--config-mode" "${config_mode}"
  )
  if [[ "${auto_port}" -eq 1 ]]; then
    args+=("--auto-port")
  else
    args+=("--port" "${port}")
  fi
  if [[ -n "${config_file}" ]]; then
    args+=("--config-file" "${config_file}")
  fi
  if [[ "${start_runtime}" -eq 1 ]]; then
    args+=("--start-runtime")
  fi
  if [[ "${snapshot}" -eq 1 ]]; then
    args+=("--snapshot")
  fi
  if [[ "${fail_on_tmp}" -eq 1 ]]; then
    args+=("--fail-on-tmp")
  fi
  if [[ "${json_mode}" -eq 1 ]]; then
    args+=("--json")
  fi
  if [[ "${#normalized_files[@]}" -gt 0 ]]; then
    for item in "${normalized_files[@]}"; do
      args+=("--file" "$item")
    done
  fi

  invoke_toolkit deploy "${args[@]}"
}

start_runtime_cmd() {
  local auto_port=0
  local port="${WIN_QPY_PORT}"
  local baud="${WIN_QPY_BAUD}"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --port)
        port="$2"
        auto_port=0
        shift 2
        ;;
      --auto-port)
        auto_port=1
        shift
        ;;
      --baud)
        baud="$2"
        shift 2
        ;;
      *)
        echo "unknown start option: $1" >&2
        exit 1
        ;;
    esac
  done
  local args=("--baud" "${baud}")
  if [[ "${auto_port}" -eq 1 ]]; then
    args+=("--auto-port")
  else
    args+=("--port" "${port}")
  fi
  invoke_toolkit start "${args[@]}"
}

snapshot_cmd() {
  local auto_port=0
  local port="${WIN_QPY_PORT}"
  local baud="${WIN_QPY_BAUD}"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --port)
        port="$2"
        auto_port=0
        shift 2
        ;;
      --auto-port)
        auto_port=1
        shift
        ;;
      --baud)
        baud="$2"
        shift 2
        ;;
      *)
        echo "unknown snapshot option: $1" >&2
        exit 1
        ;;
    esac
  done
  local args=("--baud" "${baud}")
  if [[ "${auto_port}" -eq 1 ]]; then
    args+=("--auto-port")
  else
    args+=("--port" "${port}")
  fi
  invoke_toolkit snapshot "${args[@]}"
}

cleanup_tmp_cmd() {
  local auto_port=0
  local port="${WIN_QPY_PORT}"
  local baud="${WIN_QPY_BAUD}"
  local timeout_sec=25
  local json_mode=0
  local apply_mode=0
  local include_rollback=0
  local paths=()

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --port)
        port="$2"
        auto_port=0
        shift 2
        ;;
      --auto-port)
        auto_port=1
        shift
        ;;
      --baud)
        baud="$2"
        shift 2
        ;;
      --timeout)
        timeout_sec="$2"
        shift 2
        ;;
      --json)
        json_mode=1
        shift
        ;;
      --apply)
        apply_mode=1
        shift
        ;;
      --include-rollback)
        include_rollback=1
        shift
        ;;
      --path)
        paths+=("$2")
        shift 2
        ;;
      *)
        echo "unknown cleanup-tmp option: $1" >&2
        exit 1
        ;;
    esac
  done

  local args=("--baud" "${baud}" "--timeout" "${timeout_sec}")
  if [[ "${auto_port}" -eq 1 ]]; then
    args+=("--auto-port")
  else
    args+=("--port" "${port}")
  fi
  if [[ "${json_mode}" -eq 1 ]]; then
    args+=("--json")
  fi
  if [[ "${apply_mode}" -eq 1 ]]; then
    args+=("--apply")
  fi
  if [[ "${include_rollback}" -eq 1 ]]; then
    args+=("--include-rollback")
  fi
  local item
  if [[ "${#paths[@]}" -gt 0 ]]; then
    for item in "${paths[@]}"; do
      args+=("--path" "${item}")
    done
  fi
  invoke_toolkit cleanup-tmp "${args[@]}"
}

cmd="${1:-}"
if [[ -z "${cmd}" ]]; then
  usage
  exit 1
fi
shift || true

case "${cmd}" in
  doctor)
    need_winctl
    "${WINCTL}" doctor
    ;;
  install)
    install_toolkit "$@"
    ;;
  sync-runtime)
    sync_runtime_files "$@"
    ;;
  deploy)
    deploy_runtime "$@"
    ;;
  start)
    start_runtime_cmd "$@"
    ;;
  snapshot)
    snapshot_cmd "$@"
    ;;
  cleanup-tmp)
    cleanup_tmp_cmd "$@"
    ;;
  fs)
    invoke_toolkit fs "$@"
    ;;
  *)
    usage
    exit 1
    ;;
esac
