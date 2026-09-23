# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""扫描全量 BUMI3 训练参考动作，找出依赖仿真中不存在地形的动作。

SONIC 的 MuJoCo/Isaac 训练场景只有一块 z=0 的无限平地。若某条参考动作的根高度
在动作结束时比开始时高出几十厘米（爬梯子、跳上台阶），或者第一帧就悬在半空
（站在台子上往下跳），那么在平地上永远不可能复现——策略再怎么练也只能是摔倒。
这类动作会被自适应采样持续判定为「困难」，从而无限吸走采样预算。

判据只使用 ``root_trans_offset`` 的 z 分量，不做 FK、不加载 MJCF，因此可以在无
GPU、无图形环境的数据服务器上对十万级动作批量运行。首尾高度各取 10% 帧的中位数，
避免单帧抖动主导结论。

输出 JSON 含逐条动作的高度统计与判定，可直接与
``extract_motion_sampling_stats.py`` 的采样统计按 motion key 合并，得出「剔除这批
动作能释放多少采样预算」。
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import os
import os.path as osp
from pathlib import Path

import joblib
import numpy as np

# BUMI3 直立时 base_link 根高约 0.46 m；判据全部相对首帧自身高度，不依赖该常数，
# 这里仅用于把结果打印成人类可读的「相当于几级台阶」。
NOMINAL_ROOT_HEIGHT = 0.46


def _extract_root_height(path: str) -> np.ndarray | None:
    """从 SONIC Robot PKL 中取出逐帧根高度；结构不符时返回 None。"""

    data = joblib.load(path)
    if not isinstance(data, dict):
        return None
    # 训练 PKL 为 {motion_key: {root_trans_offset, dof, root_rot, fps}} 的单动作容器。
    if "root_trans_offset" in data:
        mapping = data
    else:
        nested = [value for value in data.values() if isinstance(value, dict)]
        if len(nested) != 1:
            return None
        mapping = nested[0]
    root = mapping.get("root_trans_offset")
    if root is None:
        return None
    root = np.asarray(root, dtype=np.float64)
    if root.ndim != 2 or root.shape[1] < 3 or root.shape[0] < 2:
        return None
    return root[:, 2]


def _scan_one(path: str) -> dict | None:
    try:
        height = _extract_root_height(path)
    except Exception as error:  # noqa: BLE001
        return {"key": osp.splitext(osp.basename(path))[0], "error": repr(error)}
    if height is None:
        return {"key": osp.splitext(osp.basename(path))[0], "error": "no root_trans_offset"}

    span = max(1, len(height) // 10)
    start = float(np.median(height[:span]))
    end = float(np.median(height[-span:]))
    return {
        "key": osp.splitext(osp.basename(path))[0],
        "frames": int(len(height)),
        "start": start,
        "end": end,
        "net": end - start,
        "min": float(height.min()),
        "max": float(height.max()),
    }


def classify(row: dict, platform_threshold: float) -> str:
    """按首尾两端的**绝对**根高度判断动作是否踩在仿真中不存在的台面上。

    判据只看绝对高度，不看首尾净变化。这一点是本工具最容易踩错的地方：平地上根
    高度可以任意**降低**（跪、盘腿坐、趴），但不可能在动作起止这种静止状态下持续
    **高于**站立高度，除非脚下有台阶/梯子/墙。若改用「净变化超过阈值」判定，会把
    kneeling_stop、sit_on_heels、stand_up_lying、idle_crawl 这些正当低姿态动作全部
    误杀——实测该误判会删掉全部 8 条 kneeling_stop，正好是地面接触专项要修的目标。

    只看首尾中位高度还有一个好处：跳跃、后空翻的腾空瞬间不会被误判。实测
    flip_360/flip_180 峰值根高达 1.02 m，但首尾都在 0.46 m，正确保留为平地可行。
    """

    if "error" in row:
        return "读取失败"
    if row["start"] > platform_threshold or row["end"] > platform_threshold:
        return "台面依赖"
    return "平地可行"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--motion-dir", required=True, help="训练 Robot PKL 根目录，递归扫描")
    parser.add_argument("--out", required=True, help="输出 JSON 路径")
    parser.add_argument("--workers", type=int, default=max(os.cpu_count() // 2, 1))
    parser.add_argument(
        "--platform-threshold",
        type=float,
        default=0.62,
        help=(
            "首帧或末帧根高超过该值（米）即判为台面依赖；默认 0.62 = BUMI3 直立根高 "
            "0.46 加 0.16 余量"
        ),
    )
    args = parser.parse_args()

    motion_dir = Path(args.motion_dir).expanduser().resolve()
    paths = sorted(
        str(item)
        for item in motion_dir.rglob("*.pkl")
        if item.name != "metadata.pkl"
    )
    print(f"待扫描动作数: {len(paths)}，并行进程: {args.workers}")

    rows: list[dict] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for index, row in enumerate(pool.map(_scan_one, paths, chunksize=64), start=1):
            if row is not None:
                rows.append(row)
            if index % 5000 == 0:
                print(f"  已完成 {index}/{len(paths)}")

    for row in rows:
        row["verdict"] = classify(row, args.platform_threshold)

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    print("\n判定汇总:")
    for verdict, count in sorted(counts.items(), key=lambda item: -item[1]):
        print(f"  {verdict:<20s}: {count:>7d} ({100.0 * count / len(rows):5.2f}%)")

    terrain = [row for row in rows if row["verdict"] == "台面依赖"]
    terrain.sort(key=lambda row: -max(row["start"], row["end"]))
    print(f"\n台面高度最高的 30 条（共 {len(terrain)} 条台面依赖）:")
    for row in terrain[:30]:
        steps = (max(row["start"], row["end"]) - NOMINAL_ROOT_HEIGHT) / NOMINAL_ROOT_HEIGHT
        print(
            f"  start={row['start']:.3f} end={row['end']:.3f} max={row['max']:.3f} "
            f"(高出站立 {steps:4.2f}×)  {row['key']}"
        )

    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as stream:
        json.dump(
            {
                "motion_dir": str(motion_dir),
                "platform_threshold": args.platform_threshold,
                "rows": rows,
            },
            stream,
        )
    print(f"\n已写出 {len(rows)} 条明细: {out_path}")


if __name__ == "__main__":
    main()
