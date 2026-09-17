# BUMI3 原生 SONIC 修改记录

本文档记录 BUMI3 原生 SONIC 支持的实际修改、机器人参数来源、兼容性边界和验证证据。所有结论区分静态检查、Isaac Sim 配置导入、环境 reset/step 与真实训练；未执行的测试不会表述为已通过。

## 2026-08-28：修复五集合根坐标契约、足底验证和脚部训练闭环

### 1. 修改目标、分支与工作区保护

- 所属分支：`feature/bumi-native-sonic-full-training`；起始 HEAD：
  `b1c3606ce96f00a01745cb8382f8bfa0b9b4d780`，与同名 origin 分支 ahead `0`、behind
  `0`。本轮没有执行 commit、push、pull、merge、rebase、stash、reset 或分支切换。
- 修改前工作区已有 sim2sim 代码、配置、测试、文档、`gear_sonic/pyproject.toml`、
  `agent.md` 和本记录文件等未提交工作；这些内容全部视为用户受保护修改。本轮没有覆盖、
  回退或暂存它们，`agent.md` 未由本轮修改。
- 目标是修复已停止训练所使用的 `hq_all_v1` 数据中公开四库根姿态坐标错误，补足会让
  横躺/穿地动作静默通过的验证，并让“5point”奖励实际包含双脚；不启动服务器训练，
  不原地覆盖旧数据，不改 SONIC 网络、PPO、控制频率或其他奖励数值。

### 2. 故障证据与坐标契约结论

- 对服务器现有 3,162 条公开动作和 99 条 Mine 动作进行了只读全帧根倾角审计。旧输出中：
  - AIOZ-GDANCE 1,978 条：中位根倾角 `87.693°`，`>45°` 帧占 `99.789%`；
  - AIST++ 963 条：中位 `79.847°`，`>45°` 占 `96.339%`；
  - CoMPAS3D 72 条：中位 `89.742°`，`>45°` 占 `99.885%`；
  - FineDance 149 条：中位 `88.348°`，`>45°` 占 `99.088%`；
  - Mine 99 条：中位 `5.503°`，`>45°` 仅 `0.058%`。
- 每个源文件本身已携带可区分的契约，不能通过倾角猜测来源：公开四库为
  `genmo.bumi_legacy_motion.v1`，Mine 为 `genmo.bumi_csv_qpos_xyzw.v1`。原转换器读取根
  `wxyz` 四元数后直接写出，没有处理公开库的 legacy Y-up 根姿态。
- 已验证的公开库修正是世界系左乘 `Rx(+90°)`：
  `q_zup = [sqrt(0.5), sqrt(0.5), 0, 0] ⊗ q_legacy`。全量只读统计应用该修正后，五集合
  中位倾角依次为 AIOZ `8.441°`、AIST `15.477°`、CoMPAS `9.444°`、FineDance
  `10.187°`，Mine identity 后仍为 `5.503°`；公开库 `>45°` 比例降为 `0.586%`、
  `8.770%`、`0.646%`、`2.600%`。AIST 中仍有真实大倾角动作，因此验证采用数据集聚合
  阈值，不粗暴删除任意单帧 `>45°` 的动作。
- 只修四元数还不够：公开库 Root-Z 是修正前足底 QP 的结果；Mine 虽然姿态正确，但源
  元数据明确采用 `legacy_body_origin_min_zero`。抽样 Mine 在当前 BUMI3 MJCF 下足底最低
  到 `-0.051115 m`。因此 Mine 四元数保持 identity，但所有集合的 Root-Z 都必须在当前
  SONIC BUMI3 MJCF 下重新对地，不能为让旧数据通过而放宽穿地检查。

### 3. 修改文件与具体内容

- `gear_sonic/tools/prepare_bumi3_sonic_dataset.py`：
  - 将输出 provenance 升级为 `sonic.bumi3_hq_all.v2`，要求每个源文件存在
    `source_motion_contract_version`；公开库只接受 legacy 契约并做固定 `Rx(+90°)`，Mine
    只接受 CSV Z-up 契约并做 identity，契约和数据集不匹配时直接失败，不使用启发式猜测；
  - 同时更新 `root_rot` 和 `pose_aa[:, 0]`，写出最终 root frame、修正四元数、Root-Z
    policy 和优化诊断，验证二者的四元数 round trip 一致；
  - 用当前 `bumi3.xml` 的关节名称和 `jnt_qposadr` 执行 MuJoCo FK，使用
    `mj_geomDistance(ground, foot_geom)` 计算实际几何足底距离，不用 body origin 或虚构
    包围盒点替代脚底；
  - 以足底接触软目标、修正的一/二阶平滑项和每帧硬下界重新求 Root-Z；二阶项只作用于
    新增修正，不抹平源动作本身的起跳/落地加速度；最终每帧足底穿透最多 `0.002 m`；
  - 全量 `validate` 新增 source/root 契约、四元数范数、根姿态与 axis-angle 一致性、每段
    17 帧 FK 抽检、完整序列穿地诊断，以及每数据集根倾角中位数 `<=30°`、`>45°` 比例
    `<=20%`；shape、有限值、FPS、配对、计数和 SHA256 原检查继续保留；
  - manifest/provenance 记录 root correction、Root-Z policy、倾角阈值和穿地容差；示例输出
    改为新目录 `hq_all_v2`，避免误覆盖或继续使用已知错误的 `hq_all_v1`。
- `gear_sonic/tools/test_prepare_bumi3_sonic_dataset.py`：从 4 项扩展到 6 项；Mine fixture
  显式声明 Z-up 契约并验证 identity/足底，新增公开 legacy `Rx(+90°)` + Root-Z 回归测试，
  新增“公开数据伪装成 Mine 契约必须失败”测试。
- `gear_sonic/config/exp/manager/universal_token/all_modes/sonic_bumi3.yaml`：
  - `reward_point_body` 从实际 3 点扩展为腰、双肘、双踝 5 点，双脚 offset 为零；继续调用
    原 `tracking_local_vr_5point_error`，其 weight `2.0`、std `0.1` 和实现均未修改；
  - `foot_pos_xyz` 从 BUMI3 覆盖值 `0.15 m` 恢复到 SONIC/G1 基础值 `0.20 m`，让训练早期
    能先通过五点奖励纠正脚部，再触发三维脚误差终止；
  - `ee_body_pos=0.12` 的自适应高度检查、`anchor_pos=0.12`、`anchor_ori_full=0.20`、
    `feet_acc=-2.5e-6`、力矩限制奖励、其他奖励和全部 domain randomization 保持不变。
- `gear_sonic/tools/validate_bumi3_integration.py`：锁定最终 5 个 reward body 和 `0.20 m`
  foot threshold；smoke 不再强制使用依赖可选 Nucleus USD 的 `plane`，改用正式 BUMI3
  配置的本地生成 `trimesh`。静态集成仍同时 compose `sonic_release` 和 `sonic_h2`。
- `BUMI3_SONIC_修改记录.md`：新增本节，记录故障证据、变更、实际测试、失败项、风险与
  回滚方法。

### 4. 真实源动作抽样结果

- 从服务器只读拉取 AIST、AIOZ、FineDance、CoMPAS 和 Mine 各一条源动作，在本地临时
  目录用最终代码转换并对全部帧做 MuJoCo 几何 FK：
  - AIST：倾角中位数 `78.001° -> 16.677°`，P95 `27.545°`，足底最低 `-0.002 m`；
  - AIOZ：`86.894° -> 6.864°`，P95 `15.304°`，足底最低 `-0.002 m`；
  - FineDance：`83.788° -> 9.018°`，P95 `27.169°`，`>45°` 为 `3.245%`，足底最低
    `-0.002 m`；
  - CoMPAS：`82.140° -> 12.992°`，P95 `21.124°`，足底最低 `-0.002 m`；
  - Mine：倾角保持 `5.963°`，P95 `12.765°`，足底从已知最低 `-0.051115 m` 修正到
    `-0.002 m`，没有对 Mine 应用公开库姿态旋转。
- 五条动作的额外动态 Root-Z 最大修正分别为 `0.045675`、`0.071957`、`0.104962`、
  `0.072836`、`0.033079 m`；最大修正加速度分别为 `4.476`、`3.538`、`6.267`、
  `5.514`、`1.962 m/s²`。这些值被写入每段输出诊断，便于全量构建后审计离群段。
- 远端源文件没有被修改；本地临时源副本、单段转换产物和临时日志验证后均已逐文件删除，
  未进入 Git。

### 5. 实际运行的验证与结果

- `/home/weili/miniconda3/envs/env_isaaclab/bin/python -m pytest -q
  gear_sonic/tools/test_prepare_bumi3_sonic_dataset.py`：`6 passed`。
- `/home/weili/miniconda3/envs/env_isaaclab/bin/python -m pytest -q
  gear_sonic/tools/test_prepare_bumi3_sonic_dataset.py gear_sonic/tests/test_bumi3_sim2sim.py`：
  `11 passed`；只有既有 `<unknown>:4 invalid escape sequence` DeprecationWarning。
- `/home/weili/miniconda3/envs/env_isaaclab/bin/python
  gear_sonic/tools/validate_bumi3_integration.py`：通过；实际解析 `21 DoF/22 bodies`，
  `sim_dt=0.005`、`decimation=4`、control/target `50 Hz`、action `21`、FSQ token `64`、
  actor proprioception `690`、tokenizer flat `1262`、critic `1245`、dynamic decoder
  `754 -> 21`，并通过 G1/H2 compose 与 mapping 检查。
- `/home/weili/miniconda3/envs/env_isaaclab/bin/python -m compileall -q gear_sonic`：通过。
- `git diff --check`：通过。
- 本地环境没有安装独立 Ruff，因此没有把行长人工检查描述为 Ruff 已通过；变更 Python
  文件按仓库 `115` 字符限制检查，无超长行。

### 6. 动态 smoke 失败项与未运行项

- 使用修正后的 FineDance `001` Robot/SMPL 单段数据运行 1-env、10-step smoke。第一次在
  scene 创建前失败，因为验证器原先强制 `plane`，本机 `ISAAC_NUCLEUS_DIR=None`，请求了
  `None/Isaac/Environments/Grid/default_environment.usd`；改用本地 `trimesh` 后该问题消失。
- 第二次到达 BUMI3 URDF 导入时失败：本地 Isaac Lab 的 `UrdfConverter` 调用
  `ImportConfig.set_merge_fixed_ignore_inertia`，但当前 Isaac Sim URDF importer 没有该 API；
  这是本机 Isaac Lab/Isaac Sim 版本不配套。环境未完成创建，因而本轮没有把 reset、step
  或 NaN/Inf smoke 写成通过；该兼容问题需在正式服务器 `liwei_lab` 环境复核/修复。
- 未在服务器构建完整 `hq_all_v2`、未运行 3,261/3,162 全量 `validate`、未运行 16-env
  replay、100 iteration smoke training 或八卡训练：本轮代码尚未获得 commit/push 授权，
  旧 `hq_all_v1` 又是本次确认的错误产物，不能拿它冒充修复后验证。服务器训练保持停止。

### 7. 兼容性、后续边界与回滚

- `sonic_release`、H2、G1/H2 mapping、Robot+SMPL 双编码器、FSQ、PPO、critic、trainer、
  `sim_dt`、decimation、history/future frame、SMPL 参数均未修改。只改变 BUMI3 活跃配置的
  五点名称集合和脚部三维终止阈值。
- 旧 `hq_all_v1/built` 不得继续用于训练或 ONNX 导出；修复代码默认示例将新产物放到
  `hq_all_v2`，构建器本身也拒绝覆盖已有 `robot_all/smpl_all`。全量构建通过后仍需先检查
  每集合倾角摘要、Root-Z 离群诊断和 Isaac reset/step，再允许重新训练。
- 回滚时只需撤销本节涉及的四个代码/配置/测试文件和本记录节；数据修正未写入服务器，
  没有远端产物需要删除。回滚到旧转换器只代表恢复代码，不代表旧 `hq_all_v1` 数据正确。

## 2026-08-28：服务器构建 hq_all_v2 并从零重启八卡训练

### 1. 授权、保护边界和服务器现状

- 用户明确要求“在服务器上重新开始训练”，因此本轮只向
  `noetix-volc` 的 `/home/liwei/GR00T-WholeBodyControl` 同步本次 BUMI3 修复相关文件、
  构建新数据并启动新实验；没有 commit、push、pull、merge、rebase、stash 或 reset。
- 本地和服务器分支均为 `feature/bumi-native-sonic-full-training`，HEAD 为
  `b1c3606ce96f00a01745cb8382f8bfa0b9b4d780`。服务器同步前是干净工作区；本地既有
  sim2sim、`agent.md`、`pyproject.toml` 等受保护未提交修改没有被同步、回退或覆盖。
- 服务器原代码备份为
  `/data/sonic_bumi3/code_snapshots/pre_hq_all_v2_20260828_131927`；旧 `hq_all_v1`、旧
  `hq_all_scratch_100k-20260827_170205` 训练目录及 16k checkpoint 均保留，但新训练不读取它们。
- 服务器 Conda 环境是 `/root/miniconda3/envs/liwei_lab`，PyTorch
  `2.7.0+cu126`、MuJoCo `3.3.2`、Isaac Sim `5.1.0`。启动前确认 8 张 RTX 4090 D
  均无训练进程、显存约 `2 MiB`。

### 2. 开训前追加修正

- `gear_sonic/data/assets/robot_description/urdf/bumi3/bumi.urdf`：复核发现当前提交仍是
  较大的旧腿部圆柱，与用户先前明确参数不一致；因此在正式训练前落实最终值：
  - 左右 `leg_roll_link`：origin `[0, 0, -0.02]`、radius `0.03`、length `0.08`；
  - 左右 `knee_pitch_link`：保留之前 origin `[0.008475, 0, -0.0894694]`，radius `0.025`、
    length `0.13`；
  - `base_link` 保持 length `0.12`，左右 `leg_pitch/yaw` 继续无 collision。
  URDF 已重新统一为 CRLF，避免因换行符造成全文件假 diff。
- `gear_sonic/tools/validate_bumi3_integration.py`：参考资产路径不再写死为
  `/home/weili`；先读 `BUMI3_REFERENCE_ROOT`，再按仓库同级、`/home/weili`、`/home/liwei`和
  `/home/listao` 候选路径查找，仍使用原 SHA256 锁定权威版本。服务器自有
  `legged_lab` 的 `bumi.py/MJCF` SHA 与本集成权威版不同，未修改该参考仓库；只把本机
  权威快照复制到 `/data/sonic_bumi3/reference_assets/bumi3` 供验证使用。
- `gear_sonic/tools/prepare_bumi3_sonic_dataset.py`：`_git_commit` 使用精确仓库路径的
  `git -c safe.directory=...` 读取 HEAD，修复 root 用户读取 `/home/liwei` 普通用户仓库时
  provenance 被记录为 `unknown` 的问题。该修正不改动作数值，只重写 metadata 和 SHA 清单。
- `BUMI3_SONIC_修改记录.md`：新增本节，记录服务器同步、新数据、smoke、正式训练与
  尚未证明的质量边界。

### 3. hq_all_v2 构建与独立全量验证

- 构建命令读取 `hq_all_v1/source_{bumi,smpl,mine}`，只向新目录
  `/data/sonic_bumi3/datasets/hq_all_v2` 写入，使用 32 workers；日志为
  `/data/sonic_bumi3/logs/prepare_hq_all_v2_20260828_132309.log`。完整转换、内置全量验证和
  原子发布均通过，随后再独立执行 `validate` 一次，输出
  `BUMI3_SONIC_DATASET_VALIDATE=PASS`。
- 最终数据为 3,261 条 robot、3,162 条 SMPL、99 条 Mine-only，数据集约 `3.7G`。
  provenance 为 `sonic.bumi3_hq_all.v2`，代码 HEAD 为 `b1c3606...`，公开库修正是
  `[0.70710678, 0.70710678, 0, 0]`，运行目标 50Hz，足底穿透容差 `0.002 m`。
- 全量修正后根倾角聚合结果：AIST++ `15.477° / 8.770%`、AIOZ-GDANCE
  `8.441° / 0.586%`、FineDance `10.187° / 2.600%`、CoMPAS3D `9.444° / 0.646%`、
  Mine `5.503° / 0.058%`；每组分别为中位倾角和 `>45°` 帧占比。
- 元数据 SHA256：
  - `meta/SHA256SUMS`：`2aa75a3ab0c95b999978be4fc29d56d261aee2cf3ad5a3cc39b3f6175c4bd427`；
  - `meta/manifest.jsonl`：`7c388ae40874d06d195afcf336f5dbc5b2a2de5a48a8e1b0d1f80290c83058da`；
  - `meta/provenance.json`：`bc8debdb3604164acfeaa8a801438008c86784a8dc3593e339da26b03cca66b6`。

### 4. 实际验证命令和结果

- 本机 `env_isaaclab`：`compileall -q gear_sonic`、数据工具 6 项 pytest 和完整
  `validate_bumi3_integration.py` 均通过；后者实际解析 21 DoF/22 bodies、映射、执行器、
  Robot+SMPL 网络和 Hydra 兼容配置。
- 服务器 `liwei_lab`：`compileall -q gear_sonic`、`pytest
  gear_sonic/tools/test_prepare_bumi3_sonic_dataset.py` 为 `6 passed`；不启动 Isaac 的资产/Hydra
  静态部分通过，resolved 为 `sim_dt=0.005`、`decimation=4`、50Hz、action 21、FSQ 64、
  actor proprioception 690、tokenizer 1262、critic 1245、decoder `754 -> 21`。
- 服务器直接执行验证器的裸 `SimulationApp` 时，会因 pip IsaacLab 的 source 路径和
  headless Vulkan 上下文报 `isaaclab.sim`/图形插件错误；未把这次失败写成通过。改用项目
  正式 `train_agent_trl.py` 入口自身的 `AppLauncher` 后，16 env、2 iterations 真实 smoke
  完成 768 timesteps，两次 PPO 更新均成功，无 Traceback、OOM、NCCL、NaN/Inf。
- smoke 配置是 `checkpoint:null`、`auto_load_latest:false`，数据路径为 `hq_all_v2`；
  日志为 `/data/sonic_bumi3/logs/smoke_hq_all_v2_20260828_134953.log`，产物目录为
  `/data/sonic_bumi3/smoke/TRL_BUMI3_Track/manager/universal_token/all_modes/
  sonic_bumi3_hq_all_v2_coordfix_smoke-20260828_134957`。smoke 权重没有作为正式训练初始化。

### 5. 八卡正式从零训练

- tmux：`bumi3_sonic_v2`；日志：
  `/data/sonic_bumi3/logs/train_hq_all_v2_20260828_135112.log`；实验目录：
  `/data/sonic_bumi3/runs/TRL_BUMI3_Track/manager/universal_token/all_modes/
  sonic_bumi3_hq_all_v2_coordfix_scratch_100k-20260828_135120`。
- resolved 配置明确为 8 processes、每 rank `num_envs=4096`、`100000` iterations、
  `checkpoint:null`、`auto_load_latest:false`、`resume:false`、`sim_dt=0.005`、`decimation=4`，
  robot/SMPL 都只读 `hq_all_v2/built`。旧 16k checkpoint 和 smoke 权重均未加载。
- 截至 `iteration 105`，进程仍在运行；每轮 786,432 timesteps，累计
  `82,575,360` timesteps，最近吞吐 `220,558 steps/s`、iteration `3.57s`，8 卡各占约
  `19.7–20.2 GiB`。日志无 Traceback、OOM、NCCL timeout/error、NaN/Inf，`last.pt`
  已保存，大小 `385,843,368` bytes。
- 当时 mean reward `0.46244`、mean length `9.5775` steps；主要 termination 分解为
  `ee_body_pos=0.6108`、`anchor_ori_full=0.2627`、`foot_pos_xyz=0.2028`、
  `anchor_pos=0.0067`。这只证明从零随机策略的训练通道正常；前 100 iterations 的
  mean length 仍在约 9–10 steps 波动，没有证明中后期策略质量已恢复。
- 根据当时 ETA `353,339 s`，动态估计剩余约 `98.1 h`（约 4.1 天）；该值会随
  采样/更新吞吐变化，不是完成承诺。应在 500/1000/5000 iterations 继续检查 mean length、
  termination 分解和固定动作回放，不能只看训练 reward 就判定物理质量或真机安全。
- 服务器仍会打印已知的 `VkResult: ERROR_INCOMPATIBLE_DRIVER`/图形插件告警；
  本次 headless smoke 和 8 卡正式训练均继续执行 PhysX/CUDA。这不等价于 GUI/相机/渲染
  已验证，以后若需可视化仍必须单独修复 Vulkan ICD/驱动环境。

### 6. 回滚与继续监控

- 停止新训练可向 `tmux` 会话 `bumi3_sonic_v2` 发送 `Ctrl-C`；不要删除新数据或
  旧实验来“回滚”代码。代码回滚目标是本节的 URDF、验证器路径解析和 provenance
  safe-directory 三处追加修正，覆盖前服务器文件可从上述 code snapshot 恢复。
- 本轮交付时既没有自动停止正式训练，也没有 commit/push 当前未提交工作区。

## 2026-08-28：新增 BUMI3 原生 SONIC MuJoCo sim2sim

### 1. 修改目标、分支与起始状态

- 所属分支：`feature/bumi-native-sonic-full-training`。
- 起始 HEAD：`b1c3606ce96f00a01745cb8382f8bfa0b9b4d780`。
- 修改前本分支相对 `origin/feature/bumi-native-sonic-full-training` 为 ahead `0`、behind
  `0`；没有执行 pull、commit、push、merge、rebase、stash 或分支切换。
- 修改前已有且受保护的用户工作区内容为 `BUMI3_SONIC_修改记录.md` 和 `agent.md`；本轮
  只在记录文档新增本节，没有撤销、覆盖或改写原有记录，`agent.md` 未由本轮修改。
- 目标是参考现有 G1 SONIC sim2sim 的动作参考、历史观测、ONNX 推理和 MuJoCo PD 闭环，
  增加可独立运行的 BUMI3 版本；不把 BUMI3 强行接入 G1 专用的 29 电机、Unitree DDS、
  C++ 硬件 order 和 robot model。

### 2. 配置与资产来源

- 权威参考仓库：`/home/weili/legged_lab`，分支 `main`，HEAD
  `d555c76e5977af66ef55a104b98e1be486349996`。
- 参考工作区当前有未提交修改，本轮只读、未修改；其中：
  - `assets/robots/bumi3/bumi.py` SHA256：
    `74aaeca9da615c50e3749e4f103bbf713b83443d9cb16fab08edfd320227c03e`；
  - `assets/robots/bumi3/mjcf/bumi3.xml` SHA256：
    `041c81e8176c7f375302796deca28b141891a3c097d8e341e8d967b735466edf`。
- 本仓库实际加载的 BUMI3 MJCF SHA256：
  `02874afebbe30ba1f90218394c8f9953f5d7a808e6b9950e7964c731da6dfbfe`。验证脚本会把
  本地 MJCF 与当前参考做完整 XML 语义比较，当前唯一允许的差异是仓库布局导致的
  `compiler.meshdir`：参考为 `../meshes/`，本地为 `../meshes/bumi3/`。
- PD、effort、velocity、armature、初始姿态和 action scale 来源于当前本仓库
  `gear_sonic/envs/manager_env/robots/bumi3.py`，该文件此前已按上述参考 `bumi.py`
  逐字段验证。本轮没有修改 BUMI3 URDF、MJCF、mesh 或训练配置。

### 3. 修改文件与具体目的

- `gear_sonic/config/sim2sim/bumi3_sonic.yaml`：新增集中、可审计的 BUMI3 sim2sim
  契约，记录 21 关节 MuJoCo/IsaacLab 顺序、初始姿态、PD、effort/velocity、踝关节
  armature、时间参数和网络维度。动作缩放不写死，运行时始终按
  `0.25 * effort_limit / stiffness` 计算。
- `gear_sonic/utils/mujoco_sim/bumi3_sim2sim.py`：新增核心实现：
  - 通过名称查询每个关节的 `jnt_qposadr`、`jnt_dofadr` 和 motor，不使用
    `qpos[7:]` 这类隐式顺序；
  - 支持 SONIC PKL、NPZ 和 G1 `MotionDataReader` 风格 CSV clip；PKL 自动采用
    MuJoCo DoF + `xyzw` root quaternion，CSV 自动采用策略 DoF + `wxyz`，也可由 CLI
    显式覆盖；只接受 50 FPS，不在部署端静默重采样；
  - 复刻 SONIC Robot Encoder 的 10 个 future frames、0.1 秒间隔和训练端
    `command_multi_future_nonflat` 的实际 flatten 布局；
  - 默认计算 `robot_start_heading * inverse(reference_start_heading)`，把参考动作起始 yaw
    对齐到机器人，与 G1 sim2sim 的 `ComputeApplyDeltaHeading` 行为一致，并支持 CLI 关闭；
  - 按训练 `PolicyCfg` 顺序构造 10 帧 `base_ang_vel / joint_pos_rel / joint_vel /
    last_action / gravity_dir`，proprioception 为 690 维；
  - 加载 `eval_agent_trl.py` 导出的 `*_g1.onnx` 联合 Robot Encoder + dynamic decoder，
    严格验证 `1170 -> 21`；这里 `g1` 仅为网络内部兼容键名；
  - 用 BUMI3 action scale、PD 和 effort clip 在 `0.005` 秒 MuJoCo step、decimation `4`
    下闭环执行，并逐步检查 observation/action/torque/qpos/qvel/ctrl 有限值。
- `gear_sonic/scripts/run_bumi3_sim2sim.py`：新增 Tyro CLI，支持 GUI/headless、实时/最快
  执行、动作选择、顺序覆盖、起始帧、时长、循环和 validate-only。
- `gear_sonic/tools/validate_bumi3_sim2sim.py`：新增一键验证；检查参考 MJCF、全部 mesh、
  `nq/nv/nu/body`、关节和 actuator 顺序、mapping round trip、action scale、armature、
  480/690/1170/21 维度以及 100 控制周期有限值；可选真实 ONNX 和动作输入。
- `gear_sonic/tests/test_bumi3_sim2sim.py`：新增 4 个回归测试，覆盖映射/维度/action scale、
  SONIC PKL 顺序、G1 风格 CSV 顺序和无界面 MuJoCo 闭环。
- `docs/source/getting_started/bumi3_sim2sim.md`：新增环境安装、checkpoint 导出、GUI/
  headless 运行、动作格式、验证命令和能力边界说明。
- `gear_sonic/pyproject.toml`：在既有 `sim` extra 中加入 `onnxruntime`，使新的推理入口按
  文档安装后具备完整依赖；不修改 training/teleop/inference extra。
- `BUMI3_SONIC_修改记录.md`：新增本次来源、实现、测试、风险和回滚记录。

### 4. 最终顺序、映射与 resolved 契约

BUMI3 MuJoCo 顺序：

`[waist_yaw, l_arm_pitch, l_arm_roll, l_arm_yaw, l_elbow_pitch, r_arm_pitch,
r_arm_roll, r_arm_yaw, r_elbow_pitch, l_leg_pitch, l_leg_roll, l_leg_yaw,
l_knee_pitch, l_ankle_pitch, l_ankle_roll, r_leg_pitch, r_leg_roll, r_leg_yaw,
r_knee_pitch, r_ankle_pitch, r_ankle_roll]`，完整名称均带 `_joint`。

策略/IsaacLab 顺序：

`[l_leg_pitch, r_leg_pitch, waist_yaw, l_leg_roll, r_leg_roll, l_arm_pitch,
r_arm_pitch, l_leg_yaw, r_leg_yaw, l_arm_roll, r_arm_roll, l_knee_pitch,
r_knee_pitch, l_arm_yaw, r_arm_yaw, l_ankle_pitch, r_ankle_pitch,
l_elbow_pitch, r_elbow_pitch, l_ankle_roll, r_ankle_roll]`，完整名称均带 `_joint`。

- IsaacLab → MuJoCo：
  `[2,5,9,13,17,6,10,14,18,0,3,7,11,15,19,1,4,8,12,16,20]`。
- MuJoCo → IsaacLab：
  `[9,15,0,10,16,1,5,11,17,2,6,12,18,3,7,13,19,4,8,14,20]`。
- 实际 MJCF：`nq=28`、`nv=27`、`nu=21`、robot bodies `22`（MuJoCo `nbody=23`
  还包含 world body）、mesh `22`。
- `sim_dt=0.005`、`decimation=4`、control frequency `50 Hz`、target FPS `50`、history
  `10`、future frames `10`、future stride `5`（0.1 秒）。
- Robot tokenizer `480`、actor proprioception `690`、联合 ONNX input `1170`、FSQ token
  `64`、action/output `21`。

### 5. 实际运行的验证与结果

- `/home/weili/miniconda3/envs/env_isaaclab/bin/python -m compileall -q gear_sonic`：通过。
- `/home/weili/miniconda3/envs/env_isaaclab/bin/python -m pytest -q
  gear_sonic/tests/test_bumi3_sim2sim.py`：`5 passed`，其中新增 90 度参考 yaw 对齐回归测试。
- `.venv_sim/bin/python -m compileall -q gear_sonic`、`.venv_sim/bin/python -m pytest -q
  gear_sonic/tests/test_bumi3_sim2sim.py` 和 CLI `--help`：通过；证明独立 Python 3.10
  MuJoCo 环境可编译、可运行全部 5 个测试并正确生成命令帮助。
- `/home/weili/miniconda3/envs/env_isaaclab/bin/python
  gear_sonic/tools/validate_bumi3_sim2sim.py --steps 100`：通过；实际执行 100 个 50 Hz
  control steps / 400 个 MuJoCo steps，仿真时间 `2.0 s`，全链路无 NaN/Inf。
- 使用 ONNX helper 临时生成严格 `1170 -> 21` 的零输出 ONNX，并生成带显式
  `joint_order=mujoco`、`quaternion_convention=wxyz` 的 50 FPS BUMI3 NPZ：
  - `.venv_sim/bin/python gear_sonic/tools/validate_bumi3_sim2sim.py --policy
    /tmp/bumi3-sim2sim-ucYE2d/mock_g1.onnx --motion
    /tmp/bumi3-sim2sim-ucYE2d/motion.npz --steps 100`：通过，验证了真实 ONNX Runtime
    session、真实文件加载和 100 周期闭环；
  - `.venv_sim/bin/python gear_sonic/scripts/run_bumi3_sim2sim.py ... --duration 0.1
    --headless --no-real-time`：通过，实际运行 5 个控制周期，仿真时间 `0.1 s`。
  - 上述 `/tmp` 文件仅为接口测试产物，不是训练数据或可交付 checkpoint；验证后已逐文件
    删除并移除空临时目录，未加入 Git，也没有保留生成数据。
- `/home/weili/miniconda3/envs/env_isaaclab/bin/python
  gear_sonic/tools/validate_bumi3_integration.py`：通过；重新确认 `sonic_bumi3` 与现有 G1/H2
  Hydra compose、执行器、mapping、时间参数和网络维度兼容检查未回归。
- `git diff --check`：通过。
- 使用独立临时 index 显式加入全部已跟踪修改和 6 个未跟踪新增文件后运行
  `git diff --cached --check`：通过；首次完整统计为 `9 files changed, 1962 insertions,
  2 deletions`。真实 Git index 在审计前后均为空，未替用户暂存任何文件。
- 为运行独立 sim 环境验证，在未跟踪的 `.venv_sim` 中安装了 `onnxruntime==1.23.2` 和
  `pytest==9.1.1`；项目依赖声明只新增 `onnxruntime`，pytest 仅为本地测试工具。

### 6. 未通过/未运行项与原因

- 合并运行新增测试和现有 `gear_sonic/tests/test_input_readers.py` 时，现有测试在 collection
  阶段失败：它从当前 `gear_sonic.utils.teleop.input_readers` 导入
  `build_body_pose_sample`，但该函数当前不存在。该失败发生在任何 BUMI3 测试执行前，属于
  现有 Teleop 测试/实现漂移；本轮不修改无关 Teleop 通用代码。单独运行全部 4 个新增测试
  已通过。
- 未使用 `model_step_016000.pt` 导出并回放真实 BUMI3 policy：本机 checkpoint 的 resolved
  config 指向 `/data/sonic_bumi3/datasets/hq_all_v1/built/robot_all` 和 `smpl_all`，这些训练数据
  本机不存在；本轮不擅自从其他 BUMI3/G1 数据替代，也不生成训练数据。因而本轮 ONNX
  Runtime 证据是接口级临时 ONNX，不是训练效果验证。
- 未运行 GUI viewer：本轮自动验证使用 headless，CLI 的 viewer 分支已完成导入与参数路径
  检查，但没有把无界面 smoke 描述为 GUI 验证。
- 未做实机测试：该入口明确不包含 DDS/CAN/硬件安全映射，只用于 MuJoCo sim2sim。

### 7. 兼容性、已知风险与回滚

- 未修改 `gear_sonic/scripts/run_sim_loop.py`、`gear_sonic_deploy` 或 G1/H2 配置；现有 G1
  C++/DDS sim2sim 行为保持不变。BUMI3 使用新入口，避免 21 DoF 被错误塞入 29 DoF 映射。
- 本地 BUMI3 MJCF 保持当前 `legged_lab` 数值，只调整了既有 meshdir；训练使用的 URDF
  有用户指定的简化碰撞，而 MuJoCo MJCF 当前仍是 mesh geometry。该差异是 sim2sim 的一个
  明确物理域差异，对爬行/跪地效果的影响必须用真实动作和真实 checkpoint 继续评估。
- 100 周期零策略 smoke 中机器人最终跌倒但数值保持有限；这是零策略不产生平衡动作的预期
  结果，不能当作 policy 稳定性结论。
- 回滚时删除本轮 5 个新增代码/配置/测试文件及 1 个新增文档，移除 `pyproject.toml` 中
  `sim` extra 的 `onnxruntime` 一行，并删除本记录节即可；BUMI3/G1/H2 既有资产和训练代码
  均不需要回滚。本轮未 commit/push，Git 历史和远端没有变化。

### 8. 统一改用 Conda `env_isaaclab`

- 用户明确要求不使用 `.venv_sim`，后续 BUMI3 训练、ONNX 导出和 sim2sim 统一使用
  `/home/weili/miniconda3/envs/env_isaaclab`。sim2sim 实现本身从未绑定 `.venv_sim`；此前该
  环境只用于隔离测试。
- 检查时 `env_isaaclab` 已有 Python `3.11.15`、MuJoCo `3.3.2`、ONNX Runtime
  `1.27.0`、NumPy `1.26.4`、PyYAML `6.0.2` 和 joblib `1.5.3`，唯一缺少 CLI 依赖
  Tyro。
- 第一次直接安装最新版 `tyro==1.0.16` 时，它把 `typing_extensions` 从 Isaac Sim 5.1
  要求的 `4.12.2` 升级到 `4.16.0`。发现冲突后立即卸载该 Tyro 和其新增的 typeguard，
  恢复 `typing_extensions==4.12.2`，并安装与其兼容的 `tyro==0.8.14`；没有把环境留在
  已知冲突状态。
- `gear_sonic/pyproject.toml` 的 `sim` extra 同步将 Tyro 固定为 `0.8.14`，避免以后按
  extra 安装时再次升级 Isaac Sim 的 typing-extensions。文档的全部训练、导出、运行和
  验证命令也统一改为先 `conda activate env_isaaclab`。
- 在最终 Conda 环境中实际运行：
  - CLI `--help`：通过；
  - `python -m compileall -q gear_sonic`：通过；
  - `python -m pytest -q gear_sonic/tests/test_bumi3_sim2sim.py`：`5 passed`；
  - `python gear_sonic/tools/validate_bumi3_sim2sim.py --steps 100`：通过，400 个 MuJoCo
    steps 无 NaN/Inf；
  - `python gear_sonic/tools/validate_bumi3_integration.py`：在恢复 Isaac Sim 依赖版本后再次
    通过，确认 BUMI3/G1/H2 Hydra、执行器、mapping 和网络维度检查未受 Tyro 安装影响；
  - 使用临时 `1170 -> 21` ONNX 和 50 FPS NPZ 运行正式 CLI 5 个控制周期：通过，仿真
    时间 `0.1 s`；临时 ONNX/NPZ 随后已删除。
- `pip check` 仍报告两个本轮之前就存在的环境问题：IsaacSim kernel 声明
  `numpy==1.26.0` 而环境为 `1.26.4`，FastAPI 要求 `starlette<0.46.0` 而环境为
  `0.49.1`。本轮没有改动 NumPy、FastAPI 或 Starlette；当前 Isaac Lab 集成验证和
  BUMI3 sim2sim 均能运行，但这两个历史依赖漂移不能被描述为整个 Conda 环境完全无冲突。

## 2026-08-27：建立 Git 分支模型与 Agent 安全操作规范

### 修改目标与所属分支

- 所属分支：`feature/bumi-native-sonic-full-training`。
- 起始 HEAD：`b1c3606ce96f00a01745cb8382f8bfa0b9b4d780`。
- 用户要求为 SONIC 和 GENMO 统一建立 `feature/*`、`release/*`、`main` 的职责边界，
  并特别确认用户已有未提交修改均视为正确修改，Agent 不得擅自丢弃。

### 修改文件与具体内容

- `agent.md`：保留原有 BUMI3 来源、兼容性和强制记录规则，新增以下仓库级约束：
  - `main` 保持可运行、已验证、可交付；功能开发进入 `feature/*`，发布准备进入
    `release/*`，线上紧急修复进入 `hotfix/*`。
  - 规定分支来源、命名、允许修改范围、release 修复回流和语义版本 Tag 生命周期。
  - 将用户已有未提交修改定义为正确且受保护的内容，禁止 reset、clean、stash、覆盖、
    回退或混入无关提交。
  - commit、push、merge、rebase、Tag 和删分支等共享历史操作必须获得用户明确授权。
  - 强制修改前审计分支、HEAD、工作区和远端差异；逐文件暂存并区分代码、配置、资产、
    模型及生成数据。
  - 细化修改记录字段、验证等级、合并审计、发布说明和 GitHub 分支保护要求。
- `BUMI3_SONIC_修改记录.md`：新增本节，记录规则修改的来源、范围、理由和验证边界。

### 修改理由与兼容性边界

- 本仓库后续主要由 Agent 执行修改，仅定义分支用途不能防止覆盖用户工作区、误提交数据、
  未经批准改写历史或夸大验证结果，因此将工作区保护、权限边界、提交审计和发布证据纳入
  同一套规则。
- 本次只修改 Agent 工作规范和记录文档，不修改 SONIC/BUMI3/G1/H2 的代码、配置、机器人
  资产、训练数据、Checkpoint、网络结构或运行行为。
- 回滚时只需撤销本节和 `agent.md` 对应规则文本；不会影响任何模型或训练产物。

### 实际验证结果

- 修改前确认当前分支为 `feature/bumi-native-sonic-full-training`、起始工作区干净且已跟踪
  同名 origin 分支。
- `git diff --check`：通过。
- 未运行 Python、Isaac Sim、动作 replay 或训练测试：本次没有修改任何代码、配置或资产，
  这些运行级验证与文档规则修改无直接关系，因此不将文档检查描述为功能验证。

## 2026-08-27：接入五集合 Robot+SMPL 高质量训练数据

### 修改文件与内容

- 新增 `gear_sonic/tools/prepare_bumi3_sonic_dataset.py`：读取四个配对数据集和
  Mine-only 数据集；依照源 `joint_names` 将 BUMI3 qpos 重排到当前 SONIC MJCF，
  输出 30Hz robot motion-lib PKL；将 SMPL `pose_aa/transl/smpl_joints` 同步转换到
  50Hz；执行 3261/3162/99 计数、全量维度、有限值、配对、四元数和 SHA256 校验。
- 新增 `gear_sonic/tools/test_prepare_bumi3_sonic_dataset.py`：覆盖 MJCF 顺序解析、
  名称重排、axis-angle 生成以及与 SONIC 相同的 30Hz→50Hz 末帧排除时间网格。
- `validate` 读取包含输出路径和运行时帧数的扩展 manifest 时，只提取
  `SampleRecord` 契约字段，避免元数据扩展字段被误传给数据类构造函数。
- robot/SMPL 单文件先写入带 PID 的隐藏临时文件，joblib 完成后再原子替换为目标
  文件名；中断恢复不会把半文件误判为已完成。
- 锁定源 BUMI 文件实际携带的 MJCF SHA256
  `482138b437dbdabd6171fa8d44b55db5d7125a228c95b69ce3d1159cafe8537c`，并将其与
  当前 SONIC BUMI3 MJCF 指纹分别写入 provenance。两者不相同，因此只允许通过
  每段文件的 21 个 `joint_names` 做名称集合验证和显式重排，禁止按源列位置直拷。
- 实施前复核发现 `bumi.urdf` 的修改时间晚于验证脚本，工作区已经存在一组未记录
  的后续碰撞参数。为保留用户现有修改，本轮不改 URDF，只同步更新
  `validate_bumi3_integration.py` 的锁定值：左右 leg-roll 为 origin Z `-0.08`、
  radius `0.045`、length `0.1`；左右 knee 为 origin Z `-0.0694694`、radius
  `0.046`、length `0.15`。base 圆柱和四个无碰撞 link 保持不变。

### 修改理由与兼容性

- 机器人源文件保留 30Hz，由 motion-lib 在 FK 加载时统一转换到目标 50Hz；SMPL
  当前加载器只会重采样 pose，不能同步处理 joints/transl，因此三项必须离线共同
  转成 50Hz，且目标帧数必须与机器人运行时帧数完全一致。
- 机器人源数据采用另一份 MJCF 生成，不能按列位置假设关节顺序；转换器只信任
  每个文件的 `joint_names`，并要求其名称集合与当前 BUMI3 MJCF 精确相等。
- 工具仅新增离线数据入口，不修改 G1/H2 数据、训练网络、奖励、termination、
  domain randomization 或 checkpoint 行为。
- 碰撞验证器调整只是追踪当前较新的 URDF 工作区状态，不把碰撞参数回退为日志中
  较早的缩小版本；对应资产仍需通过实际 Isaac 导入和训练 smoke。

### 实际验证结果

- `/home/weili/miniconda3/envs/env_isaaclab/bin/python -m compileall -q gear_sonic`：通过。
- `gear_sonic/tools/validate_bumi3_integration.py`：通过；当前较新的 URDF 碰撞值、
  21 DoF/22 bodies、双编码器维度、50Hz 控制契约和 BUMI3 映射均通过静态及
  Isaac 配置导入检查；本次未请求该脚本的动作 smoke。
- `python -m pytest -q gear_sonic/tools/test_prepare_bumi3_sonic_dataset.py`：4 项通过；
  覆盖当前 MJCF、名称重排、轴角生成和目标帧时间网格。
- `git diff --check`：通过。
- 本地 Isaac Lab 环境未安装独立 `ruff` 可执行文件，因此没有把 Ruff 描述为已运行；
  将在 noetix 的正式训练环境再次检查可用性。
- noetix 全量数据转换及 SONIC 单卡/八卡训练 smoke 已于本节后续“服务器落盘与
  正式规模训练可行性验证”中完成并记录。正式 100k 训练未启动。

## 2026-08-27：服务器落盘与正式规模训练可行性验证

### 1. noetix 2TiB 数据盘

- 操作前再次确认 `/dev/vdb` 为精确的 2TiB 空盘，无分区、文件系统、挂载点、
  残留签名、占用进程或 `/etc/fstab` 条目；系统盘是 `/dev/vda2`，未对其执行
  分区或格式化操作。
- 为 `/dev/vdb` 创建 GPT 和单个 ext4 分区 `/dev/vdb1`，卷标为 `SONIC_DATA`，
  reserved blocks 为 0；实际 UUID 为
  `68f60019-f39c-44d1-8e14-320d25755dd6`。
- `/etc/fstab` 使用 `defaults,noatime,nofail 0 2` 挂载到 `/data`；`findmnt`、
  `findmnt --verify`、`df -hT` 和写入/删除测试均通过。原 fstab 备份为
  `/etc/fstab.codex-before-sonic-data`。
- 数据固定放在 `/data/sonic_bumi3/datasets/hq_all_v1`，训练和 smoke 分别放在
  `/data/sonic_bumi3/runs`、`/data/sonic_bumi3/smoke`，日志放在
  `/data/sonic_bumi3/logs`。全部数据和 smoke 验证结束时数据盘使用约 6.2GiB，
  仍有约 2.0TiB 可用；其中 datasets 约 5.5GiB、smoke 约 737MiB。

### 2. 服务器间直传和源数据校验

- SMPL 服务器直接向 noetix 推送 2,202 个 motion/curation 文件，共
  `1,503,420,296` bytes；BUMI 服务器直接推送四个配对集合 3,174 个文件，共
  `418,741,956` bytes，以及 Mine 集合 103 个文件，共 `17,722,804` bytes。
- 数据没有经过本地机器，也没有传 WAV 或 35 维音乐特征。传输使用临时受限
  SSH 公钥和可续传 rsync；完成后源端私钥和 noetix 临时授权条目均已删除，
  密码未写入仓库、脚本或日志。
- 源端/目标端逐文件排序 SHA256 清单的聚合指纹完全一致：SMPL 为
  `e934012a7c4b81adaa69d821df147fe2024ca3eda320549a32acefcdfa9bd23d`，
  四个 BUMI 配对集合为
  `46f04748306a8b9e473525394c13ceda10972bb4555d560a2ca509be49a4e25c`，
  Mine 为 `7cebe8f2404e271900760cac18dbb8bfaef90aa1bb2ca938c61cef52b78ff123`。
- 目标端逐文件清单保存在 `meta/source_smpl_files.sha256`、
  `meta/source_bumi_files.sha256` 和 `meta/source_mine_files.sha256`。

### 3. 代码、LFS 与转换产物

- noetix 仓库固定在提交 `b3cd0699a04ac31aef0a1f2ce76b8e06082ae30f`；分支为
  `feature/bumi-native-sonic-full-training`，拉取后工作区干净。
- BUMI3 的 22 个 STL 和 `human/human_joints_info.pkl` 共 23 个 LFS 文件均不再是
  指针，并逐文件通过“实体 SHA256 等于 Git LFS OID”检查。全仓库 `git lfs fsck`
  仍会报告两个与 BUMI3 无关且未实体化的大文件，因此不把全仓库 fsck 结果误写成
  BUMI3 资产失败。
- noetix 的 `compileall` 和转换器 4 项 pytest 均通过；本地完整
  `validate_bumi3_integration.py` 再次通过实际 Isaac Sim 配置导入、Hydra 组合、
  资产追溯、映射、执行器、碰撞和双编码器维度检查。
- 全量 `build` 后又独立运行一次 `validate`，两次均通过。最终是 3,261 个 robot、
  3,162 个 SMPL、3,162 个配对、99 个 Mine-only；所有 key 唯一，Mine-only 的
  `dataset=mine`、key 前缀为 `mine__`，并且 `smpl_file=null`。
- robot motion-lib 保持 30Hz，SMPL 的 pose/transl/joints 全部共同离线转为 50Hz，
  两者运行目标均为 50Hz。`meta/SHA256SUMS` 共 6,425 行，执行
  `sha256sum -c` 全部通过。
- 关键元数据指纹：`SHA256SUMS` 为
  `2fecb9ed7f70430c8d86a9b261c3c4d3862e032b31fb7b0dc06cfceffbf01c99`，
  `manifest.jsonl` 为
  `5871ec25ff70786763bb31d0f70b177bed6b278e8b7abdadec46e8b2020593b6`，
  `provenance.json` 为
  `e21d9572ee922a7db7d524e0197369f921f8b5b0dbef546db5faf24a8f3930cd`。

### 4. 实际训练 smoke

所有 smoke 都使用同一份正式数据、`checkpoint=null`、`auto_load_latest=False`、
`resume=False` 从零初始化。未使用 smoke 权重作为后一档 smoke 的初始化；最后的
checkpoint 重载是单独的兼容性检查。

| 阶段 | 结果 | 关键证据 |
|---|---|---|
| 单卡、64 env、10 iterations | 通过 | 完成 15,360 timesteps 和 10 次 PPO 更新；无 OOM、Traceback、NaN/Inf；首批实际采到 `mine__...` |
| 八卡、每 rank 512 env、100 iterations | 通过 | 8 个进程正常退出；9,830,400 timesteps；约 41k steps/s；每卡约 10.6–11.0GiB；无 OOM、NCCL timeout、Traceback、NaN/Inf |
| 八卡、每 rank 4,096 env、100 iterations | 通过 | 8 个进程正常退出；78,643,200 timesteps；稳定约 195k–202k steps/s；每卡约 20.3–20.9GiB、约 86–90% GPU 负载；无 OOM、NCCL timeout、Traceback、NaN/Inf |

- 4,096/rank 已完整通过，因此没有执行 2,048 或 1,024 回退，正式 `num_envs`
  取 4,096。
- 512/rank 和 4,096/rank 的日志均显示八个 rank 各自初始化 Robot（内部兼容键名
  `g1`）与 SMPL encoder，并在抽样 motion key 中实际出现 Mine-only。Mine 数据没有
  SMPL 文件，因此只能走 Robot encoder；配对数据同时提供两个 encoder 的输入。
- 4,096/rank 的 `last.pt` 在 step 50 和 100 均成功保存，大小约 368MiB。直接加载
  得到 global step 100、45 个 policy tensors、17 个 value tensors，并包含 optimizer、
  LR scheduler 和 env state。随后通过 SONIC 训练入口打印
  `Loaded checkpoint from step 100`，在单卡 64 env 上再完成 1 次 PPO 更新，证明
  不只是 pickle 可读，模型权重形状和加载路径也兼容。
- noetix 的 Isaac Sim 在纯 headless 启动时每 rank 会打印
  `VkResult: ERROR_INCOMPATIBLE_DRIVER` 和图形插件不可用；4,096/rank 日志共 24 次。
  这是当前服务器 Vulkan/渲染环境告警，不影响 PhysX/CUDA 无渲染训练：三档 smoke
  均继续完成，八卡负载稳定且进程以 0 退出。若未来需要相机或渲染，必须先修复
  Vulkan ICD/驱动环境，不能用本次 headless 训练通过替代渲染验证。

### 5. 正式训练边界

- 本轮没有启动 100k 正式训练，也没有执行 ONNX 导出；只证明当前提交、当前数据和
  当前 noetix 软硬件环境可从零训练到 4,096 env/rank。
- 正式训练必须继续使用 `checkpoint=null`、`auto_load_latest=False`、`resume=False`，
  不得添加 smoke checkpoint。正式命令的 `num_envs=4096` 已由完整 100 iterations
  实测确定，其余网络、PPO、环境和数据参数保持活跃配置不变。

## 2026-08-26：将误用的 BUMI2 集成完整迁移为 BUMI3

### 1. 修改原因与处理原则

- 用户确认实际训练机器人是 BUMI3，此前 BUMI2 机器人资产和参数选择错误。
- 本次不是简单字符串改名：BUMI2 的 URDF/MJCF、质量惯量、执行器上限、KP/KD、armature 和 action scale 全部废弃，按指定 BUMI3 参考目录重新复制和实现。
- 旧 BUMI2 资产目录、机器人模块、Hydra 实验入口和验证脚本已从当前集成中删除；这些文件此前均未提交，仍可从原参考仓库重新复制恢复。
- SONIC 的网络主体、Robot/SMPL 双编码器、PPO、critic、trainer、50 Hz 控制契约和 G1/H2 支持继续保留。

### 2. BUMI3 参考来源与版本状态

唯一机器人参数来源：

`/home/weili/legged_lab/source/NoetixRobot/NoetixRobot/assets/robots/bumi3/`

参考仓库当前提交：`d555c76e5977af66ef55a104b98e1be486349996`。

参考仓库当前存在未提交修改，因此本集成明确采用“当前工作区版本”，不回退到提交版：

- `bumi.py` SHA256：`74aaeca9da615c50e3749e4f103bbf713b83443d9cb16fab08edfd320227c03e`。
  - 相对当前 Git HEAD 的有效差异：arms `velocity_limit_sim` 从 `30` 改为 `12`；本集成采用 `12`。
- `urdf/bumi.urdf` SHA256：`174c1747019ced64267e74244bf89f3746856c90c30f88e4f162582ebc486476`。
- `mjcf/bumi3.xml` SHA256：`041c81e8176c7f375302796deca28b141891a3c097d8e341e8d967b735466edf`。
  - 相对当前 Git HEAD 的有效差异：`waist_yaw_joint` axis 使用 `0 0 1`；左右 `arm_roll` 限位分别为 `[-0.14, 1.94]`、`[-1.94, 0.14]`。这些当前值已原样纳入。
- `meshes/BUMI(1)_5.26.urdf` 和 `meshes/BUMI_V3.0_260119GG.urdf` 也有参考工作区修改；mesh 目录按当前文件集合逐文件复制并由验证脚本比较 SHA256。

验证脚本锁定上述三个关键 SHA。参考文件若再次变化，验证会明确失败，要求重新审计，而不会静默继续使用旧参数。

### 3. 机器人资产迁移

- 新增 `gear_sonic/data/assets/robot_description/urdf/bumi3/bumi.urdf`：复制 BUMI3 权威 URDF，只把 mesh 相对路径从 `../meshes/` 改为 `../../meshes/bumi3/`；质量、质心、惯量、碰撞、joint origin/axis/limit 均不修改。
- 新增 `gear_sonic/data/assets/robot_description/meshes/bumi3/*`：复制当前 BUMI3 `meshes/` 全部 26 个文件，包括 22 个 STL 和 4 个附属 URDF。
- 新增 `gear_sonic/data/assets/robot_description/mjcf/bumi3.xml`：复制当前 BUMI3 MJCF，只把 `meshdir` 从 `../meshes/` 改为 `../meshes/bumi3/`；body/joint 名称、轴、限位和全部数值均不修改。
- 删除本次集成产生的 `urdf/bumi2/`、`meshes/bumi2/` 和 `mjcf/bumi2.xml`。
- `.gitignore` 的资产白名单由 BUMI2 改为 BUMI3；本地 CSV、motion、训练输出和其他 `data/` 内容仍保持忽略。
- `.gitattributes` 对上述 BUMI3 URDF 设置路径级 `whitespace=cr-at-eol`：参考文件原生使用 CRLF，该规则只让 Git 将 `CR` 视为换行的一部分，不转换文件内容，从而同时保持参考字节与有效的代码 whitespace 检查。

### 4. BUMI3 原生机器人配置

新增 `gear_sonic/envs/manager_env/robots/bumi3.py`，不依赖 `NoetixRobot` Python 包，使用项目内 `DelayedImplicitActuatorCfg`。

基础配置与参考 `Bumi_CFG` 一致：

- floating base，contact sensors 开启，cylinder-to-capsule 开启。
- self collision 开启，solver position/velocity iterations 为 `8/4`。
- 初始 root position 为 `(0, 0, 0.65)`，soft joint position limit factor 为 `0.9`。
- 腿部初始姿态：左右 hip pitch `-0.1495`、knee `0.3215`、ankle pitch `-0.1720`，其余腿关节为零。
- 上身初始姿态：左 arm roll `0.3`、右 arm roll `-0.3`，腰和其他手臂关节为零。
- 四组执行器 delay 均为 `min_delay=0, max_delay=4`。

实际执行器参数如下，其中 effort/velocity 分别为仿真力矩和速度上限：

| 关节组 | effort | velocity | KP | KD | armature |
|---|---:|---:|---:|---:|---:|
| leg yaw | 12 | 12 | 20 | 1.0 | 未启用 |
| leg roll | 50 | 12 | 45 | 3.0 | 未启用 |
| leg pitch | 50 | 12 | 45 | 3.0 | 未启用 |
| knee pitch | 50 | 12 | 45 | 2.0 | 未启用 |
| waist yaw | 27 | 9 | 53 | 3.4 | 未启用 |
| ankle pitch | 9 | 12 | 8 | 0.5 | 0.012574 |
| ankle roll | 9 | 12 | 8 | 0.5 | 0.009608 |
| arm pitch/roll/yaw/elbow | 4 | 12 | 8 | 0.4 | 未启用 |

`BUMI3_ACTION_SCALE` 未写死，继续按 `0.25 * effort_limit_sim / stiffness` 生成：

- leg yaw：`0.15`。
- leg roll/pitch/knee：`0.2777777777777778`。
- waist yaw：`0.12735849056603774`。
- ankle pitch/roll：`0.28125`。
- arms/elbows：`0.125`。

### 5. 关节、body 顺序与映射

BUMI3 MuJoCo DoF 顺序来自当前 MJCF：

`[waist_yaw, l_arm_pitch, l_arm_roll, l_arm_yaw, l_elbow_pitch, r_arm_pitch, r_arm_roll, r_arm_yaw, r_elbow_pitch, l_leg_pitch, l_leg_roll, l_leg_yaw, l_knee_pitch, l_ankle_pitch, l_ankle_roll, r_leg_pitch, r_leg_roll, r_leg_yaw, r_knee_pitch, r_ankle_pitch, r_ankle_roll]`，各项完整名称均带 `_joint`。

BUMI3 Isaac Lab DoF 顺序来自参考 `bumi.py:joint_names`：

`[l_leg_pitch, r_leg_pitch, waist_yaw, l_leg_roll, r_leg_roll, l_arm_pitch, r_arm_pitch, l_leg_yaw, r_leg_yaw, l_arm_roll, r_arm_roll, l_knee_pitch, r_knee_pitch, l_arm_yaw, r_arm_yaw, l_ankle_pitch, r_ankle_pitch, l_elbow_pitch, r_elbow_pitch, l_ankle_roll, r_ankle_roll]`，各项完整名称均带 `_joint`。

映射由名称生成并在导入时验证：

- Isaac Lab → MuJoCo DoF：`[2, 5, 9, 13, 17, 6, 10, 14, 18, 0, 3, 7, 11, 15, 19, 1, 4, 8, 12, 16, 20]`。
- MuJoCo → Isaac Lab DoF：`[9, 15, 0, 10, 16, 1, 5, 11, 17, 2, 6, 12, 18, 3, 7, 13, 19, 4, 8, 14, 20]`。
- Isaac Lab → MuJoCo body：`[0, 3, 6, 10, 14, 18, 7, 11, 15, 19, 1, 4, 8, 12, 16, 20, 2, 5, 9, 13, 17, 21]`。
- MuJoCo → Isaac Lab body：`[0, 10, 16, 1, 11, 17, 2, 6, 12, 18, 3, 7, 13, 19, 4, 8, 14, 20, 5, 9, 15, 21]`。
- lower-body MuJoCo indices：`[9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]`。

### 6. SONIC 注册、converter 与数据接口

- `robots/__init__.py` 和 `modular_tracking_env_cfg.py`：只注册新 robot type `bumi3`；G1/H2 条目不变。
- `order_converter.py`：将原错误 converter 替换为 lazy-import `Bumi3Converter`；factory 支持 `bumi3`，默认仍为 G1。
- `commands.py`：BUMI3 lower-body index 检查固定为 `9..20`，通用默认仍为 G1 `range(12)`。
- `motion_lib_base.py`：wrist indices 继续可配置；BUMI3 设为空列表，G1 默认 `[19,20,21,26,27,28]` 不变。
- BUMI3 实验的 motion/SMPL 路径保持 `null`，必须由 CLI 指定，避免把任何 G1 或未核验 BUMI3 数据静默用于训练。

### 7. Robot + SMPL 双编码器 SONIC

- `all_mlp_v1_no_teleop.yaml`：只实例化内部键名 `g1` 的 Robot Encoder 和 `smpl` Encoder；MLP、FSQ、token、dynamic/kinematic decoder 不变。
- `unitoken_robot_smpl_noz.yaml`：只含 encoder index、Robot multi-future joint/anchor 和 SMPL multi-future local joint/root 输入。
- `g1_recon_and_smpl_latent.yaml`：只含 Robot reconstruction、Robot-SMPL latent 和 reencoded SMPL-Robot latent 三项损失。
- 内部 `g1` 键保留用于 SONIC 网络/checkpoint 兼容，不代表使用 G1 机器人资产。

### 8. BUMI3 专用训练配置

`sonic_bumi3.yaml` 保持：

- `sim_dt=0.005`、`decimation=4`，控制频率 50 Hz。
- `target_fps=50`，actor/critic history length 10。
- Robot/SMPL future frames 均为 10，步长分别 `0.1/0.02`。
- action dim 21，motion library asset 为 `bumi3.xml`，robot type 为 `bumi3`。
- 沿用 SONIC 14-body tracking subset、奖励函数和 termination 实现，只使用 BUMI3 当前模型中存在的 body 名称。

用户后续明确授权的 BUMI3 动力学差异：

- 质量 scale：选中 waist 和左右 elbow，范围 `[0.8, 1.2]`。
- 踝 armature：在各自 BUMI3 名义值上按 `[0.9, 1.1]` scale；pitch 实际范围 `[0.0113166, 0.0138314]`，roll 实际范围 `[0.0086472, 0.0105688]`。
- 全部 21 关节 KP/KD：分别按 `[0.8, 1.2]` scale，每次 reset 从名义默认值重新采样。
- 力矩限制奖励：全部关节，`limit_ratio=0.85`、`weight=-0.01`，惩罚平方超额和。

### 9. 验证脚本

`gear_sonic/tools/validate_bumi3_integration.py` 已迁移并增强：

- 锁定当前参考 `bumi.py`、URDF、MJCF SHA256。
- 比较 URDF/MJCF 允许的 mesh 路径改动以及 mesh 文件 SHA256。
- 验证 21 DoF、22 bodies、名称唯一、URDF/MJCF 全关节 axis/range 一致。
- 验证 DoF/body mapping 完整排列和 round trip。
- 验证完整初始姿态、rigid/solver 参数、全部 BUMI3 effort/velocity/KP/KD/armature/delay。
- 在隔离的模块命名空间内直接执行当前参考工作区的 `bumi.py`，逐字段比较本地 `BUMI3_CFG` 与参考 `Bumi_CFG`；这样不仅验证手工抄录的期望值，也验证本地实现与当前参考 Python 配置本身一致。
- 由公式验证 action scale，不依赖复制的常量。
- 验证质量、armature、KP/KD 随机化和 torque-limit reward 的 resolved 配置。
- 验证双编码器、无 Teleop 活跃输入/损失、FSQ 64、actor proprioception 690、tokenizer 1262、critic 1245、dynamic decoder `754 -> 21`。
- 保留可选 `--smoke` 环境 reset/step 和 NaN/Inf 检查。

### 10. 当前实际验证结果

- `/home/weili/miniconda3/envs/env_isaaclab/bin/python -m compileall -q gear_sonic`：通过。
- 静态 BUMI3 资产、拓扑、轴/限位、Hydra 和维度验证：通过。
- `/home/weili/miniconda3/envs/env_isaaclab/bin/python gear_sonic/tools/validate_bumi3_integration.py`：通过；实际导入 BUMI3 `ArticulationCfg` 并验证全部机器人参数和映射。
- 当前参考 `bumi.py` 直接执行与本地 `BUMI3_CFG` 逐字段一致性检查：通过；覆盖执行器 joint selector、effort/velocity、KP/KD、armature、delay、初始关节姿态和 action scale。
- MuJoCo 直接加载 `bumi3.xml`：通过；模型得到 `nq=28`、`nv=27`、`nu=21`、`nbody=23`（其中 `nbody` 包含 MuJoCo world body，对应机器人自身 22 bodies）。
- 活跃代码和配置负向搜索：`gear_sonic`、`.gitignore`、`agent.md` 中不存在 BUMI2 标识；`sonic_bumi3` 活跃配置中不存在 Teleop encoder、Teleop tokenizer input、Teleop auxiliary loss 或 G1 wrist index。
- resolved 数值：`sim_dt=0.005`、`decimation=4`、control frequency `50.0`、target FPS `50`、action dim `21`、FSQ `64`、actor proprioception `690`、tokenizer `1262`、critic `1245`、dynamic decoder `754 -> 21`。
- 包含全部未跟踪新资产/配置的临时索引 `git diff --cached --check`：通过；在本次碰撞修改前统计为 45 files changed、5319 insertions、7 deletions，真实 Git 暂存区未改动。
- 现有测试检索只发现 `gear_sonic/tests/test_input_readers.py`，没有覆盖机器人配置、converter、mapping 或 Hydra compose 的相关单元测试；1-env ManagerBasedRLEnv reset/step 和训练 smoke 也尚未运行。当前 BUMI3 配置要求用户提供相互匹配的 robot motion 与 SMPL motion；本轮未擅自选择、生成或转换数据。本机先前还存在 URDF importer extension 依赖冲突，不能把配置导入检查表述为环境 spawn 已通过。

## 2026-08-26：修复 BUMI3 双编码器 ONNX 导出硬编码 Teleop

### 问题

- `gear_sonic/eval_agent_trl.py` 的 universal-token ONNX 导出入口原先无条件导出 `smpl`、`g1`和 `teleop` 三个 encoder。
- BUMI3 活跃网络只注册 `g1` Robot Encoder 和 `smpl` Encoder，因此原入口会在读取 `encoder_input_features["teleop"]` 时触发 `KeyError: 'teleop'`，并在导出组合 encoder 和 decoder 之前异常退出。

### 修改内容与理由

- 删除 `smpl/g1/teleop` 三段硬编码调用，改为遍历当前模型的 `actor_module.encoders_to_iterate`。
- 导出前检查 encoder 列表非空，并确认每个 encoder 都已注册 `encoder_input_features`，避免缺失配置被静默忽略。
- 输出文件名仍为 `_<encoder_name>.onnx`；BUMI3 自动生成 `_g1.onnx` 和 `_smpl.onnx`，不再尝试生成 `_teleop.onnx`。
- 组合 `_encoder.onnx` 和 `_decoder.onnx` 继续导出，并复用已校验的 `actor_module` 引用。

### 兼容性

- BUMI3 双编码器模型只导出 `g1/smpl`，修复确定的 Teleop `KeyError`。
- 原 G1 SONIC 的 `encoders_to_iterate` 仍包含 `g1/teleop/smpl`，因此依然会导出三个 encoder 模型，不删减原有能力。
- 不修改训练网络、checkpoint、观测维度、FSQ、decoder 或 PPO 参数。

### 实际验证结果

- `compileall` 和 `git diff --check` 通过。
- Hydra 解析后，BUMI3 的 encoder 顺序为 `['g1', 'smpl']`，原 G1 SONIC v1.1 为 `['g1', 'teleop', 'smpl']`，证明动态导出同时覆盖双编码器和三编码器配置。
- 使用当前 BUMI3 resolved 网络和随机初始化权重实际执行同一导出逻辑，精确生成四个模型：
  - `_g1.onnx`：输入 `[1, 1170]`，输出 `[1, 21]`；
  - `_smpl.onnx`：输入 `[1, 1470]`，输出 `[1, 21]`；
  - `_encoder.onnx`：输入 `[1, 1263]`，输出 `[1, 64]`；
  - `_decoder.onnx`：输入 `[1, 754]`，输出 `[1, 21]`。
- 四个模型均通过 ONNX checker 和 ONNX Runtime CPU 有限值推理；组合 encoder 的 `g1/smpl` 两个 selector 分支均通过。
- 导出目录中没有 `_teleop.onnx`，因此 BUMI3 不再进入会触发 `KeyError: 'teleop'` 的路径。
- 未运行“真实训练 checkpoint + 完整仿真环境”的 `eval_agent_trl.py` 全流程：当前没有本次从零训练生成的 BUMI3 checkpoint 及成对动作数据。本轮已验证的是本次修改直接影响的网络构建与 ONNX 导出边界。

## 2026-08-26：为爬行和跪地动作补齐 BUMI3 简化碰撞体

### 1. 修改原因和范围

- SONIC 训练动作包含爬行、跪地等非站立接触，原 BUMI3 URDF 的 `base_link`、左右 `leg_roll_link` 和左右 `knee_pitch_link` collision 被注释，无法产生相应身体接触。
- 用户明确要求上述 link 使用圆柱简化碰撞，并取消左右 `leg_pitch_link`、左右 `leg_yaw_link` 的碰撞。
- 本轮只修改 SONIC 使用的 `gear_sonic/data/assets/robot_description/urdf/bumi3/bumi.urdf`；参考 `legged_lab`、BUMI3 MJCF、mesh、质量、质心、惯量、visual、joint origin/axis/limit、执行器和训练配置均未修改。

### 2. 圆柱尺寸和坐标依据

使用当前仓库 BUMI3 STL 的局部轴对齐包围盒确定圆柱长度和中心，圆柱轴均沿 link 局部 Z 轴。半径取横向主半宽并小幅取整，没有采用包围盒对角半径，避免爬行时碰撞体过度膨胀：

| Link | STL 局部 AABB extents | collision origin xyz | radius | length |
|---|---|---|---:|---:|
| `base_link` | `[0.101807, 0.096937, 0.131050]` | `[-0.0013853, 0, 0.065525]` | `0.052` | `0.13105` |
| `l/r_leg_roll_link` | `[0.115000, 0.083960, 0.156461]` | `[0, 0, -0.0402693]` | `0.058` | `0.1564614` |
| `l/r_knee_pitch_link` | `约 [0.09297, 0.10500, 0.255315]` | `[0.008475, 0, -0.0894694]` | `0.053` | `0.2553155` |

最终 URDF collision 策略：

- 圆柱 collision：`base_link`、`l_leg_roll_link`、`r_leg_roll_link`、`l_knee_pitch_link`、`r_knee_pitch_link`。
- 无 collision：`l_leg_pitch_link`、`r_leg_pitch_link`、`l_leg_yaw_link`、`r_leg_yaw_link`。
- 其余 link 的 collision 与当前 BUMI3 参考 URDF 保持一致。
- `BUMI3_CFG.spawn.replace_cylinders_with_capsules=True` 保持不变，所以文件层面是用户要求的 URDF cylinder，Isaac Lab 训练运行时会将这五个 cylinder 转成接触更平滑的 Capsule。

### 3. 验证脚本修改

- 修改 `gear_sonic/tools/validate_bumi3_integration.py` 的资产追溯逻辑：结构化比较本地与参考 URDF，并忽略且单独审计 collision 节点；由此证明除 mesh 相对路径和本次指定 collision 外，其他 URDF 结构完全未改。
- 新增五个圆柱的 link、origin、RPY、radius、length 和唯一 geometry 检查。
- 新增四个无碰撞 link 的零 collision 检查。
- 对其余全部 link 逐项比较本地和参考 collision，防止意外扩大修改范围。

### 4. 实际验证结果

- 使用 `trimesh` 读取 9 个相关 BUMI3 STL 并检查 bounds/centroid：通过；上述尺寸均来自当前 BUMI3 mesh。
- XML 资产追溯、碰撞策略、mesh 存在性、21 DoF 和 22 bodies 静态检查：通过，输出 `COLLISION_STATIC_VALIDATION=PASS`。
- `/home/weili/miniconda3/envs/env_isaaclab/bin/python -m compileall -q gear_sonic`：通过。
- `/home/weili/miniconda3/envs/env_isaaclab/bin/python gear_sonic/tools/validate_bumi3_integration.py`：通过；原 SONIC 时间、网络、映射、执行器和 Hydra 兼容性检查均保持通过。
- 使用 Isaac Lab `UrdfConverterCfg(replace_cylinders_with_capsules=True)` 实际执行 URDF→USD：通过；生成主 USD 共 14 个 collider，五个目标 link 均为 Capsule，四个禁用 link 均没有 collider，输出 `ISAAC_URDF_TO_USD_COLLISION_SMOKE=PASS`。
- 第一次 USD 检查只使用普通 `stage.Traverse()`，没有遍历 instance proxy，因此误报缺少 `base_link` collider；生成的 USD 本身成功。改用 `Usd.TraverseInstanceProxies()` 后重新断言并通过。
- 未运行含动作数据的 1-env reset/step 或爬行/跪地 replay：BUMI3 robot-motion/SMPL 数据路径仍按训练安全要求保持 `null`，本轮没有擅自选择训练数据。因此碰撞资产和 Isaac 导入已验证，但具体动作的接触质量仍需在指定动作数据上回放确认。
- 该轮完成时的完整临时索引 `git diff --cached --check`：通过；当时累计统计为 45 files changed、5461 insertions、7 deletions，真实 Git 暂存区未改动。

## 2026-08-26：按训练需求缩小 BUMI3 圆柱碰撞体

### 1. 用户指定参数

本次参数是用户对上一版 STL 包围盒初始方案的明确覆盖，不再把圆柱描述为完整包络 mesh。碰撞 link 集合和局部 Z 轴方向不变，只修改以下尺寸与位置：

| Link | 修改项 | 新值 | 保持不变项 |
|---|---|---|---|
| `base_link` | length | `0.12` | radius `0.052`，origin `[-0.0013853, 0, 0.065525]` |
| `l/r_leg_roll_link` | radius、length、origin | `0.03`、`0.08`、`[0, 0, -0.02]` | RPY `[0, 0, 0]` |
| `l/r_knee_pitch_link` | radius、length | `0.025`、`0.13` | origin `[0.008475, 0, -0.0894694]`，RPY `[0, 0, 0]` |

左右 `leg_pitch_link` 和左右 `leg_yaw_link` 继续保持无 collision；其他 link 的碰撞不变。`replace_cylinders_with_capsules=True` 也不变，因此 Isaac Lab 运行时仍会把五个 URDF cylinder 转为 Capsule。

### 2. 修改文件和原因

- `gear_sonic/data/assets/robot_description/urdf/bumi3/bumi.urdf`：应用用户指定的新圆柱参数；未修改 visual、inertial、joint、mesh 路径或其他 collision。
- `gear_sonic/tools/validate_bumi3_integration.py`：同步更新五个圆柱的期望值，并明确这些值来自用户训练调参，而不是继续声称完全来自 STL AABB。
- `BUMI3_SONIC_修改记录.md`：记录覆盖关系、最终参数、未改范围和测试证据。

### 3. 兼容性边界

- 不修改 BUMI3 MJCF、执行器、action scale、域随机化、奖励、termination、SONIC 网络、控制频率或数据路径。
- 不修改参考 `/home/weili/legged_lab`。
- 21 DoF、22 bodies、关节/body 顺序和 Isaac Lab/MuJoCo mapping 不变。

### 4. 实际验证结果

- XML 资产追溯、五个圆柱精确参数、四个无碰撞 link、mesh 存在性、21 DoF 和 22 bodies 静态检查：通过，输出 `COLLISION_STATIC_VALIDATION=PASS`。
- `/home/weili/miniconda3/envs/env_isaaclab/bin/python -m compileall -q gear_sonic`：通过。
- `/home/weili/miniconda3/envs/env_isaaclab/bin/python gear_sonic/tools/validate_bumi3_integration.py`：通过；SONIC 时间参数、网络维度、执行器和映射仍保持原值。
- 使用 `UrdfConverterCfg(replace_cylinders_with_capsules=True)` 强制重新生成 USD：通过；随后通过 `Usd.TraverseInstanceProxies()` 读取实际碰撞 prim，五个目标 link 的 Capsule origin/radius/height 与本节表格逐项一致，轴均为 Z。
- 生成 USD 共 14 个 collider；左右 `leg_pitch_link`、左右 `leg_yaw_link` 仍为零 collider，输出 `ISAAC_TUNED_COLLISION_SMOKE=PASS`。
- 未运行带爬行/跪地动作数据的环境 replay，原因仍是 BUMI3 robot-motion/SMPL 路径保持 `null`，本轮未擅自选择数据。

## 2026-08-31：修正双肘终止与 BUMI3 sim2sim 参考状态、锚点及碰撞语义

### 1. 起点、授权范围和保护措施

- 分支：`feature/bumi-native-sonic-full-training`。
- 修改前 HEAD：`b1c3606ce96f00a01745cb8382f8bfa0b9b4d780`。
- 用户明确要求：`ee_body_pos` 只检查双肘并保留 `0.12 m`；降低 sim2sim 固定悬空回退高度；修复 Robot Encoder 把 root quaternion 当成 `waist_yaw_link` 锚点姿态的问题；解释终止条件和 Robot/SMPL 异常配对。
- 工作树在本轮开始前已有 BUMI3 资产、数据准备、sim2sim 和记录文件的未提交改动；本轮没有 reset、clean、stash、checkout、rebase，也没有提交或推送。

### 2. 训练 termination 修改

- `gear_sonic/config/exp/manager/universal_token/all_modes/sonic_bumi3.yaml`：从 `ee_body_pos.params.body_names` 删除左右 `ankle_roll_link`，只保留 `l_elbow_pitch_link`、`r_elbow_pitch_link`；threshold 继续为 `0.12`，adaptive、down threshold、root height threshold 和 termination 实现均未修改。
- 左右脚仍由独立的 `foot_pos_xyz` 检查，不再同时进入 `ee_body_pos`。该改动减少重复截断，但不被描述为训练失败的唯一根因。
- `gear_sonic/tools/validate_bumi3_integration.py`：同步锁定 resolved 双肘列表，防止 Hydra 配置回退到双脚+双肘。

### 3. sim2sim 参考状态和初始化高度

- `ReferenceMotion` 新增可选 `root_position_world`。SONIC PKL/NPZ 会读取 `root_trans_offset/root_pos/root_position/root_translation`，含 `qpos` 的 NPZ 可回退到 `qpos[:, :3]`；CSV 若提供 `body_pos.csv` 则读取第一个 body 的位置。
- reset 不再固定写入 `[0,0,0.65] + 默认关节 + 零速度`，而是使用所选参考帧的 root position、root quaternion、21 关节位置和关节速度；浮动根速度由相邻 MuJoCo qpos 用 `mj_differentiatePos` 求得。
- `gear_sonic/config/sim2sim/bumi3_sonic.yaml` 的旧动作缺 root translation 时的回退位置改为 `[0,0,0.4744]`。真实 FineDance 首帧实际使用动作自带的约 `0.529/0.538 m`，不是强行改成回退高度。
- reset 的 10 帧 proprioception history 改为按 Isaac Lab `CircularBuffer` 首次 append 行为用当前状态复制填满，不再以 9 帧零状态开始。

### 4. Robot Encoder 锚点语义修复

- 训练端 `motion_anchor_ori_b_mf_nonflat` 实际读取 `TrackingCommand.root_rot_dif_l_multi_future`，其参考 quaternion 来自 MotionLib 中 `motion_anchor_body_index` 指向的 `waist_yaw_link`，不是浮动根 `base_link`。
- 旧 sim2sim 在 tokenizer 和起始 heading 对齐中直接使用 `motion.root_quat_wxyz`，因此腰部 yaw 非零时输入语义错误。
- 新实现逐帧把参考 root 和 21 关节写入一个独立 `MjData`，调用 BUMI3 MJCF FK，缓存 `waist_yaw_link` 的世界 quaternion；未来 10 帧 6D orientation 和起始 heading 对齐均使用该缓存。
- checkpoint/ONNX 只保存网络权重和张量接口，不保存动作文件、anchor body 名称或 FK 结果。本地 `model_step_070000.pt` 为 368 MiB，含 policy/value/optimizer/trainer state；`env_state_dict` 只有 motion-lib state。`model_step_070000_g1.onnx` 为 53 MiB、输入 1170、输出 21，因此部署端必须自行正确重建观测。

### 5. sim2sim 碰撞语义修复

- 真实 FineDance 首帧在旧 MJCF mesh collision 下 reset 即出现左右 `knee_pitch_link` 与 `ankle_roll_link` 自碰撞，穿透分别约 `24.62/24.87 mm`。首帧 observation 最大绝对值为 `1.08`，一次控制后碰撞冲击把该值推到约 `31`，证明问题不只是初始高度。
- 运行器现在仅在内存 `MjModel` 中关闭训练 URDF 未启用的 arm pitch、arm yaw、leg pitch、leg yaw mesh collision；把 base、左右 leg roll、左右 knee 的 mesh geom 改为训练 importer 实际使用的 capsule。
- capsule 的位置、半径和半长严格对应当前 URDF cylinder 与 `replace_cylinders_with_capsules=True`：base `[-0.0013853,0,0.065525], r=0.052, half=0.06`；leg roll `[0,0,-0.02], r=0.03, half=0.04`；knee `[0.008475,0,-0.0894694], r=0.025, half=0.065`。
- 原始 `bumi3.xml` 未改写；GUI 中上述五个单 geom 会显示成简化 capsule。该取舍避免改变 MotionLib 使用的参考 MJCF，同时优先保证 sim2sim 碰撞动力学接近训练 URDF。

### 6. Robot/SMPL 精确配对审计结论

- 在服务器 `/data/sonic_bumi3/datasets/hq_all_v2/built` 对 3162 个公开 Robot/SMPL 同名配对重新审计；99 个 Mine robot-only 动作没有 SMPL，不计入“异常配对”。
- 审计严格使用 MotionLib 的 `arange(0,duration,1/50)` 独占末帧时间网格、机器人 root+waist quaternion Slerp、BUMI3 `waist_yaw_link` FK 等价姿态，以及训练端 SMPL Y-up→Z-up 和 base rotation removal。3162 对全部帧数一致，没有时间轴长度错配。
- 以整段 `median(angle(inv(robot_waist) * smpl_root)) > 45°` 为初筛后得到 55 条，而不是旧的 root-only 近似统计 57 条。55 条中 51 条来自 AIST++、3 条 AIOZ-GDance、1 条 COMPAS；AIST++ 中 33 条为 `gBR` breakdance。
- 55 条中 41 条至少一侧中位倾角超过 45°：23 条双方均超过、13 条只有机器人 waist 超过、5 条只有 SMPL root 超过。这些主要是倒地、翻滚、breaking 等动作在人类 pelvis 与重定向机器人 base/waist 上的姿态差，不是整库仍存在统一 90° 坐标轴错误。
- 剩余 14 条双方中位倾角都不超过 45°，但多数已接近 30–45°；只有 `aistpp__gWA_sBM_cAll_d26_mWA4_ch08.pkl` 双方都低于 30°（约 23.4°/23.9°）而相对角中位数仍约 48.6°，应列为优先人工同步回放对象。该审计不自动删除或改写训练数据。

### 7. 修改文件及目的

- `gear_sonic/config/exp/manager/universal_token/all_modes/sonic_bumi3.yaml`：`ee_body_pos` 仅双肘。
- `gear_sonic/config/sim2sim/bumi3_sonic.yaml`：旧动作固定回退根高降至 `0.4744 m`。
- `gear_sonic/utils/mujoco_sim/bumi3_sim2sim.py`：root translation 加载、参考状态 reset、正确 history 初始化、waist FK anchor、训练 URDF collision runtime override。
- `gear_sonic/tests/test_bumi3_sim2sim.py`：新增 root translation、参考 reset、waist FK、history 和 collision 回归测试。
- `gear_sonic/tools/validate_bumi3_sim2sim.py`：验证回退根高、FK anchor、collision override，并打印实际 reference reset 来源。
- `gear_sonic/tools/validate_bumi3_integration.py`：验证 resolved `ee_body_pos` 仅双肘。
- `docs/source/getting_started/bumi3_sim2sim.md`：说明 checkpoint/ONNX 边界、参考初始化、anchor FK、history 和碰撞契约。
- `BUMI3_SONIC_修改记录.md`：记录本轮原因、实现、实测数据、测试边界和回滚信息。

### 8. 实际运行的验证及结果

- `git diff --check`：通过。
- `/home/weili/miniconda3/envs/env_isaaclab/bin/python -m pytest -q gear_sonic/tests/test_bumi3_sim2sim.py gear_sonic/tools/test_prepare_bumi3_sonic_dataset.py`：`15 passed`；另有 1 个既有 invalid escape sequence DeprecationWarning。
- `/home/weili/miniconda3/envs/env_isaaclab/bin/python gear_sonic/tools/validate_bumi3_integration.py`：通过；resolved `sim_dt=0.005`、`decimation=4`、control 50 Hz、action 21、actor proprioception 690、dynamic decoder `754 -> 21`。
- `/home/weili/miniconda3/envs/env_isaaclab/bin/python -m compileall -q gear_sonic`：通过。
- 真实 `model_step_070000_g1.onnx` + `finedance__001_50fps.pkl` 执行 100 个控制周期：接口、1170/21 维度、FK anchor、碰撞覆盖和 NaN/Inf 检查通过；2 秒后 root height 仍降到 `0.066842 m`。
- 最后一项明确表明当前 70k checkpoint 仍未学会稳定跟踪；本轮已修复部署语义，但不能把有限值 smoke 误报为动作质量通过。训练曲线此前平均 episode 约 `0.79 s`、`ee_body_pos` 聚合触发约 70%，所以该 checkpoint 摔倒与训练质量一致，需要在新 termination 配置下做受控重训/对照实验后再导出新 ONNX。

### 9. 未执行项、风险和回滚

- 未在本轮停止、重启或续训服务器任务；代码配置改变不会追溯修改已有 checkpoint。
- 未自动筛除 55 条高差异配对，因为其中大量是用户需要的爬行、倒地和 breakdance；应先对 14 条非明显倒地项，尤其唯一双方低于 30° 的样本做 Robot/SMPL 同步可视化，再决定 quarantine。
- 未证明删除脚部重复 termination 单独即可解决训练。正确验证方法是同一初始权重/seed 做旧配置与新配置短程 A/B，记录左右脚、左右肘的独立误差和首次触发 body；当前聚合 `ee_body_pos` TensorBoard tag 无法反推是哪一个 body。
- 回滚范围是本节列出的配置、sim2sim、测试、验证和文档局部 diff；工作树无本轮 commit，不能使用破坏其他未提交修改的全局 reset。

## 2026-08-31：隔离 55 条异常配对、增加坐标启动门禁与 TensorBoard

### 1. 起点与授权边界

- 分支：`feature/bumi-native-sonic-full-training`。
- 修改前 HEAD：`b1c3606ce96f00a01745cb8382f8bfa0b9b4d780`。
- 用户明确要求：55 条 Robot/SMPL 异常配对不参与训练；确认原始/训练坐标契约；在服务器从头启动 8 卡训练；必须产生 TensorBoard event 文件。
- 本轮开始前工作树已有 BUMI3 数据、碰撞、sim2sim 和记录文件的未提交改动。本轮未执行 reset、clean、stash、checkout、rebase、commit 或 push，也未覆盖无关改动。

### 2. 55 条异常动作的精确隔离

- `sonic_bumi3.yaml` 在 `motion_lib_cfg.exclude_motion_keys` 中逐条保存 55 个完整 key：AIST++ 51 条、AIOZ-GDance 3 条、CoMPAS3D 1 条；不含 99 条 Mine-only 动作。
- `motion_lib_base.py` 新增 `exclude_motion_data_by_exact_keys`，在正则过滤、前缀删除和随机限量之前执行完整 key 匹配。它不复用 `remove_motion_keys` 的前缀语义，也不原地修改完整动作索引。
- MotionLib 会记录 requested、matched、missing、remaining。完整训练集的预期日志为 `requested=55, matched=55, missing=0, remaining=3206`；对单动作导出/回放则允许清单中其他 key 缺失并明确 warning，避免破坏既有评估入口。
- `validate_bumi3_integration.py` 锁定数量、唯一性、来源计数和排序后 SHA256 指纹 `808786f5202af4c8cef08c0aee8ff025468b99d3e3a5ade83f273e2d4aacfd88`。
- `test_prepare_bumi3_sonic_dataset.py` 新增精确匹配、无前缀误删、原字典不被修改、重复 key 拒绝测试。

### 3. 原始数据和训练输入的坐标契约

- 四个公开 Robot 库源契约为 `genmo.bumi_legacy_motion.v1`：世界上轴是 `+Y`。数据准备阶段对根四元数世界系左乘 `Rx(+90°)`，统一写成 SONIC/MuJoCo `+Z` 上轴；21 个关节按 BUMI3 MuJoCo actuator 名称重排；根高按当前 BUMI3 MJCF 双脚 FK 优化。Robot 文件仍以 30 Hz 保存，MotionLib 按独占末帧的时间网格插值为 50 Hz。
- Mine Robot 源契约为 `genmo.bumi_csv_qpos_xyzw.v1`：已经是 `+Z` 上轴，因此根姿态使用 identity 修正；关节顺序和根高仍按同一 BUMI3 契约校验。Mine 只有 Robot 动作，没有 SMPL 配对。
- 公开 SMPL 的 `pose_aa` 保留源 `+Y` 上轴并以 50 Hz 保存。训练命令项在构造 SMPL 根姿态 token 时左乘 `Rx(+90°)` 一次，再移除 `[0.5,0.5,0.5,0.5]` SMPL base rotation；`smpl_y_up=true` 因此是正确且必要的，不能改成 false。
- 同一个 SMPL 文件中的 `smpl_joints` 已在数据准备阶段使用转换后的 Z-up 根姿态做 FK，训练观测不再对 joint positions 做第二次 Y→Z 转换。也就是说，源文件保留可追溯契约，但进入两个 Encoder 的实际姿态/关节张量都已经在 Z-up 语义下。

### 4. 训练前坐标门禁

- 新增 `gear_sonic/tools/validate_bumi3_training_coordinates.py`。该脚本只读数据，不生成、改写、筛选或重采样任何文件。
- Robot 侧复现 MotionLib 30→50 Hz 时间网格，并对 root 与 `waist_yaw_link` 局部姿态分别 Slerp 后组合腰部世界姿态；SMPL 侧复现训练时 Y-up→Z-up 和 base rotation removal。
- 门禁要求 3261 Robot、3162 同名配对、99 Mine-only、55 个隔离 key 全部存在；重新计算的 `median(angle(inv(robot_waist) * processed_smpl_root)) > 45°` 集合必须与配置中的 55 条完全一致。通过后预期训练候选为 3206 Robot，其中 3107 条有 SMPL。

### 5. TensorBoard 原生写入

- `ppo_trainer.py` 在 rank 0 为每个实验创建 `<experiment_dir>/tensorboard/` 的 `SummaryWriter`，初始化时立即 flush，保证即使环境或首轮 rollout 失败也能定位 event 文件。
- 每次 PPO 日志迭代把已有的数值指标按 `global_step` 写入并 flush；字符串路径等非标量不会写入。正常结束和提前停止都会关闭 writer；其他 GPU 不重复写 event。
- 该改动不改变 PPO、网络、奖励、控制频率、batch 或优化器，只新增旁路可视化记录。

### 6. 已完成的本地验证

- `/home/weili/miniconda3/envs/env_isaaclab/bin/python -m compileall -q gear_sonic`：通过。
- `/home/weili/miniconda3/envs/env_isaaclab/bin/python -m pytest -q gear_sonic/tools/test_prepare_bumi3_sonic_dataset.py`：`8 passed`；有 1 个既有 invalid escape sequence DeprecationWarning。
- `git diff --check`：通过。

### 7. 待本节后续补录

- 尚需把本轮文件同步到 `noetix-volc:/home/liwei/GR00T-WholeBodyControl`，运行全量坐标门禁和 BUMI3 集成验证，再启动新的 8 卡 scratch 训练。
- 只有确认 MotionLib 日志命中 55/55、首轮真实 PPO 指标、8 张 4090 均有计算负载、训练日志无 traceback/NaN/Inf、且新实验目录内存在可解析 TensorBoard event 后，才把“训练已重启”记录为完成。

### 8. 服务器全量门禁和 8 卡 scratch 启动结果

- 同步目标：`noetix-volc:/home/liwei/GR00T-WholeBodyControl`。仅同步本轮明确涉及的配置、MotionLib、trainer、测试、验证脚本和记录文件；没有目录级删除、Git reset/clean 或参考仓库修改。
- 首次多源 `rsync` 错误地把 6 个代码文件平铺到远端仓库根目录。核对文件名/大小后仅删除这 6 个由本轮刚创建的根目录副本，再以 `rsync -R` 同步到正确包路径；实际包内文件在纠正前未被该错误传输覆盖，其他根目录文件未动。
- 服务器 `/root/miniconda3/envs/liwei_lab/bin/python -m compileall -q gear_sonic`：通过。
- 服务器数据契约单测：`8 passed`，同一既有 invalid escape sequence warning。
- 服务器全量坐标门禁：通过。实际输出为 `robot_total=3261 smpl_paired=3162 mine_only=99 excluded=55 training_robot=3206 training_smpl=3107`；保留配对相对角中位数 `13.636874°`、最大 `44.710664°`，隔离集合最小 `45.181285°`。
- 远端 `validate_bumi3_integration.py` 未通过外部参考 provenance 检查：`/home/liwei/legged_lab` 的 `bumi.py` 和 MJCF 已不同于本地锁定参考版本。只读核对确认本仓库实际训练 URDF/MJCF 哈希与本地通过集成验证的文件完全一致；训练不动态导入远端参考仓库。没有为了通过检查而修改 `legged_lab` 或放宽哈希门禁。

实际启动命令使用 Accelerate 8 个进程、每个 rank 4096 个环境、100000 PPO iterations：

```bash
/root/miniconda3/envs/liwei_lab/bin/accelerate launch --num_processes=8 \
  gear_sonic/train_agent_trl.py \
  +exp=manager/universal_token/all_modes/sonic_bumi3 \
  +resume=false checkpoint=null auto_load_latest=false \
  use_wandb=false headless=True num_envs=4096 \
  base_dir=/data/sonic_bumi3/runs \
  exp_var=hq_all_v2_coordfix_q55_scratch_100k \
  algo.config.num_learning_iterations=100000 \
  ++manager_env.commands.motion.motion_lib_cfg.motion_file=/data/sonic_bumi3/datasets/hq_all_v2/built/robot_all \
  ++manager_env.commands.motion.motion_lib_cfg.smpl_motion_file=/data/sonic_bumi3/datasets/hq_all_v2/built/smpl_all
```

- tmux：`sonic_bumi3_q55_8gpu`。
- 启动日志：`/data/sonic_bumi3/launch_logs/sonic_bumi3_q55_8gpu_20260831_135526.log`。
- 实验目录：`/data/sonic_bumi3/runs/TRL_BUMI3_Track/manager/universal_token/all_modes/sonic_bumi3_hq_all_v2_coordfix_q55_scratch_100k-20260831_135533`。
- resolved config 已确认 `checkpoint: null`、`resume: false`、`auto_load_latest: false`，日志没有 checkpoint 加载记录，属于从头训练。
- 8 个 rank 均打印 `requested=55, matched=55, missing=0, remaining=3206`，证明隔离实际生效而非只写进 YAML。
- 观察到第 12 iteration：约 `226842–231005 steps/s`；第 12 轮 mean reward `0.50039`、mean length `11.18375`。这是随机初始化最早期指标，只能证明训练循环工作，不能据此判断收敛质量。
- 检查时 8 张 RTX 4090 显存约 `19.7–20.7 GiB`，GPU 利用率约 `74%–89%`；8 个 worker 均存活。
- 训练日志未发现 traceback、AssertionError、RuntimeError、OOM、NCCL error 或 NaN/Inf。Isaac headless 初始化存在既有 Vulkan/GPU Foundation renderer 报错，但各 rank 均继续完成场景、MotionLib、DDP 和 PPO 训练初始化。
- TensorBoard event：`<实验目录>/tensorboard/events.out.tfevents.1788155827.noetix.3046464.0`。EventAccumulator 成功解析 `122` 个 scalar tags；检查时已有 13 个 step，`objective/rewards=0.5022393`、`objective/length=11.48`、`fps=229372`，证明不是空文件或仅创建目录。

## 2026-08-31：BUMI3 SONIC sim2sim 参考影子与训练 termination 复查

### 1. 起点、参考范围和保护措施

- 分支：`feature/bumi-native-sonic-full-training`；起始 HEAD：`b1c3606ce96f00a01745cb8382f8bfa0b9b4d780`。
- 本轮开始前 sim2sim 核心、入口、测试、验证和文档均为工作区内已有的未跟踪文件；本轮在其现有实现上增量加入参考影子，没有 reset、clean、stash、覆盖其他用户文件，也没有 commit/push。
- 用户指定参考 `/home/weili/legged_lab/scripts/sim2sim_mimic_vision_4340.py`。本轮只复用“独立参考 FK data + 半透明 decorative geom”的可视化思路；没有复制 BUMI3_4340 的执行器、关节限位、初始高度、映射、奖励或其他机器人参数。实际影子继续使用本仓库 BUMI3 SONIC contract、21 DoF 名称映射和当前 `bumi3.xml`。

### 2. 服务器 termination 实际复查

- 训练会话仍为 `sonic_bumi3_q55_8gpu`，检查时 8 个 worker 存活，日志无 traceback/OOM/NCCL/NaN。
- TensorBoard rank-0 曲线：`objective/length` 从 step 1 的 `11.865` 增至 step 1000 的 `34.19`，但 step 4503 又降至 `24.10`，即平均 episode 约 `0.482 s`；`objective/rewards` 同期为 `0.52251 -> 2.14561 -> 1.50061`，没有保持单调改善。
- step 4503 termination：`anchor_pos=0.26003`、`anchor_ori_full=0.06537`、`ee_body_pos=0.53400`、`foot_pos_xyz=0.44933`。当前 `ee_body_pos` 已只包含双肘，因此高触发率不能再归因于双脚重复计数；双肘和双脚位置仍是主要失败项，anchor position 也在恶化，而 anchor orientation 已相对较低。
- termination term 可以同一 episode 同时触发，所以上述比例不可相加当成概率分布；但短 episode、双肘/双脚高触发以及 length/reward 回落共同证明当前训练仍未稳定学会跟踪。

### 3. 参考影子实现

- `gear_sonic/utils/mujoco_sim/bumi3_sim2sim.py`：新增独立 `reference_visual_data`。每帧用动作文件的 root position、root quaternion 和 21 个关节构造完整 MuJoCo qpos，只施加与 Robot Encoder 一致的可选起始 heading 对齐，再执行 `mj_forward`。
- 参考 root Z 不跟随真实机器人，也不在显示层做贴地或高度覆盖。如果训练参考横躺/穿地，红色影子会原样显示，避免参考脚本中 `align_reference_height_to_robot=True` 掩盖问题。
- 参考 geom 写入 passive viewer 的 `user_scn`，统一红色 tint、默认 alpha `0.32`，category 为 `mjCAT_DECOR`；不进入 contact、collision、actuator 或 MuJoCo 积分。
- 新增 `reference_pose_diagnostics`：打印参考帧 root height、base/`waist_yaw_link` 上轴对世界 +Z 的倾角和最低 body origin 高度。站立通常接近 0°，侧躺通常接近 90°。
- `gear_sonic/scripts/run_bumi3_sim2sim.py`：默认开启影子，新增 `--reference-alpha` 和 `--no-show-reference`，启动前打印 `BUMI3_REFERENCE_POSE`。
- `gear_sonic/tests/test_bumi3_sim2sim.py`：新增直立/90°侧躺诊断、参考高度不跟随实际机器人、marker 数量/有限值/透明度/decorative category 回归测试。
- `gear_sonic/tools/validate_bumi3_sim2sim.py`：验证独立参考 FK、22 个影子 geom、alpha 和 physics=false 契约。
- `docs/source/getting_started/bumi3_sim2sim.md`：记录不透明实际机器人/红色参考影子的视觉含义、判读方式和 CLI。

### 4. 真实参考和旧 checkpoint 验证

- `finedance__001_50fps.pkl` 首帧：root height `0.538330 m`，base/waist tilt 均为 `0.755295°`，明确为直立参考，不是横躺。
- `finedance__001` 全 4879 帧：base/waist tilt 中位数 `9.019°`、P95 `27.0182°`、最大 `93.8133°`、超过 45° 帧占 `3.2794%`。少量高倾角帧属于动作内容，整段不是统一横躺。
- `finedance__002` 全 5179 帧：中位数 `11.4468°`、P95 `54.1611°`、最大 `81.7806°`、超过 45° 帧占 `8.0711%`；该动作包含更多大倾角片段，但中位参考仍为直立。
- 使用旧 `model_step_070000_g1.onnx` + `finedance__001_50fps.pkl` 做 100 控制步真实 smoke：参考首帧 tilt `0.7553°`，实际机器人 2 秒后 root height `0.066842 m`。至少对该轨迹，摔倒不能归因于参考首帧横躺，说明需要继续检查 checkpoint 学习质量、SONIC 双编码器/解码器训练语义、奖励/termination 和部署动力学，而不是继续做统一 90° 根坐标修正。

### 5. 实际测试及结果

- `/home/weili/miniconda3/envs/env_isaaclab/bin/python -m compileall -q gear_sonic`：通过。
- `/home/weili/miniconda3/envs/env_isaaclab/bin/python -m pytest -q gear_sonic/tests/test_bumi3_sim2sim.py`：`11 passed`。
- `git diff --check`：通过。
- `validate_bumi3_sim2sim.py --skip-smoke`：通过；影子 `22` geoms、alpha `0.32`、physics false，静态参考 base/waist tilt `0°`。
- 真实 ONNX+参考 100-step validation：通过接口、顺序、影子 FK 和有限值检查；不把 2 秒后摔倒误报为动作质量通过。
- GUI passive viewer 实际启动 2 个控制步：通过，`viewer.user_scn` 影子写入和同步没有 API/runtime error；该短运行只验证渲染链路，不代表人工完成整段视觉验收。
- Ruff 未运行：当前 `env_isaaclab` 没有安装 `ruff`（`No module named ruff`），未为本轮擅自改变环境依赖。

### 6. 风险和回滚

- 当前只对本地已有两条 FineDance 50 Hz 轨迹做完整倾角统计；全库训练坐标门禁此前已通过 3162 对配对检查，但“动作语义是否合理”仍需选取代表性站立、爬行、跪地和翻滚片段人工观察红色影子。
- 影子只影响 GUI user scene；关闭方式为 CLI `--no-show-reference`，代码回滚范围仅是本节列出的 sim2sim、测试、验证和文档增量。训练进程未重启，影子修改不会改变正在运行的 Isaac Lab 训练。

## 2026-08-31：参考影子“散架”渲染修正

### 1. 问题现象与确认原因

- 用户实际截图显示红色参考机器人各 link 视觉上分离，并出现大量 capsule 形状；这不是指定参考脚本的显示效果。
- 第一个实现只建了独立 `MjData`，但仍复用已执行 `_apply_training_collision_contract()` 的动力学 `self.model`。该模型已把 base、左右 leg-roll 和左右 knee 的唯一 mesh geom 替换成训练 URDF capsule，因而不能用来画完整参考外观。
- 第一个实现还直接使用 `geom_xpos/geom_xmat` 和模型数组重建 marker，没有像参考脚本一样先调用 `mjv_updateScene` 获取渲染器已解析的 `MjvGeom`。
- 对照 `/home/weili/legged_lab/scripts/sim2sim_mimic_vision_4340.py` 后确认，参考实现的关键是独立 `ref_model + ref_data + ref_scene`，而不只是第二个 data。

### 2. 代码修改

- `gear_sonic/utils/mujoco_sim/bumi3_sim2sim.py`：从原始 BUMI3 MJCF 单独重新加载 `reference_visual_model`，不对它施加训练碰撞体或 armature 运行时覆盖；参考 FK、base/`waist_yaw_link` 姿态诊断和 anchor 四元数均改为使用该独立模型。
- `gear_sonic/utils/mujoco_sim/bumi3_sim2sim.py`：每帧调用 `mjv_updateScene(reference_visual_model, reference_visual_data, ...)`，只复制其中的 22 个 robot `MjvGeom`，不自行推断 mesh 姿态/尺寸。
- `gear_sonic/utils/mujoco_sim/bumi3_sim2sim.py`：写入 viewer scene 时复制 `type/pos/mat/size/rgba/dataid/matid` 及其他渲染字段，再单独设为 `mjCAT_DECOR`。不再调用会二次解释 capsule size 的 `mjv_initGeom`。
- 离屏像素检查又发现预分配 `MjvGeom.label` 未清空时会把随机字节渲染为字符；现已显式复制参考 label（当前为空字符串）。
- `gear_sonic/tests/test_bumi3_sim2sim.py`：回归测试改为与独立 `mjv_updateScene` 结果逐 geom 对比 `pos/mat/size/dataid/matid/label`；同时断言动力学 base 为 capsule、红色参考 base 仍为原始 mesh。
- `gear_sonic/tools/validate_bumi3_sim2sim.py`：新增独立 ref model、完整有限 marker 字段和 base mesh/capsule 隔离校验；输出明确标记 `render_source:independent_ref_model_mjv_updateScene`。
- `docs/source/getting_started/bumi3_sim2sim.md`：记录独立 ref model 与最终 `MjvGeom` 复制契约，说明为何不能复用已替换碰撞体的动力学 model。

### 3. 实际验证

- `/home/weili/miniconda3/envs/env_isaaclab/bin/python -m pytest -q gear_sonic/tests/test_bumi3_sim2sim.py`：`11 passed`。
- `/home/weili/miniconda3/envs/env_isaaclab/bin/python gear_sonic/tools/validate_bumi3_sim2sim.py --skip-smoke`：`PASS`；输出 `geoms:22` 且 `render_source:independent_ref_model_mjv_updateScene`。
- 使用真实 `model_step_070000_g1.onnx` + `finedance__001_50fps.pkl` 运行 100 个控制步，再用 MuJoCo EGL 离屏渲染同一 user-scene geom 复制链。修正后红色参考为完整、连通、直立的 22 个原始 mesh，无随机字符；白色机器人同时已倒地，root height 为 `0.0668425 m`。这个画面现在能正确区分“参考姿态”与“policy/部署闭环失败”。
- 此修改只影响 sim2sim 可视化，没有改动 ONNX 观测、控制、训练数据、奖励、termination 或服务器训练进程。

## 2026-08-31：纠正 sim2sim 碰撞来源为 BUMI3 XML

### 1. 用户纠正与最终契约

- 用户明确纠正：sim2sim 在 MuJoCo 内运行，碰撞必须使用 `bumi3.xml`，与 Isaac Lab URDF 无关。
- 本节取代本文档前面“sim2sim 在内存中复刻训练 URDF collision”的旧结论。旧结论是错误的，不再是当前代码行为。
- 最终白色 policy 机器人就是 `self.model/self.data`：MuJoCo 从 `bumi3.xml` 加载的同一组 geom 同时用于碰撞、动力学和渲染，不隐藏、不替换、不叠加 policy 可视代理。
- 红色参考从同一 `bumi3.xml` 单独加载 `ref_model/ref_data/ref_scene`，只用于持有参考 qpos 和绘制 decorative marker，不参与物理。
- Isaac Lab URDF 的 cylinder→capsule、禁用 collision link 等契约不再进入 sim2sim Python。如需改变 MuJoCo 碰撞，应显式修改并审核 XML。

### 2. 代码修改

- `gear_sonic/utils/mujoco_sim/bumi3_sim2sim.py`：删除 `BUMI3_URDF_DISABLED_COLLISION_BODIES`、`BUMI3_URDF_CAPSULE_COLLISIONS`、`_apply_training_collision_contract()` 及初始化调用。运行时不再改写 `geom_type/dataid/pos/quat/size/contype/conaffinity`。
- `gear_sonic/utils/mujoco_sim/bumi3_sim2sim.py`：撤销中途尝试的“隐藏动力学 geom + 用 user scene 额外绘制白色 policy mesh”方案。GUI 现在由 MuJoCo 直接渲染 XML 动力学模型，user scene 只包含红色参考。
- `gear_sonic/tests/test_bumi3_sim2sim.py`：用 `test_runtime_visual_and_collision_geoms_match_original_xml` 取代 URDF collision 测试。测试重新加载 XML，逐数组比较 `geom_type/bodyid/contype/conaffinity/condim/dataid/group/priority/pos/quat/size/friction/solref/solimp/margin/gap/rgba`，并断言 22 个 robot geom 均保留 XML mesh。
- `gear_sonic/tools/validate_bumi3_sim2sim.py`：删除 capsule/禁用 link 断言和白色可视代理断言，改为同样的 XML geom 数组指纹校验；输出 `collision_source:bumi3_xml` 和 `render_source:dynamics_bumi3_xml`。
- `gear_sonic/scripts/run_bumi3_sim2sim.py`：resolved 输出改为 `policy_visual_and_collision: direct_bumi3_xml_dynamics_model`。
- `docs/source/getting_started/bumi3_sim2sim.md`：删除“运行时复刻 URDF 碰撞”说明，明确 sim2sim 不读取、不复刻、不覆盖 URDF collision。

### 3. 实际验证和结果

- `/home/weili/miniconda3/envs/env_isaaclab/bin/python -m compileall -q gear_sonic`：通过。
- `/home/weili/miniconda3/envs/env_isaaclab/bin/python -m pytest -q gear_sonic/tests/test_bumi3_sim2sim.py`：`11 passed`。
- `/home/weili/miniconda3/envs/env_isaaclab/bin/python gear_sonic/tools/validate_bumi3_sim2sim.py --skip-smoke`：通过；22 个 policy geom 全部来自 XML，输出 `physics:true` 和 `collision_source:bumi3_xml`。
- 真实 `model_step_070000_g1.onnx` + `finedance__001_50fps.pkl` 100 控制步：接口/有限值/XML 碰撞指纹验证通过；2 秒后 policy root height 为 `0.084035 m`，仍然摔倒。
- MuJoCo EGL 离屏像素检查：白色 policy 是完整 XML mesh 且直接由动力学 scene 渲染；红色参考是完整 XML mesh 的 decorative 影子。画面不再出现 URDF capsule 代理。
- GUI 真实入口运行 5 个控制步并正常退出；X11 在程序结束后打印 `NV-GLX missing` 环境警告，本次命令退出码仍为 0，不把该警告当作 GPU GUI 稳定性证明。
- `git diff --check`：通过；搜索已确认 sim2sim 代码和文档中不再存在 `_apply_training_collision_contract`、`BUMI3_URDF_CAPSULE_COLLISIONS`、`training_urdf_runtime_override` 或 policy 可视代理路径。本轮未 commit/push，未改动服务器训练。

## 2026-09-01：2790 条 HQ4 PASS-only BUMI3 严格 50 Hz 数据准备（阶段一）

### 1. 起点、授权范围与保护措施

- 分支仍为 `feature/bumi-native-sonic-full-training`，起始 HEAD 仍为 `b1c3606ce96f00a01745cb8382f8bfa0b9b4d780`；工作区已有的大量用户修改全部保留，没有 reset、clean、stash、commit 或 push。
- 本轮数据源只使用服务器2的 `/data0/user/liwei/robot_retargeter_bumi3_hq4_zup_v1`；唯一白名单只接受质量报告 `/data0/user/liwei/datasets/bumi_quality_robot_retargeter_30hz_v1/quality_report.jsonl` 中同时满足 `status=PASS` 和 `quality_accepted=true` 的条目，数量必须恰好为 2790。REVIEW/REJECT 即使文件存在也不会进入输出。
- 4090 原目录在本阶段尚未替换；先构建独立数据集、全量验证和安全传输，最终只会通过保留时间戳备份的 rename/symlink 发布，保证可回滚。
- SSH 密码只用于本轮交互式认证，没有写入仓库、转换脚本、日志或数据 provenance。

### 2. 新增代码与目的

- 新增 `gear_sonic/tools/prepare_bumi3_pass50_dataset.py`：
  - 从质量报告建立严格、唯一、哈希锁定的 2790 条 PASS manifest；
  - 比较 retargeter MJCF 与本仓库 SONIC MJCF 的 22-body/21-joint 核心名称、树结构、body pose、joint origin/axis/range 和 actuator 顺序，不一致立即拒绝构建；
  - 采用 `arange(0,(T-1)/30,1/50)` 的独占末帧时间网格，把位置/关节位置线性插值到 50 Hz，把 wxyz body 四元数做最短弧 SLERP；
  - 从 50 Hz 结果重新计算 joint velocity/acceleration/jerk、body linear/angular velocity，并按双 `ankle_roll_link` 的低位与水平/垂直速度滞回重新计算接触；
  - 输出 SONIC 实际读取的 50 Hz robot PKL，同时把导数量和接触保存到独立 audit NPZ；PASS 原始 NPZ 只允许建立硬链接，跨文件系统或退化成复制会失败；
  - `pair-smpl` 不只要求同名、50 Hz 和严格同帧数，还复现训练的 SMPL Y-up→Z-up 与 base rotation removal，并比较 Robot `waist_yaw_link` 世界姿态。中位相对角超过 45 度的条目保留为 robot-only，避免把坐标语义异常配对送入 SMPL Encoder。
- 新增 `gear_sonic/tools/test_prepare_bumi3_pass50_dataset.py`：用合成的匀速平移/绕 Z 轴旋转动作覆盖完整 build/validate/pair 路径，验证 PASS-only、硬链接 inode、线性插值、SLERP、四元数范数、派生速度以及 SMPL 坐标配对门禁。

### 3. 服务器2真实构建结果

- 质量报告实际为 3154 行；严格白名单为 2790 条，组成：`aioz_gdance=1884`、`aistpp=750`、`finedance=88`、`compas3d=68`。
- retargeter MJCF SHA256 为 `fe93472dd764704fe8389b0f82052ae84ed8bc90f6d71b1467872f86e08a9ad3`，SONIC MJCF SHA256 为 `02874afebbe30ba1f90218394c8f9953f5d7a808e6b9950e7964c731da6dfbfe`；二者整体文件不同，但过滤 retargeter 辅助 marker 后，核心运动学门禁通过，核心 SHA256 为 `b65b51c4775a91658aa95e48eda220b3ff75b99451491b4ef175ce18d7d0bed2`。
- 发布目录：`/data0/user/liwei/datasets/sonic_bumi3_hq4_pass50_v1`。原始源帧总数 `3,043,605`，严格 50 Hz 目标总帧数 `5,069,508`；2790 条全部 finite，root quaternion 最大单位范数误差 `2.220446049250313e-16`。
- 左右脚平均接触占比分别为 `0.5534127` 和 `0.5653995`。PASS raw 硬链接目录表观大小约 3.4 GiB、robot PKL 约 1.1 GiB、audit NPZ 约 3.3 GiB、meta 约 4.2 MiB；抽样 inode 和全量 validator 都确认 raw 是原文件硬链接，不是复制。
- provenance 固定质量报告 SHA256 `d3bc24fb62600a71339625ef233bf0eb267d05296d45a3701a298d92b5cfb798`，并记录源/目标 MJCF 哈希、时间网格、插值方法、派生量和接触重算规则。

### 4. 阶段一实际验证

- `/home/weili/miniconda3/envs/env_isaaclab/bin/python -m pytest -q gear_sonic/tools/test_prepare_bumi3_pass50_dataset.py`：`3 passed`。
- `/home/weili/miniconda3/envs/env_isaaclab/bin/python -m compileall -q gear_sonic`：通过。
- `git diff --check`：通过。
- 服务器2构建内置全量验证：`BUMI3_PASS50_BUILD=PASS`，`robot_count=2790`，`total_target_frames=5069508`。
- 服务器2独立再次执行 full validate：`BUMI3_PASS50_VALIDATE=PASS`，逐条反序列化 2790 个 robot PKL，并逐条检查 2790 个 raw 硬链接和 2790 个 audit NPZ。

### 5. 仍待阶段二补录

- 4090 端训练子集传输、逐条 training-only 校验、SMPL key/frame/坐标语义配对、旧目录时间戳备份与替换、8 卡 scratch 启动及 TensorBoard 真实 event/首轮指标将在传输和运行验证结束后补录；在这些证据出现前不把训练写成“已成功重启”。

## 2026-09-01：2790 条 HQ4 PASS-only 发布、SMPL 配对与八卡重训（阶段二）

### 1. 传输、校验和发布

- 只把服务器2输出中的 `built/robot_all`（约 1.1 GiB）和 `meta`（约 4.2 MiB）传到 4090；3.4 GiB raw 硬链接和 3.3 GiB audit NPZ 留在服务器2，避免重复跨机传输。传输目标先使用 `/data/sonic_bumi3/datasets/.hq4_pass50_v1.transfer.20260901` staging。
- 最初在单流传输仍运行时过早执行了 validation，因只看到 24 个已落盘文件而产生预期的 `manifest.jsonl` missing。检查本地与两端 tar PID 后确认是校验竞态，不是 tar 已成功结束；没有发布不完整目录。随后按目标端实际文件大小生成缺失清单，用四个独立 SSH master 传输不重叠且总字节均衡的分片。
- 四个分片均返回 `MULTI_SHARD_0..3=PASS`。4090 端独立运行 training-only validator，逐条反序列化 2790 个 PKL，结果为 `BUMI3_PASS50_VALIDATE=PASS {"robot_count": 2790, "total_target_frames": 5069508}`。
- 独立发布目录为 `/data/sonic_bumi3/datasets/hq4_pass50_v1`。旧 `/data/sonic_bumi3/datasets/hq_all_v1/built/robot_all` 的 3261 条文件完整移动到 `/data/sonic_bumi3/datasets/hq_all_v1/built/robot_all.pre_hq4_pass50_20260901_110141`；原路径现为指向新 2790 条目录的符号链接。没有删除旧数据，回滚只需停止新训练、删除该符号链接并把备份目录改回 `robot_all`。

### 2. SMPL 严格配对结果

- 配对源仍为 `/data/sonic_bumi3/datasets/hq_all_v1/built/smpl_all`，新目录为 `/data/sonic_bumi3/datasets/hq4_pass50_v1/built/smpl_all`。通过项使用同文件系统硬链接，抽样确认源/目标 `st_dev + inode` 完全相同。
- 2790 条 Robot 中 2788 条通过 key、`fps=50`、三项 SMPL 字段严格同帧数以及 Robot-waist/processed-SMPL-root 中位相对角不超过 45 度的全部门禁；保留配对的中位角总体中位数 `16.112373°`，最大 `42.886849°`。
- 两条仅因坐标语义门禁降为 robot-only：`aistpp__gLO_sBM_cAll_d15_mLO5_ch04=48.422173°`、`aistpp__gWA_sBM_cAll_d27_mWA5_ch08=61.399928°`。训练代码对无 SMPL 配对的 Robot 动作使用既有零 SMPL fallback，没有删除这两条 PASS Robot 数据。
- 完整逐条结果保存在新数据集 `meta/smpl_pairing_report.jsonl`，汇总保存在 `meta/smpl_pairing_summary.json`。

### 3. Hydra resolved 配置与启动命令

- 实际 compose 输出保存为 `/data/sonic_bumi3/datasets/hq4_pass50_v1/meta/resolved_training_config.yaml`。解析确认：`checkpoint=null`、`resume=false`、`auto_load_latest=false`、`num_envs=4096/rank`、`num_learning_iterations=100000`、`target_fps=50`、`exclude_motion_keys=[]`、`sim_dt=0.005`、`decimation=4`，控制频率为 50 Hz。
- 新质量报告已重新验证机器人本体，因此旧 55 条 Robot/SMPL 异常清单不再作为 Robot 过滤器；其与新 2790 PASS 的交集为 11 条。启动时显式覆盖为空，保证 Robot 唯一白名单确实是 2790 PASS；SMPL 是否启用只由本轮新配对门禁决定。
- 八卡从头训练命令：

```bash
/root/miniconda3/envs/liwei_lab/bin/accelerate launch --num_processes=8 \
  gear_sonic/train_agent_trl.py \
  +exp=manager/universal_token/all_modes/sonic_bumi3 \
  +resume=false checkpoint=null auto_load_latest=false \
  use_wandb=false headless=True num_envs=4096 \
  base_dir=/data/sonic_bumi3/runs \
  exp_var=hq4_pass50_v1_scratch_100k \
  algo.config.num_learning_iterations=100000 \
  ++manager_env.commands.motion.motion_lib_cfg.motion_file=/data/sonic_bumi3/datasets/hq4_pass50_v1/built/robot_all \
  ++manager_env.commands.motion.motion_lib_cfg.smpl_motion_file=/data/sonic_bumi3/datasets/hq4_pass50_v1/built/smpl_all \
  ++manager_env.commands.motion.motion_lib_cfg.exclude_motion_keys=[]
```

- 训练 tmux：`sonic_bumi3_hq4_pass50_8gpu`；启动日志：`/data/sonic_bumi3/launch_logs/sonic_bumi3_hq4_pass50_8gpu_20260901_110307.log`；实验目录：`/data/sonic_bumi3/runs/TRL_BUMI3_Track/manager/universal_token/all_modes/sonic_bumi3_hq4_pass50_v1_scratch_100k-20260901_110314`。

### 4. 真实运行证据和当前边界

- 4090 `liwei_lab` 环境运行 `python -m pytest -q gear_sonic/tools/test_prepare_bumi3_pass50_dataset.py`：`3 passed`；本地 `env_isaaclab` 同一测试为 `3 passed`，本地 `compileall -q gear_sonic` 与 `git diff --check` 均通过。
- 8 个 rank 均打印 `Loaded 2790 motions` 和 `requested=0, matched=0, missing=0, remaining=2790`；运行时 Action Manager shape 为 `21`，policy observation 为 `690`，critic observation 为 `1245`。
- tokenizer 只有 `encoder_index`、Robot 两项输入和 SMPL 两项输入；运行时只初始化 `g1` 与 `smpl` encoder。FSQ 输出为 `64`（2 tokens × 32），没有 Teleop encoder/tokenizer/loss。
- 运行时 physics step `0.005 s`、environment step `0.02 s`；奖励表确认 `feet_acc=-2.5e-6`、`torque_limits=-0.01`，termination 表确认 `ee_body_pos`、`foot_pos_xyz` 是两个独立项。
- TensorBoard event 已真实生成并解析：`tensorboard/events.out.tfevents.1788231887.noetix.3236527.0`，含 122 个 scalar tags。step 1→51：reward `0.61743→0.57356`、mean length `10.97→10.326`、value loss `0.08377→0.01805`；step 51 吞吐约 `239275 steps/s`。早期 reward/length 尚未改善，必须继续观察而不能把训练链路正常等同于策略已开始收敛。
- 检查时 8 张 RTX 4090 显存约 `19.9–20.3 GiB`，利用率约 `85%–90%`；日志未发现 traceback、AssertionError、RuntimeError、CUDA OOM、NCCL 或 NaN。已有 headless Vulkan/renderer 报错与该服务器此前多卡训练相同，所有 rank 在这些日志后继续完成场景、MotionLib、网络、DDP 和 PPO iteration。
- 这些 51 个 iteration 只证明数据加载、Isaac 环境、双 Encoder、PPO、TensorBoard 和八卡计算链路工作；随机初始化早期 termination 仍高，不能据此宣称动作已收敛或 sim2sim 不再摔倒，后续必须持续看 length/reward/termination 曲线并用新 checkpoint 做参考影子 sim2sim。

### 5. TensorBoard 服务和查看方式

- 服务器原 6006 端口已有其他 TensorBoard，未终止或覆盖用户进程。本实验单独在 tmux `tensorboard_bumi3_hq4_pass50` 的 `127.0.0.1:6016` 运行 TensorBoard 2.20.0。
- 本地端口转发：`ssh -N -L 6016:127.0.0.1:6016 noetix-volc`，浏览器打开 `http://127.0.0.1:6016/`。
- 训练查看：`ssh noetix-volc -t 'tmux attach -t sonic_bumi3_hq4_pass50_8gpu'`；脱离 tmux 使用 `Ctrl-b` 后按 `d`。

## 2026-09-01：补充 Git 中文提交说明与 SONIC 训练服务器约束

### 1. 修改范围与理由

- 所属分支：`feature/bumi-native-sonic-full-training`；起始 HEAD：
  `b1c3606ce96f00a01745cb8382f8bfa0b9b4d780`；修改前与上游 ahead `0`、behind `0`。
- `agent.md`：把原有“推荐提交消息”规则收紧为 Git 提交标题和正文必须使用详细中文说明，
  并要求明确写出具体改动、修改理由、影响边界、实际验证、未执行项及原因，避免模糊或仅列
  文件名的提交记录。
- `agent.md`：新增 SONIC 训练服务器章节，固定使用 SSH Host 别名 `noetix-volc`，并记录
  用户指定的 HostName、用户、端口、IdentityFile、IdentitiesOnly 和 keepalive 参数。
- 修改理由：保证 Git 历史可由中文直接审计，并避免后续 SONIC 训练误连其他服务器。

### 2. 兼容性、验证与回滚

- 本轮只修改规则文档和本记录，没有修改训练代码、配置、数据、模型或服务器状态；没有连接
  `noetix-volc`，也没有执行 commit、push、merge、rebase、stash、reset 或训练操作。
- 实际验证：使用文本检索核对新增规则和 7 项 SSH 配置字段，并执行 `git diff --check`。
- 未运行代码测试：本轮没有代码行为变化，单元测试、仿真和训练均不适用。
- 风险：SSH 配置中的私钥路径要求执行环境已有 `~/.ssh/noetix-8.pem` 且权限正确；本轮未验证
  密钥存在性或远端可达性。
- 回滚：只需删除 `agent.md` 的对应规则增量和本节记录；不得影响同文件内其他已有未提交内容。

## 2026-09-01：补充代码注释必须使用详细中文的约束

### 1. 修改内容与理由

- 所属分支：`feature/bumi-native-sonic-full-training`；起始 HEAD：
  `b1c3606ce96f00a01745cb8382f8bfa0b9b4d780`。
- `agent.md`：新增强制规则，要求新增、改写及受当次代码修改影响的注释全部使用详细中文，
  并准确说明代码目的、关键逻辑、输入输出、边界条件或必要的设计理由。
- 同时禁止新增仅复述代码字面行为、含义模糊或只有英文的注释；未涉及的历史注释不进行批量
  改写，避免把无关格式变化混入功能修改。
- 修改理由：让后续代码的关键意图和约束可以直接用中文审查、维护与追溯。

### 2. 验证、影响与回滚

- 本轮只修改规则文档和本记录，没有修改任何运行代码、训练配置、数据、模型或服务器状态；
  没有执行 commit、push、远程连接或训练操作。
- 实际验证：文本检索确认规则已写入 `agent.md`，并执行 `git diff --check`。
- 未运行代码测试：本轮没有代码行为变化，单元测试、仿真和训练均不适用。
- 回滚：删除 `agent.md` 第 6 条规则及本节记录即可，不应改动同文件内其他已有内容。

## 2026-09-01：修正 Robot Encoder 的 BUMI3 waist 锚点姿态语义

### 1. 现象、根因与修正边界

- 所属分支：`feature/bumi-native-sonic-full-training`；起始 HEAD：
  `b1c3606ce96f00a01745cb8382f8bfa0b9b4d780`；修改前与上游 ahead `0`、behind `0`。
- 工作区已有 BUMI3 资产、数据处理、sim2sim 和训练调整等未提交改动；本轮仅编辑
  锚点调用链、对应回归测试及本记录，没有 reset、stash、clean 或覆盖其他现有改动。
- `sonic_bumi3.yaml` 虽然已将 `anchor_body` 配成 `waist_yaw_link`，但 Robot Encoder 的姿态
  输入实际经过 `motion_anchor_ori_b_mf_nonflat -> root_rot_dif_l_multi_future`，
  原实现在参考侧直接调用 `MotionLib.get_root_quat_w()`，得到的是第 0 个刚体
  `base_link` 的浮动根四元数；仿真侧则使用 `robot_anchor_quat_w`，即
  `waist_yaw_link`。因此原始计算实际是
  `inverse(sim_waist) * reference_base`，当 `waist_yaw_joint` 非零时两侧刚体语义不一致。
- 本记录早期第 886 行曾误写“参考 quaternion 已来自
  `motion_anchor_body_index`”；该结论是根据配置和辅助属性做的错误推断，没有跟到
  `root_rot_dif_l_multi_future` 末端实现。本节的生产代码差异和回归测试证据取代
  那条旧记录，不再把原始状态说成已修正。
- 本修正不改网络层、token 数、观测维度、控制频率、奖励、PPO 或数据，只把
  Robot Encoder 的参考姿态改为与仿真侧同名的 `waist_yaw_link` FK 姿态。

### 2. 文件级修改

- `gear_sonic/envs/manager_env/mdp/commands.py`：
  - `root_rot_dif_l` 从 `get_root_quat_w(...)` 改为读取 `self.anchor_quat_w`；
  - `root_rot_dif_l_multi_future` 从多未来帧根四元数改为读取
    `self.anchor_quat_w_multi_future`，并恢复为 `[num_envs, num_future_frames, 4]`；
  - 修正后单帧和 Robot Encoder 实际使用的多未来帧均计算
    `inverse(sim_waist) * reference_waist`；
  - 保留 `root_rot_dif_*` 属性名以兼容旧配置，只修正其内部语义；新增中文注释
    明确 BUMI3 禁止把 `base_link` 根姿态代替 `waist_yaw_link` 的 FK 姿态。
- `gear_sonic/tests/test_tracking_anchor_semantics.py`：新增不需启动 Isaac Sim 的 AST 契约测试，
  锁定单帧和多未来帧实现必须读取命名 anchor，且不得重新调用
  `get_root_quat_w`。文件开头已详细说明 BUMI3 `base_link`/`waist_yaw_link` 差异和
  采用 AST 的原因。
- sim2sim 生产代码本轮无需再改：
  `gear_sonic/utils/mujoco_sim/bumi3_sim2sim.py` 已使用 `bumi3.xml` 独立 FK 每帧
  `waist_yaw_link` 的参考世界姿态，且用当前 policy robot 的同名 waist 姿态求相对旋转；
  `gear_sonic/config/sim2sim/bumi3_sonic.yaml` 中 `anchor_body_name` 也已是
  `waist_yaw_link`。

### 3. 兼容性与 checkpoint 影响

- G1 的配置 anchor 与其根刚体语义等价，所以返回数值不变；H2 和其他机器人从此也统一
  遵循各自配置的 `anchor_body`，旧的配置键和观测属性名没有变化。
- 当前正在服务器上运行的训练进程以及已生成 checkpoint 不会自动获得本地修正；
  其 Robot Encoder 已经按旧的 base/waist 混合语义训练。要评估这个修正，必须将当前
  代码同步到 4090 服务器后从头训练；本轮没有连接服务器、停止训练或启动新任务。
- 维度契约保持不变：`sim_dt=0.005`、`decimation=4`、控制/target FPS `50 Hz`、
  `action_dim=21`、FSQ 总维度 `64`、actor proprioception `690`、dynamic decoder
  `754 -> 21`。

### 4. 实际验证和未执行项

- 首次尝试在普通 `pytest` 中直接导入 `TrackingCommand` 做行为测试，收集阶段因未启动
  Isaac Sim `SimulationApp` 而报 `ModuleNotFoundError: No module named 'pxr'`。这是测试运行环境
  限制，不是锚点逻辑断言失败；因此把新测试改为可在普通 Python 中运行的 AST
  契约检查。
- `/home/weili/miniconda3/envs/env_isaaclab/bin/python -m pytest -q
  gear_sonic/tests/test_tracking_anchor_semantics.py`：`2 passed in 0.06s`。
- `/home/weili/miniconda3/envs/env_isaaclab/bin/python -m pytest -q
  gear_sonic/tests/test_bumi3_sim2sim.py`：`11 passed in 2.52s`；其中现有数值测试会将
  `waist_yaw_joint` 设为 `0.4 rad`，验证 sim2sim Robot Encoder 参考姿态来自 waist FK，
  而非 identity root quaternion。
- `/home/weili/miniconda3/envs/env_isaaclab/bin/python -m compileall -q
  gear_sonic/envs/manager_env/mdp/commands.py gear_sonic/tests/test_tracking_anchor_semantics.py`：通过。
- `/home/weili/miniconda3/envs/env_isaaclab/bin/python
  gear_sonic/tools/validate_bumi3_integration.py`：通过，输出 `BUMI3 原生 SONIC 集成验证通过`，
  并确认 21 DoF、22 bodies、上述频率和网络维度契约均未变。
- 未执行 1-env Isaac Lab reset/step：当前本地 BUMI3 训练数据路径为 `null`/由 CLI 指定，
  validation 脚本明确输出 `smoke: 未请求（需显式提供现有 BUMI3/SMPL 数据）`；本轮不把未运行
  的仿真 smoke 写为通过。
- 本轮没有 commit、push、merge、rebase、stash、reset，也没有修改远程数据或训练进程。

### 5. 回滚方式

- 如需回滚本轮锚点修正，只恢复 `commands.py` 中两个 `root_rot_dif_l*` 属性的原实现，
  删除 `test_tracking_anchor_semantics.py` 和本节记录即可；不得回滚或覆盖工作区中其他
  BUMI3 资产、数据、配置、sim2sim 和训练改动。

## 2026-09-01：强制中文注释与修改后 GitHub/训练服务器同步闭环

### 1. 用户规则与文件修改

- 所属分支：`feature/bumi-native-sonic-full-training`；起始 HEAD：
  `b1c3606ce96f00a01745cb8382f8bfa0b9b4d780`；修改前本地与上游 ahead `0`、behind `0`。
- `agent.md` 将代码注释规则明确扩展到行内注释、块注释、docstring 和 TODO；说明
  标识符、API 名和必要专有名词可保留原文，但解释句必须使用完整中文，不得
  新增只有英文或没有中文语义的注释。
- `agent.md` 记录用户对当前开发分支的持续非破坏性授权：每次修改完成后，必须
  更新记录、验证、逐文件暂存、使用详细中文提交、推送 GitHub，并在
  `noetix-volc` 同分支执行 `git pull --ff-only`。该授权不包含 merge、rebase、Tag、
  删分支、force push 或改写历史。
- 闭环规则显式保留安全边界：如果本地或服务器有用户独立未提交修改、分支不一致、
  非快进历史或网络故障，必须保留现场并报告，禁止通过 stash、reset、force push
  或自行合并来强行完成。

### 2. 服务器同步前的只读核对

- 已通过 SSH Host `noetix-volc` 连接，服务器仓库为
  `/home/liwei/GR00T-WholeBodyControl`，分支为
  `feature/bumi-native-sonic-full-training`，HEAD 同样为
  `b1c3606ce96f00a01745cb8382f8bfa0b9b4d780`。
- 服务器仓库所有者不是 SSH 的 `root` 用户，Git 报 `dubious ownership`。本轮不修改全局
  Git 配置，远端检查与同步命令只使用单次参数
  `-c safe.directory=/home/liwei/GR00T-WholeBodyControl`。
- 服务器存在 8 个已跟踪改动和 3 个未跟踪数据工具文件。逐文件 SHA256 核对后，
  10 个代码/配置/测试文件与本地完全相同；服务器的
  `BUMI3_SONIC_修改记录.md` 为本地记录前 `107075` 字节的严格字节前缀，
  无服务器独有后缀。这些文件是之前部署但未提交的同一批改动，不是新的服务器分叉。
- 正式同步时必须在 GitHub 推送后再根据远端目标 commit 复核所有这些路径；只有确认
  工作树内容已完整包含在目标 commit 中、没有独有修改后，才可清除重复工作树状态
  并执行快进拉取。

### 3. 本地验证结果

- `/home/weili/miniconda3/envs/env_isaaclab/bin/python -m compileall -q gear_sonic`：通过。
- 下列四组测试合并运行：`24 passed in 3.92s`；存在 1 条历史
  `DeprecationWarning: invalid escape sequence '\\*'`，未造成测试失败。
  - `gear_sonic/tools/test_prepare_bumi3_sonic_dataset.py`；
  - `gear_sonic/tools/test_prepare_bumi3_pass50_dataset.py`；
  - `gear_sonic/tests/test_bumi3_sim2sim.py`；
  - `gear_sonic/tests/test_tracking_anchor_semantics.py`。
- `/home/weili/miniconda3/envs/env_isaaclab/bin/python gear_sonic/tools/validate_bumi3_integration.py`：
  通过，输出 `BUMI3 原生 SONIC 集成验证通过`；实测为 21 DoF、22 bodies、
  `sim_dt=0.005`、`decimation=4`、控制/target FPS `50 Hz`、`action_dim=21`、
  FSQ `64`、actor proprioception `690`、dynamic decoder `754 -> 21`。
- integration validation 启动 Isaac Sim 时输出了已知的 CPU topology、powersave、IOMMU 和
  deprecated extension 警告，但进程退出码为 `0`并完成全部静态/Hydra 契约验证。
- validation 中 1-env smoke 仍显式未请求，原因是本地没有通过 CLI 提供现有
  BUMI3/SMPL 数据目录；本轮不把它记为已通过。

### 4. 待本轮操作完成后补录

- 当前累积 BUMI3 原生 SONIC、数据准备、训练坐标校验、sim2sim、waist 锚点修正、
  规则与详细记录将逐文件暂存，使用详细中文提交并推送 GitHub；实际 commit SHA、
  push 结果、服务器重复改动处置和 `git pull --ff-only` 证据将在操作完成后另行补录。

### 5. 实际提交、GitHub 推送和服务器快进结果

- 本地逐文件暂存了 21 个已核对的源码、配置、URDF、测试和 Markdown 文件；
  没有暂存 checkpoint、ONNX、PKL、NPZ、CSV、视频、日志、缓存或训练输出。
  `git diff --cached --check` 通过，staged stat 为 `21 files changed, 5864 insertions(+),
  64 deletions(-)`。
- 主提交 SHA 为 `c287ac97808dfe0511ed00b875e6fbcfc3313499`，中文标题为
  `feat: 完成 BUMI3 原生 SONIC 训练与 sim2sim 闭环`。提交正文详细记录了数据、训练、
  sim2sim、waist 锚点、兼容边界、实际验证和未执行 1-env smoke 的原因。
- `git push origin feature/bumi-native-sonic-full-training` 成功，GitHub 远端由
  `b1c3606` 快进到 `c287ac9`，没有 force push 或历史改写。
- GitHub 推送后，服务器执行 `git fetch` 并确认目标 ref 精确为
  `c287ac97808dfe0511ed00b875e6fbcfc3313499`。10 个重复代码/配置/测试文件再次与
  目标 commit 逐字节 SHA256 一致，服务器记录再次通过目标记录严格前缀检查。
- 为使三个已被目标 commit 完整包含的未跟踪数据工具可恢复，先将它们移动到
  `/tmp/bumi3_git_sync_backup.FqkxYc`；已跟踪重复改动只在确认目标 commit 已保存同样内容后
  恢复到旧 HEAD，随后执行非破坏性快进拉取。拉取后三个新文件与备份逐字节
  `cmp` 通过，因此没有丢失服务器内容。
- 服务器实际执行
  `git -c safe.directory=/home/liwei/GR00T-WholeBodyControl pull --ff-only origin
  feature/bumi-native-sonic-full-training`，结果为 `Updating b1c3606..c287ac9` 和
  `Fast-forward`。执行后分支正确、HEAD 为 `c287ac9`、`git status --short` 无输出，
  `SYNC_VERIFY=PASS`。
- 本次只完成代码 Git 同步，没有停止、重启或恢复服务器上已运行的训练进程。
  旧进程已加载的 Python 模块不会因工作树 `git pull` 自动替换；如要让新的
  `waist_yaw_link` 训练锚点生效，仍需用新代码从头启动新训练。

## 2026-09-01：修复 noetix-volc 的 Git 目录信任并统一分支跟踪

### 1. 问题含义和根因

- 所属分支：`feature/bumi-native-sonic-full-training`；起始 HEAD：
  `5d97f452751fbe5645929af9bb57e7b92e6a00bf`；本地工作区干净，与上游 ahead `0`、behind `0`。
- “服务器仓库非 root 用户所有”并不表示没有关联 GitHub。服务器目录
  `/home/liwei/GR00T-WholeBodyControl` 的顶层所有者是数值 UID/GID `14000032`，
  当前系统没有该 UID 的用户名映射，因此 `stat` 显示 `owner=UNKNOWN`；`.git` 目录本身
  属于 root。root 访问顶层所有者不同的仓库时，Git 按安全策略报
  `detected dubious ownership`。
- 服务器在修复前已存在正确 GitHub 远端：`origin` 的 fetch/push URL 均为
  `git@github.com:XiaoxiaoKuankuan/GR00T-WholeBodyControl.git`；服务器并非未关联仓库。

### 2. 实际修复和分支统一

- 在服务器 root 的全局 Git 配置中精确新增：
  `safe.directory=/home/liwei/GR00T-WholeBodyControl`。没有设置通配符，没有把其他目录
  加入信任范围，也没有 chown 整个仓库。修复后 root 可以直接运行普通 `git` 命令，
  不再需要每次传入 `-c safe.directory=...`。
- 本地和服务器均显式执行了
  `git branch --set-upstream-to=origin/feature/bumi-native-sonic-full-training
  feature/bumi-native-sonic-full-training`。两端当前分支、upstream 和 GitHub ref 现在一致：
  - 当前分支：`feature/bumi-native-sonic-full-training`；
  - upstream：`origin/feature/bumi-native-sonic-full-training`；
  - 本地、GitHub、服务器核对时 HEAD：
    `5d97f452751fbe5645929af9bb57e7b92e6a00bf`；
  - 两端 ahead/behind：`0/0`；
  - 两端 `git status --short`：无输出。

### 3. 端到端验证和影响边界

- 本地实际执行普通 `git push --dry-run`，结果为 `Everything up-to-date`，证明当前本地
  分支可以通过 `origin` SSH URL 访问 GitHub 并使用正确的默认推送目标。
- 服务器在不传 `-c safe.directory`、不指定远端和分支的情况下，实际执行普通
  `git pull --ff-only`，结果为 `Already up to date.`，证明 root 目录信任、GitHub SSH
  访问、origin 和 upstream 全部有效。
- 本轮修改的是服务器 root Git 配置、两端分支跟踪关系和本记录；没有修改
  SONIC 源码、训练配置、数据、checkpoint 或运行中的训练进程，因此代码单元测试和仿真
  不适用。
- 回滚服务器信任配置时，只需精确删除 root Git config 中这一条
  `safe.directory=/home/liwei/GR00T-WholeBodyControl`；但删除后 root 会再次遇到 ownership 安全拦截。

## 2026-09-01：实现 BUMI3 SONIC 三数据源只读索引与可选尾帧对齐

### 1. 修改起点、授权范围和数据来源

- 所属分支：`feature/bumi-native-sonic-full-training`；起始 HEAD：
  `4efe77e2bee5fd2752376e59e302761d688b32c2`。修改前本地与
  `origin/feature/bumi-native-sonic-full-training` 的 ahead/behind 为 `0/0`，
  `git status --short` 无输出。
- 用户明确要求实现三数据源联合训练方案、提交并推送当前 feature 分支，再让
  `noetix-volc` 同分支执行 `git pull --ff-only`。本轮不获得停止或覆盖现有 hq4
  八卡训练的授权，因此只读核对其进程，不改变 PID、tmux、日志、checkpoint 或运行目录。
- 服务器只读核对确认新索引目标
  `/data/sonic_bumi3/datasets/bumi3_sonic_three_source_v1` 尚不存在，2 TB 数据盘
  约剩余 1.9 TB；三项实际来源路径为：
  - `/data/sonic_bumi3/datasets/bumi3_smpl_97660_v1`；
  - `/data/sonic_bumi3/datasets/hq4_pass50_v1`；
  - `/data/sonic_bumi3/datasets/hq_all_v2/built/robot_all` 中精确的 `mine__*`。
- 服务器构建前仍在运行 8 个训练 worker，启动参数指向旧 hq4 PASS50 数据和独立
  `hq4_pass50_v1_scratch_100k` 实验。本轮提交和后续快进不会替换已经载入进程内存的
  Python 代码，也不会自动重启该任务。

### 2. MotionLib 尾帧和随机截段修正

- `gear_sonic/utils/motion_lib/motion_lib_base.py` 新增
  `resolve_paired_frame_alignment`：
  - 默认 `strict` 保留 G1/H2 的严格行为；同为目标帧率时，在统一切片前要求已有
    SMPL 时间字段与 Robot 原始长度完全一致，不能把较长 SMPL 静默裁短；
  - 可选 `trim_trailing` 只接受 Robot/SMPL 都已经是目标帧率、
    `pose_aa/smpl_joints/transl` 内部长度一致且尾差不超过配置上限的配对；
  - 返回两侧共同的较短长度，只裁末尾，不重复帧、不插值、不改变起始时间；非法模式、
    布尔型/负数上限、错帧率、缺字段、内部错长或超过上限均在 FK 前失败。
- 同名 SMPL 现在先于 Robot 随机截段载入。Robot 和 50 Hz SMPL 共用同一
  `[start:end]`，修复旧实现在 `max_len` 随机截取 Robot 后仍把整段 SMPL 输入网络的
  时间错位；`pose_aa`、`smpl_joints`、`transl` 三个字段使用相同窗口。
- freeze-frame augmentation 继续使用同一 Robot 源帧索引换算到目标帧率，并同步冻结
  三个 SMPL 字段。Robot-only 动作保持 `curr_smpl_data=None`，不会进入配对对齐逻辑。
- BUMI3 `sonic_bumi3.yaml` 显式启用 `mode=trim_trailing`、
  `max_frame_delta=2`。因此 50 Hz 大集可裁 0–2 个尾帧，30 Hz Mine Robot-only 仍由
  既有 Robot FK 插值到 50 Hz；若未来误把 30 Hz Robot 和 SMPL 配在一起会立即失败，
  不会用该开关掩盖帧率契约错误。

### 3. 三来源全量构建与审计工具

- 新增 `gear_sonic/tools/build_bumi3_three_source_dataset.py`，文件头以中文详细说明
  输入、字段级坐标契约、降级边界、原子发布和验证能力。工具默认锁定计划中的来源
  计数：大集 train `92443`、test `5217`，hq4 Robot `2790`、SMPL `2788`，
  Mine `99`。
- 发现阶段递归建立 basename 唯一索引，要求大集 train/test 完整配对、hq4 SMPL 是
  Robot 子集、三训练来源 key 不冲突、train/test 不交叉。整个 `hq_all_v2` 不进入索引，
  只接受精确 `mine__` 前缀，避免和 hq4 PASS50 重复训练。
- 每条 Robot 全量检查外层 key、必要字段、有限值、50/30 Hz 来源契约、
  `(T,22,3)` pose、`(T,21)` DoF、`(T,4)` root、四元数单位范数和 xyzw 顺序；
  还统计根倾角和 Z 高度，以来源级中位数/横躺帧比例阻止系统性错误坐标。
- 每条 SMPL 全量检查 `pose_aa/transl/smpl_joints/fps`、50 Hz、有限值和内部长度，
  并根据 24 个关节的 XYZ extent 判断 `smpl_joints` 是否以 Z 为人体主轴。
  `pose_aa/transl` 仍按 Y-up 源字段处理，不对整份 PKL 做错误的统一旋转。
- 同名配对复现 SONIC 的 SMPL Y-up 到 Z-up 左乘、SMPL base rotation removal，
  并用 BUMI3 `pose_aa` 的 index 1 计算 `waist_yaw_link` 世界姿态；对全部共同帧计算
  waist/SMPL 根姿态中位差。帧差超过 2、SMPL 契约错误或中位差超过 45 度时，
  只把该 SMPL 降级为 Robot-only；Robot 不合格则整次构建失败。
- 每个实际发布的源文件均写入 SHA256。输出先在目标同级唯一 staging 目录构建，
  只创建绝对软链接，不复制、不重写、不重采样源 PKL；同时生成 train/test JSONL
  manifest、`summary.json` 和 `provenance.json`，结构验证通过后才用 `os.replace`
  原子发布。目标已存在时拒绝覆盖，失败时只清理本工具创建的 staging 目录。
- `validate` 子命令验证清单、软链接目标、计数、配对状态和 train/test 隔离；正式模式
  重新计算全部源 SHA256，`--skip-hash-verification` 仅允许调试结构。
- 配置删除旧 `hq_all_v2` 的 55 条静态 key 清单，设为 `exclude_motion_keys: []`。
  新三源构建根据当前全量数据重新决定配对状态，避免用旧名单误删同名新数据。
- `validate_bumi3_training_coordinates.py` 继续作为旧 hq_all_v2 的历史审计工具：新配置
  清单为空时仍要求从旧目录独立检出恰好 55 条；若未来传入非空完整清单，则继续要求
  检测集合和配置完全相同。它不再把旧 55 条描述为新三源训练的活跃隔离名单。

### 4. 新增测试与兼容性门禁

- `gear_sonic/tools/test_bumi3_paired_frame_alignment.py` 覆盖 strict 默认值、同帧率
  strict 错长拒绝、0/1/2 帧双方向裁剪、超过两帧拒绝、帧率错误、缺字段、字段内部
  错长和非法配置。测试还用轻量假 FK 真正执行 `load_motion_with_skeleton`，验证随机
  截段和 freeze-frame 后 Robot/SMPL 四项时间数据逐帧一致。
- `gear_sonic/tools/test_build_bumi3_three_source_dataset.py` 构造缩小的三来源数据，
  验证 2 帧尾差配对、hq4/Mine Robot-only、旧公开动作不重新进入索引、自然按动作数
  采样、train/test 隔离、绝对软链接和 SHA256 复核。
- `validate_bumi3_integration.py` 将 resolved 配置门禁更新为：活跃隔离列表为空，
  `paired_frame_alignment` 必须精确为 `trim_trailing/2`；G1 `sonic_release`、H2 compose、
  网络层、FSQ、token、PPO、奖励和控制参数的原有校验保持不变。

### 5. 本地实际验证结果

- `/home/weili/miniconda3/envs/env_isaaclab/bin/python -m pytest -q` 后接本轮两个新测试、
  两个 BUMI3 数据准备测试、`test_bumi3_sim2sim.py` 和
  `test_tracking_anchor_semantics.py`：`36 passed in 3.92s`；仅有 1 条已有
  `DeprecationWarning: invalid escape sequence '\\*'`，未造成失败。
- `/home/weili/miniconda3/envs/env_isaaclab/bin/python -m compileall -q gear_sonic`：通过。
- `/home/weili/miniconda3/envs/env_isaaclab/bin/python
  gear_sonic/tools/validate_bumi3_integration.py`：退出码 `0`，输出
  `BUMI3 原生 SONIC 集成验证通过`；同时完成 G1/H2/BUMI3 Hydra compose 和 Isaac Sim
  动态机器人配置导入。实测 resolved 数值为 `sim_dt=0.005`、`decimation=4`、控制频率
  `50 Hz`、`target_fps=50`、`action_dim=21`、FSQ 总维度 `64`、actor proprioception
  `690`、tokenizer flat `1262`、critic `1245`、dynamic decoder `754 -> 21`。
- `git diff --check`：通过。
- 尝试运行当前 `env_isaaclab` 内的 Black/Ruff，两个模块均未安装，因此没有把格式检查
  写成通过；新增文件人工限制在 Black 100 字符行宽，语法和 compileall 已通过。

### 6. 尚未执行项、风险与回滚

- 首次代码提交前尚未在服务器执行 100,431 条 train/test 全量数据审计、索引发布和
  第二次全量哈希复核；这些操作必须先让服务器快进到包含本工具的提交，实际结果会在
  后续记录中补录，当前不能写成通过。
- 本地没有三来源真实数据，所以尚未运行 MotionLib 三源真实加载、1-env reset/step、
  16-env 100-step 或 8 卡 100-iteration smoke。服务器 8 张 GPU 正被用户要求保留的
  hq4 正式训练占用；不会为了 smoke 停止该任务，最终会明确记录能执行和不能执行的层级。
- 全量 SHA256 会产生明显磁盘读取；绝对软链接节省容量但依赖三个源目录保持原路径。
  后续 `validate` 会在源文件内容或链接目标漂移时失败。
- 本轮没有修改 PPO、网络主体、奖励、事件、终止、机器人资产、关节顺序、
  `sim_dt`、`decimation` 或控制频率。回滚代码时应同时恢复 MotionLib 对齐函数、
  BUMI3 两项配置、两个新测试、构建工具及两个验证脚本的对应门禁；发布的数据索引
  只是源文件软链接，可在确认没有训练使用后单独处理，但不得删除或重写三个源目录。

### 7. 首次服务器全量审计、SHA 复核和历史审计结果

- 提交 `851eda706649ec8296736bbfc654668d6b2b00be` 已推送 GitHub；服务器仓库在
  同一 feature 分支、工作区干净的前提下由 `4efe77e` 执行普通
  `git pull --ff-only`，正常 fast-forward 到 `851eda7`。两端均未执行 force push、
  merge、rebase、stash、reset 或 clean。
- 服务器 `liwei_lab` 同步后执行和本地相同的 6 组相关测试：
  `36 passed in 6.62s`；`compileall -q gear_sonic` 与 `git diff --check` 通过。
- 在独立 tmux `bumi3_three_source_build` 执行全量 build。发现记录数精确为
  `100549 = 95332 train + 5217 test`，逐条审计完成后原子发布到用户指定目录；
  构建内结构验证输出 `BUMI3_THREE_SOURCE_VALIDATE=PASS`。
- 首次真实汇总不是计划前的估计值：train Robot `95332` 全部通过；可配对 SMPL
  `95132`，Robot-only `200`。其中预期无 SMPL 为 hq4 `2` 加 Mine `99`，另有
  大集 train `99` 条 waist/SMPL 根姿态中位差超过 45 度而降级。它们的帧差为
  `0:44`、`-1:50`、`-2:5`，所以不是尾帧裁剪制造的异常；角差范围约
  `45.0421°` 至 `177.3349°`。hq4 的 2788 条配对全部通过，test 的 5217 条
  全部通过。
- 自然按动作条数的实测来源概率为：大集 `0.96969538035497`、hq4
  `0.029266143582427726`、Mine `0.0010384760626022743`，没有增加来源权重。
- 来源级坐标实测：Robot 根倾角 clip 中位数分别约为大集 train `6.0823°`、
  test `6.0210°`、hq4 `8.2705°`、Mine `5.6613°`；各含 SMPL 来源的
  `smpl_joints` 人体主轴均为 Z。通过配对的根姿态中位差数据集内中位数为
  大集 train `9.6749°`、test `8.8959°`、hq4 `16.1124°`。
- 在独立 tmux `bumi3_three_source_hash` 调用不带跳过参数的正式 `validate`，
  第二遍重新计算 `100549/100549` 个 Robot/test manifest 条目的源 SHA256；输出
  `BUMI3_THREE_SOURCE_VALIDATE=PASS`。该结果证明发布后的链接、清单、第一次记录
  的哈希和第二次独立读取一致。
- 更新后的旧数据历史工具对 `hq_all_v2` 全量 3162 对运行，输出
  `BUMI3_TRAINING_COORDINATES=PASS`：仍独立检出 55 条历史异常，活跃配置隔离数为 0，
  正常保留集合中位角 `13.636874°`、最大 `44.710664°`，历史异常最小
  `45.181285°`。这证明清空新配置静态名单没有破坏旧数据审计能力。

### 8. 数据资产/关节顺序门禁补强及原因

- 服务器当前 `/home/liwei/legged_lab` 并不是本集成锁定的参考快照：其 `bumi.py`
  SHA256 为 `41e39f9c...5037`，手臂 velocity limit 已由 12 改为 30；其
  `bumi3.xml` SHA256 为 `8639f0da...580`，waist 轴为 `-Z` 且 arm-roll 限位不同。
  本地用户明确指定的 `/home/weili/legged_lab` 对应 SHA 仍是验证器锁定的
  `74aaeca9...03e`、`041c81e8...edf`。本轮没有修改任何 legged_lab 文件。
- 大集自身归档了 `/meta/bumi3.source.xml`，SHA256 为
  `db4f51fc64030a99a69f0592852c4436e5495eebf8941f89c727a1410a20c1a4`；其报告明确
  记录 DoF/body 双重重排和 waist_yaw 取反。程序化解析确认它使用 waist `+Z`、
  正确 arm-roll 限位，并与当前 SONIC MJCF 的 21 关节遍历顺序、轴、限位完全一致；
  两份 XML 的总体 SHA 不同仅因为归档版使用 `pelvis` 名称和另一套 mesh 相对路径。
- hq4 provenance 的 `target_mjcf_sha256` 和 hq_all_v2 Mine provenance 的
  `mjcf_sha256` 均为当前 SONIC MJCF
  `02874afebbe30ba1f90218394c8f9953f5d7a808e6b9950e7964c731da6dfbfe`。
- 根据上述现场，继续只检查 `dof.shape == 21` 不足以抵御另一套 BUMI3 轴符号或
  同维度错序。本轮再次修改 `build_bumi3_three_source_dataset.py`：
  - 从当前 MJCF body 遍历自动读取 21 个名称、单位轴和限位，并断言名称精确等于
    BUMI3 MuJoCo 顺序；
  - 构建前验证大集归档 MJCF 的关节顺序/轴/限位，验证 hq4 和 Mine provenance
    的目标 MJCF SHA，并把全部路径、SHA、顺序、轴和限位写入 summary/provenance；
  - 每条 Robot 对全部帧执行
    `pose_aa[:,1:,:] == dof[:,:,None] * current_mjcf_axes`，容差 `1e-6`。这会同时锁住
    pose 节点顺序、dof 顺序、关节轴和 waist 取反结果；真实三来源分层抽查误差均为 0；
  - 检查可选 `start_time/time_offset/timestamps` 等字段。实际 PKL 没有显式时间字段，
    因此两侧都按“数组 index 0 等于 0 秒”解释，只允许裁末尾；未来若任一来源声明
    不同非零起点，该 SMPL 会降级为 Robot-only，不能用尾帧对齐掩盖头部偏移。
- `test_build_bumi3_three_source_dataset.py` 增加真实 MJCF/provenance 的缩小版门禁、
  waist 使用负 Z 时 Robot 致命拒绝、同名 Robot/SMPL 时间起点差 0.02 秒时只降级
  SMPL 的测试。补强后六组本地相关测试为 `38 passed in 3.99s`，compileall 和
  `git diff --check` 再次通过。

### 9. 仿真 smoke 现场边界

- 首次服务器 1-env smoke 尚未创建环境，就在 `_validate_asset_provenance` 被服务器
  漂移后的 `/home/liwei/legged_lab/bumi.py` SHA 拦截，退出码为 1。因此这次结果只能
  记为“参考路径错误，仿真未执行”，不能记为 MotionLib、reset 或 step 失败。
- 本轮将以不修改 legged_lab 的方式，把本地锁定参考文件复制到独立临时验证目录并通过
  `BUMI3_REFERENCE_ROOT` 显式指定后重跑。临时目录只服务验证，不参与训练资产加载；
  训练和 MotionLib 仍以仓库 `gear_sonic/.../bumi3.xml` 为准。
- 原 hq4 八卡任务在本轮开始时确实有 8 个 worker；之后于 iteration 4855、日志时间
  `15:31:43` 停止，`last.pt` 时间为 `15:31:26`。日志末尾没有 Python traceback，
  dmesg/journal 未检出 OOM、killed process 或 GPU Xid。本 Agent 没有调用 kill、发送
  信号、关闭其 tmux、删除进程或覆盖实验目录；停止原因目前不能从日志确认。

### 10. 增强门禁重建结果与 AppLauncher 启动修正

- 关节/时间门禁提交 `02dd0131e0873d2ffb027f681902e6a6702b1f58` 已推送并在
  服务器同分支再次 `git pull --ff-only`。同步后服务器新增测试结果为
  `14 passed in 2.24s`，`py_compile` 通过。
- 重建前确认没有进程引用新三源索引，将首次由 `851eda7` 生成的目录完整移动到
  `/data/sonic_bumi3/datasets/bumi3_sonic_three_source_v1.pre_joint_contract_851eda7`。
  这是可恢复改名，不是删除；其清单和报告仍保留。随后用增强门禁重新构建用户指定的
  原目标 `/data/sonic_bumi3/datasets/bumi3_sonic_three_source_v1`。
- 增强重建再次审计 `100549/100549` 条并通过；所有真实 Robot 的全帧
  `pose_aa/dof/current-MJCF-axis` 最大误差均未超过 `1e-6`，否则构建会整体失败。
  配对状态和首次结果完全一致：train Robot `95332`、paired SMPL `95132`、
  Robot-only `200`、test paired `5217`。
- 新 summary/provenance 实际写入：当前 MJCF SHA
  `02874afb...bfe`、大集归档 MJCF SHA `db4f51fc...c1a4`、hq4 provenance SHA
  `246464d36e92b41372105ecb7577bada7f47837c822f28d36075b6505ad6ebbc`、Mine
  provenance SHA
  `bc8debdb3604164acfeaa8a801438008c86784a8dc3593e339da26b03cca66b6`，以及完整
  21 关节名称、轴和限位。重建后正式 rehash 又完成 `100549/100549`，输出
  `BUMI3_THREE_SOURCE_VALIDATE=PASS`。
- 使用临时锁定参考目录重跑 smoke 后，参考 SHA 门禁已通过，但服务器 pip 版
  `isaaclab` 顶层包只暴露 `isaaclab.app`，第一次报
  `ModuleNotFoundError: isaaclab.sim`；手工只加入 core source 后又报
  `ModuleNotFoundError: isaaclab_contrib`。两次均发生在环境创建前，不能记为 reset/step
  失败。这也证明用手工拼接单个 PYTHONPATH 不是可靠的训练等价启动方式。
- `gear_sonic/tools/validate_bumi3_integration.py` 改为使用项目训练入口同款的
  `isaaclab.app.AppLauncher`，而不是直接构造 `isaacsim.SimulationApp`。AppLauncher
  负责注册 pip 安装内的 core/contrib/assets 等 source 路径，并注入 physics CUDA
  device 和 headless kit 参数；验证脚本增加 `--no-window` 且不启用 camera。
- 本地 `env_isaaclab` 使用 AppLauncher 重新运行完整 integration validation，退出码 0，
  21 DoF、22 bodies、G1/H2/BUMI3 Hydra 和全部 resolved 网络/频率数值仍通过；输出
  `smoke: 未请求`。该修改不涉及环境、奖励、训练算法或数据契约，服务器真实 1/16-env
  smoke 必须等本提交同步后再执行。

### 11. 为近十万动作补充 MotionLib 启动元数据

- AppLauncher 修复提交 `ef90ad488d41ce1d428186e10778ae339e879e0a` 已推送并在
  服务器快进同步。真实 1-env smoke 随后成功创建场景、启动仿真，MotionLib 识别到
  `95332` 条动作，说明 AppLauncher、IsaacLab 模块、BUMI3 场景和三源目录均已打通。
- 该 smoke 没有继续到 reset/step：启用 adaptive sampling 时，MotionLib 要为全库建立
  稳定 bin，但新软链接目录没有 `metadata.pkl`，因此 `init_adaptive_sampling` 退化为
  逐条打开全部 95332 个 Robot PKL 读取 `length/fps`。进程在约 80 秒时仍以 200% 以上
  CPU 执行文件扫描；这不是死锁或数据错误，但 8 卡正式训练会让每个 rank 重复扫描，
  启动延迟和磁盘压力不可接受。
- 本 Agent 只向自己创建的 tmux `bumi3_three_source_smoke1_final` 发送 Ctrl-C，停止该次
  未完成 smoke；没有影响用户训练进程。shell 因 Isaac Sim 的信号处理最终记录
  `SMOKE_EXIT=0`，但本记录明确不把它当作 reset/step 通过证据。
- `build_bumi3_three_source_dataset.py` 现在根据已经全量审计的 manifest，在 train/test
  各自 `robot_all/metadata.pkl` 写入最小 `{key: {length, fps}}`。该文件只缓存整数帧数和
  浮点帧率，不包含动作数组、不复制源文件、不改变采样权重，也不改变任何源 PKL SHA。
- `validate_index` 新增 metadata 顶层类型、完整 key 集、逐动作 length/fps 与 manifest
  一致性检查；Robot 软链接计数显式排除 `metadata.pkl`，防止把元数据误算成动作。
  provenance 增加 `motionlib_metadata=generated_length_and_fps_only`。
- 缩小版构建测试新增 train metadata 精确内容断言。相关六组本地回归仍为
  `38 passed in 3.88s`，`compileall -q gear_sonic` 与 `git diff --check` 通过。
- 该修正需要再次生成目标索引后才能生效；仍采用“完整移动旧索引为可恢复备份，再构建
  原目标路径”的方式，不会删除已有报告或源数据。完成后的真实 smoke 必须看到
  MotionLib 从 metadata 获取全库长度，再实际完成 reset/step 才能记为通过。

### 12. 修正配对尾帧裁剪后的 adaptive sampling 有效长度

- metadata 提交 `86faf55f2f4b59bef17f82a7d136944d48aaca36` 已推送并同步服务器。
  重建前把上一版增强索引完整移动到可恢复目录
  `/data/sonic_bumi3/datasets/bumi3_sonic_three_source_v1.pre_metadata_02dd013`，随后
  重新构建目标路径。train/test metadata 大小约为 5.1 MB/279 KB，配对计数保持
  `95332/95132/200/5217` 不变，正式第二遍 SHA 再次完成 `100549/100549` 并通过。
- 带 metadata 的 1-env smoke 退出码为 0，明确输出 `smoke: 通过`：完成场景创建、
  MotionLib 全库索引、1 条动作加载、环境 setup、reset 和 1 次 step；验证器递归检查
  observation/action/reward 没有 NaN/Inf。该轮加载日志从 `Loaded 95332 motions` 到
  `Loading motions with 1 jobs` 不再出现近十万次源 PKL 文件扫描。
- 16-env、100-step smoke 随机选中 `walk_ff_stop_180_R_002__A047` 后，在 manager
  初始化阶段 fail-fast：`Adaptive sampling frame count mismatch`，具体为
  `adp_samp=375, loaded=374`。该条是允许的一帧尾差配对；FK 按
  `trim_trailing` 使用共同 374 帧，而初版 metadata 错误写入 Robot 原始 375 帧。
  因此该失败准确定位在 curriculum 长度缓存，不是 NaN、坐标错误或 PhysX 摔倒。
- `build_bumi3_three_source_dataset.py` 对通过配对新增 `aligned_source_frames`，值为
  `min(robot_frames, smpl_frames)`；MotionLib metadata 中 PAIRED 使用该有效长度。
  所有 Robot-only 条目继续使用完整 Robot 帧数，尤其不能让缺失、错坐标或被降级的
  SMPL 缩短仍可训练的 Robot 数据。
- 构建测试把两帧尾差合成配对的 metadata 期望从 Robot 原始 10 改为共同 8，并锁定
  manifest 的 `aligned_source_frames=8`。修正后相关测试 `38 passed in 3.90s`，
  compileall 和 `git diff --check` 通过。
- 该修正必须再次重建目标索引并重新运行 16-env 100-step；在看到实际退出码 0 前，
  本记录不会把 16-env 写成通过。1-env 的既有通过证据仍有效，因为它随机选中的配对
  没有触发 metadata/FK 长度差。

### 13. 最终三源索引重建、元数据和哈希门禁

- 有效长度修正提交 `ab5dc9db0d346f5f284067e9acd8cc51980f0b71` 已推送 GitHub，
  `noetix-volc` 在同一 `feature/bumi-native-sonic-full-training` 分支执行普通
  `git pull --ff-only` 后，本地、GitHub 和服务器 HEAD 完全一致，服务器工作区干净。
- 最终重建前确认没有构建、验证或训练进程引用目标索引。上一版目录没有删除，而是完整
  改名保留为
  `/data/sonic_bumi3/datasets/bumi3_sonic_three_source_v1.pre_aligned_metadata_86faf55`；
  另外两次历史重建也分别保存在 `.pre_joint_contract_851eda7` 和
  `.pre_metadata_02dd013`，需要回滚时仍可核对原报告。
- 最终 build 在 tmux `bumi3_three_source_final_build` 中完成 `100549/100549` 条全量
  数值审计并原子发布。正式路径仍为
  `/data/sonic_bumi3/datasets/bumi3_sonic_three_source_v1`，日志为
  `/data/sonic_bumi3/build_logs/bumi3_three_source_final_build_ab5dc9d.log`。
- 最终计数为 train Robot `95332`、train paired SMPL `95132`、Robot-only `200`、
  test Robot/SMPL 配对 `5217`。Robot-only 中 `101` 条原本就没有 SMPL，另 `99` 条
  是 Robot 合格但 SMPL 坐标配对中位角超过 45 度；没有丢弃这些 Robot 动作。
- `61346` 条合法配对存在末尾网格差，其中 SMPL 相对 Robot 少 1 帧为 `53569` 条、
  少 2 帧为 `7777` 条。逐条读取 `train_manifest.jsonl` 和 `metadata.pkl` 后确认：
  所有 PAIRED metadata `length` 均等于 `aligned_source_frames=min(robot, smpl)`；
  所有 Robot-only metadata 仍等于完整 Robot 帧数，输出 `metadata_alignment=PASS`。
- 独立 tmux `bumi3_three_source_final_hash` 再次调用不带跳过参数的正式 `validate`，
  重新读取并计算 `100549/100549` 条 manifest 源文件 SHA256，输出
  `BUMI3_THREE_SOURCE_VALIDATE=PASS`。日志为
  `/data/sonic_bumi3/build_logs/bumi3_three_source_final_hash_ab5dc9d.log`。
- 最终来源自然采样概率仍为：大集 `0.96969538035497`、hq4 PASS50
  `0.029266143582427726`、Mine Robot-only `0.0010384760626022743`；代码没有增加
  来源权重，也没有把旧 `hq_all_v2` 四库动作再次加入训练。

### 14. 16 环境和八卡 100 轮真实运行结果

- 服务器使用仓库训练同款 `isaaclab.app.AppLauncher` 执行 16-env、100-step：

```bash
BUMI3_REFERENCE_ROOT=/tmp/bumi3_reference_02dd013 \
/root/miniconda3/envs/liwei_lab/bin/python \
  gear_sonic/tools/validate_bumi3_integration.py \
  --smoke \
  --motion-file /data/sonic_bumi3/datasets/bumi3_sonic_three_source_v1/train/robot_all \
  --smpl-motion-file /data/sonic_bumi3/datasets/bumi3_sonic_three_source_v1/train/smpl_all \
  --num-envs 16 --iterations 100 --device cuda:0
```

  实际完成场景、MotionLib、reset 和 100 次 step，输出 `smoke: 通过`；验证器递归检查
  observation、action 和 reward 均无 NaN/Inf。日志为
  `/data/sonic_bumi3/build_logs/bumi3_three_source_smoke16_ab5dc9d.log`。
- 16-env resolved 实测：URDF/MJCF 为 `21 DoF/22 bodies`，`sim_dt=0.005`、
  `decimation=4`、控制频率 `50 Hz`、`target_fps=50`、`action_dim=21`、FSQ 总维度
  `64`、actor proprioception `690`、tokenizer flat `1262`、critic observation
  `1245`、dynamic decoder `754 -> 21`；Isaac/MuJoCo 双向关节和 body mapping 门禁通过。
- GPU 空闲后，在独立 tmux `sonic_bumi3_three_source_smoke_8gpu` 执行生产规模
  `8 rank x 4096 env/rank`、从随机初始化开始的 100-iteration smoke；命令没有使用
  checkpoint、resume 或正式训练目录。8 个 rank 都打印 `Loaded 95332 motions` 并完成
  environment setup，最终 tmux pane `dead_status=0`，保存了 `last.pt`。
- 八卡 smoke 累计 `78,643,200` timesteps、`3,276,800` episodes，总耗时
  `362.55 s`；首轮/末轮吞吐分别为 `159254/218651 steps/s`，运行中 8 卡显存约
  `15.7--16.6 GiB`、利用率通常约 `87%--89%`。完整日志未发现 traceback、
  AssertionError、RuntimeError、CUDA OOM、NCCL 或 NaN。
- smoke 实验主目录为
  `/data/sonic_bumi3/smoke_runs/TRL_BUMI3_Track/manager/universal_token/all_modes/`
  `sonic_bumi3_three_source_smoke_100iter_ab5dc9d-20260901_162058`；`last.pt` 大小约
  391 MB，TensorBoard event 含 `122` 个 scalar tags，100 个 step 的所有 scalar 均有限。
- TensorBoard 首轮到末轮：reward `0.918509 -> 0.905722`、episode length
  `14.69625 -> 14.23250`、value loss `0.149846 -> 0.022008`；三项 auxiliary loss tag
  都真实存在。末轮 termination 分量为 anchor-pos `0.000203`、anchor-ori
  `0.363922`、双肘 ee-body-pos `0.216858`、双脚 foot-pos `0.494853`、timeout
  `0.002024`。100 轮只证明端到端计算和数值稳定，不能据此宣称策略已收敛。
- resolved `config.yaml` 现场解析确认：anchor 是 `waist_yaw_link`；encoder keys 仅
  `g1/smpl`；tokenizer 数据项仅 `encoder_index`、Robot 两项和 SMPL 两项；aux loss
  仅 `g1_recon/g1_smpl_latent/reencoded_smpl_g1_latent`；
  `wrist_mujoco_dof_indices=[]`。活动配置中不存在 Teleop encoder、Teleop tokenizer、
  Teleop auxiliary loss 或 G1 腕部索引 `[19,20,21,26,27,28]`。
- 服务器无 X Server 时仍打印既有 Vulkan/GPU Foundation renderer 错误，但随后各 rank
  都完成 headless PhysX、MotionLib、网络、DDP 和 PPO 100 轮并以 0 退出；因此这些日志
  记录为无窗口渲染噪声，不伪装成已修复，也不把它们误判为训练失败。

### 15. 正式八卡训练与 TensorBoard 命令

- smoke 发现各 rank 若分别解析 `${timestamp}`，秒边界可能生成两个候选目录；DDP 计算
  不受影响，但正式任务必须显式给出同一个 `experiment_dir`，保证 checkpoint、Hydra
  配置和 TensorBoard 只落入一个目录。下面命令先在当前 shell 生成一次唯一目录，再把
  该固定字符串传给所有 rank：

```bash
cd /home/liwei/GR00T-WholeBodyControl
BUMI3_RUN_ID="$(date +%Y%m%d_%H%M%S)"
BUMI3_EXP_DIR="/data/sonic_bumi3/runs/TRL_BUMI3_Track/manager/universal_token/all_modes/sonic_bumi3_three_source_scratch_100k-${BUMI3_RUN_ID}"
BUMI3_LOG="/data/sonic_bumi3/launch_logs/sonic_bumi3_three_source_scratch_100k-${BUMI3_RUN_ID}.log"
mkdir -p /data/sonic_bumi3/launch_logs

tmux new-session -d -s sonic_bumi3_three_source_8gpu \
  "/root/miniconda3/envs/liwei_lab/bin/accelerate launch --num_processes=8 \
    gear_sonic/train_agent_trl.py \
    +exp=manager/universal_token/all_modes/sonic_bumi3 \
    +resume=false checkpoint=null auto_load_latest=false \
    use_wandb=false headless=True num_envs=4096 \
    base_dir=/data/sonic_bumi3/runs \
    exp_var=three_source_scratch_100k \
    experiment_dir=${BUMI3_EXP_DIR} \
    algo.config.num_learning_iterations=100000 \
    ++manager_env.commands.motion.motion_lib_cfg.motion_file=/data/sonic_bumi3/datasets/bumi3_sonic_three_source_v1/train/robot_all \
    ++manager_env.commands.motion.motion_lib_cfg.smpl_motion_file=/data/sonic_bumi3/datasets/bumi3_sonic_three_source_v1/train/smpl_all \
    ++manager_env.commands.motion.motion_lib_cfg.exclude_motion_keys=[] \
    2>&1 | tee ${BUMI3_LOG}"
```

- 查看训练 tmux：
  `ssh noetix-volc -t 'tmux attach -t sonic_bumi3_three_source_8gpu'`；脱离会话使用
  `Ctrl-b` 后按 `d`。本轮只运行了独立 100 轮 smoke，没有替用户启动 100000 轮正式长训练。
- 正式训练启动后，可另建 TensorBoard tmux（6017 避开现有 6006/6016）：

```bash
tmux new-session -d -s tensorboard_bumi3_three_source \
  "/root/miniconda3/envs/liwei_lab/bin/tensorboard \
    --logdir /data/sonic_bumi3/runs/TRL_BUMI3_Track \
    --host 127.0.0.1 --port 6017"
```

  本地建立隧道：`ssh -N -L 6017:127.0.0.1:6017 noetix-volc`，浏览器访问
  `http://127.0.0.1:6017/`。
- 回滚边界：代码可按本轮提交逐项反向提交；数据索引是软链接和元数据，只有确认没有训练
  使用时才可把当前目录改名并恢复某个 `.pre_*` 备份。三个源数据、现有 hq4 历史实验、
  本轮 smoke checkpoint 和日志均未删除或覆盖。
- 最终交付前，本地 `env_isaaclab` 再次运行六组相关 pytest，结果为
  `38 passed in 3.92s`，仅保留一条已有 invalid escape sequence DeprecationWarning；
  `python -m compileall -q gear_sonic`、BUMI3/G1/H2 完整 Hydra/资产/网络静态集成门禁和
  `git diff --check` 均通过。集成门禁输出仍为 `smoke: 未请求`，这是本地命令没有传真实
  服务器数据的准确说明；真实 1/16-env 和八卡 smoke 证据以上述服务器日志为准。

## 2026-09-01：增加一次性验证产物完成后强制清理规则

- 所属分支：`feature/bumi-native-sonic-full-training`；起始 HEAD：
  `dccf1328a4b791034e5a64d379348e0248bd00e6`。修改前本地工作区干净，服务器正式
  BUMI3 三源八卡训练正在独立目录运行，本次规则修改不停止、不重启、不覆盖该正式任务。
- 修改 `agent.md` 的“验证、合并与发布”章节，新增规则：Agent 为验证代码创建的 smoke、
  测试运行、短回合训练、临时 replay/导出在完成且记录证据后，必须删除该次验证专用的
  运行目录、checkpoint、event、导出、渲染、日志及已结束 tmux，保持目录结构清晰。
- 为避免“测试后删除”被错误扩大为破坏性清理，规则同时锁定删除前置条件：必须先确认进程
  结束，精确核对目标只属于该次测试且未被正式训练或用户任务引用；禁止宽泛路径、未解析
  变量、递归通配符和 `git clean`。测试源码、fixture、原始数据、正式训练/checkpoint、
  用户产物和共享缓存不属于清理范围；用户明确要求保留时记录路径和原因后保留。
- 本次只修改仓库治理文档，没有启动新的测试任务或生成新测试产物，也没有追溯删除历史
  产物，因此代码单元测试、仿真和训练验证不适用。提交前执行 Markdown diff 人工检查和
  `git diff --check`；回滚时只需反向提交本节及 `agent.md` 对应规则，不影响训练代码和数据。

## 2026-09-02：直接修正 BUMI3 MJCF 自碰撞与初始陷地

### 1. 变更边界与参考版本

- 所属分支：`feature/bumi-native-sonic-full-training`；起始 HEAD：
  `98717f7ee21114fb6ba668a4206c891578cade1e`。开始修改前本地与 GitHub 同步且工作区
  干净；本轮不改训练 URDF、SONIC 网络、观测、奖励、控制频率、执行器、PPO 或数据。
- 权威参考为
  `/home/weili/legged_lab/source/NoetixRobot/NoetixRobot/assets/robots/bumi3/mjcf/bumi3.xml`，
  SHA256 为 `041c81e8176c7f375302796deca28b141891a3c097d8e341e8d967b735466edf`。
  本地修正后 `bumi3.xml` SHA256 为
  `c4521504388c6eba296b8070fd80d73bb85c506b7346722031cefa3bcea11c04`。
- 验证器不再要求本地 MJCF 与参考逐字相同，而是排除获准修改的 `geom`、碰撞 default
  和 `meshdir` 后，继续严格锁定 body 层级、质量、质心、惯量、关节位置/轴/限位、site、
  actuator 和 sensor。这样既允许修复接触，又防止碰撞修改误伤参考动力学参数。

### 2. `bumi3.xml` 的实际修改

- 22 个原始 STL 全部保留为 `group=1` 的可视 mesh，并设置
  `contype=0/conaffinity=0`；白色 policy 机器人和红色参考影子仍使用完整 BUMI3 原始
  外观，不把 capsule 当作渲染模型。
- 新增 14 个 `group=3` 碰撞体。`base_link`、左右 `leg_roll_link`、左右
  `knee_pitch_link` 使用审核后的 5 个 capsule；位置、半径和长度严格对应训练 URDF：
  base 为 `pos=(-0.0013853,0,0.065525), radius=0.052, length=0.12`，leg-roll 为
  `pos=(0,0,-0.02), radius=0.03, length=0.08`，knee 为
  `pos=(0.008475,0,-0.0894694), radius=0.025, length=0.13`。
- `waist_yaw_link`、双侧 arm-roll、双肘、双侧 ankle-pitch 和 ankle-roll 共 9 个 link
  保留 mesh collision；arm-pitch、arm-yaw、leg-pitch 和 leg-yaw 只渲染、不碰撞，避免
  高精度相邻网格在动作 reset 时互相嵌入。
- 机器人碰撞体设置 `contype=1/conaffinity=0`，地面设置互补的
  `contype=0/conaffinity=1`。MuJoCo 因此仍计算机器人与地面的接触，但不计算机器人
  link 之间的自碰撞；没有关闭膝、肘、脚或机身用于爬行/跪地的触地能力。
- 地面从 `Z=0` 调整为 `Z=-0.02 m`。这是按已取回大集动作的脚底基准消除首帧约
  1--2 cm 陷地；FineDance 首帧会相对地面留出约 1--2 cm 间隙并自然落地，本轮没有
  在 Python 中偷偷抬高/压低 policy 或让参考影子跟随机器人。

### 3. sim2sim 与验证代码同步

- `gear_sonic/utils/mujoco_sim/bumi3_sim2sim.py` 允许一个 body 同时拥有 visual 和
  collision geom，并让红色参考影子只复制 `group=1` 的 22 个原始 mesh；动力学模型
  仍直接加载本轮 `bumi3.xml`，没有运行时碰撞覆盖。
- `gear_sonic/tests/test_bumi3_sim2sim.py` 锁定 `36=22 visual+14 collision`、5 个
  capsule、9 个碰撞 mesh、碰撞名称集合、地面高度和 bitmask；静态 reset 必须无自碰撞
  与地面穿透，主动下移浮动根后又必须只产生地面接触。
- `gear_sonic/tools/validate_bumi3_sim2sim.py` 和
  `gear_sonic/tools/validate_bumi3_integration.py` 增加同样的资产来源保护、碰撞数量/类型/
  尺寸/名称/地面门禁。输出显式区分可视 geom、碰撞 geom、自碰撞开关和初始接触。
- `docs/source/getting_started/bumi3_sim2sim.md` 更新 XML 是唯一 MuJoCo 接触来源的说明，
  并记录 FineDance 与大集地面基准差异，避免以后又在 sim2sim Python 中隐式复刻 URDF。

### 4. 实际验证结果与边界

- 本地 `env_isaaclab` 执行 `pytest -q gear_sonic/tests/test_bumi3_sim2sim.py`：
  最终复验 `12 passed in 3.09s`；`python -m compileall -q gear_sonic` 和
  `git diff --check` 同时通过。
- 执行 `validate_bumi3_sim2sim.py --skip-smoke`：通过；实测 `nq=28,nv=27,nu=21`、
  22 bodies、22 visual mesh、14 collision geom、静态 reset `contacts=0`、自碰撞 `0`、
  地面穿透 `0`，控制契约仍为 `sim_dt=0.005,decimation=4,50 Hz,input=1170,action=21`。
- 对本地取回的 5 条 FineDance 和 5 条大集动作逐帧执行 MuJoCo FK/接触扫描，共
  `26844` 帧；修正前这些动作出现肘-髋、肘-腰、膝-踝等碰撞，修正后自碰撞计数为
  `0`。10 条动作首帧均为 `ncon=0`，没有初始地面穿透；整段仍有 `702` 个机器人-地面
  接触，证明触地碰撞没有被误关。爬行/落地帧可能有较深地面接触，这是动作本身的运行
  姿态，不等同于首帧陷地。
- 完整 `validate_bumi3_integration.py` 通过；实际组合结果仍为 `sim_dt=0.005`、
  `decimation=4`、`50 Hz`、`action_dim=21`，锚点仍是 `waist_yaw_link`，本轮未请求
  Isaac 1-env 数据 smoke。Isaac 启动日志中的 platforminfo/Vulkan 信息不影响静态门禁
  退出码 0。
- 使用现有 `model_step_018000_g1.onnx` 分别对 `axe_idle_R_102__A355.pkl` 和
  `finedance__001.pkl` 执行 100 控制周期真实回放，观测、动作和状态均有限且验证器通过；
  但 2 秒末 root 高度仍分别只有约 `0.0295 m` 和 `0.0545 m`。因此本轮可以确认
  “XML 初始自碰撞/陷地”已消除，不能把旧 checkpoint 仍会摔倒伪装成已解决；后者还需
  继续核对训练/部署动力学一致性或用修正后契约重新训练，不能仅靠资产门禁下结论。
- 本轮验证只使用已有模型和动作，不创建持久 checkpoint、event、导出、渲染或临时运行
  目录，因此没有一次性测试产物需要删除。回滚时反向提交本节列出的 7 个文件即可；参考
  `legged_lab` 仓库、训练数据和已有正式模型均未修改。

## 2026-09-02：统一 base_link 锚点并收敛 BUMI3 训练变量

### 1. 修改边界与最终决策

- 所属分支：`feature/bumi-native-sonic-full-training`；起始 HEAD：
  `7cf7616afaecf198199e60453e062d986083db8a`。开始修改前，本地与 GitHub ahead/behind
  为 `0/0` 且工作区干净；服务器同分支、同 HEAD、工作区干净，没有正在运行的 SONIC
  trainer。历史 TensorBoard 和数据预检 tmux 不属于训练进程。
- 用户最终决定将 BUMI3 训练、数据配对审计和 sim2sim 的命名锚点统一为浮动根
  `base_link`，不再混用 `waist_yaw_link`。所有锚点位置、姿态、线速度、角速度都沿用
  `TrackingCommand` 的命名 body 索引通路；`waist_yaw_link` 仍是正常机器人刚体和全身
  tracking body，不做全局重命名或删除。
- 当前只保留 `base_link` 的 COM 随机化。质量随机化、全关节 KP/KD 随机化、踝关节
  armature 随机化全部设为 `null`；四组 actuator 从项目自定义的
  `DelayedImplicitActuatorCfg(min_delay=0,max_delay=4)` 改为与 G1 相同的
  `ImplicitActuatorCfg`，彻底取消 0～4 个 physics-step 随机延迟。BUMI3 名义质量、
  COM、KP/KD、armature、力矩/速度限制和 action scale 数值没有改写。
- termination 不再保留 BUMI3 的严格覆盖：脚部位置继承 G1 的 `0.20 m`，锚点位置继承
  `0.15 m`，双肘位置继承 `0.15 m`，锚点完整姿态继承 `0.20`；adaptive、
  `down_threshold` 和 `root_height_threshold` 均继承原 G1 配置。`ee_body_pos` 仍只检查
  双肘，不重复检查双脚。
- 强跟踪点从 base/双肘/双脚五个 body 减为 `base_link` 加双肘三个 body，偏移均为零。
  双脚仍参与原有脚部 termination、feet acceleration 和其他发布版奖励，但不进入该强
  point-tracking reward，避免同一脚部误差被过度约束。奖励函数、权重、std、PPO、网络、
  `sim_dt=0.005`、`decimation=4` 和 50 Hz 控制频率没有修改。
- 明确不修改 MuJoCo Euler 积分器或 Python 显式 PD，因为它们与现有 G1 sim2sim 的
  基础实现一致。本轮只修正 BUMI3 非对角 `fullinertia` 暴露出的确定性坐标问题：
  `mj_objectVelocity(local=1)` 返回惯性主轴表达，而训练 `root_ang_vel_b` 使用 link 轴；
  sim2sim 现在先读世界角速度，再乘 `base_link` 世界旋转转置得到 link 局部角速度。

### 2. 修改文件与目的

- `gear_sonic/config/exp/manager/universal_token/all_modes/sonic_bumi3.yaml`：统一 base
  anchor、COM/anti-shake/VR/reward 名称，关闭三类域随机化，继承 G1 termination 阈值，
  将 reward points 缩为三点。
- `gear_sonic/envs/manager_env/robots/bumi3.py`：四组执行器改用无延迟
  `ImplicitActuatorCfg`；保留 BUMI3 参考执行器的其余名义参数和按公式生成的 action scale。
- `gear_sonic/envs/manager_env/mdp/commands.py`：更新通用锚点姿态接口说明，明确 BUMI3
  配置选择 base，但不在通用实现硬编码机器人类型。
- `gear_sonic/trl/utils/order_converter.py`：BUMI3 三点 body 名称的第三项改为
  `base_link`；G1/H2 converter 未修改。
- `gear_sonic/config/sim2sim/bumi3_sonic.yaml`、
  `gear_sonic/utils/mujoco_sim/bumi3_sim2sim.py`：部署锚点与训练一致，并修正非对角惯量时
  base 角速度的 link 坐标表达；没有修改 Euler、PD、力矩裁剪、MJCF 或碰撞。
- `gear_sonic/tools/build_bumi3_three_source_dataset.py`：配对门禁直接比较 Robot
  `root_rot/base_link` 与训练处理后的 SMPL 根姿态，不再乘 waist 局部旋转；契约版本升级为
  `sonic.bumi3.three_source_base_anchor.v2`，默认输出改到独立的
  `/data/sonic_bumi3/datasets/bumi3_sonic_three_source_base_anchor_v2`，避免覆盖旧索引。
- `gear_sonic/tools/validate_bumi3_training_coordinates.py`：旧 hq_all_v2 只读审计也改为
  base 根锚点；旧 waist 契约下的固定 55 条不再被当作新契约真值，可用
  `--expected-bad-count` 显式设置门禁。
- `gear_sonic/tools/validate_bumi3_integration.py`、
  `gear_sonic/tools/validate_bumi3_sim2sim.py`：锁定 resolved base anchor、三点奖励、G1
  termination、仅 COM 随机化、无延迟 actuator 和 sim2sim base 锚点。
- `gear_sonic/tests/test_bumi3_sim2sim.py`、
  `gear_sonic/tests/test_tracking_anchor_semantics.py`、
  `gear_sonic/tools/test_build_bumi3_three_source_dataset.py`：锁定腰关节旋转不改变 base
  锚点/配对结果，并增加非对角惯量下 link 轴角速度回归。
- `docs/source/getting_started/bumi3_sim2sim.md`：把训练/部署共同锚点、诊断输出和观测来源
  更新为 base 契约。历史记录中的 waist 结论作为当时版本的审计证据保留，由本节明确取代。

### 3. 本地实际验证结果

- `/home/weili/miniconda3/envs/env_isaaclab/bin/python -m pytest -q` 运行本次相关的六组
  BUMI 测试文件，结果为 `41 passed in 4.80s`，仅有一条已有的 invalid escape sequence
  DeprecationWarning。单独首轮锚点/sim2sim/构建定向测试为 `19 passed in 3.55s`。
- 直接收集整个 `gear_sonic/tests` 时，被未安装的可选依赖 `msgpack` 阻断于
  `test_input_readers.py` 导入阶段；该错误发生在测试收集、与本轮 BUMI 修改无关，因此
  未把它伪装成代码失败，也未擅自改动环境依赖。
- `validate_bumi3_integration.py --device cpu` 退出码为 0；实际启动 headless Isaac Sim，
  验证 URDF/MJCF `21 DoF/22 bodies`、无延迟 actuator、BUMI3/G1/H2 Hydra compose、
  `sim_dt=0.005`、`decimation=4`、50 Hz、`action_dim=21`、FSQ `64`、actor proprioception
  `690`、tokenizer flat `1262`、critic obs `1245`、dynamic decoder `754 -> 21`。本地未提供
  服务器三源数据，所以该命令准确输出 `smoke: 未请求`。
- `validate_bumi3_sim2sim.py --steps 100` 退出码为 0：100 个控制周期 observation、action、
  torque、qpos、qvel 均为有限值；resolved anchor 为 `base_link`，模型仍为
  `nq=28,nv=27,nu=21`、22 bodies、22 个可视 mesh 和 14 个 XML 碰撞体。
- `python -m compileall -q gear_sonic` 与 `git diff --check` 均通过。上述命令未创建训练
  目录、checkpoint、TensorBoard event、导出或渲染文件，没有本轮一次性测试产物需要清理。

### 4. 待服务器闭环、删除边界与回滚

- 代码提交推送并由服务器 `git pull --ff-only` 后，必须用新 v2 默认路径全量构建和验证
  base-anchor 三源软链接索引。新索引通过前不得删除三个源数据：
  `bumi3_smpl_97660_v1`、`hq4_pass50_v1`、`hq_all_v2`。
- 新索引通过后，按用户授权精确删除旧三源派生索引及其 `.pre_*` 备份、未再引用的
  `hq_all_v1`、旧 BUMI3 训练 run/checkpoint，以及本地 `models/sonic_bumi3`。删除前必须
  再次核对无进程引用，实际删除路径、容量和结果将在本节后续记录，不能用计划冒充完成。
- 代码回滚可反向提交本节对应提交；数据回滚边界以新索引发布和旧目录实际删除记录为准。
  原始三源 PKL 始终保留，因此即使旧软链接索引被删除，也可用记录的构建命令重新生成。

### 5. 服务器首次 v2 构建的资产指纹门禁修正

- 上述代码提交 `13645ea066720f3b881967f49c867500388a3b19` 已推送 GitHub，服务器
  同分支通过 `git pull --ff-only` 快进到同一提交且工作区干净。首次执行 v2 build 时，
  构建器在发现来源阶段、创建目标目录前 fail-fast；日志为
  `/data/sonic_bumi3/build_logs/bumi3_base_anchor_v2_build_13645ea.log`。
- 失败原因是 hq4/Mine provenance 保存的目标 MJCF SHA256 为
  `02874afebbe30ba1f90218394c8f9953f5d7a808e6b9950e7964c731da6dfbfe`，而当前碰撞
  修正后 MJCF 为 `c4521504388c6eba296b8070fd80d73bb85c506b7346722031cefa3bcea11c04`。
  通过 `git show 7cf7616^:.../bumi3.xml | sha256sum` 确认前一个指纹恰好就是碰撞修正前
  仓库资产；提交 `7cf7616` 只修改已审核的 geom/地面，受保护的质量、惯量、关节、执行器
  和传感器签名仍由集成验证器逐项锁定。因此该失败是完整 XML 哈希把碰撞层变化误判为
  轨迹运动学不兼容，不是数据坐标、帧率或关节契约失败。
- `build_bumi3_three_source_dataset.py` 新增精确白名单：只接受当前完整指纹和上述已审核的
  碰撞修正前指纹。未知旧版本仍立即失败；大集归档 XML 仍逐项比较 21 个关节名称、遍历
  顺序、轴和限位，Robot PKL 仍逐条检查 dof/pose 轴符号。summary/provenance 额外记录
  当前指纹、允许指纹、hq4 实际指纹和 Mine 实际指纹，不能静默放宽。
- `test_build_bumi3_three_source_dataset.py` 新增当前指纹、碰撞修正前指纹通过以及任意未知
  指纹拒绝的三向回归。定向测试结果为 `5 passed in 0.15s`，相关文件 compileall 与
  `git diff --check` 通过。失败 build 未生成目标索引、checkpoint、event 或临时 staging，
  只保留上面的诊断日志作为本次正式数据构建审计证据。

### 6. 锁定服务器当前 2816 条 hq4 PASS 白名单

- 指纹修正提交 `99397122a4d54b4492c2334d0401ec05792ba7c3` 推送并同步服务器后，
  第二次 build 在计数门禁 fail-fast：当前 `hq4_pass50_v1` 含 Robot `2816`、SMPL
  `2815`，而旧代码仍锁定历史 `2790/2788`。日志为
  `/data/sonic_bumi3/build_logs/bumi3_base_anchor_v2_build_9939712.log`，目标 v2 目录仍未
  创建，tmux 已结束且退出码为 1。
- 现场检查确认这不是在旧目录里临时多放 26 个文件：当前 `meta/provenance.json` 和
  `meta/manifest.jsonl` 均于 2026-09-02 13:53 整套更新，provenance 明确声明
  `pass_count=2816`，质量报告 SHA256 为
  `2fc2c5865b86d38f656832985a50cd61611cc5979a533bb9a71f4fd65c2c3b20`。与旧 2790
  manifest 比较，旧集合有 10 条已不在新发布集，新集合新增 36 条，净增 26；因此不能把
  旧 key 列表直接套到已经替换的源目录，也不能假装仍是原 2790 资产。
- 按“旧数据删除、使用当前新数据”的边界，服务器从当前 hq4 manifest 原子生成固定
  `/data/sonic_bumi3/datasets/hq4_pass50_v1/meta/sonic_train_whitelist.txt`，包含 2816 个
  唯一 key，SHA256 为
  `85355027e47112b61201e5debe1d581a016bc4a597a99208cd33a1f75e1398f5`；相邻
  `sonic_train_whitelist.provenance.json` 保存 manifest/provenance/质量报告 SHA 和生成时
  `2816/2815` 计数。原 Robot/SMPL PKL 没有改写。
- 构建器现在必须读取上述白名单后再索引 hq4；白名单缺失、空行、重复 key、缺少 Robot
  或计数不符均立即失败。目录内未来新增但未进入固定 manifest 的 PKL 只记录到
  `hq4_ignored_*`，不会自动进入训练。默认 hq4 计数随当前发布契约更新为
  `2816 Robot/2815 SMPL`。
- 缩小版构建测试额外放入一条白名单外 hq4 Robot/SMPL，并确认最终 manifest 不包含它；
  定向结果为 `5 passed in 0.17s`，`git diff --check` 通过。该改动不改变大集 92443/5217
  或 Mine 99 条来源，也不改变逐 PKL 坐标、帧率、关节、配对和 SHA256 门禁。

### 7. v2 全量发布与移除外部机器人仓库验证依赖

- 提交 `a1665a4c5763b7b9cc1619c8029f3e7a2b84b8c2` 推送并同步服务器后，第三次
  build 对 `100575` 条训练/test 动作完成全量 PKL 数值审计，退出码 0，并原子发布
  `/data/sonic_bumi3/datasets/bumi3_sonic_three_source_base_anchor_v2`。独立 hash validate
  再次逐条复核 `100575/100575` 个源文件 SHA256，输出
  `BUMI3_THREE_SOURCE_VALIDATE=PASS` 且 tmux dead status 为 0。正式日志分别为
  `/data/sonic_bumi3/build_logs/bumi3_base_anchor_v2_build_a1665a4.log` 和
  `bumi3_base_anchor_v2_hash_a1665a4.log`。
- v2 最终静态计数：train Robot `95358`、paired SMPL `95222`、Robot-only `136`、test
  Robot/SMPL `5217/5217`。Robot-only 包含 `100` 条没有 SMPL 和 `36` 条 base/SMPL
  根姿态中位差超过 45 度的配对降级；没有丢弃合格 Robot。来源自然采样比例为大集
  `0.9694309863881373`、hq4 `0.0295308206967428`、Mine `0.001038192915119864`。
- 全量坐标统计中，大集 train 合格配对根姿态差中位数总体为约 `7.615°`、最大
  `44.441°`，Robot clip 根倾角中位数约 `6.082°`；test 对应约 `7.547°/28.310°` 和
  `6.021°`。hq4 配对根姿态差中位数总体约 `8.824°`、最大 `36.729°`，Robot 根倾角
  中位数约 `6.880°`。这些结果未发现数据集整体横躺；它们是数据静态门禁，不代替策略
  收敛证明。
- 新 v2 执行 1-env、1-step Isaac Lab smoke，实际加载 `95358` 条 MotionLib 元数据并抽取
  `walking_quip_360_R_002__A430_M`，完成场景、reset 和 step；action shape `21`、policy
  obs `690`、critic obs `1245`，tokenizer 只有 `g1/smpl` 五项，event 现场显示质量、
  armature、KP/KD 均为 `None`，只保留 `base_link` COM。输出 `smoke: 通过`，观测、动作、
  reward 无 NaN/Inf。服务器无图形设备的 Vulkan 报错是既有 headless 渲染噪声，PhysX 和
  smoke 仍完成。
- 该 smoke 首次调用暴露出验证器会在启动前读取 `/home/liwei/legged_lab` 的外部参考哈希。
  这不属于训练运行时依赖：实际 MotionLib、URDF、MJCF 和机器人配置始终从当前 SONIC
  仓库加载；但把外部仓库放在 smoke 前置门禁仍是错误耦合。按用户要求，
  `validate_bumi3_integration.py` 已删除外部路径发现、`BUMI3_REFERENCE_ROOT`、动态导入
  `NoetixRobot/bumi.py` 及逐文件外部比较，改为锁定 SONIC 仓库内 URDF、MJCF 和 mesh
  bundle 指纹，并继续用显式数值断言验证全部执行器、初始姿态、mapping 和 action scale。
- `validate_bumi3_sim2sim.py` 同样删除外部 MJCF 参数和比较，只读取仓库内
  `gear_sonic/data/assets/robot_description/mjcf/bumi3.xml`；sim2sim 使用文档同步说明没有
  `legged_lab` 或 `NoetixRobot` 依赖。外部仓库当前内容不会被复制、接受或用于训练。
- 去耦后本地重新运行集成验证，无任何外部环境变量即可通过；sim2sim 100 控制周期通过，
  BUMI 相关 pytest 为 `42 passed in 5.14s`，compileall 与 `git diff --check` 通过。服务器
  还需在同步该去耦提交后，不设置任何参考路径重跑 1-env smoke，结果将在后续记录补全。

### 8. SONIC 本地资产闭环、服务器复验与旧产物清理

- 去除外部机器人仓库依赖的提交
  `3ed0b0539965e88d069542c8d5a23284262e8747` 已推送 GitHub，并由服务器 SONIC 仓库
  `/home/liwei/GR00T-WholeBodyControl` 在同一
  `feature/bumi-native-sonic-full-training` 分支执行 `git pull --ff-only`。服务器随后使用
  `env -u BUMI3_REFERENCE_ROOT` 启动 1-env、1-step Isaac Lab smoke，证明没有借助残留环境
  变量或 `/home/liwei/legged_lab`：MotionLib 实际加载当前 v2 的 `95358` 条训练元数据，reset
  和 step 均通过，action 为 `21`、policy observation 为 `690`、critic observation 为
  `1245`，tokenizer 仍只有 `g1` 与 `smpl`。质量、KP/KD、踝关节 armature 随机化均为
  `None`，执行器没有随机延迟，仅保留 `base_link` COM 随机化。
- 本轮删除前再次确认没有 `train_agent_trl.py`、`eval_agent_trl.py`、旧 TensorBoard 或其他
  引用 `/data/sonic_bumi3` 的活跃进程。按用户明确授权永久删除服务器旧三源软链接索引及
  `.pre_*` 备份、旧 `hq_all_v1`、旧 `/data/sonic_bumi3/runs`（删除前约 `23 GiB`、共
  `65` 个 checkpoint/event/model 文件）、旧 smoke/export/tensorboard/launch/log/
  code_snapshot/reference_asset 目录和对应 `/tmp` 参考目录；同时永久删除本地
  `/home/weili/GR00T-WholeBodyControl/models/sonic_bumi3`（删除前约 `2.0 GiB`，包含旧
  16000、18000、70000 step checkpoint/ONNX）。这些旧模型与派生产物没有回收站，不能
  直接恢复，但源 PKL 仍完整保留。
- 清除历史构建和冒烟日志后，服务器 `build_logs` 只保留当前正式 v2 的
  `bumi3_base_anchor_v2_build_a1665a4.log` 与
  `bumi3_base_anchor_v2_hash_a1665a4.log`；本轮 1-env smoke 生成的两份精确
  `/tmp/isaaclab/logs` 文件也已删除，符合 `agent.md` 中测试结束后清除临时产物的要求。
- 当前保留的数据只有训练仍需要的三套源和当前联合索引：大集
  `bumi3_smpl_97660_v1` 约 `29 GiB`、四库 `hq4_pass50_v1` 约 `3.5 GiB`、包含 99 条
  Mine 来源的 `hq_all_v2` 约 `3.7 GiB`，以及只含软链接/manifest 的
  `bumi3_sonic_three_source_base_anchor_v2` 约 `946 MiB`。不能删除 `hq_all_v2`，因为
  当前 v2 索引的 99 条 Mine Robot-only 动作仍精确引用该源；这不是继续使用旧四库训练集。
- 清理后再次运行完整索引验证，而非只检查目录名：`build_bumi3_three_source_dataset.py
  validate --output-root /data/sonic_bumi3/datasets/bumi3_sonic_three_source_base_anchor_v2
  --workers 8` 对 `100575/100575` 个源文件完成 SHA256 复核并输出
  `BUMI3_THREE_SOURCE_VALIDATE=PASS`。最终计数保持 train Robot `95358`、paired SMPL
  `95222`、test Robot/SMPL `5217/5217`，说明旧数据和 checkpoint 清理没有造成当前索引
  断链。额外启动的逐软链接只读扫描因耗时超过终端等待窗口而被精确终止，没有遗留测试
  进程，也没有修改任何数据。

### 9. 启动 base-anchor v2 正式八卡训练

- 正式训练启动时分支为 `feature/bumi-native-sonic-full-training`，本地、GitHub 与服务器
  SONIC 仓库 HEAD 均为 `031286ff20f10299a46dd6a8d54dbc683d08396f`，工作区干净。
  服务器没有旧 trainer 或 tmux，会前 8 张 RTX 4090 D 显存均只占约 `2 MiB`、利用率为
  `0%`，`/data` 约有 `2 TiB` 可用空间；`liwei_lab` 中的 PyTorch `2.7.0+cu126` 能识别
  8 张 CUDA GPU。
- 启动前使用刚完成的全量门禁结果：当前 v2 索引 `100575/100575` 个源文件 SHA256 通过，
  train Robot `95358`、paired SMPL `95222`。正式命令只读取
  `bumi3_sonic_three_source_base_anchor_v2/train/{robot_all,smpl_all}`，不读取
  `legged_lab`、旧三源索引或旧 checkpoint。
- 训练 tmux 为 `sonic_bumi3_base_anchor_v2_8gpu`，正式实验目录为
  `/data/sonic_bumi3/runs/TRL_BUMI3_Track/manager/universal_token/all_modes/
  sonic_bumi3_base_anchor_v2_scratch_100k-20260902_164548`，启动日志为
  `/data/sonic_bumi3/formal_logs/sonic_bumi3_base_anchor_v2_scratch_100k-20260902_164548.log`。
  命令显式设置 `resume=false`、`checkpoint=null`、`auto_load_latest=false`、
  `num_learning_iterations=100000`、`num_envs=4096` 和单节点 8 个 accelerate rank，属于
  从头正式训练，不会自动接续任何旧模型。
- 8/8 个 rank 均完成 4096 环境搭建并进入真实 PPO。首次交付监控时 TensorBoard 已写入
  `122` 个 scalar；iteration `29`、累计 `22806528` timesteps、吞吐约
  `272405 steps/s`、mean reward 约 `1.0892`、mean episode length 约 `17.135`。8 张 GPU
  显存约 `15.9--16.7 GiB`、利用率约 `87%--89%`，Traceback/OOM/NCCL/NaN 扫描为 0。
  前 29 轮 termination 仍以 `anchor_ori_full≈0.5723` 和
  `foot_pos_xyz≈0.4841` 为主；这是从零训练的极早期观测，只证明日志链路有效，不能提前
  宣称策略已经收敛或 sim2sim 已通过。
- TensorBoard 正式会话为 `tensorboard_bumi3_base_anchor_v2`，服务只监听服务器本机
  `127.0.0.1:6017`；event 文件已生成并持续增长。该训练和 TensorBoard 均为用户要求保留
  的正式任务，不属于一次性 smoke，因此不会按测试产物规则删除。首个模型将在默认
  `save_last_frequency=50` 到达后写入并持续覆盖同一正式实验目录中的 `last.pt`；编号
  `model_step_*.pt` 则按 `save_interval=500` 保存。后续复核到 iteration `71` 时，约
  `391 MB` 的首个 `last.pt` 已实际存在，但尚未到第一个编号 checkpoint，不能把两类
  保存频率混为一谈。

## 2026-09-03：调整 BUMI3 跟踪点、腰部域随机化和五点奖励

### 1. 修改起点与工作区保护

- 所属分支为 `feature/bumi-native-sonic-full-training`，起始 HEAD 为
  `b7f35750366149e313f4d9593c298d3a2020c044`；修改前本地与同名 origin 分支 ahead/behind
  均为 `0/0`。工作区原有未跟踪文件 `g1.tar.gz` 属于用户受保护产物，本轮没有读取、
  修改、暂存或删除它。
- 本轮参数只来自用户明确给出的新训练契约和当前 SONIC BUMI3 配置，没有混用其他 BUMI
  版本。修改前 `sonic_bumi3.yaml` SHA256 为
  `a2ca8b208c4fc614a5ad64131558ffeb37ad445834ce440ea0cba683577c0d7a`；未修改的运行时
  URDF `bumi.urdf` 和 MotionLib MJCF `bumi3.xml` SHA256 分别为
  `0e08c15fe2226fedeac967c06a7910701935fc6de8fca2d4664a76c9ac41e955`、
  `c4521504388c6eba296b8070fd80d73bb85c506b7346722031cefa3bcea11c04`。

### 2. 配置和契约校验修改

- `gear_sonic/config/exp/manager/universal_token/all_modes/sonic_bumi3.yaml`：从 motion
  tracking `body_names` 中只移除 `l_leg_yaw_link` 和 `r_leg_yaw_link`，其余 12 个跟踪
  body 及 `anchor_body=base_link` 保持不变；该修改不移除 21 DoF 动作中的左右
  `leg_yaw_joint`，也不改变机器人关节顺序或执行器参数。
- 同一配置把 `anti_shake_ang_vel` 的 `base_link` 删除，仅保留左右
  `elbow_pitch_link`；把 COM 随机化目标从 `base_link` 改为 `waist_yaw_link`；启用只作用
  于 `waist_yaw_link` 的质量随机化，启动时按原始质量乘以均匀采样的 `[0.8, 1.5]`，
  operation 明确为 `scale`。踝关节 armature 和执行器 KP/KD 随机化仍为 `null`。
- `reward_point_body` 按用户给出的顺序改为 `waist_yaw_link`、左右肘、左右踝共五点，五个
  offset 均为 `[0.0, 0.0, 0.0]`。`vr_3point_body` 仍保持双肘加 `base_link`，因为它与
  reward 五点及 tracking body 是三套独立语义，本轮没有收到修改 VR 三点的要求。
- `gear_sonic/tools/validate_bumi3_integration.py` 同步锁定上述 resolved Hydra 契约；质量
  event 额外检查 `_target_`、函数、`startup` 时机、robot body、范围和 scale operation，
  防止只改表面 YAML 而继承到旧的 `[0.8, 2.5]`。12 个 tracking body 使 critic
  observation 从 `1245` 降为 `1227`；actor proprioception 仍为 `690`、tokenizer flat
  仍为 `1262`、动作维度仍为 `21`。

### 3. 本地实际验证与兼容性边界

- 直接调用 `_validate_resolved_configs()` 成功，实际解析得到
  `sim_dt=0.005`、`decimation=4`、控制频率/目标 FPS `50`、actor `690`、tokenizer
  `1262`、critic `1227`、decoder `754 -> 21`；不是只对 YAML 文本做搜索。
- 使用 `/home/weili/miniconda3/envs/sonic/bin/python` 运行完整
  `gear_sonic/tools/validate_bumi3_integration.py`，实际启动本地 headless Isaac Sim，验证
  当前 URDF/MJCF、21 DoF/22 body、执行器、mapping 和 resolved 配置，结果为
  `BUMI3 原生 SONIC 集成验证通过`。本轮未传正式 motion/SMPL 路径，所以没有创建环境做
  reset/step smoke；该结果不代表新参数已完成短训练或策略质量验证。
- 逐文件运行 BUMI3 dataset、配对、sim2sim 和锚点相关 pytest，结果为
  `42 passed, 1 warning in 4.94s`；warning 是历史字符串的 invalid escape sequence。
  一次对整个 `gear_sonic/tests` 的宽范围收集因环境缺少可选 `msgpack` 而在无关
  `test_input_readers.py` 收集阶段退出，退出码 `2`，没有执行测试体；改用上述逐文件命令
  后 BUMI3 范围全部通过。`compileall` 与 `git diff --check` 同样通过。
- 旧正式训练使用 14 个 tracking body，checkpoint 中的 critic 输入层按 `1245` 维创建；
  新配置为 `1227` 维，因此旧 checkpoint 不能未经权重适配就做包含 critic/optimizer 的
  完整 resume。actor 输入和 21 维输出没有因本次修改变化，但仍需单独验证仅加载 actor
  或选择性初始化的策略，不能从维度静态检查推断兼容。回滚时应对本轮提交创建反向提交，
  不得用 reset/clean 覆盖用户工作。

### 4. 服务器同步与旧训练配置边界

- 配置、校验和本记录首次补充已提交为
  `0593bf3fe00182c35d28d8af95423b54c7ba4749`，使用详细中文提交说明推送到 GitHub 同名
  feature 分支。服务器仓库 `/home/liwei/GR00T-WholeBodyControl` 修改前为
  `b7f35750366149e313f4d9593c298d3a2020c044` 且工作区干净，随后执行
  `git pull --ff-only origin feature/bumi-native-sonic-full-training`，只做快进并到达
  `0593bf3`；快进后远端工作区仍干净。
- 本次同步没有重启、停止或恢复训练。正式 tmux
  `sonic_bumi3_base_anchor_v2_8gpu` 仍是 2026-09-02 16:46 启动的原进程，最终复核时八个
  `train_agent_trl.py` rank 全部存活并继续到 iteration `25150`；TensorBoard 会话也继续在
  `127.0.0.1:6017` 运行。现场八卡显存约 `16.0～16.7 GiB`，单次 GPU 利用率采样为
  `0～58%`（GPU0 的瞬时 0% 不能解释为 rank 退出，PID、显存和后续 iteration 都在继续），
  `/data` 仍有约 `1.8 TiB` 可用。
- 运行目录内的 `config.yaml` 明确证明该进程仍使用启动时的旧契约：14 个 tracking body
  包含左右 `leg_yaw_link`，reward 仍为 `base_link` 加双肘三点，anti-shake 仍含
  `base_link`，COM 仍作用于 `base_link`，质量随机化为 `None`。因此下面的训练曲线和回传
  checkpoint 都属于旧 base-anchor v2，不能当作本轮新配置的训练结果。

### 5. 正式训练曲线与健康分析

- 从正式日志逐 iteration 解析，前 100 轮到 iteration 24911 前的最近 100 轮，平均
  reward 从 `1.0948` 提升到 `14.0518`，平均 episode length 从 `17.2739` 提升到
  `146.6325`，timeout 从 `0.00336` 提升到 `0.52591`。body 位置/旋转误差从
  `0.07706/0.52155` 降到 `0.04536/0.25070`，joint 位置误差从 `0.31014` 降到
  `0.14400`，anchor 旋转误差从 `0.35424` 降到 `0.13284`，说明策略相对从头阶段已有
  明显学习，而不是只保持进程存活。
- 最近 100 轮主要 termination 指标为 foot position `0.23480`、anchor orientation
  `0.22050`、end-effector position `0.08957`、anchor position `0.03214`；timeout 为
  `0.52591`。这些 episode tensor 可在同一 episode 同时置位，不能简单相加当作互斥概率。
  相较早期脚部/anchor 姿态终止已下降，但它们仍是主要失败来源；末端位置终止近期上升，
  需要后续 replay/分动作评估确认是 adaptive sampling 难例集中还是动作质量退化。
- TensorBoard 在 iteration `24938` 有 122 个 scalar。最近 100 轮：reward
  `14.1867`、length `148.2163`、吞吐约 `267192 steps/s`；policy/value loss 分别为
  `-0.00326/0.07563`，approx KL `0.01517`，clip fraction `0.10292`，ratio
  `0.99984`，advantage std `0.98411`，学习率 `1e-5`，policy noise std 约 `0.49765`。
  这些值没有数值发散迹象，但 noise std 接近配置上限 `0.5`，且最近 reward/length 有批次
  波动，不能据此宣称 100k 训练已收敛。
- 对截至 iteration `25150` 的完整正式日志使用精确边界扫描，`Traceback`、CUDA OOM、
  `OutOfMemory`、NCCL error、`RuntimeError`、独立 `NaN` 和独立 `Inf` 均为 0。宽泛的
  `grep -i inf` 会把普通字符串误计为 4249 行，不能用作异常数。本次没有执行策略 replay、
  仿真评估、ONNX 导出或硬件测试，所以结论仅为训练进程和数值曲线健康、尚未证明动作质量
  或硬件安全。

### 6. 最新模型回传、完整性和清理

- 正式 run 每 50 轮使用临时文件加原子 `os.replace` 更新 `last.pt`；编号 checkpoint 的
  真实 callback `save_frequency` 为 2000，并已保存到 `model_step_024000.pt`。为避免下载
  期间 `last.pt` 被替换，在同一文件系统为当时最新 inode 创建一次性硬链接；读取成功后
  确认其 `state.global_step=24950`、`tot_timesteps=19621478400`、大小
  `391203747` bytes，包含 policy/value/optimizer/scheduler/env state，随后才开始传输。
- 模型已回传为
  `models/sonic_bumi3/sonic_bumi3_base_anchor_v2_scratch_100k-20260902_164548/model_step_024950.pt`，
  同目录保存该 run 原始 `config.yaml` 和 `meta.yaml`。三者本地/远端 SHA256 分别一致：
  模型 `366a5457a9804a4e44dd9217ff965c31defa66a1a123d40bf70bc63bca6fd1d5`、配置
  `62f6fc8bad5619971474674241b168c6d852fa672330d8e9d45336cd6cbd313c`、meta
  `9194a2e11925a35277193b5707f51e1cd684d7ab6274e8127be032ec0318f852`。
- 本地再次用 SONIC 环境完整 `torch.load`，确认 step/timestep 不变，policy 有 45 个 tensor、
  value 有 17 个 tensor；actor 动态 decoder 第一层为 `(2048, 754)`、输出层为
  `(21, 512)`，旧 critic 第一层为 `(2048, 1245)` 且 running mean/std 为 `1245`。这提供
  了旧 checkpoint 不能完整 resume 新 `1227` 维 critic 的直接张量证据。
- 本地哈希和结构复核通过后，远端一次性硬链接
  `.codex_transfer_last_20260903.pt` 已用精确路径删除并确认不存在；正式 `last.pt`、
  `model_step_024000.pt`、训练进程、TensorBoard 和其他 checkpoint 均未删除。回传目录位于
  Git 已忽略的 `models/` 下，不进入源码提交；用户原有 `g1.tar.gz` 仍保持未跟踪且未触碰。

### 7. 在 noetix-volc 导出 step 25300 ONNX 并回传本地

- 用户要求在 `noetix-volc` 完成导出。为避免持续更新的 `last.pt` 在读取期间被原子替换，
  先在正式 run 的同一文件系统为当时最新 inode 创建一次性硬链接，使用
  `/root/miniconda3/envs/liwei_lab/bin/python` 完整 `torch.load` 后确认
  `state.global_step=25300`、`tot_timesteps=19896729600`、大小 `391203747` bytes、policy
  tensor 数为 `45`；旧 critic 输入层仍为 `(2048, 1245)`，actor decoder 输入/输出仍为
  `(2048, 754)` 和 `(21, 512)`。冻结模型保留为正式产物
  `model_step_025300.pt`，SHA256 为
  `fb365c205d599a7750aaf91d34db07b4ce127df8e87bc5a9821bbbcec64980fc`；隐藏的一次性
  `.codex_export_snapshot_20260903.pt` 随后已精确删除。
- 在物理 GPU 4 上运行 `gear_sonic/eval_agent_trl.py`，参数为冻结 checkpoint、
  `num_envs=1`、`headless=true` 和 `export_onnx_only=true`，进程退出码为 `0`。正式导出
  日志保存在
  `/data/sonic_bumi3/formal_logs/sonic_bumi3_export_step_025300_20260903.log`；无显示服务器上的
  Vulkan/renderer 提示属于 headless 噪声，日志没有 Python traceback 或 OOM。导出后
  精确删除一次性 `/tmp/isaaclab/logs/isaaclab_2026-09-03_14-17-31.log`，正式 checkpoint、
  ONNX、配置和导出日志均保留。
- 四个 ONNX 在服务器和本地分别通过 `onnx.checker.check_model` 及 ONNX Runtime CPU
  零输入有限值推理。`model_step_025300_g1.onnx` 为 BUMI3 sim2sim 使用的 Robot Encoder
  联合策略，输入/输出为 `1170 -> 21`，SHA256 为
  `562de4efda9cd2d8f90f368d304dcf990f9c59d10a41d14eaa2bf79215fb340b`；SMPL 策略为
  `1470 -> 21`，SHA256 为
  `91f8701b2e69d713d883c07e5991d6ab84908136a4e39a7ed033cca8d51f00fd`；encoder 为
  `1263 -> 64`，SHA256 为
  `c18b05dd8454522014ed162db1a0bd82da5f36c89a0ca03894f162815bb26196`；decoder 为
  `754 -> 21`，SHA256 为
  `64f19bbee4aa7aecd95b65112afa3a0bd92c4b88206a70f14058a646601585d7`。相邻
  `model_config.yaml` SHA256 为
  `19765cd038d92b9fc1635d776c310d6c565b991286c59a52769afd1abd223333`。
- 产物已回传至本地 Git 忽略目录
  `models/sonic_bumi3/sonic_bumi3_base_anchor_v2_scratch_100k-20260902_164548`，四个 ONNX、
  `model_config.yaml` 的本地/远端 SHA256 逐项一致。为了给 sim2sim 提供可直接执行的
  50 Hz BUMI3 输入，同目录额外保存服务器实际验证过的 2749 帧动作
  `sim2sim_validation_motion/aioz_gdance__-FXdDRM4lC0_03_0_1650_dancer_00.pkl`，SHA256 为
  `7909459385b500e23af9af97e53f952b9ff24a6175356a544cd39645cc6a4a42`。
- 服务器 `liwei_lab` 环境缺少的只是 `tyro` CLI 解析依赖，因此服务器验证通过临时内存
  shim 绕过 CLI 后直接调用同一脚本的 `Args` 和 `main()`，没有安装包或修改训练环境：
  `--validate-only` 等价验证输出 `BUMI3_SIM2SIM_VALIDATE_ONLY=PASS`，随后 2 秒 headless
  动力学 smoke 完成 100 个控制步。回传后使用本地已有且依赖完整的仓库
  `.venv_sim/bin/python` 运行标准 CLI，`--validate-only` 同样通过；本地 2 秒、100 控制步
  smoke 正常结束，最终 root height 约 `0.40348 m`、最大绝对 torque 约 `21.21956`。
  这些结果证明 ONNX/动作/MJCF 契约和短时 MuJoCo 执行链可用，不代表长动作质量或真机安全。
- 导出和传输没有停止或重启正式训练。最终复核时 accelerate launcher 及 8 个 worker
  全部存活，训练已从冻结时的 iteration 25300 继续到 iteration `25582`；正式日志中
  `Traceback`、CUDA OOM、`OutOfMemory`、NCCL error 和 `RuntimeError` 精确计数仍均为 0。
  该模型仍来自 2026-09-02 启动的旧 14 tracking-body/三 reward-point 配置，只是比先前
  回传的 step 24950 更新；它可以导出并运行 sim2sim，但不能代表本日新 12 body、五点奖励、
  `waist_yaw_link` COM/质量随机化配置已经训练。

### 8. 兼容 BUMI3 重定向 Mimic NPZ 的命名根 body

- 本轮位于 `feature/bumi-native-sonic-full-training`，起始 HEAD 为
  `fe16d959f17c6c678972d1b47406e6764e47943a`，本地相对 origin ahead/behind 为 `0/0`；
  修改前只有用户原有未跟踪 `g1.tar.gz`，本轮没有读取、修改、暂存或删除。修改前
  `gear_sonic/utils/mujoco_sim/bumi3_sim2sim.py` 和
  `gear_sonic/tests/test_bumi3_sim2sim.py` 的 SHA256 分别为
  `de498239de6b535364faf98910f5166dcb5910788ae5fb3dead65664cbc5264a`、
  `684aa9290849becef54e25f856c25fa202a8bfa1b00141955ceaed47cfdd8688`。
- 运行契约仍来自仓库内 `gear_sonic/config/sim2sim/bumi3_sonic.yaml` 和 BUMI3 MJCF，
  SHA256 分别为
  `843756aef9332faa81f0f5ea71e95869e1c0d4604b0f4a11c64974773ead0d17`、
  `c4521504388c6eba296b8070fd80d73bb85c506b7346722031cefa3bcea11c04`；本轮没有修改配置、
  资产、关节顺序、ONNX 或训练参数。验证使用的 step 25300 `_g1.onnx` SHA256 仍为
  `562de4efda9cd2d8f90f368d304dcf990f9c59d10a41d14eaa2bf79215fb340b`。
- `gear_sonic/utils/mujoco_sim/bumi3_sim2sim.py` 新增 BUMI3 Mimic NPZ 兼容路径：当 NPZ
  没有顶层 `root_pos/root_quat`，但提供 `body_pos_w/body_quat_w` 时，按同文件
  `body_names` 精确定位 sim2sim 配置中的 `reference_root_body_name=base_link`，再提取
  `[T,3]` 根位置和 `[T,4]` 根四元数。实现没有使用数组第 0 项假设，也没有把 NPZ 中
  `anchor_body_name=waist_yaw_link` 错当成浮动根；anchor 元数据和根 body 是不同语义。
  缺少 `body_names`、根名称缺失/重复或 `[T,B,3/4]` shape 不一致都会 fail-fast。
- 同一 NPZ 路径现在同时识别重定向器使用的 `quaternion_order` 和既有
  `quaternion_convention`；显式顶层 root pose、qpos、训练 PKL 及 G1 风格 CSV 的原有优先级
  和默认行为保持不变。该修改位于 BUMI3 专用 sim2sim 模块，不改变 G1/H2 通用部署逻辑。
- `gear_sonic/tests/test_bumi3_sim2sim.py` 新增正反两个回归：正向 fixture 故意把
  `waist_yaw_link` 放在第 0 位、`base_link` 放在第 1 位，确认加载结果仍取命名 base；反向
  fixture 缺少 `base_link`，确认明确报错而非退回索引 0。完整该文件结果为
  `15 passed in 2.77s`，其中既有训练 PKL 和 G1 风格 CSV 测试继续通过；相邻锚点语义测试为
  `2 passed in 0.04s`。
- 对本地
  `/home/weili/robot_retargeter/output_data/bumi3_requested_20260901_50hz/mimic_npz/bumi3`
  当前 8 个真实 NPZ 逐条运行标准 `run_bumi3_sim2sim.py --validate-only --provider cpu`，
  `8/8` 全部输出 `BUMI3_SIM2SIM_VALIDATE_ONLY=PASS`。现场读取均为 50 FPS、21 关节、
  22 body、wxyz 四元数，共 `32675` 帧；不能沿用旧记录中的 36675 帧。随后对
  `CFmvaQiCW6I_40_0_900_dancer_00.npz` 运行 2 秒 headless、非实时 MuJoCo smoke，完成
  100 个控制步和 1170→21 ONNX 推理，最终 root height 约 `0.24052 m`、最大绝对 torque
  约 `42.76570`。该 smoke 只证明加载、reset、观测、推理和动力学链路可执行；根高度明显
  下降，不能解释为动作质量、长时稳定性或真机安全通过。
- 两个修改文件的 `compileall` 与 `git diff --check` 通过；当前 `.venv_sim` 未安装
  `ruff`，因此没有伪称执行 ruff。pytest 临时目录由测试框架管理，本轮没有生成需保留的
  checkpoint、ONNX、视频或日志；本地 8 条原始 NPZ 与正式模型均未改写。兼容分支如需
  回滚，应对本轮提交创建反向提交，不得 reset/clean 覆盖用户工作。
- 功能、测试和本节记录已提交为
  `b00552b5e9ca93755769bbdaf3d6fe39474d5cf0` 并推送 GitHub；服务器仓库修改前位于
  `fe16d959f17c6c678972d1b47406e6764e47943a` 且工作区干净，随后在同名 feature 分支执行
  `git pull --ff-only`，快进到 `b00552b` 后仍干净。服务器使用 `liwei_lab` 环境复跑完整
  `test_bumi3_sim2sim.py`，结果为 `15 passed in 4.42s`。同步和测试没有停止或重启正式
  训练；最终检查时 8 个 worker 全部存活并继续到 iteration `25921`。

## 2026-09-03：修正通用 quaternion delta 的符号和整数帧时间对齐

### 1. 修改边界与问题定位

- 本轮位于 `feature/bumi-native-sonic-full-training`，起始 HEAD 为
  `ee748ac9468d815daa7213d8cc6e612408f73e19`，本地和 GitHub 同名分支修改前 ahead/behind
  为 `0/0`；用户原有未跟踪 `g1.tar.gz` 保持未读取、未修改、未暂存和未删除。
- 对服务器真实数据各抽取 40 条 motion 的修改前审计表明：BUMI 的相邻 FK 四元数中有
  `9411/713748` 个符号跳变，覆盖 `34/40` 条动作；旧 MotionLib 角速度相对符号修正后的
  结果 RMSE 为 `16.37%`，修正结果相对独立 SciPy Rotation 有限差分为 `0.081%`，而仅由
  前向区间改成整数帧中心差分还会带来 `8.86%` 的相对差异。G1 同样有 `1486/191968`
  个跳变、覆盖 `35/40` 条动作，三项相对差异分别为 `17.77%`、`0.165%` 和 `11.26%`。
  因而问题不是 BUMI 重定向数据独有，而是 BUMI/G1 共用的 SONIC quaternion delta
  实现同时存在 `q/-q` 双覆盖符号错误和半帧时间错位。
- 修改前正式八卡训练仍为
  `sonic_bumi3_base_anchor_v2_scratch_100k-20260902_164548`，launcher PID `21266`、worker
  PID `21445-21452` 全部存活。已独立确认编号 checkpoint `model_step_026000.pt` 大小为
  `391203747` bytes、SHA256 为
  `7393d5a19f2f580b39fb93fa0f140ea1e0ada99b2960b8f549a5b23870ee3cb3`，可完整
  `torch.load` 且 `state.global_step=26000`、`max_steps=100000`、
  `episode=851968000`。该旧 run 和 checkpoint 将保留，仅停止精确匹配的训练进程。

### 2. 通用实现与调用路径

- `gear_sonic/isaac_utils/rotations.py` 新增
  `quat_to_shortest_rotation_vector()`：先按标量部非负规范化相对四元数，再以稳定的
  `2*atan2(||v||, w)` 求最短弧 rotation vector。它同时显式支持 `xyzw` 和 `wxyz`，
  不再让同一物理旋转的 `q` 与 `-q` 产生方向相反的角速度。
- 同文件新增 `quat_sequence_angular_velocity()` 作为唯一通用序列契约。内部帧通过
  `q[t+1] * inverse(q[t-1]) / (2*dt)` 与整数帧 `t` 对齐，首尾采用相邻区间单边
  差分；一帧返回零，两帧在两个端点复用唯一合法区间，并对非正 `dt` fail-fast。
- `torch_humanoid_batch.py` 的 BUMI/G1/H2 Robot FK body 路径和 `skeleton.py` 的
  `SkeletonMotion` 路径均改为调用该公共函数，并保留历史 `sigma=2`、时间轴 `-3` 的
  高斯滤波；滤波返回值显式恢复输入 dtype/device。`motion_lib_base.py` 的 object
  `wxyz` 角速度路径也切到同一实现，消除另一个复制的旧前向差分分支。位置、线速度、
  关节位置、接触和原始 pose 数据均未改动。
- 修改前后 SHA256 分别为：`rotations.py`
  `b800cc97757ea452e04c12b16b70a2847b5cb08c041b521e32e7347b05479d99 ->
  6642e6890fb9162fe6af96f828518f1f3f3f79bbe7e699527a25d997e22e6ac7`；
  `skeleton.py`
  `9e593ed72145add9e7b5711602913494128b0853a3ee3a682dfc4609deed0b8e ->
  6c398995b8068a47365a94b42af0c5360b06506b1e1663cc3f869287aafc6250`；
  `torch_humanoid_batch.py`
  `41e5d4a44497547784a1f22fb968d112039f0a7b0eb85e166022e6ac3c4988d1 ->
  b1cff99925690f56abb79926438225d71f535369261df1bb53e9b583f3efd335`；
  `motion_lib_base.py`
  `66425b5f647cef4b9ae4ee799d35dfe226906b17f5210dc51477ccc6a8a3019c ->
  0f938b41fce8aae0aa218e72cec0fd3f95116b423cb785edc96eb0566fbf7fb0`。

### 3. 回归测试与当前验证边界

- 新增 `gear_sonic/tests/test_motion_lib_angular_velocity.py`，文件头详细记录测试目的，
  SHA256 为 `03ae2f1606c9b08396a023de86f39a16263c82286d71f17dc06ba819d90652ac`。
  解析测试覆盖：`xyzw/wxyz` 两种顺序的 `q/-q` 随机符号翻转不变性、二次角度轨迹的
  整数帧中心差分、一帧/两帧边界和高斯滤波有限值。初版 float32 小角度测试暴露旧
  `acos` 公式约 `1e-4 rad/s` 的数值误差后，公共转换改成上述 `atan2` 形式，而不是放宽
  测试掩盖误差。
- 本地 SONIC 环境最终运行新增测试及 tracking anchor、BUMI 配对/转换/三源索引、
  BUMI sim2sim 回归，共 `49 passed, 4 warnings in 5.88s`；五个修改 Python 文件的
  `compileall` 与 `git diff --check` 均通过。warning 仅为已有 `\*` 转义和
  `scipy.ndimage.filters` 弃用提示。
- 另一次扩大到 `gear_sonic/tests/test_input_readers.py` 的收集尝试因当前本地 SONIC 环境
  缺少可选依赖 `msgpack` 而在 collection 阶段退出，该次没有测试被执行；环境同时没有
  `ruff`/`black`，因此未伪称通过这些检查。服务器真实 BUMI/G1 重新计算、远端同步、旧
  训练停止和新八卡启动将在本功能提交推送后执行，并在本节后续记录精确结果。
- 本修改会改变所有共用 MotionLib 的 reference angular velocity 标签，旧模型权重结构
  本身仍兼容，但旧 optimizer/critic 学到的是错误标签。按用户要求新训练将使用
  `resume=false checkpoint=null auto_load_latest=false` 从零开始；这次修复可解释
  body angular velocity reward 的系统性异常，但不能单独证明它是训练质量的唯一根因。
  如需回滚，必须对本轮提交创建反向提交，不得 reset/clean 覆盖用户工作。

### 4. 服务器同步与真实 BUMI/G1 有限差分复验

- 功能、解析测试和初始记录提交为
  `5b863b205ccf0be9a4aa1273e2fdf2180dd67b0e`，已推送 GitHub。`noetix-volc`
  工作区修改前干净，在同名 feature 分支由 `ee748ac` 执行 `git pull --ff-only` 快进到
  `5b863b2`，同步后仍干净；服务器 `liwei_lab` 环境复跑与本地相同的测试集合，结果为
  `49 passed, 4 warnings in 8.23s`。
- 修复后按固定 seed `20260903` 重新抽取 40 条真实 BUMI motion：三个数据源分别为
  `bumi3_smpl_97660_v1` 20 条、`hq4_pass50_v1` 10 条、`hq_all_v2` 10 条，共
  `59919` 帧、50 Hz，并比较 12 个训练 tracking body。MotionLib 相对独立 SciPy
  `Rotation` 中心相对旋转及相同 `sigma=2` 滤波的相对 RMSE 为
  `5.289165391503483e-07`、最大绝对误差 `1.0309906383398904e-05 rad/s`；原始 FK
  仍有 `9486/718548` 个相邻符号跳变并覆盖 `34/40` 条 motion，但随机逐帧翻转一半
  `q/-q` 后相对 MotionLib 的 RMSE 和最大绝对误差均为 `0.0`，判定
  `FINITE_DIFF_CONSISTENCY PASS`。
- 同样以固定 seed 抽取 40 条真实 G1 motion，共 `14152` 帧、50 Hz、14 个既有
  tracking body。MotionLib 相对独立 SciPy 的相对 RMSE 为
  `6.034882924675027e-07`、最大绝对误差 `1.0280309380723829e-05 rad/s`；原始 FK
  有 `1526/197568` 个相邻符号跳变并覆盖 `35/40` 条，随机符号翻转后的 RMSE 和最大
  绝对误差同样均为 `0.0`，判定 `FINITE_DIFF_CONSISTENCY PASS`。两次审计均直接通过
  MotionLib 重新做 Robot FK，没有修改、平滑或回写任何源 PKL，也没有生成临时数据集。

### 5. 停止旧训练并从零启动新八卡正式训练

- 在功能提交已推送、服务器测试和真实数据复验通过后，向精确 tmux 会话
  `sonic_bumi3_base_anchor_v2_8gpu` 发送一次 `Ctrl-C`。8 秒后旧 launcher PID
  `21266` 和 worker PID `21445-21452` 已全部退出，GPU compute PID 为空，旧训练 tmux
  会话自动结束；独立的 `tensorboard_bumi3_base_anchor_v2` 会话继续保留。旧 run、日志和
  checkpoint 均未删除，停止后再次确认 `model_step_026000.pt` SHA256 仍为
  `7393d5a19f2f580b39fb93fa0f140ea1e0ada99b2960b8f549a5b23870ee3cb3`。
- 新正式 tmux 会话为 `sonic_bumi3_qvel_centered_v1_8gpu`，run 为
  `/data/sonic_bumi3/runs/TRL_BUMI3_Track/manager/universal_token/all_modes/sonic_bumi3_qvel_centered_v1_scratch_100k-20260903_151155`，
  tee 日志为
  `/data/sonic_bumi3/formal_logs/sonic_bumi3_qvel_centered_v1_8gpu_20260903_151155.log`。
  启动源码 HEAD 固定为 `5b863b2`，使用端口 `29517`、8 个 accelerate process、每卡
  4096 env 进程中的一份环境分片，并显式设置 `resume=false`、`checkpoint=null`、
  `auto_load_latest=false`、`num_learning_iterations=100000`，因此既不是 resume 旧
  optimizer，也没有加载旧 policy 权重。
- 落盘 resolved `config.yaml` SHA256 为
  `96fee8b8c1ccf7b008816e3a2950c051eec3a62215bfc8f7b7ef19388df57b5c`。其中 Robot/SMPL
  三源索引仍为 `bumi3_sonic_three_source_base_anchor_v2/train/{robot_all,smpl_all}`，
  `exclude_motion_keys=[]`、`target_fps=50`、`robot_type=bumi3`、MJCF 为 `bumi3.xml`、
  encoder 恰为 `g1/smpl`。运动 anchor 为 `base_link`；tracking body 为当前 12 个 body，
  五点奖励使用 `waist_yaw_link`、双肘和双踝；肘部 anti-shake 开启；COM 和质量随机化都
  精确作用于 `waist_yaw_link`。这也是此前旧 run 尚未使用的新 12-body/五点配置。
- launcher PID 为 `685367`，八个直属 worker PID 为 `685524-685531`；验证时它们分别在
  8 张 GPU 上各占约 `13.0-13.7 GiB`，不是单卡或仅创建 tmux。训练已实际到 iteration
  `61`、`47972352` timesteps，该轮 `error_body_lin_vel=0.7100`、
  `error_body_ang_vel=3.1062`；日志中 `Traceback`、`OutOfMemoryError`、
  `CUDA out of memory`、`NCCL error`、`RuntimeError` 和 `Error executing job` 均为 0。
- iteration 50 原子保存的首个 `last.pt` 已在训练继续运行时完整 `torch.load`：当时大小
  `390761384` bytes、SHA256
  `b624bc7c6f1c6758747b57d54df28ec0b7af6da3c0071eecbf8dbdded11a48b8`，
  `state.global_step=50`、`max_steps=100000`、`episode=1638400`，并含 policy 45 个
  tensor、value 17 个 tensor 以及 optimizer、scheduler、env state。该哈希只对应
  iteration 50 的当时 inode；正式 `last.pt` 会继续被后续 checkpoint 原子更新。
- 启动日志中的 headless Vulkan/renderer 提示与旧 run 一致，不伴随 Python traceback、
  OOM、NCCL 错误或非零退出。当前证据证明修复后的 reference velocity 已进入新正式训练，
  且多卡早期迭代和 checkpoint 链健康；iteration 61 的单点误差不能替代长期趋势、最终
  动作质量、动力学鲁棒性或真机安全评估。
- 完成功能提交后，本地工作区并行出现的 sim2sim 零原点改动，已由另一工作流独立提交并
  推送为 `91ce2ff` 和服务器交付记录 `9bdb7e8`；本轮没有把这些文件混入 `5b863b2`。
  新训练启动时源码固定为当时 HEAD `5b863b2`。后续两个提交只改变 sim2sim reference
  loader/验证，以及 `bumi3.xml` 的 world ground geom 高度，不改变 quaternion delta、
  MJCF body/关节层级或训练 Hydra 配置，也不会改变已经加载到运行进程中的 MotionLib；
  因而无需停止并重建已经健康运行的新训练。本轮最终提交仍只暂存本修改记录，原有未跟踪
  `g1.tar.gz` 继续保留。

## 2026-09-03：SONIC sim2sim 地面与参考动作水平原点统一为零

### 1. 修改边界与现场状态

- 本轮位于 `feature/bumi-native-sonic-full-training`。开始检查时 HEAD 为
  `ee748ac9468d815daa7213d8cc6e612408f73e19`，本地相对 GitHub ahead/behind 为
  `0/0`；当时用户已有 `rotations.py`、`motion_lib_base.py`、`skeleton.py`、
  `torch_humanoid_batch.py` 和新增角速度测试的独立修改，以及未跟踪 `g1.tar.gz`。
  本轮实施期间该组角速度修改由外部流程提交并推送为
  `5b863b205ccf0be9a4aa1273e2fdf2180dd67b0e`，本轮没有暂存、改写或回退其中任何内容；
  后续 sim2sim 修改以该新 HEAD 为父提交，未跟踪 `g1.tar.gz` 仍保持原样。
- 本轮只修改 BUMI3 的 MuJoCo sim2sim XML、专用动作加载器、对应测试/验证器和使用文档；
  不修改训练 URDF、训练 Hydra 配置、21 关节顺序、控制频率、网络、checkpoint、ONNX、
  原始 NPZ 或 `initial_root_position=[0,0,0.4744]`。实际 sim2sim 配置 SHA256 仍为
  `843756aef9332faa81f0f5ea71e95869e1c0d4604b0f4a11c64974773ead0d17`；验证使用的
  `model_step_025300_g1.onnx` SHA256 为
  `562de4efda9cd2d8f90f368d304dcf990f9c59d10a41d14eaa2bf79215fb340b`。
- 修改前 SHA256：`bumi3.xml`
  `c4521504388c6eba296b8070fd80d73bb85c506b7346722031cefa3bcea11c04`，
  `bumi3_sim2sim.py`
  `cd3c0d250c55549a4f23c3af42edc0b4c1f57e724e9452b647e0df483d2b0fb1`，
  `test_bumi3_sim2sim.py`
  `b5a5e7f8b667cb69215cfea6f5e877cc80ffb7bd9540c4889015ab46f2b09730`，
  `validate_bumi3_sim2sim.py`
  `09638241eefbe080073435d71f2ec5755ca5ce954fcdca9b2c9bb52aa90e1889`，
  `validate_bumi3_integration.py`
  `165e0ec366ac1f3b841a1529daa497f36ed713bf1033ba6f151dbee5d670d9fa`，
  `bumi3_sim2sim.md`
  `b135da6efa632cd9199b2c14a2c838fd57d107d381cf687744dd9aedc52090e9`。

### 2. XML 与加载器的实际修改

- `gear_sonic/data/assets/robot_description/mjcf/bumi3.xml` 把唯一 `ground` geom 的
  `z` 从 `-0.02 m` 改为 `0 m`，并同步中文注释。灯光、机器人惯量、碰撞几何、接触
  bitmask、摩擦和全部 actuator 均未改变；新 XML SHA256 为
  `28d55b3b460c2731ba478c083c780948b5175132cd3b7b1a73e8d6cbe6fd6547`。
- `gear_sonic/utils/mujoco_sim/bumi3_sim2sim.py` 在根位置完成 shape/有限值检查后，复制
  `root_position` 并对整段执行 `root_position[:, :2] -= root_position[0, :2]`。因此每条
  含根平移的 PKL、NPZ 和 CSV 动作都会以首帧水平位置 `(0,0)` 开始；所有帧使用同一个
  平移量，逐帧差分和相对首帧的完整水平轨迹保持不变。实现不原地修改输入数组，也不改
  `root z`、根四元数、关节、速度或 FPS；不含根平移的旧 CSV 继续使用配置回退值。
- 本轮没有随地面上移而改回退根高度。修改前的定向 MuJoCo 预检表明，在 `ground_z=0`
  且回退根高仍为 `0.4744 m` 时静态姿态接触数为 0、地面穿透为 0；额外把根高抬升
  `0.02 m` 只会增大悬空距离，没有数据依据。
- `gear_sonic/tests/test_bumi3_sim2sim.py` 更新 PKL/命名 body NPZ 预期，显式断言首帧
  `x/y=0`、整段 `np.diff(root_position)` 与源数据一致、`z` 原样保留，并把 XML 地面门禁
  更新为 0。两个验证器同步地面数值和新 MJCF 指纹；使用文档增加水平归零契约以及旧
  `Z=-0.02 m` 数据的兼容风险。修改后上述 Python、测试、验证器和文档 SHA256 依次为
  `6d3f4077fe06f2f11c8655dd801d739b460db6ff491600bfc31e045c7f6d3003`、
  `461f75eeb3da6fbef4ddb1f7da030bfce9530ee522370cba40f449e1ac6436cb`、
  `bb39727b496c548e9c35dbfefedd3b1655a1d391a6e133092efb6b53c1666f50`、
  `6a7f647c26ea73c312c18561e365d48ad238862c628f05f61e863d39aea72566`、
  `76292b4fea42fcb9e76e3092cdb2d5e7a654366f44a0a5565a7093e084db46f7`。

### 3. 实际验证结果与结论边界

- `.venv_sim/bin/python -m pytest -q gear_sonic/tests/test_bumi3_sim2sim.py
  gear_sonic/tests/test_tracking_anchor_semantics.py` 最终复验结果为 `17 passed in 3.37s`
  （修改后的首次运行同为 17 项通过，耗时 2.91 秒）。
  `validate_bumi3_sim2sim.py` 完整 100 控制周期零策略静态参考 smoke 通过，输出锁定
  `nq=28,nv=27,nu=21`、22 bodies、22 visual mesh、14 collision geom、
  `ground_z=0`、静态 reset 无自碰撞/地面穿透、1170 维输入和 21 维输出。零策略 2 秒末
  root height 为约 `0.071684 m`，这里只证明接口与数值链路可运行，不证明策略稳定性。
- 对
  `/home/weili/robot_retargeter/output_data/bumi3_requested_20260901_50hz/mimic_npz/bumi3`
  当前 8 条真实动作共 `32675` 帧逐条核验：8/8 加载后首帧 `x/y=(0,0)`，每帧 `z` 与
  原文件逐点一致，整段水平位置严格等于 `source_xy-source_xy[0]`。配合上述 step-25300
  ONNX 的标准 `run_bumi3_sim2sim.py --validate-only` 也为 `8/8 PASS`。
- `ground_z=0` 后，8 条动作中 7 条首帧产生地面接触；`hgEy_U-6Nbc_27_0_1290_dancer_00`
  仍保留数据中的约 1 mm 离地间隙。7 条有接触动作的首帧最深接触距离约为
  `-14.10 mm`，其余动作约为 `-0.34` 至 `-7.42 mm`；这是原始 `root z` 相对零地面的
  实测结果。本轮按用户要求不做垂直归零，不能把“产生接触”解释成 8 条动作都无穿透。
- 使用 `/home/weili/miniconda3/envs/sonic/bin/python` 和 AppLauncher 运行完整
  `validate_bumi3_integration.py` 通过，静态门禁确认 21 DoF、22 bodies、50 Hz、action 21；
  未传 `--smoke`，因此没有创建 Isaac 环境执行真实数据 reset/step。第一次尝试在
  `.venv_sim` 中因缺少 Hydra 未进入验证；更新第二处预期 MJCF 哈希后，正确 SONIC 环境
  退出码为 0。platforminfo 的 CPU package 提示是现有 Isaac 启动环境信息，不影响门禁。
- 修改文件的 `compileall`、`git diff --check` 均通过。本轮只读取正式 ONNX 和 8 条原始
  NPZ，没有生成 checkpoint、视频、日志或临时运行目录，因此没有一次性验证产物需清理。
  旧的按 `Z=-0.02 m` 制作的大集动作切换到本 XML 后可能出现 1--2 cm 初始穿地，应在
  数据转换或专用 XML 中显式处理；不能依赖本水平归零分支修改高度。回滚时应对本轮功能
  提交创建反向提交，不得 reset/clean 或覆盖用户角速度修改和未跟踪文件。

### 4. GitHub 与 noetix-volc 交付复验

- 功能、测试、资产、验证器、文档和本节前三部分记录已提交为
  `91ce2ff8868ea57a61acea0f42b53b2fef7bd072`，并推送到 GitHub 的
  `feature/bumi-native-sonic-full-training`。提交前逐文件暂存并核对，只有本轮 7 个文件
  进入提交；本地未跟踪 `g1.tar.gz` 没有被读取、暂存、修改或删除。
- `noetix-volc` 的 `/home/liwei/GR00T-WholeBodyControl` 同步前位于同名 feature 分支、
  HEAD 为 `5b863b205ccf0be9a4aa1273e2fdf2180dd67b0e` 且工作区干净；执行
  `git pull --ff-only origin feature/bumi-native-sonic-full-training` 后快进到
  `91ce2ff8868ea57a61acea0f42b53b2fef7bd072`，没有 stash、reset、merge 或覆盖服务器文件。
- 服务器使用 `/root/miniconda3/envs/liwei_lab/bin/python` 复跑 sim2sim 与锚点测试，结果
  为 `17 passed in 4.47s`；随后运行 `validate_bumi3_sim2sim.py --skip-smoke` 通过，输出
  再次确认 MJCF SHA256 为
  `28d55b3b460c2731ba478c083c780948b5175132cd3b7b1a73e8d6cbe6fd6547`、
  `ground_z=0`、静态 reset 无自碰撞/地面穿透、1170 维输入和 21 维动作。复验后服务器
  工作区保持干净。本次同步和测试没有启动、停止或重启正式训练，也没有创建持久产物。

## 2026-09-07：修正 BUMI3 强点/高度终止、坏动作隔离与 PPO 学习率控制

### 1. 修改边界与现场保护

- 本轮位于 `feature/bumi-native-sonic-full-training`，起始 HEAD 为
  `cd5a00a867a9634941f8946a5172a04501ad79b0`，本地与 GitHub 同名分支 ahead/behind 为
  `0/0`。修改前工作区只有用户未跟踪的 `g1.tar.gz`；本轮没有读取、修改、
  暂存、删除或打包该文件。
- 修改范围限于 BUMI3 Hydra 训练覆盖、通用 PPO trainer、通用 MotionLib 中
  默认关闭的可选动力学门禁/隔离、相关日志、集成校验与单测。没有修改
  URDF、MJCF、mesh、关节/body 顺序、动作数据、checkpoint、ONNX、正式训练目录
  或 sim2sim 实现。
- BUMI3 执行器速度上限沿用当前 SONIC
  `gear_sonic/envs/manager_env/robots/bumi3.py`（SHA256
  `53bc574948e4faabf8887a8d552e5d1ca1fdf71cb50f1f2a59c3c50f17f0ff8c`）中的腰部
  `9 rad/s`、手臂/腿/脚 `12 rad/s`。该数值同时核对了用户指定的
  `/home/weili/legged_lab/source/NoetixRobot/NoetixRobot/assets/robots/bumi3/bumi.py`，该参考
  工作区当时有用户未提交修改，因此锁定读取时 SHA256 为
  `74aaeca9da615c50e3749e4f103bbf713b83443d9cb16fab08edfd320227c03e`。参考 MJCF/URDF
  SHA256 分别为
  `041c81e8176c7f375302796deca28b141891a3c097d8e341e8d967b735466edf` 和
  `174c1747019ced64267e74244bf89f3746856c90c30f88e4f162582ebc486476`；本轮仅读取核对，
  没有修改 `legged_lab` 任何文件。SONIC BUMI3 MJCF 仍为既有 SHA256
  `28d55b3b460c2731ba478c083c780948b5175132cd3b7b1a73e8d6cbe6fd6547`。

### 2. BUMI3 局部强点与高度 termination

- `gear_sonic/config/exp/manager/universal_token/all_modes/sonic_bumi3.yaml` 将
  `reward_point_body` 从“腰部+双肘+双脚踝”改为仅
  `waist_yaw_link + l_elbow_pitch_link + r_elbow_pitch_link`，并将 offset 同步缩减为 3 项。
  双脚仍受全身 tracking reward、`foot_pos_xyz` termination、接触与脚部加速度约束，
  但不再叠加 `std=0.1` 的局部强点奖励，避免多个高刚度目标同时拉扯脚踝。
- BUMI3 为 `anchor_pos` 和 `ee_body_pos` 同时覆盖
  `root_height_threshold=0.40 m`、正常姿态 `threshold=0.12 m`、低姿态
  `down_threshold=0.25 m`。两处共用同一个低姿态分类边界，避免同一帧在锚点和
  末端 termination 中被不同解释；`0.75 m` 这个对约 `0.46 m` 高 BUMI3 近似
  关闭低姿态高度约束的数值已移除。G1/H2 的 reward point 和 termination 配置
  没有被这个 BUMI3 专用覆盖改写。
- 该配置 SHA256 从
  `36df5a1954c2985adcee25b9ad35c48b99da94916757487a6a3fb6149eb31af5` 变为
  `1dbb31da447cd14c3f741f0852e2b40c9e7f17d83c4bbed4c75abca09dd7c765`；集成验证器同步
  锁定了三强点、两套高度阈值和下述学习率/隔离配置。

### 3. 坏动作动力学门禁与 quarantine

- `gear_sonic/utils/motion_lib/motion_lib_base.py` 新增原始 DOF 轨迹动力学门禁。它在
  freeze-frame、上肢拼接和噪声增强前，按动作自身 FPS 对整条有效原始 DOF 做
  中心有限差分，端点使用单边差分。空轨迹、非有限 FPS/阈值、关节数或速度上限
  名称契约不一致时直接失败，不在随机 `max_len` 片段上得出不稳定结论。
- BUMI3 门禁配置为：速度超出执行器上限的 DOF-帧占比不得超过
  `0.005`，单点最大速度比不得超过 `2.0`，最大加速度比不得超过 `1.0`。
  加速度分母为 `velocity_limit * fps`，因而 `1.0` 表示一个数据采样周期内跨越
  一整档速度范围。该门禁只是“可否进入隔离”的必要条件，不是接触、力矩、
  仿真或硬件安全证明。
- quarantine 必须同时满足“原始参考动力学门禁失败”和“训练中连续高失败”。
  为避免复用原有“帧曝光量/分箱长度”统计导致长动作失败率被稀释，新实现
  单独记录动作级结果：提前 termination 计一次失败，自然到达动作末帧计一次
  通过。动作至少有 `5` 次结果、距上次评估新增至少 `3` 次、失败率连续 `3`
  个全 GPU 同步评估点不低于 `0.90` 后才永久进入 quarantine；一次有足够新证据的
  低失败评估会清零连续计数。
- 被 quarantine 的动作只保留 `uniform_sampling_rate` 对应的低频基线采样，不再
  从高失败率获得困难采样放大；它们不会从数据集永久删除。动力学失败、
  动作结果计数、连续评估和 quarantine 掩码均进入 env checkpoint；旧 checkpoint 缺少
  新字段时保持零值并继续恢复旧分箱统计。日志新增门禁失败动作数、已隔离
  动作数、已获得结果的动作数以及这些动作的平均/最大失败率。其他机器人
  未显式开启 `dynamics_gate/quarantine` 时保持旧行为。

### 4. Actor/Critic optimizer、整轮 KL 与 checkpoint 恢复

- `gear_sonic/trl/trainer/ppo_trainer.py` 不再使用 HuggingFace 默认的“仅按
  weight decay 分两组”方式。所有可训练参数先按 `policy.* -> actor`、
  `value_model.* -> critic`、其他附加模块 `-> auxiliary` 分角色，每个角色内再保留
  decay/no-decay 差异。每组保存稳定的角色名、组名和 schema 版本，并校验全部
  参数恰好被覆盖一次。
- `ppo_im_phc.yaml` 的 Actor 保持 `2e-5`，Critic 从未被代码使用的宣称值
  `1e-3` 改为真正作用于 Critic 参数组的 `3e-4`；BUMI3 入口显式重申两个数值。
  这是通用 PPO 缺陷修正，因此同样使用 `ppo_im_phc` 的 G1/H2 也会真正获得独立
  Critic LR；其 reward、termination 和数据契约不变。
- KL 不再在 `_compute_ppo_loss()` 的每个 micro/minibatch 中即时改 LR。本轮所有
  PPO epoch/minibatch/microbatch 结束后，`_get_train_metrics()` 一次汇总所有 GPU 的
  KL 均值、中位数、P95 和最大值；控制器每个 iteration 只使用整轮均值调整一次
  下一轮 Actor LR。调整函数从 optimizer 实际 Actor 组读取当前值，只写 Actor 组；
  Critic 和 auxiliary LR 保持不变。
- `schedule=adaptive` 时 `create_scheduler()` 明确返回 `None`，不再创建或 step HF
  constant scheduler，消除 KL 刚降低 Actor LR 就被 scheduler 恢复初始 base LR 的冲突。
  非 adaptive 配置仍沿用 HuggingFace scheduler。日志从可能过期的
  `args.learning_rate` 改为直接记录 `lr/actor_actual`、`lr/critic_actual`，存在
  auxiliary 时还记录 `lr/auxiliary_actual`；兼容旧字段 `lr` 现等于实际 Actor LR。
- 新 checkpoint 直接保存具名参数组及各自实际 LR。旧 checkpoint 的两组
  decay/no-decay optimizer 在 resume 时按当前模型稳定参数名顺序迁移 Adam 动量：
  Actor 继承旧 optimizer 中实际 LR，Critic 保留动量但启用当前独立 `3e-4`。
  参数数量/分组不能确定匹配时直接报错，不猜测恢复。恢复后会立即校验并打印
  各角色实际 LR；adaptive 模式明确忽略旧 HF scheduler 状态。
- 关键文件修改前 -> 修改后 SHA256：`ppo_im_phc.yaml`
  `57fec213ced45071d501548ea4bb31be1ca83aedfa6b5bdbdab056efae853632 ->
  fc9c4512c69dec45ad5a7d78b0d7969b40c67fe85d3d3b2ebbfb1817a97f6044`；
  `ppo_trainer.py`
  `822261d5eef7043c183dfe578a7c70979c58a324b608c2eebdad4d49ec93e2f7 ->
  3132ac5a46df6cf91afb93005e2113a7dd7c1c1e69ba278edeb556bc8bddd1e0`；
  `motion_lib_base.py`
  `0f938b41fce8aae0aa218e72cec0fd3f95116b423cb785edc96eb0566fbf7fb0 ->
  e25effe8c39d33af2fd79fa37dc7960bcb0e49c1171bad80eb20530c68c72164`。

### 5. 测试结果、已知边界与回滚

- 新增 `gear_sonic/tests/test_ppo_optimizer_and_kl.py` 和
  `gear_sonic/tests/test_motion_lib_adaptive_quarantine.py`，两个新文件均以详细中文模块
  docstring 说明验证范围。定向测试覆盖具名 Actor/Critic decay/no-decay 组、
  KL 仅改 Actor、adaptive scheduler 为空、旧/新 checkpoint 的 LR 和 Adam 状态恢复、
  每轮唯一 KL 调整点、平滑/尖峰 DOF 门禁、名称契约、双条件 quarantine、
  低失败证据重置、真实动作结果计数以及“隔离后只保留 uniform 分量”。
- 本地使用 `/home/weili/miniconda3/envs/sonic/bin/python` 运行新增定向测试，结果为
  `13 passed, 1 warning in 2.76s`。随后运行 BUMI3 sim2sim、MotionLib 角速度、
  tracking anchor、配对帧窗口、三源数据集、PASS50 与旧 BUMI3 数据准备的全部
  现有相关回归，结果为 `62 passed, 3 warnings in 6.90s`。warning 只有既有未知
  `\*` 转义和 `scipy.ndimage.filters` 弃用提示。回归首次暴露两个用
  `__new__` 构造最小 MotionLib 的旧测试缺少新字段，实现已改为“未配置时门禁
  默认关闭”，同一集合重跑后 62 项全部通过。
- 将 `gear_sonic/tests/test_input_readers.py` 也加入整体收集的尝试因本地 SONIC
  环境缺少可选依赖 `msgpack` 而在 collection 阶段退出，该文件未执行；本轮没有
  安装依赖或修改用户环境。四个修改 Python 实现/验证器的 `py_compile`、
  `git diff --check`、`uvx ruff check --select E9,F63,F7,F82` 均通过；两个新测试文件
  完整 `ruff check` 和 `ruff format --check` 通过。四个历史 Python 大文件在起始 HEAD
  就不符合当前 Ruff formatter，因此本轮没有借机整文件格式化并混入无关 diff。
- 直接调用集成验证器的仓库资产、XML/mesh 拓扑和 Hydra resolved 配置校验
  通过，确认 `21 DoF / 22 body / 50 Hz / action_dim=21`、三强点、两组高度阈值、
  21 关节速度门禁顺序和 Actor/Critic LR。本地未启动 Isaac AppLauncher，未执行
  环境 reset/step、训练 smoke、完整训练、动作质量或真机验证；用户本轮要求的是
  修改并同步代码，没有授权启动或重启正式训练。
- quarantine 阈值是根据当前问题和保守原则设定的可观测起点，不是数据集全量
  统计最优值。动力学门禁只在动作被加载时计算；默认全 GPU 自适应统计每
  `200` iteration 同步一次，因而连续 3 次确认不是立即删样本。后续必须通过
  `adp_samp/*`、KL 分位数、实际 Actor/Critic LR、value loss、终止率和 replay 联合
  判断效果，不能只看 reward 或一个早期 checkpoint。
- 本轮没有生成 checkpoint、ONNX、视频、渲染、日志或临时训练目录，因此没有
  一次性产物需要清理。如需回滚，应对本轮后续记录的功能提交创建反向提交，
  不得 reset/clean 或覆盖用户未跟踪文件。GitHub/noetix-volc 的精确提交与远端复验
  将在完成推送和 `git pull --ff-only` 后追加记录。

### 6. GitHub/noetix-volc 交付与真实数据门禁抽样

- 上述功能、配置、测试和记录提交为
  `5c44c77e4fb19cc654cd0bab40ef7f51eea05c19`，已推送到 GitHub
  `feature/bumi-native-sonic-full-training`。首次 push 在网络层长时无响应后仅中断该
  push 客户端；`git ls-remote` 确认远端仍为 `cd5a00a` 且未发生半推送，随后用
  BatchMode、连接超时和 keepalive 非交互重试，正常快进 `cd5a00a..5c44c77`。
  没有 force push、rebase、reset、stash 或改写历史；本地工作区仍只保留未跟踪
  `g1.tar.gz`。
- `noetix-volc:/home/liwei/GR00T-WholeBodyControl` 同步前为同名 feature 分支、
  HEAD `cd5a00a867a9634941f8946a5172a04501ad79b0` 且工作区干净。执行
  `git pull --ff-only origin feature/bumi-native-sonic-full-training` 后快进到
  `5c44c77e4fb19cc654cd0bab40ef7f51eea05c19`，同步后仍干净。同步前后精确查找
  `train|accelerate|torchrun` 均只命中查询命令自身，没有正式训练进程；本轮没有启动、
  停止或重启训练。
- 服务器使用 `/root/miniconda3/envs/liwei_lab/bin/python` 复跑与本地相同的全部
  62 项相关回归，结果为 `62 passed, 3 warnings in 10.25s`；服务器 `py_compile`、
  `git diff --check` 和静态 Hydra/资产契约通过。随后运行完整
  `validate_bumi3_integration.py --device cuda:0`（未传 `--smoke`）退出码为 0，输出
  `BUMI3 原生 SONIC 集成验证通过`，运行时再次确认 21 DoF、22 body、50 Hz、
  Actor/Critic/decoder 维度与双向顺序。启动时仍有该 headless 节点的
  `omni.platforminfo` 循环依赖和 `ERROR_INCOMPATIBLE_DRIVER` Vulkan 提示，但未阻止非渲染的
  运行时配置校验；本次仍没有创建环境 reset/step，不能解释为仿真 smoke 通过。
- 服务器真实训练索引
  `/data/sonic_bumi3/datasets/bumi3_sonic_three_source_base_anchor_v2/train/robot_all`
  当时有 `95358` 条动作及 1 个 `metadata.pkl`：大集 `92443`、HQ4 PASS50
  `2816`、旧 HQ `99`。按每个来源文件名排序后的等距固定索引，分别只读抽取
  `256/128/99` 条，共 `468169` 帧执行新的整条原始 DOF 门禁。大集标记
  `87/256=33.98%`，HQ4 为 `0/128`，旧 HQ 为 `1/99=1.01%`。大集最大速度比
  P50/P95/max 分别为 `1.7249/3.6085/7.6240`，最大加速度比 P95/max 为
  `1.7608/3.7913`；HQ4 两项 max 只有 `0.9990/0.1480`。
- 这个抽样不是全量数据质量结论，但说明了不能把“门禁标记”直接等同于“删除动作”：
  否则可能一次隔离近三分之一的大集抽样。当前实现只把门禁失败作为必要条件，
  还必须在真实训练中累积足够结果且连续高失败才停止困难采样放大，与本轮设计目标
  一致。抽样过程只加载 PKL 并输出统计，没有回写数据、生成报告文件或修改训练索引。
- 最终远端复查时仓库工作区干净，Isaac 校验进程已退出，仍无训练进程。
  本节仅为交付证据文档追加，将作为独立 docs 提交推送后再在服务器执行一次
  `git pull --ff-only`，使代码与交付记录保持同一 HEAD。功能回滚目标为
  `5c44c77e4fb19cc654cd0bab40ef7f51eea05c19`，需创建反向提交；仅回滚本节文档时则反向
  后续 docs 提交即可。

### 7. 八卡重启首次运行暴露整数日志均值错误并修复

- 用户授权在 `noetix-volc` 重新开始八卡 BUMI3 SONIC 训练。启动前服务器仓库位于
  `feature/bumi-native-sonic-full-training`，HEAD 为
  `a1c0f8476ec7edae3e53b34fed3669ceb27eeb99` 且工作区干净；8 张 RTX 4090 D 均无
  compute process，显存约 `4 MiB`、利用率 `0%`。当前三源索引仍有 Robot `95358`、
  paired SMPL `95222` 个软链接，没有发现一级断链。旧
  `sonic_bumi3_qvel_centered_v1_8gpu` 已在 2026-09-07 05:56 跑满 `100000` iteration 并
  保存 `model_step_100000.pt`，残留 tmux 仅停在 shell；本轮只关闭该空会话，旧 run、
  checkpoint 和约 579 MB 正式日志均保留。
- 首次新 run 为
  `/data/sonic_bumi3/runs/TRL_BUMI3_Track/manager/universal_token/all_modes/
  sonic_bumi3_native_fullfix_v1_scratch_100k-20260907_174735`，正式故障日志为
  `/data/sonic_bumi3/formal_logs/sonic_bumi3_native_fullfix_v1_8gpu_20260907_174735.log`。
  命令使用端口 `29517`、8 个 accelerate rank、每 rank `4096` env，并显式设置
  `resume=false`、`checkpoint=null`、`auto_load_latest=false` 和 `100000` iteration。
  8 个 worker PID `2523586-2523593` 均完成环境创建并进入 `===training policy===`，但在首轮
  日志聚合时全部确定性退出；没有生成 checkpoint，也没有继续占用 GPU。
- 失败堆栈精确位于 `ppo_trainer.py:2142 -> TensorAverageMeterDict.mean_and_clear() ->
  TensorAverageMeter.mean()`，异常为 `RuntimeError: mean(): could not infer output dtype ...
  Got: Long`。根因不是 OOM、NCCL、数据断链或 PPO loss，而是本轮新加的
  `dynamics_gate_failed_motions`、`quarantined_motions`、`evaluated_motions` 三个计数由
  bool 张量求和后为 `torch.long`，通用日志平均器过去只处理浮点量并直接调用
  `cat.mean()`。故障 run 和日志作为正式诊断证据保留，不当作健康训练，也不从它恢复。
- `manager_env_wrapper.py` 在上述三个计数产生处显式 `.float()`，明确环境日志的可平均
  数值契约；`average_meters.py` 同时增加兜底，只把 integer/bool 累积量转为 float 后求均值，
  已有 float64 和 complex 指标不降精度。新增
  `gear_sonic/tests/test_average_meters.py`，以详细中文模块说明覆盖 float64 保真、long 计数和
  bool 比例三类输入。修改后 SHA256 依次为：`average_meters.py`
  `6ebbe817f2040e2bb48173b782c092c4aeadbbfb3eb75db33f3d1eedf3df69df`、
  `manager_env_wrapper.py`
  `d37bfa703ac1f2811a2da09619c1ef815f6a3374640bc0b32e538d887446f1b9`、新测试
  `948c52ac57163a1c4723d7116b9285d8ec07ad6434a90fd7ee2b9f640931fa83`。
- 本地定向测试（日志平均器、quarantine、PPO optimizer/KL）结果为
  `16 passed, 2 warnings in 2.64s`；加入全部现有 BUMI3/工具回归并排除本地缺少可选
  `msgpack` 的既有 `test_input_readers.py` 后为 `65 passed, 4 warnings in 6.71s`。
  三个修改文件 `py_compile` 与 `git diff --check` 均通过。warning 仍是既有未知 `\*`、
  TRL experimental API 和 SciPy filters 弃用提示。修复会在提交、推送、服务器
  `git pull --ff-only` 及服务器复测后，以全新时间戳 run 再次从零启动；最终训练健康证据
  另行追加，不能用这里的单元测试替代真实八卡首轮。

### 8. 修复后从零重新启动八卡正式训练

- 上述日志 dtype 修复、测试与第 7 节记录提交为
  `bad93fc11e0464cd8f69f76d8ad361424575918e`，已推送 GitHub 同名 feature 分支。
  `noetix-volc` 工作区同步前干净，执行 `git pull --ff-only` 从 `a1c0f84` 快进到
  `bad93fc` 后仍干净；服务器使用 `liwei_lab` 环境复跑同一相关回归，结果为
  `65 passed, 4 warnings in 10.31s`。确认失败 run 已退出且 8 张 GPU 无 compute process 后，
  没有从故障 run 或 2026-09-03 的旧 100k 模型恢复。
- 修复后的正式 tmux 为 `sonic_bumi3_native_fullfix_v1_8gpu`；launcher PID `2531165`，
  八个直属 worker PID 为 `2531304-2531311`。正式 run 为
  `/data/sonic_bumi3/runs/TRL_BUMI3_Track/manager/universal_token/all_modes/
  sonic_bumi3_native_fullfix_v1_scratch_100k-20260907_175428`，tee 日志为
  `/data/sonic_bumi3/formal_logs/sonic_bumi3_native_fullfix_v1_8gpu_20260907_175428.log`。
  启动源码固定为 `bad93fc`，端口 `29517`，8 个 accelerate rank、每 rank `4096` env；
  `resume=false`、`checkpoint=null`、`auto_load_latest=false`、
  `num_learning_iterations=100000`，因此是全新随机初始化训练。
- 落盘 resolved `config.yaml` SHA256 为
  `f2d8bf42d2b793408c2224516bdb05addee00f584235cb4e7266b4115b0d877d`。它实际指向三源
  v2 的 Robot `95358` 和 paired SMPL `95222` 索引，并确认 Actor `2e-5`、Critic
  `3e-4`、adaptive 范围 `1e-5--2e-4`、三奖励点
  `waist_yaw_link + 双肘`、`anchor_pos/ee_body_pos` 两处完全相同的
  `root_height_threshold=0.40 m`、`threshold=0.12 m`、`down_threshold=0.25 m`，以及已开启
  dynamics gate/quarantine。该核对来自本次 run 自己的 resolved 配置，不是只读取源码
  默认值。
- 8/8 个 worker 已越过原来首轮日志聚合故障并持续进入真实 PPO。监控到 iteration `112`、
  `88080384` timesteps 时，吞吐约 `265343 steps/s`、mean reward 约 `1.05723`、mean
  episode length 约 `15.63`；8 张 GPU 总显存占用约 `15.96--16.37 GiB`、利用率抽样约
  `57%--79%`。正式日志中 `Traceback`、`OutOfMemoryError`、`CUDA out of memory`、
  `NCCL error`、`RuntimeError`、`Error executing job` 精确计数均为 0。
- TensorBoard 已写入 `137` 类 scalar；step `108` 的所有最新 scalar 均为有限值。
  Actor 实际 LR 为 `1.51875e-4`，说明整轮 KL 控制器已从初始 `2e-5` 独立上调 Actor；
  Critic 实际 LR 始终为 `3e-4`。同一步 KL mean/median/P95/max 约为
  `0.01134/0.01184/0.01506/0.01635`。动作门禁失败、quarantine、已评估动作数三个新
  日志已稳定输出为 `310/0/1017`，不再因 long dtype 中断训练。
- iteration 100 原子保存的 `last.pt` 已在训练继续运行时完整 `torch.load`，当时文件大小
  `392861510` bytes、SHA256 为
  `d1061f354eea9baee47f0e4faace0922115433188421039b7a9e87e9d9d6781e`；
  `state.global_step=100`、`max_steps=100000`、`episode=3276800`，含 policy `45` 个 tensor、
  value `17` 个 tensor 和 optimizer/env state。四个 optimizer 参数组在 checkpoint 中明确为
  `actor_decay/actor_no_decay`（schema 2、LR `1.51875e-4`）与
  `critic_decay/critic_no_decay`（schema 2、LR `3e-4`），证明训练、日志和恢复状态使用同一
  实际 LR。该哈希只对应 step 100 当时的原子文件；`last.pt` 后续会继续覆盖更新。
- 当前证据证明从零八卡启动、真实 PPO、整数日志修复、独立 Actor/Critic LR、TensorBoard
  和 checkpoint 链都已运行；iteration 112 仍是 100k 训练的极早期，不代表模型已收敛、
  达到 G1 动作效果、通过 sim2sim 或满足真机安全。本轮按用户要求不等待训练结束，tmux、
  launcher、8 个 worker、正式日志和 run 全部保留继续运行。

### 9. 修复自适应采样跨 episode 错误归因并停止污染训练

- 2026-09-08 对上述正式训练做相同步数日志审计时发现确定性矛盾：停止前最新窗口的
  `time_out` 达到约 `0.8174`，表示绝大多数 episode 没有提前失败，但
  `adp_samp/motion_failure_rate_mean` 仍为 `1.0000`。`model_step_020000.pt` 中动作级
  `5,951,915` 次评估被记录为 `5,951,880` 次失败，仅 `35` 次成功；当时已有
  `25,720/95,358` 条动作进入 quarantine，停止前实时日志进一步升至 `26,222` 条。
  该数量不能解释为 BUMI 数据质量结论。
- 源码和 Isaac Lab 实际步进顺序确认根因：`ManagerBasedRLEnv.step()` 先计算上一条
  episode 的 `reset_terminated/reset_time_outs`，再执行 `_reset_idx()`；命令 reset 会在
  `TrackingCommand._resample_command()` 中覆盖 `motion_ids` 并清零 `time_steps`，随后才
  调用 `_update_command()`。旧实现此时把上一条 episode 的 termination 与新动作 ID、
  新动作时间游标传给 `update_adaptive_sampling()`，因而同时污染分箱失败位置、动作级
  失败率和 quarantine，不是单纯日志命名错误。
- 用户授权停止当前训练后，于 2026-09-08 11:32:29 CST 只向精确 tmux
  `sonic_bumi3_native_fullfix_v1_8gpu` 发送一次 `Ctrl-C`；launcher `2531165` 和八个
  worker `2531304--2531311` 在 6 秒内全部退出，GPU 没有残留 compute process。旧训练
  最终记录到 iteration `21305`，`last.pt` 于 11:32:12 完整落盘；旧 run、固定 checkpoint、
  `last.pt` 与正式日志均保留，严重错误关键字仍全部为 0，但其 adaptive/quarantine 状态
  已知受污染，不得用于 full resume。
- `commands.py` 将结算移动到重采样覆盖旧 ID/时间之前：普通 termination/timeout 使用
  旧 `motion_ids` 和旧最终帧同时写入分箱统计与动作结果；没有 reset 的环境才在
  `_update_command()` 更新本步曝光；参考片段自然结束显式记一次成功。新增外部 reset
  标记，使训练初始化、评估切换和 motion batch 轮换的 `reset_all()` 只中断 episode，
  不冒充成功或失败；同一步刚 reset、尚未执行物理步的新动作也不会被误记为自然完成。
- `motion_lib_base.py` 把帧级 `update_adaptive_sampling()` 与动作级
  `record_adaptive_sampling_outcomes()` 拆开。后者要求调用方显式提交互斥的 failure/success，
  将非 timeout termination 记为失败，将 timeout 或自然完成记为成功；长度不一致或同一
  episode 同时成功/失败会立即报错。checkpoint 新增
  `adaptive_sampling_state_version=2`；缺少该版本的旧状态会完整跳过 adaptive 恢复，避免
  修复代码后重新载入已经错位的分箱、失败率与 quarantine，网络权重仍可独立加载。
- `manager_env_wrapper.py` 在所有主动 `env.reset()` 前声明外部中断；同时新增动作评估总数、
  失败总数、成功总数和按 episode 加权的全局失败比例日志，并直接由实时累计张量计算逐
  动作失败率，不再等待每 200 iteration 的同步缓存刷新。保留原有 adaptive sampling、
  dynamics gate 与 quarantine 配置为启用状态，修复的是证据归属和可观测性，不是关闭功能。
- 新增 `test_tracking_adaptive_sampling_timing.py`，其中文模块说明锁定旧结果先于 ID/时间
  覆盖、post-reset 更新不得读取旧 termination、外部 reset 必须先声明中断等生产源码契约；
  扩展 `test_motion_lib_adaptive_quarantine.py`，覆盖帧统计不得隐式生成动作结果、非末帧
  timeout 成功、冲突结果拒绝以及旧 checkpoint 状态拒绝恢复。首次测试唯一失败是 AST
  没有识别 `getattr(..., "reset_buf")` 的安全访问写法，修正测试后定向结果为
  `15 passed`；包含 BUMI3、PPO、MotionLib、sim2sim 和数据工具的相关回归为
  `74 passed, 4 warnings in 6.91s`，warning 均为既有 TRL/SciPy/转义弃用提示；新增的
  重复 motion ID 用例还确认多个并行环境执行同一动作时，成功和失败按真实 episode 数
  聚合，不会因 ``bincount`` 合并丢失成功证据。
- 五个修改/新增 Python 文件通过 `py_compile`、`git diff --check` 与 Ruff 致命错误检查；
  两个测试文件通过完整 Ruff check/format check。显式设置临时 BUMI worktree 为
  `PYTHONPATH` 后，本地 `validate_bumi3_integration.py` 通过并确认 `21 DoF/22 bodies/50 Hz`、
  actor `690`、critic `1227`、tokenizer `1262` 与 decoder `754 -> 21`。第一次未设
  `PYTHONPATH` 时误从受保护的主工作区 G1 分支导入并失败，未修改该主工作区；正确重跑结果
  才作为本轮验证证据。服务器提交同步、真实 Isaac reset/step 和新八卡从零训练证据将在
  后续交付记录中追加，不能由本地单元测试替代。

### 10. 同步修复并从零重启八卡 adaptive/quarantine 正式训练

- 功能、测试和第 9 节记录提交为 `1be4f928ded1ac956ea9f377ed9707b13da216ae`，已推送到
  GitHub `feature/bumi-native-sonic-full-training`。`noetix-volc` 同名分支在没有训练进程、
  8 张 GPU 均空闲且工作区干净时，通过 `git pull --ff-only` 从 `b8ec71c` 快进到该提交，
  同步后仍干净；未执行 force push、rebase、reset、stash 或覆盖用户文件。
- 服务器 `/root/miniconda3/envs/liwei_lab/bin/python` 复跑同一相关回归，结果为
  `74 passed, 4 warnings in 10.29s`，`py_compile` 与 `git diff --check` 通过。服务器
  `validate_bumi3_integration.py --device cuda:0` 退出码为 0，并再次确认 21 DoF、22 body、
  50 Hz、Actor/Critic/tokenizer/decoder 契约；headless 节点仍打印既有 Vulkan
  `ERROR_INCOMPATIBLE_DRIVER`，但没有阻止配置和资产运行时校验。
- 新训练于 2026-09-08 11:49:18 CST 从提交 `1be4f92` 启动，tmux 为
  `sonic_bumi3_native_adaptive_timing_v2_8gpu`，launcher PID `2934249`，八个直属 worker
  PID `2934386--2934393`。正式 run 为
  `/data/sonic_bumi3/runs/TRL_BUMI3_Track/manager/universal_token/all_modes/
  sonic_bumi3_native_adaptive_timing_v2_scratch_100k-20260908_114918`，正式日志为
  `/data/sonic_bumi3/formal_logs/sonic_bumi3_native_adaptive_timing_v2_8gpu_20260908_114918.log`。
  命令使用端口 `29517`、8 个 accelerate rank、每 rank `4096` env、100000 iteration，
  并显式设置 `resume=false`、`checkpoint=null`、`auto_load_latest=false`，没有继承旧模型、
  optimizer 或受污染的 adaptive/quarantine 状态。
- 新 run 自己落盘的 resolved `config.yaml` SHA256 为
  `f15d54faf9d9175e0fa39134ef712adc2490ae6b59246291abe216ddff97fd94`；其中
  `adaptive_sampling.enable=true`、`dynamics_gate.enable=true`、`quarantine.enable=true`，
  uniform 比例 `0.1`、高失败阈值 `0.90`、最少评估 `5`、最少新增评估 `3`、连续确认
  `3` 均已生效。训练继续使用三源 base-anchor-v2 Robot `95,358` 条动作和对应 SMPL 索引。
- iteration 9 的实时日志首次闭合新守恒指标：动作评估约 `51,343.918`，失败
  `51,083.375`、成功 `260.542`，三者仅有日志小数舍入误差；全局失败比例 `0.9949`
  与随机策略早期 `time_out=0.0046` 的数量级一致。旧实现同阶段之后会逐渐形成“timeout
  很高但动作失败率几乎 1”的矛盾，新实现已经能持续累积非零成功结果。
- step 100 原子 `last.pt` 完整 `torch.load`：文件大小 `392,861,574` bytes，
  `state.global_step=100`、`max_steps=100000`、`episode=3,276,800`；环境状态包含
  `adaptive_sampling_state_version=2`。checkpoint 中动作评估 `635,846`，失败 `633,536`、
  成功 `2,310`，严格满足 `evaluations=failures+successes`；已评估动作 `1,017`、门禁失败
  `310`、quarantine `0`。四个 optimizer 参数组 LR 为 Actor 两组 `1.51875e-4`、Critic
  两组 `3e-4`，独立学习率仍正确。
- step 200 完成第一次真实跨 8 卡 adaptive 同步并保存 checkpoint：动作评估
  `1,194,983.625`，失败 `1,189,855.875`、成功 `5,127.75`，全局失败比例 `0.995709`；
  所有逐动作张量 finite 且满足 `failures <= evaluations`，quarantine 始终是 gate-failed
  集合的子集。8 rank OR 合并后已评估动作 `7,833`、gate-failed `2,332`；这些动作的
  连续高失败确认最大值恰为 `1`，未达到配置要求的 `3`，因此 quarantine 仍为 `0`，说明
  第一次同步没有像旧实现一样立即错误隔离动作。
- 最终本轮复核到 TensorBoard step `227`：新 run 有 `145` 类 scalar、`32,743` 个已采样
  数据点，空 tag 和 NaN/Inf 都为 0。最新动作评估约 `1,329,145.375`，失败
  `1,322,997.75`、成功 `6,147.708`；`time_out=0.01154`，全局失败比例约 `0.99542`，
  二者随随机策略早期学习开始同步改善。8 个 worker 仍存活，8 张 GPU 显存约
  `16.0--16.8 GiB`，正式日志中 Traceback、OOM、NCCL、RuntimeError 和 Hydra job error
  均为 0，训练启动后内核日志没有 NVRM Xid。
- 以上证据确认修复后的 reset/step、动作结果归属、timeout 成功、跨 GPU 同步、checkpoint
  schema、adaptive sampling 和 quarantine 已进入真实训练路径；iteration 227 仍只是
  100k 的极早期，不代表收敛、最终动作质量、sim2sim 或真机安全。按用户要求不等待训练
  结束，新 tmux、八个 worker、run、日志和 TensorBoard 均保留继续运行。
- 12:03:35 八个 rank 首次在正式训练中同时轮换并重新加载各自的 1024 motions，实际覆盖
  了 `prepare_adaptive_sampling_external_reset()` 路径。TensorBoard step `249--252` 的动作
  评估增量依次约为 `4571.5/4005.625/4600.875/4559.5`，没有因 `reset_all()` 凭空增加
  一整批 4096 个成功或失败；成功累计持续平滑上升，每步
  `evaluations-failures-successes` 的绝对值不超过浮点日志舍入误差 `0.17`。最终复核到
  iteration `264` 时八个 worker 仍在，GPU 显存约 `16.0--16.5 GiB`，全部严重错误计数仍为
  0；这进一步确认主动换批只中断旧 episode，不污染自适应采样结果。

### 11. 修复冷启动累计失败过早触发 quarantine

- 第 10 节运行证明了动作结果身份和结算时序已经正确，但继续审计旧污染 run 的历史
  TensorBoard 后发现第二个独立问题：旧实现每 `200` iteration 用“从训练开始累计的逐动作
  失败率”增加连续计数；随机初始化策略的动作成功率约为 `0.4%--0.5%`，而配置只要求连续
  `3` 次同步。因此最早大约 `600` iteration 就可能开始隔离。旧 run 中 quarantine 首次在
  step `638` 变为 `793` 条，step `805` 已达到 `1,538` 条，最终升至 `26,222` 条；这说明即使
  修复 motion ID 错配，冷启动累计失败仍可能在策略尚无基本跟踪能力时把动力学门禁失败的
  大量动作误判为永久坏动作。
- 为避免用不完整的 v2 方案继续消耗算力，2026-09-08 12:07:39 CST 对精确 tmux
  `sonic_bumi3_native_adaptive_timing_v2_8gpu` 发送一次 `Ctrl-C`。launcher `2934249` 与八个
  worker `2934386--2934393` 在 6 秒内退出，最终记录到 iteration `326`；8 张 GPU 没有残留
  compute process。该诊断 run、step 100/200 checkpoint、正式日志和 TensorBoard 全部保留，
  没有删除、覆盖或作为后续 full resume 来源。
- quarantine 新增 `min_global_success_rate=0.20` 成熟门槛。这里的全局成功率不是训练开始以来
  的累计值，而是最近一次全 GPU adaptive 同步窗口中的 `成功 episode / 全部已结算 episode`：
  窗口成功率不足 20% 时，隔离开关 `quarantine_ready=false`，连续高失败计数强制归零，并把
  当前逐动作成功/失败量保存为新基线。这样早期随机策略的失败既不能触发隔离，也不会拖慢
  后续成熟门槛。
- 策略最近窗口达到成熟门槛后，每条动作也改用“当前累计量减去上次有效基线”的增量窗口
  失败率，而不是生命周期累计失败率。动作只有同时满足参考动力学门禁失败、累计 episode
  不少于 `5`、本窗口新增 episode 不少于 `3`、本窗口失败率不低于 `0.90`，并连续 `3` 个
  独立成熟窗口满足条件，才进入 quarantine；任一成熟低失败窗口都会把该动作连续计数清零。
  每次全局同步都单独推进全局窗口基线，而逐动作基线在证据足够时才推进，避免低频动作永远
  达不到最小窗口样本数。
- checkpoint 自适应状态版本由 `2` 提升为 `3`，新增逐动作失败基线和全局成功/失败窗口基线；
  v1/v2 或无版本状态会全部跳过 adaptive/quarantine 恢复，防止旧累计口径继续进入新训练。
  TensorBoard 新增 `adp_samp/quarantine_global_window_success_rate` 与
  `adp_samp/quarantine_ready`，可以直接区分“策略还没成熟”和“成熟后动作连续失败”。BUMI3
  集成验证器同步锁定配置中的 `0.20`，防止后续配置修改意外移除冷启动保护。
- 新增回归构造了全失败冷启动窗口、成熟后的低失败窗口和三个成熟高失败窗口：第一阶段
  ready 与连续计数均为 0；第二阶段即使动作生命周期累计失败率仍超过 90%，也不继承旧失败；
  最后只有动力学门禁失败动作在三个新增窗口后被隔离。全部 BUMI3/PPO/MotionLib/sim2sim/
  数据工具相关回归结果为 `75 passed, 4 warnings in 6.98s`，定向测试为
  `16 passed, 2 warnings`；修改文件 `py_compile`、`git diff --check`、测试 Ruff 和生产代码
  致命错误检查通过。使用当前临时 BUMI worktree 的显式 `PYTHONPATH` 运行
  `validate_bumi3_integration.py --device cuda:0` 通过，确认 21 DoF、22 body、50 Hz 与模型维度
  契约；headless 平台信息仍有既有提示，但不影响本次非仿真步进的配置/资产校验。
- 本节至此记录的是本地确定性修复和验证。服务器提交同步、新 scratch 8 卡启动、第一次
  step 200 全 GPU 同步以及 motion batch reload 的真实证据将在启动后继续追加；在取得这些
  证据前，不把单元测试等同于服务器训练健康或最终模型效果。
- 上述功能与本节本地记录提交为 `db4a65fd989a449e5f62d182eacd162a6f68c7eb`，已推送
  GitHub 同名 feature 分支。`noetix-volc` 同步前位于 `b413c35`、工作区干净且 8 张 GPU
  空闲，通过 `git pull --ff-only` 快进到 `db4a65f`；服务器复跑相同回归为
  `75 passed, 4 warnings in 10.46s`，`py_compile`、`git diff --check` 与完整 BUMI3 集成
  验证通过。服务器仍有既有 headless Vulkan 提示，但没有阻止训练的 PhysX 创建或 PPO。
- 第一次启动于 12:16:36 进入真实 PPO 后，路径审计发现命令把 `experiment_dir` 传成裸目录名；
  尽管 resolved `base_dir` 为 `/data/sonic_bumi3/runs`，训练入口仍会优先直接使用裸
  `experiment_dir`，导致 run 建在代码仓库根目录。该 run 在 iteration `43` 被优雅停止，
  8 个 worker 全部退出、GPU 回到空闲；没有从中恢复。为保留诊断材料而非删除，其完整目录
  已移动到 `/data/sonic_bumi3/runs/aborted_startup/
  sonic_bumi3_native_adaptive_maturity_v3_scratch_100k-20260908_121636`，正式日志仍为
  `/data/sonic_bumi3/formal_logs/
  sonic_bumi3_native_adaptive_maturity_v3_8gpu_20260908_121636.log`，服务器 Git 工作区恢复干净。
- 最终 scratch run 于 2026-09-08 12:21:24 CST 从 `db4a65f` 启动，tmux 为
  `sonic_bumi3_native_adaptive_maturity_v3_8gpu`，launcher PID `2953400`，八个 worker 为
  `2953537--2953544`。正式目录为 `/data/sonic_bumi3/runs/TRL_BUMI3_Track/manager/
  universal_token/all_modes/sonic_bumi3_native_adaptive_maturity_v3_scratch_100k-
  20260908_122124`，正式日志为 `/data/sonic_bumi3/formal_logs/
  sonic_bumi3_native_adaptive_maturity_v3_8gpu_20260908_122124.log`。命令显式使用 8 rank、
  每 rank 4096 env、100000 iteration，并设置 `resume=false`、`checkpoint=null`、
  `auto_load_latest=false`；resolved 配置 SHA256 为
  `ad98aef7757bfd2f1ffc69bd419b5201f084493db2cbb8d90d669d07c71fffe6`，其中绝对 run 路径、
  三源 v2 Robot/SMPL 路径以及 adaptive/dynamics gate/quarantine/20% 成熟门槛均已生效。
- step 100 的 `last.pt` 完整加载：`adaptive_sampling_state_version=3`，动作评估 `635,508`、
  失败 `633,212`、成功 `2,296`，严格满足守恒；quarantine 和连续计数最大值均为 0。
  Actor 两个参数组实际 LR 为 `6.75e-5`，Critic 两组保持 `3e-4`。这证明新 schema、动作结果
  和独立学习率已进入真实 checkpoint 路径。
- step 200 首次完成跨 8 卡同步后，checkpoint 中评估 `1,204,729`、失败 `1,199,750`、成功
  `4,979`，最近窗口成功率为 `0.00413288`，明显低于 `0.20`。全局评估/失败基线与当前总数
  差值均为 0，逐动作评估/失败基线最大差值也均为 0，说明冷启动分支确实只推进基线；
  7,833 条动作已有证据、2,332 条参考动作动力学门禁失败，但 `quarantine_ready=0`、连续计数
  最大值 `0`、quarantine `0`。所有自适应浮点张量 finite，checkpoint 当时 SHA256 为
  `68a7b06f8ed3288ee4692c9c0d65f06c2cc2eace44847ee51d2cff59e77e4547`；`last.pt` 后续会被
  新 checkpoint 覆盖，因此该哈希只对应 step 200 快照时刻。
- TensorBoard 到 step `219` 已有 `149` 个 scalar tag、`32,631` 个 scalar 点，NaN/Inf 为 0；
  它直接记录窗口成功率 `0.00413288`、`quarantine_ready=0` 和 quarantine `0`。iteration
  `249` 左右首次完成 8 rank 的 1024-motion 换批：step 245--249 每步新增评估约
  `4,899--4,979`，换批 step 250 为 `4,156`，随后 step 251--256 为 `4,572--4,690`；没有额外
  增加一整批 4096 个虚假成功或失败。各步 `evaluations-failures-successes` 绝对偏差最大约
  `0.17`，只来自跨 rank float 平均/日志精度；换批加载子进程退出后恢复为精确 8 个 worker。
- 最终本节复核到 iteration `293`：tmux、launcher 和 8 个 worker 均存活，8 张 GPU 约占
  `16.0--17.0 GiB` 且抽样利用率 `86%--89%`；正式日志中 Traceback、OOM、NCCL error、
  RuntimeError 与 Hydra job error 均为 0，服务器 Git 工作区干净。训练按用户要求继续运行；
  当前证据只证明结算时序、冷启动门禁、自适应换批和八卡运行健康，不代表策略已收敛、达到
  G1 动作效果、通过 sim2sim 或满足真机安全。


## 2026-09-09：按用户指定调整 BUMI3 采样、学习率、奖励、质量及终止阈值

> 最终质量语义：用户已明确确认 `[0.8, 1.2]` 为乘数，使用 `operation=scale`，
> 即原腰部质量的 80%～120%。其余采样、学习率、奖励与阈值改动继续有效；
> 初次加法理解错误及其纠正过程单独记录在本节末尾。

### 修改来源与工作区

- 所属分支：`feature/bumi-native-sonic-full-training`；起始 HEAD：
  `ca1351f6e31c1ba0843d6b12414d585f4f9536fd`。本地 BUMI 分支、origin 同名分支和
  noetix-volc `/home/liwei/GR00T-WholeBodyControl` 修改前一致，服务器工作区干净。
- 主工作区 `/home/weili/GR00T-WholeBodyControl` 位于 G1 分支，起始 HEAD 为
  `a33789d1d8ada5091dcfaadfed3f138a8e9d189f`；用户已有的未跟踪 `g1.tar.gz` 保留。
  本轮在 `/tmp/bumi-config-20260909` 的独立 BUMI worktree 修改，不切换 G1 分支。
- 用户明确指定采样比例、Actor/Critic LR、关闭的奖励、腰部质量区间和终止阈值。
  腰部质量按用户最终确认的 `[0.8, 1.2]` 倍数处理，使用 `operation=scale`；原腰部
  质量为 5.27167 kg，随机后为 4.217336～6.326004 kg。机器人资产没有修改。

### 逐文件改动与理由

1. `gear_sonic/config/exp/manager/universal_token/all_modes/sonic_bumi3.yaml`：
   - 显式设置 `uniform_sampling_rate=0.9`，即混合项采用 10% 困难分布加 90% 均匀分布。
   - Actor 初始 LR 保持 `2e-5`，Critic LR 从 `3e-4` 改为 `1e-3`；独立参数组与
     KL 只调整 Actor 的既有实现继续使用。
   - 切换奖励组合并移除 anti-shake 的子参数，确保局部关键点奖励
     `tracking_vr_5point_local` 与防抖奖励 `anti_shake_ang_vel` 均不进入实际组合。
   - 腰部质量从原来的 `[0.8, 1.5]` 倍缩小为 `[0.8, 1.2]` 倍，目标仍精确限定
     `waist_yaw_link`，不匹配左右 wrist_yaw link。BUMI3 本身没有手腕 yaw body。
   - 双肘高度终止阈值由 0.12 m 改为 0.20 m；双脚 XYZ 阈值原本继承 0.20 m，
     本次显式写入 0.20 m。双肘低姿态阈值仍为 0.25 m，分类根高度仍为 0.40 m。
2. 新增 `gear_sonic/config/manager_env/rewards/tracking/base_no_local_keypoint_no_anti_shake_feet_acc.yaml`：
   沿用当前 G1 分支同名组合的十项奖励清单，使用完整中文说明；BUMI3 入口另加力矩
   限制，组成十一项有效奖励。没有改写公共奖励函数，点位元数据和网络维度保持兼容。
3. `gear_sonic/tools/validate_bumi3_integration.py`：同步奖励清单、质量乘法区间、
   独立 LR、均匀占比及双肘阈值断言；保留其他奖励与 BUMI 分支 G1/H2 默认配置的
   兼容性检查，防止校验器误拒新配置或漏掉奖励被重新加入。

### G1 分支对照与本轮未改的问题

- 当前 G1 分支 `a33789d` 的 `sonic_release.yaml` 已显式配置 uniform=0.9、
  Actor/Critic 初始 LR=2e-5/1e-3、关闭上述两项奖励，并将质量随机化收窄到 torso_link。
- G1 与 BUMI 都保留“加载动作批次时抽样、重置回合时再抽样”的两层实现，也都把
  重复载入 motion 的 bins 重复加入 active bins；本轮按用户要求改参数，没有改这部分
  算法。因此 10%/90% 描述的是混合参数，不保证所有动作最终访问次数的严格比例。
- 本轮仍保留 std 上限 0.5、entropy_coef=0.01、腰部 COM 随机化、现有坏动作隔离条件、
  全模型统一梯度裁剪以及终止/timeout 同时触发时的既有价值补偿行为。这些剩余项需要
  另行修改或验证，不能把此次配置检查视为已经解决全部训练效果问题。

### 验证与运行边界

- 本地解释器为 `/home/weili/miniconda3/envs/sonic/bin/python`，PyTorch 2.7.0+cu128。
  调用校验器的 `_validate_repository_assets()`、`_validate_xml_and_meshes()` 与
  `_validate_resolved_configs()` 均通过，输出 `BUMI3_CONFIG_AND_ASSET_STATIC_CHECK=PASS`。
  确认 11 项有效奖励、两项关闭奖励不存在、mass add [-0.8,1.2] 仅作用腰部、uniform=0.9、
  LR=2e-5/1e-3、ee/foot 常规阈值均为 0.2；21 DoF、50 Hz、actor=690、critic=1227、
  tokenizer=1262、decoder 754→21 保持不变，G1/H2 配置组合兼容性通过。
- 既有 `python -m pytest -q gear_sonic/tests/test_ppo_optimizer_and_kl.py -p no:cacheprovider`
  通过：`7 passed, 1 warning in 2.73s`，warning 为既有 TRL experimental 提示。
  另将本轮真实 Hydra 配置的 LR 输入小型 Actor/Critic 参数组构造函数，四组实际 LR 为
  actor=2e-5/2e-5、critic=1e-3/1e-3，输出 `CONFIG_TO_OPTIMIZER_GROUPS=PASS`。
- 修改后的校验器 `py_compile` 和 `git diff --check` 通过；本地各可用解释器未安装 Ruff，
  未执行该可选检查，未为此修改环境依赖。服务器同步后继续复验。
- 本轮不启动仿真或新训练，也不停止、恢复现有正式八卡任务。现有进程于 2026-09-08
  启动时已加载旧配置，更新仓库文件不会让内存中的训练参数自动变化。

### 回滚方法

- 需要恢复时，以单独的反向提交撤销本轮入口与校验器差异，并在无引用后删除新增奖励
  组合文件；不执行 reset/强推，不修改旧 run 的 config.yaml、checkpoint 或用户数据。
- 提交后按本分支持续授权推送 origin，并在 noetix-volc 的同名分支执行
  `git pull --ff-only`；验证、提交和同步完成后清理本轮临时 worktree。


### 服务器同步复验及用户对质量语义的纠正

- 参数提交 `532d7149f509f3b63bf0ba910474dbbf5730d476` 已推送 origin，并在
  noetix-volc 同名分支以 `git pull --ff-only` 同步。服务器实际解释器为
  `/root/miniconda3/envs/liwei_lab/bin/python`；配置/资产静态检查、四组 LR 检查通过，
  既有 PPO 测试为 `7 passed, 1 warning in 5.27s`；正式 launcher 与 8 个 worker 均存活。
- 用户随后明确纠正：腰部质量仍应使用乘法。前一提交把 `[-0.8, 1.2]` 解释为 kg
  增量属于理解错误，该加法设置不应作为最终交付。因为负乘数会产生负质量，已向用户
  确认乘数是否应为 `[0.8, 1.2]`；确认前不把负区间直接写入乘法配置，不启动新训练。
- 采样 uniform=0.9、Actor/Critic=2e-5/1e-3、关闭两项奖励、仅选择腰部质量随机化、
  双肘和双脚常规阈值均 0.2 m 已通过服务器复验；质量项等待按用户确认的乘数修正。


### 最终腰部质量修正

- 用户确认质量乘数为 `[0.8, 1.2]`。修正 `sonic_bumi3.yaml` 为
  `mass_distribution_params=[0.8,1.2]`、`operation=scale`，并同步配置注释与
  `validate_bumi3_integration.py` 的断言。腰部原质量 5.27167 kg，对应随机区间
  4.217336～6.326004 kg；原有 COM 随机化不变，左右手腕仍不属于质量随机化目标。
- 该修正只涉及质量区间和运算方式，不改动已验证的采样比例、学习率、奖励清单、
  终止阈值、机器人资产或训练器逻辑。使用新的普通提交保留纠正过程，不改写前次提交。
- 本地最终 Hydra 组合、资产指纹/拓扑、G1/H2 兼容配置与网络维度静态复验通过，
  输出 `FINAL_BUMI3_CONFIG_AND_ASSET=PASS`；`py_compile` 和 `git diff --check` 通过。
  独立 LR 的 7 项本地与服务器测试已在前述提交通过，本次不修改 trainer，因此仅复验
  受影响的配置契约；同步服务器后再核对最终质量乘数。


### 最终服务器确认

- 质量修正提交 `72d4c01fa1b45a839ae93a2f820e43f10930a683` 已推送 origin；服务器在
  同名分支、预期旧 HEAD、干净工作区三项检查通过后执行 `git pull --ff-only`。
- 服务器最终配置/资产/网络维度检查输出 `REMOTE_FINAL_BUMI3_CONFIG_AND_ASSET=PASS`，
  确认腰部质量 `scale [0.8,1.2]`、uniform=0.9、Actor/Critic=2e-5/1e-3、两项奖励
  完全不存在、双肘/双脚常规阈值均为 0.2 m、双肘低姿态阈值仍 0.25 m。
- 本地与服务器文件 SHA256 一致：
  - `sonic_bumi3.yaml`：`9043aef4a82a204609aade90267ef08b78bac1906a784f0341fa8ec1bf331f02`。
  - `validate_bumi3_integration.py`：`19f5f9adb81416426154ee7415ebe2c69e87cbc8db8a79ab0b09377cebc5330e`。
- 服务器工作区干净；launcher `2953400` 与 worker `2953537～2953544` 全部存活。
  没有重启或修改旧 run 的 resolved 配置，当前训练仍使用 9 月 8 日启动时的旧参数。
  新参数已进入本地和服务器代码，须在后续启动时加载，不宣称已有新参数训练效果。

## 2026-09-09：双肘低姿态高度误差容限放宽至 0.40 m

### 来源、范围与修改理由

- 用户明确要求将低姿态双肘原来的 0.25 m 容限改为 0.40 m；本次不调整其余训练参数。
- 所属分支为 `feature/bumi-native-sonic-full-training`，起始提交为
  `281bb8438efd19a0cc037851d1fd187722c46296`。本地 BUMI、origin 与 noetix-volc
  同名分支起点一致且干净；主工作区仍在 G1 分支，受保护的 `g1.tar.gz` 未作改动。
- `gear_sonic/config/exp/manager/universal_token/all_modes/sonic_bumi3.yaml`：仅将
  `manager_env.terminations.ee_body_pos.params.down_threshold` 从 0.25 改为 0.40，
  补充中文注释，区分“双肘高度误差容限”与“参考根高度分类边界”两个 0.40 m。
  检查对象仍是左右 elbow_pitch link，检查的是 Z 方向高度误差，并非双肘三维距离。
- `gear_sonic/tools/validate_bumi3_integration.py`：同步上述低姿态阈值断言，保留
  正常双肘 0.20 m、参考根高度分类 0.40 m、anchor 低姿态 0.25 m 和双脚三维
  0.20 m 的既有断言；公共终止函数、机器人资产、网络结构和 G1/H2 配置不变。
- 来源为当前 BUMI 入口和用户本轮明确要求，未引入其他机器人参数或修改任何资产。

### 核查结论与未修改项

- Actor 的初始动作标准差为 0.05，但它是可学习参数，现有标准差夹紧范围为
  `[0.001, 0.5]`；0.5 是标准差的上限，不是每次高斯随机量的绝对上限。
  此处探索噪声与启动时关节默认位置扰动、回合重置时初始关节姿态扰动是不同机制。
- 腰部 COM 事件为 `startup`，作用 `waist_yaw_link`，在原刚体局部 COM 上加均匀
  扰动：x 为 `[-0.025, 0.025]` m，y/z 各为 `[-0.05, 0.05]` m；本轮不改。
- 动作末尾 timeout 与失败 termination 可以同时为真。动作采样统计使用
  `success = timed_out & ~failure`，正确记录失败；包装器仍直接将 `truncated`
  交给训练器作 timeout 价值补偿，未排除同时失败的情况。本轮仅解释现有问题，
  不修改奖励补偿、终止语义或噪声参数；没有据此推断该重叠事件的实际频率。

### 验证、运行边界及回滚

- 本地使用 `/home/weili/miniconda3/envs/sonic/bin/python`，调用既有校验器的
  `_validate_repository_assets()`、`_validate_xml_and_meshes()` 和
  `_validate_resolved_configs()`，输出 `LOCAL_BUMI3_CONFIG_AND_ASSET=PASS`。
  Hydra 实际组合确认双肘常规/低姿态为 0.20/0.40 m、根高度分类为 0.40 m；
  anchor 常规/低姿态仍为 0.12/0.25 m，双脚仍为 0.20 m，COM 范围不变。
  G1/H2 配置兼容性通过；21 维动作、50 Hz、Actor 690、Critic 1227、tokenizer
  1262 和 decoder 754→21 不变。校验器源码内存编译与 `git diff --check` 通过。
- 首次验证后的诊断打印误将 motion 配置视为含 `params` 的字典，打印阶段出现
  `KeyError: 'params'`；配置校验本身已通过。修正临时诊断命令的访问路径并完整
  重新执行后通过，该打印失误未涉及仓库代码或训练进程。
- 修改后关键文件 SHA256：
  - `sonic_bumi3.yaml`：`3e58f45f2382713a7968587623f0d263e0b7adac5faa0154e8ce23482e528611`。
  - `validate_bumi3_integration.py`：`8ae9a6d3faf58d58078d14779c99cfbdf006ec9bd8a351763317ff95a9349272`。
- 不运行仿真 reset/step、训练冒烟或正式新训练：本轮只有一个终止配置值变化，
  使用现有配置校验即可验证参数契约；用户未要求启动或重启训练。
- 服务器仓库同步不会热更新 9 月 8 日启动的正式任务，新值须在后续启动时加载。
- 需要回滚时以新的反向提交恢复入口与校验器对应值并补记日志，不改写历史，不改
  正式 run 的配置、checkpoint 或用户数据。提交和服务器复验后清理本轮临时工作区。

### 服务器复验结果

- 参数提交 `7ce9253360970ee61cdd72f38dae9f67ebba6d2f` 已推送 GitHub，并在
  noetix-volc 的同名分支通过 `git pull --ff-only` 同步；同步前已核对预期旧提交
  和干净工作区，没有合并、变基、强推或切换服务器分支。
- 服务器使用 `/root/miniconda3/envs/liwei_lab/bin/python` 运行上述三个既有静态
  校验函数，输出 `REMOTE_BUMI3_EE_THRESHOLD_CONFIG_AND_ASSET=PASS`。
  实际组合确认双肘常规/低姿态 0.20/0.40 m、姿态分类根高 0.40 m、检查对象为
  左右 elbow_pitch link；COM 仍为腰部 x±0.025 m、y/z±0.05 m。
- 两个改动代码/配置文件的 SHA256 与本地记录完全一致，输出
  `REMOTE_LOCAL_FILE_HASHES_MATCH=PASS`，服务器工作区干净。
- 正式 launcher `2953400` 与八个 worker `2953537～2953544` 均存活，未重启或
  更改其启动参数；本次验证不构成新阈值的仿真或训练效果验证。

## 2026-09-09：按用户要求停止旧任务并从零启动更新配置的八卡 BUMI 训练

### 授权、代码来源与旧任务保留

- 用户明确要求在 `noetix-volc` 停止当前训练并重新开始八卡 BUMI 训练；结合本轮
  配置调整，按“从零训练”执行，不恢复旧模型、优化器或自适应统计。
- 启动代码为 `feature/bumi-native-sonic-full-training` 的
  `053a9c94df35a427490d1d7c3f4fe95349e17879`，本地、origin 和服务器起点一致。
  服务器 `/home/liwei/GR00T-WholeBodyControl` 工作区干净。主工作区仍在 G1 分支，
  `g1.tar.gz` 原样保留；本轮仅在临时 BUMI worktree 补充操作记录，不改训练实现。
- 停止前核对 `/proc` 中的真实 launcher 命令、工作目录、八个 rank 与对应 run，
  2026-09-09 14:12:04 CST 向已确认的 launcher `2953400` 发送 SIGINT；随后确认
  launcher 与旧 worker `2953537～2953544` 全部退出，GPU 无计算进程，29517 端口释放。
  未使用宽泛进程匹配或强制杀死无关进程，既有 TensorBoard 未作改动。
- 原正式 run 保留于
  `/data/sonic_bumi3/runs/TRL_BUMI3_Track/manager/universal_token/all_modes/sonic_bumi3_native_adaptive_maturity_v3_scratch_100k-20260908_122124`。
  停止前后核对完整固定编号 `model_step_030000.pt` 为 393243856 bytes，SHA256 均为
  `9649b2e5b70fec829ae2bc201a3ed3ea8b7f7bb7729bcc4cae47a7687d497334`；旧模型、
  配置和正式日志均未删除或覆盖。

### 新训练入口及启动参数

- 新任务实际提交启动时间：2026-09-09 14:12:24 CST；tmux：
  `sonic_bumi3_uniform90_ee040_8gpu_20260909_141204`。
- 解释器：`/root/miniconda3/envs/liwei_lab/bin/python`；使用同环境的 accelerate
  `launch --num_processes=8 --main_process_port=29517`，入口为 `gear_sonic/train_agent_trl.py`。
  环境显式设置 `CUDA_VISIBLE_DEVICES=0,1,2,3,4,5,6,7`、`OMP_NUM_THREADS=1`。
- 配置入口：`+exp=manager/universal_token/all_modes/sonic_bumi3`；显式指定
  `+resume=false checkpoint=null auto_load_latest=false use_wandb=false headless=True`、
  `num_envs=4096`、`algo.config.num_learning_iterations=100000`，即每卡 4096 个环境、
  总计 32768 个环境，计划训练 100000 次迭代。
- 数据沿用 `/data/sonic_bumi3/datasets/bumi3_sonic_three_source_base_anchor_v2/train/`
  下 `robot_all` 与 `smpl_all`，通过 motion_file/smpl_motion_file 的命令行 override
  明确指定；`exclude_motion_keys=[]`。启动前已确认两个目录存在。
- 新 run 使用独立绝对路径，避免旧历史中裸 `experiment_dir` 落到仓库根目录的问题：
  `/data/sonic_bumi3/runs/TRL_BUMI3_Track/manager/universal_token/all_modes/sonic_bumi3_uniform90_lr2e5_critic1e3_ee040_scratch_100k-20260909_141204`。
- 正式日志：
  `/data/sonic_bumi3/formal_logs/sonic_bumi3_uniform90_ee040_8gpu_20260909_141204.log`。
  同目录同名前缀 `.sh` 为带详细中文说明的实际启动脚本，`.json` 保存完整 argv、
  新旧路径、代码提交、旧 checkpoint 指纹与操作状态；这些正式运行记录保留在服务器，
  不把生成日志或模型提交到 Git。启动脚本 `bash -n` 通过。

### 配置与运行验证

- 启动前服务器调用既有资产、XML/mesh 和 Hydra 配置校验，输出
  `PRELAUNCH_CONFIG_ASSET_PASS`。确认 uniform=0.9、Actor/Critic 初始 LR=2e-5/1e-3、
  两项指定奖励关闭、质量仅作用腰部且 scale [0.8,1.2]、双肘常规/低姿态
  0.20/0.40 m、双脚三维 0.20 m。动作噪声、COM 和 timeout 补偿逻辑保持现状。
- 14:12:44 的 `/proc` 核查确认新 launcher 为 `3269510`，worker 为
  `3269523～3269530`，RANK/LOCAL_RANK 精确覆盖 0～7、WORLD_SIZE 均为 8。
  此时正在创建 Isaac Lab 环境，尚不能只据进程存活宣称 PPO 已正常训练。
- 14:13:50 已读取新 run 自己的 `config.yaml`，对从零训练开关、每卡环境数、总迭代、
  绝对实验目录、独立初始 LR、采样比例、腰部质量目标/乘数、双肘/双脚阈值和关闭的
  两项奖励逐项断言通过，输出 `NEW_RUN_RESOLVED_CONFIG=PASS`；配置 SHA256 为
  `a903075d6cdf3685cd07173beacf4609cb8b3c164be73ee53c6a15762b288c89`。
  环境实际创建日志确认 21 维动作、690 维 policy、1227 维 critic、11 项有效奖励。
- 14:14:47 确认真实 PPO 从 iteration 1 持续推进到 11，八个 rank 均存活且仍对应新
  run。GPU 0～7 在训练中约使用 15.1～15.6 GiB，采样利用率 50%～89%。
  新 TensorBoard 位于本 run 的 `tensorboard/`，检查到 step 11：145 个 scalar tag、
  1595 个数据点，NaN/Inf 为 0；奖励约 0.60096、value loss 约 0.009109、KL 约
  0.006010、动作 std 约 0.05756。初期数值仅用于确认从零训练正常推进。
- 独立学习率实际日志确认：step 11 的 `lr/actor_actual=0.000151875`，
  `lr/critic_actual=0.001`。Actor 从配置初值 2e-5 按既有 KL 规则动态调整，Critic
  保持 1e-3；不能把 Actor 后续动态数值当作初始配置未生效。
- 扫描新正式日志，Traceback、CUDA OOM、DistBackendError、ChildFailedError、
  RuntimeError、Hydra job error 和 NCCL error/failed 均为 0。保留了服务器既有
  headless 图形初始化问题：`ERROR_INCOMPATIBLE_DRIVER` 出现 24 次，但此后环境
  创建和实际 PPO 迭代均正常推进，不能将这些图形日志笼统报告为“零报错”。
- 本轮启动的是用户授权的正式训练，模型、日志和会话继续保留；没有额外启动冒烟
  任务，也不把初期运行正常解释为训练已收敛或动作质量已改善。

### 恢复与后续边界

- 如用户要求回到旧任务，应另行确认恢复哪个完整 checkpoint 及其原始配置，不能直接
  把旧优化器和自适应状态混入本次新配置。需要停止新任务时，应先核对上述新 run 与
  真实进程身份，再只停止该任务；不删除旧 run、正式模型或数据。
- 本记录提交推送后按持续授权同步到服务器，文档同步不影响已经启动的训练参数。

## 2026-09-10：回传最新 BUMI SONIC 训练的 30000 轮完整模型

### 来源与操作范围

- 用户要求将 noetix-volc 最新 BUMI SONIC 训练模型传回本地，预计在 3 万轮左右。
  实时核查确认活动任务是 2026-09-09 启动的 uniform90/ee040 八卡训练；15:45:23 CST
  日志为 iteration 30622，最新已完整保存的固定编号模型为 `model_step_030000.pt`，
  保存时间为 2026-09-10 15:14:03 CST。未复制持续变化的 `last.pt`，未停止或重启训练。
- 本次操作所在 BUMI 分支为 `feature/bumi-native-sonic-full-training`，记录前本地、
  origin 与服务器 HEAD 均为 `5cccb8df5223bcfe5836a85827820e6254d2aa1c`，已跟踪文件
  干净；用户未跟踪的 `g1.tar.gz` 原样保留。训练实际启动代码仍为 `053a9c9`，
  `5cccb8d` 仅增加上一轮重启记录。本次不改训练代码、配置或机器人资产。
- 远端来源目录：
  `/data/sonic_bumi3/runs/TRL_BUMI3_Track/manager/universal_token/all_modes/sonic_bumi3_uniform90_lr2e5_critic1e3_ee040_scratch_100k-20260909_141204`。
- 本地新建独立交付目录：
  `/home/weili/GR00T-WholeBodyControl/models/sonic_bumi3/sonic_bumi3_uniform90_lr2e5_critic1e3_ee040_scratch_100k-20260909_141204`。
  目录先前不存在，不覆盖历史模型；同时回传该 run 的 `config.yaml`、`meta.yaml`，
  并在目录内保存生成的 `transfer_manifest_20260910.json`。上述模型与运行元数据
  属于既有 `models/` 忽略范围，不提交到 Git；只提交本条中文操作记录。

### 远端模型与配置确认

- 远端使用 `/root/miniconda3/envs/liwei_lab/bin/python`，限制为 CPU 和单线程，
  对固定 checkpoint 执行 `torch.load(..., map_location="cpu", weights_only=False)`，
  成功读取 `state.global_step=30000`、`state.max_steps=100000`；包含 45 个 policy
  状态项、17 个 value 状态项、4 个 optimizer 参数组，以及 scheduler/env 状态。
  加载前后文件大小和纳秒修改时间一致，确认没有在写入中读取该模型。
- 同目录配置确认 robot=bumi3、uniform=0.9、Actor/Critic 初始 LR=2e-5/1e-3、
  双肘常规/低姿态阈值为 0.20/0.40 m，确属本轮新配置训练，不是旧 run 的同名 30k。
- 源文件大小与 SHA256：
  - `model_step_030000.pt`：393243856 bytes；
    `281dac49d29a2f816ecb71538bbc1ecf15190399d4dd8992c97ec8c28a59e495`。
  - `config.yaml`：27211 bytes；
    `a903075d6cdf3685cd07173beacf4609cb8b3c164be73ee53c6a15762b288c89`。
  - `meta.yaml`：40 bytes；
    `9194a2e11925a35277193b5707f51e1cd684d7ab6274e8127be032ec0318f852`。

### 传输及验证

- 使用 `rsync --partial --info=progress2` 通过固定 SSH Host `noetix-volc` 传到显式
  `.part` 路径，每个文件只有在大小及 SHA256 与远端一致后才原子改名为正式文件。
  三份文件全部传输成功且哈希与上述来源一致，没有覆盖旧目录或遗留 `.part` 文件。
- 2026-09-10 15:56:32 CST 使用本地 `/home/weili/miniconda3/envs/sonic/bin/python`
  与 PyTorch 2.7.0+cu128，CPU 加载验证输出 `LOCAL_HASH_AND_CPU_LOAD=PASS`，
  确认 global_step=30000、max_steps=100000、policy/value 状态项 45/17、优化器
  4 组，以及随模型配置的 BUMI 身份和最新阈值/采样契约。
  首次临时验证命令将 `OnlineTrainerState` 误作字典索引，发生 TypeError；模型
  反序列化本身成功，修正为按属性读取后完整复验通过，未修改任何模型内容。
- 15:56:15 CST 远端复核确认 launcher `3269510` 与 worker `3269523～3269530`
  全部仍对应本次正式 run，训练已推进到 iteration 30838；最新固定编号仍为
  `model_step_030000.pt`。传输全过程未发送训练控制信号或修改远端模型/配置。
- `transfer_manifest_20260910.json` 已标记 complete，保存源文件指纹、双端路径、
  本地加载结果、完成时间和传输后的远端运行快照；源文件大小及 SHA256 可据此复核。
- 此次仅回传训练 checkpoint 及配套配置，不执行 ONNX 导出、仿真评估或训练恢复；
  文件完整、可以加载不代表模型已经收敛或通过仿真/真机验证。
- 如需撤销本地副本，应先确认无调用方引用，再仅处理上述独立交付目录；远端正式
  模型与训练目录保持原样，不以回滚传输为由删除服务器产物或改写 Git 历史。

## 2026-09-10：五对 BUMI/SMPL 数据回传及 sim2sim 多轨迹 T/P 交互

- 用户要求回传当前服务器训练的五对机器人/SMPL 数据，说明 Isaac Lab 中查看模型
  效果的方法，并使 BUMI sim2sim 支持单个数据集文件、首帧保持、T 播放、P 下一条。
- 起始分支为 `feature/bumi-native-sonic-full-training`、HEAD 为 `29556e4`，本地与
  origin/服务器一致，只有用户原有 `g1.tar.gz` 未跟踪，保持不变。
- 新增 `bumi3_motion_dataset.py`：解析含有序 robot/可选 smpl 路径的 JSON/YAML
  清单，检查版本、机器人身份、重复名称和缺失文件，相对路径以清单目录解析；
  数值、50 FPS、关节和四元数契约继续使用既有 BUMI 加载器。
- 修改核心 `bumi3_sim2sim.py`：新增轨迹列表和播放状态，窗口按键只入线程安全队列，
  控制线程消费 T/P；等待时固定所有未来参考帧并清零参考速度，物理仿真和策略继续
  运行。P 切下一条、循环回列表开头，重置实际机器人、历史观测和 heading 到新首帧。
  播完保持末帧；此时再按 T 从首帧重新开始。保留无窗口自动运行的兼容入口。
- 修改 `run_bumi3_sim2sim.py`：增加与 --motion 互斥的 --dataset，GUI 默认常驻且
  保持首帧，提供 --autoplay；窗口关闭退出，--duration 仍可限制运行时长。
- 不修改 G1 C++ 部署器、训练器、机器人 XML 或原始动作数据。本轮 P 按用户要求表示
  下一条，不能照搬 G1 当前 P=上一条、N=下一条的键位。
- 新增 `test_bumi3_motion_playlist.py`，覆盖清单路径和错误、首帧物理继续运行、
  全部未来参考保持、T/P 重置与循环、末帧停止和重播，以及模拟窗口回调接线与关闭。
  同步修改两个入口模块的中文介绍，明确 GUI 默认等待与数据集模式。
- 更新 `docs/source/getting_started/bumi3_sim2sim.md`：补齐清单格式、五对数据位置、
  30000 轮模型运行命令、T/P 和末帧行为、参考保持与真实物理的关系，以及 Lab
  `.pt` 的 Robot/SMPL Encoder 命令；修正导出示例中已有 checkpoint 键的 Hydra
  覆盖语法。明确当前 Lab 无直接 ONNX 入口，未把 MuJoCo T/P 描述为 Lab 功能。
- 数据来源为 `noetix-volc:/data/sonic_bumi3/datasets/bumi3_sonic_three_source_base_anchor_v2/train/`
  下的 `robot_all/`、`smpl_all/`，使用 `rsync -rtL` 解引用服务器符号链接，仅回传
  已选文件；于 16:17:13 CST 完成，10 个文件的字节数和 SHA-256 全部双端一致。
  本地目录为 `/home/weili/GR00T-WholeBodyControl/data/noetix_bumi3_5pairs_20260910/`，
  `robot/` 与 `smpl/` 各 5 个文件，没有修改或裁剪原始数据：

  | 同名 Robot/SMPL 文件（省略 .pkl） | 两侧帧数 | FPS |
  | --- | ---: | ---: |
  | Idle_Left_001__A017 | 3827 | 50 |
  | walk_forward_amateur_001__A002 | 1964 | 50 |
  | wave_R_001__A428 | 219 | 50 |
  | finedance__001 | 4879 | 50 |
  | aioz_gdance__-FXdDRM4lC0_03_0_1650_dancer_00 | 2749 | 50 |

- 源 robot 容器为 `{motion_key: motion}`，SMPL 为平铺字典。最初只读检查误将
  SMPL 首个字段视为子字典，发生 AttributeError，按实际结构修正后检查通过。
  行走候选 A001 的两侧帧数 2003/2002 不一致，故选 A002，未偷偷对源数据截帧。
  正式验证确认 Robot `[T,21]`、SMPL pose `[T,72]`、joints `[T,24,3]`、相同 T/FPS
  以及读取的关节/根姿态/平移/SMPL 数值全部有限。
- `dataset.json` SHA-256 为
  `e25ae5d8dcbc13a8a8f2ccf5d823c616f519bd318c8914dc27c4e83f7cc39be9`；
  逐文件源路径、bytes 和完整指纹保存在同目录 `transfer_manifest.json`，其 SHA-256 为
  `fc87015230deb409f4e47cc0dfcfd3699208e58c30b8dbd1ac5c39c96a96ec49`。
  两个清单和 10 个 PKL 是本地正式交付数据，受 data/ 忽略规则保护，不提交到 Git。
- 复用用户已有 30000 轮 ONNX，未重新导出或覆盖；文件为
  `models/sonic_bumi3/sonic_bumi3_uniform90_lr2e5_critic1e3_ee040_scratch_100k-20260909_141204/exported/model_step_030000_g1.onnx`，
  SHA-256 为 `e884db48c3d5d222821c0816f9c4c81fbcd8e3b9e9129cefcd507ab463466a9a`。
  sim2sim 配置 `gear_sonic/config/sim2sim/bumi3_sonic.yaml` SHA-256 为
  `843756aef9332faa81f0f5ea71e95869e1c0d4604b0f4a11c64974773ead0d17`，仓库内
  BUMI XML SHA-256 为 `28d55b3b460c2731ba478c083c780948b5175132cd3b7b1a73e8d6cbe6fd6547`，
  均沿用既有参数与资产，本轮没有资产改动。
- 所有本地运行使用 `/home/weili/miniconda3/envs/env_isaaclab/bin/python`。
  `python -m pytest -q gear_sonic/tests/test_bumi3_sim2sim.py gear_sonic/tests/test_bumi3_motion_playlist.py -p no:cacheprovider`
  输出 **28 passed in 4.43s**；原有 15 项接口/资产测试保留通过。四个改动 Python
  文件的内存 compile 与 `git diff --check` 均通过。环境没有 Ruff，未安装工具或
  把未执行的 Ruff 检查记为通过。
- 使用正式 `--policy .../model_step_030000_g1.onnx --dataset .../dataset.json --validate-only`
  输出 `BUMI3_SIM2SIM_VALIDATE_ONLY=PASS`，确认五条动作、1170→21 接口及 50 Hz。
  另通过真实 ONNX 和 MuJoCo 控制器逐条执行 10 步首帧保持、T 后 25 步播放、P
  切换，总计 **175 个控制周期、5 次 P**；全部状态/观察/动作有限且末次回到第 1 条
  首帧等待，输出 `REAL_ONNX_FIVE_MOTION_PLAYLIST=PASS`。这些是交互与短时
  数值验证，不代表完整轨迹跟踪或训练质量通过。
- 在本地 `DISPLAY=:1` 实际打开 MuJoCo GUI，使用上述数据集命令加 `--duration 1`，
  默认带红色参考影子，运行 50 个控制周期正常退出，仿真时间 1.0s、根高度
  0.460556m；首/末参考倾角均为 0.241933°，保持首帧期间物理仍运行。
  真实桌面窗口启动已经验证；T/P 键盘回调接线与窗口关闭使用模拟窗口自动测试，
  未执行人工逐条键盘验收或长时视觉质量评估。
- Lab `.pt` 使用同目录 `model_step_030000.pt`，按文档命令分别设置 `use_encoder=g1`
  与 `use_encoder=smpl`，加 `++headless=true ++max_render_steps=20`，固定
  `filter_motion_keys=[wave_R_001__A428]` 并从首帧开始。两次均打印
  `Successfully loaded policy state dict`、加载 219 帧动作、到达
  `Reached max_render_steps=20. Exiting.` 且退出码 0（分别 16:21:47、16:24:28 CST）。
  每次实际 19 次环境 step；没有启动优化器更新、全量评估 callback 或训练。
  Lab 图形界面与完整动作质量没有在本轮验收；不声称 ONNX 已在 Lab 运行。
- Lab 验证临时目录分别为 `/tmp/bumi-lab-eval-20260910-fdw0yfve` 和
  `/tmp/bumi-lab-smpl-eval-20260910-g0mxpvph`；测试时将 eval_base_dir、output_dir、
  algo.trl.output_dir、save_rendering_dir 指向各自临时目录。命令与证据已归档于本条；
  两次测试进程已退出，检查 /proc 的命令行、cwd 和文件描述符无其它进程引用后，
  已仅清理这两个精确目录（各 7 个临时文件）。正式数据和模型保留，最终再次校验
  10 个 PKL 指纹全部一致，`.pt` 指纹仍为
  `281dac49d29a2f816ecb71538bbc1ecf15190399d4dd8992c97ec8c28a59e495`。
- 16:26:47 CST 服务器复核分支/HEAD 仍为本任务起始值，工作区干净，launcher
  `3269510` 和 8 个 worker `3269523～3269530` 均仍在正式 BUMI 训练目录运行。
  本轮仅同步 sim2sim、测试和说明，不改变或重启正式训练。
- 回滚采用新的反向提交，只撤销这次清单/交互/说明修改，不改写历史、不删除正式模型
  或五对数据。
- 功能提交 `4bcf3443ca191c1c7ee66f19b22160233629d6cf` 已推送到 GitHub 同名分支；
  16:30:57 CST 服务器在核对原 HEAD 和干净工作区后，`git pull --ff-only` 成功
  从 `29556e4` 快进到该提交。服务器四个 Python 文件静态编译通过，工作区干净，
  原 launcher 与 8 个 worker 的 PID/命令/cwd 再次全部通过核验。本条后续仅补充
  审计文字，不改变已验证实现；不在正在训练的服务器重复启动仿真或训练测试。

## 2026-09-10：wave 动作首帧摔倒的 Lab/MuJoCo 对照与控制实现修复

- 用户反馈 `wave_R_001__A428.pkl` 在 MuJoCo 尚未按 T 就摔倒，而 Lab Robot/SMPL
  两个分支均正常，要求核实代码、碰撞和训练质量。起始分支
  `feature/bumi-native-sonic-full-training`，HEAD `21a3b5fb4c0892a1a2ce92f4d1291f2fb06b00f8`，
  本地/origin 同步，仅原有 `g1.tar.gz` 未跟踪，受保护且不改动。
- 固定本地 30000 轮 PT/ONNX 和五对数据中的 wave，原始代码可复现首帧保持
  1.16s 摔倒、自动播放 1.38s 摔倒；5s 内关节速度峰值 57.833/59.568 rad/s。
  摔倒判据为根高度 <0.22m 或根倾角 >60°，不是只检查数值是否有限。
- 原始 wave 首帧双脚与地面约 17.37/17.84mm 穿透。仅在内存中整体抬高机器人
  18mm 仍会摔倒；不改模型/动作/碰撞/PD 增益，将物理步长改为 1ms（策略仍 50Hz）
  或使用 MuJoCo 原生位置 PD 加 implicitfast，均可保持并播放 5s 无上述摔倒。
  这些为定位对照，未改写资产、源动作或正式配置；完整对照结果见本条后述诊断报告。
- 新增 `gear_sonic/tools/bumi3_lab_audit.py`：通过既有 eval callback 接口，在单环境
  有限步评估中记录真实策略输入、确定性动作、机器人状态、参考帧、终止标记及
  运行时动作/关节/质量参数；用于逐输入比较 PT/ONNX 与 MuJoCo，拒绝覆盖已存在
  的采集文件。该回调不更改训练器、动作、终止或物理参数。
- 实际验证、最终修复范围、指纹、临时产物清理和 Git/服务器同步结果接续记录如下。
- 修复 `bumi3_sim2sim.py`：运行时把单位 gear 的同名 motor 配置成原生位置伺服，
  gain/bias 使用现有 Kp/Kd，力矩上限写入 forcerange，使用 implicitfast；Python
  只写目标角度，不再显式积分反馈阻尼。PD 增益、惯量、200Hz 物理/50Hz 策略、
  动作缩放与碰撞体不变。reset 时 ctrl 使用当前角度，统计读取 actuator_force。
  入口同时打印 PD 实现与积分器，便于确认运行了修复版本。
- 首次 Lab 采集回调使用了本环境没有的 action_term.scale 公共属性，初始化失败；
  已按安装的 Isaac Lab 源码改用 _scale/_offset。该失败没有进入采样，不计作
  Lab 评估通过；Isaac 进程即使退出码为 0 也必须检查成功标记与采集文件。
- 第二次回调初始化暴露 TrackingCommandCfg 的实际字段为 anchor_body，而非
  anchor_body_name；已修正诊断字段访问。两次失败均发生在数据采集前，不能算完整
  Lab 运行证据，后续采用成功标记和采集文件双重确认。
- 诊断适配 Actor 默认不返回 obs_dict 的情况，直接读取当前 rollout 的已有观测缓冲，
  不修改 Actor 返回选项或重新计算含历史的观察。
- 采集元数据中的观察维度由 NumPy int64 显式转为 Python int，再写 JSON；此前
  第三次采集在元数据序列化阶段失败，尚未产生轨迹证据，保留失败日志待统一归档清理。
- 补充修复派生状态时序：每个控制周期完成积分后执行 mj_forward，确保下一次策略
  读取的根姿态/角速度与最新 qpos/qvel 同步，消除 mj_step 后约 5ms 的缓存滞后。
- `test_bumi3_sim2sim.py` 新增独立 PD 力矩公式/饱和验证、无接触无网络的低惯量
  手臂阻尼衰减回归，以及积分后根姿态同步检查。隔离实验已证实原显式 PD 在
  无重力、无接触、无神经网络的情况下仍把 1rad/s 初速度放大到 54.170rad/s；
  原生 PD 峰值 0.174rad/s，0.5s 后降至 0.00320rad/s，直接排除碰撞或训练导致
  这类数值振荡的解释。
- Lab 诊断补记 terminated/time_out，区分轨迹自然结束和失败；g1 正常评估已成功
  采集完整 219 步，仅第 219 步 done，无提前重置。修复版 wave 已通过 30s 首帧保持、
  30s 自动播放及末帧保持，以及 10s 等待→完整播放→10s 末帧保持三组长时检查。
- 逐帧输入对照发现第二处独立问题：无速度字段的 Robot PKL 原用 np.gradient
  中心差分，但当前 checkpoint 的 Humanoid_Batch.fk_batch 用前向差分，并在
  末帧复用倒数第二段速度。wave 最大参考关节速度输入差为 12.3127rad/s。
  现已仅对这类 PKL 的缺省速度计算匹配训练约定；显式速度、NPZ/CSV 路径保持
  原有契约，两帧短动作复用唯一速度段。新增非匀速/两帧回归测试。
  这处差异影响播放阶段；首帧保持参考速度为零，故不是按 T 前摔倒的主因。
- 同步 PKL 自动播放/reset 的根初速度：原来只用相邻姿态差分，训练则对根线/角
  速度使用中心差分和 sigma=2 的高斯滤波。ReferenceMotion 增加可选根速度数组，
  PKL 加载时在内存计算，reset 将世界角速度转换到 MuJoCo freejoint 局部坐标；
  NPZ/CSV 未新增速度假设，暂停仍置零。新增非匀速滤波、四元数 q/-q 和 reset
  坐标转换回归测试。此修正也不改源动作、训练代码或物理参数。
- 更新 `docs/source/getting_started/bumi3_sim2sim.md` 的原生 PD、PKL 速度和恢复运行
  说明；新增 `docs/source/getting_started/bumi3_wave_sim2sim_audit_20260910.md`，归档
  完整六组保持/播放定位对照、隔离实验、最终长时验收、模型/资产 SHA-256、
  Lab 同输入对照数值、仍存在的物理差异以及可复制的模型运行/采集命令。
- 最终全部实现使用 `env_isaaclab` 执行
  `python -m pytest -q gear_sonic/tests/test_bumi3_sim2sim.py gear_sonic/tests/test_bumi3_motion_playlist.py -p no:cacheprovider`，
  **34 passed in 8.65s**。最终 30s 首帧等待：1500 步、未倒、末根高 0.4725096868m、
  最大倾角 5.202718°；30s 自动播放后保持：1500 步、未倒、末根高 0.4692105798m、
  最大倾角 9.409625°；10s 等待→T→完整 wave→保持 10s：1219 步/24.38s、
  未倒、末根高 0.4693302095m、最大倾角 9.135653°。后两组均停在索引 218
  的末帧，playing=false。摔倒判据为根高 <0.22m 或倾角 >60°；物理始终运行。
- Lab 成功采集三组各 219 个真实输入：g1 默认噪声、g1 无观测噪声、SMPL 默认噪声。
  后两组 `terminated=[]`、`timeout=[218]`，没有提前失败；首组仅末步 done。
  将完全相同输入送入原 ONNX，最大动作差分别为 7.62939453e-6、7.62939453e-6、
  9.53674316e-6。重建无噪声 g1 的相同状态及实际随机零位，本体观测最大差
  1.34110451e-7、参考观测最大差 1.78813934e-5。没有发现导出或观测排列错误。
  根速度与训练函数对照最大差：角速度 3.94432654e-6rad/s、线速度 1.38237764e-8m/s。
- 同姿态 22 刚体 FK 位置最大差 1.1818364e-5m、四元数差 5.5834812e-7；
  MJCF/Lab 默认质量总和分别 20.24093728/20.2409373671kg，单 body 最大差
  1.4917755e-7kg。Lab 启动随机化和自碰撞、MuJoCo 固定参数及 frictionloss 的
  差异仍保留，具体采样值和边界在诊断报告中列明。初始双脚约 18mm 穿地仍是
  数据/地面问题，但单独解除仍倒、不解除且修 PD 即稳定，故不是本次主因。
- 修复不涉及训练配置/代码、XML/URDF、源 PKL、PT/ONNX 文件，关键指纹见报告。
  兼容范围为 BUMI 专用 Python sim2sim，G1/H2 通用训练逻辑未修改；T/P 接口不变。
  没有运行全数据集评估、人工长时 GUI 观看或实机测试，不能由 wave 成功推断全动作
  已收敛。原零策略 100 步 validator 的 PASS 仅为接口/有限值通过，不是站稳证据。
  回滚采用新的反向提交撤销本次修改，不改历史，不删除正式数据和模型。
- 最终四个修改/新增 Python 文件内存 compile、`git diff --check` 通过；报告中
  7 项 PT/ONNX/PKL/XML/URDF/配置指纹均与实际文件重新计算的 SHA-256 一致。
  环境无 Ruff，未执行 Ruff，未为此安装新依赖。
- 本轮所有仿真/采集/对照进程已退出；逐进程检查 /proc 的命令行、cwd、文件
  描述符，无任务引用诊断目录。命令、关键数值和三次早期采集失败原因归档后，
  已仅清理 `/tmp/bumi-wave-audit-20260910-vg5j32eh`（77 文件、5111163 bytes），
  输出 `AUDIT_TEMP_CLEANUP_PASS`。正式模型、五对数据、用户 `g1.tar.gz` 保留。
- 同步前服务器复核：`noetix-volc:/home/liwei/GR00T-WholeBodyControl` 与本地同分支，
  HEAD 仍为 `21a3b5f`，工作区干净、与其 upstream 0/0。正式训练 launcher
  `3269510`（start_ticks=964046165）和 8 个 worker `3269523～3269530`
  （start_ticks=964046505）仍在该仓库运行同一 BUMI 100k 正式训练命令。本次仅做
  部署修复同步和静态编译，不发送训练控制信号、不重启训练。
- 修复提交 `9ff1e1a2937a4a9d04ff5c261d4a49705a0cf13b` 已推送到 GitHub 当前分支。
  2026-09-10 17:25:34 CST，服务器核对原 HEAD、同分支及干净工作区后，通过
  `git pull --ff-only` 从 `21a3b5f` 快进到该提交，四个 Python 文件静态编译通过，
  工作区仍干净。launcher 和 8 个 worker 的 PID、启动 tick、命令和 cwd 在拉取
  前后均通过核对，输出 `SERVER_SYNC_PASS`。此后的提交仅补记这条同步证据，
  不更改已验收实现，也不重复启动服务器仿真或训练。

## 2026-09-10：按用户要求恢复 G1 式显式 PD 与 BUMI 手臂部署惯量

- 用户要求解释 XML 的被动关节阻尼，控制方式与 G1 保持一致，恢复外部 PD，手臂
  armature 使用 0.03；若仍摔倒继续查观测、初始化和碰撞等原因。起始分支为
  `feature/bumi-native-sonic-full-training`，HEAD `393ae3e3eb031fe4f263e539861330d4b0c96750`，
  本地与 upstream 0/0，仅用户原有 `g1.tar.gz` 未跟踪，保留不动。
- 实际 G1 路径为 `run_sim_loop.py`→`BaseSimulator.compute_body_torques/sim_step`，
  使用 Python 显式 PD、200Hz 物理、Euler 积分器；C++ 策略为 50Hz，DDS writer
  500Hz 不代表物理频率。默认场景加载 `gear_sonic/data/robot_model/model_data/g1/scene_43dof.xml`，
  其 G1 XML 对腰、腿、踝、臂、腕等电机关节的被动阻尼均为 0.05。
- `gear_sonic/utils/mujoco_sim/bumi3_sim2sim.py`：撤下运行时原生位置伺服，恢复
  default+scale*action 目标角度→外部 Kp/Kd 力矩→限幅→motor；积分器明确为 Euler。
  保留 motor 单位/传动验证、实际力矩记录、有限值检查，以及上一轮参考速度和
  积分后根状态刷新修复。等待 T、播放和 P 切换契约不变。
- `gear_sonic/data/assets/robot_description/mjcf/bumi3.xml`：按用户要求将 21 个电机
  hinge 关节的被动 damping 从 0.001 改为 G1 的 0.05；freejoint 不属于这些电机
  关节。XML 默认 armature 原本就是 0.03，不修改该值、几何、质量、连杆惯量或地面。
  `gear_sonic/config/sim2sim/bumi3_sonic.yaml` 中八个肩/肘关节的运行时 armature
  从 0 改为 0.03，避免初始化又把 XML 手臂惯量清零。其它关节 armature 和 BUMI
  Kp/Kd、力矩上限均保持原值。部署参数按用户要求有别于现有 Lab 训练参数。
- `gear_sonic/scripts/run_bumi3_sim2sim.py`：启动输出改为 `python_explicit_pd_motor`
  与 `Euler`，同时打印真实运行时的 joint_passive_damping 和 joint_armature，
  方便确认 XML/配置最终生效值。
- `gear_sonic/tests/test_bumi3_sim2sim.py`：将位置伺服测试改成显式 motor 力矩/限幅
  验证，检查手臂 0.03 与 21 关节被动阻尼 0.05；隔离扰动衰减测试使用本次部署
  参数。`validate_bumi3_sim2sim.py` 同步四踝加八臂惯量和阻尼/积分器检查。
- 本轮不修改训练器、奖励或 Isaac Lab 执行器配置，不重新导出或修改模型/动作。
  实际仿真、资产指纹、文档、清理和提交同步结果接续如下；历史对照实验按其当时
  的零手臂 armature 参数保留，不把“外部 PD 公式本身错误”作为已证明结论。
- 被动阻尼调整后，两个资产验证器的 MJCF 指纹同步更新为
  `f7a7c25565f410a54b01f5a9ba94c0dc7535eb26a75a94a427504251c9eac546`；sim2sim YAML 指纹为
  `7cf5b6fb31855540bca50fb048fe64cf61f3b2c2a12c200422a0468552604863`。
  G1 阻尼来源 XML 的 SHA-256 为
  `58c82f77753db54f8a6ca0a8e020e142b015d8587db6cfc442f9a75f2bc444c6`。
  原 BUMI XML 指纹为 `28d55b3b460c2731ba478c083c780948b5175132cd3b7b1a73e8d6cbe6fd6547`。
- 更新使用文档 `docs/source/getting_started/bumi3_sim2sim.md`：解释电机关节被动
  阻尼与 PD Kd 的区别，标明显式 PD/Euler、手臂部署惯量与训练的差异及新启动标记。
  `bumi3_wave_sim2sim_audit_20260910.md` 顶部标注历史版本边界，新增当前配置与
  实测章节，不覆盖上一轮真实对照结果，也不再把原生位置伺服描述为当前运行方式。
- 使用 `/home/weili/miniconda3/envs/env_isaaclab/bin/python -m pytest -q gear_sonic/tests/test_bumi3_sim2sim.py gear_sonic/tests/test_bumi3_motion_playlist.py -p no:cacheprovider --basetemp=/tmp/bumi-g1-pd-20260910-w4j5x099/pytest`，
  **34 passed in 8.18s**。包含用户指定惯量/阻尼下的无网络无接触扰动衰减、显式
  motor 力矩/限幅、Euler 积分器、速度契约以及 T/P 交互测试。
- 真实 `model_step_030000_g1.onnx` 与 `wave_R_001__A428.pkl` 三组验收均未倒：
  30s 首帧保持（1500 步）：末根高 0.4721292987m、最大倾角 5.305660°；
  完整播放后保持至 30s（1500 步）：末根高 0.4683850164m、最大倾角 9.587809°；
  10s 等待→T→完整播放→10s 保持（1219 步/24.38s）：末根高 0.4690687550m、
  最大倾角 9.188391°。输出 `EXPLICIT_PD_WAVE=PASS`，全部保留原始根高、碰撞
  和持续物理积分，未用 qpos 强制固定机器人。后两组停在第 218 帧。
- 三组测试通过，因此本轮没有继续调整观测、碰撞或初始化参数。该结果覆盖当前
  checkpoint 的 wave；没有重跑 Lab 或重新导出模型，未执行全动作集/实机验收。
- `python gear_sonic/tools/validate_bumi3_sim2sim.py --skip-smoke` 输出
  `BUMI3_SIM2SIM_VALIDATION=PASS`，确认 21 DoF/22 刚体、22 mesh、14 碰撞体及
  原有零地面基准；其静态默认姿态接触检查不等于 wave 首帧无穿地。
  调用集成验证器的 `_validate_repository_assets`、`_validate_xml_and_meshes`、
  `_validate_resolved_configs` 输出 `BUMI_ASSET_AND_CONFIG_GATE=PASS`；没有启动
  Isaac App 或宣称完整 Lab 集成/仿真通过。
- 真实入口使用本轮同一 ONNX 和 wave 加 `--validate-only` 输出
  `BUMI3_SIM2SIM_VALIDATE_ONLY=PASS`，实际解析的 PD 为 `python_explicit_pd_motor`、
  积分器为 `Euler`、21 个关节被动阻尼全部 0.05、八个手臂惯量全部 0.03。
  五个改动 Python 文件内存 compile 与 `git diff --check` 通过。XML 与起始版本
  做去注释语义比较，唯一参数变化是默认 damping 0.001→0.05；PT、g1 ONNX、wave
  的 SHA-256 与上一轮记录全部一致。
- 同步前服务器同分支、HEAD `393ae3e`、工作区干净；原 launcher `3269510`
  （start_ticks=964046165）和八个 worker `3269523～3269530`
  （start_ticks=964046505）均保持同一 BUMI 命令和仓库 cwd。仅同步部署代码与
  MuJoCo XML，不重启训练、不改变已创建的 Isaac Lab 训练环境参数。
- 回滚方法：在当前开发分支创建新的反向提交，只撤销本轮显式 PD/部署参数及相应
  文档和检查项，不回退 PKL 速度和根状态刷新，不改写历史或删除正式模型/数据。
- 测试进程已退出；检查 /proc 命令行、cwd 和文件描述符后，无任务引用本轮专用
  目录。关键命令、数据和结果归档后，已仅清理
  `/tmp/bumi-g1-pd-20260910-w4j5x099`（50 文件、36170 bytes），输出
  `TASK_TEMP_CLEANUP_PASS`。正式模型、五对数据、用户 `g1.tar.gz` 保留。
- 功能提交 `40434dd7578558a8d63af38e79d3f9bfff613e58` 已推送到 GitHub 当前分支。
  2026-09-10 17:58:20 CST，`noetix-volc` 核对同分支、原 HEAD 和干净工作区后
  `git pull --ff-only` 从 `393ae3e` 快进到该提交；五个 Python 文件静态编译通过，
  新 XML/YAML 的 SHA-256 与本地一致，服务器工作区干净。原 launcher 与八个
  worker 的 PID、启动 tick、训练命令及 cwd 在拉取前后均通过核对，输出
  `SERVER_SYNC_PASS`。后续仅补记同步证据，不改变已验证实现。

## 2026-09-10：实测当前 BUMI sim2sim 清零 armature 是否摔倒

- 用户询问清零 armature 的实际影响。本轮在 HEAD `056c46293bf8d326ba34f82196c11e49c268abbe`
  上进行局部诊断，使用同一 30000 轮 g1 ONNX 与 `wave_R_001__A428.pkl`，复用正式
  `Bumi3SonicSim2Sim.step_control()`，只通过内存中的 `dataclasses.replace` 修改
  armature 数组。没有更改任何正式 Python、YAML、XML、模型、动作或训练参数。
- 固定显式 PD、Euler、5ms/50Hz、被动阻尼 0.05、原 Kp/Kd、力矩上限、初始姿态
  和碰撞。测试当前八臂 0.03、仅八臂清零、全 21 关节清零三种配置，分别执行
  30s 首帧等待、播放后保持至 30s，以及等待 10s→T→完整播放→再保持约 10s。
- 当前 0.03 三场景均未倒，复现上轮数值；仅手臂清零时等待 3.82s、播放 2.60s
  摔倒；全关节清零时等待 1.60s、播放 0.98s 摔倒。两种清零配置都在等待 10s
  的 T 事件前倒下。既有摔倒阈值为根高度 <0.22m 或根倾角 >60°，采样间隔 20ms。
- 额外四组继续运行到 10s，确认不是短时蹲低：仅手臂清零的等待/播放分别在
  3.94s / 2.70s 倾角超过 60°，10s 根高度 0.050560 / 0.076259m；全清零两组
  分别在 1.70s / 1.02s 超过 60°，10s 根高度 0.052768 / 0.052671m。
- 九组主实验无 MuJoCo 数值警告或 NaN/Inf。正式 YAML、XML、运行器、ONNX、
  wave 运行前后 SHA-256 一致，输出 `FORMAL_FILES_UNCHANGED=PASS`。正式手臂
  armature 仍为 0.03；本轮没有改 PD 实现，没有连接或更改 noetix-volc 训练。
- 本轮仅追加此记录和 `docs/source/getting_started/bumi3_wave_sim2sim_audit_20260910.md`
  第 11 节，说明对照方法、结果、采样范围和结论边界；不把该实验单独解释为
  PD 公式错误或训练失败。原始诊断结果位于本轮临时目录
  `/tmp/bumi-armature-zero-20260910-jklbuznk`，关键方法与数值已归档。

## 2026-09-10：对照指定 Mimic 部署并隔离零 armature 失稳机理

- 用户指定 `/home/weili/legged_lab/scripts/sim2sim_mimic_vision_4340.py`，要求解释
  为什么 Mimic 曾能使用零 armature。本轮只核对当前该入口默认路径，不将其等同
  于用户历史通过 `--model` 指定的其他文件；两仓库实现及模型均未修改。
- 确认 Mimic 父类 `sim2sim_mimic.py:269` 直接加载 4340 XML，两个脚本均没有
  覆盖 `model.dof_armature`。实际 MuJoCo 编译后 21 个 hinge 全部为 0.03，
  被动 damping 全部为 0.001，Euler / 5ms / 50Hz。当前 XML SHA-256 为
  `94ac99adf5f4512ac11903f521d5ec2f2fddb0413cfccec3e31a73d852a37719`。
- 实际读取默认 `bumi3_0806_lalacao_dance_jingjian_6.onnx` metadata，肩肘 Kp=8、
  Kd=0.4、action_scale=0.125，与 SONIC 相同；元数据不含 armature，训练端未
  设置 armature 不代表部署端清零。Mimic 保留其余关节的 XML 0.03，SONIC 则
  明确覆盖为训练分组值，这也是两条加载链的实际区别。
- 计算同一默认姿态下的左肩 yaw 关节空间惯量矩阵对角项：SONIC 清零时为
  0.0003508188858kg·m²，加 0.03 后为 0.0303508188858，约 86.5 倍。Mimic
  该轴原有惯量为 0.0003508187656，几乎相同，不能用同名资产或总质量替代该轴分析。
- 临时内存模型关闭重力和约束，固定目标、注入左肩 yaw 初速度 1rad/s；先用各组
  原 PD 做六组资产/惯量/步长对照，再只启用八个肩肘 PD 做三组复核，排除悬空
  腿部驱动。后者 0.03/5ms 的 yaw 前三步为 0.9264→0.8522→0.7778rad/s，
  0/5ms 为 -3.1053→10.8259→-30.7411，0/1ms 为 -0.2950→0.0991→-0.0221。
  0.5s 末八臂最大速度分别为 0.005393 / 24.775654 / 0.000125rad/s。
- Mimic 实际资产与默认 ONNX 增益的隔离对照也在清零肩肘、5ms 时振荡，无需
  网络和碰撞。该结果说明小惯量与离散 PD 更新周期的组合敏感，不表明 PD 公式
  本身错误；查阅 MuJoCo 3.3.2 官方文档确认 Euler 的 XML 阻尼隐式处理机制。
- 真实 SONIC 30000 轮 wave 在零手臂惯量、仅临时改为 sim_dt=0.001 /
  decimation=20、保持策略 50Hz 后：等待 30s 未倒，根高 0.4728370615m、最大
  倾角 5.242422°；完整播放并保持到 30s 未倒，根高 0.4697831458m、最大倾角
  10.053520°。正式 PD、训练和默认 5ms / 手臂 0.03 配置保持原值。
- 本轮只追加 `bumi3_wave_sim2sim_audit_20260910.md` 第 12 节及此日志，记录路径、
  方法、实测和适用范围。原始结果在 `/tmp/bumi-mimic-armature-mechanism-20260910-ob9psbrj`；
  没有重跑 Mimic 完整网络动作、修改服务器或将一次 wave 验证推广为全数据集结果。

## 2026-09-10：按用户要求将 BUMI sim2sim 八个肩肘 armature 降为 0.01

- 起始分支 `feature/bumi-native-sonic-full-training`，HEAD
  `056c46293bf8d326ba34f82196c11e49c268abbe`，与本地跟踪的 origin 分支 0/0。
  保留前几轮同主题未提交诊断记录，以及用户原有未跟踪 `g1.tar.gz`。
- 用户认为 0.03 偏大，要求尝试 0.01。`gear_sonic/config/sim2sim/bumi3_sonic.yaml`
  将 arms 组从 0.03 改为 0.01；`gear_sonic/data/assets/robot_description/mjcf/bumi3.xml`
  仅为左右 arm_pitch、arm_roll、arm_yaw、elbow_pitch 八个 joint 显式增加
  armature=0.01。其余关节保留原 XML 默认值和原运行时覆盖，避免改动踝部或腿腰参数。
- 保留显式 Python PD、Euler、sim_dt=0.005、decimation=4、原 Kp/Kd、力矩上限、
  XML 被动阻尼 0.05、质量/连杆惯量/碰撞、训练执行器、checkpoint 和动作。
  该值来自本次用户指令，不视为按机器人尺寸推算出的真实电机折算惯量。
- 同步更新 `bumi3_sim2sim.py` 的参数说明、`test_bumi3_sim2sim.py` 的已有惯量
  验证及扰动衰减说明、`validate_bumi3_sim2sim.py` 的期望值、两个资产验证器的
  XML 指纹；更新使用文档及诊断报告当前版本指向，保留历史实验原值。
- 本轮资产指纹、测试命令、真实 wave 三场景结果、临时目录清理与 Git/服务器同步
  结果接续记录。仅该参数修改无需重导出 ONNX；回滚使用新的反向提交恢复本轮参数、
  说明和校验，不改写历史或回退先前速度/观测修复。
- 新 XML SHA-256：`1ef8da2e76be03430ba7f022e49309f194a289174db0275d7d3a123197cac3e3`；
  新 YAML SHA-256：`f52be29ca85a264273dc5ab75055ea52b8c297a362d093fd27f25ca90d9865f8`。
  原值分别为 `f7a7c25565f410a54b01f5a9ba94c0dc7535eb26a75a94a427504251c9eac546`、
  `7cf5b6fb31855540bca50fb048fe64cf61f3b2c2a12c200422a0468552604863`。
- 使用 `/home/weili/miniconda3/envs/env_isaaclab/bin/python -m pytest -q gear_sonic/tests/test_bumi3_sim2sim.py gear_sonic/tests/test_bumi3_motion_playlist.py -p no:cacheprovider --basetemp=/tmp/bumi-arm001-20260910-CvEL4G/pytest`，
  **34 passed in 5.66s**。没有增加与参数赋值重复的测试，复用已有控制、交互、
  资产和扰动衰减检查。
- 真实三场景输出 `ARM001_WAVE_THREE_SCENARIOS=PASS`：等待 30s 根高
  0.4720431696m、最大倾角 5.236921°；播放后保持至 30s 根高 0.4706900855m、
  最大倾角 9.835809°；等待 10s→T→完整播放→保持约 10s，共 24.38s，根高
  0.4695242554m、最大倾角 9.554793°。均无摔倒、MuJoCo 警告或 NaN/Inf。
- `/home/weili/miniconda3/envs/env_isaaclab/bin/python gear_sonic/tools/validate_bumi3_sim2sim.py --skip-smoke`
  以及集成检查器的 `_validate_repository_assets`、`_validate_xml_and_meshes`、
  `_validate_resolved_configs` 用于静态资产/配置验证；实际动力学验收为上述 wave
  及已有单元测试，不重新启动 Lab 训练或宣称全动作集通过。
- AST 对照确认 `bumi3_sim2sim.py` 仅改文档说明，PD/观测/播放实现未变；XML
  去注释后的差异严格为八个肩肘 joint 的 armature 属性，YAML 仅 arms 组改值，
  输出 `ONLY_EIGHT_ARMATURE_VALUES_CHANGED=PASS`、`PD_AND_RUNNER_LOGIC_UNCHANGED=PASS`。
- 默认 SSH 的 `sss_ssh_knownhostsproxy` 首次出现 banner 超时；同一 `noetix-volc`
  别名使用 `-o ProxyCommand=none` 后连接成功，未替换服务器、用户、端口或密钥。
  同步前服务器为同分支、HEAD `056c462`、工作区干净；GitHub 当前分支也为该 HEAD。
- 静态资产/配置检查全部通过，sim2sim 检查器输出 `BUMI3_SIM2SIM_VALIDATION=PASS`，
  `git diff --check` 通过。服务器原 launcher 3269510（start_ticks=964046165）
  和八个 worker 3269523～3269530（start_ticks=964046505）仍对应原 BUMI 训练目录。
- 关键方法及结果已归档后，确认本线程测试进程结束、可读进程无路径引用，仅清理
  三个精确专用目录：`/tmp/bumi-armature-zero-20260910-jklbuznk`（14 文件，233388 bytes）、
  `/tmp/bumi-mimic-armature-mechanism-20260910-ob9psbrj`（12 文件，141308 bytes）、
  `/tmp/bumi-arm001-20260910-CvEL4G`（53 文件，153451 bytes），均输出
  `TASK_TEMP_CLEANUP_PASS`。前两项为本线程前几轮已完成诊断，报告中的临时路径
  自此仅作历史来源记录；正式模型、五对数据、测试源码和用户 `g1.tar.gz` 保留。
- 本次提交一并归档本线程前几轮同主题的 0/0.03/1ms 诊断记录，保留其原始结果，
  并以报告第 13 节标明最新 0.01 正式值；不混入无关工作区内容。
- 功能提交 `48a53838fea83585657285110c5c9e40d30f3206` 已推送至 GitHub 当前分支。
  服务器经同一 `noetix-volc` 别名执行 `git pull --ff-only`，从 `056c462` 快进
  至该提交；工作区干净，XML/YAML 指纹与本地一致，八个 XML 肩肘均显式为 0.01，
  四个相关 Python 文件静态编译通过。原 launcher 与八个 worker 的 PID、启动
  tick、完整命令和 cwd 在拉取前后完全一致，输出 `SERVER_ARM001_SYNC_PASS`。
  后续提交仅补记这条同步证据，不改变已通过测试的参数或实现。

## 2026-09-10：增加 SMPL sim2sim 入口并从大训练集传回十对参考数据

- 用户要求为 BUMI sim2sim 增加 SMPL 输入，并从 noetix-volc 大数据集另外下载
  十对 Robot/SMPL 参考。起始分支 `feature/bumi-native-sonic-full-training`，HEAD
  `6ba4ef35d6992777ff0d664f5e63261c0872db56`，与 upstream 领先/落后均为 0；
  唯一未跟踪文件 `g1.tar.gz` 受保护。本轮不修改训练参数、PD、频率或 XML。
- 修改范围为 BUMI 专用 SMPL 加载/观测模块、sim2sim 核心、数据集加载器、CLI、
  专用回归测试、使用说明和本记录；默认 Robot 入口保持兼容，不改 G1/H2 通用逻辑。
- 依据 30000 步模型的保存配置与实际训练观测函数，实现 SMPL 连续十帧、每帧间隔
  0.02 秒、720 维局部人体关键点与 60 维相对根朝向，拼接 690 维本体历史为
  1470 维输入。pose_aa 的根朝向执行 Y-up→Z-up 和 SMPL 基准旋转消除；
  已离线处理的 smpl_joints 不重复转轴、不额外减根平移。Robot 仍为 1170 维。
- 新数据仅保存到独立且被 Git 忽略的正式 data 子目录，不覆盖旧五对；服务器源为
  `bumi3_sonic_three_source_base_anchor_v2/train`，仅选实际解析到
  `bumi3_smpl_97660_v1` 的大集配对，下载时跟随符号链接并核验 SHA-256。
- 验证结果、下载清单、同步证据与临时目录清理在完成后追加；未完成前不将接口
  实现或有限值检查表述为动作质量通过。回滚应使用新的反向提交，仅撤销本节改动。
- 新增 `gear_sonic/utils/mujoco_sim/bumi3_smpl_reference.py`：读取训练格式的
  PKL/NPZ 和具名容器，校验 50 FPS、[T,72]/[T,24,3]、有限值；按当前训练
  `commands.py`、`observations.py` 与 `remove_smpl_base_rot` 实现人体编码输入。
  新增 `gear_sonic/tests/test_bumi3_smpl_sim2sim.py`，直接抽取训练函数体与部署值
  比较（容差 2e-6），避免用部署实现自身生成期望值；覆盖格式、配对、纯人体入口、
  未来步长、末尾/循环、冻结、T/P、模型维度和数据集起始轨迹选择。
- `bumi3_sim2sim.py` 按 encoder 选择 1170/1470 输入，复用原本体历史和 PD。
  `bumi3_motion_dataset.py` 在 SMPL 模式读取 smpl，配对 Robot 用于初始化和
  红色影子；帧数/FPS 不一致直接拒绝。可省略配对 Robot，明确以 BUMI 默认
  站姿、0.4744m 根高和当前 SMPL yaw 初始化，此时不显示虚构参考机器人。
- CLI 增加 `--encoder robot|smpl`、`--robot-motion`、`--robot-motion-key` 和
  `--motion-name`；最后一项指定从清单哪条开始，P 仍按原顺序循环。默认 Robot
  命令保持可用。SMPL 模式需配套 `model_step_030000_smpl.onnx`，不能混用
  `*_g1.onnx`；两方向真实模型维度错误均已实测拒绝。配对红影仍是机器人参考，
  未新增人体 mesh/骨架渲染。详细命令与字段语义已写入 `bumi3_sim2sim.md` 第 3.4 节。
- 实际下载目录为 `data/noetix_bumi3_bigset_10pairs_20260910/`，共 20 个 PKL、
  7,566,316 bytes，10 对共 9067 帧/181.34 秒；robot/smpl 每对同名、同帧数、
  同为 50 FPS。目录内 `dataset.json` 保留播放顺序，`transfer_manifest.json`
  记录服务器符号链接路径、解析后的真实源路径、大小和每文件 SHA-256。
  下载通过 `rsync -avL --files-from=<十文件清单>`，SSH 使用固定 noetix-volc
  别名及 `-o ProxyCommand=none`。所有 20 文件完整性匹配，无本地符号链接，
  Robot/SMPL 两种加载器均成功读入十条，输出 `TEN_PAIRS_TRANSFER_SHA256_AND_LOAD=PASS`。
- 按动作类型选择而非策略效果筛选；早期窄名称候选无符合限制的配对，未下载任何
  不完整候选，最终扩大同类型名称匹配。选取时跳过部分 Robot/SMPL 相差一帧的
  源文件，不裁剪、不补齐，不覆盖原五对；最终具体名称、帧数和时长见使用文档表格。
- 资产和配置完全未改：XML SHA-256
  `1ef8da2e76be03430ba7f022e49309f194a289174db0275d7d3a123197cac3e3`，YAML
  `f52be29ca85a264273dc5ab75055ea52b8c297a362d093fd27f25ca90d9865f8`。
  Robot ONNX 为 `e884db48c3d5d222821c0816f9c4c81fbcd8e3b9e9129cefcd507ab463466a9a`，
  SMPL ONNX 为 `6f7e75978cff5e90e117036457d42c50e77061e37c4f6b4c033c92c71da85cf7`；
  两者继续使用原导出文件，不重新导出模型或修改训练。
- AST 与起始 HEAD 比较确认 `_apply_pd_control`、`step_control`、`reset`、
  `_build_robot_tokenizer`、`_build_proprioception`、根角速度、本体状态、参考速度、
  heading 对齐、armature 应用及模型/执行器核验共 12 个方法未改，输出
  `ORIGINAL_PD_DYNAMICS_AND_ROBOT_OBSERVATION_UNCHANGED=PASS`。
- 测试命令：`/home/weili/miniconda3/envs/env_isaaclab/bin/python -m pytest -q gear_sonic/tests/test_bumi3_sim2sim.py gear_sonic/tests/test_bumi3_motion_playlist.py gear_sonic/tests/test_bumi3_smpl_sim2sim.py -p no:cacheprovider --basetemp=/tmp/bumi-smpl-entry-20260910-uIz0Bc/pytest-final`；
  **44 passed in 6.57s**，含新增 10 项。唯一 warning 来自读取既有训练源码时
  历史 docstring 的 `\*` 转义（DeprecationWarning），不涉及动力学数值。
  `python gear_sonic/tools/validate_bumi3_sim2sim.py --skip-smoke` 输出
  `BUMI3_SIM2SIM_VALIDATION=PASS`；CLI help、新清单选 wave 的 10 秒实际回放、
  单条 SMPL 配对入口 validate-only 均成功。
- 真实 ONNX 回放使用专用临时 `runtime_check.py`：旧 wave 两种编码器各
  1500 步等待，再 T 播放 219 帧，末尾额外 500 步保持；新十对每条 250 步等待、
  T 播放完整帧数、额外 100 步保持。每个物理控制步检查有限值，记录根高和根倾角，
  全部 MuJoCo warning=0；其中一条的摔倒作为质量失败如实保留，未混称全通过。
  实际 SMPL ONNX 在 P 后也成功切至下一条、重置到第 0 帧并保持，观测为 1470 维。

| 动作 / 编码器 / 初始化 | 等待最低根高 m | 等待最大倾角 ° | 播放最低根高 m | 播放最大倾角 ° |
|---|---:|---:|---:|---:|
| wave_R_001__A428 / robot / 配对 | 0.462505 | 5.236921 | 0.458501 | 9.532584 |
| wave_R_001__A428 / smpl / 配对 | 0.462505 | 6.034218 | 0.455079 | 11.267049 |
| Idle_Right_001__A018 / smpl / 配对 | 0.449265 | 8.901551 | 0.459238 | 3.681924 |
| walk_forward_amateur_003__A001 / smpl / 配对 | 0.045201 | 83.981392 | 0.050779 | 91.972644 |
| walk_backward_loop_001__A021 / smpl / 配对 | 0.461590 | 5.216294 | 0.433238 | 10.989346 |
| wave_R_001__A431 / smpl / 配对 | 0.463453 | 6.740301 | 0.459144 | 9.274743 |
| squat_003__A361 / smpl / 配对 | 0.461762 | 3.961279 | 0.241372 | 32.131026 |
| Jump_002__A018 / smpl / 配对 | 0.460863 | 4.557819 | 0.411679 | 26.981438 |
| dance_basic_chaines_180_R_fast_001__A309 / smpl / 配对 | 0.463715 | 6.401687 | 0.418626 | 20.070341 |
| Neutral_kick_trash_004__A057 / smpl / 配对 | 0.455578 | 6.252736 | 0.402414 | 12.671854 |
| pels_air_punch_001__A493 / smpl / 配对 | 0.460645 | 2.592767 | 0.429097 | 23.159376 |
| run_start_180_R_001__A327 / smpl / 配对 | 0.459082 | 5.460049 | 0.369357 | 29.481410 |
| wave_R_001__A428 / smpl / 默认站姿 | 0.464540 | 5.610916 | 0.455545 | 11.263624 |

- 表中前走动作的“播放”从已经摔倒的等待状态开始，不能据此判断动态跟踪能力。
  为区分首帧保持与完整播放，另做独立 reset 的 Robot/SMPL 各 10s 冻结和自动播放对照：
  - robot，首帧等待 10s：最低根高 0.037799m，最大倾角 84.129398°，结束根高 0.052308m，首次根高<0.15m且倾角>60°的时刻 1.24s。
  - robot，自动播放 30.18s + 末帧保持 2s：最低根高 0.391959m，最大倾角 18.758594°，结束根高 0.467631m，首次根高<0.15m且倾角>60°的时刻 Nones。
  - smpl，首帧等待 10s：最低根高 0.045201m，最大倾角 83.981392°，结束根高 0.052233m，首次根高<0.15m且倾角>60°的时刻 1.04s。
  - smpl，自动播放 30.18s + 末帧保持 2s：最低根高 0.396225m，最大倾角 19.917747°，结束根高 0.472964m，首次根高<0.15m且倾角>60°的时刻 Nones。
- 前走首帧最大参考关节速度约 31.937 rad/s；将整段目标窗口冻结并把初始化速度设为零，不等价于播放此动态动作。两编码器等待都会摔倒而自动播放均不摔，说明此样本不适合当前首帧保持；查看时使用 `--autoplay`。未为规避此限制改动控制器、强写物理状态或删样本。
- 旧 wave 的纯 SMPL 默认站姿入口另验证等待 10s、完整播放和末尾保持 5s，最大倾角约 11.26°，未摔倒。新十对其余九条等待/播放未见明显摔倒；不将此有限样本结果表述为全数据集动作质量合格。
- 本轮未启动 Isaac Lab GUI、未重训、未进行人工 GUI 或实机验收；训练函数数值一致性、MuJoCo 动力学及键盘队列路径为已执行检查。原8卡训练在同步前 PID/启动 tick/cwd/命令均与上轮一致，服务器同分支 HEAD 6ba4ef3，工作区干净。
- 功能提交 `a7592c9ea9b713809de44de5214547ca62d5b4ee` 已推送 GitHub 当前分支；noetix-volc 同分支通过 `git pull --ff-only` 从 6ba4ef3 快进到该提交，工作区干净。5 个相关 Python 文件静态编译通过，相关源码及 XML/YAML 指纹与本地一致。同步前后 launcher 3269510（start_ticks=964046165）和八个 worker 3269523～3269530（start_ticks=964046505）的 PID、启动 tick、cwd 和完整命令逐项完全一致，输出 `SERVER_SMPL_ENTRY_SYNC_PASS`。后续仅追加审计记录，不改变已经验证的实现。
- 测试与传输关键证据已归档后，确认本线程执行进程结束，并检查可读进程的 cmdline/cwd/fd 无目录引用，仅清理精确专用目录 `/tmp/bumi-smpl-entry-20260910-uIz0Bc`（158 文件，618252 bytes），输出 `TASK_TEMP_CLEANUP_PASS`。正式十对数据、旧五对、模型、测试源码和用户 g1.tar.gz 保留。该临时路径此后仅作历史来源记录。

## 2026-09-16：地面接触专项微调——补记配置审计、修复启动器静默失败并正式启动 100k 微调

### 1. 起点、授权范围与背景

- 所属分支 `main`，起始 HEAD `b0b1ace77ff1993519b64a7d6c06bb65ec54aca6`，与 origin 一致，工作区干净。
- 用户在会话开始时已完成以下工作，但**未同步写入本记录**（违反本文件 §开头及 `agent.md` 第 1 条），本节先补记这部分内容，再记录本轮新增修改：
  - 提交 `1af2ea0`：新增地面接触专项微调配置
    `gear_sonic/config/exp/manager/universal_token/all_modes/sonic_bumi3_ground_finetune.yaml`，
    新增奖励函数 `reference_conditioned_undesired_contacts`
    （`gear_sonic/envs/manager_env/mdp/rewards.py`），新增
    `tools_local/bumi_cluster.sh` 的 `launch-ground-finetune` /
    `remote-ground-node` 入口及 `tools_local/bumi_cluster.env.example` 的
    `GROUND_FINETUNE_*` 样例字段。
  - 提交 `dcf83c9`：修正微调配置 `defaults` 中父配置引用路径。
  - 提交 `732b9ea`：`validate_bumi3_integration.py` 增加
    `--ground-finetune` smoke 开关。
  - 提交 `b0b1ace`：`validate_bumi3_integration.py` 同步接触参数校验期望值。
  - 提交 `f05d813`：把 `remote_start`/`remote_ground_start` 的 tmux 启动方式从
    `cd REPO && ... tmux new-session -d -s NAME bash -lc INNER` 改为
    `tmux new-session -d -s NAME -c REPO INNER`，用户称此举修复了此前定位到的
    "嵌套 tmux → bash -lc 命令层" 零日志问题，随后仅做了一次使用旧
    `sonic_bumi3`（非微调）配置、64 envs/GPU、5 iteration 的冒烟
    （`launch-smoke`），**未实际跑通 `launch-ground-finetune` 这条新入口**
    即计划直接启动 100k 正式微调。
- 用户本轮指令：核对上述工作的实际效果与进度，若发现问题或"思维混乱"可按其
  微调方案重做，确认无误后启动两台服务器共 16 卡、100,000 iteration 的
  低姿态/地面接触专项微调。

### 2. 配置语义审计结论

逐项核对 `sonic_bumi3_ground_finetune.yaml` 相对基线 `sonic_bumi3.yaml` 的
偏移是否真的只影响低姿态（参考根高 < 0.40 m）场景：

- **接触惩罚**（`reference_conditioned_undesired_contacts`）：正确按
  `command.anchor_pos_w[:, 2] < low_reference_height` 门控，且门控用的是
  **参考**高度而非机器人自身高度（避免策略靠主动摔倒规避惩罚）。符合预期。
- **`anchor_pos`／`ee_body_pos` 终止阈值放宽**：两者对应的函数
  `exceeded_anchor_height`／`exceeded_body_height`
  （`gear_sonic/envs/manager_env/mdp/terminations.py:97,206`）原生支持
  `threshold_adaptive + down_threshold + root_height_threshold`，微调配置只
  改了 `down_threshold`（0.25→0.40、0.40→0.50），**确认只在参考根高过低时生效**，
  符合"仅放宽低姿态"的表述。
- **`anchor_ori_full`／`foot_pos_xyz` 终止阈值放宽**：核查对应函数
  `exceeded_anchor_ori`／`exceeded_body_pos`（同文件 160/182 行）后确认，
  这两个函数**不支持任何按参考高度分档的参数**，只有一个全局
  `threshold`。微调配置把 `anchor_ori_full.threshold` 从基线继承的 0.2
  （来自 `terminations/tracking/base_adaptive_strict_ori_foot_xyz.yaml`）
  放宽到 1.0（5 倍），把 `foot_pos_xyz.threshold` 从 0.20 放宽到 0.35，
  **这两项实际对全部参考姿态（含站立、行走）生效，并非仅低姿态**。
  `validate_bumi3_integration.py::_validate_resolved_configs` 已把这两个数值
  锁定为断言期望值，说明是有意为之而非笔误，但配置文件注释
  （"Upright thresholds remain inherited from the scratch baseline"）
  与该实际效果不完全一致，可能造成后续误解。**本轮判断为已知设计取舍、
  不阻塞本次启动**：定量影响仅由本节记录、留待后续用 TensorBoard 的
  站立/行走 bin 内 reward、以及是否出现方向/落脚精度退化来复核；若观察到
  普通动作精度下降，第一排查点是这两个全局阈值，修复方式是仿照
  `exceeded_anchor_height` 的模式给 `exceeded_anchor_ori`/`exceeded_body_pos`
  增加按参考高度分档的可选参数，而非简单调回原阈值。
- **学习率**：`actor_learning_rate` 2e-5→1e-5、`critic_learning_rate`
  1e-3→5e-4，与用户所述"减半"完全一致。
- **困难采样与 quarantine**：基线 `uniform_sampling_rate=0.9`（10% 困难），
  微调改为 `0.20`（80% 困难）；`quarantine.enable` 由 `true` 改为
  `false`，`dynamics_gate.enable` 保持 `true`（不受影响）。均与用户描述一致，
  且已在下述真实冒烟的 TensorBoard 风格指标行中核实
  `Env/adp_samp/quarantined_motions` 全程为 0。
- **checkpoint 加载语义**：`gear_sonic/train_agent_trl.py` 的
  `resume_checkpoint()` 只设置 `config.checkpoint`，不改 `config.resume`；
  `PPOTrainer.load_checkpoint(path, resume=False)`
  （`gear_sonic/trl/trainer/ppo_trainer.py:2589`）在 `resume=False` 时只
  加载 `actor_model_state_dict`/`value_state_dict`，跳过 optimizer、
  lr_scheduler 与 `env_state_dict`（后者承载 adaptive sampling/quarantine
  运行时状态）。`remote_ground_node` 固定传入 `+resume=false
  checkpoint=$checkpoint`，与用户所述"仅加载网络权重、重置 optimizer 与
  adaptive/quarantine 状态"完全一致。

结论：配置语义基本正确，实现质量不是"思维混乱"，可以继续；但发现并记录了
一项设计取舍（anchor_ori_full/foot_pos_xyz 全局放宽）供后续复核，以及下述
两项必须先修的实际缺陷。

### 3. 发现并修复的问题一：本机 `.local` 配置缺少专项微调的 iteration/env 数

- `tools_local/bumi_cluster.sh::launch_ground_finetune` 用
  `envs="${GROUND_FINETUNE_ENVS_PER_GPU:-4096}"`、
  `iterations="${GROUND_FINETUNE_ITERATIONS:-50000}"` 取值，但本机真实
  `.local/sonic_bumi_cluster.env`（Git 忽略，不在仓库版本控制范围）当时
  **没有这两个字段**，只有样例文件 `tools_local/bumi_cluster.env.example`
  里写了默认值 50000。若直接执行
  `launch-ground-finetune`，会静默启动 50,000 iteration 而非用户要求的
  100,000。
- 修复：在本机 `.local/sonic_bumi_cluster.env` 追加
  `GROUND_FINETUNE_ENVS_PER_GPU="4096"`、
  `GROUND_FINETUNE_ITERATIONS="100000"`。该文件被 Git 忽略，此修改不产生
  代码提交，仅本机生效；两台服务器不读取本机 `.local` 文件，不受影响。

### 4. 发现并修复的问题二：tmux 内层 `exec` 导致启动器静默零日志（f05d813 的"修复"本身仍有 bug）

- 现象：用 `launch-ground-finetune` 通过 tmux 正式入口启动后，两端 tmux
  会话在 1 秒内消失，`node{0,1}.log` 始终 0 字节，且没有任何可诊断输出；
  多次复现（包括 4096 envs/GPU 全量参数、64 envs/GPU 冒烟参数）现象完全一致。
- 排查过程（均在 gpu14/gpu15 上实测，非本地推断）：
  1. 直接用 `sh -c "$inner"`（不经 tmux）执行完全相同的内层命令：正常运行，
     rank0 因缺少 rank1 伙伴而阻塞在 accelerate 分布式 rendezvous（符合预期，
     非 bug）；rank1 单独执行时真实拉起 8 个 `accelerate`/`train_agent_trl.py`
     worker 进程。证明内层命令字符串本身、`%q` 转义、路径解析均无问题。
  2. 用 `tmux capture-pane`/`pipe-pane` 紧跟 `tmux new-session` 尝试捕获
     pane 输出：均已 "can't find pane"，会话在毫秒级消失。
  3. 最小复现矩阵（gpu14，tmux 3.2a，`default-shell` 确认为 `/bin/bash`）：
     - `tmux new-session -c DIR "exec sleep 3"` → 存活。
     - `tmux new-session -c DIR "exec bash -c 'sleep 3'"` → 存活。
     - `tmux new-session -c DIR "exec bash tools_local/bumi_cluster.sh > log 2>&1 < /dev/null"`
       （无子命令，应打印 usage 后 `exit 2`）→ 会话消失且 **log 为空**。
     - 去掉 `exec`，同样无子命令的调用 → 会话消失（符合预期，命令执行完
       tmux 关闭 pane 是正常行为），但 **log 正确写入了完整 usage 文本**。
     - 交叉验证 "exec + 绝对路径" 与 "无 exec + 相对路径"：前者 log 为空，
       后者 log 有内容，证明与相对/绝对路径无关，**唯一变量是 `exec`**。
  4. 结论：在本项目服务器的 tmux 3.2a 上，`tmux new-session -c DIR
     "exec CMD > LOG 2>&1 < /dev/null"` 这一模式会导致 `>` 重定向失效且
     pane 立即消失，去掉 `exec`（让内层 `bash tools_local/bumi_cluster.sh
     ...` 作为子进程而非替换进程镜像运行）后行为完全正常，重定向和会话
     生命周期（命令结束即关闭）均符合预期。
- 修复：提交 `b0c9547`，把 `remote_start`／`remote_ground_start`
  （`tools_local/bumi_cluster.sh` 98-122 行）内层命令模板中的
  `"exec bash tools_local/bumi_cluster.sh ..."` 改为
  `"bash tools_local/bumi_cluster.sh ..."`，两处改法一致。`bash -n` 语法检查通过。
- 兼容性边界：该 bug 存在于 `remote_start`（`launch-smoke`/`launch-train`）
  与 `remote_ground_start`（`launch-ground-finetune`）共用的同一段代码，
  修复方式相同；但**本轮只用 `launch-ground-finetune` 路径做了完整真实验证
  （见 §5、§6），未重新验证 `launch-smoke`／`launch-train`**。用户此前报告的
  一次"16 卡冒烟通过"发生在 f05d813 提交**之前**（仍是旧 `bash -lc` 实现），
  不能作为 f05d813 之后、修复前的 `remote_start` 已验证的证据。

### 5. 真实端到端冒烟验证（launch-ground-finetune，64 envs/GPU、5 iteration）

- 提交 `b0c9547` 后先 `git bundle` 同步两台服务器到该 SHA（GitHub 直连
  当前仍会超时，沿用"本地推 GitHub + SSH 传增量 bundle"方式，
  `git fetch <bundle> <sha> && git merge --ff-only FETCH_HEAD`），
  `bash tools_local/bumi_cluster.sh verify-code` 两端均 `CODE_OK`。
- 用 `GROUND_FINETUNE_ENVS_PER_GPU=64 GROUND_FINETUNE_ITERATIONS=5
  bash tools_local/bumi_cluster.sh launch-ground-finetune
  bumi3_ground_finetune_smoke5_20260916
  /data/ouqin/checkpoints/sonic_bumi3_base_100000.pt` 启动真实 16 卡冒烟，
  checkpoint 与 §3449 节记录的同一份 100000 步 checkpoint 一致
  （SHA-256 `2abb18d65d74c16c23cda3a9f535cdf60e762776f66e4a1748890b79920e5d1e`，
  两端一致，本轮重新 `sha256sum` 复核）。
- 实际输出关键证据：
  - `[INFO] Termination Manager` 表格显示 5 个激活项
    `time_out/anchor_pos/anchor_ori_full/ee_body_pos/foot_pos_xyz`，
    `[INFO] Reward Manager` 表格显示 11 项含 `undesired_contacts`，
    `policy` 观测 690 维、`critic` 1227 维、`tokenizer` 含 g1/smpl 双路，
    与配置定义完全一致，证明 Hydra 组合在真实 Isaac Lab 运行时确实按
    微调配置生效，不止是 `validate_bumi3_integration.py` 的静态断言。
  - 两端各 8 个 worker 进程均打印
    `Loading checkpoint from /data/ouqin/checkpoints/sonic_bumi3_base_100000.pt`
    及 `Loaded checkpoint from step 100000`。
  - 5 次 PPO 迭代全部完成：`Mean rewards` 依次约
    -1.50 → -0.30 → 1.53 → 3.12 →（第 5 次未逐字记录但训练正常结束），
    与用户此前旧配置冒烟报告的数值曲线高度吻合（同一份起始网络权重下的
    合理复现）；`Total episodes: 5120`、`Total timesteps: 122880`、
    `Iteration time: 2.51s`，与 5×24×1024 的理论步数一致。
  - `Env/adp_samp/quarantined_motions: 0.0000`
    （全程为 0，确认 `quarantine.enable=false` 生效）、
    `Env/adp_samp/dynamics_gate_failed_motions: 23.0000`（dynamics_gate
    仍按基线生效，未受微调配置影响，符合预期）。
  - 全程无 `Traceback`／`CUDA out of memory`／`NCCL` 报错；rank1
    （gpu15）日志出现两条 numpy
    `RuntimeWarning: Mean of empty slice`／`invalid value encountered in
    scalar divide`，判断为 64 envs/5 iteration 极小样本下某些统计 bin
    为空的良性告警，非致命错误，**该现象未在 100k 正式规模下复现验证**，
    留作已知风险项。
- 冒烟专用运行目录（`bumi3_ground_finetune_{smoke,smoke2,smoke3,smoke5,captest*}*`、
  `debug_direct_test{,2}`）与 `/tmp` 下调试日志已在确认无进程引用后清理
  完毕，仅保留本节记录的关键证据；未清理任何非本线程产生的目录（如
  `ground_smoke16_debug`、`sonic_bumi3_ground_smoke16_from100k_20260916_1200`
  等疑似用户此前遗留的验证产物，本轮未触碰）。

### 6. 正式启动：16 卡、100,000 iteration 地面接触专项微调

- 冒烟通过、`.local` 配置修正、代码修复同步完成后，执行：
  `bash tools_local/bumi_cluster.sh launch-ground-finetune
  sonic_bumi3_ground_finetune_100k_20260916
  /data/ouqin/checkpoints/sonic_bumi3_base_100000.pt`，
  `launch_ground_finetune` 内部 `verify_code` 先确认两端均为 `CODE_OK
  b0c95477ac01a3cb1535c03406fc3cb72e412c8e`，打印
  `envs/GPU=4096, world=16, iterations=100000`，与用户要求完全一致。
- 启动后持续监控约 6 分钟：GPU 显存从空闲 4 MiB 经场景/动作库构建阶段的
  约 5.5～7.5 GiB，在 checkpoint 加载完成、进入真正训练迭代后跃升至约
  15～15.7 GiB／卡（16 张卡全部如此，`nvidia-smi` 两端逐一核实），
  两端 `Loading checkpoint`／`Loaded checkpoint from step 100000`
  各自打印 8 次（对应每节点 8 张卡各一个 worker 进程），随后
  `Learning iteration` 计数持续增长（记录时已到第 6 次），两端 tmux
  会话 `sonic_sonic_bumi3_ground_finetune_100k_20260916_node{0,1}`
  均存活，无 `Traceback`／`CUDA out of memory`／`NCCL` 报错。
- 训练数据来源：`ROBOT_MOTION_DIR=/data/ouqin/datasets/bumi3/train/robot`、
  `SMPL_MOTION_DIR=/data/ouqin/datasets/bumi3/train/smpl`（与基线训练同一
  份完整 97,660 条数据集，未做任何裁剪，`exclude_motion_keys=[]`），符合
  用户"仍使用完整数据集，保留 standing/walking replay"的要求。
- 训练产物与监控：`RUN_ROOT/sonic_bumi3_ground_finetune_100k_20260916/`
  下 `node{0,1}.log`、checkpoint 由 rank0（gpu14）负责写入；后续查看训练
  状态用 `bash tools_local/bumi_cluster.sh training-status
  sonic_bumi3_ground_finetune_100k_20260916`，TensorBoard 走 §9.3 描述的
  SSH 端口转发方式，本轮未额外新建转发隧道。

### 7. 未执行项、已知风险与回滚

- 未执行：`launch-smoke`／`launch-train`（非微调路径）在 exec 修复后的
  重新验证；100k 正式规模下是否复现 §5 提到的 numpy 空切片告警；
  anchor_ori_full/foot_pos_xyz 全局放宽对普通站立/行走动作精度的定量影响
  （需等待正式训练产出足够 TensorBoard 数据后按 bin 复核，见 §2）。
- 已知风险：若后续观察到普通动作追踪精度相对基线 100k 明显退化，应优先
  复查 §2 提到的 `anchor_ori_full`/`foot_pos_xyz` 全局阈值放宽，而非默认
  归因于学习率或采样策略。
- 回滚方法：训练层面——`training-status` 显示异常或需要终止时，
  按 §11 故障处理边界（本文件前述章节）在 tmux 会话内正常终止训练进程，
  不使用 `git reset --hard`/`kill -9` 以外的破坏性手段；代码层面——本轮
  两个提交（`b0c9547` 修复 `exec` bug）均为独立小提交，如需回滚，创建新的
  反向提交撤销 `tools_local/bumi_cluster.sh` 的两处 `exec` 前缀改动即可，
  不影响 `1af2ea0`～`b0b1ace` 引入的微调配置本身。
- 交付确认：本地、GitHub（`git push origin main`）、gpu14、gpu15 均已同步到
  `b0c95477ac01a3cb1535c03406fc3cb72e412c8e`；`sonic_bumi3_ground_finetune_100k_20260916`
  训练已在两端以 tmux 会话形式持续运行，未依赖任何前台 SSH 连接。

## 2026-09-17：调研旧项目 BVH 对齐方法论并整理新机型数据准备经验文档

### 1. 起点与背景

- 用户追问"BVH→SMPL 是否经过对齐筛选"，本轮先只读核查两个不在本仓库内、
  也不在当前两台训练服务器（GPU14/GPU15，`/data/ouqin/...`）上的历史数据目录：
  `/data/muyingchao/SONIC_BUMI`（BUMI 早期数据准备项目）与
  `/data/muyingchao/SONIC_N3`（并行的 N3 机型项目），两者恰好和 GPU14
  物理共存，通过已有的 `GPU14_SSH`/`SSH_KEY` 即可只读访问，未新增任何凭据
  或连接方式，也未修改这两个目录下的任何文件。
- 核查确认：`/data/ouqin/datasets/bumi3/train/`（当前生产训练数据）的
  `audit.json` 显示 `"pairs": 97660, "passed": 97660, "failed": 0`，与
  `SONIC_BUMI/reports/final_clips.txt`（103,126 行）之差恰好等于
  `SONIC_BUMI/reports/joint_limit_rejected_clips.txt` 的行数（5,466 行），
  `103126 - 5466 = 97660`，证明当前生产数据确实是"BVH 对齐检查 → SMPL 帧数
  修复 → 关节限位筛选"三层过滤后的最终结果，链路可追溯、数字可对上。
- `SONIC_BUMI/tools/make_smpl_symlinks.py` 的 docstring 确认其 SMPL 数据来源
  为 `SONIC_N3 smpl_filtered`，实地核查 `/data/muyingchao/SONIC_N3/data/extracted/
  smpl_filtered` 与 `sample_data/smpl_filtered` 均存在，证明 SMPL 数据在
  BUMI3/N3 两个机型项目间确实被复用，而不是各自独立重新拟合。

### 2. 新增文档

- 新增 `docs/source/getting_started/sonic_motion_dataset_alignment_playbook.md`：
  面向"给新机型准备 SONIC 训练数据的 Claude Code"整理的经验步骤文档，内容
  来自对 `SONIC_BUMI/reports/alignment_summary.md`、
  `reclassification_summary.md`、`HANDOFF.md` 的实地阅读与提炼，覆盖：
  机型相关/无关数据流的划分、BVH↔Robot 对齐检查三项方法（时长/lag/分段）
  及其阈值校准方法论（注入偏移灵敏度测试、富集分析）、A/B/C/D 分档策略、
  SMPL/Robot 帧数修复、关节限位筛选、坐标契约踩坑记录（Y-up/Z-up 变换只
  适用机器人侧、Euler 角速度伪极值问题）、只读软链接索引构建方式，以及给
  新机型项目的执行清单。文末列出旧项目参考实现的具体文件路径（明确标注
  "不在本仓库内、不可跨项目直接 import，需要移植或重新实现"），并声明旧项目
  校准出的具体阈值数字（如 0.5m 动态范围阈值、35x 富集倍数）不能直接套用到
  新机型，必须用新机型自己的数据重新校准。
- `docs/source/getting_started/bumi3_local_and_16gpu_guide.md` 顶部增加一行
  交叉引用指向新文档，与该文件已有的
  `codex_local_control_multi_node_training.md` 引用风格一致。

### 3. 兼容性与验证边界

- 本轮不改动任何训练代码、配置、机器人资产或数据本身，只新增/编辑纯文档；
  `sonic_bumi3_ground_finetune_100k_20260916` 训练未受影响，未停止、未重启。
- 未执行项：未在新机型上实际运行文档里描述的对齐检查工具链（本仓库当前
  没有新机型项目，本文档是提前为未来新机型准备的参考资料，无法针对不存在
  的新机型跑真实验证）；未尝试移植 `SONIC_BUMI/tools/` 下的具体脚本进本仓库，
  文档中明确说明这些脚本位于仓库外部服务器，仅供查阅方法论。
- 未验证 `/data/muyingchao/SONIC_BUMI`、`/data/muyingchao/SONIC_N3` 两个目录
  是否为长期保留的项目资产还是临时数据；本轮只读访问，未改写、未删除，
  也未确认这两个目录的清理/保留策略，如需长期依赖其中数据应向用户确认。

### 4. 发现并修正远程命名混淆：`origin` 已改指向内网 GitLab，不再是 GitHub

- 推送本节文档提交时发现，本地 `git push origin main` 实际推到了
  `git@10.113.0.24:muyingchao/sonic_bumi_full.git`（内网），而不是文档里
  一直描述的 GitHub；`git remote -v` 确认本地实际有两个远程：`github`
  （`git@github.com:Mu-Yingchao/sonic_bumi_full.git`，真正的唯一真源）和
  `origin`（内网 GitLab 镜像）。会话早些时候的 `git push origin main`
  （`b0c9547`、`49e4fd2` 两次）确实推到了 GitHub（当时终端输出明确显示
  `To github.com:...`），说明 `origin` 的 URL 是在本次会话过程中被改指向的，
  改动来源未知（本次会话没有执行过 `git remote set-url`）。
- 已用 `git push github main` 把落后的提交补推到 GitHub，确认本地、GitHub、
  内网 origin、GPU14、GPU15 五处重新一致（`b2f0096`）。
- 用户明确指示：之后默认一律推到 GitHub（`git push github main`），因为
  本地↔服务器的同步闭环设计上就是通过 GitHub 完成的；只有用户明确要求时才
  推到内网 GitLab（`git push origin main`）。
- 已把这条规则写入 `docs/source/getting_started/bumi3_local_and_16gpu_guide.md`
  的"日常修改同步顺序"一节（把示例命令从 `git push origin main` 改为
  `git push github main`，并新增一段"本地远程命名注意"说明两个远程分别是什么、
  默认应该推哪个）。`codex_local_control_multi_node_training.md` 里的
  `git remote add origin git@github.com:...` 仍然正确（面向全新项目的模板，
  新项目不会有这种预先存在、被改名的冲突远程），本轮未改动该模板文档。
- 未执行项：未确认内网 `10.113.0.24` GitLab 镜像是谁、什么时候配置的，也未
  确认该镜像今后的用途（纯备份还是另有同步需求）；如果用户后续说明用途，
  应回来更新本节和对应文档。
