# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""纯运动学回放 BUMI3 训练参考动作，用于肉眼判断参考本身是否物理可行。

与 ``run_bumi3_sim2sim.py`` 的区别：这里**不加载任何 ONNX 策略、不做物理步进**，
只把训练用 Robot PKL 的 ``root_trans_offset + root_rot + dof`` 逐帧写进 MuJoCo
qpos 并调用 ``mj_forward`` 做 FK 显示。因此画面里看到的完全是数据集本身，不掺
任何策略行为。MJCF 自带棋盘地面（z=0），参考若整段悬在地面之上、或根高度在动作
中途抬升几十厘米，就说明该动作依赖仿真中不存在的地形/道具，平地训练永远学不会。

同时对每条动作打印根高度诊断：首帧/末帧/最低/最高根高，以及根高度净变化。净变化
显著为正说明动作结束时人站在比出发点更高的地方（台阶、梯子），净变化显著为负则
相反。这一判据与画面互为印证，``--headless`` 下可在无显示环境单独使用。

示例::

    # 交互回放整个目录，空格暂停，N 下一条，R 重播当前条
    python gear_sonic/scripts/replay_bumi3_reference.py --motion-dir data/bumi3_terrain_check/robot

    # 无显示环境只出诊断表
    python gear_sonic/scripts/replay_bumi3_reference.py --motion-dir ... --headless
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
import time

import numpy as np
import tyro

from gear_sonic.utils.mujoco_sim.bumi3_sim2sim import (
    DEFAULT_BUMI3_SIM2SIM_CONFIG,
    Bumi3Contract,
    load_reference_motion,
)


@dataclass
class Args:
    """回放参数。``motion`` 与 ``motion_dir`` 至少提供一个。"""

    motion: tuple[Path, ...] = ()
    """单条或多条 PKL/NPZ 动作路径，按给定顺序回放。"""
    motion_dir: Path | None = None
    """动作目录，递归收集其中所有 ``*.pkl``（跳过 ``metadata.pkl``）后按名称排序。"""
    config: Path = DEFAULT_BUMI3_SIM2SIM_CONFIG
    """BUMI3 sim2sim 契约 YAML，提供 MJCF 路径与策略/MuJoCo 关节顺序映射。"""
    speed: float = 1.0
    """回放倍速，1.0 为动作原始 FPS。"""
    loop: bool = True
    """单条动作播完是否循环，便于反复观察；关闭则自动切下一条。"""
    headless: bool = False
    """不开窗口，只打印根高度诊断表。"""
    rising_threshold: float = 0.15
    """根高度净变化超过该值（米）即在诊断表中标记为疑似地形依赖。"""


# viewer 的 key_callback 只能拿到 GLFW 键码，这里只用到三个可打印键。
_KEY_SPACE = 32
_KEY_N = ord("N")
_KEY_R = ord("R")


def _collect_motions(args: Args) -> list[Path]:
    paths: list[Path] = [Path(item).expanduser().resolve() for item in args.motion]
    if args.motion_dir is not None:
        root = Path(args.motion_dir).expanduser().resolve()
        if not root.is_dir():
            raise SystemExit(f"motion_dir 不是目录: {root}")
        paths.extend(
            sorted(
                item
                for item in root.rglob("*.pkl")
                if item.name != "metadata.pkl"
            )
        )
    if not paths:
        raise SystemExit("必须通过 --motion 或 --motion-dir 指定至少一条动作")
    missing = [item for item in paths if not item.exists()]
    if missing:
        raise SystemExit(f"以下动作文件不存在: {missing}")
    return paths


def _build_qpos_series(model, contract: Bumi3Contract, motion) -> np.ndarray:
    """把参考动作整段转成 MuJoCo qpos 序列。

    这里刻意不做任何 heading 对齐或高度修正：参考是什么样就显示成什么样，
    否则「悬空」「中途升高」这些正是我们要看的特征会被渲染层悄悄抹掉。
    """
    import mujoco

    root_joint_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, "root")
    if root_joint_id < 0:
        raise SystemExit("MJCF 中找不到名为 root 的 freejoint")
    root_address = int(model.jnt_qposadr[root_joint_id])

    joint_ids = np.asarray(
        [
            mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
            for name in contract.mujoco_joint_names
        ],
        dtype=np.int64,
    )
    if np.any(joint_ids < 0):
        raise SystemExit("MJCF 缺少契约要求的 21 个关节之一")
    joint_addresses = model.jnt_qposadr[joint_ids].copy()

    frames = motion.num_frames
    series = np.zeros((frames, model.nq), dtype=np.float64)
    if motion.root_position_world is None:
        root_position = np.tile(contract.initial_root_position, (frames, 1))
    else:
        root_position = np.asarray(motion.root_position_world, dtype=np.float64)
    series[:, root_address : root_address + 3] = root_position
    series[:, root_address + 3 : root_address + 7] = motion.root_quat_wxyz
    series[:, joint_addresses] = motion.joint_pos_policy[:, contract.policy_to_mujoco]
    return series


def _diagnose(name: str, qpos_series: np.ndarray, root_address: int, threshold: float) -> dict:
    """根据根高度轨迹给出「是否疑似依赖仿真中不存在的地形」的判断。"""

    height = qpos_series[:, root_address + 2]
    # 用首尾各 10% 帧的中位数代表起止高度，避免单帧抖动主导结论。
    span = max(1, len(height) // 10)
    start = float(np.median(height[:span]))
    end = float(np.median(height[-span:]))
    net = end - start
    verdict = "平地可行"
    if abs(net) >= threshold:
        verdict = "疑似地形依赖(净升降)"
    elif float(height.max()) - start >= threshold * 2:
        verdict = "疑似地形依赖(中途腾空)"
    return {
        "name": name,
        "frames": int(len(height)),
        "start": start,
        "end": end,
        "net": net,
        "min": float(height.min()),
        "max": float(height.max()),
        "verdict": verdict,
    }


def _print_diagnostics(rows: list[dict]) -> None:
    header = (
        f"{'动作':<58s} {'帧数':>5s} {'首':>6s} {'末':>6s} "
        f"{'净变化':>7s} {'最低':>6s} {'最高':>6s}  判定"
    )
    print("=" * len(header))
    print("根高度诊断（单位：米，地面 z=0）")
    print("=" * len(header))
    print(header)
    for row in rows:
        print(
            f"{row['name']:<58s} {row['frames']:>5d} {row['start']:>6.3f} {row['end']:>6.3f} "
            f"{row['net']:>+7.3f} {row['min']:>6.3f} {row['max']:>6.3f}  {row['verdict']}"
        )


def main(args: Args) -> None:
    import mujoco

    contract = Bumi3Contract.from_yaml(args.config)
    model = mujoco.MjModel.from_xml_path(str(contract.model_path))
    root_joint_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, "root")
    root_address = int(model.jnt_qposadr[root_joint_id])

    paths = _collect_motions(args)
    print(f"共 {len(paths)} 条动作，MJCF: {contract.model_path}")

    prepared: list[tuple[str, np.ndarray, float]] = []
    rows: list[dict] = []
    for path in paths:
        motion = load_reference_motion(path, contract)
        series = _build_qpos_series(model, contract, motion)
        prepared.append((path.stem, series, motion.fps))
        rows.append(_diagnose(path.stem, series, root_address, args.rising_threshold))

    _print_diagnostics(rows)

    if args.headless:
        return

    import mujoco.viewer

    data = mujoco.MjData(model)
    state = {"index": 0, "frame": 0, "paused": False, "next": False, "restart": False}

    def key_callback(keycode: int) -> None:
        if keycode == _KEY_SPACE:
            state["paused"] = not state["paused"]
        elif keycode == _KEY_N:
            state["next"] = True
        elif keycode == _KEY_R:
            state["restart"] = True

    print()
    print("窗口操作：空格=暂停/继续，N=下一条，R=重播当前条，关闭窗口=退出")
    print()

    with mujoco.viewer.launch_passive(
        model, data, key_callback=key_callback, show_left_ui=False, show_right_ui=False
    ) as viewer:
        current = -1
        while viewer.is_running():
            index = state["index"]
            if index >= len(prepared):
                break
            name, series, fps = prepared[index]
            if index != current:
                current = index
                state["frame"] = 0
                verdict = rows[index]["verdict"]
                print(f"[{index + 1}/{len(prepared)}] {name}  ({len(series)} 帧, {fps:.0f} fps)  {verdict}")

            step_dt = 1.0 / (fps * max(args.speed, 1e-3))
            started = time.perf_counter()

            data.qpos[:] = series[state["frame"]]
            data.qvel[:] = 0.0
            mujoco.mj_forward(model, data)
            viewer.sync()

            if state["restart"]:
                state["restart"] = False
                state["frame"] = 0
            elif state["next"]:
                state["next"] = False
                state["index"] += 1
            elif not state["paused"]:
                state["frame"] += 1
                if state["frame"] >= len(series):
                    if args.loop:
                        state["frame"] = 0
                    else:
                        state["frame"] = len(series) - 1
                        state["index"] += 1

            remaining = step_dt - (time.perf_counter() - started)
            if remaining > 0:
                time.sleep(remaining)


if __name__ == "__main__":
    try:
        main(tyro.cli(Args))
    except KeyboardInterrupt:
        sys.exit(130)
