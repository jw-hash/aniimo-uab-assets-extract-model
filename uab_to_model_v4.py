#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
uab_to_model.py v2 —— 从 Unity .uab 重建带「骨骼 + 蒙皮权重 + BlendShape + 动画」的角色模型

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

依赖：pip install UnityPy numpy        （转 FBX 需要 Blender，可用 --blender 指定路径）

示例
  python uab_to_model.py ./bundles --list-characters
  python uab_to_model.py ./bundles -c Parmon_10583 --list-variants
  python uab_to_model.py ./bundles -c Parmon -o ./out -j 4 --fbx          # 整个 Parmon 系列，每个角色目录各出一份
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


def read_part(obj, mesh_name, part, lod):
    t = obj.read_typetree()
    h = MeshHandler(obj.read())
    h.process()
    P = {"name": part, "mesh_name": mesh_name, "lod": lod}
    P["pos"] = np.asarray(h.m_Vertices, np.float64).reshape(-1, 3)
    nv = len(P["pos"])
    P["nrm"] = np.asarray(h.m_Normals, np.float64).reshape(nv, -1)[:, :3] if h.m_Normals is not None else None
    P["uv"] = np.asarray(h.m_UV0, np.float64).reshape(nv, -1)[:, :2] if h.m_UV0 is not None else None
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
# 并行基础设施：每个进程缓存已加载的 bundle；任务只传 (文件, 序列化文件名, path_id)，便于多进程
# =========================================================================== #
_ENV_CACHE = {}


def _cache_env(file, env, idx):
    if len(_ENV_CACHE) >= 6:                                 # 只缓存最近几个 bundle，防止内存无限增长
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
    """有进程池就并行，否则顺序执行；结果顺序与参数顺序一致。"""
    if pool is None:
        return [fn(*a) for a in arglist]
    futs = [pool.submit(fn, *a) for a in arglist]
    return [f.result() for f in futs]


MESH_TOKEN_RE = re.compile(r"^M_(?P<c>[A-Za-z]+_\d+)_")
CHAR_SEG_RE = re.compile(r"^(?P<c>[A-Za-z]+_\d+)(?:_|$)")      # 角色目录名：Parmon_1058301_LeafSheep


def token_match(token, seg):
    """目录名 seg 是否属于 token：全名相等 / 以 'token_' 开头（id 或系列前缀）。
    Parmon_10583 匹配 Parmon_10583_LeafSheep，但不匹配 Parmon_1058301_LeafSheep；Parmon 匹配全部 Parmon_*。"""
    if token in ("all", "*"):
        return bool(CHAR_SEG_RE.match(seg))
    return seg == token or seg.startswith(token + "_")


def pick_char_dir(tokens, segs):
    """在容器目录的各级名称里挑出角色目录（优先形如 <系列>_<编号>[_*] 的那一级）。返回 (token, 目录名) 或 None"""
    for t in tokens:
        cands = [x for x in segs if token_match(t, x)]
        if not cands:
            continue
        good = [x for x in cands if CHAR_SEG_RE.match(x)]
        return t, (good or cands)[0]
    return None


def t_scan(file, tokens):
    """扫描一个 bundle：返回与各角色相关的 Mesh / AnimationClip 条目、Avatar 骨骼名表、角色目录统计。"""
    out = {"file": file, "meshes": [], "clips": [], "tos": {}, "chars": {}, "error": None}
    try:
        env = UnityPy.load(file)
        objs = list(env.objects)
        _cache_env(file, env, {(getattr(o.assets_file, "name", ""), o.path_id): o for o in objs})
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        return out
    cmap = container_paths(env)
    chars = Counter()
    for obj in objs:
        tn = obj.type.name
        if tn not in ("Mesh", "AnimationClip", "Avatar"):
            continue
        fname = getattr(obj.assets_file, "name", "")
        if tn == "Avatar":
            try:                                        # TOS: 路径哈希 -> 完整路径，既给骨骼名也给精确层级
                for h, path in obj.read_typetree().get("m_TOS", []):
                    out["tos"][int(h)] = str(path)
            except Exception:
                pass
            continue
        name = obj.peek_name() or ""
        cp = cmap.get((fname, obj.path_id), "")
        segs = cp.rsplit("/", 1)[0].split("/") if "/" in cp else []
        if not segs:                                    # 没有容器路径：退回用资产名里的 M_<系列>_<编号>_ 推断
            m = MESH_TOKEN_RE.match(name) if tn == "Mesh" else None
            segs = [m.group("c")] if m else []
        # 角色归属只看容器路径的“目录”部分：衍生角色(如 Parmon_1058301)的 Mesh 文件名仍沿用本体前缀 M_Parmon_10583_
        if tn == "Mesh" and segs and CHAR_SEG_RE.match(segs[-1]):
            chars[segs[-1]] += 1
        hit = pick_char_dir(tokens, segs)
        if hit:
            out["meshes" if tn == "Mesh" else "clips"].append(
                {"token": hit[0], "char_dir": hit[1], "file": file, "fname": fname, "pid": obj.path_id,
                 "name": name, "container": cp, "bundle": os.path.basename(file)})
    out["chars"] = dict(chars)
    return out


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
        return read_part(_get_obj(file, fname, pid), mesh_name, part, lod)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}", "name": part}


# =========================================================================== #
# 变体 / LOD 归属
# =========================================================================== #
MESH_NAME_RES = (
    re.compile(r"^M_(?P<base>.+?)_(?P<part>[A-Za-z]+\d*)(?:_LOD(?P<lod>\d+))?_(?P<hash>-?\d+)$"),
    re.compile(r"^M_(?P<base>[A-Za-z]+_\d+)_(?P<part>.+?)(?:_LOD(?P<lod>\d+))?_(?P<hash>-?\d+)$"),   # 部件名含下划线时的兜底
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
# GLB -> FBX（借助 Blender，无界面运行）
# =========================================================================== #
BLENDER_SCRIPT = r'''
import bpy, sys
argv = sys.argv[sys.argv.index("--") + 1:]
src, dst = argv[0], argv[1]
fps = float(argv[2]) if len(argv) > 2 else 30.0
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.context.scene.render.fps = int(round(fps))          # 烘焙按场景帧率采样，默认 24 会让 30fps 动画被重采样
bpy.context.scene.render.fps_base = 1.0
bpy.ops.import_scene.gltf(filepath=src)
arm = [o for o in bpy.data.objects if o.type == 'ARMATURE']
# glTF 导入器会给骨骼生成自定义显示形状(Icosphere)，它不属于模型，删除以免被导出成多余网格
shapes = set()
for a in arm:
    for pb in a.pose.bones:
        if pb.custom_shape is not None:
            shapes.add(pb.custom_shape)
            pb.custom_shape = None
for o in shapes:
    bpy.data.objects.remove(o, do_unlink=True)
# 将每个 Action 保证带 fake user，导出时全部烘焙
for a in bpy.data.actions:
    a.use_fake_user = True
bpy.ops.export_scene.fbx(
    filepath=dst, use_selection=False, object_types={'ARMATURE', 'MESH'},
    add_leaf_bones=False, bake_anim=True, bake_anim_use_all_actions=True,
    bake_anim_use_nla_strips=False, bake_anim_force_startend_keying=True,
    bake_anim_simplify_factor=0.0, mesh_smooth_type='FACE',
    axis_forward='-Z', axis_up='Y', path_mode='COPY')
print("FBX_EXPORT_OK", dst, "armatures:", len(arm), "actions:", len(bpy.data.actions))
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


def to_fbx(glb, blender, log, fps=30.0, verify=True):
    fbx = glb.with_suffix(".fbx")
    with tempfile.TemporaryDirectory() as td:
        sp = Path(td) / "conv.py"
        sp.write_text(BLENDER_SCRIPT, encoding="utf-8")
        log(f"[FBX] 调用 Blender 转换: {blender}")
        r = subprocess.run([blender, "-b", "--factory-startup", "--python", str(sp), "--", str(glb), str(fbx), str(fps)],
                           capture_output=True, text=True)
        if "FBX_EXPORT_OK" not in r.stdout:
            log("[FBX] 转换失败:\n" + (r.stdout[-1500:] + r.stderr[-1500:]))
            return None
        log("[FBX] " + [l for l in r.stdout.splitlines() if "FBX_EXPORT_OK" in l][0])
        if verify:
            vp = Path(td) / "verify.py"
            vp.write_text(BLENDER_VERIFY, encoding="utf-8")
            r2 = subprocess.run([blender, "-b", "--factory-startup", "--python", str(vp), "--", str(fbx)],
                                capture_output=True, text=True)
            for l in r2.stdout.splitlines():
                if l.startswith("VERIFY"):
                    log("[FBX] " + l)
    log(f"[FBX] 已写出 {fbx} ({fbx.stat().st_size / 1e6:.2f} MB)")
    return fbx



# =========================================================================== #
# 单个变体的重建：骨架 + 层级 + 网格/蒙皮 + 动画 -> GLB
# =========================================================================== #
def build_variant(args, char, vh, skel_parts, sel_recs, probes, clips, app, decoded, tos, plat, pool, out_dir, log):
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
    W = np.stack([Wd[h] for h in H])
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
    ws3 = np.linalg.norm(W[:, :3, :3], axis=1)                 # 每块骨骼世界矩阵三列的长度
    wsu = ws3.mean(1)
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
    Wu = np.stack([_unit(W[i]) for i in range(n)])             # 单位缩放版本，供 glTF/Blender 使用
    for P in parts:
        P["bindpose"] = [np.linalg.inv(_unit(np.linalg.inv(bp))) for bp in P["bindpose"]]

    # ---- 骨骼名 / 路径表 ----
    hash2path = dict(tos)
    if args.names:
        nm = json.load(open(args.names, encoding="utf-8"))
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
    use_tos = (not args.no_tos) and cover >= 0.8

    # ---- 层级 ----
    samples = [probes[i]["sample"] for i in app]
    cnames = [clips[i]["name"] for i in app]
    pos_tracked = {h for s in samples for h, v in s.items() if v[0] is not None}
    n_skin = n
    guessed, ties = set(), 0
    Hn, is_extra = list(H), [False] * n
    if use_tos:
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
    log(f"      层级: {'TOS 路径' if use_tos else '动画验证'} {verified} 条"
        + ("" if use_tos else f" | 几何猜测 {len(guessed)} 条(约70%准确，已在 skeleton.json 标记 guessed)")
        + f" | 根节点 {len(roots)} 个" + ("" if use_tos else f" | 位置并列经旋转裁决 {ties} 处 | 低置信度(<50%) {int(((conf > 0) & (conf < 0.5)).sum())} 块"))
    if not use_tos:
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
    log(f"      骨骼名: 已还原 {named}/{nn}" + ("" if named else "（包内无 Avatar/Prefab，使用 Bone_<哈希> 命名；可用 --names / --tos-json 提供）"))

    # ---- 静止局部变换；非 TOS 模式下根骨骼的“虚拟父节点” ----
    H, n, W, hidx = Hn, nn, Wn, {h: i for i, h in enumerate(Hn)}

    # ---- 烘焙部件偏移：每个部件的 BindPose 含有该 SkinnedMeshRenderer 相对骨架根的变换 M_p（Unity 里蒙皮顶点在静止时
    #      实际落在 M_p·v）。Blender/FBX 导入时不使用 IBM，部件会掉回原点；所以把 M_p 烘焙进顶点/法线，
    #      并让所有部件共用同一套 IBM(=骨架世界矩阵的逆)，各软件看到的静止姿态完全一致。 ----
    bake_info = {}
    for P in parts:
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

    # ------------------------------------------------------------------ #
    # 构建 glTF
    # ------------------------------------------------------------------ #
    log("[4/6] 组装 glTF（骨骼 / 蒙皮 / BlendShape）…")
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
    top = {"name": "Armature", "children": roots}          # 名字尽量短：Blender/FBX 动作名上限 63 字符
    nodes.append(top)
    top_idx = len(nodes) - 1

    materials, meshes_out, skins, scene_nodes = [], [], [], [top_idx]
    mesh_node_of = {}
    for P in parts:
        attrs = {"POSITION": gl.add(to_gl_vec(P["pos"]), 34962, minmax=True)}
        if P["nrm"] is not None:
            attrs["NORMAL"] = gl.add(to_gl_vec(P["nrm"]), 34962)
        if P["uv"] is not None:
            uv = P["uv"].copy()
            uv[:, 1] = 1.0 - uv[:, 1]                       # Unity V 向上 -> glTF V 向下
            attrs["TEXCOORD_0"] = gl.add(uv, 34962)
        skinned = P["bw"] is not None and P["bi"] is not None and len(P["hashes"]) > 0
        if skinned:
            attrs["JOINTS_0"] = gl.add(P["bi"].astype(np.uint16), 34962)
            attrs["WEIGHTS_0"] = gl.add(P["bw"], 34962)
        targets = [{"POSITION": gl.add(to_gl_vec(mo["delta"]), 34962, minmax=True)} for mo in P["morphs"]]
        mat_names = plat.get(P["mesh_name"]) or plat.get(re.sub(r"_LOD\d+", "", P["mesh_name"])) or []
        prims = []
        for k, tri in enumerate(P["tris"]):
            if len(tri) == 0:
                continue
            tri = tri if P.get("flip") else tri[:, [0, 2, 1]]       # X 镜像后翻转绕序（部件自身含镜像时再翻一次，等于不翻）
            mname = mat_names[k] if k < len(mat_names) else f"{P['name']}_mat{k:02d}"
            materials.append({"name": mname, "pbrMetallicRoughness": {"baseColorFactor": [0.8, 0.8, 0.8, 1.0],
                                                                      "metallicFactor": 0.0, "roughnessFactor": 0.8},
                              "doubleSided": True})
            prim = {"attributes": attrs, "indices": gl.add(tri.reshape(-1).astype(np.uint32), 34963),
                    "material": len(materials) - 1}
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
        if P["bw"] is None:
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

    sk = [{"index": i, "hash": H[i], "name": names[i], "path": path_of.get(H[i]), "parent": int(parent[i]),
           "parent_hash": H[int(parent[i])] if parent[i] >= 0 else None,
           "extra_node": bool(is_extra[i]), "scale": round(float(wsu_n[i]), 4),
           "verified": bool(parent[i] >= 0 and i not in guessed), "guessed": i in guessed,
           "confidence": round(float(conf[i]), 3),
           "world_pos_unity": [round(float(x), 5) for x in W[i][:3, 3]]} for i in range(n)]
    json.dump(sk, open(out_dir / "skeleton.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump({str(h): path_of.get(h, "") for h in H}, open(out_dir / "names_template.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump({"character": char, "variant_hash": vh, "lod": args.lod,
               "parts": {P["name"]: P["mesh_name"] for P in parts}, "bones": n,
               "hierarchy": {"source": "tos" if use_tos else "inferred", "verified": verified, "guessed": len(guessed),
                             "roots": len(roots), "extra_nodes": n - n_skin, "scaled_bones": len(scaled_idx)},
               "root_motion": {"mode": args.root_motion, "threshold_m": round(float(rm_thr), 3),
                               "clips_affected": len(rm_clips), "carriers": dict(rm_stat)},
               "part_offsets_baked": bake_info,
               "animations_applicable": len(app), "animations_written": len(anims),
               "rest_pose_max_error_m": worst}, open(out_dir / "variant.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return {"glb": glb, "bones": n, "anims": len(anims), "guessed": len(guessed), "variant": vh, "tag": tag}


# =========================================================================== #
# 一个角色：发现变体 -> 选 LOD -> 适配动画 -> 逐变体构建
# =========================================================================== #
def run_char(args, char, meshes, clips, tos, plat, pool, log):
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
    if not lod0:
        log(f"[!] 角色 {char}: 没有 LOD0 的 Mesh（无法确定变体）")
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
            log("      不适配: " + ", ".join(f"{re.sub(r'^(?:Ani_)?[A-Za-z]+_\\d+_', '', n)}(命中{h}/{t}轨道)" for n, h, t in miss[:6])
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
        r_ = build_variant(args, char, v, skel_parts, sel, probes, clips, plan[v], decoded, tos, plat, pool, out_dir, log)
        if r_:
            outs.append(r_)
    return outs


def run(args, log):
    tokens = [c.strip() for item in (args.character or []) for c in item.split(",") if c.strip()]
    if not tokens and not args.list_characters:
        sys.exit("[!] 请用 -c 指定角色，例如 -c Parmon_10583（编号）、-c Parmon（整个系列）、-c all；"
                 "不确定时先用 --list-characters 查看包里有哪些角色")
    jobs = (os.cpu_count() or 1) if args.jobs == 0 else max(1, args.jobs)
    pool = ProcessPoolExecutor(max_workers=jobs) if jobs > 1 else None
    outs = []
    try:
        files = list_bundles(args.inputs)
        log(f"[*] 发现 {len(files)} 个 bundle | 并行进程 {jobs}")

        def parent_id(tok):                                   # Parmon_1058301 -> Parmon_10583（衍生角色的本体编号）
            m = re.match(r"^([A-Za-z]+_\d+)", tok)
            if not m:
                return None
            idt = m.group(1)
            p = re.sub(r"\d{2}$", "", idt)
            return p if p != idt and re.search(r"\d$", p) else None
        # 扫描用的 token：请求的 + 其本体编号（只为借用动画）+ --anim-from
        scan_tokens = list(dict.fromkeys(tokens + [parent_id(t) for t in tokens if parent_id(t)] +
                                         ([args.anim_from] if args.anim_from else [])))
        scans = pmap(pool, t_scan, [(f, scan_tokens) for f in files])
        allchars, tos = Counter(), {}
        by_dir = defaultdict(lambda: {"meshes": [], "clips": []})
        for sc in scans:
            if sc["error"]:
                log(f"  [跳过] {os.path.basename(sc['file'])}: {sc['error']}")
                continue
            allchars.update(sc["chars"])
            tos.update(sc["tos"])
            for m in sc["meshes"]:
                by_dir[m["char_dir"]]["meshes"].append(m)
            for c in sc["clips"]:
                by_dir[c["char_dir"]]["clips"].append(c)
        if args.tos_json:
            extra = json.load(open(args.tos_json, encoding="utf-8"))
            tos.update({int(k): str(v) for k, v in extra.items() if v})
        if args.list_characters:
            log("\n包里发现的角色目录（按 Mesh 数量）:")
            for c, k in allchars.most_common():
                log(f"  {c:32s} Mesh {k}")
            return 0

        # 请求的角色目录（char_dir）：Mesh 命中 token 规则的目录
        want_dirs = []
        for d, v in sorted(by_dir.items()):
            if v["meshes"] and any(token_match(t, d) for t in tokens):
                want_dirs.append(d)
        if not want_dirs:
            near = [k for k, _ in allchars.most_common()][:10]
            log(f"[!] 没有找到匹配 {tokens} 的角色目录；包里的角色目录示例: {near or '无'}（--list-characters 可查看全部）")
            return 1
        log(f"[*] 将处理 {len(want_dirs)} 个角色目录: {', '.join(want_dirs[:12])}" + (" …" if len(want_dirs) > 12 else ""))
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
            outs += run_char(args, d, v["meshes"], clips_c, tos, plat, pool, log)
    finally:
        if pool:
            pool.shutdown()
    if args.list_variants:
        return 0
    if not outs:
        log("[!] 没有生成任何模型")
        return 1
    if args.fbx:
        bl = find_blender(args.blender)
        if not bl:
            log("[FBX] 没找到 Blender：请安装 Blender 后用 --blender 指定路径，或在 Blender 里 导入 glTF → 导出 FBX")
            return 2

        def conv(o):
            buf = []
            ok = to_fbx(o["glb"], bl, buf.append, fps=args.fps, verify=not args.no_verify)
            return o, buf, ok
        with ThreadPoolExecutor(max_workers=max(1, min(jobs, len(outs)))) as ex:
            for o, buf, ok in ex.map(conv, outs):
                log(f"\n[FBX] {o['tag']}:")
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
    ap = argparse.ArgumentParser(description="从 Unity .uab 重建带骨骼/权重/动画的角色模型 (GLB/FBX)",
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("示例", 1)[1])
    ap.add_argument("inputs", nargs="+", help=".uab 文件或目录（Mesh 包 + 动画包放一起即可）")
    ap.add_argument("-c", "--character", nargs="+", help="角色：编号(Parmon_10583)、系列(Parmon，处理该系列全部角色)、完整目录名(Parmon_10583_LeafSheep)或 all；可写多个")
    ap.add_argument("-o", "--output", default="./model_out", help="输出目录（每个变体一个子目录 <角色>_<变体后缀>）")
    ap.add_argument("-j", "--jobs", type=int, default=1, help="并行进程数（默认 1；0 = 使用全部 CPU 核心）")
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
    ap.add_argument("--fbx", action="store_true", help="同时转出 FBX（需要 Blender）")
    ap.add_argument("--blender", help="Blender 可执行文件路径（默认从 PATH 查找）")
    ap.add_argument("--no-verify", action="store_true", help="转出 FBX 后不回读校验")
    args = ap.parse_args()
    return run(args, lambda s: print(s, flush=True))


if __name__ == "__main__":
    sys.exit(main())
