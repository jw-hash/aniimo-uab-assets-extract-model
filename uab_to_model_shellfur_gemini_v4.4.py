#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
uab_to_model_v4_shellfur_v44.py (v4.4 / 2026-11-17) —— 从 Unity .uab 重建带「骨骼 + 蒙皮权重 + BlendShape + 动画 + Shell Fur」的角色与静态模型
更新要点：高密丝滑 ShellFur（去斑点/去层间暗影）| 面片 Alpha 裁剪隔离 | TEMPERANCE(克制平均)骨骼朝向 | 跨包材质解析 + 0 骨骼支持

输入：包含 Mesh / AnimationClip（可选 Avatar）的若干 .uab（文件或目录均可）
输出：<输出目录>/<角色>_<变体后缀>/ 下的 .glb、skeleton.json、variant.json、names_template.json；
      加 --fbx 且有 Blender 时再转出 .fbx

为什么需要“重建”而不是“直接提取 fbx”
  Unity 打包后 .fbx 已被拆成 Mesh / AnimationClip 等运行时资源，包内不存在 fbx 文件
  （容器路径里的 .fbx 只是源资源路径）。本脚本把这些运行时数据重新组装成标准模型。

角色、变体与命名
  * 角色 = 容器目录名（如 Parmon_10583_LeafSheep）。衍生角色(Parmon_1058301_LeafSheep 等)的 Mesh 资产名仍沿用
    M_Parmon_10583_ 前缀，只能靠目录区分；-c 可写编号(Parmon_10583)、系列(Parmon=该系列全部角色)、完整目录名或 all
  * 变体 = 同一角色目录内 LOD0 Mesh 后缀不同（如 -688515594）；各 LOD 的后缀与 LOD0 可能不同(如 623013025)，
    按“骨骼是否为该变体骨架的子集”并优先同后缀归属
  * 输出目录/文件统一命名为 <容器目录名>_<LOD0后缀>，如 Parmon_10583_LeafSheep_-688515594
  * 衍生角色没有自带动画时，自动借用本体编号(去掉末两位)的动画，按骨骼哈希匹配

动画偏移的三个来源及处理
  * 根运动：根节点(常见 Bip001)的位移是“角色在世界里走了多远”，原样导入会让模型飞出去。
    默认 --root-motion xz：去掉水平位移做成原地动画(保留跳跃等垂直位移)；all 连垂直也去掉；keep 原样保留
  * 祖先节点缺失：Pelvis/Bip001 等无蒙皮节点不在 BindPose 里，其子骨骼会变成彼此分离的根，动画与身体脱节。
    提供 Avatar(TOS) 或 --tos-json 时，用完整骨骼路径得到精确层级并补全这些祖先节点；否则给出警告
  * 骨骼缩放：BindPose 里带非单位缩放的骨骼(如眼球 0.01 倍)按等比缩放还原为单位骨骼，蒙皮结果不变
  * 祖先节点位置：无蒙皮的祖先(Bip001 等)没有 BindPose。根运动载体的动画首帧带着该动画的起点位移(可达数米)，
    不能用来定它的位置，改为用蒙皮子骨骼的精确世界矩阵自下而上反推，使子骨骼的静止局部位置与动画局部值一致
  * 部件偏移：每个 SkinnedMeshRenderer 的 BindPose 含其相对骨架的变换(可达 1 米以上)，Blender/FBX 导入时不使用 IBM，
    部件会掉回原点。已把偏移烘焙进顶点/法线/形变，所有部件共用同一套 IBM

还原了什么
  * 网格：顶点 / 法线 / UV / 子网格(按材质拆分)；蒙皮：每顶点最多 4 骨骼权重 + BindPose
  * BlendShape：形变目标及其动画权重；动画：Streamed / Dense / Constant / Quantized 四种曲线
  * 骨骼层级：BindPose 局部位移 × 动画局部位置交叉验证；无法验证的骨骼按几何关系猜测并标记
  * 有 Avatar(TOS) 时自动取得真实骨骼名

  * 材质与 Shell Fur（壳层毛发）导入 Blender：
    自动扫描 .uab 中的 SkinnedMeshRenderer / Material / Texture2D 并兼容 --tex-dir 手选贴图目录，按命名分型精确绑定
    CA / MOHR(R金属,G_AO,B高度,A粗糙度) / N(R=B,G=G,B=R 通道重排法线) / F(内置 R/G/B/A 可视化切换节点) /
    E / CoatMask / TW / ClearCrystalParallaxMap_C，将 Shell Fur 严格隔离于毛发材质槽并保持与 Unity 一致。

依赖：pip install UnityPy numpy        （转 FBX / 生成 .blend 与 Shell Fur 需要 Blender，可用 --blender 指定路径）

示例
  python uab_to_model.py ./bundles --list-characters
  python uab_to_model.py ./bundles -c Parmon_10583 --list-variants
  python uab_to_model.py ./bundles -c Parmon -o ./out -j 4 --fbx          # 整个 Parmon 系列，每个角色目录各出一份
  python uab_to_model.py ./bundles -c Parmon_10583 -o ./out --shell-fur --blend --fur-layers 28 --fur-length 0.014
  python uab_to_model.py ./bundles -c Parmon_10583 Parmon_1058301 -o ./out -j 8
  python uab_to_model.py ./bundles -c all -o ./out -j 8 --root-motion xz
  python uab_to_model.py ./bundles -c Parmon_10583 -o ./out --variant=-688515594 --clips "Idle|Walk"
  python uab_to_model.py ./bundles -c Parmon_10583 -o ./out --lod 1 --no-anim
  python uab_to_model.py ./bundles -c Parmon_10583 -o ./out --tos-json tos.json --root-motion all
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import numpy as np

try:
    import UnityPy
    from UnityPy.helpers.MeshHelper import MeshHandler
except ImportError:  # pragma: no cover
    sys.exit("缺少依赖，请先执行: pip install UnityPy numpy")

SCRIPT_VERSION = "v4.4 (2026-11-17)"
MAGICS = (b"UnityFS", b"UnityWeb", b"UnityRaw", b"UnityArchive")
S_MIRROR = np.diag([-1.0, 1.0, 1.0, 1.0])          # Unity(左手) -> glTF(右手)：镜像 X


# =========================================================================== #
# 四元数 / 矩阵工具（四元数顺序 x,y,z,w）
# =========================================================================== #
def qnorm(q):
    return q / np.maximum(np.linalg.norm(q, axis=-1, keepdims=True), 1e-12)


def qmul(a, b):
    ax, ay, az, aw = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
    bx, by, bz, bw = b[..., 0], b[..., 1], b[..., 2], b[..., 3]
    return np.stack([aw * bx + bw * ax + ay * bz - az * by,
                     aw * by + bw * ay + az * bx - ax * bz,
                     aw * bz + bw * az + ax * by - ay * bx,
                     aw * bw - ax * bx - ay * by - az * bz], -1)


def qangle(a, b):
    d = np.clip(np.abs(np.sum(a * b, axis=-1)), 0.0, 1.0)
    return np.degrees(2.0 * np.arccos(d))


def quat_to_mat(q):
    x, y, z, w = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    R = np.empty(q.shape[:-1] + (3, 3), q.dtype)
    R[..., 0, 0] = 1 - 2 * (y * y + z * z); R[..., 0, 1] = 2 * (x * y - z * w); R[..., 0, 2] = 2 * (x * z + y * w)
    R[..., 1, 0] = 2 * (x * y + z * w); R[..., 1, 1] = 1 - 2 * (x * x + z * z); R[..., 1, 2] = 2 * (y * z - x * w)
    R[..., 2, 0] = 2 * (x * z - y * w); R[..., 2, 1] = 2 * (y * z + x * w); R[..., 2, 2] = 1 - 2 * (x * x + y * y)
    return R


def mat_to_quat(R):
    R = np.asarray(R, np.float64)
    t = R[0, 0] + R[1, 1] + R[2, 2]
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        q = [(R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s, 0.25 * s]
    else:
        i = int(np.argmax(np.diag(R)))
        j, k = (i + 1) % 3, (i + 2) % 3
        s = math.sqrt(1.0 + R[i, i] - R[j, j] - R[k, k]) * 2
        q = [0.0, 0.0, 0.0, 0.0]
        q[i] = 0.25 * s
        q[j] = (R[j, i] + R[i, j]) / s
        q[k] = (R[k, i] + R[i, k]) / s
        q[3] = (R[k, j] - R[j, k]) / s
    q = np.array(q)
    return q / np.linalg.norm(q)


def fix_continuity(q):
    """沿时间轴让相邻四元数同半球，避免插值走远路。"""
    q = q.copy()
    for i in range(1, len(q)):
        if np.dot(q[i], q[i - 1]) < 0:
            q[i] = -q[i]
    return q


def m4(d):
    return np.array([[d[f"e{r}{c}"] for c in range(4)] for r in range(4)], np.float64)


def to_gl_vec(v):          # 位置/法线/位移
    v = np.asarray(v).copy()
    v[..., 0] *= -1
    return v


def to_gl_quat(q):         # 旋转：镜像 X => (x,-y,-z,w)
    q = np.asarray(q).copy()
    q[..., 1] *= -1
    q[..., 2] *= -1
    return q


# =========================================================================== #
# AnimationClip 曲线解码：Streamed / Dense / Constant / Quantized
# =========================================================================== #
CURVE_N = {1: 3, 2: 4, 3: 3, 4: 3}      # Transform：位置 / 旋转(四元数) / 缩放 / 欧拉


def _binding_curve_count(b):
    return CURVE_N.get(b["attribute"], 1) if b["typeID"] == 4 else 1


def _decode_streamed(sc, times):
    n = sc["curveCount"]
    out = np.zeros((n, len(times)), np.float32)
    if n == 0 or not sc["data"]:
        return out
    raw = struct.pack("<%dI" % len(sc["data"]), *sc["data"])
    keys = [[] for _ in range(n)]
    pos = 0
    while pos + 8 <= len(raw):
        tm, nk = struct.unpack_from("<fI", raw, pos)
        pos += 8
        for _ in range(nk):
            i, a, b, c, d = struct.unpack_from("<Iffff", raw, pos)
            pos += 20
            if i < n and (np.isfinite(tm) or tm < -1e30):
                keys[i].append((tm, a, b, c, d))
    for ci in range(n):
        ks = keys[ci]
        if not ks:
            continue
        kt = np.array([k[0] for k in ks], np.float64)
        co = np.array([k[1:] for k in ks], np.float64)
        idx = np.clip(np.searchsorted(kt, times, side="right") - 1, 0, len(ks) - 1)
        dt = times - kt[idx]
        dt[kt[idx] < -1e30] = 0.0
        dt = np.maximum(dt, 0.0)
        a, b, c, d = co[idx].T
        with np.errstate(all="ignore"):
            v = ((a * dt + b) * dt + c) * dt + d
        bad = ~np.isfinite(v)
        v[bad] = d[bad]                                   # 阶梯(斜率 inf)：取起始值
        out[ci] = v
    return out


def _decode_dense(dc, times):
    n = dc["m_CurveCount"]
    out = np.zeros((n, len(times)), np.float32)
    if n == 0:
        return out
    fc = dc["m_FrameCount"]
    arr = np.asarray(dc["m_SampleArray"], np.float32).reshape(fc, n)
    f = np.clip((times - dc["m_BeginTime"]) * dc["m_SampleRate"], 0, fc - 1)
    i0 = np.floor(f).astype(int)
    i1 = np.minimum(i0 + 1, fc - 1)
    w = (f - i0).astype(np.float32)
    for ci in range(n):
        out[ci] = arr[i0, ci] * (1 - w) + arr[i1, ci] * w
    return out


def _decode_quantized(qc, times):
    """布局：类型表(n×1B) | 索引表(n×4B) | 静态值(NumStatic×float) | 动态块(NumDynamic×FrameSize)；
    每个动态块 = float start + float step + FrameCount×uint16，值 = start + q*step"""
    n = qc["m_CurveCount"]
    out = np.zeros((n, len(times)), np.float32)
    if n == 0:
        return out
    buf = bytes(bytearray(qc["m_Data"]))
    types = np.frombuffer(buf, np.uint8, n, qc["m_TypeOffset"])
    idx = np.frombuffer(buf, "<u4", n, qc["m_IndicesOffset"])
    static = np.frombuffer(buf, "<f4", qc["m_NumStatic"], qc["m_StaticOffset"])
    fs, fc = qc["m_FrameSize"], qc["m_FrameCount"]
    f = np.clip((times - qc["m_BeginTime"]) * qc["m_SampleRate"], 0, fc - 1)
    i0 = np.floor(f).astype(int)
    i1 = np.minimum(i0 + 1, fc - 1)
    w = (f - i0).astype(np.float32)
    for ci in range(n):
        if types[ci] == 0:
            out[ci] = static[idx[ci]]
        else:
            base = qc["m_DynamicOffset"] + int(idx[ci]) * fs
            start, step = struct.unpack_from("<ff", buf, base)
            q = np.frombuffer(buf, "<u2", fc, base + 8).astype(np.float32)
            vals = start + q * step
            out[ci] = vals[i0] * (1 - w) + vals[i1] * w
    return out


def decode_clip(tree, times=None, fps=30.0):
    """
    返回 (times, tracks, blend, stop)
      tracks: {路径哈希: {'pos':(N,3)|None,'rot':(N,4)|None,'scl':(N,3)|None}}   (Unity 空间、局部坐标)
      blend : {属性哈希: (N,)}   SkinnedMeshRenderer 上的 BlendShape 权重曲线（0~100）
    """
    mc = tree["m_MuscleClip"]
    clip = mc["m_Clip"]["data"]
    stop, start = float(mc["m_StopTime"]), float(mc["m_StartTime"])
    if times is None:
        times = np.unique(np.append(start + np.arange(0, max(stop - start, 0) + 1e-9, 1.0 / fps), stop))
    times = np.asarray(times, np.float64)
    if clip.get("m_PredictClip", {}).get("m_CurveCount", 0):
        raise NotImplementedError("该剪辑使用 PredictClip 压缩，暂不支持")
    allv = np.concatenate([
        _decode_streamed(clip["m_StreamedClip"], times),
        _decode_dense(clip["m_DenseClip"], times),
        np.tile(np.asarray(clip["m_ConstantClip"]["data"], np.float32)[:, None], (1, len(times))),
        _decode_quantized(clip["m_QuantizedClip"], times),
    ], axis=0)
    bindings = tree["m_ClipBindingConstant"]["genericBindings"]
    need = sum(_binding_curve_count(b) for b in bindings)
    if need != allv.shape[0]:
        raise ValueError(f"曲线数不一致: 绑定需要 {need}, 实际 {allv.shape[0]}")
    tracks, blend, ci = {}, {}, 0
    for b in bindings:
        k = _binding_curve_count(b)
        if b["typeID"] == 4 and b["attribute"] in (1, 2, 3):
            ent = tracks.setdefault(b["path"], {"pos": None, "rot": None, "scl": None})
            ent[{1: "pos", 2: "rot", 3: "scl"}[b["attribute"]]] = allv[ci:ci + k].T.astype(np.float64)
        elif b["typeID"] == 137:
            blend[b["attribute"]] = allv[ci].astype(np.float64)
        ci += k
    return times, tracks, blend, stop



# =========================================================================== #
# 扫描 bundle
# =========================================================================== #

def sniff(path):
    try:
        with open(path, "rb") as f:
            return any(f.read(12).startswith(m) for m in MAGICS)
    except OSError:
        return False


def list_bundles(inputs):
    out = []
    for inp in inputs:
        p = Path(inp)
        if p.is_file():
            out.append(str(p))
        elif p.is_dir():
            for dp, _, fns in os.walk(p):
                for fn in fns:
                    full = os.path.join(dp, fn)
                    if fn.lower().endswith((".uab", ".ab", ".bundle", ".assetbundle", ".unity3d")) or sniff(full):
                        out.append(full)
    return sorted(set(out))


def container_paths(env):
    res = {}
    for obj in env.objects:
        if obj.type.name != "AssetBundle":
            continue
        try:
            ab = obj.read()
            fname = getattr(obj.assets_file, "name", "")
            for cp, info in ab.m_Container:
                if getattr(info.asset, "file_id", 0) == 0:
                    res.setdefault((fname, info.asset.path_id), cp)
        except Exception:
            pass
    return res


# =========================================================================== #
# Mesh 读取
# =========================================================================== #

def _pad_skin(bw, bi, nv):
    """每顶点影响骨骼数可能是 1~4（通道维度不固定），统一补齐为 4 列。"""
    if bi is None:
        return None, None
    if bw is None:                          # 刚性绑定：只有骨骼索引(如眼球)，每个顶点跟随一块骨骼，权重隐含为 1
        i = np.zeros((nv, 4), np.int64)
        i[:, 0] = np.asarray(bi, np.int64).reshape(nv, -1)[:, 0]
        w = np.zeros((nv, 4))
        w[:, 0] = 1.0
        return w, i
    bw = np.asarray(bw, np.float64).reshape(nv, -1)
    bi = np.asarray(bi, np.int64).reshape(nv, -1)
    k = min(bw.shape[1], bi.shape[1], 4)
    w = np.zeros((nv, 4))
    i = np.zeros((nv, 4), np.int64)
    w[:, :k], i[:, :k] = bw[:, :k], bi[:, :k]
    zero = w.sum(1) <= 1e-9                 # 没有权重的顶点：全部交给第一个骨骼，避免被丢弃
    w[zero, 0] = 1.0
    return w, i


def _norm_colors(raw_c, nv):
    if raw_c is None:
        return None
    try:
        arr = np.asarray(raw_c, np.float32).reshape(nv, -1)
        if arr.shape[1] == 0:
            return None
        if arr.max() > 1.0 + 1e-3:
            arr = arr / 255.0
        if arr.shape[1] < 4:
            out = np.ones((nv, 4), np.float32)
            out[:, :arr.shape[1]] = arr
            arr = out
        else:
            arr = arr[:, :4]
        return np.clip(arr, 0.0, 1.0)
    except Exception:
        return None


def read_part(obj, mesh_name, part, lod, file="", fname="", pid=0):
    t = obj.read_typetree()
    h = MeshHandler(obj.read())
    h.process()
    P = {"name": part, "mesh_name": mesh_name, "lod": lod,
         "file": file, "fname": fname, "pid": pid}
    P["pos"] = np.asarray(h.m_Vertices, np.float64).reshape(-1, 3)
    nv = len(P["pos"])
    P["nrm"] = np.asarray(h.m_Normals, np.float64).reshape(nv, -1)[:, :3] if h.m_Normals is not None else None
    P["uv"] = np.asarray(h.m_UV0, np.float64).reshape(nv, -1)[:, :2] if h.m_UV0 is not None else None
    uv1 = getattr(h, "m_UV1", None)
    try:
        P["uv1"] = np.asarray(uv1, np.float64).reshape(nv, -1)[:, :2] if uv1 is not None else None
    except Exception:
        P["uv1"] = None
    P["colors"] = _norm_colors(getattr(h, "m_Colors", None), nv)
    P["tris"] = [np.asarray(s, np.uint32).reshape(-1, 3) for s in h.get_triangles()]
    P["bw"], P["bi"] = _pad_skin(h.m_BoneWeights, h.m_BoneIndices, nv)
    P["hashes"] = [int(x) for x in t.get("m_BoneNameHashes", [])]
    P["bindpose"] = [m4(m) for m in t.get("m_BindPose", [])]
    P["root_hash"] = int(t.get("m_RootBoneNameHash", 0))
    # ---- BlendShape ----
    P["morphs"] = []
    sh = t.get("m_Shapes") or {}
    if sh.get("vertices"):
        verts, shapes = sh["vertices"], sh["shapes"]
        for ch in sh["channels"]:
            si = ch["frameIndex"] + ch["frameCount"] - 1          # 取最后一帧(满权重)
            s = shapes[si]
            d = np.zeros((nv, 3), np.float64)
            for v in verts[s["firstVertex"]: s["firstVertex"] + s["vertexCount"]]:
                d[v["index"]] = (v["vertex"]["x"], v["vertex"]["y"], v["vertex"]["z"])
            nm = ch["name"].split(".", 1)[1] if ch["name"].startswith("blendShape.") else ch["name"]
            P["morphs"].append({"name": nm, "hash": int(ch["nameHash"]), "delta": d})
    return P


def load_platform_materials(paths):
    """从 PlatformData JSON 读取各 Mesh 部件对应的材质名（可选）。"""
    res = {}
    files = []
    for p in paths or []:
        p = Path(p)
        files += [str(x) for x in p.rglob("*PlatformData*.json")] if p.is_dir() else [str(p)]
    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8"))
            r = d["m_DefaultConfig"]["m_Lods"][0]["m_Renderers"][0]
            mesh = Path(r["m_MeshPath"]["m_Path"]).stem
            mats = [Path(m["m_Path"]).stem for m in r["m_MaterialList"]]
            res[mesh] = mats
        except Exception:
            continue
    return res


# =========================================================================== #
# 骨骼层级推断
# =========================================================================== #
def infer_parents(H, W, samples, tol=1e-3, Wu=None):
    """
    H: 骨骼哈希列表；W: (n,4,4) 模型空间世界矩阵
    samples: [{hash:(pos(3)|None, rot(4)|None)}...] 每个 clip 的首帧局部位置/旋转
    原理：刚体骨骼的局部位移为常量，且等于 inv(W_父) @ W_子 的平移；
         对每块骨骼跨所有 clip 投票选出使两者吻合的候选父骨骼，并用旋转一致性消除并列。
    """
    n = len(H)
    Winv = np.linalg.inv(W)
    Wu = W if Wu is None else Wu                                  # 旋转比较用单位化(去缩放)的矩阵
    Wuinv = np.linalg.inv(Wu)
    T = np.einsum("jab,ibc->jiac", Winv, W)[..., :3, 3]          # T[j,i] = (Winv[j] @ W[i]) 的平移（含父缩放，与动画局部位置同一量纲）
    votes = np.zeros((n, n), np.int64)
    seen = np.zeros(n, np.int64)
    for smp in samples:
        P = np.full((n, 3), np.nan)
        for i, h in enumerate(H):
            v = smp.get(h)
            if v is not None and v[0] is not None:
                P[i] = v[0]
        mask = ~np.isnan(P[:, 0])
        seen += mask
        d = np.linalg.norm(T - P[None, :, :], axis=2)            # (j, i)
        hit = (d < tol) & mask[None, :]
        hit[np.arange(n), np.arange(n)] = False
        votes += hit.T.astype(np.int64)
    parent = np.full(n, -1, np.int64)
    conf = np.zeros(n)
    ties = 0
    for i in range(n):
        mx = votes[i].max()
        if mx <= 0:
            continue
        cand = [j for j in range(n) if votes[i, j] >= 0.9 * mx]
        if len(cand) > 1:                                          # 位置并列 -> 用旋转一致性裁决
            ties += 1
            best, bj = 1e9, cand[0]
            for j in cand:
                qr = mat_to_quat((Wuinv[j] @ Wu[i])[:3, :3])
                errs = [qangle(s[H[i]][1], qr) for s in samples[::6]
                        if H[i] in s and s[H[i]][1] is not None]
                e = float(np.median(errs)) if errs else 1e9
                if e < best:
                    best, bj = e, j
            parent[i] = bj
        else:
            parent[i] = cand[0]
        conf[i] = votes[i, parent[i]] / max(seen[i], 1)
    # 环检测：出现环则断开置信度最低的边
    for i in range(n):
        seen_chain, k = [], i
        while k >= 0 and k not in seen_chain:
            seen_chain.append(k)
            k = int(parent[k])
        if k >= 0:
            cyc = seen_chain[seen_chain.index(k):]
            cut = min(cyc, key=lambda x: conf[x])
            parent[cut] = -1
    return parent, conf, ties


# =========================================================================== #
# glTF/GLB 写出
# =========================================================================== #
class Gltf:
    def __init__(self):
        self.bin = bytearray()
        self.views, self.accs = [], []

    def _pad(self):
        while len(self.bin) % 4:
            self.bin.append(0)

    def add(self, arr, target=None, minmax=False):
        arr = np.ascontiguousarray(arr)
        if arr.dtype == np.float64:
            arr = arr.astype(np.float32)
        ctype = {np.dtype("float32"): 5126, np.dtype("uint16"): 5123, np.dtype("uint32"): 5125,
                 np.dtype("uint8"): 5121}[arr.dtype]
        if arr.ndim == 1:
            typ, n = "SCALAR", len(arr)
        elif arr.ndim == 2:
            typ, n = {2: "VEC2", 3: "VEC3", 4: "VEC4"}[arr.shape[1]], len(arr)
        else:                                                   # (N,4,4) 矩阵，glTF 为列主序
            typ, n = "MAT4", len(arr)
            arr = np.ascontiguousarray(arr.transpose(0, 2, 1))
        self._pad()
        view = {"buffer": 0, "byteOffset": len(self.bin), "byteLength": arr.nbytes}
        if target:
            view["target"] = target
        self.bin += arr.tobytes()
        self.views.append(view)
        acc = {"bufferView": len(self.views) - 1, "componentType": ctype, "count": n, "type": typ}
        if minmax:
            flat = arr.reshape(n, -1)
            acc["min"] = [float(x) for x in flat.min(0)]
            acc["max"] = [float(x) for x in flat.max(0)]
        self.accs.append(acc)
        return len(self.accs) - 1


def write_glb(path, doc, gl):
    gl._pad()
    doc["bufferViews"], doc["accessors"] = gl.views, gl.accs
    doc["buffers"] = [{"byteLength": len(gl.bin)}]
    js = json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    js += b" " * ((4 - len(js) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(gl.bin)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, total))
        f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        f.write(struct.pack("<II", len(gl.bin), 0x004E4942) + bytes(gl.bin))



# =========================================================================== #
# 通用小工具
# =========================================================================== #

def safe_name(s):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(s)).strip() or "_"



# =========================================================================== #
# 并行基础设施：每个进程缓存已加载的 bundle；任务按文件聚簇减少重复解压
# =========================================================================== #
_ENV_CACHE = {}
_ENV_CACHE_MAX = 24


def _cache_env(file, env, idx):
    if len(_ENV_CACHE) >= _ENV_CACHE_MAX:
        _ENV_CACHE.pop(next(iter(_ENV_CACHE)))
    _ENV_CACHE[file] = (env, idx)


def _get_obj(file, fname, pid):
    ent = _ENV_CACHE.get(file)
    if ent is None:
        env = UnityPy.load(file)
        idx = {(getattr(o.assets_file, "name", ""), o.path_id): o for o in env.objects}
        _cache_env(file, env, idx)
        ent = _ENV_CACHE[file]
    return ent[1][(fname, pid)]


def pmap(pool, fn, arglist):
    """按参数首元素(bundle 路径)排序聚簇提交以提升 _ENV_CACHE 命中率，同时保持原序返回结果。"""
    if not arglist:
        return []
    if pool is None:
        order = sorted(range(len(arglist)), key=lambda i: str(arglist[i][0]) if arglist[i] else "")
        out = [None] * len(arglist)
        for i in order:
            out[i] = fn(*arglist[i])
        return out
    order = sorted(range(len(arglist)), key=lambda i: str(arglist[i][0]) if arglist[i] else "")
    futs = [(i, pool.submit(fn, *arglist[i])) for i in order]
    out = [None] * len(arglist)
    for i, f in futs:
        out[i] = f.result()
    return out


MESH_TOKEN_RE = re.compile(r"^M_(?P<c>[A-Za-z]+_\d+)_")
CHAR_SEG_RE = re.compile(r"^(?P<c>[A-Za-z]+_\d{4,})(?:_|$)")      # 角色目录名：Parmon_1058301_LeafSheep
_GENERIC_DIR_SEGS = frozenset({
    "assets", "art", "res", "resources", "mesh", "meshes", "model", "models",
    "prefab", "prefabs", "fbx", "lod", "lods", "lod0", "lod1", "lod2", "lod3",
    "material", "materials", "texture", "textures", "animation", "animations",
    "anim", "anims", "rig", "avatar", "avatars", "common", "shared", "runtime",
})


def token_match(token, seg):
    """目录名 seg 是否属于 token：全名相等 / 以 'token_' 开头（大小写不敏感）。
    Parmon_10583 匹配 Parmon_10583_LeafSheep，但不匹配 Parmon_1058301_LeafSheep；Parmon 匹配全部 Parmon_*。"""
    if token in ("all", "*"):
        return bool(CHAR_SEG_RE.match(seg))
    sl, tl = seg.lower(), token.lower()
    return sl == tl or sl.startswith(tl + "_")


def _leaf_asset_dir(segs, start_idx=0, mesh_name=""):
    """在命中泛化系列目录后提取具体的末端资产目录（跳过 Mesh/Prefabs/LOD 等通用词），避免道具混并。"""
    sub = [s for s in segs[start_idx:] if s and s.lower() not in _GENERIC_DIR_SEGS]
    if len(sub) >= 2:
        return sub[-1]
    if mesh_name:
        stem = re.sub(r"_-?\d+$", "", mesh_name)
        stem = re.sub(r"_LOD\d+$", "", stem, flags=re.I)
        stem = re.sub(r"^M_", "", stem)
        if stem:
            return stem
    return sub[-1] if sub else (segs[start_idx] if start_idx < len(segs) else "")


def pick_char_dir(tokens, segs, mesh_name=""):
    """在容器目录的各级名称里挑出角色或资产目录：
    1) 优先返回形如 <系列>_<4位以上编号>[_*] 的角色目录；
    2) 若命中无编号目录（如道具/家具），则按各自最末级具体资产子目录独立分组，避免全series混并。"""
    for t in tokens:
        good = [x for x in segs if token_match(t, x) and CHAR_SEG_RE.match(x)]
        if good:
            return t, good[0]
        hits = [i for i, x in enumerate(segs) if token_match(t, x)]
        if hits:
            leaf = _leaf_asset_dir(segs, hits[0], mesh_name=mesh_name)
            if leaf:
                return t, leaf
    return None


def _pptr_tuple(p):
    if p is None:
        return None
    if isinstance(p, dict):
        fid = int(p.get("m_FileID", 0))
        pid = int(p.get("m_PathID", 0))
    else:
        fid = int(getattr(p, "m_FileID", getattr(p, "file_id", 0)))
        pid = int(getattr(p, "m_PathID", getattr(p, "path_id", 0)))
    return (fid, pid) if pid != 0 else None


def _norm_ext_name(ext):
    """UnityPy FileIdentifier 的路径常写在 ext.path（如 archive:/CAB-xxx/CAB-xxx），ext.name 常为空。"""
    for attr in ("path", "name"):
        v = getattr(ext, attr, "") or ""
        if v:
            v = v.replace("\\", "/").rsplit("/", 1)[-1]
            if v:
                return v
    return ""


def t_scan_bundle_index(file):
    """极速两段式首轮索引：仅读取 AssetBundle.m_Container、externals 与轻量 peek_name()，
    完全跳过跨全包的重型 read_typetree()，并将索引结构精简以便进程间高速传输与本地磁盘缓存。"""
    out = {
        "file": file, "meshes": [], "clips": [], "avatars": [],
        "materials": [], "textures": [], "renderers": [],
        "externals": {}, "chars": {}, "error": None,
    }
    try:
        env = UnityPy.load(file)
        objs = list(env.objects)
        _cache_env(file, env, {(getattr(o.assets_file, "name", ""), o.path_id): o for o in objs})
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        return out
    cmap = container_paths(env)
    chars = Counter()
    bname = os.path.basename(file)
    for obj in objs:
        tn = obj.type.name
        fname = getattr(obj.assets_file, "name", "")
        if fname and fname not in out["externals"]:
            exts = [_norm_ext_name(ext) for ext in (getattr(obj.assets_file, "externals", []) or [])]
            out["externals"][fname] = exts
        if tn not in ("Mesh", "AnimationClip", "Avatar", "Material", "Texture2D", "SkinnedMeshRenderer", "MeshRenderer"):
            continue
        cp = cmap.get((fname, obj.path_id), "")
        if tn == "Material":
            out["materials"].append({"file": file, "fname": fname, "pid": obj.path_id,
                                     "name": obj.peek_name() or "", "container": cp})
        elif tn == "Texture2D":
            out["textures"].append({"file": file, "fname": fname, "pid": obj.path_id,
                                    "name": obj.peek_name() or "", "container": cp})
        elif tn in ("SkinnedMeshRenderer", "MeshRenderer"):
            out["renderers"].append({"file": file, "fname": fname, "pid": obj.path_id, "container": cp})
        elif tn == "Avatar":
            out["avatars"].append({"file": file, "fname": fname, "pid": obj.path_id,
                                   "name": obj.peek_name() or "", "container": cp})
        else:
            name = obj.peek_name() or ""
            segs = cp.rsplit("/", 1)[0].split("/") if "/" in cp else []
            if tn == "Mesh" and not any(CHAR_SEG_RE.match(s) for s in segs):
                m = MESH_TOKEN_RE.match(name)
                if m:
                    segs = segs + [m.group("c")]
            if tn == "Mesh" and segs:
                hit_c = next((s for s in segs if CHAR_SEG_RE.match(s)), None) or _leaf_asset_dir(segs, 0, mesh_name=name)
                if hit_c:
                    chars[hit_c] += 1
            out["meshes" if tn == "Mesh" else "clips"].append({
                "file": file, "fname": fname, "pid": obj.path_id,
                "name": name, "container": cp, "segs": segs, "bundle": bname,
            })
    out["chars"] = dict(chars)
    return out


def t_read_renderers(items):
    """按需批量解析目标角色相关 bundle 内的 Renderer typetree（支持 SkinnedMeshRenderer 与 MeshRenderer+MeshFilter）。"""
    res = []
    mf_by_file_fname = {}
    for file, fname, pid, cp in items:
        try:
            obj = _get_obj(file, fname, pid)
            t = obj.read_typetree()
            mp = _pptr_tuple(t.get("m_Mesh"))
            if mp is None:
                go = _pptr_tuple(t.get("m_GameObject"))
                if go is not None:
                    ckey = (file, fname)
                    if ckey not in mf_by_file_fname:
                        mf_map = {}
                        ent = _ENV_CACHE.get(file)
                        if ent is not None:
                            for o in ent[0].objects:
                                if o.type.name == "MeshFilter" and getattr(o.assets_file, "name", "") == fname:
                                    try:
                                        mft = o.read_typetree()
                                        mf_go = _pptr_tuple(mft.get("m_GameObject"))
                                        mf_mesh = _pptr_tuple(mft.get("m_Mesh"))
                                        if mf_go is not None and mf_mesh is not None:
                                            mf_map[mf_go] = mf_mesh
                                    except Exception:
                                        pass
                        mf_by_file_fname[ckey] = mf_map
                    mp = mf_by_file_fname[ckey].get(go)
            if mp is not None:
                mats = [_pptr_tuple(x) for x in (t.get("m_Materials") or [])]
                res.append({"file": file, "fname": fname, "pid": pid, "mesh": mp, "mats": mats, "container": cp})
        except Exception:
            pass
    return res


def t_read_avatars(items):
    """按需批量读取候选 Avatar 的 m_TOS 路径表。"""
    tos = {}
    for file, fname, pid in items:
        try:
            obj = _get_obj(file, fname, pid)
            for h, path in obj.read_typetree().get("m_TOS", []):
                tos[int(h)] = str(path)
        except Exception:
            pass
    return tos


def t_mesh_info(file, fname, pid):
    """只读 Mesh 的骨骼信息（不读顶点）：骨骼哈希 + BindPose，用于变体/LOD 归属判断与骨架重建。"""
    try:
        t = _get_obj(file, fname, pid).read_typetree()
        bp = [m4(m) for m in t.get("m_BindPose", [])]
        return {"bones": [int(x) for x in t.get("m_BoneNameHashes", [])],
                "bindpose": np.stack(bp) if bp else np.zeros((0, 4, 4)),
                "verts": int(t["m_VertexData"]["m_VertexCount"]),
                "morphs": len((t.get("m_Shapes") or {}).get("channels", [])), "error": None}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def t_probe_clip(file, fname, pid):
    """读取动画的轨道哈希集合与首帧局部位置/旋转（用于适配判定与层级推断）。"""
    try:
        t = _get_obj(file, fname, pid).read_typetree()
        binds = {b["path"] for b in t["m_ClipBindingConstant"]["genericBindings"] if b["typeID"] == 4}
        _, tr, bl, _ = decode_clip(t, times=[float(t["m_MuscleClip"]["m_StartTime"])])
        sample = {h: (v["pos"][0] if v["pos"] is not None else None,
                      v["rot"][0] if v["rot"] is not None else None) for h, v in tr.items()}
        return {"binds": binds, "sample": sample, "error": None}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def t_decode_clip(file, fname, pid, fps):
    try:
        t = _get_obj(file, fname, pid).read_typetree()
        tm, tr, bl, stop = decode_clip(t, fps=fps)
        return {"times": tm, "tracks": tr, "blend": bl, "stop": stop, "error": None}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def t_read_part(file, fname, pid, mesh_name, part, lod):
    try:
        return read_part(_get_obj(file, fname, pid), mesh_name, part, lod, file=file, fname=fname, pid=pid)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}", "name": part}


def _iter_kv(c):
    if isinstance(c, dict):
        return list(c.items())
    out = []
    for item in (c or []):
        if isinstance(item, (list, tuple)) and len(item) == 2:
            out.append((item[0], item[1]))
        elif isinstance(item, dict) and "first" in item and "second" in item:
            out.append((item["first"], item["second"]))
    return out


def t_read_material(file, fname, pid):
    """读取 Unity Material 的着色器关键字、纹理引用(含 UV Scale/Offset)、浮点参数与颜色参数。"""
    try:
        obj = _get_obj(file, fname, pid)
        t = obj.read_typetree()
        sp = t.get("m_SavedProperties") or {}
        tex_envs = {}
        for k, v in _iter_kv(sp.get("m_TexEnvs")):
            if not isinstance(v, dict):
                continue
            pt = _pptr_tuple(v.get("m_Texture"))
            sc = v.get("m_Scale") or {}
            of = v.get("m_Offset") or {}
            tex_envs[str(k)] = {
                "pptr": pt,
                "scale": [float(sc.get("x", 1.0)), float(sc.get("y", 1.0))],
                "offset": [float(of.get("x", 0.0)), float(of.get("y", 0.0))],
            }
        floats = {str(k): float(v) for k, v in _iter_kv(sp.get("m_Floats"))}
        colors = {}
        for k, v in _iter_kv(sp.get("m_Colors")):
            if isinstance(v, dict):
                colors[str(k)] = [float(v.get("r", 1.0)), float(v.get("g", 1.0)),
                                  float(v.get("b", 1.0)), float(v.get("a", 1.0))]
        kws = [str(x) for x in (t.get("m_ShaderKeywords") or "").split() if x]
        kws += [str(x) for x in (t.get("m_ValidKeywords") or []) if x]
        return {
            "name": str(t.get("m_Name") or obj.peek_name() or ""),
            "fname": fname,
            "pid": pid,
            "shader_pptr": _pptr_tuple(t.get("m_Shader")),
            "keywords": sorted(set(kws)),
            "tex_envs": tex_envs,
            "floats": floats,
            "colors": colors,
            "error": None,
        }
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def t_export_texture(file, fname, pid, out_path):
    try:
        obj = _get_obj(file, fname, pid)
        tex = obj.read()
        img = getattr(tex, "image", None)
        if img is None:
            return {"error": "Texture2D.image 为空"}
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        # compress_level=1 大幅加速 2K/4K 无损 PNG 写出
        img.save(out_path, format="PNG", compress_level=1)
        # 在导出侧用 numpy 毫秒级预计算统计量，避免 Blender 启动主线程读写 im.pixels 卡死
        stats = {"all_zero": False, "max_rgb": 1.0, "max_a": 1.0, "min_a": 1.0}
        try:
            arr = np.asarray(img)
            h, w = arr.shape[:2]
            sy = max(1, h // 96)
            sx = max(1, w // 96)
            sub = arr[::sy, ::sx]
            if sub.ndim == 2:
                mrgb = float(sub.max()) / 255.0
                ma = 1.0
                mina = 1.0
            else:
                ch = sub.shape[2]
                mrgb = float(sub[..., :min(3, ch)].max()) / 255.0
                ma = (float(sub[..., 3].max()) / 255.0) if ch >= 4 else 1.0
                mina = (float(sub[..., 3].min()) / 255.0) if ch >= 4 else 1.0
            stats = {
                "all_zero": bool(mrgb < 0.004 and ma < 0.004),
                "max_rgb": round(mrgb, 4),
                "max_a": round(ma, 4),
                "min_a": round(mina, 4),
            }
        except Exception:
            pass
        ts = getattr(tex, "m_TextureSettings", None)
        return {
            "name": str(getattr(tex, "m_Name", "") or obj.peek_name() or ""),
            "width": int(img.width),
            "height": int(img.height),
            "wrap_u": int(getattr(ts, "m_WrapU", 0)) if ts else 0,
            "wrap_v": int(getattr(ts, "m_WrapV", 0)) if ts else 0,
            "stats": stats,
            "error": None,
        }
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


# =========================================================================== #
# 变体 / LOD 归属
# =========================================================================== #
MESH_NAME_RES = (
    re.compile(r"^M_(?P<base>.+?)_(?P<part>(?!LOD\d+(?:_|$))[A-Za-z]+\d*)(?:_LOD(?P<lod>\d+))?_(?P<hash>-?\d+)$"),
    re.compile(r"^M_(?P<base>[A-Za-z]+_\d+)_(?P<part>(?!LOD\d+(?:_|$)).+?)(?:_LOD(?P<lod>\d+))?_(?P<hash>-?\d+)$"),   # 部件名含下划线时的兜底
    re.compile(r"^(?:M_)?(?P<part>.+?)(?:_LOD(?P<lod>\d+))?_(?P<hash>-\d{4,}|\d{5,})$"),                          # 通用/道具网格名兜底
)


def parse_mesh_name(name):
    """M_Parmon_10583_Body01_LOD1_623013025 -> ('Body01', 1, 623013025)；无法解析返回 None。
    注意：衍生角色(Parmon_1058301 等)的 Mesh 仍沿用 M_Parmon_10583_ 前缀，角色归属由容器目录决定。"""
    for rx in MESH_NAME_RES:
        m = rx.match(name)
        if m:
            return m.group("part"), int(m.group("lod") or 0), int(m.group("hash"))
    return None


def pick_lod(vh, lod0_parts, all_by, lod, forced_hash, log):
    """
    为变体 vh 选择 LOD=lod 的各部件 Mesh。
    规则：(1) 骨骼必须是该变体骨架的子集；(2) 先用骨骼最多的“锚点部件”(Body)确定该 LOD 使用的哈希，
         优先与变体同哈希；(3) 其余部件优先取与锚点相同哈希的 Mesh。
    """
    skel = set().union(*[set(r["bones"]) for r in lod0_parts.values()])
    anchor = max(lod0_parts, key=lambda p: len(lod0_parts[p]["bones"]))

    def compat(r):
        return set(r["bones"]) <= skel
    cands = [r for r in all_by.get((anchor, lod), []) if compat(r)]
    if forced_hash is not None:
        cands = [r for r in cands if r["hash"] == forced_hash] or cands
    pick = [r for r in cands if r["hash"] == vh] or cands
    lod_hash = pick[0]["hash"] if pick else None
    if len(cands) > 1:
        log(f"      LOD{lod} 锚点部件 {anchor} 有 {len(cands)} 个兼容候选 {[r['hash'] for r in cands]}，"
            f"取 {lod_hash}（可用 --lod-hash 指定）")
    sel = {}
    for part in lod0_parts:
        cs = [r for r in all_by.get((part, lod), []) if compat(r)]
        pk = [r for r in cs if r["hash"] == lod_hash] or [r for r in cs if r["hash"] == vh] or cs
        if pk:
            sel[part] = pk[0]
        else:
            log(f"      [提示] 部件 {part} 没有 LOD{lod} 的兼容 Mesh，已跳过")
    return sel


def applicable_clip(binds, skel_set):
    """动画能否驱动该骨架：命中轨道≥10，且(≥60% 的轨道属于该骨架 或 骨架一半以上被覆盖)。
    其它角色的动画命中率接近 0；衍生变体缺少本体的部分骨骼，借用本体动画时命中率通常在 60%~100%。"""
    hit = len(binds & skel_set)
    return hit >= 10 and (hit >= 0.6 * len(binds) or hit >= 0.5 * len(skel_set))


def guess_parents(H, W, parent, has_track, log):
    """
    对“没有任何位置轨道、无法用动画验证”的骨骼，按几何关系贪心地挂到已确定的结构上：
    评分 = 距离 × (1 + 6×(1 − 方向余弦))，方向取已验证父子对在父局部系中的主导轴。
    (在 V1 已验证层级上隐藏 15~40% 父节点的模拟中，准确率约 70%，仅作近似。)
    """
    n = len(H)
    unk = [i for i in range(n) if parent[i] < 0 and not has_track[i]]
    if not unk:
        return set()
    ver = [i for i in range(n) if parent[i] >= 0]
    if len(ver) < 10:
        log("      [提示] 已验证的父子关系太少，无法估计几何规律，未启用父骨骼猜测")
        return set()
    pos = W[:, :3, 3]
    dirs = []
    for i in ver:
        v = W[parent[i]][:3, :3].T @ (pos[i] - pos[parent[i]])
        d = np.linalg.norm(v)
        if d > 0.01:
            dirs.append(v / d)
    if len(dirs) < 5:
        return set()
    dirs = np.array(dirs)
    ax = int(np.argmax(np.abs(dirs).mean(0)))
    sg = float(np.sign(np.median(dirs[:, ax]))) or 1.0
    Rt = np.stack([W[j][:3, :3].T for j in range(n)])
    A = [i for i in range(n) if i not in set(unk)]
    pending, guessed = set(unk), set()
    while pending:
        Aarr = np.array(A)
        best = (1e18, None, None)
        for i in pending:
            v = np.einsum("jab,jb->ja", Rt[Aarr], pos[i] - pos[Aarr])
            d = np.linalg.norm(v, axis=1)
            with np.errstate(all="ignore"):
                c = (v[:, ax] * sg) / d
            sc = d * (1 + 6.0 * (1 - c))
            sc[d < 1e-9] = 1e9
            k = int(np.argmin(sc))
            if sc[k] < best[0]:
                best = (sc[k], i, int(Aarr[k]))
        _, i, j = best
        parent[i] = j
        A.append(i)
        pending.discard(i)
        guessed.add(i)
    return guessed


# =========================================================================== #
# Blender 导入：材质贴图映射 + Shell Fur（Geometry Nodes + 着色器）+ 保存 .blend / 导出 .fbx
# =========================================================================== #
BLENDER_SHELLFUR_SCRIPT = r'''
"""
在 Blender 中导入 .glb，重建 Unity 分型材质与纹理映射（CA / MOHR / N(B<->R) / F(可切换通道) / E / CoatMask / TW / ClearCrystal），
并生成可实时调节且作用域精确隔离的 Shell Fur（壳层毛发）效果。
支持作为标准 Blender 插件安装（Preferences -> Add-ons -> Install），在 3D 视口侧栏 N -> Shell Fur
中一键加载 shellfur_config.json 还原游戏内毛发配置，或由 uab_to_model_v4.py 无界面自动调用：
  blender -b --python blender_import_shellfur.py -- model.glb out.blend "" 30.0 --tex-dir ./textures
"""
bl_info = {
    "name": "UAB Shell Fur Importer & Live Configurator",
    "author": "UAB Pipeline",
    "version": (2, 1, 0),
    "blender": (3, 6, 0),
    "location": "File > Import > Shell Fur (.glb / shellfur_config.json) & View3D > Sidebar (N) > Shell Fur",
    "description": "导入 Unity 导出模型与 shellfur_config.json，还原游戏内分型材质与轻量化视口/渲染双档 Shell Fur",
    "category": "Import-Export",
}

import json
import math
import os
import re
import sys
import bpy

# 若希望手动指定外部贴图文件夹，可填写下方路径或在 N 面板 Tex Dir 中设置：
USER_TEX_DIR = ""
_IMG_STATS_CACHE = {}


# --------------------------------------------------------------------------- #
# Blender 3.x / 4.x 兼容辅助
# --------------------------------------------------------------------------- #
def _active_in(node, name):
    for s in node.inputs:
        if s.name == name and getattr(s, "enabled", True):
            return s
    for s in node.inputs:
        if s.name == name:
            return s
    return None


def _active_out(node, name):
    for s in node.outputs:
        if s.name == name and getattr(s, "enabled", True):
            return s
    for s in node.outputs:
        if s.name == name:
            return s
    return None


def _add_gn_socket(ng, name, in_out, socket_type, default=None, min_val=None, max_val=None):
    if hasattr(ng, "interface"):
        s = ng.interface.new_socket(name=name, in_out=in_out, socket_type=socket_type)
    else:
        coll = ng.inputs if in_out == 'INPUT' else ng.outputs
        s = coll.new(socket_type, name)
    if default is not None and hasattr(s, "default_value"):
        s.default_value = default
    if min_val is not None and hasattr(s, "min_value"):
        s.min_value = min_val
    if max_val is not None and hasattr(s, "max_value"):
        s.max_value = max_val
    return s


def _set_gn_mod_input(mod, ng, name, value):
    if hasattr(ng, "interface"):
        for item in ng.interface.items_tree:
            if item.item_type == 'SOCKET' and item.in_out == 'INPUT' and item.name == name:
                mod[item.identifier] = value
                return
    else:
        for inp in ng.inputs:
            if inp.name == name:
                mod[inp.identifier] = value
                return


def _get_gn_mod_input(mod, ng, name, default=None):
    if hasattr(ng, "interface"):
        for item in ng.interface.items_tree:
            if item.item_type == 'SOCKET' and item.in_out == 'INPUT' and item.name == name:
                return mod.get(item.identifier, default)
    else:
        for inp in ng.inputs:
            if inp.name == name:
                return mod.get(inp.identifier, default)
    return default


def _make_mix(nodes, data_type='RGBA', blend_type='MIX', loc=(0, 0)):
    try:
        n = nodes.new('ShaderNodeMix')
        n.location = loc
        n.data_type = data_type
        if data_type == 'RGBA':
            n.blend_type = blend_type
            fac = n.inputs[0]
            a = next((s for s in n.inputs if s.name == 'A' and s.type == 'RGBA'), n.inputs[6])
            b = next((s for s in n.inputs if s.name == 'B' and s.type == 'RGBA'), n.inputs[7])
            out = next((s for s in n.outputs if s.name == 'Result' and s.type == 'RGBA'), n.outputs[2])
        elif data_type == 'FLOAT':
            fac = n.inputs[0]
            a = next((s for s in n.inputs if s.name == 'A' and s.type == 'VALUE'), n.inputs[2])
            b = next((s for s in n.inputs if s.name == 'B' and s.type == 'VALUE'), n.inputs[3])
            out = next((s for s in n.outputs if s.name == 'Result' and s.type == 'VALUE'), n.outputs[0])
        else:
            fac = n.inputs[0]
            a = next((s for s in n.inputs if s.name == 'A' and s.type == 'VECTOR'), n.inputs[4])
            b = next((s for s in n.inputs if s.name == 'B' and s.type == 'VECTOR'), n.inputs[5])
            out = next((s for s in n.outputs if s.name == 'Result' and s.type == 'VECTOR'), n.outputs[1])
        return n, fac, a, b, out
    except Exception:
        n = nodes.new('ShaderNodeMixRGB')
        n.location = loc
        n.blend_type = blend_type
        return n, n.inputs['Fac'], n.inputs['Color1'], n.inputs['Color2'], n.outputs['Color']


def _make_sep_color(nodes, loc=(0, 0)):
    try:
        n = nodes.new('ShaderNodeSeparateColor')
        n.location = loc
        return n, n.inputs['Color'], n.outputs['Red'], n.outputs['Green'], n.outputs['Blue']
    except Exception:
        n = nodes.new('ShaderNodeSeparateRGB')
        n.location = loc
        return n, n.inputs['Image'], n.outputs['R'], n.outputs['G'], n.outputs['B']


def _make_comb_color(nodes, loc=(0, 0)):
    try:
        n = nodes.new('ShaderNodeCombineColor')
        n.location = loc
        return n, n.inputs['Red'], n.inputs['Green'], n.inputs['Blue'], n.outputs['Color']
    except Exception:
        n = nodes.new('ShaderNodeCombineRGB')
        n.location = loc
        return n, n.inputs['R'], n.inputs['G'], n.inputs['B'], n.outputs['Image']


def _load_image(base_dir, rel_path, colorspace='sRGB'):
    if not rel_path:
        return None
    full = rel_path if os.path.isabs(rel_path) else os.path.join(base_dir, rel_path)
    if not os.path.exists(full):
        return None
    abs_norm = os.path.abspath(full)
    for im in bpy.data.images:
        try:
            if os.path.abspath(bpy.path.abspath(im.filepath)) == abs_norm:
                return im
        except Exception:
            pass
    im = bpy.data.images.load(abs_norm, check_existing=True)
    try:
        im.colorspace_settings.name = colorspace
    except Exception:
        pass
    return im


def _lookup_precomputed_stats(tex_info, mats_db):
    if isinstance(tex_info, dict) and isinstance(tex_info.get("stats"), dict):
        return tex_info["stats"]
    img_stats = (mats_db or {}).get("image_stats") or {}
    if isinstance(tex_info, dict) and tex_info.get("file"):
        f = str(tex_info["file"]).replace("\\", "/")
        if f in img_stats:
            return img_stats[f]
        bn = os.path.basename(f)
        for k, v in img_stats.items():
            if k.endswith("/" + bn) or os.path.basename(k) == bn:
                return v
    return None


def _sample_image_stats(im, precomputed=None):
    """零阻塞图像统计：优先使用导出阶段写入 materials.json 的预计算 stats；兜底用 numpy foreach_get 极速跨步采样。"""
    if isinstance(precomputed, dict) and "max_a" in precomputed and "min_a" in precomputed:
        return precomputed
    if im is None:
        return {"all_zero": True, "max_a": 1.0, "min_a": 1.0, "max_rgb": 1.0}
    try:
        key = (os.path.abspath(bpy.path.abspath(im.filepath)) if im.filepath else im.name, tuple(im.size))
        if key in _IMG_STATS_CACHE:
            return _IMG_STATS_CACHE[key]
        w, h = int(im.size[0]), int(im.size[1])
        total = w * h * 4
        if total < 4:
            return {"all_zero": True, "max_a": 1.0, "min_a": 1.0, "max_rgb": 1.0}
        try:
            import numpy as np
            buf = np.empty(total, dtype=np.float32)
            im.pixels.foreach_get(buf)
            arr = buf.reshape(-1, 4)
            step = max(1, len(arr) // 4096)
            sub = arr[::step]
            max_rgb = float(sub[:, :3].max()) if len(sub) else 0.0
            max_a = float(sub[:, 3].max()) if len(sub) else 1.0
            min_a = float(sub[:, 3].min()) if len(sub) else 1.0
        except Exception:
            px = im.pixels
            step = max(1, (total // 4) // 2048) * 4
            max_rgb = 0.0
            max_a = 0.0
            min_a = 1.0
            for i in range(0, total, step):
                r, g, b, a = px[i], px[i + 1], px[i + 2], px[i + 3]
                if r > max_rgb:
                    max_rgb = r
                if g > max_rgb:
                    max_rgb = g
                if b > max_rgb:
                    max_rgb = b
                if a > max_a:
                    max_a = a
                if a < min_a:
                    min_a = a
        res = {
            "all_zero": (max_rgb < 0.004 and max_a < 0.004),
            "max_rgb": float(max_rgb),
            "max_a": float(max_a),
            "min_a": float(min_a),
        }
        _IMG_STATS_CACHE[key] = res
        return res
    except Exception:
        return {"all_zero": False, "max_rgb": 1.0, "max_a": 1.0, "min_a": 1.0}


def _merge_material_fur_cfg(fur_cfg, mat_name, mat_info=None):
    """合并全局 shellfur_config.json、in_game_preset 与单材质 material_overrides，还原游戏内原始毛发配置。"""
    merged = dict(fur_cfg or {})
    preset = (fur_cfg or {}).get("in_game_preset") or {}
    prefer_ingame = merged.get("prefer_in_game", True)
    for k, v in preset.items():
        if v is None:
            continue
        if k == "layers" and merged.get("layers_explicit"):
            continue
        if k == "length" and merged.get("length_explicit"):
            continue
        if prefer_ingame or k not in merged:
            merged[k] = v
    overrides = (fur_cfg or {}).get("material_overrides") or {}
    mo = overrides.get(mat_name)
    if isinstance(mo, dict):
        for k, v in mo.items():
            if v is not None:
                merged[k] = v
    return merged


def _pick_tex(tex_map, names):
    for nm in names:
        if nm in tex_map and tex_map[nm].get("file"):
            return nm, tex_map[nm]
    lower = {k.lower(): (k, v) for k, v in tex_map.items() if v.get("file")}
    for nm in names:
        if nm.lower() in lower:
            return lower[nm.lower()]
    return None, None


def _pick_float(floats, names, default=None):
    for nm in names:
        if nm in floats:
            return floats[nm]
    lower = {k.lower(): v for k, v in floats.items()}
    for nm in names:
        if nm.lower() in lower:
            return lower[nm.lower()]
    return default


def _pick_color(colors, names, default=None):
    for nm in names:
        if nm in colors:
            return colors[nm]
    lower = {k.lower(): v for k, v in colors.items()}
    for nm in names:
        if nm.lower() in lower:
            return lower[nm.lower()]
    return default


def _make_uv_tex_node(nodes, links, uv_out, base_dir, tex_info, label, loc, colorspace='sRGB'):
    """创建 Mapping(含 Unity Scale/Offset -> Blender V-down 转换) + Image Texture 节点。"""
    sx, sy = tex_info.get("scale", [1.0, 1.0])
    ox, oy = tex_info.get("offset", [0.0, 0.0])
    mp = nodes.new('ShaderNodeMapping')
    mp.label = f"{label}_Mapping"
    mp.location = (loc[0] - 220, loc[1])
    mp.vector_type = 'POINT'
    mp.inputs['Location'].default_value = (ox, 1.0 - sy - oy, 0.0)
    mp.inputs['Scale'].default_value = (sx, sy, 1.0)
    links.new(uv_out, mp.inputs['Vector'])

    tx = nodes.new('ShaderNodeTexImage')
    tx.label = label
    tx.location = loc
    im = _load_image(base_dir, tex_info.get("file"), colorspace=colorspace)
    if im is not None:
        tx.image = im
    wrap_u = tex_info.get("wrap_u", 0)
    tx.extension = 'EXTEND' if wrap_u == 1 else 'REPEAT'
    links.new(mp.outputs['Vector'], tx.inputs['Vector'])
    return tx, mp


# --------------------------------------------------------------------------- #
# 贴图文件名智能识别与子材质槽位匹配（兼容 .uab 导出与手选贴图文件夹）
# --------------------------------------------------------------------------- #
TEX_EXTS = (".png", ".tga", ".jpg", ".jpeg", ".dds", ".exr", ".tif", ".tiff", ".bmp")
QUALIFIER_TOKENS = ("darkshiny", "whiteshiny", "blackshiny", "clearcrystal", "crystal", "shiny", "glass")
PART_TOKENS = ("body", "eye", "tail", "head", "wing", "horn", "ear", "hair", "face", "cloth", "acc")


def _clean_tex_stem(filename):
    stem = os.path.splitext(os.path.basename(filename))[0]
    # 剥离上传或缓存带有的 6~10 位十六进制哈希后缀（如 _07f803f0）及 _LODx
    stem = re.sub(r"_[0-9a-fA-F]{6,10}$", "", stem)
    stem = re.sub(r"_LOD\d+$", "", stem, flags=re.I)
    return stem


def _parse_tex_filename(filename):
    stem = _clean_tex_stem(filename)
    lower = stem.lower()
    role = None
    core = stem

    role_patterns = [
        ("PARALLAX", r"(?:_ClearCrystalParallaxMap(?:_C)?|_ParallaxMap(?:_C)?|_Parallax(?:_C)?)$"),
        ("COATMASK", r"(?:_CoatMask|_ClearCoatMask|_Coat)$"),
        ("MOHR", r"(?:_MOHR|_MaskMap|_PBRMaskMap|_ORM)$"),
        ("CA", r"(?:_CA|_Albedo|_BaseColor|_BaseMap|_Diffuse|_MainTex|_D|_C)$"),
        ("N", r"(?:_N|_Normal|_NormalMap|_Norm|_BumpMap|_Bump)$"),
        ("F", r"(?:_F|_FurMap|_FurNoiseMap|_FurMask|_Fur)$"),
        ("E", r"(?:_E|_Emissive|_Emission|_EmissionMap)$"),
        ("TW", r"(?:_TW|_Thickness|_Translucency|_Subsurface)$"),
    ]
    for rname, pat in role_patterns:
        m = re.search(pat, stem, re.I)
        if m:
            role = rname
            core = stem[:m.start()]
            break

    stem_low = stem.lower()
    core_low = core.lower()
    qualifiers = {q for q in QUALIFIER_TOKENS if q in stem_low}
    if "darkshiny" in qualifiers or "whiteshiny" in qualifiers or "blackshiny" in qualifiers:
        qualifiers.discard("shiny")
    if "clearcrystal" in qualifiers:
        qualifiers.discard("crystal")

    parts = {p for p in PART_TOKENS if re.search(rf"(?:^|_){p}(?:\d|_|$)", core_low)}
    slot_num = None
    ms = re.search(r"(?:_|^)(?:eye|body|part|mat)?0*(\d+)[a-z]?$", core_low)
    if ms:
        slot_num = int(ms.group(1))
    else:
        ms2 = re.search(r"_0*(\d+)[a-z]?(?:_|$)", core_low)
        if ms2:
            slot_num = int(ms2.group(1))

    toks = {t for t in re.split(r"[_\-\s]+", core_low) if t and t not in ("t", "m", "mi")}
    return {
        "stem": stem,
        "core": core_low,
        "role": role,
        "qualifiers": qualifiers,
        "parts": parts,
        "slot_num": slot_num,
        "tokens": toks,
    }


def _parse_mat_identity(mat_name, obj_hint=""):
    comb = f"{obj_hint}_{mat_name}" if obj_hint else mat_name
    low = comb.lower()
    mlow = mat_name.lower()
    qualifiers = {q for q in QUALIFIER_TOKENS if q in mlow}
    if "darkshiny" in qualifiers or "whiteshiny" in qualifiers or "blackshiny" in qualifiers:
        qualifiers.discard("shiny")
    if "clearcrystal" in qualifiers:
        qualifiers.discard("crystal")

    parts = {p for p in PART_TOKENS if re.search(rf"(?:^|_){p}(?:\d|_|$)", low)}
    slot_num = None
    ms = re.search(r"(?:_|^)(?:eye|body|part|mat)?0*(\d+)[a-z]?$", mlow)
    if ms:
        slot_num = int(ms.group(1))
        # 处理 Body_mat00 -> 1 (01a), Body_mat01 -> 2 (02a) 的 0 起始编号
        if "mat" in mlow and slot_num >= 0 and re.search(r"mat0*\d+$", mlow):
            slot_num += 1
    else:
        ms2 = re.search(r"_0*(\d+)[a-z]?(?:_|$)", mlow)
        if ms2:
            slot_num = int(ms2.group(1))
    toks = {t for t in re.split(r"[_\-\s]+", mlow) if t and t not in ("m", "mi", "mat")}
    return {
        "mlow": mlow,
        "qualifiers": qualifiers,
        "parts": parts,
        "slot_num": slot_num,
        "tokens": toks,
    }


def _extract_char_id(text):
    if not text:
        return None
    m = re.search(r"(?:^|[_\-/])([a-z]+_\d+)(?!\d)", str(text).lower())
    return m.group(1) if m else None


def _collect_texture_pool(base_dir, mats_db, fur_cfg):
    dirs = []
    for cand in [
        fur_cfg.get("tex_dir"),
        USER_TEX_DIR,
        os.path.join(base_dir, "textures"),
        base_dir,
        os.path.join(os.path.dirname(base_dir), "textures"),
    ]:
        if cand and os.path.isdir(cand):
            ap = os.path.abspath(cand)
            if ap not in dirs:
                dirs.append(ap)

    target_cid = _extract_char_id((mats_db or {}).get("character", ""))
    seen_files = set()
    pool = []

    def _add_entry(filepath, info_extra=None):
        ap = os.path.abspath(filepath if os.path.isabs(filepath) else os.path.join(base_dir, filepath))
        if not os.path.isfile(ap) or ap in seen_files:
            return
        seen_files.add(ap)
        meta = _parse_tex_filename(ap)
        if not meta["role"]:
            return
        # 严格过滤 UI 图标或不同角色编号的散落贴图（例如拒绝 T_Parmon_105XX 混入 Parmon_10583）
        fn_low = os.path.basename(ap).lower()
        if fn_low.startswith(("ui_img_", "ui_", "icon_", "thumb_")):
            return
        item_cid = _extract_char_id(meta["stem"])
        entry = {
            "file": ap,
            "char_id": item_cid,
            "scale": (info_extra or {}).get("scale", [1.0, 1.0]),
            "offset": (info_extra or {}).get("offset", [0.0, 0.0]),
            "wrap_u": (info_extra or {}).get("wrap_u", 0),
            "wrap_v": (info_extra or {}).get("wrap_v", 0),
            **meta,
        }
        pool.append(entry)

    for rel in (mats_db or {}).get("texture_pool", []):
        if isinstance(rel, dict):
            _add_entry(rel.get("file", ""), rel)
        elif isinstance(rel, str):
            _add_entry(rel)

    for d in dirs:
        try:
            for fn in sorted(os.listdir(d)):
                if fn.lower().endswith(TEX_EXTS):
                    _add_entry(os.path.join(d, fn))
        except Exception:
            pass

    # 若贴图池包含当前角色专属编号的贴图，剔除其他不同角色编号的无关贴图
    if target_cid:
        exact = [e for e in pool if e.get("char_id") in (None, target_cid)]
        if any(e.get("char_id") == target_cid for e in exact):
            pool = exact
    return pool


def _match_textures_for_material(mat_name, tex_pool, obj_hint="", target_char_id=None):
    if not tex_pool:
        return {}
    mi = _parse_mat_identity(mat_name, obj_hint)
    mat_cid = _extract_char_id(mat_name) or target_char_id
    matched = {}
    roles = ("CA", "MOHR", "N", "F", "E", "COATMASK", "TW", "PARALLAX")
    for role in roles:
        best_sc = -1e9
        best_item = None
        for item in tex_pool:
            if item["role"] != role:
                continue
            item_cid = item.get("char_id")
            if mat_cid and item_cid and item_cid != mat_cid:
                continue
            # 1) 部位互斥（Eye vs Body 不得跨界配对）
            if mi["parts"] and item["parts"] and not (mi["parts"] & item["parts"]):
                continue
            # 2) 变体修饰符检查（DarkShiny / WhiteShiny / BlackShiny / ClearCrystal）
            mq = mi["qualifiers"]
            tq = item["qualifiers"]
            strict_role = role in ("F", "MOHR", "COATMASK", "TW", "PARALLAX")
            if mq != tq:
                if mq and tq:
                    continue
                if tq and not mq:
                    continue
                if ("clearcrystal" in mq or "crystal" in mq):
                    continue
                # 当材质带 DarkShiny 等且缺失自己 CA/N 时，仅允许同槽位(非 F/MOHR)轻量兜底；Eye_DarkShiny 已有专属 CA 不会命中此分支
                if mq and not tq and strict_role:
                    continue

            sc = 10.0
            if mat_cid and item_cid == mat_cid:
                sc += 180.0
            if mq == tq and mq:
                sc += 250.0
            elif mq == tq:
                sc += 60.0
            if mi["parts"] and item["parts"] and (mi["parts"] & item["parts"]):
                sc += 120.0
            if mi["slot_num"] is not None and item["slot_num"] is not None:
                if mi["slot_num"] == item["slot_num"]:
                    sc += 110.0
                else:
                    if role in ("F", "COATMASK", "TW", "PARALLAX"):
                        continue
                    if strict_role and not ("eye" in mi["parts"] and item["slot_num"] == 1):
                        continue
                    sc -= 40.0
            overlap = len(mi["tokens"] & item["tokens"])
            sc += overlap * 25.0
            if item["core"] and item["core"] in mi["mlow"]:
                sc += 90.0
            # 优先使用无额外十六进制哈希的原始导出文件名
            if not re.search(r"_[0-9a-f]{6,10}\.", os.path.basename(item["file"]), re.I):
                sc += 5.0
            if sc > best_sc:
                best_sc = sc
                best_item = item
        if best_item is not None and best_sc >= 80.0:
            matched[role] = best_item
    return matched


def _classify_material_archetype(mat_name, role_tex, mat_info, fur_cfg, mats_db=None):
    mlow = mat_name.lower()
    extra_pats = fur_cfg.get("fur_materials") or []
    for p in extra_pats:
        if p and re.search(p, mat_name, re.I):
            return "fur"
    if "PARALLAX" in role_tex or re.search(r"(clearcrystal|crystal|parallax)", mlow):
        return "crystal"
    if re.search(r"(?:^|[_\-\s])(eye|pupil|cornea|iris)(?:$|[_\-\s0-9])", mlow) or re.search(r"^eye\d+", mlow):
        if "F" in role_tex:
            return "fur"
        return "eye"
    if re.search(r"(darkshiny|whiteshiny|blackshiny|shiny|metallic|bead|gem|hoof|horn)", mlow):
        if "F" in role_tex:
            return "fur"
        return "shiny"
    # 检测 Alpha 裁剪面片（如狐狸颊毛/胸毛簇卡、02a 叶片等）：禁止挤出 Shell Fur，强制走 Alpha 透明裁剪
    tex_envs = (mat_info or {}).get("tex_envs", {})
    _, ca_ti = _pick_tex(tex_envs, ["_MainTex", "_BaseMap", "_BaseColorMap", "_AlbedoMap", "_DiffuseTex", "_ColorMap", "_CA"])
    if not ca_ti and "CA" in role_tex:
        ca_ti = role_tex["CA"]
    ca_stats = _lookup_precomputed_stats(ca_ti, mats_db) if ca_ti else None
    if not ca_stats and ca_ti and ca_ti.get("file"):
        im_tmp = _load_image(os.path.dirname(ca_ti["file"]) if os.path.isabs(ca_ti["file"]) else "", ca_ti["file"], 'sRGB')
        if im_tmp is not None:
            ca_stats = _sample_image_stats(im_tmp, None)
    kws_l = {str(k).lower() for k in (mat_info or {}).get("shader_keywords", [])}
    has_alpha_cutout = bool(
        (ca_stats and float(ca_stats.get("min_a", 1.0)) < 0.90 and float(ca_stats.get("max_a", 1.0)) > 0.15)
        or "_alphatest_on" in kws_l
        or "_alphaclip" in kws_l
        or "alphatest" in kws_l
    )
    if "TW" in role_tex or "COATMASK" in role_tex or re.search(r"(?:_|^)(02[a-z]?|leaf|leaves|petal|flower|vine|tuft|card|whisker|ruff)(?:_|$)", mlow):
        if "F" in role_tex and not has_alpha_cutout:
            return "fur"
        return "foliage"
    if has_alpha_cutout and "F" not in role_tex:
        return "foliage"
    if "F" in role_tex:
        return "fur"
    if mat_info and mat_info.get("is_fur"):
        return "fur"
    if re.search(r"(?:^|[_\-\s])(fur|shell|hair|fluff|wool|plush|furry|feather)(?:$|[_\-\s0-9])", mlow):
        return "fur"
    return "standard"


# --------------------------------------------------------------------------- #
# 专用 NodeGroups：
#   1) NG_Normal_BR_Swizzle : Separate Color -> Combine Color(R=B, G=G, B=R)
#   2) NG_MOHR_Unpack       : R=Metallic, G=AO, B=Height, A=Roughness
#   3) NG_Fur_F_Channel_Switcher : *_F RGBA 通道可视化切换与预览组
#   4) NG_Parallax_UV       : ClearCrystal 视差 UV 偏移组
# --------------------------------------------------------------------------- #
def _build_channel_selector(nodes, links, ch_sockets, idx_socket, loc_x, loc_y, label_prefix):
    """根据浮点索引 (0=R, 1=G, 2=B, 3=A) 在节点树中无缝路由选中通道。"""
    acc_sock = None
    for k, ch_s in enumerate(ch_sockets):
        sub = nodes.new('ShaderNodeMath')
        sub.operation = 'SUBTRACT'
        sub.location = (loc_x, loc_y - k * 140)
        sub.label = f"{label_prefix}_Diff_{k}"
        links.new(idx_socket, sub.inputs[0])
        sub.inputs[1].default_value = float(k)

        ab = nodes.new('ShaderNodeMath')
        ab.operation = 'ABSOLUTE'
        ab.location = (loc_x + 160, loc_y - k * 140)
        links.new(sub.outputs['Value'], ab.inputs[0])

        lt = nodes.new('ShaderNodeMath')
        lt.operation = 'LESS_THAN'
        lt.location = (loc_x + 320, loc_y - k * 140)
        links.new(ab.outputs['Value'], lt.inputs[0])
        lt.inputs[1].default_value = 0.5

        mul = nodes.new('ShaderNodeMath')
        mul.operation = 'MULTIPLY'
        mul.location = (loc_x + 480, loc_y - k * 140)
        links.new(ch_s, mul.inputs[0])
        links.new(lt.outputs['Value'], mul.inputs[1])

        if acc_sock is None:
            acc_sock = mul.outputs['Value']
        else:
            add = nodes.new('ShaderNodeMath')
            add.operation = 'ADD'
            add.location = (loc_x + 650, loc_y - k * 140)
            links.new(acc_sock, add.inputs[0])
            links.new(mul.outputs['Value'], add.inputs[1])
            acc_sock = add.outputs['Value']
    return acc_sock


def get_or_create_normal_swizzle_ng():
    name = "NG_Normal_BR_Swizzle"
    if name in bpy.data.node_groups:
        return bpy.data.node_groups[name]
    ng = bpy.data.node_groups.new(name=name, type='ShaderNodeTree')
    _add_gn_socket(ng, "Color", 'INPUT', 'NodeSocketColor', default=(0.5, 0.5, 1.0, 1.0))
    _add_gn_socket(ng, "Swizzle R=B B=R", 'INPUT', 'NodeSocketFloat', default=1.0, min_val=0.0, max_val=1.0)
    _add_gn_socket(ng, "Color", 'OUTPUT', 'NodeSocketColor')

    nodes, links = ng.nodes, ng.links
    gin = nodes.new('NodeGroupInput')
    gin.location = (-500, 0)
    gout = nodes.new('NodeGroupOutput')
    gout.location = (450, 0)

    sep, sep_in, s_r, s_g, s_b = _make_sep_color(nodes, (-260, -80))
    links.new(gin.outputs['Color'], sep_in)

    comb, c_r, c_g, c_b, comb_out = _make_comb_color(nodes, (-20, -80))
    # 用户确认 Unity 法线规则: 红 = 蓝, 绿 = 绿, 蓝 = 红
    links.new(s_b, c_r)
    links.new(s_g, c_g)
    links.new(s_r, c_b)

    _, m_fac, m_a, m_b, m_out = _make_mix(nodes, 'RGBA', 'MIX', (220, 40))
    links.new(gin.outputs['Swizzle R=B B=R'], m_fac)
    links.new(gin.outputs['Color'], m_a)
    links.new(comb_out, m_b)
    links.new(m_out, gout.inputs['Color'])
    return ng


def get_or_create_mohr_ng():
    name = "NG_MOHR_Unpack"
    if name in bpy.data.node_groups:
        return bpy.data.node_groups[name]
    ng = bpy.data.node_groups.new(name=name, type='ShaderNodeTree')
    _add_gn_socket(ng, "MOHR Color", 'INPUT', 'NodeSocketColor', default=(0.0, 1.0, 0.0, 1.0))
    _add_gn_socket(ng, "MOHR Alpha", 'INPUT', 'NodeSocketFloat', default=0.5, min_val=0.0, max_val=1.0)
    _add_gn_socket(ng, "Invert Alpha (Smoothness)", 'INPUT', 'NodeSocketFloat', default=0.0, min_val=0.0, max_val=1.0)
    _add_gn_socket(ng, "AO Strength", 'INPUT', 'NodeSocketFloat', default=0.85, min_val=0.0, max_val=1.0)
    _add_gn_socket(ng, "Metallic", 'OUTPUT', 'NodeSocketFloat')
    _add_gn_socket(ng, "AO", 'OUTPUT', 'NodeSocketFloat')
    _add_gn_socket(ng, "Height", 'OUTPUT', 'NodeSocketFloat')
    _add_gn_socket(ng, "Roughness", 'OUTPUT', 'NodeSocketFloat')

    nodes, links = ng.nodes, ng.links
    gin = nodes.new('NodeGroupInput')
    gin.location = (-500, 0)
    gout = nodes.new('NodeGroupOutput')
    gout.location = (380, 0)

    sep, sep_in, s_r, s_g, s_b = _make_sep_color(nodes, (-220, 120))
    links.new(gin.outputs['MOHR Color'], sep_in)
    links.new(s_r, gout.inputs['Metallic'])
    links.new(s_b, gout.inputs['Height'])

    _, ao_fac, ao_a, ao_b, ao_out = _make_mix(nodes, 'FLOAT', 'MIX', (80, 100))
    links.new(gin.outputs['AO Strength'], ao_fac)
    ao_a.default_value = 1.0
    links.new(s_g, ao_b)
    links.new(ao_out, gout.inputs['AO'])

    inv = nodes.new('ShaderNodeMath')
    inv.operation = 'SUBTRACT'
    inv.location = (-160, -160)
    inv.inputs[0].default_value = 1.0
    links.new(gin.outputs['MOHR Alpha'], inv.inputs[1])

    _, r_fac, r_a, r_b, r_out = _make_mix(nodes, 'FLOAT', 'MIX', (80, -140))
    links.new(gin.outputs['Invert Alpha (Smoothness)'], r_fac)
    links.new(gin.outputs['MOHR Alpha'], r_a)
    links.new(inv.outputs['Value'], r_b)
    links.new(r_out, gout.inputs['Roughness'])
    return ng


def get_or_create_fur_f_switcher_ng():
    name = "NG_Fur_F_Channel_Switcher"
    if name in bpy.data.node_groups:
        return bpy.data.node_groups[name]
    ng = bpy.data.node_groups.new(name=name, type='ShaderNodeTree')
    _add_gn_socket(ng, "F Color", 'INPUT', 'NodeSocketColor', default=(0.5, 0.5, 1.0, 1.0))
    _add_gn_socket(ng, "F Alpha", 'INPUT', 'NodeSocketFloat', default=1.0, min_val=0.0, max_val=1.0)
    _add_gn_socket(ng, "Alpha Gain", 'INPUT', 'NodeSocketFloat', default=1.0, min_val=0.1, max_val=20.0)
    _add_gn_socket(ng, "Mask Ch (0R 1G 2B 3A)", 'INPUT', 'NodeSocketFloat', default=3.0, min_val=0.0, max_val=3.0)
    _add_gn_socket(ng, "Length Ch (0R 1G 2B 3A)", 'INPUT', 'NodeSocketFloat', default=3.0, min_val=0.0, max_val=3.0)
    _add_gn_socket(ng, "Strand Ch (0R 1G 2B 3A)", 'INPUT', 'NodeSocketFloat', default=3.0, min_val=0.0, max_val=3.0)
    _add_gn_socket(ng, "AO Ch (0R 1G 2B 3A)", 'INPUT', 'NodeSocketFloat', default=3.0, min_val=0.0, max_val=3.0)
    _add_gn_socket(ng, "Invert Mask", 'INPUT', 'NodeSocketFloat', default=0.0, min_val=0.0, max_val=1.0)
    _add_gn_socket(ng, "Mask Threshold", 'INPUT', 'NodeSocketFloat', default=0.06, min_val=0.0, max_val=1.0)
    _add_gn_socket(ng, "Mask Ramp Max", 'INPUT', 'NodeSocketFloat', default=0.18, min_val=0.05, max_val=1.0)
    _add_gn_socket(ng, "Preview Mode (0Off 1R 2G 3B 4A)", 'INPUT', 'NodeSocketFloat', default=0.0, min_val=0.0, max_val=4.0)

    _add_gn_socket(ng, "Mask", 'OUTPUT', 'NodeSocketFloat')
    _add_gn_socket(ng, "Length", 'OUTPUT', 'NodeSocketFloat')
    _add_gn_socket(ng, "Strand", 'OUTPUT', 'NodeSocketFloat')
    _add_gn_socket(ng, "AO", 'OUTPUT', 'NodeSocketFloat')
    _add_gn_socket(ng, "Flow Vector", 'OUTPUT', 'NodeSocketVector')
    _add_gn_socket(ng, "Preview Color", 'OUTPUT', 'NodeSocketColor')
    _add_gn_socket(ng, "Preview Active", 'OUTPUT', 'NodeSocketFloat')

    nodes, links = ng.nodes, ng.links
    gin = nodes.new('NodeGroupInput')
    gin.location = (-1080, 0)
    gout = nodes.new('NodeGroupOutput')
    gout.location = (1220, 0)

    sep, sep_in, s_r, s_g, s_b = _make_sep_color(nodes, (-820, 120))
    links.new(gin.outputs['F Color'], sep_in)

    # *_F.Alpha 在部分 Unity 毛发贴图中编码在 0~0.14 量程，先乘 Alpha Gain 再限幅到 [0,1]
    a_mul = nodes.new('ShaderNodeMath')
    a_mul.operation = 'MULTIPLY'
    a_mul.use_clamp = True
    a_mul.location = (-620, -140)
    links.new(gin.outputs['F Alpha'], a_mul.inputs[0])
    links.new(gin.outputs['Alpha Gain'], a_mul.inputs[1])

    chs = [s_r, s_g, s_b, a_mul.outputs['Value']]

    # 解析 *_F.(R,G) 切线梳毛流向矢量: flow = ((R - 0.5)*2, (G - 0.5)*2, 0)
    comb_rgb, cb_r, cb_g, cb_b, cb_out = _make_comb_color(nodes, (-620, 340))
    links.new(s_r, cb_r)
    links.new(s_g, cb_g)
    cb_b.default_value = 0.5
    fl_sub = nodes.new('ShaderNodeVectorMath')
    fl_sub.operation = 'SUBTRACT'
    fl_sub.location = (-400, 340)
    links.new(cb_out, fl_sub.inputs[0])
    fl_sub.inputs[1].default_value = (0.5, 0.5, 0.5)
    fl_mul = nodes.new('ShaderNodeVectorMath')
    fl_mul.operation = 'SCALE'
    fl_mul.location = (-180, 340)
    links.new(fl_sub.outputs['Vector'], fl_mul.inputs[0])
    _active_in(fl_mul, 'Scale').default_value = 2.0
    links.new(fl_mul.outputs['Vector'], gout.inputs['Flow Vector'])

    mask_raw = _build_channel_selector(nodes, links, chs, gin.outputs['Mask Ch (0R 1G 2B 3A)'], -400, 960, "Mask")
    inv_m = nodes.new('ShaderNodeMath')
    inv_m.operation = 'SUBTRACT'
    inv_m.location = (380, 820)
    inv_m.inputs[0].default_value = 1.0
    links.new(mask_raw, inv_m.inputs[1])
    _, mf_fac, mf_a, mf_b, mf_out = _make_mix(nodes, 'FLOAT', 'MIX', (560, 880))
    links.new(gin.outputs['Invert Mask'], mf_fac)
    links.new(mask_raw, mf_a)
    links.new(inv_m.outputs['Value'], mf_b)

    mr_mask = nodes.new('ShaderNodeMapRange')
    mr_mask.location = (760, 880)
    mr_mask.clamp = True
    links.new(mf_out, mr_mask.inputs['Value'])
    links.new(gin.outputs['Mask Threshold'], mr_mask.inputs['From Min'])
    links.new(gin.outputs['Mask Ramp Max'], mr_mask.inputs['From Max'])
    mr_mask.inputs['To Min'].default_value = 0.0
    mr_mask.inputs['To Max'].default_value = 1.0
    links.new(mr_mask.outputs['Result'], gout.inputs['Mask'])

    len_raw = _build_channel_selector(nodes, links, chs, gin.outputs['Length Ch (0R 1G 2B 3A)'], -400, 120, "Len")
    links.new(len_raw, gout.inputs['Length'])

    str_raw = _build_channel_selector(nodes, links, chs, gin.outputs['Strand Ch (0R 1G 2B 3A)'], -400, -480, "Str")
    links.new(str_raw, gout.inputs['Strand'])

    ao_raw = _build_channel_selector(nodes, links, chs, gin.outputs['AO Ch (0R 1G 2B 3A)'], -400, -1080, "AO")
    links.new(ao_raw, gout.inputs['AO'])

    # Preview Mode (0=Off, 1=R, 2=G, 3=B, 4=A) -> 转 0..3 索引 + 开关
    prev_sub = nodes.new('ShaderNodeMath')
    prev_sub.operation = 'SUBTRACT'
    prev_sub.location = (-600, -1620)
    links.new(gin.outputs['Preview Mode (0Off 1R 2G 3B 4A)'], prev_sub.inputs[0])
    prev_sub.inputs[1].default_value = 1.0

    prev_val = _build_channel_selector(nodes, links, chs, prev_sub.outputs['Value'], -400, -1620, "Prev")
    comb_p, cp_r, cp_g, cp_b, cp_out = _make_comb_color(nodes, (560, -1620))
    links.new(prev_val, cp_r)
    links.new(prev_val, cp_g)
    links.new(prev_val, cp_b)
    links.new(cp_out, gout.inputs['Preview Color'])

    prev_on = nodes.new('ShaderNodeMath')
    prev_on.operation = 'GREATER_THAN'
    prev_on.location = (560, -1790)
    links.new(gin.outputs['Preview Mode (0Off 1R 2G 3B 4A)'], prev_on.inputs[0])
    prev_on.inputs[1].default_value = 0.5
    links.new(prev_on.outputs['Value'], gout.inputs['Preview Active'])
    return ng


def get_or_create_parallax_uv_ng():
    name = "NG_Parallax_UV"
    if name in bpy.data.node_groups:
        return bpy.data.node_groups[name]
    ng = bpy.data.node_groups.new(name=name, type='ShaderNodeTree')
    _add_gn_socket(ng, "UV", 'INPUT', 'NodeSocketVector', default=(0.0, 0.0, 0.0))
    _add_gn_socket(ng, "Height", 'INPUT', 'NodeSocketFloat', default=0.5, min_val=0.0, max_val=1.0)
    _add_gn_socket(ng, "Depth", 'INPUT', 'NodeSocketFloat', default=0.035, min_val=-0.25, max_val=0.25)
    _add_gn_socket(ng, "UV", 'OUTPUT', 'NodeSocketVector')

    nodes, links = ng.nodes, ng.links
    gin = nodes.new('NodeGroupInput')
    gin.location = (-650, 0)
    gout = nodes.new('NodeGroupOutput')
    gout.location = (420, 0)

    geom = nodes.new('ShaderNodeNewGeometry')
    geom.location = (-650, -240)
    vtr = nodes.new('ShaderNodeVectorTransform')
    vtr.vector_type = 'VECTOR'
    vtr.convert_from = 'WORLD'
    vtr.convert_to = 'OBJECT'
    vtr.location = (-440, -240)
    links.new(geom.outputs['Incoming'], vtr.inputs['Vector'])

    h_cen = nodes.new('ShaderNodeMath')
    h_cen.operation = 'SUBTRACT'
    h_cen.location = (-440, -40)
    links.new(gin.outputs['Height'], h_cen.inputs[0])
    h_cen.inputs[1].default_value = 0.5

    h_dep = nodes.new('ShaderNodeMath')
    h_dep.operation = 'MULTIPLY'
    h_dep.location = (-240, -40)
    links.new(h_cen.outputs['Value'], h_dep.inputs[0])
    links.new(gin.outputs['Depth'], h_dep.inputs[1])

    v_sc = nodes.new('ShaderNodeVectorMath')
    v_sc.operation = 'SCALE'
    v_sc.location = (-60, -180)
    links.new(vtr.outputs['Vector'], v_sc.inputs[0])
    links.new(h_dep.outputs['Value'], _active_in(v_sc, 'Scale'))

    v_add = nodes.new('ShaderNodeVectorMath')
    v_add.operation = 'ADD'
    v_add.location = (180, 0)
    links.new(gin.outputs['UV'], v_add.inputs[0])
    links.new(v_sc.outputs['Vector'], v_add.inputs[1])
    links.new(v_add.outputs['Vector'], gout.inputs['UV'])
    return ng


# --------------------------------------------------------------------------- #
# 材质与纹理映射节点树构建（全分型材质 + Shell Fur 分层着色器）
# --------------------------------------------------------------------------- #
def build_material_nodes(mat, mat_info, base_dir, fur_cfg, apply_fur, role_tex=None, archetype="standard", mats_db=None):
    mat.use_nodes = True
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    nodes.clear()
    m_cfg = _merge_material_fur_cfg(fur_cfg, mat.name, mat_info)

    out = nodes.new('ShaderNodeOutputMaterial')
    out.location = (1250, 0)
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.location = (760, 0)
    links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])

    f_uv = nodes.new('NodeFrame')
    f_uv.label = f"01. UV & Textures [{archetype}]"
    f_pbr = nodes.new('NodeFrame')
    f_pbr.label = "02. PBR / Normal(R=B,G=G,B=R) / Special Maps"

    tex_coord = nodes.new('ShaderNodeTexCoord')
    tex_coord.location = (-1350, 120)
    tex_coord.parent = f_uv
    uv_main = tex_coord.outputs['UV']

    tex_envs = (mat_info or {}).get("tex_envs", {})
    floats = (mat_info or {}).get("floats", {})
    colors = (mat_info or {}).get("colors", {})
    role_tex = role_tex or {}

    def _resolve_tex_slot(unity_names, fallback_role):
        _, ti = _pick_tex(tex_envs, unity_names)
        if ti:
            return ti
        if fallback_role and fallback_role in role_tex:
            return role_tex[fallback_role]
        return None

    # ---- 0. ClearCrystal 视差 UV 支持 ----
    parallax_info = _resolve_tex_slot(["_ParallaxMap", "_ClearCrystalParallaxMap", "_ClearCrystalParallaxMap_C"], "PARALLAX")
    uv_crystal = uv_main
    tx_para = None
    if archetype == "crystal" and parallax_info:
        ng_para = nodes.new('ShaderNodeGroup')
        ng_para.node_tree = get_or_create_parallax_uv_ng()
        ng_para.label = "Crystal_Parallax_UV"
        ng_para.location = (-1040, 320)
        ng_para.parent = f_uv
        links.new(uv_main, ng_para.inputs['UV'])
        ng_para.inputs['Depth'].default_value = float(_pick_float(floats, ["_Parallax", "_ParallaxDepth"], 0.04))
        uv_crystal = ng_para.outputs['UV']
        tx_para, mp_para = _make_uv_tex_node(nodes, links, uv_crystal, base_dir, parallax_info, "ClearCrystal_Parallax_C", (-480, 560), 'sRGB')
        tx_para.parent = f_uv
        mp_para.parent = f_uv

    # ---- 1. Base Color (*_CA) ----
    base_tex_info = _resolve_tex_slot(["_MainTex", "_BaseMap", "_BaseColorMap", "_AlbedoMap", "_DiffuseTex", "_ColorMap", "_CA"], "CA")
    base_col = _pick_color(colors, ["_Color", "_BaseColor", "_MainColor"], None)
    if base_col is None:
        ml = mat.name.lower()
        if "blackshiny" in ml:
            base_col = [0.025, 0.025, 0.03, 1.0]
        elif "darkshiny" in ml:
            base_col = [0.075, 0.08, 0.095, 1.0]
        elif "whiteshiny" in ml:
            base_col = [0.92, 0.94, 0.96, 1.0]
        else:
            base_col = [1.0, 1.0, 1.0, 1.0]

    tx_base = None
    if base_tex_info:
        tx_base, mp_base = _make_uv_tex_node(nodes, links, uv_main, base_dir, base_tex_info, "BaseColor_CA", (-480, 300), 'sRGB')
        tx_base.parent = f_uv
        mp_base.parent = f_uv
        base_out = tx_base.outputs['Color']
        if any(abs(c - 1.0) > 1e-3 for c in base_col[:3]):
            _, _, a_in, b_in, m_out = _make_mix(nodes, 'RGBA', 'MULTIPLY', (-140, 300))
            b_in.default_value = (base_col[0], base_col[1], base_col[2], 1.0)
            links.new(base_out, a_in)
            base_out = m_out
        if tx_para is not None:
            _, p_fac, p_a, p_b, p_out = _make_mix(nodes, 'RGBA', 'MIX', (40, 420))
            p_fac.default_value = 0.65
            links.new(base_out, p_a)
            links.new(tx_para.outputs['Color'], p_b)
            base_out = p_out
    elif tx_para is not None:
        base_out = tx_para.outputs['Color']
    else:
        col_node = nodes.new('ShaderNodeRGB')
        col_node.label = "BaseColor"
        col_node.location = (-320, 300)
        col_node.outputs[0].default_value = (base_col[0], base_col[1], base_col[2], 1.0)
        base_out = col_node.outputs[0]

    # ---- 2. Normal Map (*_N -> Separate Color -> Combine Color(R=B, G=G, B=R) -> Normal Map) ----
    nrm_tex_info = _resolve_tex_slot(["_BumpMap", "_NormalMap", "_DetailNormalMap", "_N"], "N")
    if nrm_tex_info:
        tx_nrm, mp_nrm = _make_uv_tex_node(nodes, links, uv_main, base_dir, nrm_tex_info, "Normal_N", (-480, -340), 'Non-Color')
        tx_nrm.parent = f_uv
        mp_nrm.parent = f_uv

        swiz = nodes.new('ShaderNodeGroup')
        swiz.node_tree = get_or_create_normal_swizzle_ng()
        swiz.label = "Normal_BR_Swizzle (R=B,G=G,B=R)"
        swiz.location = (-100, -340)
        swiz.parent = f_pbr
        links.new(tx_nrm.outputs['Color'], swiz.inputs['Color'])
        swiz.inputs['Swizzle R=B B=R'].default_value = 1.0

        nmap = nodes.new('ShaderNodeNormalMap')
        nmap.location = (220, -340)
        nmap.parent = f_pbr
        bump_scale = _pick_float(floats, ["_BumpScale", "_NormalScale"], 1.0)
        nmap.inputs['Strength'].default_value = float(bump_scale)
        links.new(swiz.outputs['Color'], nmap.inputs['Color'])
        links.new(nmap.outputs['Normal'], bsdf.inputs['Normal'])

    # ---- 3. MOHR / Metallic-Roughness / AO（过滤全黑占位 MOHR 如 DarkShiny_01a_MOHR）----
    mohr_info = _resolve_tex_slot(["_MOHR", "_MaskMap", "_PBRMaskMap"], "MOHR")
    legacy_pbr_info = None if mohr_info else _resolve_tex_slot(["_MetallicGlossMap", "_SpecGlossMap"], None)
    mlow = mat.name.lower()
    has_leaf_maps = ("TW" in role_tex or "COATMASK" in role_tex or bool(re.search(r"(leaf|leaves|petal|flower|vine)", mlow)))
    metallic_val = float(_pick_float(floats, ["_Metallic"], 0.15 if archetype == "shiny" else 0.0))
    smooth_val = _pick_float(floats, ["_Smoothness", "_Glossiness", "_GlossMapScale"], None)
    rough_val = _pick_float(floats, ["_Roughness"], None)
    if rough_val is None:
        if archetype == "shiny":
            rough_val = 0.14
        elif archetype == "crystal":
            rough_val = 0.06
        elif archetype == "eye":
            rough_val = 0.08
        elif archetype == "foliage":
            rough_val = 0.18 if has_leaf_maps else 0.72
        else:
            rough_val = (1.0 - float(smooth_val)) if smooth_val is not None else 0.68
    bsdf.inputs['Metallic'].default_value = metallic_val
    bsdf.inputs['Roughness'].default_value = max(0.03, min(1.0, float(rough_val)))

    ao_out = None
    if mohr_info:
        tx_pbr, mp_pbr = _make_uv_tex_node(nodes, links, uv_main, base_dir, mohr_info, "PBR_MOHR", (-480, -40), 'Non-Color')
        tx_pbr.parent = f_uv
        mp_pbr.parent = f_uv
        pbr_stats = _sample_image_stats(tx_pbr.image, _lookup_precomputed_stats(mohr_info, mats_db))
        if not pbr_stats["all_zero"]:
            mohr_ng = nodes.new('ShaderNodeGroup')
            mohr_ng.node_tree = get_or_create_mohr_ng()
            mohr_ng.label = "MOHR_Unpack (R=Metal,G=AO,B=H,A=Rough)"
            mohr_ng.location = (-80, -40)
            mohr_ng.parent = f_pbr
            links.new(tx_pbr.outputs['Color'], mohr_ng.inputs['MOHR Color'])
            links.new(tx_pbr.outputs['Alpha'], mohr_ng.inputs['MOHR Alpha'])
            mohr_ng.inputs['Invert Alpha (Smoothness)'].default_value = 0.0
            mohr_ng.inputs['AO Strength'].default_value = 0.55 if apply_fur else 0.75

            links.new(mohr_ng.outputs['Metallic'], bsdf.inputs['Metallic'])
            links.new(mohr_ng.outputs['Roughness'], bsdf.inputs['Roughness'])
            ao_out = mohr_ng.outputs['AO']
    elif legacy_pbr_info:
        tx_pbr, mp_pbr = _make_uv_tex_node(nodes, links, uv_main, base_dir, legacy_pbr_info, "PBR_MetallicGloss", (-480, -40), 'Non-Color')
        tx_pbr.parent = f_uv
        mp_pbr.parent = f_uv
        sep, sep_in, s_r, _, _ = _make_sep_color(nodes, (-140, -40))
        sep.parent = f_pbr
        links.new(tx_pbr.outputs['Color'], sep_in)
        links.new(s_r, bsdf.inputs['Metallic'])
        inv_r = nodes.new('ShaderNodeMath')
        inv_r.operation = 'SUBTRACT'
        inv_r.location = (80, -80)
        inv_r.parent = f_pbr
        inv_r.inputs[0].default_value = 1.0
        links.new(tx_pbr.outputs['Alpha'], inv_r.inputs[1])
        links.new(inv_r.outputs['Value'], bsdf.inputs['Roughness'])

    if ao_out is not None:
        _, _, ao_ca, ao_cb, ao_mul_out = _make_mix(nodes, 'RGBA', 'MULTIPLY', (200, 220))
        links.new(base_out, ao_ca)
        comb_ao, cao_r, cao_g, cao_b, cao_out = _make_comb_color(nodes, (20, 140))
        comb_ao.parent = f_pbr
        links.new(ao_out, cao_r)
        links.new(ao_out, cao_g)
        links.new(ao_out, cao_b)
        links.new(cao_out, ao_cb)
        base_out = ao_mul_out

    # ---- 4. Emission (*_E) ----
    em_tex_info = _resolve_tex_slot(["_EmissionMap", "_EmissiveMap", "_E"], "E")
    em_col = _pick_color(colors, ["_EmissionColor", "_EmissiveColor"], None)
    em_sock = _active_in(bsdf, 'Emission Color') or _active_in(bsdf, 'Emission')
    if em_tex_info and em_sock is not None:
        tx_em, mp_em = _make_uv_tex_node(nodes, links, uv_main, base_dir, em_tex_info, "Emission_E", (-480, -640), 'sRGB')
        tx_em.parent = f_uv
        mp_em.parent = f_uv
        links.new(tx_em.outputs['Color'], em_sock)
        if _active_in(bsdf, 'Emission Strength'):
            _active_in(bsdf, 'Emission Strength').default_value = 0.65 if archetype == "foliage" else 1.0
    elif em_col and max(em_col[:3]) > 1e-3 and em_sock is not None:
        em_sock.default_value = (em_col[0], em_col[1], em_col[2], 1.0)
        if _active_in(bsdf, 'Emission Strength'):
            _active_in(bsdf, 'Emission Strength').default_value = 0.8

    # ---- 5. CoatMask / Clearcoat (叶片/双角 02a / 光泽表面 / 晶体 / 眼球) ----
    coat_sock = _active_in(bsdf, 'Coat Weight') or _active_in(bsdf, 'Clearcoat')
    coat_rough = _active_in(bsdf, 'Coat Roughness') or _active_in(bsdf, 'Clearcoat Roughness')
    coat_info = _resolve_tex_slot(["_CoatMask", "_ClearCoatMask", "_Coat"], "COATMASK")
    if coat_info and coat_sock is not None:
        tx_coat, mp_coat = _make_uv_tex_node(nodes, links, uv_main, base_dir, coat_info, "CoatMask", (-480, -900), 'Non-Color')
        tx_coat.parent = f_uv
        mp_coat.parent = f_uv
        links.new(tx_coat.outputs['Color'], coat_sock)
        if coat_rough is not None:
            coat_rough.default_value = 0.06
    elif archetype in ("shiny", "eye", "crystal") and coat_sock is not None:
        coat_sock.default_value = 0.9
        if coat_rough is not None:
            coat_rough.default_value = 0.04
    elif archetype == "foliage" and has_leaf_maps and coat_sock is not None:
        coat_sock.default_value = 0.75
        if coat_rough is not None:
            coat_rough.default_value = 0.07

    # ---- 6. TW (02a 叶片透光/次表面厚度) & Crystal 透射参数 ----
    tw_info = _resolve_tex_slot(["_TW", "_Thickness", "_Translucency"], "TW")
    sss_sock = _active_in(bsdf, 'Subsurface Weight') or _active_in(bsdf, 'Subsurface')
    if tw_info and sss_sock is not None:
        tx_tw, mp_tw = _make_uv_tex_node(nodes, links, uv_main, base_dir, tw_info, "Foliage_TW", (-480, -1160), 'Non-Color')
        tx_tw.parent = f_uv
        mp_tw.parent = f_uv
        sep_tw, sep_tw_in, tw_r, _, _ = _make_sep_color(nodes, (-100, -1160))
        sep_tw.parent = f_pbr
        links.new(tx_tw.outputs['Color'], sep_tw_in)
        mul_sss = nodes.new('ShaderNodeMath')
        mul_sss.operation = 'MULTIPLY'
        mul_sss.location = (180, -1160)
        mul_sss.parent = f_pbr
        links.new(tw_r, mul_sss.inputs[0])
        mul_sss.inputs[1].default_value = 0.38
        links.new(mul_sss.outputs['Value'], sss_sock)
        if _active_in(bsdf, 'Subsurface Scale'):
            _active_in(bsdf, 'Subsurface Scale').default_value = 0.025
        if _active_in(bsdf, 'Subsurface Radius'):
            _active_in(bsdf, 'Subsurface Radius').default_value = (0.35, 1.0, 0.25)

    if archetype == "crystal":
        tr_sock = _active_in(bsdf, 'Transmission Weight') or _active_in(bsdf, 'Transmission')
        if tr_sock is not None:
            tr_sock.default_value = 0.78
        if _active_in(bsdf, 'IOR'):
            _active_in(bsdf, 'IOR').default_value = 1.52

    # ---- 7. 非毛发材质到此结束（检测纹理实际 min_a < 0.96 或 _ALPHATEST_ON，修复狐狸颊毛/胸毛簇卡白底条带） ----
    if not apply_fur:
        links.new(base_out, bsdf.inputs['Base Color'])
        if archetype in ("foliage", "standard") and tx_base is not None:
            ca_stats = _sample_image_stats(tx_base.image, _lookup_precomputed_stats(base_tex_info, mats_db))
            kws_l = {str(k).lower() for k in (mat_info or {}).get("shader_keywords", [])}
            min_a = float(ca_stats.get("min_a", 1.0))
            max_a = float(ca_stats.get("max_a", 1.0))
            has_cutout = (min_a < 0.96 and max_a > 0.15) or "_alphatest_on" in kws_l or "_alphaclip" in kws_l or "alphatest" in kws_l
            if has_cutout:
                if hasattr(mat, "blend_method"):
                    mat.blend_method = 'HASHED'
                if hasattr(mat, "shadow_method"):
                    mat.shadow_method = 'NONE'
                if hasattr(mat, "alpha_threshold"):
                    mat.alpha_threshold = 0.35
                if hasattr(mat, "surface_render_method"):
                    mat.surface_render_method = 'DITHERED'
                mat.use_backface_culling = False
                links.new(tx_base.outputs['Alpha'], bsdf.inputs['Alpha'])
                if archetype == "foliage" and not has_leaf_maps:
                    sh_card = _active_in(bsdf, 'Sheen Weight') or _active_in(bsdf, 'Sheen')
                    if sh_card is not None:
                        sh_card.default_value = 0.85
                    if _active_in(bsdf, 'Sheen Roughness'):
                        _active_in(bsdf, 'Sheen Roughness').default_value = 0.35
                    if _active_in(bsdf, 'Specular IOR Level'):
                        _active_in(bsdf, 'Specular IOR Level').default_value = 0.16
                    bsdf.inputs['Roughness'].default_value = max(0.62, bsdf.inputs['Roughness'].default_value)
        return

    # ----------------------------------------------------------------------- #
    # Shell Fur 超高密丝滑细绒着色器（v4.4 对标实机游戏渲染：消除圆点斑驳与层间暗斑）：
    #   shell_factor == 0 -> 不透明底层绒毛基色 (Alpha = 1.0，或遵循卡面 Alpha)
    #   shell_factor >  0 -> 各向异性高密细丝 + Noise 破除规则孔洞 + 柔和羽化边缘 Alpha
    #                        + LightPath IsShadowRay 壳层阴影透明直通（零椒盐黑点）
    # ----------------------------------------------------------------------- #
    f_fur = nodes.new('NodeFrame')
    f_fur.label = "03. Silky Shell Fur v4.4 & *_F Channel Switcher"

    if hasattr(mat, "blend_method"):
        mat.blend_method = 'HASHED'
    if hasattr(mat, "alpha_threshold"):
        mat.alpha_threshold = 0.18
    if hasattr(mat, "shadow_method"):
        mat.shadow_method = 'NONE'
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = 'DITHERED'
    mat.use_backface_culling = False

    sheen_sock = _active_in(bsdf, 'Sheen Weight') or _active_in(bsdf, 'Sheen')
    if sheen_sock is not None:
        sheen_sock.default_value = 0.92
    if _active_in(bsdf, 'Sheen Roughness'):
        _active_in(bsdf, 'Sheen Roughness').default_value = 0.32
    if _active_in(bsdf, 'Specular IOR Level'):
        _active_in(bsdf, 'Specular IOR Level').default_value = 0.14
    sss_fur = _active_in(bsdf, 'Subsurface Weight') or _active_in(bsdf, 'Subsurface')
    if sss_fur is not None and not sss_fur.is_linked:
        sss_fur.default_value = 0.16
        if _active_in(bsdf, 'Subsurface Scale'):
            _active_in(bsdf, 'Subsurface Scale').default_value = 0.008
    bsdf.inputs['Roughness'].default_value = 0.78

    attr_sf = nodes.new('ShaderNodeAttribute')
    attr_sf.attribute_name = "shell_factor"
    attr_sf.location = (-1320, 680)
    attr_sf.parent = f_fur

    is_shell = nodes.new('ShaderNodeMath')
    is_shell.operation = 'GREATER_THAN'
    is_shell.location = (-1080, 720)
    is_shell.parent = f_fur
    links.new(attr_sf.outputs['Fac'], is_shell.inputs[0])
    is_shell.inputs[1].default_value = 0.001

    # 1) *_F 贴图解析 + 自动 Alpha 增益检测 + 2D 切线顺毛流向偏移
    f_tex_info = _resolve_tex_slot(
        ["_FurMap", "_FurNoiseMap", "_FurMask", "_FurMaskMap", "_FurLengthMap", "_FurTex", "_F"],
        "F",
    )
    f_ch_cfg = m_cfg.get("f_channels") or {}
    ch_idx_map = {"r": 0.0, "g": 1.0, "b": 2.0, "a": 3.0}
    sw_node = None
    fur_uv_src = uv_main
    fur_density = float(_pick_float(floats, ["_FurDensity", "_Density", "_FurTiling", "_NoiseScale"], m_cfg.get("density", 44.0)))
    comb_strength = float(_pick_float(floats, ["_FurComb", "_CombStrength"], m_cfg.get("comb", 0.55)))

    if f_tex_info:
        tx_f, mp_f = _make_uv_tex_node(nodes, links, uv_main, base_dir, f_tex_info, "Fur_F_Map", (-1320, 1460), 'Non-Color')
        tx_f.parent = f_fur
        mp_f.parent = f_fur

        f_stats = _sample_image_stats(tx_f.image, _lookup_precomputed_stats(f_tex_info, mats_db))
        auto_a_gain = float(m_cfg.get("alpha_gain", 1.0) or 1.0)
        if auto_a_gain <= 1.01 and 0.02 < f_stats["max_a"] < 0.30:
            auto_a_gain = min(12.0, round(0.95 / f_stats["max_a"], 2))

        sw_node = nodes.new('ShaderNodeGroup')
        sw_node.node_tree = get_or_create_fur_f_switcher_ng()
        sw_node.label = "F_Channel_Switcher"
        sw_node.location = (-960, 1420)
        sw_node.parent = f_fur
        links.new(tx_f.outputs['Color'], sw_node.inputs['F Color'])
        links.new(tx_f.outputs['Alpha'], sw_node.inputs['F Alpha'])
        sw_node.inputs['Alpha Gain'].default_value = auto_a_gain
        sw_node.inputs['Mask Ch (0R 1G 2B 3A)'].default_value = ch_idx_map.get(str(f_ch_cfg.get("mask", "a")).lower(), 3.0)
        sw_node.inputs['Length Ch (0R 1G 2B 3A)'].default_value = ch_idx_map.get(str(f_ch_cfg.get("length", "a")).lower(), 3.0)
        sw_node.inputs['Strand Ch (0R 1G 2B 3A)'].default_value = ch_idx_map.get(str(f_ch_cfg.get("strand", "a")).lower(), 3.0)
        sw_node.inputs['AO Ch (0R 1G 2B 3A)'].default_value = ch_idx_map.get(str(f_ch_cfg.get("ao", "a")).lower(), 3.0)
        sw_node.inputs['Invert Mask'].default_value = 1.0 if f_ch_cfg.get("invert_mask") else 0.0
        sw_node.inputs['Mask Threshold'].default_value = float(f_ch_cfg.get("mask_threshold", 0.05))
        sw_node.inputs['Mask Ramp Max'].default_value = float(f_ch_cfg.get("mask_ramp_max", 0.16))
        sw_node.inputs['Preview Mode (0Off 1R 2G 3B 4A)'].default_value = float(f_ch_cfg.get("preview", 0.0))

        # 利用 *_F.(R,G) 梳毛方向矢量在 UV 层间拖拽拉出丝滑顺毛斜纹（防止静态垂直圆点）
        fl_sf = nodes.new('ShaderNodeVectorMath')
        fl_sf.operation = 'SCALE'
        fl_sf.location = (-680, 1180)
        fl_sf.parent = f_fur
        links.new(sw_node.outputs['Flow Vector'], fl_sf.inputs[0])
        links.new(attr_sf.outputs['Fac'], _active_in(fl_sf, 'Scale'))

        fl_amt = nodes.new('ShaderNodeVectorMath')
        fl_amt.label = "Fur_Comb_Amt"
        fl_amt.operation = 'SCALE'
        fl_amt.location = (-500, 1180)
        fl_amt.parent = f_fur
        links.new(fl_sf.outputs['Vector'], fl_amt.inputs[0])
        _active_in(fl_amt, 'Scale').default_value = -0.022 * comb_strength * (44.0 / max(fur_density, 8.0))

        uv_comb = nodes.new('ShaderNodeVectorMath')
        uv_comb.operation = 'ADD'
        uv_comb.location = (-320, 1180)
        uv_comb.parent = f_fur
        links.new(uv_main, uv_comb.inputs[0])
        links.new(fl_amt.outputs['Vector'], uv_comb.inputs[1])
        fur_uv_src = uv_comb.outputs['Vector']
    else:
        fl_sf = nodes.new('ShaderNodeVectorMath')
        fl_sf.operation = 'SCALE'
        fl_sf.location = (-680, 1180)
        fl_sf.parent = f_fur
        fl_sf.inputs[0].default_value = (0.0, -0.75, 0.0)
        links.new(attr_sf.outputs['Fac'], _active_in(fl_sf, 'Scale'))

        fl_amt = nodes.new('ShaderNodeVectorMath')
        fl_amt.label = "Fur_Comb_Amt"
        fl_amt.operation = 'SCALE'
        fl_amt.location = (-500, 1180)
        fl_amt.parent = f_fur
        links.new(fl_sf.outputs['Vector'], fl_amt.inputs[0])
        _active_in(fl_amt, 'Scale').default_value = -0.022 * comb_strength * (44.0 / max(fur_density, 8.0))

        uv_comb = nodes.new('ShaderNodeVectorMath')
        uv_comb.operation = 'ADD'
        uv_comb.location = (-320, 1180)
        uv_comb.parent = f_fur
        links.new(uv_main, uv_comb.inputs[0])
        links.new(fl_amt.outputs['Vector'], uv_comb.inputs[1])
        fur_uv_src = uv_comb.outputs['Vector']

    # 2) 超高频各向异性细丝纤维 (scale = max(240, density * 32) ≈ 1408) + Noise 自然错落破除斑点
    vor_scale = max(240.0, fur_density * 32.0)
    mp_proc = nodes.new('ShaderNodeMapping')
    mp_proc.label = "Fur_Micro_Hair_UV"
    mp_proc.location = (-1040, 960)
    mp_proc.parent = f_fur
    mp_proc.inputs['Scale'].default_value = (vor_scale, vor_scale * 0.68, 1.0)
    links.new(fur_uv_src, mp_proc.inputs['Vector'])

    vor = nodes.new('ShaderNodeTexVoronoi')
    vor.label = "Fur_Micro_Hair_Cones"
    vor.feature = 'F1'
    vor.distance = 'EUCLIDEAN'
    vor.location = (-820, 960)
    vor.parent = f_fur
    vor.inputs['Scale'].default_value = 1.0
    if _active_in(vor, 'Randomness'):
        _active_in(vor, 'Randomness').default_value = 0.96
    links.new(mp_proc.outputs['Vector'], vor.inputs['Vector'])

    mr_cone = nodes.new('ShaderNodeMapRange')
    mr_cone.label = "Hair_Cone_Shape"
    mr_cone.location = (-580, 980)
    mr_cone.parent = f_fur
    mr_cone.clamp = True
    links.new(vor.outputs['Distance'], mr_cone.inputs['Value'])
    mr_cone.inputs['From Min'].default_value = 0.0
    mr_cone.inputs['From Max'].default_value = 0.46
    mr_cone.inputs['To Min'].default_value = 1.0
    mr_cone.inputs['To Max'].default_value = 0.0

    # 加入高频 Noise 破除 Voronoi 规则圆点轮廓，形成软绵自然绒毛
    ns_brk = nodes.new('ShaderNodeTexNoise')
    ns_brk.label = "Fur_Noise_Breakup"
    ns_brk.location = (-820, 740)
    ns_brk.parent = f_fur
    ns_brk.inputs['Scale'].default_value = vor_scale * 0.55
    ns_brk.inputs['Detail'].default_value = 2.0
    ns_brk.inputs['Roughness'].default_value = 0.60
    links.new(fur_uv_src, ns_brk.inputs['Vector'])

    _, brk_fac, brk_a, brk_b, brk_out = _make_mix(nodes, 'FLOAT', 'MIX', (-360, 960))
    brk_fac.default_value = 0.35
    links.new(mr_cone.outputs['Result'], brk_a)
    links.new(ns_brk.outputs['Fac'], brk_b)

    sep_vc, vc_in, vc_r, _, _ = _make_sep_color(nodes, (-580, 760))
    sep_vc.parent = f_fur
    links.new(vor.outputs['Color'], vc_in)

    mr_var = nodes.new('ShaderNodeMapRange')
    mr_var.label = "Per_Hair_Height_Var"
    mr_var.location = (-360, 760)
    mr_var.parent = f_fur
    mr_var.clamp = True
    links.new(vc_r, mr_var.inputs['Value'])
    mr_var.inputs['From Min'].default_value = 0.0
    mr_var.inputs['From Max'].default_value = 1.0
    mr_var.inputs['To Min'].default_value = 0.58
    mr_var.inputs['To Max'].default_value = 1.06

    mul_hair = nodes.new('ShaderNodeMath')
    mul_hair.operation = 'MULTIPLY'
    mul_hair.location = (-160, 920)
    mul_hair.parent = f_fur
    links.new(brk_out, mul_hair.inputs[0])
    links.new(mr_var.outputs['Result'], mul_hair.inputs[1])
    fur_noise_out = mul_hair.outputs['Value']

    if sw_node is not None:
        mul_mask = nodes.new('ShaderNodeMath')
        mul_mask.operation = 'MULTIPLY'
        mul_mask.location = (60, 980)
        mul_mask.parent = f_fur
        links.new(fur_noise_out, mul_mask.inputs[0])
        links.new(sw_node.outputs['Mask'], mul_mask.inputs[1])
        fur_noise_out = mul_mask.outputs['Value']

    # 3) 柔和羽化收尖裁剪（用平滑坡度 MapRange 取代硬二值 GREATER_THAN，消除圆盘台阶感）
    fur_taper = float(m_cfg.get("taper", 1.45))
    fur_cutoff = float(_pick_float(floats, ["_Cutoff", "_AlphaCutoff", "_FurCutoff"], m_cfg.get("cutoff", 0.16)))

    pow_sf = nodes.new('ShaderNodeMath')
    pow_sf.label = "Shell_Taper_Pow"
    pow_sf.operation = 'POWER'
    pow_sf.location = (-640, 520)
    pow_sf.parent = f_fur
    links.new(attr_sf.outputs['Fac'], pow_sf.inputs[0])
    pow_sf.inputs[1].default_value = max(0.1, fur_taper)

    map_thr = nodes.new('ShaderNodeMapRange')
    map_thr.label = "Shell_Taper_Threshold"
    map_thr.location = (-400, 520)
    map_thr.parent = f_fur
    links.new(pow_sf.outputs['Value'], map_thr.inputs['Value'])
    map_thr.inputs['From Min'].default_value = 0.0
    map_thr.inputs['From Max'].default_value = 1.0
    map_thr.inputs['To Min'].default_value = max(0.0, min(0.92, fur_cutoff))
    map_thr.inputs['To Max'].default_value = 0.90

    thr_lo = nodes.new('ShaderNodeMath')
    thr_lo.operation = 'SUBTRACT'
    thr_lo.location = (-160, 620)
    thr_lo.parent = f_fur
    links.new(map_thr.outputs['Result'], thr_lo.inputs[0])
    thr_lo.inputs[1].default_value = 0.10

    thr_hi = nodes.new('ShaderNodeMath')
    thr_hi.operation = 'ADD'
    thr_hi.location = (-160, 480)
    thr_hi.parent = f_fur
    links.new(map_thr.outputs['Result'], thr_hi.inputs[0])
    thr_hi.inputs[1].default_value = 0.10

    soft_cmp = nodes.new('ShaderNodeMapRange')
    soft_cmp.label = "Soft_Fur_Alpha_Ramp"
    soft_cmp.clamp = True
    soft_cmp.location = (120, 700)
    soft_cmp.parent = f_fur
    links.new(fur_noise_out, soft_cmp.inputs['Value'])
    links.new(thr_lo.outputs['Value'], soft_cmp.inputs['From Min'])
    links.new(thr_hi.outputs['Value'], soft_cmp.inputs['From Max'])
    soft_cmp.inputs['To Min'].default_value = 0.0
    soft_cmp.inputs['To Max'].default_value = 1.0

    # 最外层发梢柔和淡出，消除高对比散斑
    tip_fade = nodes.new('ShaderNodeMapRange')
    tip_fade.clamp = True
    tip_fade.location = (120, 500)
    tip_fade.parent = f_fur
    links.new(pow_sf.outputs['Value'], tip_fade.inputs['Value'])
    tip_fade.inputs['From Min'].default_value = 0.0
    tip_fade.inputs['From Max'].default_value = 1.0
    tip_fade.inputs['To Min'].default_value = 1.0
    tip_fade.inputs['To Max'].default_value = 0.78

    mul_soft_a = nodes.new('ShaderNodeMath')
    mul_soft_a.operation = 'MULTIPLY'
    mul_soft_a.location = (320, 640)
    mul_soft_a.parent = f_fur
    links.new(soft_cmp.outputs['Result'], mul_soft_a.inputs[0])
    links.new(tip_fade.outputs['Result'], mul_soft_a.inputs[1])

    _, a_fac, a_base, a_shell, a_out = _make_mix(nodes, 'FLOAT', 'MIX', (500, 620))
    links.new(is_shell.outputs['Value'], a_fac)
    a_base.default_value = 1.0
    links.new(mul_soft_a.outputs['Value'], a_shell)
    final_fur_alpha = a_out

    if tx_base is not None:
        ca_fur_stats = _sample_image_stats(tx_base.image, _lookup_precomputed_stats(base_tex_info, mats_db))
        if float(ca_fur_stats.get("min_a", 1.0)) < 0.96 and float(ca_fur_stats.get("max_a", 1.0)) > 0.15:
            mul_ba = nodes.new('ShaderNodeMath')
            mul_ba.operation = 'MULTIPLY'
            mul_ba.location = (640, 580)
            mul_ba.parent = f_fur
            links.new(final_fur_alpha, mul_ba.inputs[0])
            links.new(tx_base.outputs['Alpha'], mul_ba.inputs[1])
            final_fur_alpha = mul_ba.outputs['Value']
    links.new(final_fur_alpha, bsdf.inputs['Alpha'])

    # 4) 柔和根部 AO + 发梢背光绒毛泛光 + *_F 通道实时预览
    root_ao = float(_pick_float(floats, ["_FurAO", "_Occlusion", "_RootOcclusion"], m_cfg.get("root_ao", 0.28)))
    root_col = _pick_color(colors, ["_RootColor", "_FurRootColor"], m_cfg.get("root_color"))
    tip_col = _pick_color(colors, ["_TipColor", "_FurTipColor", "_FurColor"], m_cfg.get("tip_color") or [1.04, 1.04, 1.02, 1.0])
    if root_col is None:
        v_root = max(0.35, 1.0 - max(0.0, min(0.75, root_ao)))
        root_col = [v_root, v_root, v_root, 1.0]

    ao_pow = nodes.new('ShaderNodeMath')
    ao_pow.label = "Fur_RootAO_Pow"
    ao_pow.operation = 'POWER'
    ao_pow.location = (-120, 380)
    ao_pow.parent = f_fur
    links.new(attr_sf.outputs['Fac'], ao_pow.inputs[0])
    ao_pow.inputs[1].default_value = 0.65

    grad_mix, grad_fac, grad_a, grad_b, grad_out = _make_mix(nodes, 'RGBA', 'MIX', (60, 380))
    grad_mix.label = "Fur_Grad_Mix"
    links.new(ao_pow.outputs['Value'], grad_fac)
    grad_a.default_value = (root_col[0], root_col[1], root_col[2], 1.0)
    grad_b.default_value = (tip_col[0], tip_col[1], tip_col[2], 1.0)

    _, col_fac, col_a, col_b, col_out = _make_mix(nodes, 'RGBA', 'MULTIPLY', (280, 320))
    col_fac.default_value = 1.0
    links.new(base_out, col_a)
    links.new(grad_out, col_b)

    lw = nodes.new('ShaderNodeLayerWeight')
    lw.location = (60, 120)
    lw.parent = f_fur
    lw.inputs['Blend'].default_value = 0.30

    rim_pow = nodes.new('ShaderNodeMath')
    rim_pow.operation = 'POWER'
    rim_pow.location = (240, 120)
    rim_pow.parent = f_fur
    links.new(lw.outputs['Facing'], rim_pow.inputs[0])
    rim_pow.inputs[1].default_value = 2.2

    rim_sf = nodes.new('ShaderNodeMath')
    rim_sf.operation = 'MULTIPLY'
    rim_sf.location = (400, 120)
    rim_sf.parent = f_fur
    links.new(rim_pow.outputs['Value'], rim_sf.inputs[0])
    links.new(attr_sf.outputs['Fac'], rim_sf.inputs[1])

    rim_str = nodes.new('ShaderNodeMath')
    rim_str.operation = 'MULTIPLY'
    rim_str.location = (540, 120)
    rim_str.parent = f_fur
    links.new(rim_sf.outputs['Value'], rim_str.inputs[0])
    rim_str.inputs[1].default_value = 0.35

    _, rim_fac, rim_a, rim_b, rim_col_out = _make_mix(nodes, 'RGBA', 'MIX', (480, 320))
    links.new(rim_str.outputs['Value'], rim_fac)
    links.new(col_out, rim_a)
    rim_b.default_value = (1.0, 1.0, 0.98, 1.0)

    if sw_node is not None:
        _, pv_fac, pv_a, pv_b, pv_out = _make_mix(nodes, 'RGBA', 'MIX', (640, 320))
        links.new(sw_node.outputs['Preview Active'], pv_fac)
        links.new(rim_col_out, pv_a)
        links.new(sw_node.outputs['Preview Color'], pv_b)
        links.new(pv_out, bsdf.inputs['Base Color'])
    else:
        links.new(rim_col_out, bsdf.inputs['Base Color'])

    # 5) 关键：Cycles 阴影光线在壳层直接透明直通，彻底根除外层壳向外层内壁投射黑色斑点噪点
    lp = nodes.new('ShaderNodeLightPath')
    lp.location = (540, -180)
    lp.parent = f_fur

    sh_ray_mul = nodes.new('ShaderNodeMath')
    sh_ray_mul.operation = 'MULTIPLY'
    sh_ray_mul.location = (760, -180)
    sh_ray_mul.parent = f_fur
    links.new(lp.outputs['Is Shadow Ray'], sh_ray_mul.inputs[0])
    links.new(is_shell.outputs['Value'], sh_ray_mul.inputs[1])

    tr_shad = nodes.new('ShaderNodeBsdfTransparent')
    tr_shad.location = (760, -340)
    tr_shad.parent = f_fur

    mix_shad = nodes.new('ShaderNodeMixShader')
    mix_shad.location = (1000, -40)
    mix_shad.parent = f_fur
    links.new(sh_ray_mul.outputs['Value'], mix_shad.inputs['Fac'])
    links.new(bsdf.outputs['BSDF'], mix_shad.inputs[1])
    links.new(tr_shad.outputs['BSDF'], mix_shad.inputs[2])
    links.new(mix_shad.outputs['Shader'], out.inputs['Surface'])


# --------------------------------------------------------------------------- #
# Geometry Nodes Shell Fur 修改器：
#   1) IsViewport 双档壳层数（视口轻量 6~10 层，F12 渲染 28+ 满层）
#   2) 实例化前在基础网格缓存 gn_fur_mask，按 Mask Cull Threshold 预剔除无毛面
#   3) Realize 后零纹理采样，交互流畅不卡死
# --------------------------------------------------------------------------- #
def get_or_create_shellfur_gn(mask_image=None, default_f_ch=3.0, alpha_gain=1.0):
    name = "GN_ShellFur"
    if name in bpy.data.node_groups:
        bpy.data.node_groups.remove(bpy.data.node_groups[name])
    ng = bpy.data.node_groups.new(name=name, type='GeometryNodeTree')

    _add_gn_socket(ng, "Geometry", 'OUTPUT', 'NodeSocketGeometry')
    _add_gn_socket(ng, "Geometry", 'INPUT', 'NodeSocketGeometry')
    _add_gn_socket(ng, "Viewport Shells", 'INPUT', 'NodeSocketInt', default=16, min_val=1, max_val=64)
    _add_gn_socket(ng, "Render Shells", 'INPUT', 'NodeSocketInt', default=36, min_val=2, max_val=128)
    _add_gn_socket(ng, "Fur Length", 'INPUT', 'NodeSocketFloat', default=0.009, min_val=0.0, max_val=1.0)
    _add_gn_socket(ng, "Gravity", 'INPUT', 'NodeSocketFloat', default=0.0035, min_val=-0.5, max_val=0.5)
    _add_gn_socket(ng, "Comb", 'INPUT', 'NodeSocketFloat', default=0.55, min_val=0.0, max_val=2.0)
    _add_gn_socket(ng, "Length Mask Weight", 'INPUT', 'NodeSocketFloat', default=1.0, min_val=0.0, max_val=1.0)
    _add_gn_socket(ng, "F Mask Ch (0R 1G 2B 3A)", 'INPUT', 'NodeSocketFloat', default=float(default_f_ch), min_val=0.0, max_val=3.0)
    _add_gn_socket(ng, "Alpha Gain", 'INPUT', 'NodeSocketFloat', default=float(alpha_gain), min_val=0.1, max_val=20.0)
    _add_gn_socket(ng, "Mask Cull Threshold", 'INPUT', 'NodeSocketFloat', default=0.02, min_val=0.0, max_val=0.5)

    nodes, links = ng.nodes, ng.links
    gin = nodes.new('NodeGroupInput')
    gin.location = (-1350, 0)
    gout = nodes.new('NodeGroupOutput')
    gout.location = (1180, 0)

    # 1) 在基础网格上仅采样 1 次毛发遮罩并存储为点属性 gn_fur_mask（避免 Realize 后逐壳层重采样卡死）
    if mask_image is not None:
        uv_attr = nodes.new('GeometryNodeInputNamedAttribute')
        uv_attr.data_type = 'FLOAT_VECTOR'
        uv_attr.location = (-1160, -540)
        _active_in(uv_attr, 'Name').default_value = "UVMap"
        gimg = nodes.new('GeometryNodeImageTexture')
        gimg.location = (-960, -540)
        gimg.inputs['Image'].default_value = mask_image
        links.new(_active_out(uv_attr, 'Attribute'), gimg.inputs['Vector'])

        sep, sep_in, s_r, s_g, s_b = _make_sep_color(nodes, (-740, -600))
        links.new(gimg.outputs['Color'], sep_in)
        alpha_raw = _active_out(gimg, 'Alpha') or s_g
        a_mul_gn = nodes.new('ShaderNodeMath')
        a_mul_gn.operation = 'MULTIPLY'
        a_mul_gn.use_clamp = True
        a_mul_gn.location = (-580, -720)
        links.new(alpha_raw, a_mul_gn.inputs[0])
        links.new(gin.outputs['Alpha Gain'], a_mul_gn.inputs[1])

        mask_val_out = _build_channel_selector(
            nodes, links, [s_r, s_g, s_b, a_mul_gn.outputs['Value']],
            gin.outputs['F Mask Ch (0R 1G 2B 3A)'], -420, -600, "GNMask",
        )
    else:
        lm_attr = nodes.new('GeometryNodeInputNamedAttribute')
        lm_attr.data_type = 'FLOAT'
        lm_attr.location = (-740, -520)
        _active_in(lm_attr, 'Name').default_value = "fur_length_mask"
        mask_val_out = _active_out(lm_attr, 'Attribute')

    _, ml_fac, ml_a, ml_b, ml_out = _make_mix(nodes, 'FLOAT', 'MIX', (-180, -460))
    links.new(gin.outputs['Length Mask Weight'], ml_fac)
    ml_a.default_value = 1.0
    links.new(mask_val_out, ml_b)

    store_mask = nodes.new('GeometryNodeStoreNamedAttribute')
    store_mask.data_type = 'FLOAT'
    store_mask.domain = 'POINT'
    store_mask.location = (-860, -80)
    _active_in(store_mask, 'Name').default_value = "gn_fur_mask"
    links.new(gin.outputs['Geometry'], store_mask.inputs['Geometry'])
    links.new(ml_out, _active_in(store_mask, 'Value'))

    # 2) 按 fur_region AND (gn_fur_mask > Mask Cull Threshold) 预剔除无毛区域面
    attr_reg = nodes.new('GeometryNodeInputNamedAttribute')
    attr_reg.data_type = 'FLOAT'
    attr_reg.location = (-860, -240)
    _active_in(attr_reg, 'Name').default_value = "fur_region"

    cmp_reg = nodes.new('FunctionNodeCompare')
    cmp_reg.data_type = 'FLOAT'
    cmp_reg.operation = 'GREATER_THAN'
    cmp_reg.location = (-660, -240)
    links.new(_active_out(attr_reg, 'Attribute'), _active_in(cmp_reg, 'A'))
    _active_in(cmp_reg, 'B').default_value = 0.5

    read_mask_cull = nodes.new('GeometryNodeInputNamedAttribute')
    read_mask_cull.data_type = 'FLOAT'
    read_mask_cull.location = (-860, -370)
    _active_in(read_mask_cull, 'Name').default_value = "gn_fur_mask"

    cmp_mask = nodes.new('FunctionNodeCompare')
    cmp_mask.data_type = 'FLOAT'
    cmp_mask.operation = 'GREATER_THAN'
    cmp_mask.location = (-660, -370)
    links.new(_active_out(read_mask_cull, 'Attribute'), _active_in(cmp_mask, 'A'))
    links.new(gin.outputs['Mask Cull Threshold'], _active_in(cmp_mask, 'B'))

    b_and = nodes.new('FunctionNodeBooleanMath')
    b_and.operation = 'AND'
    b_and.location = (-460, -280)
    links.new(_active_out(cmp_reg, 'Result'), b_and.inputs[0])
    links.new(_active_out(cmp_mask, 'Result'), b_and.inputs[1])

    sep_geo = nodes.new('GeometryNodeSeparateGeometry')
    sep_geo.domain = 'FACE'
    sep_geo.location = (-280, -180)
    links.new(store_mask.outputs['Geometry'], sep_geo.inputs['Geometry'])
    links.new(_active_out(b_and, 'Boolean') or b_and.outputs[0], sep_geo.inputs['Selection'])

    # 3) IsViewport 自动切换壳层数：视口轻量层数 + F12 渲染满层
    is_vp = nodes.new('GeometryNodeIsViewport')
    is_vp.location = (-1120, 280)

    sw_cnt = nodes.new('GeometryNodeSwitch')
    sw_cnt.input_type = 'INT'
    sw_cnt.location = (-920, 240)
    links.new(is_vp.outputs['Is Viewport'], _active_in(sw_cnt, 'Switch'))
    links.new(gin.outputs['Render Shells'], _active_in(sw_cnt, 'False'))
    links.new(gin.outputs['Viewport Shells'], _active_in(sw_cnt, 'True'))
    active_shells = _active_out(sw_cnt, 'Output') or sw_cnt.outputs[0]

    shell_cnt_m1 = nodes.new('ShaderNodeMath')
    shell_cnt_m1.operation = 'SUBTRACT'
    shell_cnt_m1.location = (-720, 220)
    links.new(active_shells, shell_cnt_m1.inputs[0])
    shell_cnt_m1.inputs[1].default_value = 1.0

    shell_cnt_safe = nodes.new('ShaderNodeMath')
    shell_cnt_safe.operation = 'MAXIMUM'
    shell_cnt_safe.location = (-540, 220)
    links.new(shell_cnt_m1.outputs['Value'], shell_cnt_safe.inputs[0])
    shell_cnt_safe.inputs[1].default_value = 1.0

    mesh_line = nodes.new('GeometryNodeMeshLine')
    mesh_line.mode = 'OFFSET'
    mesh_line.location = (-340, 220)
    links.new(shell_cnt_safe.outputs['Value'], _active_in(mesh_line, 'Count'))
    _active_in(mesh_line, 'Offset').default_value = (0.0, 0.0, 0.0)

    inst = nodes.new('GeometryNodeInstanceOnPoints')
    inst.location = (-100, 80)
    links.new(_active_out(mesh_line, 'Mesh'), inst.inputs['Points'])
    links.new(_active_out(sep_geo, 'Selection'), inst.inputs['Instance'])

    idx = nodes.new('GeometryNodeInputIndex')
    idx.location = (-540, 420)
    idx_p1 = nodes.new('ShaderNodeMath')
    idx_p1.operation = 'ADD'
    idx_p1.location = (-340, 420)
    links.new(idx.outputs['Index'], idx_p1.inputs[0])
    idx_p1.inputs[1].default_value = 1.0

    sf_div = nodes.new('ShaderNodeMath')
    sf_div.operation = 'DIVIDE'
    sf_div.location = (-120, 420)
    links.new(idx_p1.outputs['Value'], sf_div.inputs[0])
    links.new(shell_cnt_safe.outputs['Value'], sf_div.inputs[1])

    # 非线性壳层排布 (sf^0.88)：贴近表皮更密，蓬松度与体积感一致
    sf_prog = nodes.new('ShaderNodeMath')
    sf_prog.operation = 'POWER'
    sf_prog.location = (0, 420)
    links.new(sf_div.outputs['Value'], sf_prog.inputs[0])
    sf_prog.inputs[1].default_value = 0.88

    store_sf = nodes.new('GeometryNodeStoreNamedAttribute')
    store_sf.data_type = 'FLOAT'
    store_sf.domain = 'INSTANCE'
    store_sf.location = (160, 160)
    _active_in(store_sf, 'Name').default_value = "shell_factor"
    links.new(inst.outputs['Instances'], store_sf.inputs['Geometry'])
    links.new(sf_prog.outputs['Value'], _active_in(store_sf, 'Value'))

    realize = nodes.new('GeometryNodeRealizeInstances')
    realize.location = (360, 160)
    links.new(store_sf.outputs['Geometry'], realize.inputs['Geometry'])

    # 4) SetPosition 直接读取已缓存的 gn_fur_mask 与 shell_factor + 顺毛几何向后/向下梳理矢量
    read_sf = nodes.new('GeometryNodeInputNamedAttribute')
    read_sf.data_type = 'FLOAT'
    read_sf.location = (0, -180)
    _active_in(read_sf, 'Name').default_value = "shell_factor"

    read_mask_pt = nodes.new('GeometryNodeInputNamedAttribute')
    read_mask_pt.data_type = 'FLOAT'
    read_mask_pt.location = (0, -340)
    _active_in(read_mask_pt, 'Name').default_value = "gn_fur_mask"

    nrm = nodes.new('GeometryNodeInputNormal')
    nrm.location = (220, -40)

    sf_len = nodes.new('ShaderNodeMath')
    sf_len.operation = 'MULTIPLY'
    sf_len.location = (220, -180)
    links.new(_active_out(read_sf, 'Attribute'), sf_len.inputs[0])
    links.new(gin.outputs['Fur Length'], sf_len.inputs[1])

    sf_len_m = nodes.new('ShaderNodeMath')
    sf_len_m.operation = 'MULTIPLY'
    sf_len_m.location = (400, -200)
    links.new(sf_len.outputs['Value'], sf_len_m.inputs[0])
    links.new(_active_out(read_mask_pt, 'Attribute'), sf_len_m.inputs[1])

    v_nrm = nodes.new('ShaderNodeVectorMath')
    v_nrm.operation = 'SCALE'
    v_nrm.location = (580, -100)
    links.new(nrm.outputs['Normal'], v_nrm.inputs[0])
    links.new(sf_len_m.outputs['Value'], _active_in(v_nrm, 'Scale'))

    sf_sq = nodes.new('ShaderNodeMath')
    sf_sq.operation = 'MULTIPLY'
    sf_sq.location = (220, -420)
    links.new(_active_out(read_sf, 'Attribute'), sf_sq.inputs[0])
    links.new(_active_out(read_sf, 'Attribute'), sf_sq.inputs[1])

    sf_grav = nodes.new('ShaderNodeMath')
    sf_grav.operation = 'MULTIPLY'
    sf_grav.location = (400, -420)
    links.new(sf_sq.outputs['Value'], sf_grav.inputs[0])
    links.new(gin.outputs['Gravity'], sf_grav.inputs[1])

    sf_grav_m = nodes.new('ShaderNodeMath')
    sf_grav_m.operation = 'MULTIPLY'
    sf_grav_m.location = (560, -420)
    links.new(sf_grav.outputs['Value'], sf_grav_m.inputs[0])
    links.new(_active_out(read_mask_pt, 'Attribute'), sf_grav_m.inputs[1])

    v_grav = nodes.new('ShaderNodeVectorMath')
    v_grav.operation = 'SCALE'
    v_grav.location = (720, -380)
    v_grav.inputs[0].default_value = (0.0, 0.0, -1.0)
    links.new(sf_grav_m.outputs['Value'], _active_in(v_grav, 'Scale'))

    # 3D 发梢顺毛掠伏偏移：(0, +0.22, -0.30) * Comb * FurLength * (sf^1.6) * gn_fur_mask
    sf_comb_pow = nodes.new('ShaderNodeMath')
    sf_comb_pow.operation = 'POWER'
    sf_comb_pow.location = (220, -600)
    links.new(_active_out(read_sf, 'Attribute'), sf_comb_pow.inputs[0])
    sf_comb_pow.inputs[1].default_value = 1.6

    cb_mul1 = nodes.new('ShaderNodeMath')
    cb_mul1.operation = 'MULTIPLY'
    cb_mul1.location = (380, -600)
    links.new(sf_comb_pow.outputs['Value'], cb_mul1.inputs[0])
    links.new(gin.outputs['Comb'], cb_mul1.inputs[1])

    cb_mul2 = nodes.new('ShaderNodeMath')
    cb_mul2.operation = 'MULTIPLY'
    cb_mul2.location = (540, -600)
    links.new(cb_mul1.outputs['Value'], cb_mul2.inputs[0])
    links.new(gin.outputs['Fur Length'], cb_mul2.inputs[1])

    cb_mul3 = nodes.new('ShaderNodeMath')
    cb_mul3.operation = 'MULTIPLY'
    cb_mul3.location = (700, -600)
    links.new(cb_mul2.outputs['Value'], cb_mul3.inputs[0])
    links.new(_active_out(read_mask_pt, 'Attribute'), cb_mul3.inputs[1])

    v_comb = nodes.new('ShaderNodeVectorMath')
    v_comb.operation = 'SCALE'
    v_comb.location = (840, -560)
    v_comb.inputs[0].default_value = (0.0, 0.22, -0.30)
    links.new(cb_mul3.outputs['Value'], _active_in(v_comb, 'Scale'))

    v_tot1 = nodes.new('ShaderNodeVectorMath')
    v_tot1.operation = 'ADD'
    v_tot1.location = (840, -240)
    links.new(v_nrm.outputs['Vector'], v_tot1.inputs[0])
    links.new(v_grav.outputs['Vector'], v_tot1.inputs[1])

    v_tot = nodes.new('ShaderNodeVectorMath')
    v_tot.operation = 'ADD'
    v_tot.location = (1000, -240)
    links.new(v_tot1.outputs['Vector'], v_tot.inputs[0])
    links.new(v_comb.outputs['Vector'], v_tot.inputs[1])

    set_pos = nodes.new('GeometryNodeSetPosition')
    set_pos.location = (640, 160)
    links.new(realize.outputs['Geometry'], set_pos.inputs['Geometry'])
    links.new(v_tot.outputs['Vector'], set_pos.inputs['Offset'])

    join = nodes.new('GeometryNodeJoinGeometry')
    join.location = (940, 40)
    links.new(gin.outputs['Geometry'], join.inputs['Geometry'])
    links.new(set_pos.outputs['Geometry'], join.inputs['Geometry'])
    links.new(join.outputs['Geometry'], gout.inputs['Geometry'])
    return ng


def _color_channel_values(me, ch_name):
    col_attr = None
    if hasattr(me, "color_attributes") and me.color_attributes:
        col_attr = me.color_attributes.active_color or me.color_attributes[0]
    elif hasattr(me, "vertex_colors") and me.vertex_colors:
        col_attr = me.vertex_colors.active or me.vertex_colors[0]
    if col_attr is None:
        return None
    idx = {"r": 0, "g": 1, "b": 2, "a": 3}[ch_name]
    if getattr(col_attr, "domain", "CORNER") == 'POINT':
        return [float(d.color[idx]) for d in col_attr.data]
    acc = [0.0] * len(me.vertices)
    cnt = [0] * len(me.vertices)
    for loop, d in zip(me.loops, col_attr.data):
        vi = loop.vertex_index
        acc[vi] += float(d.color[idx])
        cnt[vi] += 1
    return [acc[i] / cnt[i] if cnt[i] else 1.0 for i in range(len(me.vertices))]


def setup_scene_materials_and_shellfur(base_dir, mats_db, fur_cfg):
    mats_by_name = mats_db.get("materials", {}) if mats_db else {}
    fur_parts = set(fur_cfg.get("fur_parts") or [])
    fur_enabled = bool(fur_cfg.get("enabled", False))
    mesh_objs = [o for o in bpy.data.objects if o.type == 'MESH']
    tex_pool = _collect_texture_pool(base_dir, mats_db, fur_cfg)
    target_cid = _extract_char_id((mats_db or {}).get("character", ""))

    mat_obj_hints = {}
    for obj in mesh_objs:
        for slot in obj.material_slots:
            if slot.material and slot.material.name not in mat_obj_hints:
                mat_obj_hints[slot.material.name] = obj.name

    mat_roles = {}
    mat_archetypes = {}
    for m in bpy.data.materials:
        minfo = mats_by_name.get(m.name)
        roles = _match_textures_for_material(m.name, tex_pool, obj_hint=mat_obj_hints.get(m.name, ""), target_char_id=target_cid)
        mat_roles[m.name] = roles
        mat_archetypes[m.name] = _classify_material_archetype(m.name, roles, minfo, fur_cfg, mats_db=mats_db)

    any_mat_fur = any(arch == "fur" for arch in mat_archetypes.values())
    fallback_parts = fur_parts if fur_parts else ({"Body"} if (fur_enabled and not any_mat_fur) else set())

    fur_mat_names = set()
    for obj in mesh_objs:
        part_explicit = obj.name in fur_parts
        part_fallback = obj.name in fallback_parts
        for slot in obj.material_slots:
            m = slot.material
            if m is None:
                continue
            arch = mat_archetypes.get(m.name, "standard")
            # 仅对 fur 分型启用 Shell Fur；在无 *_F 贴图的回退模式下也严格排除 Shiny / Eye / Crystal / Foliage(02a)
            if arch == "fur":
                if fur_enabled:
                    fur_mat_names.add(m.name)
            elif (part_explicit or part_fallback) and arch == "standard":
                if not part_explicit and re.search(r"^(Eye|Pupil|Teeth|Tongue|Claw|Weapon)", obj.name, re.I):
                    continue
                fur_mat_names.add(m.name)

    # 1) 重建场景所有材质节点树（纹理映射 + B/R 法线重排 + MOHR + 分型特殊通道 + Shell Fur）
    for m in bpy.data.materials:
        minfo = mats_by_name.get(m.name)
        roles = mat_roles.get(m.name, {})
        arch = mat_archetypes.get(m.name, "standard")
        is_fur = m.name in fur_mat_names
        if minfo or roles or is_fur or arch != "standard":
            build_material_nodes(m, minfo, base_dir, fur_cfg, apply_fur=is_fur, role_tex=roles, archetype=arch, mats_db=mats_db)

    if not fur_enabled or not fur_mat_names:
        for o in mesh_objs:
            if "ShellFur" in o.modifiers:
                o.modifiers.remove(o.modifiers["ShellFur"])
        print(f"MATERIALS_SETUP_OK tex_pool={len(tex_pool)} fur_materials=[]")
        return 0

    # 2) 为包含毛发材质的 Mesh 写入 fur_region 面属性并挂载 GN_ShellFur 修改器
    mask_img = None
    mask_finfo = None
    for mname in sorted(fur_mat_names):
        minfo = mats_by_name.get(mname) or {}
        _, finfo = _pick_tex(minfo.get("tex_envs", {}), ["_FurMask", "_FurMaskMap", "_FurLengthMap", "_LengthMask", "_FurMap", "_F"])
        if not finfo and "F" in mat_roles.get(mname, {}):
            finfo = mat_roles[mname]["F"]
        if finfo:
            mask_img = _load_image(base_dir, finfo.get("file"), colorspace='Non-Color')
            if mask_img:
                mask_finfo = finfo
                break

    in_game_base = _merge_material_fur_cfg(fur_cfg, sorted(fur_mat_names)[0])
    f_ch_cfg = in_game_base.get("f_channels") or {}
    ch_idx_map = {"r": 0.0, "g": 1.0, "b": 2.0, "a": 3.0}
    default_f_ch = ch_idx_map.get(str(f_ch_cfg.get("mask", "a")).lower(), 3.0)
    auto_a_gain = float(in_game_base.get("alpha_gain", 1.0) or 1.0)
    if mask_img is not None and auto_a_gain <= 1.01:
        mstats = _sample_image_stats(mask_img, _lookup_precomputed_stats(mask_finfo, mats_db))
        if 0.02 < mstats["max_a"] < 0.30:
            auto_a_gain = min(12.0, round(0.95 / mstats["max_a"], 2))

    ng = get_or_create_shellfur_gn(mask_image=mask_img, default_f_ch=default_f_ch, alpha_gain=auto_a_gain)
    vp_layers = max(1, int(fur_cfg.get("viewport_layers", 16)))
    cull_thr = float(fur_cfg.get("mask_cull_threshold", 0.02))
    applied = 0
    for obj in mesh_objs:
        me = obj.data
        fur_slot_indices = {i for i, sl in enumerate(obj.material_slots)
                            if sl.material and sl.material.name in fur_mat_names}
        if not fur_slot_indices:
            if "ShellFur" in obj.modifiers:
                obj.modifiers.remove(obj.modifiers["ShellFur"])
            continue

        if "fur_region" in me.attributes:
            me.attributes.remove(me.attributes["fur_region"])
        attr = me.attributes.new(name="fur_region", type='FLOAT', domain='FACE')
        attr.data.foreach_set("value", [1.0 if p.material_index in fur_slot_indices else 0.0 for p in me.polygons])

        mask_ch = (fur_cfg.get("mask_channel") or "auto").lower()
        use_mask_weight = 1.0 if mask_img is not None else 0.0
        if mask_ch in ("r", "g", "b", "a") and mask_img is None:
            vals = _color_channel_values(me, mask_ch)
            if vals is not None:
                if "fur_length_mask" in me.attributes:
                    me.attributes.remove(me.attributes["fur_length_mask"])
                la = me.attributes.new(name="fur_length_mask", type='FLOAT', domain='POINT')
                la.data.foreach_set("value", vals)
                use_mask_weight = 1.0

        obj_layers = int(in_game_base.get("layers", 36))
        obj_len = float(in_game_base.get("length", 0.009))
        obj_grav = float(in_game_base.get("gravity", 0.0035))
        obj_comb = float(in_game_base.get("comb", 0.55))
        for si in fur_slot_indices:
            m = obj.material_slots[si].material
            minfo = mats_by_name.get(m.name) or {}
            m_merged = _merge_material_fur_cfg(fur_cfg, m.name, minfo)
            fl = minfo.get("floats", {})
            if m_merged.get("length") and not fur_cfg.get("length_explicit"):
                obj_len = min(0.04, float(m_merged["length"]))
            else:
                ul = _pick_float(fl, ["_FurLength", "_HairLength", "_ShellLength", "_MaxLength"], None)
                if ul is not None and ul > 1e-4 and not fur_cfg.get("length_explicit"):
                    obj_len = min(0.04, float(ul))
            if m_merged.get("layers") and not fur_cfg.get("layers_explicit"):
                obj_layers = max(2, int(round(float(m_merged["layers"]))))
            else:
                uc = _pick_float(fl, ["_ShellCount", "_LayerCount", "_FurLayers", "_FurShellCount"], None)
                if uc is not None and uc >= 2 and not fur_cfg.get("layers_explicit"):
                    obj_layers = int(round(uc))
            if m_merged.get("gravity") is not None:
                obj_grav = float(m_merged["gravity"])
            if m_merged.get("comb") is not None:
                obj_comb = float(m_merged["comb"])
            break

        if "ShellFur" in obj.modifiers:
            obj.modifiers.remove(obj.modifiers["ShellFur"])
        mod = obj.modifiers.new(name="ShellFur", type='NODES')
        mod.node_group = ng
        _set_gn_mod_input(mod, ng, "Viewport Shells", min(vp_layers, obj_layers))
        _set_gn_mod_input(mod, ng, "Render Shells", obj_layers)
        _set_gn_mod_input(mod, ng, "Fur Length", obj_len)
        _set_gn_mod_input(mod, ng, "Gravity", obj_grav)
        _set_gn_mod_input(mod, ng, "Comb", obj_comb)
        _set_gn_mod_input(mod, ng, "Length Mask Weight", use_mask_weight)
        _set_gn_mod_input(mod, ng, "F Mask Ch (0R 1G 2B 3A)", default_f_ch)
        _set_gn_mod_input(mod, ng, "Alpha Gain", auto_a_gain)
        _set_gn_mod_input(mod, ng, "Mask Cull Threshold", cull_thr)
        applied += 1

    if hasattr(bpy.context.scene, "cycles"):
        bpy.context.scene.cycles.transparent_max_bounces = max(64, int(in_game_base.get("layers", 36)) * 2 + 12)
    print(f"SHELLFUR_SETUP_OK meshes={applied} vp_layers={vp_layers} tex_pool={len(tex_pool)} fur_materials={sorted(fur_mat_names)} alpha_gain={auto_a_gain}")
    return applied


def _parse_extra_flags(argv):
    extra = {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--tex-dir" and i + 1 < len(argv):
            extra["tex_dir"] = argv[i + 1]
            i += 2
            continue
        if a.startswith("--tex-dir="):
            extra["tex_dir"] = a.split("=", 1)[1]
            i += 1
            continue
        if a == "--fur-f-channels" and i + 1 < len(argv):
            extra["f_channels_str"] = argv[i + 1]
            i += 2
            continue
        if a.startswith("--fur-f-channels="):
            extra["f_channels_str"] = a.split("=", 1)[1]
            i += 1
            continue
        i += 1
    return extra


def _import_glb_and_apply_fur(src_glb, fur_cfg, mats_db, base_dir, fps=30.0):
    bpy.context.scene.render.fps = int(round(fps))
    bpy.context.scene.render.fps_base = 1.0
    # 自动以“克制（平均）”(TEMPERANCE) 导入 glTF 骨骼，防止尾巴/耳朵等未末端对齐骨骼朝向垂直向下
    try:
        bpy.ops.import_scene.gltf(filepath=src_glb, bone_heuristic='TEMPERANCE')
    except TypeError:
        bpy.ops.import_scene.gltf(filepath=src_glb)

    arm = [o for o in bpy.data.objects if o.type == 'ARMATURE']
    shapes = set()
    for a in arm:
        for pb in a.pose.bones:
            if pb.custom_shape is not None:
                shapes.add(pb.custom_shape)
                pb.custom_shape = None
    for o in shapes:
        bpy.data.objects.remove(o, do_unlink=True)
    for a in bpy.data.actions:
        a.use_fake_user = True

    setup_scene_materials_and_shellfur(base_dir, mats_db, fur_cfg)
    return arm


def run():
    extra = {}
    if "--" in sys.argv:
        raw = sys.argv[sys.argv.index("--") + 1:]
        pos = [x for x in raw if not x.startswith("--")]
        extra = _parse_extra_flags(raw)
        src = pos[0]
        out_blend = pos[1] if len(pos) > 1 and pos[1] else ""
        out_fbx = pos[2] if len(pos) > 2 and pos[2] else ""
        fps = float(pos[3]) if len(pos) > 3 else 30.0
        if len(pos) > 4 and pos[4] and "tex_dir" not in extra:
            extra["tex_dir"] = pos[4]
        bpy.ops.wm.read_factory_settings(use_empty=True)
    else:
        here = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
        glbs = [f for f in os.listdir(here) if f.lower().endswith(".glb")]
        if not glbs:
            raise RuntimeError(f"在 {here} 下未找到 .glb 文件")
        src = os.path.join(here, glbs[0])
        out_blend = os.path.splitext(src)[0] + ".blend"
        out_fbx = ""
        fps = 30.0

    base_dir = os.path.dirname(os.path.abspath(src))
    mats_path = os.path.join(base_dir, "materials.json")
    cfg_path = os.path.join(base_dir, "shellfur_config.json")
    mats_db = json.load(open(mats_path, encoding="utf-8")) if os.path.exists(mats_path) else {}
    fur_cfg = json.load(open(cfg_path, encoding="utf-8")) if os.path.exists(cfg_path) else {"enabled": True}
    if extra.get("tex_dir"):
        fur_cfg["tex_dir"] = extra["tex_dir"]
    if extra.get("f_channels_str"):
        ps = [x.strip().lower() for x in extra["f_channels_str"].split(",")]
        keys = ("mask", "length", "strand", "ao")
        fc = fur_cfg.setdefault("f_channels", {})
        for k, v in zip(keys, ps):
            if v in ("r", "g", "b", "a"):
                fc[k] = v

    arm = _import_glb_and_apply_fur(src, fur_cfg, mats_db, base_dir, fps=fps)

    if out_blend:
        if fur_cfg.get("pack_textures"):
            try:
                bpy.ops.file.pack_all()
            except Exception as e:
                print("PACK_WARN", e)
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(out_blend))
        print("BLEND_SAVE_OK", out_blend, "armatures:", len(arm), "actions:", len(bpy.data.actions))

    if out_fbx:
        if fur_cfg.get("bake_fbx_fur"):
            for o in bpy.data.objects:
                if o.type == 'MESH' and "ShellFur" in o.modifiers:
                    bpy.context.view_layer.objects.active = o
                    try:
                        bpy.ops.object.modifier_apply(modifier="ShellFur")
                    except Exception as e:
                        print("FBX_APPLY_FUR_WARN", o.name, e)
        bpy.ops.export_scene.fbx(
            filepath=out_fbx, use_selection=False, object_types={'ARMATURE', 'MESH'},
            add_leaf_bones=False, bake_anim=True, bake_anim_use_all_actions=True,
            bake_anim_use_nla_strips=False, bake_anim_force_startend_keying=True,
            bake_anim_simplify_factor=0.0, mesh_smooth_type='FACE',
            axis_forward='-Z', axis_up='Y', path_mode='COPY')
        print("FBX_EXPORT_OK", out_fbx, "armatures:", len(arm), "actions:", len(bpy.data.actions))


# --------------------------------------------------------------------------- #
# Blender 插件 UI / 操作器 / 实时面板 (零阻塞 register, N 面板 -> Shell Fur)
# --------------------------------------------------------------------------- #
_SYNCING_PROPS = False
_CH_ITEMS = [('r', "R (0)", ""), ('g', "G (1)", ""), ('b', "B (2)", ""), ('a', "A (3)", "")]
_PREVIEW_ITEMS = [
    ('0', "0 · 正常渲染", ""),
    ('1', "1 · 预览 *_F.R", ""),
    ('2', "2 · 预览 *_F.G", ""),
    ('3', "3 · 预览 *_F.B", ""),
    ('4', "4 · 预览 *_F.A", ""),
]


def _live_update_shellfur(self, context):
    if _SYNCING_PROPS:
        return
    ch_map = {'r': 0.0, 'g': 1.0, 'b': 2.0, 'a': 3.0}
    f_mask = ch_map.get(self.f_mask_ch, 3.0)
    f_len = ch_map.get(self.f_length_ch, 3.0)
    f_str = ch_map.get(self.f_strand_ch, 3.0)
    f_ao = ch_map.get(self.f_ao_ch, 3.0)
    prev_val = float(int(self.f_preview))

    ng = bpy.data.node_groups.get("GN_ShellFur")
    if ng is not None:
        for obj in bpy.data.objects:
            if obj.type == 'MESH' and "ShellFur" in obj.modifiers:
                mod = obj.modifiers["ShellFur"]
                _set_gn_mod_input(mod, ng, "Viewport Shells", int(self.viewport_layers))
                _set_gn_mod_input(mod, ng, "Render Shells", int(self.render_layers))
                _set_gn_mod_input(mod, ng, "Fur Length", float(self.fur_length))
                _set_gn_mod_input(mod, ng, "Gravity", float(self.fur_gravity))
                _set_gn_mod_input(mod, ng, "Comb", float(self.fur_comb))
                _set_gn_mod_input(mod, ng, "Mask Cull Threshold", float(self.mask_cull_threshold))
                _set_gn_mod_input(mod, ng, "F Mask Ch (0R 1G 2B 3A)", f_mask)
                obj.update_tag()

    vor_scale = max(240.0, float(self.fur_density) * 32.0)
    comb_scale = -0.022 * float(self.fur_comb) * (44.0 / max(float(self.fur_density), 8.0))
    v_root = max(0.35, 1.0 - max(0.0, min(0.75, float(self.fur_root_ao))))
    for mat in bpy.data.materials:
        if not mat.use_nodes or not mat.node_tree:
            continue
        nodes = mat.node_tree.nodes
        sw = next((n for n in nodes if n.label == "F_Channel_Switcher"), None)
        if sw is None and not any(n.label == "Shell_Taper_Threshold" for n in nodes):
            continue
        if sw is not None:
            sw.inputs['Mask Ch (0R 1G 2B 3A)'].default_value = f_mask
            sw.inputs['Length Ch (0R 1G 2B 3A)'].default_value = f_len
            sw.inputs['Strand Ch (0R 1G 2B 3A)'].default_value = f_str
            sw.inputs['AO Ch (0R 1G 2B 3A)'].default_value = f_ao
            sw.inputs['Preview Mode (0Off 1R 2G 3B 4A)'].default_value = prev_val
        mp_uv = next((n for n in nodes if n.label == "Fur_Micro_Hair_UV"), None)
        if mp_uv is not None:
            mp_uv.inputs['Scale'].default_value = (vor_scale, vor_scale * 0.68, 1.0)
        ns_brk = next((n for n in nodes if n.label == "Fur_Noise_Breakup"), None)
        if ns_brk is not None:
            ns_brk.inputs['Scale'].default_value = vor_scale * 0.55
        cb_amt = next((n for n in nodes if n.label == "Fur_Comb_Amt"), None)
        if cb_amt is not None:
            sc_in = _active_in(cb_amt, 'Scale')
            if sc_in is not None:
                sc_in.default_value = comb_scale
        tp_pow = next((n for n in nodes if n.label == "Shell_Taper_Pow"), None)
        if tp_pow is not None:
            tp_pow.inputs[1].default_value = max(0.1, float(self.fur_taper))
        tp_thr = next((n for n in nodes if n.label == "Shell_Taper_Threshold"), None)
        if tp_thr is not None:
            tp_thr.inputs['To Min'].default_value = max(0.0, min(0.92, float(self.fur_cutoff)))
        gm = next((n for n in nodes if n.label == "Fur_Grad_Mix"), None)
        if gm is not None:
            a_sock = next((s for s in gm.inputs if s.name in ('A', 'Color1') and s.type == 'RGBA'), None)
            if a_sock is not None:
                a_sock.default_value = (v_root, v_root, v_root, 1.0)
        mat.node_tree.update_tag()

    if context and context.view_layer:
        context.view_layer.update()


def _sync_props_from_cfg(props, fur_cfg, use_ingame=False):
    global _SYNCING_PROPS
    _SYNCING_PROPS = True
    try:
        src = dict(fur_cfg or {})
        preset = src.get("in_game_preset") or {}
        if use_ingame or src.get("prefer_in_game", True):
            for k in ("layers", "length", "density", "taper", "cutoff", "gravity", "comb", "root_ao", "f_channels"):
                if k in preset and preset[k] is not None:
                    if k == "layers" and not use_ingame and src.get("layers_explicit"):
                        continue
                    if k == "length" and not use_ingame and src.get("length_explicit"):
                        continue
                    src[k] = preset[k]
        props.viewport_layers = max(1, min(64, int(src.get("viewport_layers", 16))))
        props.render_layers = max(2, min(128, int(src.get("layers", 36))))
        props.fur_length = float(src.get("length", 0.009))
        props.fur_density = float(src.get("density", 44.0))
        props.fur_taper = float(src.get("taper", 1.45))
        props.fur_cutoff = float(src.get("cutoff", 0.16))
        props.fur_gravity = float(src.get("gravity", 0.0035))
        props.fur_comb = float(src.get("comb", 0.55))
        props.fur_root_ao = float(src.get("root_ao", 0.28))
        props.mask_cull_threshold = float(src.get("mask_cull_threshold", 0.02))
        props.pack_textures = bool(src.get("pack_textures", False))
        if src.get("tex_dir"):
            props.tex_dir = str(src["tex_dir"])
        fc = src.get("f_channels") or {}
        props.f_mask_ch = fc.get("mask", "a") if fc.get("mask") in ("r", "g", "b", "a") else "a"
        props.f_length_ch = fc.get("length", "a") if fc.get("length") in ("r", "g", "b", "a") else "a"
        props.f_strand_ch = fc.get("strand", "a") if fc.get("strand") in ("r", "g", "b", "a") else "a"
        props.f_ao_ch = fc.get("ao", "a") if fc.get("ao") in ("r", "g", "b", "a") else "a"
        pv = str(int(fc.get("preview", 0)))
        props.f_preview = pv if pv in ("0", "1", "2", "3", "4") else "0"
    finally:
        _SYNCING_PROPS = False


def _resolve_config_and_base(props):
    cfg_p = bpy.path.abspath(props.config_path) if props.config_path else ""
    if cfg_p and os.path.isdir(cfg_p):
        cfg_p = os.path.join(cfg_p, "shellfur_config.json")
    if not cfg_p or not os.path.isfile(cfg_p):
        if bpy.data.filepath:
            cand = os.path.join(os.path.dirname(bpy.path.abspath(bpy.data.filepath)), "shellfur_config.json")
            if os.path.isfile(cand):
                cfg_p = cand
    base_dir = os.path.dirname(cfg_p) if cfg_p and os.path.isfile(cfg_p) else (
        os.path.dirname(bpy.path.abspath(bpy.data.filepath)) if bpy.data.filepath else os.getcwd()
    )
    fur_cfg = json.load(open(cfg_p, encoding="utf-8")) if cfg_p and os.path.isfile(cfg_p) else {"enabled": True}
    mats_p = os.path.join(base_dir, "materials.json")
    mats_db = json.load(open(mats_p, encoding="utf-8")) if os.path.isfile(mats_p) else {}
    return cfg_p, base_dir, fur_cfg, mats_db


class ShellFurAddonProps(bpy.types.PropertyGroup):
    config_path: bpy.props.StringProperty(
        name="Config JSON",
        description="指向导出目录中的 shellfur_config.json（自动读取同目录 materials.json 与 .glb）",
        subtype='FILE_PATH',
        default="",
    )
    tex_dir: bpy.props.StringProperty(
        name="Tex Dir",
        description="可选外部贴图目录（留空则读取导出目录 textures/）",
        subtype='DIR_PATH',
        default="",
    )
    viewport_layers: bpy.props.IntProperty(
        name="视口层数", default=16, min=1, max=64,
        description="3D 视口实时交互使用的轻量壳层数，防止高面数卡顿",
        update=_live_update_shellfur,
    )
    render_layers: bpy.props.IntProperty(
        name="渲染层数", default=36, min=2, max=128,
        description="F12 渲染与烘焙时自动切换的高精度满层数",
        update=_live_update_shellfur,
    )
    fur_length: bpy.props.FloatProperty(
        name="毛发长度 (m)", default=0.009, min=0.0, max=0.1, step=0.1, precision=4,
        update=_live_update_shellfur,
    )
    fur_density: bpy.props.FloatProperty(
        name="微发丝密度", default=44.0, min=8.0, max=120.0, step=50, precision=1,
        update=_live_update_shellfur,
    )
    fur_taper: bpy.props.FloatProperty(
        name="发梢收尖", default=1.45, min=0.2, max=4.0, step=5, precision=2,
        update=_live_update_shellfur,
    )
    fur_cutoff: bpy.props.FloatProperty(
        name="裁剪阈值", default=0.16, min=0.0, max=0.9, step=2, precision=2,
        update=_live_update_shellfur,
    )
    fur_gravity: bpy.props.FloatProperty(
        name="重力垂坠", default=0.0035, min=-0.1, max=0.1, step=0.1, precision=4,
        update=_live_update_shellfur,
    )
    fur_comb: bpy.props.FloatProperty(
        name="顺毛倾角", default=0.55, min=0.0, max=2.0, step=5, precision=2,
        update=_live_update_shellfur,
    )
    fur_root_ao: bpy.props.FloatProperty(
        name="根部 AO", default=0.28, min=0.0, max=0.95, step=2, precision=2,
        update=_live_update_shellfur,
    )
    mask_cull_threshold: bpy.props.FloatProperty(
        name="无毛面剔除阈值", default=0.02, min=0.0, max=0.5, step=1, precision=3,
        description="低于该遮罩长度值的三角面在壳层实例化前直接剔除，大幅降低面数",
        update=_live_update_shellfur,
    )
    f_mask_ch: bpy.props.EnumProperty(name="Mask", items=_CH_ITEMS, default='a', update=_live_update_shellfur)
    f_length_ch: bpy.props.EnumProperty(name="Length", items=_CH_ITEMS, default='a', update=_live_update_shellfur)
    f_strand_ch: bpy.props.EnumProperty(name="Strand", items=_CH_ITEMS, default='a', update=_live_update_shellfur)
    f_ao_ch: bpy.props.EnumProperty(name="AO", items=_CH_ITEMS, default='a', update=_live_update_shellfur)
    f_preview: bpy.props.EnumProperty(name="通道预览", items=_PREVIEW_ITEMS, default='0', update=_live_update_shellfur)
    pack_textures: bpy.props.BoolProperty(name="打包贴图", default=False)


class IMPORT_SCENE_OT_shellfur(bpy.types.Operator):
    """导入 .glb 并依据 shellfur_config.json / materials.json 重建游戏内毛发与分型材质"""
    bl_idname = "import_scene.uab_shellfur"
    bl_label = "导入 Shell Fur 模型 (.glb / shellfur_config.json)"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    filter_glob: bpy.props.StringProperty(default="*.json;*.glb", options={'HIDDEN'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        fp = bpy.path.abspath(self.filepath)
        if not os.path.isfile(fp):
            self.report({'ERROR'}, f"文件不存在: {fp}")
            return {'CANCELLED'}
        base_dir = os.path.dirname(fp)
        if fp.lower().endswith(".json"):
            cfg_path = fp
            glbs = sorted(f for f in os.listdir(base_dir) if f.lower().endswith(".glb"))
            if not glbs:
                self.report({'ERROR'}, f"在 {base_dir} 中未找到对应的 .glb 模型文件")
                return {'CANCELLED'}
            src_glb = os.path.join(base_dir, glbs[0])
        else:
            src_glb = fp
            cfg_path = os.path.join(base_dir, "shellfur_config.json")

        props = context.scene.shellfur_props
        if os.path.isfile(cfg_path):
            props.config_path = cfg_path
        mats_path = os.path.join(base_dir, "materials.json")
        mats_db = json.load(open(mats_path, encoding="utf-8")) if os.path.isfile(mats_path) else {}
        fur_cfg = json.load(open(cfg_path, encoding="utf-8")) if os.path.isfile(cfg_path) else {"enabled": True}
        if props.tex_dir:
            fur_cfg["tex_dir"] = bpy.path.abspath(props.tex_dir)

        _import_glb_and_apply_fur(src_glb, fur_cfg, mats_db, base_dir)
        _sync_props_from_cfg(props, fur_cfg, use_ingame=False)
        if props.pack_textures:
            try:
                bpy.ops.file.pack_all()
            except Exception:
                pass
        self.report({'INFO'}, f"已导入 {os.path.basename(src_glb)} 并应用 Shell Fur 配置")
        return {'FINISHED'}


class OBJECT_OT_shellfur_load_json(bpy.types.Operator):
    """读取 shellfur_config.json 并重新应用材质与 Shell Fur（不重复导入模型）"""
    bl_idname = "object.shellfur_load_json"
    bl_label = "加载配置并重建毛发"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.shellfur_props
        cfg_p, base_dir, fur_cfg, mats_db = _resolve_config_and_base(props)
        if cfg_p:
            props.config_path = cfg_p
        if props.tex_dir:
            fur_cfg["tex_dir"] = bpy.path.abspath(props.tex_dir)
        fur_cfg["enabled"] = True
        _sync_props_from_cfg(props, fur_cfg, use_ingame=False)
        applied = setup_scene_materials_and_shellfur(base_dir, mats_db, fur_cfg)
        self.report({'INFO'}, f"已从 {os.path.basename(cfg_p or '默认配置')} 重建 {applied} 个毛发网格")
        return {'FINISHED'}


class OBJECT_OT_shellfur_reset_ingame(bpy.types.Operator):
    """还原 shellfur_config.json 中记录的 Unity 游戏内原始毛发预设 (in_game_preset)"""
    bl_idname = "object.shellfur_reset_ingame"
    bl_label = "还原游戏内毛发配置"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.shellfur_props
        cfg_p, base_dir, fur_cfg, mats_db = _resolve_config_and_base(props)
        fur_cfg["enabled"] = True
        fur_cfg["prefer_in_game"] = True
        fur_cfg["layers_explicit"] = False
        fur_cfg["length_explicit"] = False
        _sync_props_from_cfg(props, fur_cfg, use_ingame=True)
        applied = setup_scene_materials_and_shellfur(base_dir, mats_db, fur_cfg)
        self.report({'INFO'}, f"已还原游戏内毛发参数（应用到 {applied} 个网格）")
        return {'FINISHED'}


class VIEW3D_PT_shellfur(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Shell Fur'
    bl_label = 'UAB Shell Fur 控制台'

    def draw(self, context):
        layout = self.layout
        props = context.scene.shellfur_props

        box = layout.box()
        box.label(text="游戏配置导入 / 重建", icon='IMPORT')
        box.prop(props, "config_path", text="Config")
        box.prop(props, "tex_dir", text="Tex Dir")
        row = box.row(align=True)
        row.operator("import_scene.uab_shellfur", text="导入模型+配置", icon='FILEBROWSER')
        row.operator("object.shellfur_load_json", text="重建毛发", icon='FILE_REFRESH')
        box.operator("object.shellfur_reset_ingame", text="还原游戏内预设 (In-Game)", icon='LOOP_BACK')

        box2 = layout.box()
        box2.label(text="防卡死双档壳层 (Viewport / Render)", icon='MOD_ARRAY')
        col = box2.column(align=True)
        col.prop(props, "viewport_layers")
        col.prop(props, "render_layers")
        col.prop(props, "mask_cull_threshold")

        box3 = layout.box()
        box3.label(text="丝滑绒毛外观参数", icon='STRANDS')
        col = box3.column(align=True)
        col.prop(props, "fur_length")
        col.prop(props, "fur_density")
        col.prop(props, "fur_taper")
        col.prop(props, "fur_cutoff")
        col.prop(props, "fur_gravity")
        col.prop(props, "fur_comb")
        col.prop(props, "fur_root_ao")

        box4 = layout.box()
        box4.label(text="*_F 通道分配与单通道验图", icon='NODE_TEXTURE')
        col = box4.column(align=True)
        col.prop(props, "f_mask_ch")
        col.prop(props, "f_length_ch")
        col.prop(props, "f_strand_ch")
        col.prop(props, "f_ao_ch")
        col.prop(props, "f_preview")
        box4.prop(props, "pack_textures")


def menu_func_import(self, context):
    self.layout.operator(IMPORT_SCENE_OT_shellfur.bl_idname, text="UAB Shell Fur (.glb / shellfur_config.json)")


_ADDON_CLASSES = (
    ShellFurAddonProps,
    IMPORT_SCENE_OT_shellfur,
    OBJECT_OT_shellfur_load_json,
    OBJECT_OT_shellfur_reset_ingame,
    VIEW3D_PT_shellfur,
)


def register():
    for cls in _ADDON_CLASSES:
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
        bpy.utils.register_class(cls)
    bpy.types.Scene.shellfur_props = bpy.props.PointerProperty(type=ShellFurAddonProps)
    if hasattr(bpy.types, "TOPBAR_MT_file_import"):
        bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    if hasattr(bpy.types, "TOPBAR_MT_file_import"):
        try:
            bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
        except Exception:
            pass
    if hasattr(bpy.types.Scene, "shellfur_props"):
        del bpy.types.Scene.shellfur_props
    for cls in reversed(_ADDON_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass


if __name__ == "__main__":
    if bpy.app.background or "--" in sys.argv:
        run()
    else:
        register()
        try:
            here = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
            cfg = os.path.join(here, "shellfur_config.json")
            if os.path.isfile(cfg) and bpy.context.scene and hasattr(bpy.context.scene, "shellfur_props"):
                bpy.context.scene.shellfur_props.config_path = cfg
        except Exception:
            pass
'''

BLENDER_VERIFY = r'''
import bpy, sys
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=sys.argv[sys.argv.index("--") + 1])
arms = [o for o in bpy.data.objects if o.type == 'ARMATURE']
meshes = [o for o in bpy.data.objects if o.type == 'MESH']
print("VERIFY armatures:", len(arms), "bones:", sum(len(a.data.bones) for a in arms))
for m in meshes:
    sk = m.data.shape_keys
    print("VERIFY mesh", m.name, "verts", len(m.data.vertices), "vgroups", len(m.vertex_groups),
          "shape_keys", (len(sk.key_blocks) - 1) if sk else 0)
arm_actions = [a for a in bpy.data.actions if not a.name.startswith("Key|")]
print("VERIFY armature actions:", len(arm_actions), "| shape-key actions:", len(bpy.data.actions) - len(arm_actions))
# 实际播放一个动画，取 Body 变形后的包围盒尺寸（Blender 为 Z 向上）
body = next((m for m in meshes if m.name == "Body"), None)
pick = next((a for a in arm_actions if "Walk" in a.name), arm_actions[0] if arm_actions else None)
if arms and body and pick:
    arm = arms[0]
    arm.animation_data_create().action = pick
    f0, f1 = int(pick.frame_range[0]), int(pick.frame_range[1])
    dg = bpy.context.evaluated_depsgraph_get()
    import mathutils
    dims = []
    for f in (f0, (f0 + f1) // 2, f1):
        bpy.context.scene.frame_set(f)
        dg = bpy.context.evaluated_depsgraph_get()
        me = body.evaluated_get(dg).to_mesh()
        xs = [body.matrix_world @ v.co for v in me.vertices]
        mn = [min(v[i] for v in xs) for i in range(3)]; mx = [max(v[i] for v in xs) for i in range(3)]
        dims.append([round(mx[i] - mn[i], 2) for i in range(3)])
    print("VERIFY play", pick.name[:40], "frames", f0, f1, "Body 包围盒尺寸(x,y,z):", dims)
'''


def find_blender(user_path):
    for c in ([user_path] if user_path else []) + [shutil.which("blender")]:
        if c and os.path.exists(c):
            return c
    return None


def run_blender_pipeline(glb, blender, log, fps=30.0, want_blend=False, want_fbx=False, verify=True):
    glb = Path(glb)
    out_dir = glb.parent
    sp = out_dir / "blender_import_shellfur.py"
    sp.write_text(BLENDER_SHELLFUR_SCRIPT, encoding="utf-8")
    blend_path = str(glb.with_suffix(".blend")) if want_blend else ""
    fbx_path = str(glb.with_suffix(".fbx")) if want_fbx else ""
    log(f"[Blender] 调用 Blender 处理: {blender}")
    r = subprocess.run([blender, "-b", "--factory-startup", "--python", str(sp), "--",
                        str(glb), blend_path, fbx_path, str(fps)],
                       capture_output=True, text=True)
    ok = True
    for line in r.stdout.splitlines():
        if line.startswith(("SHELLFUR_SETUP_OK", "BLEND_SAVE_OK", "FBX_EXPORT_OK", "PACK_WARN", "FBX_APPLY_FUR_WARN")):
            log("[Blender] " + line)
    if want_blend and "BLEND_SAVE_OK" not in r.stdout:
        log("[Blender] 生成 .blend 失败:\n" + (r.stdout[-1500:] + r.stderr[-1500:]))
        ok = False
    if want_fbx and "FBX_EXPORT_OK" not in r.stdout:
        log("[FBX] 转换失败:\n" + (r.stdout[-1500:] + r.stderr[-1500:]))
        ok = False
    if want_fbx and ok and verify:
        with tempfile.TemporaryDirectory() as td:
            vp = Path(td) / "verify.py"
            vp.write_text(BLENDER_VERIFY, encoding="utf-8")
            r2 = subprocess.run([blender, "-b", "--factory-startup", "--python", str(vp), "--", fbx_path],
                                capture_output=True, text=True)
            for l in r2.stdout.splitlines():
                if l.startswith("VERIFY"):
                    log("[FBX] " + l)
    if want_blend and Path(blend_path).exists():
        log(f"[Blender] 已写出 {blend_path} ({Path(blend_path).stat().st_size / 1e6:.2f} MB)")
    if want_fbx and Path(fbx_path).exists():
        log(f"[FBX] 已写出 {fbx_path} ({Path(fbx_path).stat().st_size / 1e6:.2f} MB)")
    return ok



# =========================================================================== #
# 材质 / 贴图解析与导出
# =========================================================================== #
FUR_PROP_HINTS = ("_FurLength", "_ShellCount", "_LayerCount", "_FurLayers", "_FurMap",
                  "_FurNoiseMap", "_FurMask", "_FurDensity", "_FurThickness", "_HairLength")


def _resolve_pptr(pptr, src_fname, mat_ctx, src_file=""):
    if not pptr:
        return None
    fid, pid = pptr
    if pid == 0:
        return None
    target_fname = src_fname
    if fid > 0:
        exts = (mat_ctx.get("externals_by_file", {}).get((src_file, src_fname))
                or mat_ctx["externals"].get(src_fname)
                or mat_ctx.get("externals_low", {}).get((src_fname or "").lower(), []))
        if fid - 1 < len(exts) and exts[fid - 1]:
            target_fname = exts[fid - 1]
    tlow = (target_fname or "").lower()
    hit = (mat_ctx["by_fname_pid"].get((target_fname, pid))
           or mat_ctx.get("by_fname_low_pid", {}).get((tlow, pid))
           or (mat_ctx.get("by_fname_low_pid", {}).get((tlow.rsplit(".", 1)[0], pid)) if "." in tlow else None))
    if hit is not None:
        return hit
    return mat_ctx["by_pid"].get(pid)


def _detect_is_fur(mname, mdata):
    if re.search(r"(?:^|[_\-\s])(fur|shell|hair|fluff|wool|plush|furry|feather)(?:$|[_\-\s0-9])", mname, re.I):
        return True
    if not mdata:
        return False
    if any(re.search(r"(fur|shell)", kw, re.I) for kw in mdata.get("keywords", [])):
        return True
    keys = set(mdata.get("tex_envs", {})) | set(mdata.get("floats", {})) | set(mdata.get("colors", {}))
    return any(k in keys or any(h.lower() in k.lower() for h in ("_Fur", "_Shell", "FurNoise", "FurMask")) for k in keys)


def _derive_parent_char_id(cid):
    """仅对衍生角色编号（数字长度 >= 6，如 Parmon_1058301）推导本体编号（Parmon_10583）；
    防止 Parmon_10583（5 位）被截断为 Parmon_105 导致跨角色误匹配 T_Parmon_105XX。"""
    m = re.match(r"^([A-Za-z]+_)(\d+)$", cid or "")
    if not m or len(m.group(2)) < 6:
        return None
    return f"{m.group(1)}{m.group(2)[:-2]}"


def _tex_matches_char_id(trec, char_full_low, cid_low):
    """严格判断 Texture2D 是否属于指定角色：校验容器目录段或带数字边界的贴图名，杜绝 Parmon_105XX 污染。"""
    tname_low = (trec.get("name") or "").lower()
    cp_low = (trec.get("container") or "").lower()
    # 剔除非模型 UI 贴图（如 UI_Img_ResearchBook_Enter_10583 等）
    if re.match(r"^(?:ui_img_|ui_|icon_|thumb_|spr_|atlas_)", tname_low) or "/ui/" in cp_low or "/atlas/" in cp_low:
        return False
    segs = [s for s in cp_low.split("/")[:-1] if s] if "/" in cp_low else []
    if segs:
        if char_full_low and char_full_low in segs:
            return True
        if any(re.match(rf"^{re.escape(cid_low)}(?:_|$)", s) for s in segs):
            return True
    return bool(re.search(rf"(?:^|[_\-/]){re.escape(cid_low)}(?!\d)(?:[_\-.]|$)", tname_low))


def _extract_ingame_fur_presets(mat_manifest, f_ch_dict, args):
    """从 Unity Material 提取游戏内原始毛发参数与单材质覆盖表，供 shellfur_config.json / Blender 插件还原。"""
    def _pick_fl(fl, names):
        for nm in names:
            if nm in fl:
                return float(fl[nm])
        low = {k.lower(): v for k, v in fl.items()}
        for nm in names:
            if nm.lower() in low:
                return float(low[nm.lower()])
        return None

    def _pick_cl(cl, names):
        for nm in names:
            if nm in cl:
                return [round(float(x), 4) for x in cl[nm]]
        low = {k.lower(): v for k, v in cl.items()}
        for nm in names:
            if nm.lower() in low:
                return [round(float(x), 4) for x in low[nm.lower()]]
        return None

    overrides = {}
    primary = None
    for mname, md in mat_manifest.items():
        if not md.get("is_fur"):
            continue
        fl = md.get("floats") or {}
        cl = md.get("colors") or {}
        te = md.get("tex_envs") or {}
        ov = {}
        val = _pick_fl(fl, ["_ShellCount", "_LayerCount", "_FurLayers", "_FurShellCount"])
        if val is not None and val >= 2:
            ov["layers"] = int(round(val))
        val = _pick_fl(fl, ["_FurLength", "_HairLength", "_ShellLength", "_MaxLength"])
        if val is not None and val > 1e-4:
            ov["length"] = round(min(0.04, val), 5)
        val = _pick_fl(fl, ["_FurDensity", "_Density", "_FurTiling", "_NoiseScale"])
        if val is not None and val > 0.5:
            ov["density"] = round(val, 3)
        val = _pick_fl(fl, ["_Cutoff", "_AlphaCutoff", "_FurCutoff"])
        if val is not None:
            ov["cutoff"] = round(val, 4)
        val = _pick_fl(fl, ["_FurGravity", "_Gravity"])
        if val is not None:
            ov["gravity"] = round(val, 5)
        val = _pick_fl(fl, ["_FurComb", "_CombStrength"])
        if val is not None:
            ov["comb"] = round(val, 4)
        val = _pick_fl(fl, ["_FurAO", "_Occlusion", "_RootOcclusion"])
        if val is not None:
            ov["root_ao"] = round(val, 4)
        val = _pick_fl(fl, ["_FurTaper", "_Taper"])
        if val is not None and val > 0.05:
            ov["taper"] = round(val, 4)
        rc = _pick_cl(cl, ["_RootColor", "_FurRootColor"])
        if rc is not None:
            ov["root_color"] = rc
        tc = _pick_cl(cl, ["_TipColor", "_FurTipColor", "_FurColor"])
        if tc is not None:
            ov["tip_color"] = tc

        # 自动计算 *_F Alpha 低量程增益
        for fprop in ("_FurMap", "_FurNoiseMap", "_FurMask", "_FurMaskMap", "_FurLengthMap", "_FurTex", "_F"):
            ft = te.get(fprop)
            if isinstance(ft, dict) and isinstance(ft.get("stats"), dict):
                ma = float(ft["stats"].get("max_a", 1.0))
                if 0.02 < ma < 0.30:
                    ov["alpha_gain"] = min(12.0, round(0.95 / ma, 2))
                break

        if ov:
            overrides[mname] = ov
        if primary is None:
            primary = ov

    preset = {
        "layers": int(primary.get("layers", args.fur_layers)) if primary else int(args.fur_layers),
        "length": float(primary.get("length", args.fur_length)) if primary else float(args.fur_length),
        "density": float(primary.get("density", args.fur_density)) if primary else float(args.fur_density),
        "taper": float(primary.get("taper", args.fur_taper)) if primary else float(args.fur_taper),
        "cutoff": float(primary.get("cutoff", args.fur_cutoff)) if primary else float(args.fur_cutoff),
        "gravity": float(primary.get("gravity", args.fur_gravity)) if primary else float(args.fur_gravity),
        "comb": float(primary.get("comb", getattr(args, "fur_comb", 0.55))) if primary else float(getattr(args, "fur_comb", 0.55)),
        "root_ao": float(primary.get("root_ao", args.fur_root_ao)) if primary else float(args.fur_root_ao),
        "f_channels": dict(f_ch_dict),
    }
    if primary and "alpha_gain" in primary:
        preset["alpha_gain"] = primary["alpha_gain"]
    if primary and "root_color" in primary:
        preset["root_color"] = primary["root_color"]
    if primary and "tip_color" in primary:
        preset["tip_color"] = primary["tip_color"]
    return {"in_game_preset": preset, "material_overrides": overrides}


def resolve_parts_materials(args, parts, mat_ctx, plat, out_dir, pool, log, char=""):
    """解析各部件子网格对应的 Unity Material 与 Texture2D；默认仅导出材质实际引用的贴图以大幅提速。"""
    empty_ig = {"in_game_preset": {}, "material_overrides": {}}
    if args.no_textures or mat_ctx is None:
        return {}, empty_ig
    part_mat_names = {}
    need_mat_keys = {}
    for P in parts:
        mesh_key = (P.get("fname", ""), P.get("pid", 0))
        mesh_key_low = (P.get("fname", "").lower(), P.get("pid", 0))
        rend = (mat_ctx["rend_by_mesh"].get(mesh_key)
                or mat_ctx.get("rend_by_mesh_low", {}).get(mesh_key_low)
                or mat_ctx["rend_by_mesh_pid"].get(P.get("pid", 0)))
        plat_names = plat.get(P["mesh_name"]) or plat.get(re.sub(r"_LOD\d+", "", P["mesh_name"])) or []
        names_for_part = []
        for k in range(len(P["tris"])):
            mrec = None
            if rend and k < len(rend["mats"]) and rend["mats"][k]:
                mrec = _resolve_pptr(rend["mats"][k], rend["fname"], mat_ctx["mat_lookup"], rend.get("file", ""))
            if mrec is None and k < len(plat_names):
                cands = (mat_ctx["mat_by_name"].get(plat_names[k])
                         or mat_ctx.get("mat_by_name_low", {}).get(plat_names[k].lower(), []))
                mrec = cands[0] if cands else None
            if mrec is not None:
                mname = mrec["name"] or (plat_names[k] if k < len(plat_names) else f"{P['name']}_mat{k:02d}")
                need_mat_keys[(mrec["file"], mrec["fname"], mrec["pid"])] = mrec
                names_for_part.append((mname, (mrec["file"], mrec["fname"], mrec["pid"])))
            else:
                mname = plat_names[k] if k < len(plat_names) else f"{P['name']}_mat{k:02d}"
                names_for_part.append((mname, None))
        part_mat_names[P["name"]] = names_for_part

    parsed_mats = {}
    need_tex = {}
    if need_mat_keys:
        mat_items = list(need_mat_keys.values())
        mat_datas = pmap(pool, t_read_material, [(r["file"], r["fname"], r["pid"]) for r in mat_items])
        for rec, md in zip(mat_items, mat_datas):
            if md.get("error"):
                continue
            key = (rec["file"], rec["fname"], rec["pid"])
            md["file"] = rec["file"]
            parsed_mats[key] = md
            for prop, te in md["tex_envs"].items():
                trec = _resolve_pptr(te["pptr"], rec["fname"], mat_ctx["tex_lookup"], rec["file"])
                if trec is not None:
                    tkey = (trec["file"], trec["fname"], trec["pid"])
                    need_tex[tkey] = trec

    # 仅导出材质实际引用的贴图；当材质未解析到贴图时，仅当存在明确数字角色编号(如 Parmon_10583)才启用按编号兜底
    m_cid = re.match(r"^([A-Za-z]+_\d{4,})(?:_|$)", char or "")
    auto_fallback = (len(need_tex) == 0) and bool(m_cid)
    want_extra = bool(getattr(args, "all_char_textures", False)) or auto_fallback
    used_fallback_tag = None
    if char and want_extra:
        if not m_cid:
            if getattr(args, "all_char_textures", False):
                log(f"      [材质] 目录 {char} 不含 4 位以上数字角色编号，已跳过 --all-char-textures 全系列扫图以防误匹配爆盘")
        else:
            char_full_low = char.lower()
            cid = m_cid.group(1)
            cid_low = cid.lower()
            extra_found = 0
            for trec in mat_ctx.get("textures", []):
                tkey = (trec["file"], trec["fname"], trec["pid"])
                if tkey in need_tex:
                    continue
                if _tex_matches_char_id(trec, char_full_low, cid_low):
                    need_tex[tkey] = trec
                    extra_found += 1
            if not need_tex and extra_found == 0:
                parent_cid = _derive_parent_char_id(cid)
                if parent_cid:
                    pcid_low = parent_cid.lower()
                    for trec in mat_ctx.get("textures", []):
                        tkey = (trec["file"], trec["fname"], trec["pid"])
                        if tkey not in need_tex and _tex_matches_char_id(trec, "", pcid_low):
                            need_tex[tkey] = trec
            if getattr(args, "all_char_textures", False):
                used_fallback_tag = "全角色散落"
            elif need_tex:
                used_fallback_tag = "按角色编号兜底"

    tex_dir = Path(out_dir) / "textures"
    tex_files = {}
    tex_pool_rels = []
    image_stats = {}
    if need_tex:
        tex_dir.mkdir(parents=True, exist_ok=True)
        used_tnames = set()
        tex_jobs = []
        for tkey, trec in need_tex.items():
            base_tn = safe_name(trec["name"] or f"tex_{trec['pid']}")
            fn = base_tn
            if fn in used_tnames:
                fn = f"{base_tn}_{abs(trec['pid'])}"
            used_tnames.add(fn)
            rel = f"textures/{fn}.png"
            tex_jobs.append((tkey, trec, str(Path(out_dir) / rel), rel))
        tex_res = pmap(pool, t_export_texture, [(r["file"], r["fname"], r["pid"], fp) for _, r, fp, _ in tex_jobs])
        ok_cnt = 0
        for (tkey, _, _, rel), res in zip(tex_jobs, tex_res):
            if not res.get("error"):
                tex_files[tkey] = {"file": rel, **res}
                tex_pool_rels.append(rel)
                if isinstance(res.get("stats"), dict):
                    image_stats[rel] = res["stats"]
                ok_cnt += 1
        mode_tag = used_fallback_tag or "仅材质引用"
        log(f"      [材质] 已读取 {len(parsed_mats)} 个 Material，导出 {ok_cnt}/{len(tex_jobs)} 张 Texture2D ({mode_tag})")
    else:
        log(f"      [材质] 已读取 {len(parsed_mats)} 个 Material，未发现材质引用贴图（已跳过全库扫图以防写满磁盘）")

    mat_manifest = {}
    for key, md in parsed_mats.items():
        mname = md["name"] or f"mat_{md['pid']}"
        tex_out = {}
        for prop, te in md["tex_envs"].items():
            trec = _resolve_pptr(te["pptr"], md["fname"], mat_ctx["tex_lookup"], md.get("file", ""))
            tkey = (trec["file"], trec["fname"], trec["pid"]) if trec else None
            tf = tex_files.get(tkey)
            if tf:
                tex_out[prop] = {
                    "file": tf["file"],
                    "scale": te["scale"],
                    "offset": te["offset"],
                    "wrap_u": tf["wrap_u"],
                    "wrap_v": tf["wrap_v"],
                    "stats": tf.get("stats"),
                }
        mat_manifest[mname] = {
            "shader_keywords": md["keywords"],
            "is_fur": _detect_is_fur(mname, md),
            "tex_envs": tex_out,
            "floats": md["floats"],
            "colors": md["colors"],
        }

    for p_mats in part_mat_names.values():
        for mname, _ in p_mats:
            mat_manifest.setdefault(mname, {
                "shader_keywords": [],
                "is_fur": bool(re.search(r"(?:^|[_\-\s])(fur|shell|hair|fluff)(?:$|[_\-\s0-9])", mname, re.I)),
                "tex_envs": {},
                "floats": {},
                "colors": {},
            })

    fch_parts = [x.strip().lower() for x in (getattr(args, "fur_f_channels", None) or "a,a,a,a").split(",")]
    f_ch_dict = {
        "mask": fch_parts[0] if len(fch_parts) > 0 and fch_parts[0] in ("r", "g", "b", "a") else "a",
        "length": fch_parts[1] if len(fch_parts) > 1 and fch_parts[1] in ("r", "g", "b", "a") else "a",
        "strand": fch_parts[2] if len(fch_parts) > 2 and fch_parts[2] in ("r", "g", "b", "a") else "a",
        "ao": fch_parts[3] if len(fch_parts) > 3 and fch_parts[3] in ("r", "g", "b", "a") else "a",
        "preview": int(getattr(args, "fur_f_preview", 0) or 0),
    }
    ingame_info = _extract_ingame_fur_presets(mat_manifest, f_ch_dict, args)

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    with open(Path(out_dir) / "materials.json", "w", encoding="utf-8") as _mf:
        json.dump({"character": char, "materials": mat_manifest, "texture_pool": tex_pool_rels, "image_stats": image_stats},
                  _mf, ensure_ascii=False, indent=1)
    return part_mat_names, ingame_info


# =========================================================================== #
# 单个变体的重建：骨架 + 层级 + 网格/蒙皮 + 动画 -> GLB
# =========================================================================== #
def build_variant(args, char, vh, skel_parts, sel_recs, probes, clips, app, decoded, tos, plat, mat_ctx, pool, out_dir, log):
    tag = f"{safe_name(char)}_{vh}"

    # ---- 骨架：该变体全部 LOD0 部件的骨骼并集（与所选 LOD 无关，LOD 部件只引用其子集） ----
    H, Wd = [], {}
    for r in skel_parts:
        for h, bp in zip(r["bones"], r["bindpose"]):
            if h not in Wd:
                Wd[h] = np.linalg.inv(bp)
                H.append(h)
    n = len(H)
    hidx = {h: i for i, h in enumerate(H)}
    W = np.stack([Wd[h] for h in H]) if H else np.zeros((0, 4, 4))
    base = skel_parts[0]
    for r in skel_parts[1:]:                                 # 不同部件的网格空间可能有微小平移，统计一下
        diffs = [np.linalg.inv(bp)[:3, 3] - Wd[h][:3, 3] for h, bp in zip(r["bones"], r["bindpose"]) if h in Wd]
        if diffs:
            d = np.array(diffs)
            log(f"      部件 {r['part']} 相对 {base['part']} 的骨骼平移差: 均值 {d.mean(0).round(5).tolist()} 最大 {np.abs(d).max():.5f}")

    # ---- 读取选定 LOD 的各部件（顶点/权重/BlendShape），可并行 ----
    recs = sorted(sel_recs.items(), key=lambda kv: -len(kv[1]["bones"]))
    parts = pmap(pool, t_read_part, [(r["file"], r["fname"], r["pid"], r["name"], p, r["lod"]) for p, r in recs])
    ok_parts = []
    for P in parts:
        if P.get("error"):
            log(f"      [跳过部件] {P.get('name')}: {P['error']}")
        elif any(h not in hidx for h in P["hashes"]):
            log(f"      [跳过部件] {P['name']}: 含有不在该变体骨架内的骨骼")
        else:
            ok_parts.append(P)
    parts = sorted(ok_parts, key=lambda P: -len(P["hashes"]))
    if not parts:
        log("      [!] 没有可用部件，跳过该变体")
        return None
    for P in parts:
        log(f"      {P['name']:8s} {P['mesh_name'][-24:]:>24s} 顶点 {len(P['pos']):6d} 子网格 {len(P['tris'])} 骨骼 {len(P['hashes']):3d} "
            f"BlendShape {len(P['morphs'])} 权重 {'有' if P['bw'] is not None else '无'}")

    height = max(float(P["pos"][:, 1].max() - P["pos"][:, 1].min()) for P in parts)
    rm_thr = args.root_motion_threshold or max(0.15, 0.3 * height)
    rm_stat, rm_clips = Counter(), set()

    # ---- 骨骼缩放：BindPose 里有非单位缩放的骨骼（如眼球骨骼 0.01 倍） ----
    ws3 = np.linalg.norm(W[:, :3, :3], axis=1) if n else np.zeros((0, 3))
    wsu = ws3.mean(1) if n else np.zeros(0)
    scaled_idx = [i for i in range(n) if np.abs(ws3[i] - 1).max() > 1e-3]
    nonuni = [i for i in scaled_idx if (ws3[i].max() - ws3[i].min()) > 1e-3]

    def _unit(M):
        M = M.copy()
        c = np.linalg.norm(M[:3, :3], axis=0)
        M[:3, :3] = M[:3, :3] / np.where(c > 1e-9, c, 1.0)
        return M
    if scaled_idx:
        log(f"      [缩放] {len(scaled_idx)} 块骨骼的 BindPose 带缩放（例 {[(H[i], round(float(wsu[i]), 4)) for i in scaled_idx[:3]]}），"
            "已按等比缩放还原为单位骨骼：蒙皮结果不变，动画里的平移/缩放按比例换算"
            + (f"；其中 {len(nonuni)} 块为非等比缩放，精度可能下降" if nonuni else ""))
    Wu = np.stack([_unit(W[i]) for i in range(n)]) if n else np.zeros((0, 4, 4))
    for P in parts:
        P["bindpose"] = [np.linalg.inv(_unit(np.linalg.inv(bp))) for bp in P["bindpose"]]

    # ---- 骨骼名 / 路径表 ----
    hash2path = dict(tos)
    if args.names:
        with open(args.names, encoding="utf-8") as _nf:
            nm = json.load(_nf)
        if isinstance(nm, list):
            for p in nm:
                parts_ = p.strip("/").split("/")
                for k in range(1, len(parts_) + 1):
                    pp = "/".join(parts_[:k])
                    hash2path[zlib.crc32(pp.encode("utf-8"))] = pp
        else:
            for k, v in nm.items():
                if v:
                    hash2path[int(k)] = str(v)
    path_of = dict(hash2path)                                  # 为所有路径补上各级前缀（前缀哈希 = crc32(前缀路径)）
    for p in list(hash2path.values()):
        seg = p.split("/")
        for k in range(1, len(seg)):
            pp = "/".join(seg[:k])
            path_of.setdefault(zlib.crc32(pp.encode("utf-8")), pp)
    path2hash = {}
    for h, p in path_of.items():
        path2hash.setdefault(p, h)
    cover = sum(1 for h in H if h in path_of) / max(n, 1)
    use_tos = (n > 0) and (not args.no_tos) and cover >= 0.8

    # ---- 层级 ----
    samples = [probes[i]["sample"] for i in app]
    cnames = [clips[i]["name"] for i in app]
    pos_tracked = {h for s in samples for h, v in s.items() if v[0] is not None}
    n_skin = n
    guessed, ties = set(), 0
    Hn, is_extra = list(H), [False] * n
    if n == 0:
        log("[3/6] 无骨骼静态网格，跳过骨架与动画层级构建")
        nn = 0
        parent = np.zeros(0, np.int64)
        conf = np.zeros(0)
        Wn = np.zeros((0, 4, 4))
        wsu_n = np.zeros(0)
        roots = []
        verified = 0
        WP = {}
        samples_for_wp = []
    elif use_tos:
        log(f"[3/6] 用 Avatar(TOS) 路径还原骨骼层级（{cover * 100:.0f}% 的骨骼有路径，{len(app)} 个动画可用）…")
        idx = {h: i for i, h in enumerate(Hn)}

        def par_h(h):
            p = path_of.get(h)
            return path2hash.get(p.rsplit("/", 1)[0]) if p and "/" in p else None
        stack = list(H)
        while stack:                                           # 补全祖先节点（无蒙皮但参与动画，如 Bip001 / Pelvis / 根运动载体）
            h = stack.pop()
            ph = par_h(h)
            if ph is not None and ph not in idx:
                idx[ph] = len(Hn)
                Hn.append(ph)
                is_extra.append(True)
                stack.append(ph)
        nn = len(Hn)
        parent = np.full(nn, -1, np.int64)
        for i, h in enumerate(Hn):
            ph = par_h(h)
            if ph is not None:
                parent[i] = idx[ph]
        conf = np.ones(nn)
        if samples:                                            # 与“动画交叉验证”的推断结果对照，评估 TOS 是否匹配这套骨架
            ip, _, ties = infer_parents(H, W, samples, Wu=Wu)
            pairs = [(i, ip[i]) for i in range(n) if ip[i] >= 0 and 0 <= parent[i] < n]
            agree = sum(1 for i, j in pairs if parent[i] == j)
            log(f"      TOS 层级 vs 动画交叉验证: 一致 {agree}/{len(pairs)}" + ("" if agree >= 0.9 * max(len(pairs), 1) else "  [警告] 一致率偏低，TOS 可能不属于这套骨架"))
        nopath = [h for h in H if h not in path_of]
        log(f"      节点 {nn} = 蒙皮骨骼 {n} + 补全的祖先节点 {nn - n}" + (f" | {len(nopath)} 块骨骼没有路径(作为根)" if nopath else ""))
        # 参考帧：与 BindPose 旋转最接近的动画首帧，用来给“无蒙皮祖先节点”定静止局部变换
        rest_rot = {i: mat_to_quat((np.linalg.inv(Wu[int(parent[i])]) @ Wu[i])[:3, :3]) for i in range(n) if 0 <= parent[i] < n}
        bk, best = 0, 1e9
        for k, smp in enumerate(samples):
            errs = [qangle(smp[H[i]][1], q) for i, q in rest_rot.items() if H[i] in smp and smp[H[i]][1] is not None]
            if errs and np.median(errs) < best:
                bk, best = k, float(np.median(errs))
        if samples:
            log(f"      以动画「{cnames[bk]}」首帧作为静止姿态参考（与 BindPose 旋转中位偏差 {best:.2f}°）")
        wsu_n = np.concatenate([wsu, np.ones(nn - n)])
        Wn = np.zeros((nn, 4, 4))
        Wn[:n] = Wu
        done = [i < n for i in range(nn)]
        ref_smp = samples[bk] if samples else {}

        def ref_local(h):
            """该节点在参考帧里的局部 TRS（4x4）；参考帧没有就取别的动画里第一个有轨道的；都没有返回 None。"""
            for smp in ([ref_smp] + samples):
                v = smp.get(h)
                if v is not None and (v[0] is not None or v[1] is not None):
                    L = np.eye(4)
                    if v[1] is not None:
                        L[:3, :3] = quat_to_mat(qnorm(np.asarray(v[1])))
                    if v[0] is not None:
                        L[:3, 3] = np.asarray(v[0])
                    return L
            return None

        def travel(h):                                         # 该节点首帧位置在各动画间的水平波动：大 => 根运动载体
            ps = np.array([smp[h][0] for smp in samples if h in smp and smp[h][0] is not None])
            return float(np.ptp(ps[:, [0, 2]], axis=0).max()) if len(ps) > 1 else 0.0
        is_carrier = [i >= n and travel(Hn[i]) > rm_thr for i in range(nn)]
        kids = defaultdict(list)
        for i in range(nn):
            if parent[i] >= 0:
                kids[int(parent[i])].append(i)
        n_up = n_down = 0
        # 祖先节点没有 BindPose。参考帧里“根运动载体”(Bip001)的位置带着该动画的起点位移，不能用来定它的世界位置：
        # 载体(及无已知父节点的)改为用其已求出的子节点反推：W_父 = W_子 · inv(L_子)，使子节点的静止局部变换与动画局部值一致。
        for _ in range(nn + 2):
            progressed = False
            for i in range(n, nn):
                if done[i]:
                    continue
                p = int(parent[i])
                # 自上而下：本节点不是载体，且(父节点已知 或 本身是顶层节点)
                if (p < 0 or done[p]) and not is_carrier[i]:
                    L = ref_local(Hn[i])
                    if L is None:
                        L = np.eye(4)
                    elif p >= 0:
                        L = L.copy()
                        L[:3, 3] *= wsu_n[p]
                    Wn[i] = (Wn[p] @ L) if p >= 0 else L
                    done[i] = True
                    n_down += 1
                    progressed = True
                    continue
                # 自下而上：用已知的子节点反推
                ests = []
                for c in kids[i]:
                    if done[c]:
                        Lc = ref_local(Hn[c])
                        if Lc is not None:
                            Lc = Lc.copy()
                            Lc[:3, 3] *= (wsu_n[i] if wsu_n[i] else 1.0)
                            ests.append((0 if c < n else 1, Wn[c] @ np.linalg.inv(Lc)))
                if ests:
                    best_rank = min(r for r, _ in ests)               # 优先用蒙皮子骨骼(世界矩阵精确)的估计
                    cand = [E for r, E in ests if r == best_rank]
                    med = np.median(np.array([E[:3, 3] for E in cand]), axis=0)
                    Wn[i] = min(cand, key=lambda E: np.linalg.norm(E[:3, 3] - med))
                    done[i] = True
                    n_up += 1
                    progressed = True
            if not progressed:
                break
        for i in range(n, nn):                                  # 仍无法确定（既无已知父也无已知子）：按参考帧局部值或单位阵
            if not done[i]:
                L = ref_local(Hn[i])
                Wn[i] = L if L is not None else np.eye(4)
        carriers = [path_of.get(Hn[i], str(Hn[i])).split("/")[-1] for i in range(n, nn) if is_carrier[i]]
        log(f"      补全节点 {nn - n} 个：自下而上反推 {n_up} 个(含根运动载体 {carriers or '无'})，自上而下 {n_down} 个")
        roots = [i for i in range(nn) if parent[i] < 0]
        log(f"      根(顶层)节点 {len(roots)} 个: " + ", ".join((path_of.get(Hn[r], str(Hn[r])).split("/")[-1]) for r in roots[:6]))
        verified = int(np.sum(parent[:n] >= 0))
        WP = {}
        samples_for_wp = []
    else:
        why = "未提供 Avatar(TOS)" if cover == 0 else f"TOS 只覆盖 {cover * 100:.0f}% 的骨骼(<80%)" if not args.no_tos else "已用 --no-tos 关闭"
        log(f"[3/6] 推断骨骼层级（{n} 块骨骼，可用动画 {len(app)} 个；{why}，改用 BindPose×动画 交叉验证）…")
        if samples:
            parent, conf, ties = infer_parents(H, W, samples, Wu=Wu)
        else:
            parent, conf, ties = np.full(n, -1, np.int64), np.zeros(n), 0
            log("      [警告] 没有可用动画，无法验证层级")
        verified = int((parent >= 0).sum())
        if not args.no_guess and samples:
            guessed = guess_parents(H, Wu, parent, [h in pos_tracked for h in H], log)
        for i in guessed:
            conf[i] = 0.0
        nn = n
        Wn = Wu
        wsu_n = wsu
        roots = [i for i in range(n) if parent[i] < 0]
        samples_for_wp = samples
    if n > 0:
        log(f"      层级: {'TOS 路径' if use_tos else '动画验证'} {verified} 条"
            + ("" if use_tos else f" | 几何猜测 {len(guessed)} 条(约70%准确，已在 skeleton.json 标记 guessed)")
            + f" | 根节点 {len(roots)} 个" + ("" if use_tos else f" | 位置并列经旋转裁决 {ties} 处 | 低置信度(<50%) {int(((conf > 0) & (conf < 0.5)).sum())} 块"))
    if n > 0 and not use_tos:
        orphan = [r for r in roots if H[r] in pos_tracked]
        if len(roots) > 1 and len(orphan) > 1:
            log(f"      [警告] 有 {len(orphan)} 个带动画的根骨骼，它们的真实父节点(如 Pelvis/Bip001)不在蒙皮骨骼里且没有 Avatar，"
                "无法补全：动画里这些骨骼不会跟随被省略的祖先运动，可能出现身体脱节/网格被拉长。请把包含 Avatar 的 .uab 加入输入，或用 --tos-json 提供骨骼路径表")
        elif orphan:
            log("      [提示] 根骨骼的祖先(如 Bip001/Root)不在蒙皮骨骼里，其整体位移(根运动)已无法体现，动画为原地动画")
        for r in roots[:6]:
            sub, st = 0, [r]
            while st:
                k = st.pop()
                sub += 1
                st += [j for j in range(n) if parent[j] == k]
            log(f"      根骨骼 #{r:3d} hash={H[r]} 世界位置={np.round(W[r][:3, 3], 3).tolist()} 子树 {sub} 块")

    # ---- 命名（所有节点） ----
    names, used = [], set()
    for i, h in enumerate(Hn):
        base_n = path_of[h].split("/")[-1] if h in path_of else f"Bone_{h}"
        nm_ = safe_name(base_n)
        if nm_ in used:
            nm_ = f"{nm_}_{h}"
        used.add(nm_)
        names.append(nm_)
    named = sum(1 for h in Hn if h in path_of)
    if nn > 0:
        log(f"      骨骼名: 已还原 {named}/{nn}" + ("" if named else "（包内无 Avatar/Prefab，使用 Bone_<哈希> 命名；可用 --names / --tos-json 提供）"))

    # ---- 静止局部变换；非 TOS 模式下根骨骼的“虚拟父节点” ----
    H, n, W, hidx = Hn, nn, Wn, {h: i for i, h in enumerate(Hn)}

    # ---- 烘焙部件偏移：每个部件的 BindPose 含有该 SkinnedMeshRenderer 相对骨架根的变换 M_p（Unity 里蒙皮顶点在静止时
    #      实际落在 M_p·v）。Blender/FBX 导入时不使用 IBM，部件会掉回原点；所以把 M_p 烘焙进顶点/法线，
    #      并让所有部件共用同一套 IBM(=骨架世界矩阵的逆)，各软件看到的静止姿态完全一致。 ----
    bake_info = {}
    for P in parts:
        if not P["hashes"]:
            bake_info[P["name"]] = {"shift_m": 0.0, "rot_dev": 0.0, "consistency": 0.0, "mirrored": False}
            P["flip"] = False
            P["bindpose"] = []
            continue
        Ms = np.stack([W[hidx[h]] @ P["bindpose"][k] for k, h in enumerate(P["hashes"])])
        M = np.eye(4)
        M[:3, 3] = Ms[:, :3, 3].mean(0)
        u_, _, vt_ = np.linalg.svd(Ms[:, :3, :3].mean(0))
        M[:3, :3] = u_ @ vt_
        dev = float(max(np.abs(Ms[:, :3, 3] - M[:3, 3]).max(), np.abs(Ms[:, :3, :3] - M[:3, :3]).max()))
        shift = float(np.linalg.norm(M[:3, 3]))
        rotdev = float(np.abs(M[:3, :3] - np.eye(3)).max())
        mirrored = bool(np.linalg.det(M[:3, :3]) < 0)
        bake_info[P["name"]] = {"shift_m": round(shift, 5), "rot_dev": round(rotdev, 6), "consistency": round(dev, 6), "mirrored": mirrored}
        if shift > 1e-6 or rotdev > 1e-6:
            R = M[:3, :3]
            P["pos"] = P["pos"] @ R.T + M[:3, 3]
            if P["nrm"] is not None:
                nr = P["nrm"] @ R.T
                P["nrm"] = nr / np.maximum(np.linalg.norm(nr, axis=1, keepdims=True), 1e-12)
            for mo in P["morphs"]:
                mo["delta"] = mo["delta"] @ R.T
            log(f"      部件 {P['name']:8s} 已烘焙相对骨架的偏移 {shift * 1000:.1f} mm"
                + (f"、旋转偏差 {rotdev:.4f}" if rotdev > 1e-6 else "")
                + (f"  [警告] 各骨骼推出的偏移不一致(最大差 {dev:.4f})，该部件的 BindPose 可能含非刚体变换" if dev > 1e-3 else ""))
        P["flip"] = mirrored                                    # 镜像变换会翻转绕序，导出三角形时需额外翻转一次
        P["bindpose"] = [np.linalg.inv(W[hidx[h]]) for h in P["hashes"]]
    rest_loc = []
    for i in range(n):
        L = W[i] if parent[i] < 0 else np.linalg.inv(W[parent[i]]) @ W[i]
        rest_loc.append((L[:3, 3].copy(), mat_to_quat(L[:3, :3])))
    WP, anchor0 = {r: np.eye(4) for r in roots}, {}
    if not use_tos and samples_for_wp and roots:
        best, bk = 1e9, 0
        for k, smp in enumerate(samples_for_wp):
            errs = [qangle(smp[H[i]][1], rest_loc[i][1]) for i in range(n)
                    if parent[i] >= 0 and i not in guessed and H[i] in smp and smp[H[i]][1] is not None]
            if errs and np.median(errs) < best:
                best, bk = float(np.median(errs)), k
        log(f"      以动画「{cnames[bk]}」首帧作为静止姿态参考（与 BindPose 旋转中位偏差 {best:.2f}°）")
        for r in roots:
            v = samples_for_wp[bk].get(H[r])
            if v is None or v[1] is None:
                continue
            p0 = v[0] if v[0] is not None else np.zeros(3)
            anchor0[r] = np.asarray(p0, float)
            Lr = np.eye(4)
            Lr[:3, :3] = quat_to_mat(qnorm(np.asarray(v[1])))
            Lr[:3, 3] = p0
            WP[r] = W[r] @ np.linalg.inv(Lr)

    # ---- 解析并导出本变体各部件的材质与贴图 ----
    out_dir = Path(out_dir)
    part_mat_names, ingame_info = resolve_parts_materials(args, parts, mat_ctx, plat, out_dir, pool, log, char=char)

    # ------------------------------------------------------------------ #
    # 构建 glTF
    # ------------------------------------------------------------------ #
    log("[4/6] 组装 glTF（骨骼 / 蒙皮 / BlendShape / UV / 顶点色）…")
    gl = Gltf()
    nodes, children = [], defaultdict(list)
    for i in range(n):
        t_, q_ = rest_loc[i]
        nodes.append({"name": names[i], "translation": [float(x) for x in to_gl_vec(t_)],
                      "rotation": [float(x) for x in to_gl_quat(q_)]})
        if parent[i] >= 0:
            children[int(parent[i])].append(i)
    for i, ch in children.items():
        nodes[i]["children"] = ch
    materials, mat_idx_map, meshes_out, skins, scene_nodes = [], {}, [], [], []
    top_idx = None
    if n > 0:
        top = {"name": "Armature", "children": roots}          # 名字尽量短：Blender/FBX 动作名上限 63 字符
        nodes.append(top)
        top_idx = len(nodes) - 1
        scene_nodes.append(top_idx)
    mesh_node_of = {}
    for P in parts:
        attrs = {"POSITION": gl.add(to_gl_vec(P["pos"]), 34962, minmax=True)}
        if P["nrm"] is not None:
            attrs["NORMAL"] = gl.add(to_gl_vec(P["nrm"]), 34962)
        if P["uv"] is not None:
            uv = P["uv"].copy()
            uv[:, 1] = 1.0 - uv[:, 1]                       # Unity V 向上 -> glTF V 向下
            attrs["TEXCOORD_0"] = gl.add(uv, 34962)
        if P.get("uv1") is not None:
            uv1 = P["uv1"].copy()
            uv1[:, 1] = 1.0 - uv1[:, 1]
            attrs["TEXCOORD_1"] = gl.add(uv1, 34962)
        if P.get("colors") is not None:
            attrs["COLOR_0"] = gl.add(P["colors"].astype(np.float32), 34962)
        skinned = P["bw"] is not None and P["bi"] is not None and len(P["hashes"]) > 0
        if skinned:
            attrs["JOINTS_0"] = gl.add(P["bi"].astype(np.uint16), 34962)
            attrs["WEIGHTS_0"] = gl.add(P["bw"], 34962)
        targets = [{"POSITION": gl.add(to_gl_vec(mo["delta"]), 34962, minmax=True)} for mo in P["morphs"]]
        plat_names = plat.get(P["mesh_name"]) or plat.get(re.sub(r"_LOD\d+", "", P["mesh_name"])) or []
        resolved_names = part_mat_names.get(P["name"], [])
        prims = []
        for k, tri in enumerate(P["tris"]):
            if len(tri) == 0:
                continue
            tri = tri if P.get("flip") else tri[:, [0, 2, 1]]       # X 镜像后翻转绕序（部件自身含镜像时再翻一次，等于不翻）
            if k < len(resolved_names):
                mname = resolved_names[k][0]
            elif k < len(plat_names):
                mname = plat_names[k]
            else:
                mname = f"{P['name']}_mat{k:02d}"
            if mname not in mat_idx_map:
                mat_idx_map[mname] = len(materials)
                materials.append({"name": mname, "pbrMetallicRoughness": {"baseColorFactor": [0.8, 0.8, 0.8, 1.0],
                                                                          "metallicFactor": 0.0, "roughnessFactor": 0.8},
                                  "doubleSided": True})
            prim = {"attributes": attrs, "indices": gl.add(tri.reshape(-1).astype(np.uint32), 34963),
                    "material": mat_idx_map[mname]}
            if targets:
                prim["targets"] = targets
            prims.append(prim)
        mesh = {"name": P["name"], "primitives": prims}
        if targets:
            mesh["weights"] = [0.0] * len(targets)
            mesh["extras"] = {"targetNames": [mo["name"] for mo in P["morphs"]]}
        meshes_out.append(mesh)
        node = {"name": P["name"], "mesh": len(meshes_out) - 1}
        if skinned:
            ibm = np.stack([S_MIRROR @ bp @ S_MIRROR for bp in P["bindpose"]])
            skins.append({"name": f"{P['name']}_Skin", "joints": [hidx[h] for h in P["hashes"]],
                          "inverseBindMatrices": gl.add(ibm), "skeleton": top_idx})
            node["skin"] = len(skins) - 1
        nodes.append(node)
        scene_nodes.append(len(nodes) - 1)
        mesh_node_of[P["name"]] = len(nodes) - 1

    doc = {"asset": {"version": "2.0", "generator": "uab_to_model.py"}, "scene": 0,
           "scenes": [{"name": tag, "nodes": scene_nodes}], "nodes": nodes,
           "meshes": meshes_out, "materials": materials}
    if skins:
        doc["skins"] = skins

    # ---- 静止姿态自检：按 glTF 公式蒙皮后应与原网格一致 ----
    Jw = np.zeros((n, 4, 4))
    for i in range(n):
        t_, q_ = to_gl_vec(rest_loc[i][0]), to_gl_quat(rest_loc[i][1])
        L = np.eye(4)
        L[:3, :3] = quat_to_mat(q_)
        L[:3, 3] = t_
        Jw[i] = L
    order, seen_ = [], set()

    def visit(i):
        if i in seen_:
            return
        if parent[i] >= 0:
            visit(int(parent[i]))
        seen_.add(i)
        order.append(i)
    for i in range(n):
        visit(i)
    for i in order:
        if parent[i] >= 0:
            Jw[i] = Jw[int(parent[i])] @ Jw[i]
    worst = 0.0
    for P in parts:
        if P["bw"] is None or not P["hashes"]:
            continue
        ibm = np.stack([S_MIRROR @ bp @ S_MIRROR for bp in P["bindpose"]])
        jm = np.stack([Jw[hidx[h]] @ ibm[k] for k, h in enumerate(P["hashes"])])
        v = np.c_[to_gl_vec(P["pos"]), np.ones(len(P["pos"]))]
        out = np.zeros((len(v), 3))
        for s in range(4):
            out += P["bw"][:, s:s + 1] * np.einsum("vab,vb->va", jm[P["bi"][:, s]], v)[:, :3]
        diff = out - to_gl_vec(P["pos"])
        off = np.median(diff, axis=0)                       # 部件网格空间相对骨架的整体平移（Unity 里同样存在）
        err = float(np.abs(diff - off).max())
        worst = max(worst, err)
        note = f"，含部件整体平移 {np.abs(off).max() * 1000:.2f} mm" if np.abs(off).max() > 1e-4 else ""
        log(f"      自检 {P['name']:8s}: 静止姿态蒙皮重投影最大误差 {err:.2e} m{note}" + ("  ✓" if err < 1e-3 else "  ✗ 不一致!"))

    # ------------------------------------------------------------------ #
    # 动画
    # ------------------------------------------------------------------ #
    anims, anim_names = [], Counter()
    pat = re.compile(args.clips) if args.clips else None
    sel_ids = [i for i in app if pat is None or pat.search(clips[i]["name"])]
    if not args.no_anim and sel_ids:
        log(f"[5/6] 写出动画 {len(sel_ids)}/{len(app)} 个（{args.fps:g} fps）…")
        blend_by_part = {P["name"]: {mo["hash"]: k for k, mo in enumerate(P["morphs"])} for P in parts if P["morphs"]}
        for k_, ci in enumerate(sel_ids):
            d = decoded.get(ci)
            cname = clips[ci]["name"]
            if not d or d.get("error"):
                log(f"      [跳过 clip] {cname}: {(d or {}).get('error', '未解码')}")
                continue
            tm, tr, bl = d["times"], d["tracks"], d["blend"]
            N = len(tm)
            tin = gl.add((tm - tm[0]).astype(np.float32), minmax=True)
            samplers, channels = [], []

            def emit(node, path, arr):
                samplers.append({"input": tin, "output": gl.add(arr), "interpolation": "LINEAR"})
                channels.append({"sampler": len(samplers) - 1, "target": {"node": node, "path": path}})
            for i, h in enumerate(H):
                v = tr.get(h)
                if v is None:
                    continue
                rp, rq = rest_loc[i]
                p_i = int(parent[i])
                pf = float(wsu_n[p_i]) if p_i >= 0 else 1.0           # 父骨骼若带缩放，子骨骼的局部位移要换算到单位骨骼
                rs = float(wsu_n[i]) / pf                              # 本骨骼相对父骨骼的静止缩放
                pos = v["pos"] * pf if v["pos"] is not None else None
                rot = qnorm(v["rot"]) if v["rot"] is not None else None
                if rot is not None:
                    rot = fix_continuity(rot)
                # ---- 根运动：某节点的水平位移范围超过阈值 -> 视为“根运动载体”，按 --root-motion 处理 ----
                if pos is not None and args.root_motion != "keep":
                    anchor = anchor0.get(i) if (parent[i] < 0 and not use_tos) else rp
                    cols = [0, 1, 2] if args.root_motion == "all" else [0, 2]          # all: 垂直位移(跳跃)也算根运动
                    if anchor is not None and float(np.ptp(pos[:, cols], axis=0).max()) > rm_thr:
                        pos = pos.copy()
                        pos[:, 0], pos[:, 2] = anchor[0], anchor[2]
                        if args.root_motion == "all":
                            pos[:, 1] = anchor[1]
                        rm_stat[names[i]] += 1
                        rm_clips.add(cname)
                if parent[i] < 0 and not use_tos and (pos is not None or rot is not None):   # 根骨骼：并入虚拟父节点
                    Mp = WP[i]
                    qP = mat_to_quat(Mp[:3, :3])
                    pp = pos if pos is not None else np.tile(np.zeros(3), (N, 1))
                    rr = rot if rot is not None else np.tile(np.array([0, 0, 0, 1.0]), (N, 1))
                    pos = pp @ Mp[:3, :3].T + Mp[:3, 3]
                    rot = fix_continuity(qnorm(qmul(np.tile(qP, (N, 1)), rr)))
                if pos is not None and np.abs(pos - rp).max() > 1e-4:
                    emit(i, "translation", to_gl_vec(pos).astype(np.float32))
                if rot is not None and qangle(rot, np.tile(rq, (N, 1))).max() > 0.1:
                    emit(i, "rotation", to_gl_quat(rot).astype(np.float32))
                if v["scl"] is not None:
                    scl = v["scl"] / rs                                # 相对静止缩放；等于 1 说明没有额外缩放动画
                    if np.abs(scl - 1).max() > 1e-4:
                        emit(i, "scale", scl.astype(np.float32))
            for pname, hm in blend_by_part.items():
                if any(h in bl for h in hm):
                    w = np.zeros((N, len(hm)), np.float32)
                    for h, k in hm.items():
                        if h in bl:
                            w[:, k] = bl[h] / 100.0
                    samplers.append({"input": tin, "output": gl.add(w.reshape(-1)), "interpolation": "LINEAR"})
                    channels.append({"sampler": len(samplers) - 1,
                                     "target": {"node": mesh_node_of[pname], "path": "weights"}})
            if not channels:
                continue
            short = re.sub(r"^(?:Ani_)?[A-Za-z]+_\d+_", "", cname)             # 去掉 Ani_<系列>_<编号>_ 前缀，动作名更短
            anim_names[short] += 1
            nm_ = short if anim_names[short] == 1 else f"{short}_{anim_names[short]}"
            anims.append({"name": nm_, "samplers": samplers, "channels": channels})
        if anims:
            doc["animations"] = anims
        if rm_clips:
            log(f"      根运动: {len(rm_clips)} 个动画含根运动，已按 --root-motion={args.root_motion} 处理"
                f"(阈值 {rm_thr:.2f}m；载体节点: {', '.join(f'{k}×{v}' for k, v in rm_stat.most_common(4))})")
    else:
        log("[5/6] 跳过动画")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    glb = out_dir / f"{tag}.glb"
    write_glb(glb, doc, gl)
    log(f"[6/6] 已写出 {glb}  ({glb.stat().st_size / 1e6:.2f} MB) | 骨骼 {n} | 部件 {len(parts)} | 动画 {len(anims)}")

    # 写出 Shell Fur 配置与独立 Blender 插件脚本（即使不在本机运行 Blender，也可直接安装进本地 Blender）
    fch_parts = [x.strip().lower() for x in (getattr(args, "fur_f_channels", None) or "a,a,a,a").split(",")]
    f_ch_dict = {
        "mask": fch_parts[0] if len(fch_parts) > 0 and fch_parts[0] in ("r", "g", "b", "a") else "a",
        "length": fch_parts[1] if len(fch_parts) > 1 and fch_parts[1] in ("r", "g", "b", "a") else "a",
        "strand": fch_parts[2] if len(fch_parts) > 2 and fch_parts[2] in ("r", "g", "b", "a") else "a",
        "ao": fch_parts[3] if len(fch_parts) > 3 and fch_parts[3] in ("r", "g", "b", "a") else "a",
        "preview": int(getattr(args, "fur_f_preview", 0) or 0),
    }
    ig_preset = (ingame_info or {}).get("in_game_preset") or {}
    mat_overrides = (ingame_info or {}).get("material_overrides") or {}
    layers_explicit = bool(getattr(args, "_fur_layers_explicit", False))
    length_explicit = bool(getattr(args, "_fur_length_explicit", False))
    cfg_layers = int(args.fur_layers) if layers_explicit else int(ig_preset.get("layers", args.fur_layers))
    cfg_length = float(args.fur_length) if length_explicit else float(ig_preset.get("length", args.fur_length))
    fur_cfg = {
        "enabled": bool(args.shell_fur),
        "tex_dir": os.path.abspath(args.tex_dir) if getattr(args, "tex_dir", None) else "",
        "layers": cfg_layers,
        "layers_explicit": layers_explicit,
        "viewport_layers": max(2, int(getattr(args, "fur_viewport_layers", 16) or 16)),
        "length": cfg_length,
        "length_explicit": length_explicit,
        "density": float(args.fur_density),
        "taper": float(args.fur_taper),
        "cutoff": float(args.fur_cutoff),
        "gravity": float(args.fur_gravity),
        "comb": float(getattr(args, "fur_comb", 0.55)),
        "root_ao": float(args.fur_root_ao),
        "mask_cull_threshold": float(getattr(args, "fur_mask_cull_threshold", 0.02)),
        "prefer_in_game": True,
        "fur_parts": [x.strip() for x in (args.fur_parts or "").split(",") if x.strip()],
        "fur_materials": [x.strip() for x in (args.fur_materials or "").split(",") if x.strip()],
        "mask_channel": args.fur_mask_channel,
        "f_channels": f_ch_dict,
        "pack_textures": bool(args.pack_textures),
        "bake_fbx_fur": bool(args.fbx_bake_fur),
        "in_game_preset": ig_preset,
        "material_overrides": mat_overrides,
    }
    with open(out_dir / "shellfur_config.json", "w", encoding="utf-8") as _sf:
        json.dump(fur_cfg, _sf, ensure_ascii=False, indent=1)
    (out_dir / "blender_import_shellfur.py").write_text(BLENDER_SHELLFUR_SCRIPT, encoding="utf-8")

    sk = [{"index": i, "hash": H[i], "name": names[i], "path": path_of.get(H[i]), "parent": int(parent[i]),
           "parent_hash": H[int(parent[i])] if parent[i] >= 0 else None,
           "extra_node": bool(is_extra[i]), "scale": round(float(wsu_n[i]), 4),
           "verified": bool(parent[i] >= 0 and i not in guessed), "guessed": i in guessed,
           "confidence": round(float(conf[i]), 3),
           "world_pos_unity": [round(float(x), 5) for x in W[i][:3, 3]]} for i in range(n)]
    with open(out_dir / "skeleton.json", "w", encoding="utf-8") as _skf:
        json.dump(sk, _skf, ensure_ascii=False, indent=1)
    with open(out_dir / "names_template.json", "w", encoding="utf-8") as _nmf:
        json.dump({str(h): path_of.get(h, "") for h in H}, _nmf, ensure_ascii=False, indent=1)
    with open(out_dir / "variant.json", "w", encoding="utf-8") as _vf:
        json.dump({"character": char, "variant_hash": vh, "lod": args.lod,
                   "parts": {P["name"]: P["mesh_name"] for P in parts}, "bones": n,
                   "hierarchy": {"source": "tos" if use_tos else "inferred", "verified": verified, "guessed": len(guessed),
                                 "roots": len(roots), "extra_nodes": n - n_skin, "scaled_bones": len(scaled_idx)},
                   "root_motion": {"mode": args.root_motion, "threshold_m": round(float(rm_thr), 3),
                                   "clips_affected": len(rm_clips), "carriers": dict(rm_stat)},
                   "part_offsets_baked": bake_info,
                   "shell_fur": fur_cfg,
                   "animations_applicable": len(app), "animations_written": len(anims),
                   "rest_pose_max_error_m": worst}, _vf, ensure_ascii=False, indent=1)
    return {"glb": glb, "bones": n, "anims": len(anims), "guessed": len(guessed), "variant": vh, "tag": tag}


# =========================================================================== #
# 一个角色：发现变体 -> 选 LOD -> 适配动画 -> 逐变体构建
# =========================================================================== #
def run_char(args, char, meshes, clips, tos, plat, mat_ctx, pool, log):
    if not meshes:
        log(f"[!] 角色 {char}: 没有找到 Mesh")
        return []
    infos = pmap(pool, t_mesh_info, [(m["file"], m["fname"], m["pid"]) for m in meshes])
    lod0, all_by, bad = defaultdict(dict), defaultdict(list), 0
    for m, info in zip(meshes, infos):
        pr = parse_mesh_name(m["name"])
        if info.get("error") or not pr:
            bad += 1
            continue
        part, lod, h = pr
        rec = {**m, **info, "part": part, "lod": lod, "hash": h}
        all_by[(part, lod)].append(rec)
        if lod == 0:
            lod0[h][part] = rec
    if not lod0 and all_by:
        anchor_lod = min(l for (_, l) in all_by)
        for (p, l), rs in all_by.items():
            if l == anchor_lod:
                for rec in rs:
                    lod0[rec["hash"]][p] = rec
        log(f"      [提示] 资产 {char} 无 LOD0 网格，已改用 LOD{anchor_lod} 作为基准变体")
    if not lod0:
        log(f"[!] 角色 {char}: 没有可用的 Mesh（无法确定变体）")
        return []
    variants = sorted(lod0)
    if args.variant:
        want = {int(x) for x in args.variant.split(",")}
        variants = [v for v in variants if v in want]
        if not variants:
            log(f"[!] 角色 {char}: 没有指定的变体 {sorted(want)}；可用: {sorted(lod0)}")
            return []

    # ---- 变体总览 ----
    log(f"\n===== 角色 {char}：发现 {len(lod0)} 个变体（按 LOD0 Mesh 后缀区分）=====")
    for v in sorted(lod0):
        ps = lod0[v]
        skel = set().union(*[set(r["bones"]) for r in ps.values()])
        lods = sorted({lod for (p, lod), rs in all_by.items() if p in ps and any(r["hash"] == v or set(r["bones"]) <= skel for r in rs)})
        mark = "" if v in variants else "  (已按 --variant 排除)"
        cdir = sorted({r["container"].rsplit("/", 2)[-2] if "/" in r["container"] else "?" for r in ps.values()})
        log(f"  变体 {v:>12d}: 部件 {sorted(ps)} | 骨骼 {len(skel)} | LOD {lods} | 目录 {cdir}{mark}")
    if args.list_variants:
        return []

    # ---- 动画：探测一次，各变体各自判定适配 ----
    log(f"[2/6] 探测 {len(clips)} 个动画 …")
    probes = pmap(pool, t_probe_clip, [(c["file"], c["fname"], c["pid"]) for c in clips])
    for c, p in zip(clips, probes):
        if p.get("error"):
            log(f"      [跳过 clip] {c['name']}: {p['error']}")
    pat = re.compile(args.clips) if args.clips else None
    plan = {}
    for v in variants:
        skel = set().union(*[set(r["bones"]) for r in lod0[v].values()])
        app = [i for i, p in enumerate(probes) if not p.get("error") and applicable_clip(p["binds"], skel)]
        plan[v] = app
        log(f"  变体 {v:>12d}: 适配动画 {len(app)}/{len(clips)} 个")
        miss = [(clips[i]["name"], len(p["binds"] & skel), len(p["binds"])) for i, p in enumerate(probes)
                if not p.get("error") and i not in set(app)]
        if miss:
            miss_pat = re.compile(r"^(?:Ani_)?[A-Za-z]+_\d+_")
            log("      不适配: " + ", ".join(f"{miss_pat.sub('', n)}(命中{h}/{t}轨道)" for n, h, t in miss[:6])
                + (f" 等 {len(miss)} 个" if len(miss) > 6 else ""))
    need = sorted({i for v in variants for i in plan[v] if pat is None or pat.search(clips[i]["name"])}) if not args.no_anim else []
    if need:
        log(f"      解码 {len(need)} 个动画曲线（{args.fps:g} fps）…")
    res = pmap(pool, t_decode_clip, [(clips[i]["file"], clips[i]["fname"], clips[i]["pid"], args.fps) for i in need])
    decoded = dict(zip(need, res))

    outs = []
    for v in variants:
        log(f"\n----- 变体 {v} -----")
        parts_lod0 = lod0[v]
        skel_parts = sorted(parts_lod0.values(), key=lambda r: -len(r["bones"]))
        if args.lod == 0:
            sel = dict(parts_lod0)
        else:
            sel = pick_lod(v, parts_lod0, all_by, args.lod, args.lod_hash, log)
        if args.parts:
            keep = {p.strip() for p in args.parts.split(",")}
            sel = {k: r for k, r in sel.items() if k in keep}
        if not sel:
            log(f"      [!] 该变体在 LOD{args.lod} 下没有可用部件，跳过")
            continue
        log(f"[1/6] 部件(LOD{args.lod}): " + ", ".join(f"{p}[{r['hash']}]" for p, r in sorted(sel.items())))
        out_dir = Path(args.output) / f"{safe_name(char)}_{v}"
        r_ = build_variant(args, char, v, skel_parts, sel, probes, clips, plan[v], decoded, tos, plat, mat_ctx, pool, out_dir, log)
        if r_:
            outs.append(r_)
    return outs


def run(args, log):
    tokens = [c.strip() for item in (args.character or []) for c in item.split(",") if c.strip()]
    if not tokens and not args.list_characters:
        sys.exit("[!] 请用 -c 指定角色，例如 -c Parmon_10583（编号）、-c Parmon（整个系列）、-c all；"
                 "不确定时先用 --list-characters 查看包里有哪些角色")
    if args.shell_fur and not args.blend and not args.fbx:
        args.blend = True
    jobs = min(os.cpu_count() or 1, 8) if args.jobs == 0 else max(1, args.jobs)
    pool = ProcessPoolExecutor(max_workers=jobs) if jobs > 1 else None
    outs = []
    try:
        files = list_bundles(args.inputs)
        log(f"[*] 脚本版本: {SCRIPT_VERSION} [ShellFur完整版] | 丝滑绒毛 + Alpha面片隔离 + TEMPERANCE骨骼朝向")
        log(f"[*] 发现 {len(files)} 个 bundle | 并行进程 {jobs}")

        def parent_id(tok):                                   # Parmon_1058301 -> Parmon_10583（仅限 6 位及以上衍生编号）
            m = re.match(r"^([A-Za-z]+_)(\d+)", tok)
            if not m:
                return None
            return _derive_parent_char_id(f"{m.group(1)}{m.group(2)}")
        # 扫描用的 token：请求的 + 其本体编号（只为借用动画）+ --anim-from
        scan_tokens = list(dict.fromkeys(tokens + [parent_id(t) for t in tokens if parent_id(t)] +
                                         ([args.anim_from] if args.anim_from else [])))

        # ---- 本地轻量索引缓存 (.uab_scan_cache.json, version=3) ----
        cache_base = Path(args.inputs[0]) if len(args.inputs) == 1 and os.path.isdir(args.inputs[0]) else Path(args.output)
        cache_file = cache_base / ".uab_scan_cache.json"
        fallback_cache = Path(args.output) / ".uab_scan_cache.json"
        cached_files = {}
        if not getattr(args, "no_cache", False):
            for cf in (cache_file, fallback_cache):
                if cf.is_file():
                    try:
                        cobj = json.loads(cf.read_text(encoding="utf-8"))
                        if cobj.get("version") == 3 and isinstance(cobj.get("files"), dict):
                            cached_files.update(cobj["files"])
                            break
                    except Exception:
                        pass

        scans = [None] * len(files)
        uncached_idx = []
        file_stats = {}
        for idx, f in enumerate(files):
            ap = os.path.abspath(f)
            try:
                st = os.stat(f)
                sig = (int(st.st_size), int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))))
            except Exception:
                sig = None
            file_stats[ap] = sig
            ent = cached_files.get(ap) if (not getattr(args, "no_cache", False) and sig is not None) else None
            if ent and ent.get("size") == sig[0] and ent.get("mtime_ns") == sig[1] and isinstance(ent.get("data"), dict):
                scans[idx] = ent["data"]
            else:
                uncached_idx.append(idx)

        if uncached_idx:
            new_scans = pmap(pool, t_scan_bundle_index, [(files[idx],) for idx in uncached_idx])
            for idx, sc in zip(uncached_idx, new_scans):
                scans[idx] = sc
                ap = os.path.abspath(files[idx])
                sig = file_stats.get(ap)
                if not sc.get("error") and sig is not None:
                    cached_files[ap] = {"size": sig[0], "mtime_ns": sig[1], "data": sc}
            if not getattr(args, "no_cache", False):
                payload = json.dumps({"version": 3, "files": cached_files}, ensure_ascii=False)
                for cf in (cache_file, fallback_cache):
                    try:
                        cf.parent.mkdir(parents=True, exist_ok=True)
                        cf.write_text(payload, encoding="utf-8")
                        break
                    except Exception:
                        continue
        if not getattr(args, "no_cache", False) and len(files) > 0:
            log(f"    索引缓存命中 {len(files) - len(uncached_idx)}/{len(files)} 个 bundle")

        allchars, tos = Counter(), {}
        by_dir = defaultdict(lambda: {"meshes": [], "clips": [], "match_tokens": set()})
        externals, externals_low, externals_by_file = {}, {}, {}
        mat_by_fname_pid, mat_by_fname_low_pid, mat_by_pid = {}, {}, {}
        mat_by_name, mat_by_name_low = defaultdict(list), defaultdict(list)
        tex_by_fname_pid, tex_by_fname_low_pid, tex_by_pid = {}, {}, {}
        all_textures, all_avatars, all_renderers = [], [], []
        asset_char_files = set()
        for sc in scans:
            if not sc or sc.get("error"):
                if sc:
                    log(f"  [跳过] {os.path.basename(sc['file'])}: {sc['error']}")
                continue
            sc_file = sc["file"]
            allchars.update(sc.get("chars", {}))
            for fn, exts in (sc.get("externals") or {}).items():
                externals[fn] = exts
                externals_low[fn.lower()] = exts
                externals_by_file[(sc_file, fn)] = exts
            for mr in sc.get("materials", []):
                mat_by_fname_pid[(mr["fname"], mr["pid"])] = mr
                mat_by_fname_low_pid[(mr["fname"].lower(), mr["pid"])] = mr
                mat_by_pid.setdefault(mr["pid"], mr)
                if mr["name"]:
                    mat_by_name[mr["name"]].append(mr)
                    mat_by_name_low[mr["name"].lower()].append(mr)
                if pick_char_dir(tokens, (mr.get("container") or "").split("/")):
                    asset_char_files.add(sc_file)
            for tr in sc.get("textures", []):
                tex_by_fname_pid[(tr["fname"], tr["pid"])] = tr
                tex_by_fname_low_pid[(tr["fname"].lower(), tr["pid"])] = tr
                tex_by_pid.setdefault(tr["pid"], tr)
                all_textures.append(tr)
            for av in sc.get("avatars", []):
                all_avatars.append(av)
                if pick_char_dir(tokens, (av.get("container") or "").split("/")):
                    asset_char_files.add(sc_file)
            all_renderers.extend(sc.get("renderers", []))
            for m in sc.get("meshes", []):
                hit = pick_char_dir(scan_tokens, m.get("segs", []), m.get("name", "")) if scan_tokens else None
                if hit is not None:
                    by_dir[hit[1]]["meshes"].append({**m, "char_dir": hit[1]})
                    by_dir[hit[1]]["match_tokens"].add(hit[0].lower())
            for c in sc.get("clips", []):
                hit = pick_char_dir(scan_tokens, c.get("segs", [])) if scan_tokens else None
                if hit is not None:
                    by_dir[hit[1]]["clips"].append({**c, "char_dir": hit[1]})
                    by_dir[hit[1]]["match_tokens"].add(hit[0].lower())

        if args.list_characters:
            log("\n包里发现的角色/资产目录（按 Mesh 数量）:")
            for c, k in allchars.most_common():
                log(f"  {c:32s} Mesh {k}")
            return 0

        # 请求的目标目录：既匹配带数字编号的角色目录，也保留道具等无编号资产的独立子目录
        tok_lows = {t.lower() for t in tokens}
        want_dirs = []
        for d, v in sorted(by_dir.items()):
            if v["meshes"] and (bool(v["match_tokens"] & tok_lows) or any(token_match(t, d) for t in tokens)):
                want_dirs.append(d)
        if not want_dirs:
            near = [k for k, _ in allchars.most_common()][:10]
            log(f"[!] 没有找到匹配 {tokens} 的角色或资产目录；示例: {near or '无'}（--list-characters 可查看全部）")
            return 1
        log(f"[*] 将处理 {len(want_dirs)} 个资产目录: {', '.join(want_dirs[:12])}" + (" …" if len(want_dirs) > 12 else ""))

        target_mesh_files = {m["file"] for d in want_dirs for m in by_dir[d]["meshes"]}
        target_fnames = {m["fname"] for d in want_dirs for m in by_dir[d]["meshes"] if m.get("fname")}
        target_fnames_low = {f.lower() for f in target_fnames}
        target_fnames_stem_low = {f.lower().rsplit(".", 1)[0] for f in target_fnames}
        rel_bundle_files = target_mesh_files | asset_char_files

        # ---- 按需读取目标角色 Avatar(TOS) ----
        if not args.no_tos and all_avatars:
            prio_avs, rest_avs = [], []
            for av in all_avatars:
                segs = (av.get("container") or "").split("/")
                if av["file"] in target_mesh_files or any(token_match(t, s) for s in segs for t in scan_tokens):
                    prio_avs.append(av)
                else:
                    rest_avs.append(av)
            av_src = prio_avs or rest_avs
            if av_src:
                av_by_file = defaultdict(list)
                for av in av_src:
                    av_by_file[av["file"]].append((av["file"], av["fname"], av["pid"]))
                for td in pmap(pool, t_read_avatars, [(items,) for items in av_by_file.values()]):
                    tos.update(td)
            if not tos and not args.tos_json and prio_avs and rest_avs:
                av_by_file = defaultdict(list)
                for av in rest_avs:
                    av_by_file[av["file"]].append((av["file"], av["fname"], av["pid"]))
                for td in pmap(pool, t_read_avatars, [(items,) for items in av_by_file.values()]):
                    tos.update(td)

        if args.tos_json:
            with open(args.tos_json, encoding="utf-8") as _tf:
                extra = json.load(_tf)
            tos.update({int(k): str(v) for k, v in extra.items() if v})

        # ---- 按需读取目标角色 Renderer（绑定 Mesh -> Material） ----
        rend_by_mesh, rend_by_mesh_low, rend_by_mesh_pid = {}, {}, {}
        if not args.no_textures and not args.list_variants and all_renderers:
            rel_renderers = []
            for rr in all_renderers:
                if rr["file"] in rel_bundle_files:
                    rel_renderers.append(rr)
                    continue
                exts = (externals_by_file.get((rr["file"], rr["fname"]))
                        or externals.get(rr["fname"])
                        or externals_low.get(rr["fname"].lower(), []))
                if any((ext.lower() in target_fnames_low or ext.lower().rsplit(".", 1)[0] in target_fnames_stem_low) for ext in exts if ext):
                    rel_renderers.append(rr)
                    continue
                segs = (rr.get("container") or "").split("/")
                if any(token_match(t, s) for s in segs for t in tokens):
                    rel_renderers.append(rr)
            if rel_renderers:
                r_by_file = defaultdict(list)
                for rr in rel_renderers:
                    r_by_file[rr["file"]].append((rr["file"], rr["fname"], rr["pid"], rr.get("container", "")))
                for chunk in pmap(pool, t_read_renderers, [(items,) for items in r_by_file.values()]):
                    for rr in chunk:
                        mfid, mpid = rr["mesh"]
                        mfname = rr["fname"]
                        if mfid > 0:
                            exts = (externals_by_file.get((rr["file"], rr["fname"]))
                                    or externals.get(rr["fname"])
                                    or externals_low.get(rr["fname"].lower(), []))
                            if mfid - 1 < len(exts) and exts[mfid - 1]:
                                mfname = exts[mfid - 1]
                        rend_by_mesh[(mfname, mpid)] = rr
                        rend_by_mesh_low[(mfname.lower(), mpid)] = rr
                        if "." in mfname:
                            rend_by_mesh_low[(mfname.lower().rsplit(".", 1)[0], mpid)] = rr
                        rend_by_mesh_pid.setdefault(mpid, rr)

        mat_ctx = {
            "externals": externals,
            "externals_low": externals_low,
            "externals_by_file": externals_by_file,
            "mat_lookup": {"externals": externals, "externals_low": externals_low, "externals_by_file": externals_by_file,
                           "by_fname_pid": mat_by_fname_pid, "by_fname_low_pid": mat_by_fname_low_pid, "by_pid": mat_by_pid},
            "tex_lookup": {"externals": externals, "externals_low": externals_low, "externals_by_file": externals_by_file,
                           "by_fname_pid": tex_by_fname_pid, "by_fname_low_pid": tex_by_fname_low_pid, "by_pid": tex_by_pid},
            "textures": all_textures,
            "mat_by_name": mat_by_name,
            "mat_by_name_low": mat_by_name_low,
            "rend_by_mesh": rend_by_mesh,
            "rend_by_mesh_low": rend_by_mesh_low,
            "rend_by_mesh_pid": rend_by_mesh_pid,
        }

        plat = load_platform_materials(args.platform)
        for d in want_dirs:
            v = by_dir[d]
            clips_c = list(v["clips"])
            src_dirs = []
            if args.anim_from:
                src_dirs = [x for x in by_dir if x != d and token_match(args.anim_from, x) and by_dir[x]["clips"]]
            elif not clips_c:
                m = CHAR_SEG_RE.match(d)
                pid = parent_id(m.group("c")) if m else None
                if pid:
                    src_dirs = [x for x in by_dir if x != d and token_match(pid, x) and by_dir[x]["clips"]]
            for x in src_dirs:
                clips_c += by_dir[x]["clips"]
            if src_dirs:
                log(f"\n[*] {d} 自带动画 {len(v['clips'])} 个，借用 {', '.join(src_dirs)} 的动画 {len(clips_c) - len(v['clips'])} 个"
                    "（衍生角色共用本体动画，按骨骼哈希匹配；仅驱动共有骨骼）")
            log(f"\n[*] 角色目录 {d}: Mesh {len(v['meshes'])} | AnimationClip {len(clips_c)} | Avatar(TOS) 骨骼名 {len(tos)} 条")
            outs += run_char(args, d, v["meshes"], clips_c, tos, plat, mat_ctx, pool, log)
    finally:
        if pool:
            pool.shutdown()
    if args.list_variants:
        return 0
    if not outs:
        log("[!] 没有生成任何模型")
        return 1
    if args.fbx or args.blend:
        bl = find_blender(args.blender)
        if not bl:
            log("[Blender] 没找到 Blender：请安装 Blender 后用 --blender 指定路径；"
                "或直接在目标 Blender 里运行各输出目录中的 blender_import_shellfur.py 导入模型与 Shell Fur")
            if args.fbx:
                return 2
        else:
            def conv(o):
                buf = []
                ok = run_blender_pipeline(
                    o["glb"], bl, buf.append, fps=args.fps,
                    want_blend=args.blend, want_fbx=args.fbx, verify=not args.no_verify,
                )
                return o, buf, ok
            with ThreadPoolExecutor(max_workers=max(1, min(jobs, len(outs)))) as ex:
                for o, buf, ok in ex.map(conv, outs):
                    log(f"\n[Blender] {o['tag']}:")
                    for line in buf:
                        log("  " + line)
    log("\n===== 完成 =====")
    for o in outs:
        log(f"  {o['tag']:44s} 骨骼 {o['bones']:3d} 动画 {o['anims']:3d} 猜测父骨骼 {o['guessed']:2d}  {o['glb']}")
    return 0


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="从 Unity .uab 重建带骨骼/权重/动画/Shell Fur 材质的角色模型 (GLB/BLEND/FBX)",
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("示例", 1)[1])
    ap.add_argument("inputs", nargs="+", help=".uab 文件或目录（Mesh 包 + 动画包放一起即可）")
    ap.add_argument("-c", "--character", nargs="+", help="角色：编号(Parmon_10583)、系列(Parmon，处理该系列全部角色)、完整目录名(Parmon_10583_LeafSheep)或 all；可写多个")
    ap.add_argument("-o", "--output", default="./model_out", help="输出目录（每个变体一个子目录 <角色>_<变体后缀>）")
    ap.add_argument("-j", "--jobs", type=int, default=0, help="并行进程数（默认 0=自动多核，上限 8）")
    ap.add_argument("--anim-from", help="借用另一个角色的动画，如 --anim-from Parmon_10583（默认：衍生角色自动借用编号去掉末两位的本体）")
    ap.add_argument("--list-characters", action="store_true", help="只列出包里发现的角色标识，不导出")
    ap.add_argument("--list-variants", action="store_true", help="只列出该角色的变体（按 LOD0 Mesh 后缀），不导出")
    ap.add_argument("--variant", help="只导出指定变体（LOD0 Mesh 后缀，逗号分隔）；后缀为负数时请用等号：--variant=-688515594,-1350362960")
    ap.add_argument("--lod", type=int, default=0, help="使用的 LOD 级别（默认 0 最高精度）")
    ap.add_argument("--lod-hash", type=int, help="LOD>0 出现多个兼容候选时，强制使用该后缀的 Mesh")
    ap.add_argument("--parts", help="只导出指定部件，逗号分隔，如 Body,Eye（默认全部）")
    ap.add_argument("--clips", help="只导出名称匹配该正则的动画，如 'Idle|Walk|Run'")
    ap.add_argument("--fps", type=float, default=30.0, help="动画采样帧率（默认 30；源动画为 60fps，高于 60 无额外信息）")
    ap.add_argument("--no-anim", action="store_true", help="不导出动画")
    ap.add_argument("--root-motion", choices=["xz", "all", "keep"], default="xz",
                    help="根运动处理：xz=去掉水平位移做成原地动画(默认)；all=连垂直位移也去掉；keep=原样保留")
    ap.add_argument("--root-motion-threshold", type=float, help="判定“根运动载体”的位移阈值(米)，默认 max(0.15, 0.3×模型高度)")
    ap.add_argument("--tos-json", help="骨骼路径表 JSON {哈希: 完整路径}（Avatar 的 TOS 导出），提供后用路径还原精确层级与骨骼名")
    ap.add_argument("--no-tos", action="store_true", help="即使有 Avatar(TOS) 也不用它还原层级（仅用于对比验证）")
    ap.add_argument("--no-guess", action="store_true", help="不对无法用动画验证的骨骼做几何猜测（它们将作为根骨骼保持静止）")
    ap.add_argument("--names", help="骨骼名映射 JSON：{哈希: 名称} 或 路径列表 ['Bip001/Bip001 Pelvis', ...]")
    ap.add_argument("--platform", nargs="*", help="PlatformData JSON（文件/目录），用于给材质命名")
    ap.add_argument("--no-textures", action="store_true", help="不提取 Material 参数与 Texture2D 贴图")
    ap.add_argument("--all-char-textures", action="store_true", help="导出同角色目录所有 Texture2D（默认仅导出材质实际引用的贴图以大幅提速）")
    ap.add_argument("--no-cache", action="store_true", help="禁用 .uab_scan_cache.json 扫描索引磁盘缓存")
    ap.add_argument("--tex-dir", help="额外手选贴图文件夹路径（作为 .uab 贴图的补充/兜底匹配源）")
    ap.add_argument("--blend", action="store_true", help="生成带材质贴图映射的 Blender 工程文件 (.blend，需要 Blender)")
    ap.add_argument("--pack-textures", action="store_true", help="保存 .blend 时将贴图打包进工程文件内")
    ap.add_argument("--shell-fur", action="store_true", help="在 Blender 中构建 Shell Fur 壳层毛发(Geometry Nodes + 分层着色器映射)，默认同时启用 --blend")
    ap.add_argument("--fur-layers", type=int, default=36, help="Shell Fur 渲染满层数量（默认 36，层数越高毛丝越丝滑无台阶感）")
    ap.add_argument("--fur-viewport-layers", type=int, default=16, help="Shell Fur 视口轻量壳层数（默认 16，兼顾高密丝滑质感与实时流畅度；渲染自动使用 --fur-layers）")
    ap.add_argument("--fur-mask-cull-threshold", type=float, default=0.02, help="Shell Fur 无毛面提前剔除阈值（默认 0.02，降低壳层总面数）")
    ap.add_argument("--fur-length", type=float, default=0.009, help="Shell Fur 毛发最大长度，单位米（默认 0.009；未显式指定时优先采用材质 _FurLength）")
    ap.add_argument("--fur-density", type=float, default=44.0, help="Shell Fur 超高频微发丝密度（默认 44.0）")
    ap.add_argument("--fur-taper", type=float, default=1.45, help="Shell Fur 发梢收尖指数（默认 1.45，越大根部越密、发梢越尖细）")
    ap.add_argument("--fur-cutoff", type=float, default=0.16, help="Shell Fur 底层透明裁剪阈值（默认 0.16）")
    ap.add_argument("--fur-gravity", type=float, default=0.0035, help="Shell Fur 重力垂坠偏移量，单位米（默认 0.0035）")
    ap.add_argument("--fur-comb", type=float, default=0.55, help="基于 *_F.(R,G) 切线流向贴图的丝滑顺毛倾斜强度（默认 0.55）")
    ap.add_argument("--fur-root-ao", type=float, default=0.28, help="Shell Fur 根部 AO 暗化强度 0~1（默认 0.28）")
    ap.add_argument("--fur-parts", help="强制启用 Shell Fur 的部件名（逗号分隔，如 Body,Tail；会自动排除 Shiny/Eye/Crystal/02a 等非毛发材质）")
    ap.add_argument("--fur-materials", help="额外匹配为毛发材质的正则/名称（逗号分隔，如 Fur,01a）")
    ap.add_argument("--fur-mask-channel", choices=["auto", "r", "g", "b", "a", "none"], default="auto",
                    help="无 *_F 贴图时用顶点色通道控制 3D 毛发长度遮罩（默认 auto：有 *_F/_FurMask 贴图时优先用贴图驱动）")
    ap.add_argument("--fur-f-channels", default="a,a,a,a",
                    help="指定 *_F 贴图默认通道分配: mask,length,strand,ao（默认 a,a,a,a 匹配 Unity Alpha 长度遮罩并自动增益；R/G 自动用于切线顺毛流向）")
    ap.add_argument("--fur-f-preview", type=int, choices=[0, 1, 2, 3, 4], default=0,
                    help="*_F 贴图默认通道预览模式: 0=正常毛发, 1=R, 2=G, 3=B, 4=A（默认 0）")
    ap.add_argument("--fbx", action="store_true", help="同时转出 FBX（需要 Blender）")
    ap.add_argument("--fbx-bake-fur", action="store_true", help="导出 FBX 时将 ShellFur 修改器烘焙为实际多层网格（默认仅在 .blend 中保留实时修改器）")
    ap.add_argument("--blender", help="Blender 可执行文件路径（默认从 PATH 查找）")
    ap.add_argument("--no-verify", action="store_true", help="转出 FBX 后不回读校验")
    raw_argv = sys.argv[1:]
    args = ap.parse_args(raw_argv)
    args._fur_layers_explicit = any(a == "--fur-layers" or a.startswith("--fur-layers=") for a in raw_argv)
    args._fur_length_explicit = any(a == "--fur-length" or a.startswith("--fur-length=") for a in raw_argv)
    return run(args, lambda s: print(s, flush=True))


if __name__ == "__main__":
    sys.exit(main())
