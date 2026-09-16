#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""验证 BUMI3 原生 SONIC 的资产、顺序、执行器和双编码器训练契约。

脚本默认完成不依赖训练数据的全部检查：锁定 SONIC 仓库内 URDF/MJCF/mesh 指纹与
BUMI3 爬行/跪地碰撞契约，验证 MJCF 的 22 个可视网格、14 个独立碰撞体和地面
高度，解析两种机器人描述并检查 mesh、验证 21 DoF/22
body、双向顺序与 round trip、执行器动作缩放/无延迟，以及 Hydra 组合后的时间
参数、网络输入维度和 Teleop 清除结果。动态机器人配置检查会启动 headless
Isaac Sim，以保证导入的是实际 Isaac Lab 配置而非重复维护的常量。提供兼容的
BUMI3 robot/SMPL motion 路径并加
``--smoke`` 后，还会创建环境并执行 reset/step，递归检查 observation、action、
reward 是否包含 NaN/Inf；``--num-envs 16 --iterations 100`` 可用于扩大冒烟训练前
的 replay 压力检查。脚本绝不生成、转换或筛选训练数据。
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import hashlib
import math
import os
from pathlib import Path
import sys
import traceback
import xml.etree.ElementTree as ET

from hydra import compose, initialize_config_dir
from hydra.core.hydra_config import HydraConfig
from omegaconf import OmegaConf


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "gear_sonic/config"
ASSET_ROOT = REPO_ROOT / "gear_sonic/data/assets/robot_description"
URDF_PATH = ASSET_ROOT / "urdf/bumi3/bumi.urdf"
MJCF_PATH = ASSET_ROOT / "mjcf/bumi3.xml"
MESH_DIR = ASSET_ROOT / "meshes/bumi3"
EXP_NAME = "manager/universal_token/all_modes/sonic_bumi3"
GROUND_FINETUNE_EXP_NAME = (
    "manager/universal_token/all_modes/sonic_bumi3_ground_finetune"
)
EXPECTED_BUMI3_MUJOCO_DOF_NAMES = [
    "waist_yaw_joint",
    "l_arm_pitch_joint",
    "l_arm_roll_joint",
    "l_arm_yaw_joint",
    "l_elbow_pitch_joint",
    "r_arm_pitch_joint",
    "r_arm_roll_joint",
    "r_arm_yaw_joint",
    "r_elbow_pitch_joint",
    "l_leg_pitch_joint",
    "l_leg_roll_joint",
    "l_leg_yaw_joint",
    "l_knee_pitch_joint",
    "l_ankle_pitch_joint",
    "l_ankle_roll_joint",
    "r_leg_pitch_joint",
    "r_leg_roll_joint",
    "r_leg_yaw_joint",
    "r_knee_pitch_joint",
    "r_ankle_pitch_joint",
    "r_ankle_roll_joint",
]
EXPECTED_LOCAL_URDF_SHA256 = (
    "0e08c15fe2226fedeac967c06a7910701935fc6de8fca2d4664a76c9ac41e955"
)
EXPECTED_LOCAL_MJCF_SHA256 = (
    "1ef8da2e76be03430ba7f022e49309f194a289174db0275d7d3a123197cac3e3"
)
EXPECTED_LOCAL_MESH_BUNDLE_SHA256 = (
    "5d84767fbd21ec22434c1cba8145e4887d4f5910512d5a8efeac50781f3afa26"
)

# 圆柱轴使用 URDF 的局部 Z 轴。以下数值是用户在 BUMI3 STL 初始包围盒方案上
# 明确指定的训练碰撞参数；验证脚本锁定这些值，防止后续静默回退或漂移。
EXPECTED_CYLINDER_COLLISIONS = {
    "base_link": {
        "xyz": (-0.0013853, 0.0, 0.065525),
        "rpy": (0.0, 0.0, 0.0),
        "radius": 0.052,
        "length": 0.12,
    },
    "l_leg_roll_link": {
        "xyz": (0.0, 0.0, -0.02),
        "rpy": (0.0, 0.0, 0.0),
        "radius": 0.03,
        "length": 0.08,
    },
    "r_leg_roll_link": {
        "xyz": (0.0, 0.0, -0.02),
        "rpy": (0.0, 0.0, 0.0),
        "radius": 0.03,
        "length": 0.08,
    },
    "l_knee_pitch_link": {
        "xyz": (0.008475, 0.0, -0.0894694),
        "rpy": (0.0, 0.0, 0.0),
        "radius": 0.025,
        "length": 0.13,
    },
    "r_knee_pitch_link": {
        "xyz": (0.008475, 0.0, -0.0894694),
        "rpy": (0.0, 0.0, 0.0),
        "radius": 0.025,
        "length": 0.13,
    },
}
EXPECTED_MJCF_MESH_COLLISIONS = {
    "waist_yaw_link",
    "l_arm_roll_link",
    "l_elbow_pitch_link",
    "r_arm_roll_link",
    "r_elbow_pitch_link",
    "l_ankle_pitch_link",
    "l_ankle_roll_link",
    "r_ankle_pitch_link",
    "r_ankle_roll_link",
}


def _assert_unique(names: Sequence[str], label: str) -> None:
    """验证名称列表没有重复项。"""

    duplicates = sorted({name for name in names if names.count(name) > 1})
    assert not duplicates, f"{label} 存在重复名称: {duplicates}"


def _sha256(path: Path) -> str:
    """返回文件 SHA256，用于确认复制 mesh 未被修改。"""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mesh_bundle_sha256(root: Path) -> str:
    """按文件名和内容生成仓库内 BUMI3 mesh 集合的稳定指纹。"""

    digest = hashlib.sha256()
    for path in sorted(candidate for candidate in root.iterdir() if candidate.is_file()):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _parse_vector(value: str) -> tuple[float, ...]:
    """解析 URDF 空格分隔向量，供碰撞 origin 数值比较。"""

    return tuple(float(item) for item in value.split())


def _validate_urdf_collision_policy(
    urdf_root: ET.Element,
) -> None:
    """只根据 SONIC 仓库契约核对五个圆柱、九个 mesh 和无碰撞 link。"""

    local_links = {node.attrib["name"]: node for node in urdf_root.findall("link")}

    for link_name, local_link in local_links.items():
        collisions = local_link.findall("collision")
        if link_name in EXPECTED_CYLINDER_COLLISIONS:
            assert len(collisions) == 1, f"{link_name} 必须恰好有一个圆柱 collision"
            collision = collisions[0]
            origin = collision.find("origin")
            geometry = collision.find("geometry")
            assert origin is not None and geometry is not None
            cylinder = geometry.find("cylinder")
            assert cylinder is not None, f"{link_name} collision 必须使用 cylinder"
            assert len(geometry) == 1, f"{link_name} collision 不得混入 mesh 等其他几何"

            expected = EXPECTED_CYLINDER_COLLISIONS[link_name]
            assert _parse_vector(origin.attrib["xyz"]) == expected["xyz"]
            assert _parse_vector(origin.attrib["rpy"]) == expected["rpy"]
            assert math.isclose(float(cylinder.attrib["radius"]), expected["radius"])
            assert math.isclose(float(cylinder.attrib["length"]), expected["length"])
        elif link_name in EXPECTED_MJCF_MESH_COLLISIONS:
            assert len(collisions) == 1, f"{link_name} 必须恰好有一个 mesh collision"
            collision = collisions[0]
            origin = collision.find("origin")
            geometry = collision.find("geometry")
            assert origin is not None and geometry is not None
            mesh = geometry.find("mesh")
            assert mesh is not None and len(geometry) == 1
            assert _parse_vector(origin.attrib["xyz"]) == (0.0, 0.0, 0.0)
            assert _parse_vector(origin.attrib["rpy"]) == (0.0, 0.0, 0.0)
            assert mesh.attrib["filename"] == (
                f"../../meshes/bumi3/{link_name}.STL"
            )
        else:
            assert not collisions, f"{link_name} 按 SONIC BUMI3 契约不得包含 collision"


def _validate_mjcf_collision_policy(mjcf_root: ET.Element) -> None:
    """逐 body 锁定 MJCF 的可视/碰撞分离、简化 capsule 和地面基准。"""

    visual_default = mjcf_root.find("./default/default[@class='visual']/geom")
    collision_default = mjcf_root.find("./default/default[@class='collision']/geom")
    assert visual_default is not None and collision_default is not None
    assert visual_default.attrib == {
        "type": "mesh",
        "contype": "0",
        "conaffinity": "0",
        "group": "1",
        "density": "0",
    }
    assert collision_default.attrib == {
        "contype": "1",
        "conaffinity": "0",
        "condim": "3",
        "group": "3",
        "density": "0",
        "friction": "1 0.005 0.0001",
        "rgba": "0 0 0 0",
    }

    ground = mjcf_root.find("./worldbody/geom[@name='ground']")
    assert ground is not None
    assert _parse_vector(ground.attrib["pos"]) == (0.001, 0.0, 0.0)
    assert ground.attrib["contype"] == "0"
    assert ground.attrib["conaffinity"] == "1"
    assert ground.attrib["condim"] == "3"
    assert ground.attrib["friction"] == "1 0.005 0.0001"

    body_nodes = {
        node.attrib["name"]: node for node in mjcf_root.findall(".//body")
    }
    expected_collision_bodies = (
        set(EXPECTED_CYLINDER_COLLISIONS) | EXPECTED_MJCF_MESH_COLLISIONS
    )
    assert len(expected_collision_bodies) == 14
    for body_name, body_node in body_nodes.items():
        direct_geoms = body_node.findall("geom")
        visual_geoms = [node for node in direct_geoms if node.attrib.get("class") == "visual"]
        collision_geoms = [
            node for node in direct_geoms if node.attrib.get("class") == "collision"
        ]
        assert len(visual_geoms) == 1, f"{body_name} 必须恰好有一个 MJCF visual geom"
        visual = visual_geoms[0]
        assert visual.attrib["name"] == f"{body_name}_visual"
        assert visual.attrib["mesh"] == body_name

        expected_collision_count = int(body_name in expected_collision_bodies)
        assert len(collision_geoms) == expected_collision_count, (
            f"{body_name} MJCF collision 数量错误"
        )
        assert len(direct_geoms) == 1 + expected_collision_count, (
            f"{body_name} 存在未归类的 MJCF geom"
        )
        if not collision_geoms:
            continue

        collision = collision_geoms[0]
        assert collision.attrib["name"] == f"{body_name}_collision"
        if body_name in EXPECTED_CYLINDER_COLLISIONS:
            expected = EXPECTED_CYLINDER_COLLISIONS[body_name]
            assert collision.attrib["type"] == "capsule"
            assert _parse_vector(collision.attrib["pos"]) == expected["xyz"]
            expected_size = (expected["radius"], expected["length"] / 2.0)
            assert _parse_vector(collision.attrib["size"]) == expected_size
            assert "mesh" not in collision.attrib
        else:
            assert body_name in EXPECTED_MJCF_MESH_COLLISIONS
            assert collision.attrib["type"] == "mesh"
            assert collision.attrib["mesh"] == body_name


def _validate_repository_assets() -> None:
    """只锁定 SONIC 仓库内 BUMI3 资产，不读取任何外部参考仓库。"""

    assert _sha256(URDF_PATH) == EXPECTED_LOCAL_URDF_SHA256, (
        "SONIC 仓库内 BUMI3 URDF 指纹变化，必须同步审计并更新契约"
    )
    assert _sha256(MJCF_PATH) == EXPECTED_LOCAL_MJCF_SHA256, (
        "SONIC 仓库内 BUMI3 MJCF 指纹变化，必须同步审计并更新契约"
    )
    assert _mesh_bundle_sha256(MESH_DIR) == EXPECTED_LOCAL_MESH_BUNDLE_SHA256, (
        "SONIC 仓库内 BUMI3 mesh 集合变化，必须同步审计并更新契约"
    )

    local_urdf_root = ET.parse(URDF_PATH).getroot()
    _validate_urdf_collision_policy(local_urdf_root)

    local_mjcf_root = ET.parse(MJCF_PATH).getroot()
    _validate_mjcf_collision_policy(local_mjcf_root)


def _validate_xml_and_meshes() -> dict[str, list[str]]:
    """解析 URDF/MJCF，并验证拓扑名称、数量和全部 mesh 引用。"""

    urdf_root = ET.parse(URDF_PATH).getroot()
    mjcf_root = ET.parse(MJCF_PATH).getroot()

    urdf_bodies = [node.attrib["name"] for node in urdf_root.findall("link")]
    urdf_joints = [node.attrib["name"] for node in urdf_root.findall("joint")]
    mjcf_bodies = [node.attrib["name"] for node in mjcf_root.findall(".//body")]
    worldbody = mjcf_root.find("worldbody")
    assert worldbody is not None, "MJCF 缺少 worldbody"
    mjcf_joints = [node.attrib["name"] for node in worldbody.findall(".//joint")]

    assert len(urdf_joints) == len(mjcf_joints) == 21, (
        f"DoF 数量错误: URDF={len(urdf_joints)}, MJCF={len(mjcf_joints)}"
    )
    assert len(urdf_bodies) == len(mjcf_bodies) == 22, (
        f"body 数量错误: URDF={len(urdf_bodies)}, MJCF={len(mjcf_bodies)}"
    )
    for label, names in (
        ("URDF joint", urdf_joints),
        ("MJCF joint", mjcf_joints),
        ("URDF body", urdf_bodies),
        ("MJCF body", mjcf_bodies),
    ):
        _assert_unique(names, label)
    assert set(urdf_joints) == set(mjcf_joints), "URDF/MJCF joint 名称集合不一致"
    assert set(urdf_bodies) == set(mjcf_bodies), "URDF/MJCF body 名称集合不一致"
    assert urdf_root.attrib["name"] == "BUMI_V3.0_260119"
    assert mjcf_root.attrib["model"] == "bumi3.0"

    # 当前 BUMI3 MJCF 含工作区修正后的 waist 轴和 arm-roll 限位；逐关节与
    # 权威 URDF 对比，避免命名相同但运动学方向或限位仍来自旧模型。
    urdf_joint_nodes = {node.attrib["name"]: node for node in urdf_root.findall("joint")}
    mjcf_joint_nodes = {node.attrib["name"]: node for node in worldbody.findall(".//joint")}
    for joint_name in urdf_joints:
        urdf_joint = urdf_joint_nodes[joint_name]
        mjcf_joint = mjcf_joint_nodes[joint_name]
        urdf_axis = [float(value) for value in urdf_joint.find("axis").attrib["xyz"].split()]
        mjcf_axis = [float(value) for value in mjcf_joint.attrib["axis"].split()]
        assert urdf_axis == mjcf_axis, f"URDF/MJCF joint axis 不一致: {joint_name}"
        urdf_limit = urdf_joint.find("limit")
        urdf_range = [float(urdf_limit.attrib[key]) for key in ("lower", "upper")]
        mjcf_range = [float(value) for value in mjcf_joint.attrib["range"].split()]
        assert urdf_range == mjcf_range, f"URDF/MJCF joint range 不一致: {joint_name}"

    for mesh in urdf_root.findall(".//mesh"):
        mesh_path = (URDF_PATH.parent / mesh.attrib["filename"]).resolve()
        assert mesh_path.is_file(), f"URDF mesh 不存在: {mesh_path}"

    compiler = mjcf_root.find("compiler")
    assert compiler is not None and compiler.attrib.get("meshdir") == "../meshes/bumi3/"
    mjcf_mesh_dir = (MJCF_PATH.parent / compiler.attrib["meshdir"]).resolve()
    for mesh in mjcf_root.findall("./asset/mesh"):
        mesh_path = mjcf_mesh_dir / mesh.attrib["file"]
        assert mesh_path.is_file(), f"MJCF mesh 不存在: {mesh_path}"

    return {
        "urdf_joints": urdf_joints,
        "urdf_bodies": urdf_bodies,
        "mjcf_joints": mjcf_joints,
        "mjcf_bodies": mjcf_bodies,
    }


def _compose_config(exp_name: str, overrides: Sequence[str] = ()):
    """组合一个实验配置，并注册 Hydra runtime 供局部 interpolation 解析。"""

    with initialize_config_dir(version_base="1.3", config_dir=str(CONFIG_DIR)):
        cfg = compose(
            config_name="base",
            overrides=[f"+exp={exp_name}", *overrides],
            return_hydra_config=True,
        )
    HydraConfig.instance().set_config(cfg)
    return cfg


def _resolved_section(cfg, key: str) -> dict:
    """解析单个配置区段，避开 Hydra 自身只读配置节点。"""

    return OmegaConf.to_container(cfg[key], resolve=True)


def _without_body_names(value):
    """递归移除允许按机器人覆盖的 body_names 字段，供数值契约对比。"""

    if isinstance(value, Mapping):
        return {
            key: _without_body_names(item)
            for key, item in value.items()
            if key != "body_names"
        }
    if isinstance(value, list):
        return [_without_body_names(item) for item in value]
    return value


def _validate_reward_compatibility(bumi_manager: dict, release_manager: dict) -> None:
    """确认 BUMI3 关闭获准的两项奖励，增加力矩约束，其余项保持发布版契约。"""

    bumi_rewards = bumi_manager["rewards"]
    release_rewards = release_manager["rewards"]
    disabled_rewards = {"tracking_vr_5point_local", "anti_shake_ang_vel"}
    assert disabled_rewards.isdisjoint(bumi_rewards), "已关闭的 BUMI3 奖励被重新装配"
    assert set(bumi_rewards) == (set(release_rewards) - disabled_rewards) | {"torque_limits"}, (
        "BUMI3 除关闭局部关键点、防抖及增加力矩限制外出现未授权的奖励项变化"
    )
    release_compatible_rewards = {
        key: value for key, value in bumi_rewards.items() if key != "torque_limits"
    }
    assert _without_body_names(release_compatible_rewards) == _without_body_names(
        {key: value for key, value in release_rewards.items() if key not in disabled_rewards}
    ), (
        "BUMI3 既有 reward 除 body_names 外的函数、weight、std 或参数与 "
        "sonic_release 不一致"
    )
    assert math.isclose(bumi_rewards["feet_acc"]["weight"], -2.5e-6)
    torque_limits = bumi_rewards["torque_limits"]
    assert torque_limits["_target_"] == "isaaclab.managers.RewardTermCfg"
    assert torque_limits["func"] == (
        "gear_sonic.envs.manager_env.mdp:applied_torque_limits_by_ratio"
    )
    assert math.isclose(torque_limits["weight"], -0.01)
    assert torque_limits["params"]["asset_cfg"]["name"] == "robot"
    assert torque_limits["params"]["asset_cfg"]["joint_names"] == [".*"]
    assert math.isclose(torque_limits["params"]["limit_ratio"], 0.85)


def _validate_event_compatibility(bumi_manager: dict, release_manager: dict) -> None:
    """确认 BUMI3 腰部质量/COM 扰动范围，并锁定其余随机化关闭状态。"""

    bumi_events = bumi_manager["events"]
    release_events = release_manager["events"]
    bumi_only_events = {
        "randomize_ankle_armature",
        "randomize_actuator_gains",
    }
    assert set(bumi_events) == set(release_events) | bumi_only_events, (
        "BUMI3 event 集合出现未授权变化"
    )

    for event_name, release_event in release_events.items():
        bumi_event = bumi_events[event_name]
        if event_name == "randomize_rigid_body_mass":
            assert bumi_event["_target_"] == release_event["_target_"]
            assert bumi_event["func"] == release_event["func"]
            assert bumi_event["mode"] == "startup"
            mass_params = bumi_event["params"]
            assert mass_params["asset_cfg"]["name"] == "robot"
            assert mass_params["asset_cfg"]["body_names"] == "waist_yaw_link"
            # 只允许用户确认的腰部质量倍数；精确 body 名同时排除了左右手腕。
            assert mass_params["mass_distribution_params"] == [0.8, 1.2]
            assert mass_params["operation"] == "scale"
            continue
        assert _without_body_names(bumi_event) == _without_body_names(release_event), (
            f"BUMI3 event {event_name} 出现未授权的函数、范围或执行时机变化"
        )

    assert bumi_events["base_com"]["params"]["asset_cfg"]["body_names"] == (
        "waist_yaw_link"
    )
    assert bumi_events["randomize_ankle_armature"] is None
    assert bumi_events["randomize_actuator_gains"] is None


def _validate_resolved_configs() -> dict[str, int | float]:
    """验证 BUMI3/G1/H2 的 Hydra 组合及 SONIC 网络维度契约。"""

    bumi_cfg = _compose_config(EXP_NAME)
    bumi_manager = _resolved_section(bumi_cfg, "manager_env")
    bumi_algo = _resolved_section(bumi_cfg, "algo")

    release_cfg = _compose_config("manager/universal_token/all_modes/sonic_release")
    release_manager = _resolved_section(release_cfg, "manager_env")
    release_algo = _resolved_section(release_cfg, "algo")
    _compose_config("manager/universal_token/all_modes/sonic_h2")

    sim_dt = bumi_manager["config"]["sim_dt"]
    decimation = bumi_manager["config"]["decimation"]
    control_frequency = 1.0 / (sim_dt * decimation)
    motion_cfg = bumi_manager["commands"]["motion"]
    motion_lib_cfg = motion_cfg["motion_lib_cfg"]

    assert sim_dt == 0.005
    assert decimation == 4
    assert control_frequency == 50.0
    assert motion_lib_cfg["target_fps"] == 50
    assert motion_cfg["num_future_frames"] == 10
    assert motion_cfg["dt_future_ref_frames"] == 0.1
    assert motion_cfg["smpl_num_future_frames"] == 10
    assert motion_cfg["smpl_dt_future_ref_frames"] == 0.02
    assert motion_cfg["motion_lib_num_dof"] == 21
    assert motion_cfg["cat_upper_body_poses"] is True
    assert motion_cfg["cat_upper_body_poses_prob"] == 0.5
    assert motion_cfg["freeze_frame_aug"] is True
    assert motion_cfg["teleop_sample_prob_when_smpl"] == 0.0
    assert motion_lib_cfg["robot_type"] == "bumi3"
    assert motion_lib_cfg["asset"]["assetFileName"] == "bumi3.xml"
    assert motion_lib_cfg["wrist_mujoco_dof_indices"] == []
    # 三源索引已经逐条审计并在清单层降级异常 SMPL，不得继续误删旧 hq_all_v2
    # 的 55 个 key；运行时只承担同为 50 Hz 的最多两帧尾差对齐。
    excluded_motion_keys = list(motion_lib_cfg["exclude_motion_keys"])
    assert excluded_motion_keys == []
    assert motion_lib_cfg["paired_frame_alignment"] == {
        "mode": "trim_trailing",
        "max_frame_delta": 2,
    }
    # SMPL pose_aa 保存源 Y-up 姿态，训练端只转换一次；smpl_joints 已离线为 Z-up。
    assert motion_lib_cfg["smpl_y_up"] is True
    assert motion_cfg["randomize_wrist_poses"] is False
    assert motion_lib_cfg["motion_file"] is None
    assert motion_lib_cfg["smpl_motion_file"] is None
    assert motion_cfg["anchor_body"] == "base_link"
    assert motion_cfg["body_names"] == [
        "base_link",
        "waist_yaw_link",
        "l_arm_roll_link",
        "l_elbow_pitch_link",
        "r_arm_roll_link",
        "r_elbow_pitch_link",
        "l_leg_roll_link",
        "l_knee_pitch_link",
        "l_ankle_roll_link",
        "r_leg_roll_link",
        "r_knee_pitch_link",
        "r_ankle_roll_link",
    ]
    assert motion_cfg["reward_point_body"] == [
        "waist_yaw_link",
        "l_elbow_pitch_link",
        "r_elbow_pitch_link",
    ]
    assert motion_cfg["reward_point_body_offset"] == [
        [0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0],
    ]
    assert motion_cfg["vr_3point_body"] == [
        "l_elbow_pitch_link",
        "r_elbow_pitch_link",
        "base_link",
    ]
    assert motion_cfg["vr_3point_body_offset"] == [
        [0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0],
    ]

    actor_backbone = bumi_algo["config"]["actor"]["backbone"]
    assert list(actor_backbone["encoders"]) == ["g1", "smpl"]
    assert actor_backbone["reencode_smpl_g1_recon"] is True
    assert actor_backbone["encoders"]["g1"]["inputs"] == [
        "command_multi_future_nonflat",
        "motion_anchor_ori_b_mf_nonflat",
    ]
    assert actor_backbone["encoders"]["smpl"]["inputs"] == [
        "smpl_joints_multi_future_local_nonflat",
        "smpl_root_ori_b_multi_future",
    ]

    tokenizer = bumi_manager["observations"]["tokenizer"]
    tokenizer_meta = {"_target_", "enable_corruption", "concatenate_terms"}
    tokenizer_terms = [key for key in tokenizer if key not in tokenizer_meta]
    assert tokenizer_terms == [
        "encoder_index",
        "command_multi_future_nonflat",
        "motion_anchor_ori_b_mf_nonflat",
        "smpl_joints_multi_future_local_nonflat",
        "smpl_root_ori_b_multi_future",
    ]
    forbidden_tokenizer_terms = {
        "command_multi_future_lower_body",
        "vr_3point_local_target",
        "vr_3point_local_orn_target",
        "joint_pos_multi_future_wrist_for_smpl",
    }
    assert forbidden_tokenizer_terms.isdisjoint(tokenizer_terms)

    aux_loss_coef = actor_backbone["aux_loss_coef"]
    assert aux_loss_coef == {
        "g1_recon": 0.01,
        "g1_smpl_latent": 1.0,
        "reencoded_smpl_g1_latent": 1.0,
    }
    assert set(actor_backbone["aux_loss_func"]) == set(aux_loss_coef)

    release_backbone = release_algo["config"]["actor"]["backbone"]
    for encoder_name in ("g1", "smpl"):
        assert actor_backbone["encoders"][encoder_name]["params"] == (
            release_backbone["encoders"][encoder_name]["params"]
        ), f"{encoder_name} encoder MLP 主体与 sonic_release 不一致"
    assert actor_backbone["decoders"] == release_backbone["decoders"], (
        "decoder MLP 主体与 sonic_release 不一致"
    )
    assert actor_backbone["quantizer"] == release_backbone["quantizer"]
    assert bumi_algo["config"]["critic"] == release_algo["config"]["critic"]

    token_total_dim = actor_backbone["num_fsq_levels"] * actor_backbone["max_num_tokens"]
    assert token_total_dim == 64
    action_dim = 21
    actor_proprioception_dim = (
        (3 + 3 + action_dim + action_dim) * bumi_cfg.actor_prop_history_length
        + action_dim * bumi_cfg.actor_actions_history_length
    )
    assert actor_proprioception_dim == 690
    tokenizer_flat_dim = (
        2  # encoder_index: g1 + smpl
        + 10 * (2 * action_dim)  # Robot joint position + velocity
        + 10 * 6  # Robot anchor 6D orientation
        + 10 * (24 * 3)  # 24 SMPL joints in local xyz
        + 10 * 6  # SMPL root 6D orientation
    )
    assert tokenizer_flat_dim == 1262
    num_tracking_bodies = len(motion_cfg["body_names"])
    critic_obs_dim = (
        10 * (2 * action_dim)
        + 3
        + 6
        + num_tracking_bodies * 3
        + num_tracking_bodies * 6
        + (3 + 3 + action_dim + action_dim) * bumi_cfg.critic_prop_history_length
        + action_dim * bumi_cfg.critic_actions_history_length
    )
    assert critic_obs_dim == 1227
    dynamic_decoder_input_dim = token_total_dim + actor_proprioception_dim
    assert dynamic_decoder_input_dim == 754
    dynamic_decoder_output_dim = action_dim
    assert dynamic_decoder_output_dim == 21

    _validate_reward_compatibility(bumi_manager, release_manager)
    _validate_event_compatibility(bumi_manager, release_manager)
    terminations = bumi_manager["terminations"]
    assert terminations["foot_pos_xyz"]["params"]["threshold"] == 0.20
    assert terminations["foot_pos_xyz"]["params"]["body_names"] == [
        "l_ankle_roll_link",
        "r_ankle_roll_link",
    ]
    assert terminations["anchor_pos"]["params"]["threshold"] == 0.12
    assert terminations["anchor_pos"]["params"]["threshold_adaptive"] is True
    assert terminations["anchor_pos"]["params"]["down_threshold"] == 0.25
    assert terminations["anchor_pos"]["params"]["root_height_threshold"] == 0.4
    assert terminations["ee_body_pos"]["params"]["threshold"] == 0.20
    assert terminations["ee_body_pos"]["params"]["body_names"] == [
        "l_elbow_pitch_link",
        "r_elbow_pitch_link",
    ]
    assert terminations["ee_body_pos"]["params"]["threshold_adaptive"] is True
    assert terminations["ee_body_pos"]["params"]["down_threshold"] == 0.40
    assert terminations["ee_body_pos"]["params"]["root_height_threshold"] == 0.4
    assert terminations["anchor_ori_full"]["params"]["threshold"] == 0.20

    assert bumi_algo["config"]["actor_learning_rate"] == 2e-5
    assert bumi_algo["config"]["critic_learning_rate"] == 1e-3
    adaptive_sampling = motion_lib_cfg["adaptive_sampling"]
    assert adaptive_sampling["enable"] is True
    assert adaptive_sampling["uniform_sampling_rate"] == 0.9
    assert adaptive_sampling["dynamics_gate"]["enable"] is True
    assert adaptive_sampling["dynamics_gate"]["dof_names"] == (
        EXPECTED_BUMI3_MUJOCO_DOF_NAMES
    )
    assert list(adaptive_sampling["dynamics_gate"]["dof_velocity_limits"]) == (
        EXPECTED_BUMI3_MUJOCO_DOF_NAMES
    )
    assert adaptive_sampling["dynamics_gate"]["max_velocity_exceedance_fraction"] == 0.005
    assert adaptive_sampling["dynamics_gate"]["max_velocity_ratio"] == 2.0
    assert adaptive_sampling["dynamics_gate"]["max_acceleration_ratio"] == 1.0
    assert adaptive_sampling["quarantine"] == {
        "enable": True,
        "min_global_success_rate": 0.2,
        "high_failure_rate": 0.9,
        "min_motion_episodes": 5.0,
        "min_new_motion_episodes": 3.0,
        "consecutive_evaluations": 3,
    }

    ground_cfg = _compose_config(GROUND_FINETUNE_EXP_NAME)
    ground_manager = _resolved_section(ground_cfg, "manager_env")
    ground_algo = _resolved_section(ground_cfg, "algo")
    ground_rewards = ground_manager["rewards"]
    ground_terminations = ground_manager["terminations"]
    ground_sampling = ground_manager["commands"]["motion"]["motion_lib_cfg"][
        "adaptive_sampling"
    ]

    assert ground_rewards["undesired_contacts"]["func"] == (
        "gear_sonic.envs.manager_env.mdp:reference_conditioned_undesired_contacts"
    )
    assert ground_rewards["undesired_contacts"]["params"]["command_name"] == "motion"
    assert ground_rewards["undesired_contacts"]["params"]["low_reference_height"] == 0.40
    assert ground_rewards["undesired_contacts"]["params"]["low_pose_penalty_scale"] == 0.0
    assert ground_terminations["anchor_pos"]["params"]["threshold"] == 0.12
    assert ground_terminations["anchor_pos"]["params"]["down_threshold"] == 0.40
    assert ground_terminations["anchor_ori_full"]["params"]["threshold"] == 1.0
    assert ground_terminations["foot_pos_xyz"]["params"]["threshold"] == 0.35
    assert ground_terminations["ee_body_pos"]["params"]["down_threshold"] == 0.50
    assert ground_sampling["uniform_sampling_rate"] == 0.20
    assert ground_sampling["quarantine"]["enable"] is False
    assert ground_sampling["dynamics_gate"]["enable"] is True
    assert ground_algo["config"]["actor_learning_rate"] == 1.0e-5
    assert ground_algo["config"]["critic_learning_rate"] == 5.0e-4

    return {
        "sim_dt": sim_dt,
        "decimation": decimation,
        "control_frequency": control_frequency,
        "target_fps": motion_lib_cfg["target_fps"],
        "excluded_motion_count": len(excluded_motion_keys),
        "action_dim": action_dim,
        "token_total_dim": token_total_dim,
        "actor_proprioception_dim": actor_proprioception_dim,
        "tokenizer_flat_dim": tokenizer_flat_dim,
        "critic_obs_dim": critic_obs_dim,
        "dynamic_decoder_input_dim": dynamic_decoder_input_dim,
        "dynamic_decoder_output_dim": dynamic_decoder_output_dim,
    }


def _resolve_action_scale(action_scale: Mapping[str, float], joint_names: Sequence[str]) -> dict:
    """把执行器正则动作缩放展开为逐关节数值。"""

    import re

    resolved = {}
    for joint_name in joint_names:
        matches = [value for pattern, value in action_scale.items() if re.fullmatch(pattern, joint_name)]
        assert len(matches) == 1, f"关节 {joint_name} 的 action scale 匹配数不是 1: {matches}"
        resolved[joint_name] = matches[0]
    return resolved


def _validate_runtime_robot_config(simulation_app) -> dict[str, list[int]]:  # noqa: ARG001
    """在 Isaac Sim 已启动后导入并验证真实 ArticulationCfg。"""

    from isaaclab.actuators import ImplicitActuatorCfg
    import torch

    from gear_sonic.envs.manager_env.robots import bumi3
    from gear_sonic.envs.manager_env.mdp.commands import _validated_lower_joint_indices
    from gear_sonic.envs.manager_env.mdp.rewards import applied_torque_limits_by_ratio
    from gear_sonic.trl.utils.order_converter import Bumi3Converter, get_order_converter

    assert len(bumi3.BUMI3_ISAACLAB_DOF_NAMES) == 21
    assert len(bumi3.BUMI3_ISAACLAB_BODY_NAMES) == 22
    for mapping in (
        bumi3.BUMI3_ISAACLAB_TO_MUJOCO_DOF,
        bumi3.BUMI3_MUJOCO_TO_ISAACLAB_DOF,
    ):
        assert sorted(mapping) == list(range(21)), f"DoF mapping 不是 0..20 完整排列: {mapping}"
    for mapping in (
        bumi3.BUMI3_ISAACLAB_TO_MUJOCO_BODY,
        bumi3.BUMI3_MUJOCO_TO_ISAACLAB_BODY,
    ):
        assert sorted(mapping) == list(range(22)), f"body mapping 不是 0..21 完整排列: {mapping}"

    converter = Bumi3Converter()
    dof = torch.arange(21, dtype=torch.float32).unsqueeze(0)
    assert torch.equal(converter.to_isaaclab(converter.to_mujoco(dof)), dof)
    body = torch.arange(22 * 3, dtype=torch.float32).reshape(1, 22, 3)
    assert torch.equal(converter.to_isaaclab(converter.to_mujoco(body)), body)
    assert converter.get_isaaclab_to_mujoco_mapping()["lower_joint_indices_mujoco"] == list(
        range(9, 21)
    )
    assert type(get_order_converter()).__name__ == "G1Converter"
    assert type(get_order_converter("h2")).__name__ == "H2Converter"
    assert type(get_order_converter("bumi3")).__name__ == "Bumi3Converter"
    assert _validated_lower_joint_indices({}, 29, "g1") == list(range(12))
    assert _validated_lower_joint_indices(
        bumi3.BUMI3_ISAACLAB_TO_MUJOCO_MAPPING, 21, "bumi3"
    ) == list(range(9, 21))

    robot_cfg = bumi3.BUMI3_CFG
    assert robot_cfg.spawn.fix_base is False
    assert robot_cfg.spawn.asset_path == (
        "gear_sonic/data/assets/robot_description/urdf/bumi3/bumi.urdf"
    )
    assert robot_cfg.spawn.activate_contact_sensors is True
    assert robot_cfg.spawn.replace_cylinders_with_capsules is True
    assert robot_cfg.spawn.rigid_props.disable_gravity is False
    assert robot_cfg.spawn.rigid_props.retain_accelerations is False
    assert robot_cfg.spawn.rigid_props.linear_damping == 0.0
    assert robot_cfg.spawn.rigid_props.angular_damping == 0.0
    assert robot_cfg.spawn.rigid_props.max_linear_velocity == 1000.0
    assert robot_cfg.spawn.rigid_props.max_angular_velocity == 1000.0
    assert robot_cfg.spawn.rigid_props.max_depenetration_velocity == 1.0
    assert robot_cfg.spawn.articulation_props.enabled_self_collisions is True
    assert robot_cfg.spawn.articulation_props.solver_position_iteration_count == 8
    assert robot_cfg.spawn.articulation_props.solver_velocity_iteration_count == 4
    assert robot_cfg.init_state.pos == (0.0, 0.0, 0.65)
    assert robot_cfg.init_state.joint_pos == {
        "l_leg_yaw_joint": 0.0,
        "l_leg_roll_joint": 0.0,
        "l_leg_pitch_joint": -0.1495,
        "l_knee_pitch_joint": 0.3215,
        "l_ankle_pitch_joint": -0.1720,
        "l_ankle_roll_joint": 0.0,
        "r_leg_yaw_joint": 0.0,
        "r_leg_roll_joint": 0.0,
        "r_leg_pitch_joint": -0.1495,
        "r_knee_pitch_joint": 0.3215,
        "r_ankle_pitch_joint": -0.1720,
        "r_ankle_roll_joint": 0.0,
        "waist_yaw_joint": 0.0,
        "l_arm_pitch_joint": 0.0,
        "l_arm_roll_joint": 0.3,
        "l_arm_yaw_joint": 0.0,
        "l_elbow_pitch_joint": 0.0,
        "r_arm_pitch_joint": 0.0,
        "r_arm_roll_joint": -0.3,
        "r_arm_yaw_joint": 0.0,
        "r_elbow_pitch_joint": 0.0,
    }
    assert robot_cfg.init_state.joint_vel == {".*": 0.0}
    assert robot_cfg.soft_joint_pos_limit_factor == 0.9

    actuators = robot_cfg.actuators
    assert set(actuators) == {"legs", "waist", "feet", "arms"}
    for actuator_name, actuator in actuators.items():
        assert type(actuator) is ImplicitActuatorCfg, (
            f"执行器 {actuator_name} 必须使用与 G1 相同的无延迟 ImplicitActuatorCfg"
        )
    assert actuators["legs"].effort_limit_sim == {
        ".*_leg_yaw_joint": 12,
        ".*_leg_roll_joint": 50.0,
        ".*_leg_pitch_joint": 50.0,
        ".*_knee_pitch_joint": 50.0,
    }
    assert actuators["legs"].velocity_limit_sim == {
        ".*_leg_yaw_joint": 12.0,
        ".*_leg_roll_joint": 12.0,
        ".*_leg_pitch_joint": 12.0,
        ".*_knee_pitch_joint": 12.0,
    }
    assert actuators["legs"].stiffness == {
        ".*_leg_yaw_joint": 20,
        ".*_leg_roll_joint": 45,
        ".*_leg_pitch_joint": 45,
        ".*_knee_pitch_joint": 45,
    }
    assert actuators["legs"].damping == {
        ".*_leg_yaw_joint": 1.0,
        ".*_leg_roll_joint": 3.0,
        ".*_leg_pitch_joint": 3.0,
        ".*_knee_pitch_joint": 2.0,
    }
    assert actuators["waist"].effort_limit_sim == 27.0
    assert actuators["waist"].velocity_limit_sim == 9.0
    assert actuators["waist"].stiffness == 53
    assert actuators["waist"].damping == 3.4
    assert actuators["feet"].effort_limit_sim == 9.0
    assert actuators["feet"].velocity_limit_sim == 12.0
    assert actuators["feet"].stiffness == {
        ".*_ankle_pitch_joint": 8,
        ".*_ankle_roll_joint": 8,
    }
    assert actuators["feet"].damping == {
        ".*_ankle_pitch_joint": 0.5,
        ".*_ankle_roll_joint": 0.5,
    }
    assert actuators["feet"].armature == {
        ".*_ankle_pitch_joint": 0.012574,
        ".*_ankle_roll_joint": 0.009608,
    }
    assert actuators["arms"].effort_limit_sim == 4.0
    assert actuators["arms"].velocity_limit_sim == 12
    assert actuators["arms"].stiffness == 8
    assert actuators["arms"].damping == 0.4
    for actuator_name in ("legs", "waist", "arms"):
        assert actuators[actuator_name].armature is None, (
            f"非踝执行器 {actuator_name} 不应配置 armature"
        )

    resolved_scale = _resolve_action_scale(
        bumi3.BUMI3_ACTION_SCALE, bumi3.BUMI3_ISAACLAB_DOF_NAMES
    )
    expected_scale = {
        ".*_leg_yaw_joint": 0.25 * 12.0 / 20.0,
        ".*_leg_roll_joint": 0.25 * 50.0 / 45.0,
        ".*_leg_pitch_joint": 0.25 * 50.0 / 45.0,
        ".*_knee_pitch_joint": 0.25 * 50.0 / 45.0,
        "waist_yaw_joint": 0.25 * 27.0 / 53.0,
        ".*_ankle_pitch_joint": 0.25 * 9.0 / 8.0,
        ".*_ankle_roll_joint": 0.25 * 9.0 / 8.0,
        ".*_arm_pitch_joint": 0.25 * 4.0 / 8.0,
        ".*_arm_roll_joint": 0.25 * 4.0 / 8.0,
        ".*_arm_yaw_joint": 0.25 * 4.0 / 8.0,
        ".*_elbow_pitch_joint": 0.25 * 4.0 / 8.0,
    }
    import re

    for joint_name, actual in resolved_scale.items():
        expected = next(
            value for pattern, value in expected_scale.items() if re.fullmatch(pattern, joint_name)
        )
        assert math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12), (
            f"action scale 错误: {joint_name}={actual}, expected={expected}"
        )

    # 用最小伪环境验证力矩奖励的阈值、绝对值和平方超额语义。
    from types import SimpleNamespace

    reward_robot = SimpleNamespace(
        data=SimpleNamespace(
            joint_effort_limits=torch.tensor([[10.0, 20.0, 5.0]]),
            applied_torque=torch.tensor([[8.5, 18.0, -5.0]]),
        )
    )
    reward_env = SimpleNamespace(scene={"robot": reward_robot})
    reward_asset_cfg = SimpleNamespace(name="robot", joint_ids=[0, 1, 2])
    torque_penalty = applied_torque_limits_by_ratio(
        reward_env, asset_cfg=reward_asset_cfg, limit_ratio=0.85
    )
    # 超额分别为 0、1、0.75，平方和为 1.5625。
    assert torch.allclose(torque_penalty, torch.tensor([1.5625]))

    return {
        "isaaclab_to_mujoco_dof": bumi3.BUMI3_ISAACLAB_TO_MUJOCO_DOF,
        "mujoco_to_isaaclab_dof": bumi3.BUMI3_MUJOCO_TO_ISAACLAB_DOF,
        "isaaclab_to_mujoco_body": bumi3.BUMI3_ISAACLAB_TO_MUJOCO_BODY,
        "mujoco_to_isaaclab_body": bumi3.BUMI3_MUJOCO_TO_ISAACLAB_BODY,
    }


def _assert_finite(value, label: str) -> None:
    """递归检查环境输出中的浮点 tensor 没有 NaN/Inf。"""

    import torch

    if isinstance(value, torch.Tensor):
        if value.is_floating_point():
            assert torch.isfinite(value).all(), f"{label} 包含 NaN/Inf"
    elif isinstance(value, Mapping):
        for key, item in value.items():
            _assert_finite(item, f"{label}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
        for index, item in enumerate(value):
            _assert_finite(item, f"{label}[{index}]")


def _run_environment_smoke(args, simulation_app) -> None:  # noqa: ARG001
    """使用用户提供的现有训练数据创建环境并执行有限步 replay smoke。"""

    assert args.motion_file is not None, "--smoke 必须提供 --motion-file"
    assert args.smpl_motion_file is not None, "--smoke 必须提供 --smpl-motion-file"
    assert args.motion_file.exists(), f"robot motion 路径不存在: {args.motion_file}"
    assert args.smpl_motion_file.exists(), f"SMPL motion 路径不存在: {args.smpl_motion_file}"

    import torch
    from isaaclab.envs import ManagerBasedRLEnv

    from gear_sonic.trl.utils.common import custom_instantiate

    overrides = [
        f"num_envs={args.num_envs}",
        # 使用正式 BUMI3 配置的本地 trimesh，避免 plane 依赖可选的 Nucleus USD。
        "manager_env.config.terrain_type=trimesh",
        f"manager_env.commands.motion.motion_lib_cfg.motion_file={args.motion_file}",
        f"manager_env.commands.motion.motion_lib_cfg.smpl_motion_file={args.smpl_motion_file}",
    ]
    cfg = _compose_config(EXP_NAME, overrides)
    env_cfg = custom_instantiate(cfg.manager_env)
    env_cfg.seed = cfg.seed
    env_cfg.sim.device = args.device
    env_cfg.config["headless"] = True
    env = ManagerBasedRLEnv(cfg=env_cfg)
    try:
        reset_result = env.reset()
        _assert_finite(reset_result, "reset")
        assert env.scene["robot"].joint_names == list(
            __import__(
                "gear_sonic.envs.manager_env.robots.bumi3", fromlist=["BUMI3_ISAACLAB_DOF_NAMES"]
            ).BUMI3_ISAACLAB_DOF_NAMES
        )
        assert env.scene["robot"].body_names == list(
            __import__(
                "gear_sonic.envs.manager_env.robots.bumi3", fromlist=["BUMI3_ISAACLAB_BODY_NAMES"]
            ).BUMI3_ISAACLAB_BODY_NAMES
        )
        action = torch.zeros((args.num_envs, 21), dtype=torch.float32, device=env.device)
        _assert_finite(action, "action")
        for iteration in range(args.iterations):
            step_result = env.step(action)
            _assert_finite(step_result, f"step[{iteration}]")
    finally:
        env.close()


def _parse_args():
    """解析静态验证与可选仿真 smoke 参数。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true", help="创建 Isaac Lab 环境并 reset/step")
    parser.add_argument("--motion-file", type=Path, help="已有 BUMI3 robot motion 文件或目录")
    parser.add_argument("--smpl-motion-file", type=Path, help="已有且配对的 SMPL motion 路径")
    parser.add_argument("--num-envs", type=int, default=1, help="smoke 环境数量，默认 1")
    parser.add_argument("--iterations", type=int, default=1, help="smoke step 次数，默认 1")
    parser.add_argument("--device", default="cuda:0", help="Isaac Lab smoke 设备")
    return parser.parse_args()


def main() -> int:
    """运行全部静态/动态契约检查，并在成功时打印关键 resolved 数值。"""

    args = _parse_args()
    _validate_repository_assets()
    topology = _validate_xml_and_meshes()
    resolved = _validate_resolved_configs()

    # 必须通过 Isaac Lab 官方 AppLauncher 启动应用，再导入依赖 pxr/PhysX 的配置模块。
    # 直接实例化 SimulationApp 会绕过 pip 版 IsaacLab 的 source 路径注册，并且不会
    # 注入训练入口所用的 physics CUDA device 参数，服务器与实际训练环境会因此不一致。
    from isaaclab.app import AppLauncher

    app_launcher = AppLauncher(
        headless=True,
        device=args.device,
        enable_cameras=False,
        kit_args=(
            "--/log/level=error --/log/fileLogLevel=error "
            "--/log/outputStreamLevel=error --no-window"
        ),
    )
    simulation_app = app_launcher.app
    try:
        mappings = _validate_runtime_robot_config(simulation_app)
        if args.smoke:
            _run_environment_smoke(args, simulation_app)

        # Isaac Sim 关闭过程可能直接结束其 Python host，因此在 close 前刷新结果。
        print("BUMI3 原生 SONIC 集成验证通过")
        print(
            f"URDF/MJCF: {len(topology['urdf_joints'])} DoF, "
            f"{len(topology['urdf_bodies'])} bodies"
        )
        for key, value in resolved.items():
            print(f"{key}: {value}")
        for key, value in mappings.items():
            print(f"{key}: {value}")
        print(
            f"smoke: {'通过' if args.smoke else '未请求（需显式提供现有 BUMI3/SMPL 数据）'}",
            flush=True,
        )
    except BaseException:  # Isaac Sim close 可能吞掉异常退出码，必须先明确失败退出。
        traceback.print_exc()
        print("BUMI3 原生 SONIC 集成验证失败", file=sys.stderr, flush=True)
        os._exit(1)
    else:
        simulation_app.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
