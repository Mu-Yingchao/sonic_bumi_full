#!/usr/bin/env bash
set -euo pipefail

# Two-node BUMI SONIC operator.  Secrets and site-specific endpoints live in
# .local/sonic_bumi_cluster.env, which is deliberately ignored by Git.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_FILE="${BUMI_CLUSTER_CONFIG:-$REPO_ROOT/.local/sonic_bumi_cluster.env}"

usage() {
  cat <<'EOF'
Usage:
  tools_local/bumi_cluster.sh status
  tools_local/bumi_cluster.sh training-status RUN_ID
  tools_local/bumi_cluster.sh verify-code [EXPECTED_SHA]
  tools_local/bumi_cluster.sh launch-nccl RUN_ID
  tools_local/bumi_cluster.sh launch-smoke RUN_ID
  tools_local/bumi_cluster.sh launch-train RUN_ID
  tools_local/bumi_cluster.sh launch-ground-finetune RUN_ID CHECKPOINT
  tools_local/bumi_cluster.sh remote-node MACHINE_RANK RUN_ID ENVS ITERATIONS ROBOT_DIR SMPL_DIR
  tools_local/bumi_cluster.sh remote-ground-node MACHINE_RANK RUN_ID ENVS ITERATIONS ROBOT_DIR SMPL_DIR CHECKPOINT

All commands except the remote-* entry points run on the workstation.
remote-node is invoked internally on each server.  The script never stores a password.
EOF
}

load_config() {
  if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "Missing cluster config: $CONFIG_FILE" >&2
    echo "Copy tools_local/bumi_cluster.env.example to that path and edit it." >&2
    exit 2
  fi
  # shellcheck disable=SC1090
  source "$CONFIG_FILE"
  : "${MASTER_ADDR:?}" "${MASTER_PORT:?}"
  : "${REMOTE_REPO:?}" "${REMOTE_PYTHON:?}" "${RUN_ROOT:?}"
  : "${ROBOT_MOTION_DIR:?}" "${SMPL_MOTION_DIR:?}"
  NCCL_SOCKET_IFNAME="${NCCL_SOCKET_IFNAME:-=bond4}"
  NCCL_IB_HCA="${NCCL_IB_HCA:-}"
  NCCL_MASTER_PORT="${NCCL_MASTER_PORT:-29518}"
}

ssh_node() {
  local node="$1"
  shift
  local host port
  : "${GPU14_SSH:?}" "${GPU14_PORT:?}" "${GPU15_SSH:?}" "${GPU15_PORT:?}" "${SSH_KEY:?}"
  if [[ "$node" == "gpu14" ]]; then
    host="$GPU14_SSH"; port="$GPU14_PORT"
  else
    host="$GPU15_SSH"; port="$GPU15_PORT"
  fi
  ssh -i "$SSH_KEY" -p "$port" -o BatchMode=yes -o ConnectTimeout=10 "$host" "$@"
}

status() {
  local node
  for node in gpu14 gpu15; do
    echo "[$node]"
    ssh_node "$node" "hostname; git -C '$REMOTE_REPO' rev-parse --short HEAD 2>/dev/null || true; nvidia-smi --query-gpu=index,name,memory.used,utilization.gpu --format=csv,noheader; tmux list-sessions 2>/dev/null || true; pgrep -af 'accelerate.*train_agent_trl.py' || true"
  done
}

training_status() {
  local run_id="$1" node rank remote_cmd pattern
  [[ "$run_id" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "Unsafe RUN_ID" >&2; exit 2; }
  pattern="^$REMOTE_PYTHON -u gear_sonic/train_agent_trl.py .*experiment_dir=$RUN_ROOT/$run_id"
  for node in gpu14 gpu15; do
    if [[ "$node" == "gpu14" ]]; then rank=0; else rank=1; fi
    echo "[$node / node$rank]"
    printf -v remote_cmd \
      'run=%q; log="$run/node%s.log"; test -f "$log" || { echo "Missing log: $log"; exit 1; }; stat -c "log_bytes=%%s log_modified=%%y" "$log"; printf "training_ranks="; pgrep -fc %q || true; nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader; grep -E "Traceback|Error executing|CUDA out of memory|NCCL.*(error|Error)|ProcessExitedException" "$log" | tail -5 || true' \
      "$RUN_ROOT/$run_id" "$rank" "$pattern"
    ssh_node "$node" "$remote_cmd"
  done
  echo "[gpu14 / rank-0 progress and checkpoints]"
  printf -v remote_cmd \
    'run=%q; grep "Learning iteration" "$run/node0.log" | tail -1; grep -E "Mean rewards:|Total timesteps:|Iteration time:|Total time:|ETA:" "$run/node0.log" | tail -5; find "$run" -maxdepth 1 -type f \( -name "last.pt" -o -name "model_step_*.pt" \) -printf "%%f %%s bytes\\n" | sort | tail -10' \
    "$RUN_ROOT/$run_id"
  ssh_node gpu14 "$remote_cmd"
}

verify_code() {
  local expected="${1:-$(git -C "$REPO_ROOT" rev-parse HEAD)}"
  local node actual dirty
  for node in gpu14 gpu15; do
    actual="$(ssh_node "$node" "git -C '$REMOTE_REPO' rev-parse HEAD")"
    dirty="$(ssh_node "$node" "git -C '$REMOTE_REPO' status --porcelain --untracked-files=no")"
    [[ "$actual" == "$expected" ]] || { echo "$node SHA mismatch: $actual != $expected" >&2; exit 1; }
    [[ -z "$dirty" ]] || { echo "$node tracked worktree is dirty" >&2; exit 1; }
    echo "$node CODE_OK $actual"
  done
}

remote_start() {
  local node="$1" rank="$2" run_id="$3" envs="$4" iterations="$5" robot_dir="$6" smpl_dir="$7"
  local inner remote_cmd session_name
  session_name="sonic_${run_id}_node${rank}"
  printf -v inner \
    "exec bash tools_local/bumi_cluster.sh remote-node %q %q %q %q %q %q > %q 2>&1 < /dev/null" \
    "$rank" "$run_id" "$envs" "$iterations" "$robot_dir" "$smpl_dir" "$RUN_ROOT/$run_id/node${rank}.log"
  printf -v remote_cmd \
    "cd %q && mkdir -p %q && command -v tmux >/dev/null && ! tmux has-session -t %q 2>/dev/null && tmux new-session -d -s %q bash -lc %q && echo STARTED_TMUX:%q" \
    "$REMOTE_REPO" "$RUN_ROOT/$run_id" "$session_name" "$session_name" "$inner" "$session_name"
  # Provisioning copies a machine-local config to REMOTE_REPO/.local on both nodes.
  ssh_node "$node" "$remote_cmd"
}

remote_ground_start() {
  local node="$1" rank="$2" run_id="$3" envs="$4" iterations="$5"
  local robot_dir="$6" smpl_dir="$7" checkpoint="$8"
  local inner remote_cmd session_name
  session_name="sonic_${run_id}_node${rank}"
  printf -v inner \
    "exec bash tools_local/bumi_cluster.sh remote-ground-node %q %q %q %q %q %q %q > %q 2>&1 < /dev/null" \
    "$rank" "$run_id" "$envs" "$iterations" "$robot_dir" "$smpl_dir" "$checkpoint" \
    "$RUN_ROOT/$run_id/node${rank}.log"
  printf -v remote_cmd \
    "cd %q && mkdir -p %q && command -v tmux >/dev/null && ! tmux has-session -t %q 2>/dev/null && tmux new-session -d -s %q bash -lc %q && echo STARTED_TMUX:%q" \
    "$REMOTE_REPO" "$RUN_ROOT/$run_id" "$session_name" "$session_name" "$inner" "$session_name"
  ssh_node "$node" "$remote_cmd"
}

launch() {
  local mode="$1" run_id="$2" envs iterations robot_dir smpl_dir
  case "$mode" in
    smoke)
      envs="${SMOKE_ENVS_PER_GPU:-64}"; iterations="${SMOKE_ITERATIONS:-5}"
      robot_dir="${SMOKE_ROBOT_MOTION_DIR:-$ROBOT_MOTION_DIR}"
      smpl_dir="${SMOKE_SMPL_MOTION_DIR:-$SMPL_MOTION_DIR}"
      ;;
    train)
      envs="${TRAIN_ENVS_PER_GPU:-4096}"; iterations="${TRAIN_ITERATIONS:-100000}"
      robot_dir="$ROBOT_MOTION_DIR"; smpl_dir="$SMPL_MOTION_DIR"
      ;;
    *) echo "Unknown mode: $mode" >&2; exit 2 ;;
  esac
  [[ "$run_id" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "Unsafe RUN_ID" >&2; exit 2; }
  verify_code
  echo "Starting rank 1 first; it will wait for rank 0 rendezvous."
  remote_start gpu15 1 "$run_id" "$envs" "$iterations" "$robot_dir" "$smpl_dir"
  remote_start gpu14 0 "$run_id" "$envs" "$iterations" "$robot_dir" "$smpl_dir"
  echo "Started $mode: run=$run_id, envs/GPU=$envs, world=16, iterations=$iterations"
}

launch_ground_finetune() {
  local run_id="$1" checkpoint="$2"
  local envs="${GROUND_FINETUNE_ENVS_PER_GPU:-4096}"
  local iterations="${GROUND_FINETUNE_ITERATIONS:-50000}"
  [[ "$run_id" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "Unsafe RUN_ID" >&2; exit 2; }
  [[ "$checkpoint" == /* ]] || { echo "CHECKPOINT must be an absolute path" >&2; exit 2; }
  verify_code
  for node in gpu14 gpu15; do
    ssh_node "$node" "test -s '$checkpoint'" || {
      echo "$node missing checkpoint: $checkpoint" >&2
      exit 1
    }
  done
  echo "Starting ground-contact fine-tune rank 1 first; it will wait for rank 0."
  remote_ground_start gpu15 1 "$run_id" "$envs" "$iterations" \
    "$ROBOT_MOTION_DIR" "$SMPL_MOTION_DIR" "$checkpoint"
  remote_ground_start gpu14 0 "$run_id" "$envs" "$iterations" \
    "$ROBOT_MOTION_DIR" "$SMPL_MOTION_DIR" "$checkpoint"
  echo "Started ground fine-tune: run=$run_id, checkpoint=$checkpoint, envs/GPU=$envs, world=16, iterations=$iterations"
}

remote_nccl_start() {
  local node="$1" rank="$2" run_id="$3" inner remote_cmd
  printf -v inner \
    "exec bash tools_local/bumi_cluster.sh remote-nccl %q > %q 2>&1 < /dev/null" \
    "$rank" "$RUN_ROOT/$run_id/nccl_node${rank}.log"
  printf -v remote_cmd \
    "cd %q && mkdir -p %q && setsid -f bash -c %q && echo STARTED" \
    "$REMOTE_REPO" "$RUN_ROOT/$run_id" "$inner"
  ssh_node "$node" "$remote_cmd"
}

launch_nccl() {
  local run_id="$1"
  [[ "$run_id" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "Unsafe RUN_ID" >&2; exit 2; }
  verify_code
  remote_nccl_start gpu15 1 "$run_id"
  remote_nccl_start gpu14 0 "$run_id"
  echo "Started NCCL smoke: $run_id"
}

remote_nccl() {
  local rank="$1"
  cd "$REMOTE_REPO"
  export NCCL_SOCKET_IFNAME
  export NCCL_IB_DISABLE="${NCCL_IB_DISABLE:-0}"
  if [[ -n "$NCCL_IB_HCA" ]]; then export NCCL_IB_HCA; fi
  exec "$REMOTE_PYTHON" -m torch.distributed.run \
    --nnodes=2 --nproc-per-node=8 --node-rank="$rank" \
    --master-addr="$MASTER_ADDR" --master-port="$NCCL_MASTER_PORT" \
    tools_local/nccl_smoke.py
}

remote_node() {
  local rank="$1" run_id="$2" envs="$3" iterations="$4" robot_dir="$5" smpl_dir="$6"
  local experiment_dir="$RUN_ROOT/$run_id"
  cd "$REMOTE_REPO"
  [[ -x "$REMOTE_PYTHON" ]] || { echo "Python missing: $REMOTE_PYTHON" >&2; exit 1; }
  [[ "${OMNI_KIT_ACCEPT_EULA:-NO}" == "YES" ]] || {
    echo "NVIDIA Omniverse EULA has not been explicitly accepted" >&2
    exit 1
  }
  [[ -d "$robot_dir" ]] || { echo "Robot data missing: $robot_dir" >&2; exit 1; }
  [[ -d "$smpl_dir" ]] || { echo "SMPL data missing: $smpl_dir" >&2; exit 1; }
  # Avoid a machine-global /tmp/isaaclab owned by another account.
  export TMPDIR="${ISAACLAB_TMPDIR:-$RUN_ROOT/.tmp/$USER/node$rank}"
  mkdir -p "$TMPDIR"
  export NCCL_SOCKET_IFNAME
  export OMNI_KIT_ACCEPT_EULA
  # Optional user-space system libraries (for example libGLU on a node where
  # the package is not installed globally).
  if [[ -n "${SITE_LIBRARY_DIR:-}" ]]; then
    export LD_LIBRARY_PATH="$SITE_LIBRARY_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  fi
  export NCCL_IB_DISABLE="${NCCL_IB_DISABLE:-0}"
  export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
  if [[ -n "$NCCL_IB_HCA" ]]; then export NCCL_IB_HCA; fi
  exec "$REMOTE_PYTHON" -m accelerate.commands.launch \
    --multi_gpu --num_machines=2 --num_processes=16 \
    --machine_rank="$rank" \
    --main_process_ip="$MASTER_ADDR" --main_process_port="$MASTER_PORT" \
    gear_sonic/train_agent_trl.py \
    +exp=manager/universal_token/all_modes/sonic_bumi3 \
    +resume=false checkpoint=null auto_load_latest=false use_wandb=false headless=True \
    "experiment_dir=$experiment_dir" "num_envs=$envs" \
    "++algo.config.num_learning_iterations=$iterations" \
    "++manager_env.commands.motion.motion_lib_cfg.motion_file=$robot_dir" \
    "++manager_env.commands.motion.motion_lib_cfg.smpl_motion_file=$smpl_dir" \
    '++manager_env.commands.motion.motion_lib_cfg.exclude_motion_keys=[]'
}

remote_ground_node() {
  local rank="$1" run_id="$2" envs="$3" iterations="$4"
  local robot_dir="$5" smpl_dir="$6" checkpoint="$7"
  local experiment_dir="$RUN_ROOT/$run_id"
  cd "$REMOTE_REPO"
  [[ -x "$REMOTE_PYTHON" ]] || { echo "Python missing: $REMOTE_PYTHON" >&2; exit 1; }
  [[ -s "$checkpoint" ]] || { echo "Checkpoint missing: $checkpoint" >&2; exit 1; }
  [[ "${OMNI_KIT_ACCEPT_EULA:-NO}" == "YES" ]] || {
    echo "NVIDIA Omniverse EULA has not been explicitly accepted" >&2
    exit 1
  }
  [[ -d "$robot_dir" ]] || { echo "Robot data missing: $robot_dir" >&2; exit 1; }
  [[ -d "$smpl_dir" ]] || { echo "SMPL data missing: $smpl_dir" >&2; exit 1; }
  export TMPDIR="${ISAACLAB_TMPDIR:-$RUN_ROOT/.tmp/$USER/node$rank}"
  mkdir -p "$TMPDIR"
  export NCCL_SOCKET_IFNAME OMNI_KIT_ACCEPT_EULA
  if [[ -n "${SITE_LIBRARY_DIR:-}" ]]; then
    export LD_LIBRARY_PATH="$SITE_LIBRARY_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  fi
  export NCCL_IB_DISABLE="${NCCL_IB_DISABLE:-0}"
  export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
  if [[ -n "$NCCL_IB_HCA" ]]; then export NCCL_IB_HCA; fi
  exec "$REMOTE_PYTHON" -m accelerate.commands.launch \
    --multi_gpu --num_machines=2 --num_processes=16 \
    --machine_rank="$rank" \
    --main_process_ip="$MASTER_ADDR" --main_process_port="$MASTER_PORT" \
    gear_sonic/train_agent_trl.py \
    +exp=manager/universal_token/all_modes/sonic_bumi3_ground_finetune \
    +resume=false "checkpoint=$checkpoint" auto_load_latest=false use_wandb=false headless=True \
    "experiment_dir=$experiment_dir" "num_envs=$envs" \
    "++algo.config.num_learning_iterations=$iterations" \
    "++manager_env.commands.motion.motion_lib_cfg.motion_file=$robot_dir" \
    "++manager_env.commands.motion.motion_lib_cfg.smpl_motion_file=$smpl_dir" \
    '++manager_env.commands.motion.motion_lib_cfg.exclude_motion_keys=[]'
}

case "${1:-}" in
  status) load_config; status ;;
  training-status) [[ $# -eq 2 ]] || { usage; exit 2; }; load_config; training_status "$2" ;;
  verify-code) load_config; verify_code "${2:-}" ;;
  launch-nccl) [[ $# -eq 2 ]] || { usage; exit 2; }; load_config; launch_nccl "$2" ;;
  launch-smoke) [[ $# -eq 2 ]] || { usage; exit 2; }; load_config; launch smoke "$2" ;;
  launch-train) [[ $# -eq 2 ]] || { usage; exit 2; }; load_config; launch train "$2" ;;
  launch-ground-finetune) [[ $# -eq 3 ]] || { usage; exit 2; }; load_config; launch_ground_finetune "$2" "$3" ;;
  remote-node) [[ $# -eq 7 ]] || { usage; exit 2; }; load_config; remote_node "$2" "$3" "$4" "$5" "$6" "$7" ;;
  remote-ground-node) [[ $# -eq 8 ]] || { usage; exit 2; }; load_config; remote_ground_node "$2" "$3" "$4" "$5" "$6" "$7" "$8" ;;
  remote-nccl) [[ $# -eq 2 ]] || { usage; exit 2; }; load_config; remote_nccl "$2" ;;
  *) usage; exit 2 ;;
esac
