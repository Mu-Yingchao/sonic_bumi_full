# BUMI3 本地部署与双机 16 GPU 训练指南

本文只描述当前仓库的 BUMI3 原生 SONIC 路径。旧 `gear_sonic_deploy` 的 G1 C++
DDS/CSV 三终端流程不是当前 BUMI3 sim2sim 入口，不能混用按键和观测约定。

本地 VSCode/Codex 作为控制中枢、GitHub 作为代码唯一真源、多节点作为计算端的完整
可复用规范见 `codex_local_control_multi_node_training.md`。

## 1. 代码一致性规则

Git commit 是唯一代码版本标识。算法、配置、资产或部署代码只能先在开发机修改、测试、
提交并推送，再让两台服务器快进到同一个 commit；禁止直接在服务器工作树修改源码。
数据、环境、日志和 checkpoint 放在仓库外，不提交 Git。每次启动前执行：

```bash
tools_local/bumi_cluster.sh verify-code
```

唯一真源是公开仓库 `https://github.com/Mu-Yingchao/sonic_bumi_full` 的 `main` 分支。
开发机使用 SSH URL 推送，两台服务器使用 HTTPS URL 只读拉取。真实服务器地址放在被忽略的
`.local/sonic_bumi_cluster.env`，不得记录密码或私钥正文。

当前三份代码路径统一为：

- 本地：`/home/yingchaomu/下载/sonic_bumi_full`
- GPU14：`/data/ouqin/sonic_bumi_full`
- GPU15：`/data/ouqin/sonic_bumi_full`

两台服务器的 `/data` 都是本地 NVMe 文件系统，不是内存盘；GPU14、GPU15 分别约有
2.4 TiB、2.6 TiB 可用空间。旧 `/data/muyingchao/SONIC_BUMI` 和旧本地
`bumi_local_deploy_bundle` 都不是本训练任务的源码、数据或 Python 导入来源。

日常修改同步顺序：

```bash
# 只在本地开发机修改源码
cd /home/yingchaomu/下载/sonic_bumi_full
git status --short
git pull --ff-only
# 修改并完成测试后
git add <明确的文件>
git commit -m "说明本次修改"
git push origin main

# 再让两台服务器分别更新；服务器工作树不得直接编辑
cd /data/ouqin/sonic_bumi_full
git status --short
git pull --ff-only
```

最后回到本地运行 `bash tools_local/bumi_cluster.sh verify-code`，必须看到两台
`CODE_OK` 和同一个完整 SHA 后，修改才算完成同步。数据、环境、日志、checkpoint、ONNX
和 `.local` 密钥配置不通过 Git 同步。

## 2. 本地 MuJoCo sim2sim

可直接复制的离线 Robot/SMPL、Isaac Lab play 和 PICO 实时遥操命令集中在
仓库根目录 `deploy.md`。

安装（已有 Isaac Lab 环境时可直接复用其 Python）：

```bash
cd /home/yingchaomu/下载/sonic_bumi_full
python3 -m venv .venv_sim
source .venv_sim/bin/activate
python -m pip install --upgrade pip
python -m pip install -e 'gear_sonic[sim]'
python gear_sonic/tools/validate_bumi3_sim2sim.py --skip-smoke
```

若第一条命令提示 `ensurepip` 或 `venv` 不可用，先安装当前系统对应的 `python3-venv`；以后
每次新开本地部署终端只需 `cd` 到仓库并执行 `source .venv_sim/bin/activate`，不必重复安装。

### 2.1 本机必须用 NVIDIA 启动器

本机是 Intel 核显连接显示器、RTX 4090 处于 PRIME `on-demand` 的 X11 配置。
直接执行 `python ...run_bumi3_sim2sim.py` 时，OpenGL 会落到 Mesa
`llvmpipe`（CPU 软件渲染），MuJoCo 窗口会明显卡顿。本地有窗口的
Robot/SMPL 部署统一使用以下启动器：

```bash
tools_local/run_bumi3_sim2sim_nvidia.sh <原 run_bumi3_sim2sim.py 的所有参数>
```

它只把 GLFW/OpenGL 渲染强制到 RTX 4090，不会改变 ONNX provider、策略输入输出、
MuJoCo 物理或 50 Hz 控制频率。服务器 `--headless` 验收仍直接使用 Python
入口。如需恢复 OpenGL 垂直同步，在命令前加 `BUMI_GL_VSYNC=1`。

### 2.2 MuJoCo 动力学与接触契约

运行器加载 MJCF 后，按关节名称将 21 个驱动关节的 `dof_armature`
全部覆盖为 `0.01`，并校验覆盖结果；root freejoint 的 6 个自由度不在
映射表中，保持 `0`。XML 保留 `armature=0.03` 作为资产默认值，但不是
sim-to-sim 的实际运行值。

接触参数对齐已验证的 4340 设置：`condim=6`、
`friction="1 0.05 0.01"`、`cone=elliptic`、`impratio=10`、
`solref="0.01 1"`、Newton `iterations=80`；被动关节 `damping=0.001`。
本次保留当前已审计的连杆质量、惯量、独立碰撞体和自碰撞隔离，不把
4340 文件里同时发生的资产拓扑变化误归因为单一接触参数效果。

实测 viewer 进程已出现在 RTX 4090 的 NVIDIA 图形进程列表，占用约
179 MiB 显存。单环境 ONNX 使用 2/1 intra/inter-op 线程，PICO PyTorch
也使用 2/1；原默认会在一次 1470 维推理中使用约 15 个 CPU 核，与
viewer 和 PICO 生产端产生调度抢占。

Robot Encoder（`1170 -> 21`）：

```bash
source .venv_sim/bin/activate
tools_local/run_bumi3_sim2sim_nvidia.sh \
  --encoder robot \
  --policy /绝对路径/model_step_030000_g1.onnx \
  --motion /绝对路径/robot_motion.pkl
```

SMPL Encoder（`1470 -> 21`），推荐传入同名 Robot 动作用于一致的初始状态和红色影子：

```bash
tools_local/run_bumi3_sim2sim_nvidia.sh \
  --encoder smpl \
  --policy /绝对路径/model_step_030000_smpl.onnx \
  --motion /绝对路径/smpl_motion.pkl \
  --robot-motion /绝对路径/robot_motion.pkl
```

窗口中只需：先单击窗口，按 `T` 播放，按 `P` 切换清单动作。没有 `]`、`9`，不需要
两个或三个终端，也不需要先把 PKL 转 CSV。白色是不透明的 MuJoCo policy 机器人，红色
半透明机器人是 Robot 参考影子。无窗口验收命令：

```bash
python gear_sonic/scripts/run_bumi3_sim2sim.py \
  --encoder robot --policy /绝对路径/model_g1.onnx \
  --motion /绝对路径/robot.pkl \
  --headless --no-real-time --duration 10
```

批量动作使用 `--dataset /绝对路径/dataset.json`；详细清单格式、首帧等待语义、SMPL
字段契约和已知限制见 `bumi3_sim2sim.md`。

当前仓库中可直接测试的本地资产（均位于被 Git 忽略的运行数据目录）是：

```text
data/bumi3_sim2sim_test/robot/wave_R_001__A428.pkl
data/bumi3_sim2sim_test/smpl/wave_R_001__A428.pkl
models/deployment/robot/model_step_030000.onnx
models/deployment/robot/model_step_050000.onnx
models/deployment/robot/model_step_064000_robot.onnx
models/deployment/robot/model_step_086000.onnx
models/deployment/smpl/model_step_030000.onnx
models/deployment/smpl/model_step_050000.onnx
models/deployment/smpl/model_step_064000_smpl.onnx
models/deployment/smpl/model_step_086000.onnx
```

当前最新综合候选为 86000-step，Robot 与 SMPL 测试可分别执行：

```bash
cd /home/yingchaomu/下载/sonic_bumi_full
source .venv_sim/bin/activate
tools_local/run_bumi3_sim2sim_nvidia.sh \
  --encoder robot \
  --policy models/deployment/robot/model_step_086000.onnx \
  --motion data/bumi3_sim2sim_test/robot/wave_R_001__A428.pkl

tools_local/run_bumi3_sim2sim_nvidia.sh \
  --encoder smpl \
  --policy models/deployment/smpl/model_step_086000.onnx \
  --motion data/bumi3_sim2sim_test/smpl/wave_R_001__A428.pkl \
  --robot-motion data/bumi3_sim2sim_test/robot/wave_R_001__A428.pkl
```

正式跑物理前，建议先把上面命令末尾加 `--validate-only`；看到
`BUMI3_SIM2SIM_VALIDATE_ONLY=PASS` 后再去掉该参数。服务器或无窗口快速验收：

```bash
python gear_sonic/scripts/run_bumi3_sim2sim.py \
  --encoder robot \
  --policy models/deployment/robot/model_step_086000.onnx \
  --motion data/bumi3_sim2sim_test/robot/wave_R_001__A428.pkl \
  --headless --no-real-time --duration 10
```

86000 的 wave 无窗口验收两路均完整运行 500/500 帧，最低根高度分别为
Robot `0.4572 m`、SMPL `0.4493 m`。深蹲轨迹两路最低根高度均为
`0.2566 m`，说明髋膝活动范围没有被部署端普遍锁死。

真正跪地仍未通过。训练集包含 76 条名称明确的 kneeling Robot 动作，本地已保留
以下三对运行测试数据（这些运行数据仍由 Git 忽略）：

```text
data/bumi3_sim2sim_test/kneeling/{robot,smpl}/kneeling_start_001__A037.pkl
data/bumi3_sim2sim_test/kneeling/{robot,smpl}/kneeling_loop_003__A040.pkl
data/bumi3_sim2sim_test/kneeling/{robot,smpl}/kneeling_stop_003__A049.pkl
```

86000 的 start 轨迹能够下降但没有完整复现跪姿，loop/stop 在膝地接触阶段会倒塌，
Robot 与 SMPL 表现一致。当前证据将问题限定为策略对膝地接触的鲁棒性或
Isaac Lab/MuJoCo 接触与碰撞差异，而非 GPU 渲染、关节映射或 PICO 独有问题。
下一步需要在 Isaac Lab play 中用同一 motion/checkpoint 对照，再比较两端膝、脚
碰撞体及接触力。

## 3. Isaac Lab play 与 ONNX 导出

`.pt` 的 play/eval 使用训练环境，必须把 checkpoint 配套配置中的服务器数据路径覆盖为
本机绝对路径：
它需要 PyTorch `*.pt` 和 Isaac Lab，不使用 ONNX，也不能在轻量 `.venv_sim`
中运行。当前本机未安装 Isaac Lab 环境且未保存 checkpoint；服务器的 16 GPU
训练还在运行，不得同时启动 play 抢占训练显存。完整的 checkpoint 下载、Robot/SMPL
play 命令见 `deploy.md` 第 4 节。

```bash
python gear_sonic/eval_agent_trl.py \
  checkpoint=/绝对路径/model_step_030000.pt \
  ++num_envs=1 ++headless=false \
  ++manager_env.commands.motion.motion_lib_cfg.motion_file=/绝对路径/robot目录 \
  ++manager_env.commands.motion.motion_lib_cfg.smpl_motion_file=/绝对路径/smpl目录
```

只导出联合 ONNX 时增加 `++headless=true ++export_onnx_only=true`。导出的
`*_g1.onnx` 用于 Robot reference，`*_smpl.onnx` 用于离线 SMPL 以及后续的
SMPL/PICO 5 点实时参考。不要交叉使用两种输入维度。

## 4. 双机 16 GPU 训练策略

每张 GPU 一个进程，2 台 × 8 GPU 共 16 个 Accelerate/DDP rank。两台机器没有共享盘，
因此必须各自保存同路径、同内容的数据与环境；world rank 0 位于 GPU14，只有它写正式
checkpoint。`num_envs` 是每张 GPU 的环境数。SONIC 论文使用 4096/GPU，因此
128 GPU 正式训练为 524,288 个并行环境；本项目正式配置也保持 4096/GPU：

- 正式 16 GPU 使用 `4096/GPU`，全局 `65536`，用更大的 PPO batch 获取论文所述的
  多 GPU 优化稳定性收益；
- `2048/GPU`（全局 `32768`）只作为与原 8 卡 × 4096 保持相同全局 batch 的可选
  强扩展速度对照，不能当成正式扩展实验；
- 先做 5 iteration/64 env 每卡的双机 smoke，再启动 100000 iteration 正式训练。

初始化本机配置：

```bash
mkdir -p .local
cp tools_local/bumi_cluster.env.example .local/sonic_bumi_cluster.env
# 编辑地址、SSH key、远端 Python、Robot/SMPL 数据目录；不要填写密码。
bash tools_local/bumi_cluster.sh status
bash tools_local/bumi_cluster.sh verify-code
bash tools_local/bumi_cluster.sh launch-nccl bumi3_nccl_smoke_YYYYMMDD_HHMMSS
```

环境、数据、NCCL 双机 collective 和 NVIDIA Isaac Sim EULA均验证后：

```bash
bash tools_local/bumi_cluster.sh launch-smoke bumi3_16gpu_smoke_YYYYMMDD_HHMMSS
# 检查两台 node0.log/node1.log、16 个 rank、PPO step、有限指标和 GPU 利用率后：
bash tools_local/bumi_cluster.sh launch-train bumi3_16gpu_scratch_100k_YYYYMMDD_HHMMSS
```

正式启动参数固定包含 `resume=false checkpoint=null auto_load_latest=false`，因此不会加载
旧策略。默认正式配置每卡 4096 env；若要做保持 32768 全局环境的速度对照，在本机
私有配置中另设 `TRAIN_ENVS_PER_GPU=2048`，并使用新的 run ID，不能覆盖正式实验。

### 4.1 一条命令确认训练进度和 16 GPU

以下命令必须在本地开发机执行，不要在 GPU14/GPU15 上再绕公网 SSH：

```bash
cd /home/yingchaomu/下载/sonic_bumi_full
RUN_ID=sonic_bumi3_16gpu_4096_scratch_100k_20260911_150534
bash tools_local/bumi_cluster.sh training-status "$RUN_ID"
```

健康输出应同时满足：GPU14 和 GPU15 都显示 `training_ranks=8`，共16个 rank；每张卡有约
15 GiB 显存占用且利用率会变化；GPU14 最后显示持续增长的 `Learning iteration` 和
`Total timesteps`；错误区为空。GPU15 是 ranks 8～15，非 global-rank 0 默认不重复输出
训练表格或 TensorBoard，所以 `node1.log` 在 motion 加载结束后长期不增长是正常现象，
不能据此判断 GPU15 没训练。梯度同步需要16个 rank 同时到达 collective；任何一个 rank
退出后整个 DDP 作业都会报错退出。

### 4.2 查看文本日志

从本地开发机执行：

```bash
RUN_ID=sonic_bumi3_16gpu_4096_scratch_100k_20260911_150534

# GPU14/world-rank 0：训练指标、checkpoint 写入端
ssh -i ~/.ssh/id_ed25519_sonic_bumi -p 22115 ouqin@117.161.121.54 \
  "tail -f /data/ouqin/runs/$RUN_ID/node0.log"

# GPU15：非零 rank 的初始化和报错日志
ssh -i ~/.ssh/id_ed25519_sonic_bumi -p 22116 ouqin@117.161.121.54 \
  "tail -f /data/ouqin/runs/$RUN_ID/node1.log"

```

`tail -f` 用 `Ctrl+C` 退出只会停止查看，不会停止训练。如果终端提示符已经是
`muyingchao@RTX4090-gpu-014` 或 `ouqin@RTX4090-gpu-014`，直接运行：

```bash
tail -f /data/ouqin/runs/sonic_bumi3_16gpu_4096_scratch_100k_20260911_150534/node0.log
```

不要在服务器里使用 `~/.ssh/id_ed25519_sonic_bumi` 再连接公网地址；该私钥在本地开发机，
而且服务器经公网映射回连自己可能得到 `Connection refused`。

### 4.3 TensorBoard 曲线

当前 GPU14 已在 `tensorboard_bumi3` tmux session 中启动 TensorBoard 6006端口。本机的
6006可能被 VS Code 端口代理占用，因此默认使用本地16006映射远端6006。每次查看时，只需
在本地开发机建立隧道并保持该终端开启：

```bash
ssh -N -i ~/.ssh/id_ed25519_sonic_bumi -p 22115 \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -L 16006:127.0.0.1:6006 ouqin@117.161.121.54
```

然后浏览器打开 `http://127.0.0.1:16006`。这个 SSH 终端没有输出且一直占用前台是正常
状态，`Ctrl+C` 会关闭隧道但不会停止服务器训练或 TensorBoard。

出现 `Address already in use` 时，先在本地检查占用者和HTTP响应：

```bash
ss -ltnp '( sport = :16006 )'
curl -I --max-time 5 http://127.0.0.1:16006/
```

- 若返回 `HTTP/1.1 200 OK`，说明已有可用隧道，不要重复启动，直接打开浏览器。
- 若监听进程是 `code` 且请求超时，说明端口被 VS Code 占用，改用本地26006：

```bash
ssh -N -i ~/.ssh/id_ed25519_sonic_bumi -p 22115 \
  -o ExitOnForwardFailure=yes \
  -L 26006:127.0.0.1:6006 ouqin@117.161.121.54
# 浏览器打开 http://127.0.0.1:26006
```

`ExitOnForwardFailure=yes` 很重要：它保证本地端口绑定失败时 SSH 整体退出，不会发生“只绑定
IPv6、浏览器的IPv4请求却被其他程序接走”的半成功状态。

检查/重启服务器上的 TensorBoard（先从本地 SSH 登录 GPU14，再执行）：

```bash
tmux has-session -t tensorboard_bumi3 && echo TENSORBOARD_RUNNING
ss -ltn | grep ':6006'

RUN_ID=sonic_bumi3_16gpu_4096_scratch_100k_20260911_150534
tmux new-session -d -s tensorboard_bumi3 \
  "/data/ouqin/envs/sonic_bumi/bin/python -m tensorboard.main \
   --logdir /data/ouqin/runs/$RUN_ID/tensorboard \
   --host 127.0.0.1 --port 6006 \
   >/data/ouqin/runs/$RUN_ID/tensorboard_server.log 2>&1"

sleep 5
curl -I --max-time 5 http://127.0.0.1:6006/
```

如果 `tmux has-session` 已成功，不要重复执行 `new-session`。TensorFlow 未安装的提示不影响
PyTorch event 文件的标量曲线读取。

`last.pt` 每 50 step 更新一次，长期 `model_step_*.pt` 每 2000 step 保存一次；只有
world rank 0 写这些文件。

### 4.4 checkpoint 与 ONNX 策略导出

训练 checkpoint 与导出策略的存放规则：

- GPU14/world-rank 0 保存：`/data/ouqin/runs/RUN_ID/last.pt` 和
  `model_step_XXXXXX.pt`；GPU15 不重复保存 checkpoint。
- ONNX 不在训练中自动导出。选定 checkpoint 后在 GPU14 运行导出，结果写入
  `/data/ouqin/runs/RUN_ID/exported/`，包括 `*_g1.onnx` 和 `*_smpl.onnx`。

当前16张卡都在训练，不要同时启动导出抢占显存。训练完成或释放一张 GPU 后，从本地登录
GPU14 的 `ouqin` 账号：

```bash
ssh -i ~/.ssh/id_ed25519_sonic_bumi -p 22115 ouqin@117.161.121.54
```

然后在 GPU14 执行（示例导出30000 step，必须使用稳定的 `model_step_*.pt`，不要读取正在
覆盖写入的 `last.pt`）：

```bash
cd /data/ouqin/sonic_bumi_full
source .local/sonic_bumi_cluster.env
RUN_ID=sonic_bumi3_16gpu_4096_scratch_100k_20260911_150534
STEP=030000
CHECKPOINT=/data/ouqin/runs/$RUN_ID/model_step_$STEP.pt
test -f "$CHECKPOINT"

export OMNI_KIT_ACCEPT_EULA=YES
export TMPDIR=/data/ouqin/runs/.tmp/ouqin/export
mkdir -p "$TMPDIR"
CUDA_VISIBLE_DEVICES=0 "$REMOTE_PYTHON" gear_sonic/eval_agent_trl.py \
  checkpoint="$CHECKPOINT" \
  ++num_envs=1 ++headless=true ++export_onnx_only=true \
  ++manager_env.commands.motion.motion_lib_cfg.motion_file="$ROBOT_MOTION_DIR" \
  ++manager_env.commands.motion.motion_lib_cfg.smpl_motion_file="$SMPL_MOTION_DIR"

ls -lh /data/ouqin/runs/$RUN_ID/exported/model_step_${STEP}_{g1,smpl}.onnx
```

### 4.5 策略传回本地并部署

退出 GPU14，回到本地开发机，执行以下命令自动下载并分别保存 Robot/SMPL 策略：

```bash
cd /home/yingchaomu/下载/sonic_bumi_full
bash tools_local/fetch_bumi_onnx.sh RUN_ID STEP
```

例如：

```bash
bash tools_local/fetch_bumi_onnx.sh \
  sonic_bumi3_16gpu_4096_scratch_100k_20260911_150534 30000
```

下载后直接按第2节执行本地部署。对应关系固定为：

```text
服务器 exported/model_step_030000_g1.onnx
  -> 本地 models/deployment/robot/model_step_030000.onnx

服务器 exported/model_step_030000_smpl.onnx
  -> 本地 models/deployment/smpl/model_step_030000.onnx
```

checkpoint/ONNX 是大体积、可再生的实验产物，不进入普通 Git 历史；服务器 run 目录是训练
原件，本地 `models/deployment/{robot,smpl}` 是部署副本。重要里程碑应另做带校验和的备份或
对象存储归档，而不能只保留一份；“不提交 Git”不等于“不备份”。

## 5. 启动门槛

正式训练前必须同时满足：两台 commit 完全一致且 tracked worktree 干净；Python、PyTorch、
CUDA、Isaac Sim、Isaac Lab 和 `gear_sonic` 版本一致；Robot/SMPL 文件集合和内容哈希一致；
动作是一一配对的 50 FPS 当前训练集；单机 BUMI 环境 smoke 通过；跨机 NCCL all-reduce
通过。任一项不满足时，不用正式 16 卡任务来“试错”。

PICO 遥操是 SMPL encoder 的实时输入生产端，不是当前离线 sim2sim 的第三种 policy。
验收顺序应是：离线 Robot → 离线 SMPL（同名配对初始化）→ SMPL/PICO 5 点实时流 →
真机低风险分级测试。

### 5.1 BUMI3 SMPL/PICO 实时 sim-to-sim

当前 BUMI3 Python 部署端已新增真正的实时链路，不复用 G1 C++ planner：

```text
PICO 五点 -> SMPL -> ZMQ pose[10帧] -> 780维 SMPL token
                                   + 690维 BUMI3 proprioception
                                   -> 1470维 SMPL ONNX -> 21维动作 -> MuJoCo PD
```

PICO 端必须以 `--target_fps 50 --num_frames_to_send 10` 运行。实时不可能提前获得未来
9 帧，因此部署端把十帧窗口的最早帧作为当前参考，明确引入约 180 ms 延迟，
不重复当前帧伪造 future reference。带窗口的 BUMI3 接收端使用：

当前 `unitoken_all_noz` tokenizer 按训练契约不编码全局平移和 root z。PICO 端仅把
人体整体向下移动不会命令机器人跪地，必须由五点解算产生真实髋膝局部姿态；但配对
离线 SMPL kneeling 也失败，因此不应通过破坏 no-z 输入契约来掩盖问题。

首次安装发布端环境并验证 XRoboToolkit：

```bash
cd /home/yingchaomu/下载/sonic_bumi_full
SKIP_SIM_AND_UNITREE=1 bash install_scripts/install_pico.sh
source .venv_teleop/bin/activate
python -c "import xrobotoolkit_sdk; print('XRT_IMPORT_OK')"
```

安装器强制使用带 `Python.h` 的 uv-managed Python 3.10，并把 pybind11 的真实 CMake
目录传给 XRoboToolkit 构建系统。不要用系统 `/usr/bin/python3.10` 重建这个环境。

```bash
tools_local/run_bumi3_pico_sim2sim_nvidia.sh \
  --policy models/deployment/smpl/model_step_086000.onnx \
  --zmq-url tcp://127.0.0.1:5556 \
  --startup-timeout 300 \
  --stream-timeout 0.5
```

必须等发布端出现 5556 已绑定且持续产生 pose 后再启动接收端。接收端的
`no PICO pose received` 是发布端未出数据的下游症状。完整的两终端命令、安全切入方式、
故障判断和验收顺序见 `deploy.md` 第 5 节。

## 6. 2026-09-11 首次建群记录

- 两台节点均为 8 × RTX 4090，Isaac Lab 固定提交
  `37ddf626`（2.3.2）。
- 环境固定为 Python 3.11、PyTorch 2.7.0+cu128、Isaac Sim 5.1.0.0、
  Isaac Lab 0.54.2、Accelerate 1.14.0；两端导入路径已确认指向 `/data/ouqin`。
- 当前候选训练副本为 97,660 对同名 Robot/SMPL；SMPL 源软链接已解引用。两端
  195,320 个 PKL 的 SHA-256 manifest 摘要一致。该一致性只证明复制无误，正式启动前
  仍需由当前 MotionLib 做坐标契约检查。独立全量字段审计已通过：所有配对均为 50 FPS、
  帧数一致、字段形状正确、无 NaN/Inf，合计 33,655,845 帧，单条 30～9007 帧。
- 互联为 `bond4`，RDMA HCA 为 `mlx5_bond_0:1`。首次自动选择网络的 16-rank NCCL
  all-reduce 已通过；64 MiB、20 次测试的慢端用时 0.254643 秒，测试口径吞吐
  4.909 GiB/s。显式固定 HCA 后再次通过，慢端 0.253931 秒、4.923 GiB/s，正式配置
  使用 `NCCL_SOCKET_IFNAME==bond4` 与 `NCCL_IB_HCA==mlx5_bond_0:1`。
- 不把历史 checkpoint 放入新 run；正式命令保持 `resume=false`、`checkpoint=null`、
  `auto_load_latest=false`。
- 2026-09-11，项目所有者明确接受 NVIDIA Omniverse EULA，并授权两台训练节点设置
  `OMNI_KIT_ACCEPT_EULA=YES`；运维脚本在未明确设置为 `YES` 时拒绝启动 Isaac 训练。
- Isaac Kit 启动锁按 Unix UID 隔离，避免共享服务器上其他用户遗留的全局 `/tmp` 锁
  阻止当前用户启动；同一节点的8个本地rank仍共用同一把锁并保持串行启动。
- Isaac Lab 日志临时目录和 BUMI URDF 生成的 USD 缓存分别按用户、节点/rank 隔离，避免
  共享服务器旧账号目录权限以及多 rank 并发转换冲突。GPU15 缺少的 `libGLU.so.1` 放在
  `/data/ouqin/lib` 并通过私有集群配置加入运行库路径，不修改系统目录。
- 单卡 16 env/2 iteration smoke 已通过；双机 16 GPU、64 env/GPU、5 iteration smoke
  已通过，共 122,880 timestep。正式任务
  `sonic_bumi3_16gpu_4096_scratch_100k_20260911_150534` 已从零启动：16 GPU、4096
  env/GPU、全局 65,536 env、24 rollout step。实测 GPU14 的 ranks 0～7 和 GPU15 的
  ranks 8～15 均显示 `WORLD_SIZE=16`；iteration 2560 时两端各8个训练进程、16张卡均有
  约15 GiB显存占用和动态计算负载，无 OOM、NCCL 或非有限指标错误。GPU15 非零 rank
  不输出重复训练表格，因此其 `node1.log` 停在 motion 加载信息属于预期行为。
- 当前正式任务由 `setsid` 启动，Accelerate 主进程的父进程和 session 已脱离 SSH，因此
  本地终端关闭或公网 SSH 断开不会停止训练。后续新任务由运维脚本创建独立 `tmux` session；
  `status` 会同时显示 session 和训练进程。两节点内部训练网络若中断，NCCL 作业仍会失败，
  需要从最近 checkpoint 重新启动，tmux 不能恢复同一次 collective。

不启动 Isaac Sim 的全量配对字段审计：

```bash
/data/ouqin/envs/sonic_bumi/bin/python tools_local/audit_bumi_dataset.py \
  --robot-dir /data/ouqin/datasets/bumi3/train/robot \
  --smpl-dir /data/ouqin/datasets/bumi3/train/smpl \
  --expected-pairs 97660 --workers 16 \
  --report /data/ouqin/datasets/bumi3/audit.json
```
