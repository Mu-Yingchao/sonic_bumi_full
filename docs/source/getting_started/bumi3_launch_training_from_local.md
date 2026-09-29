# 从本地开发机启动 BUMI3 双机 16 GPU 训练

本文是可直接照抄的操作手册，覆盖从"决定开训"到"训练稳定跑起来"的完整流程，以及
每一步的验证点和已经踩过的坑。背景原理、sim2sim、ONNX 导出与部署见
`bumi3_local_and_16gpu_guide.md`；多节点控制的通用规范见
`codex_local_control_multi_node_training.md`。

所有命令都在**本地开发机**执行，不需要先登录服务器。

## 1. 启动前四项检查

```bash
cd /home/yingchaomu/下载/sonic_bumi_full
source .local/sonic_bumi_cluster.env
```

### 1.1 两台机器的整体状态

```bash
bash tools_local/bumi_cluster.sh status
```

逐台输出 hostname、代码短 SHA、8 张卡的显存与利用率、tmux 会话列表、正在跑的
`train_agent_trl.py` 进程。**要确认 16 张卡全部空闲**（显存个位数 MiB、利用率 0%）。

已有训练在跑时再起一个必然 OOM，而且会把正在跑的那个一起带崩——16 路 DDP 任何一个
rank 退出，整个作业就结束。

### 1.2 三端代码一致

```bash
bash tools_local/bumi_cluster.sh verify-code
```

必须看到两行 `CODE_OK` 且 SHA 与本地 `git rev-parse HEAD` 相同。不一致就先做第 2 步。

`launch-*` 内部会自动再调一次 `verify_code`，不一致直接退出，不会误启动。

### 1.3 rendezvous 端口空闲

```bash
for n in 14 15; do
  eval P=\$GPU${n}_PORT; eval S=\$GPU${n}_SSH
  echo "GPU$n:"; ssh -i "$SSH_KEY" -p "$P" "$S" "ss -ltn | grep -E '$MASTER_PORT|$NCCL_MASTER_PORT' || echo '  端口空闲'"
done
```

快速反复启动/杀掉时容易残留占用，撞上会导致 rank 0 起不来。

### 1.4 磁盘余量

```bash
for n in 14 15; do
  eval P=\$GPU${n}_PORT; eval S=\$GPU${n}_SSH
  ssh -i "$SSH_KEY" -p "$P" "$S" "df -h /data | tail -1"
done
```

一次 100k 训练产物约 21 G（每 2000 步一个 375 M 的 checkpoint），日志另有约 400 M。

## 2. 把新代码送到服务器

**只在本地改代码**，提交推送后再同步服务器；禁止直接编辑服务器工作树。

```bash
git add <明确的文件>
git commit -m "说明本次修改"
git push github main        # 默认推 github，不是 origin（origin 是内网 GitLab）
```

服务器从 GitHub 直连会超时，因此用 **git bundle 走 SSH** 传增量：

```bash
SERVER_SHA=$(ssh -i "$SSH_KEY" -p "$GPU14_PORT" "$GPU14_SSH" \
  "git -C $REMOTE_REPO rev-parse HEAD")
git bundle create /tmp/sync.bundle ${SERVER_SHA}..main

for n in 14 15; do
  eval P=\$GPU${n}_PORT; eval S=\$GPU${n}_SSH
  scp -i "$SSH_KEY" -P "$P" /tmp/sync.bundle "$S:/data/ouqin/sync.bundle"
  ssh -i "$SSH_KEY" -p "$P" "$S" \
    "cd $REMOTE_REPO && git fetch -q /data/ouqin/sync.bundle main \
     && git merge -q --ff-only FETCH_HEAD && echo GPU$n: \$(git rev-parse --short HEAD)"
done

bash tools_local/bumi_cluster.sh verify-code
```

`git bundle create` 的版本范围必须以**分支名**结尾（`${SHA}..main`）。写成
`${SHA}..${目标SHA}` 会因为范围里不含任何 ref 而报 `fatal: 不能创建空的归档包`。

## 3. 改了配置？先做 Hydra 组装验证

新增或修改 `gear_sonic/config/exp/...` 下的配置后，**必须验证覆盖真的生效**，
YAML 语法检查发现不了这类问题。

最典型的坑：exp 配置首行漏写 `# @package _global_` 时，Hydra 会把整个文件的内容放进
嵌套包，`manager_env` 等覆盖根本不落到全局配置树上——而**训练照常跑完 100k、日志零
报错**，只是覆盖完全没生效。2026-09-24 新增 `sonic_bumi3_filtered.yaml` 时就漏写过，
84 条黑名单实测解析结果是 0 条。

开发机通常没装 hydra，到服务器上验证：

```bash
ssh -i "$SSH_KEY" -p "$GPU14_PORT" "$GPU14_SSH" "cd $REMOTE_REPO && $REMOTE_PYTHON -c \"
from hydra import compose, initialize_config_dir
import os
with initialize_config_dir(config_dir=os.path.abspath('gear_sonic/config'), version_base=None):
    cfg = compose(config_name='base',
                  overrides=['+exp=manager/universal_token/all_modes/<你的配置名>'])
    m = cfg.manager_env.commands.motion.motion_lib_cfg
    print('exclude_motion_keys =', len(list(m.exclude_motion_keys)))
    print('uniform_sampling_rate =', m.adaptive_sampling.uniform_sampling_rate)
    print('actor/critic lr =', cfg.algo.config.actor_learning_rate,
          cfg.algo.config.critic_learning_rate)
\""
```

另外：`tools_local/bumi_cluster.sh` 里如果对某字段有命令行 `++key=value` 硬编码，
它会压掉配置文件的同名设置。新增依赖该字段的配置前，先确认启动器没有硬编码覆盖
（`exclude_motion_keys=[]` 就曾经被这样写死过，已移除）。

## 4. Smoke 测试

正式开训前必跑。16 卡 × 64 env × 5 iteration，约 2 分钟，能验证整条启动链路。

```bash
bash tools_local/bumi_cluster.sh launch-smoke smoke_$(date +%Y%m%d_%H%M)
# 用剔除台面动作的配置时：
bash tools_local/bumi_cluster.sh launch-smoke-filtered smoke_filtered_$(date +%Y%m%d_%H%M)
```

约 2 分钟后检查，四项都要满足：

```bash
RUN_ID=<上面打印的 run id>
ssh -i "$SSH_KEY" -p "$GPU14_PORT" "$GPU14_SSH" "
  L=$RUN_ROOT/$RUN_ID/node0.log
  echo '迭代数:'; grep -c 'Learning iteration' \$L
  echo '报错数:'; grep -icE 'traceback|CUDA error|RuntimeError' \$L
  echo 'tmux:'; tmux ls 2>/dev/null | grep $RUN_ID || echo '(会话已正常退出)'
  echo 'GPU:'; nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader | head -3
"
```

- 迭代数 = 5
- 报错数 = 0
- tmux 会话**已自行退出**（payload 跑完就退，这是正常收尾）
- GPU 显存已释放

任何一项不满足就不要开正式训练。日志停在 0 字节、tmux 会话瞬间消失，见第 8 节。

## 5. 正式启动

```bash
RUN_ID="sonic_bumi3_filtered_100k_$(date +%Y%m%d_%H%M)"
echo "RUN_ID=$RUN_ID"

bash tools_local/bumi_cluster.sh launch-train-filtered "$RUN_ID"
# 不剔除台面动作的基础配置用：
# bash tools_local/bumi_cluster.sh launch-train "$RUN_ID"
```

规模由 `.local/sonic_bumi_cluster.env` 决定，当前是 `TRAIN_ENVS_PER_GPU=4096`、
`TRAIN_ITERATIONS=100000`。**这两项若缺失会静默使用代码默认值**（迭代数默认只有
50000），新建配置文件时务必确认它们存在。

启动参数固定含 `+resume=false checkpoint=null auto_load_latest=false`，因此一定是
从零随机初始化，不会意外加载旧策略。

内部顺序是**先起 GPU15 的 rank 1、再起 GPU14 的 rank 0**：rank 1 会阻塞等待
rendezvous，反过来则 rank 0 可能超时退出并留下 8 个占显存的僵尸 worker。

## 6. 启动后必须验证的三件事

### 6.1 16 个 rank 全部在算

启动后约 4~8 分钟（Isaac Sim 初始化 + 动作加载较慢）：

```bash
bash tools_local/bumi_cluster.sh training-status "$RUN_ID"
```

健康输出：两台都显示 `training_ranks=8`（合计 16）；每卡约 15 GiB 显存、利用率有变化；
GPU14 显示持续增长的 `Learning iteration`；错误区为空。

`node1.log` 在动作加载结束后长期不增长是**正常的**——非 global-rank 0 不重复输出训练
表格，不能据此判断 GPU15 没在训练。

### 6.2 迭代真的在推进

```bash
ssh -i "$SSH_KEY" -p "$GPU14_PORT" "$GPU14_SSH" \
  "grep 'Learning iteration' $RUN_ROOT/$RUN_ID/node0.log | tail -1"
```

隔几分钟再跑一次，数字必须变大。

## 7. 监控

### 7.1 文本日志

```bash
# 实时跟踪（Ctrl+C 只停止查看，不影响训练）
ssh -i "$SSH_KEY" -p "$GPU14_PORT" "$GPU14_SSH" \
  "tail -f $RUN_ROOT/$RUN_ID/node0.log"

# 只看进度（日志可达数百 MB，不要 cat）
ssh -i "$SSH_KEY" -p "$GPU14_PORT" "$GPU14_SSH" \
  "grep 'Learning iteration' $RUN_ROOT/$RUN_ID/node0.log | tail -1"
```

### 7.2 TensorBoard

**一个 run 一个远端端口**，新 run 必须换端口，端口分配表见
`bumi3_local_and_16gpu_guide.md` §4.0。先查空闲端口：

```bash
ssh -i "$SSH_KEY" -p "$GPU14_PORT" "$GPU14_SSH" "ss -ltn | grep -E ':60[0-9][0-9]'"
```

在服务器起服务（`SESSION` 与 `PORT` 换成未占用的值）：

```bash
ssh -i "$SSH_KEY" -p "$GPU14_PORT" "$GPU14_SSH" "
  tmux new-session -d -s tb_$RUN_ID -c $REMOTE_REPO \
    '$REMOTE_PYTHON -m tensorboard.main \
     --logdir $RUN_ROOT/$RUN_ID/tensorboard --host 127.0.0.1 --port 6010 \
     > $RUN_ROOT/$RUN_ID/tensorboard_server.log 2>&1'
  sleep 8; ss -ltn | grep 6010 && echo TB_OK
"
```

本地建隧道（保持终端开着，无输出是正常的）：

```bash
ssh -i "$SSH_KEY" -p "$GPU14_PORT" -N \
  -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
  -L 6020:127.0.0.1:6010 "$GPU14_SSH"
```

浏览器打开 `http://127.0.0.1:6020`。

本地端口被 VS Code 占用是常见问题（报 `Address already in use`）。先确认本地空闲：

```bash
ss -ltnp '( sport = :6020 )'
```

被占就换 6021/6022/6023，**右侧的远端端口不要改**。`ExitOnForwardFailure=yes` 必须
带上，否则会出现"只绑定 IPv6、浏览器的 IPv4 请求被别的程序接走"的半成功状态。

100k 训练的 event 文件会涨到约 640 MB，浏览器首次加载慢属正常，不是卡死。

## 8. 停止训练

启动器没有 stop 子命令，手动杀：

tmux 会话名是 `sonic_<RUN_ID>_node<RANK>`，GPU14 是 rank 0、GPU15 是 rank 1：

```bash
# 先确认要杀的会话名对得上，别误杀别的训练
for n in 14 15; do
  eval P=\$GPU${n}_PORT; eval S=\$GPU${n}_SSH
  [ "$n" = 14 ] && RANK=0 || RANK=1
  echo "GPU$n 将杀: sonic_${RUN_ID}_node${RANK}"
  ssh -i "$SSH_KEY" -p "$P" "$S" "tmux ls 2>/dev/null | grep ${RUN_ID} || echo '  (无匹配会话)'"
done

# 确认无误后再执行
for n in 14 15; do
  eval P=\$GPU${n}_PORT; eval S=\$GPU${n}_SSH
  [ "$n" = 14 ] && RANK=0 || RANK=1
  ssh -i "$SSH_KEY" -p "$P" "$S" \
    "tmux kill-session -t sonic_${RUN_ID}_node${RANK} 2>/dev/null; \
     pkill -f 'experiment_dir=$RUN_ROOT/$RUN_ID' || true"
done
```

`pkill` 的匹配串带完整 `experiment_dir=` 路径，只会命中这一个 run 的 worker，
不会误伤同机器上的其他训练。

杀完务必确认显存真的释放，残留 worker 会占着卡：

```bash
bash tools_local/bumi_cluster.sh status
```

checkpoint 每 2000 步落盘，停掉最多损失 2000 步。
```
