#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""从训练 checkpoint 中提取逐动作的成功/失败统计，无需重跑任何仿真。

背景：``MotionLibBase.get_state_dict()`` 会把 ``adp_samp_motion_num_evaluations``
与 ``adp_samp_motion_num_failures`` 两个长度为 ``_num_unique_motions`` 的张量写进
checkpoint 的 ``env_state_dict['motion_lib']``，索引顺序与 ``_motion_data_keys``
完全一致。因此一次训练跑完后，逐条动作的历史失败率已经躺在 checkpoint 里，本脚本
只做只读提取，不加载任何动作数据、不启动仿真。

两点必须注意，否则会误读结论：

1. 多卡训练在 ``sync_and_compute_adaptive_sampling`` 里对这两个计数做的是**跨卡
   求均值**，因此这里读到的是「每卡平均次数」，全局总次数需要再乘以卡数。失败率
   是比值，不受该归一化影响。
2. 这些统计来自训练分布，带有自适应采样的强烈偏置（困难动作被反复采样，简单动作
   可能只有几十次），起始时刻随机且开启了域随机化，失败判据是该次训练所用的
   termination 阈值。因此它只能当作「免费的先验」，不能替代用统一判据跑的全量
   评估（``eval_agent_trl.py`` + ``im_eval`` 回调）。
"""

import argparse
import glob
import json
import os
import os.path as osp

import numpy as np
import torch


def rebuild_motion_keys(motion_dir):
    """按 ``MotionLibBase.load_data()`` 的完全相同方式重建动作 key 顺序。

    训练侧用的是 ``glob.glob(..., recursive=True)`` 的原生返回顺序（未排序），
    所以这里必须原样复刻，不能自作主张排序，否则索引会整体错位。
    """
    keys = [
        osp.splitext(osp.basename(f))[0]
        for f in glob.glob(osp.join(motion_dir, "**", "*.pkl"), recursive=True)
        if not f.endswith("metadata.pkl")
    ]
    return keys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--motion-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--num-gpus", type=int, default=16)
    args = parser.parse_args()

    print(f"[1/4] 加载 checkpoint: {args.checkpoint}")
    ckpt = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    print(f"      顶层 key: {sorted(ckpt.keys())}")

    if "env_state_dict" not in ckpt:
        raise SystemExit("checkpoint 中没有 env_state_dict，无法提取逐动作统计")
    ml_state = ckpt["env_state_dict"]["motion_lib"]
    print("      motion_lib 状态字段:")
    for k, v in ml_state.items():
        shape = tuple(v.shape) if torch.is_tensor(v) else type(v).__name__
        print(f"        {k}: {shape}")

    evals = ml_state["adp_samp_motion_num_evaluations"].float().numpy()
    fails = ml_state["adp_samp_motion_num_failures"].float().numpy()
    gate_failed = ml_state["adp_samp_dynamics_gate_failed"].bool().numpy()
    quarantined = ml_state["adp_samp_motion_quarantined"].bool().numpy()

    print(f"[2/4] 重建动作 key 顺序: {args.motion_dir}")
    keys = rebuild_motion_keys(args.motion_dir)
    print(f"      目录内动作数 = {len(keys)}, 统计数组长度 = {len(evals)}")
    if len(keys) != len(evals):
        raise SystemExit(
            "动作数量与统计数组长度不一致，key 映射不可信；"
            "请确认 motion_dir 与训练时使用的完全一致"
        )

    print("[3/4] 计算失败率分布")
    total_evals = evals * args.num_gpus
    total_fails = fails * args.num_gpus
    rate = np.where(evals > 0, fails / np.maximum(evals, 1e-9), np.nan)
    seen = evals > 0

    def pct(mask):
        return f"{mask.sum():>7d} ({100.0 * mask.sum() / len(keys):5.2f}%)"

    print(f"      动作总数                  : {len(keys)}")
    print(f"      被评估过至少一次          : {pct(seen)}")
    print(f"      从未被评估                : {pct(~seen)}")
    print(f"      dynamics_gate 判定不可行  : {pct(gate_failed)}")
    print(f"      被 quarantine 隔离        : {pct(quarantined)}")
    print(f"      全局 episode 总数(估)     : {total_evals.sum():,.0f}")
    print(f"      全局失败 episode 总数(估) : {total_fails.sum():,.0f}")
    if total_evals.sum() > 0:
        print(f"      全局失败率(按 episode 加权): {total_fails.sum() / total_evals.sum():.4f}")

    print("\n      每条动作被评估次数(跨卡平均)分位:")
    if seen.any():
        qs = [0, 1, 5, 25, 50, 75, 95, 99, 100]
        vals = np.percentile(evals[seen], qs)
        for q, v in zip(qs, vals):
            print(f"        p{q:<3d} = {v:10.2f}  (全局约 {v * args.num_gpus:10.0f})")

    print("\n      失败率分档（仅统计被评估过的动作）:")
    bands = [
        ("完全成功  rate == 0.00", lambda r: r == 0.0),
        ("0.00 < rate <= 0.10", lambda r: (r > 0.0) & (r <= 0.10)),
        ("0.10 < rate <= 0.30", lambda r: (r > 0.10) & (r <= 0.30)),
        ("0.30 < rate <= 0.50", lambda r: (r > 0.30) & (r <= 0.50)),
        ("0.50 < rate <= 0.70", lambda r: (r > 0.50) & (r <= 0.70)),
        ("0.70 < rate <= 0.90", lambda r: (r > 0.70) & (r <= 0.90)),
        ("0.90 < rate <  1.00", lambda r: (r > 0.90) & (r < 1.0)),
        ("完全失败  rate == 1.00", lambda r: r == 1.0),
    ]
    r_seen = rate[seen]
    for label, fn in bands:
        m = fn(r_seen)
        print(f"        {label:<24s}: {m.sum():>7d} ({100.0 * m.sum() / len(r_seen):5.2f}%)")

    print("\n      按『评估次数 >= 5(跨卡平均)』过滤后的高置信子集:")
    conf = evals >= 5
    if conf.any():
        r_conf = rate[conf]
        print(f"        高置信动作数: {conf.sum()} ({100.0 * conf.sum() / len(keys):.2f}%)")
        for label, fn in bands:
            m = fn(r_conf)
            print(f"        {label:<24s}: {m.sum():>7d} ({100.0 * m.sum() / len(r_conf):5.2f}%)")

    print("\n      失败率最高的 30 条动作（评估次数 >= 5）:")
    if conf.any():
        idx = np.where(conf)[0]
        order = idx[np.argsort(-rate[idx])][:30]
        for i in order:
            print(f"        {rate[i]:.3f}  evals={evals[i]:8.2f}  {keys[i]}")

    print("\n      kneeling 相关动作的统计:")
    kn = [i for i, k in enumerate(keys) if "kneel" in k.lower()]
    print(f"        kneeling 动作总数: {len(kn)}")
    if kn:
        kn_arr = np.array(kn)
        kn_seen = kn_arr[evals[kn_arr] > 0]
        if len(kn_seen):
            print(f"        被评估过: {len(kn_seen)}")
            print(f"        平均失败率: {np.nanmean(rate[kn_seen]):.4f}")
            print(f"        全体动作平均失败率: {np.nanmean(rate[seen]):.4f}")
            print("        失败率最高的 15 条 kneeling:")
            order = kn_seen[np.argsort(-rate[kn_seen])][:15]
            for i in order:
                print(f"          {rate[i]:.3f}  evals={evals[i]:8.2f}  {keys[i]}")

    print(f"\n[4/4] 写出逐动作明细: {args.out}")
    os.makedirs(osp.dirname(args.out), exist_ok=True)
    payload = {
        "checkpoint": args.checkpoint,
        "motion_dir": args.motion_dir,
        "num_gpus": args.num_gpus,
        "note": "evaluations/failures 为跨卡平均值；全局总量需乘以 num_gpus",
        "motion_keys": keys,
        "evaluations": evals.tolist(),
        "failures": fails.tolist(),
        "failure_rate": np.where(seen, rate, -1.0).tolist(),
        "dynamics_gate_failed": gate_failed.tolist(),
        "quarantined": quarantined.tolist(),
    }
    with open(args.out, "w") as f:
        json.dump(payload, f)
    print("      完成")


if __name__ == "__main__":
    main()
