"""删除 STL 里"从外面看不见"的内部零件（电机/螺丝/轴承/支架…）。

等价于 MeshLab 的手工流程:
    Filters -> Mesh Layer -> Split in Connected Components
    -> 逐层看，内部小零件删掉
    -> Filters -> Mesh Layer -> Flatten Visible Layers -> 导出 STL

判据(和人眼在 MeshLab 里转模型看是一回事): 把网格拆成连通体，然后从球面上 64 个方向
做正交射线扫描，记录每根射线打到的**第一个**三角形 —— 这些就是"从外面看得见"的面。
一个连通体里能被看见的面占比低于阈值 => 内部件 => 整块删掉。几何本身一个三角形都不改。

阈值来源: 拿一个人工在 MeshLab 里逐层删过的同类零件做过标定 —— 人工保留的 14 个零件
可见率最低 5.4%，人工删掉的 32 个最高 13.0%，两者有重叠，不存在完全可分的阈值。
默认取 0.05: 在标定件上"该留的一个没删"(零误删)，代价是多留 3 个零件 / 6145 面。
调高到 0.15 能删得更干净，但会误删一个人工保留的零件。所以阈值附近的零件建议人工过一眼
—— 这正是配套网页版 (../index.html) 存在的理由: 点一下就能手动增删。

依赖: pip install trimesh embreex numpy

用法:
    python vis_split.py <文件或目录> [-o 输出目录] [--thresh 0.05] [--report] [--dry-run]

默认输出到输入文件同目录、文件名加 _ML 后缀，已存在则跳过(除非 --force)。
"""

import argparse
import json
import os
import sys
import time

import numpy as np
import trimesh

SLIVER_FACES = 100  # 小于这个面数的连通体一律保留(都是 CAD 导出的零面积碎片)
MIN_SPACING = 3e-4  # 射线间距下限 3mm/10，再密没意义
N_DIRS = 64


def fib_dirs(n):
    """球面上均匀分布的 n 个方向"""
    i = np.arange(n) + 0.5
    phi = np.arccos(1 - 2 * i / n)
    theta = np.pi * (1 + 5**0.5) * i
    return np.c_[np.cos(theta) * np.sin(phi), np.sin(theta) * np.sin(phi), np.cos(phi)]


def farfield_visible(mesh, n_dirs=N_DIRS, grid=600):
    """从外面各个方向做正交扫描 -> 每个面是否被"第一眼"看到"""
    inter = trimesh.ray.ray_pyembree.RayMeshIntersector(mesh)
    center = mesh.bounds.mean(axis=0)
    r = np.linalg.norm(mesh.extents) / 2 * 1.05
    n = int(min(grid, max(64, np.ceil(2 * r / MIN_SPACING))))
    lin = np.linspace(-r, r, n)
    gx, gy = np.meshgrid(lin, lin, indexing="ij")
    grid_xy = np.c_[gx.ravel(), gy.ravel()]
    seen = np.zeros(len(mesh.faces), bool)
    for d in fib_dirs(n_dirs):
        up = np.array([0.0, 0.0, 1.0]) if abs(d[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
        e1 = np.cross(d, up)
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(d, e1)
        origins = center - d * r * 1.5 + grid_xy[:, :1] * e1 + grid_xy[:, 1:] * e2
        tri = inter.intersects_first(origins, np.tile(d, (len(origins), 1)))
        seen[tri[tri >= 0]] = True
    return seen, 2 * r / n


def face_labels(mesh):
    """连通体标号(只沿"恰好被两个面共用"的边, 即 trimesh 的 face_adjacency)。

    CAD 导出常把整片曲面写两遍(base_link 的两个电机罐子就是: 1743 个三角形各出现两次)。
    重复面会把它每条边的共用面数顶到 4, 于是一条边都连不上, 整片皮碎成一个个单三角形,
    再被 SLIVER_FACES 无条件保留 —— 电机就永远删不掉。所以顶点集合相同的三角形只留第一份
    参与建邻接, 副本跟着它的代表面走: 几何一个不改, 导出仍是原始三角形的严格子集。
    """
    tri = np.sort(mesh.faces, axis=1)
    _, first, inv = np.unique(tri, axis=0, return_index=True, return_inverse=True)
    twin = first[inv.ravel()]                           # 每个面 -> 它的代表面 (numpy 2.0 的 inv 是二维)
    rep = np.flatnonzero(twin == np.arange(len(mesh.faces)))
    if len(rep) == len(mesh.faces):                     # 没有重复面: 就是原来那条路
        return trimesh.graph.connected_component_labels(mesh.face_adjacency, node_count=len(mesh.faces))
    slot = np.empty(len(mesh.faces), int)
    slot[rep] = np.arange(len(rep))                     # 代表面 -> 它在子网格里的下标
    sub = trimesh.Trimesh(vertices=mesh.vertices, faces=mesh.faces[rep], process=False)
    lab_rep = trimesh.graph.connected_component_labels(sub.face_adjacency, node_count=len(rep))
    return lab_rep[slot[twin]]


def analyse(mesh, grid=600):
    labels = face_labels(mesh)
    n_comp = int(labels.max()) + 1
    counts = np.bincount(labels, minlength=n_comp)
    seen, spacing = farfield_visible(mesh, grid=grid)
    vis = np.ones(n_comp)  # 碎片默认可见 -> 保留
    for c in range(n_comp):
        if counts[c] >= SLIVER_FACES:
            vis[c] = seen[labels == c].mean()
    return labels, vis, counts, spacing


def process(src, dst, thresh=0.05, report=False, dry_run=False, grid=600):
    t0 = time.time()
    mesh = trimesh.load_mesh(src, process=False)
    mesh.merge_vertices()  # STL 没有共享顶点，必须先焊接，否则每个三角形都是一个连通体
    labels, vis, counts, spacing = analyse(mesh, grid=grid)

    keep_comp = (vis >= thresh) | (counts < SLIVER_FACES)
    keep_face = keep_comp[labels]
    real = counts >= SLIVER_FACES  # "真零件"(非碎片)

    if report:
        print("  %5s %8s %9s  %s" % ("comp", "faces", "visible", "decision"))
        for c in np.argsort(-counts):
            if real[c]:
                print("  %5d %8d %8.1f%%  %s" % (c, counts[c], 100 * vis[c], "keep" if keep_comp[c] else "DELETE"))

    stat = {
        "name": os.path.basename(src),
        "faces_in": int(len(mesh.faces)),
        "faces_out": int(keep_face.sum()),
        "comp_real": int(real.sum()),
        "comp_deleted": int((~keep_comp & real).sum()),
        "ray_spacing_mm": round(spacing * 1000, 3),
        # 可见率在阈值附近的零件，人工只要复核这些就够了
        "borderline": [
            [int(counts[c]), round(100 * float(vis[c]), 1)]
            for c in np.argsort(-counts)
            if real[c] and thresh * 0.4 < vis[c] < 0.30
        ],
        "comps": [[int(counts[c]), round(float(vis[c]), 4)] for c in np.argsort(-counts) if real[c]],
    }
    if stat["faces_out"] and stat["comp_deleted"] and not dry_run:
        mesh.submesh([np.flatnonzero(keep_face)], append=True).export(dst)
        stat["written"] = dst
    stat["secs"] = round(time.time() - t0, 1)
    return stat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="STL 文件或包含 STL 的目录")
    ap.add_argument("-o", "--out-dir", default=None)
    ap.add_argument("--suffix", default="_ML")
    ap.add_argument("--thresh", type=float, default=0.05, help="可见面占比阈值，低于它就删 (默认 0.05)")
    ap.add_argument("--grid", type=int, default=600, help="每个方向的扫描射线网格边长 (默认 600)")
    ap.add_argument("--report", action="store_true", help="打印每个连通体的可见率")
    ap.add_argument("--dry-run", action="store_true", help="只统计不写文件")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的输出")
    ap.add_argument("--json", default=None, help="把逐零件的统计写到这个 json")
    a = ap.parse_args()

    if os.path.isdir(a.path):
        files = sorted(
            os.path.join(a.path, f)
            for f in os.listdir(a.path)
            if f.lower().endswith(".stl") and not os.path.splitext(f)[0].endswith(a.suffix)
        )
    else:
        files = [a.path]

    stats = []
    for i, src in enumerate(files, 1):
        stem, ext = os.path.splitext(os.path.basename(src))
        out_dir = a.out_dir or os.path.dirname(os.path.abspath(src))
        dst = os.path.join(out_dir, stem + a.suffix + ext)
        if os.path.exists(dst) and not a.force and not a.dry_run:
            print(f"[{i}/{len(files)}] skip {os.path.basename(src)} (输出已存在: {os.path.basename(dst)})")
            continue
        print(f"[{i}/{len(files)}] {os.path.basename(src)}", flush=True)
        s = process(src, dst, thresh=a.thresh, report=a.report, dry_run=a.dry_run, grid=a.grid)
        stats.append(s)
        print(
            "    %d -> %d faces (-%.1f%%), 删除 %d/%d 个零件, 射线间距 %.2fmm, %.1fs%s"
            % (
                s["faces_in"], s["faces_out"], 100 * (1 - s["faces_out"] / max(s["faces_in"], 1)),
                s["comp_deleted"], s["comp_real"], s["ray_spacing_mm"], s["secs"],
                "" if s.get("written") or a.dry_run else "  [无内部件，未写文件]",
            ),
            flush=True,
        )
        if s["borderline"]:
            print("    边界零件(建议人工复核) 面数/可见率: %s" % s["borderline"], flush=True)

    if a.json:
        with open(a.json, "w") as f:
            json.dump(stats, f, indent=1)

    if len(stats) > 1:
        fi = sum(s["faces_in"] for s in stats)
        fo = sum(s["faces_out"] for s in stats)
        print("\n== 汇总: %d 个文件, %d -> %d 面 (-%.1f%%), 共删除 %d 个内部零件 =="
              % (len(stats), fi, fo, 100 * (1 - fo / fi), sum(s["comp_deleted"] for s in stats)))
        print("%-26s %9s %9s %8s %8s" % ("mesh", "faces_in", "faces_out", "减少", "删零件"))
        for s in sorted(stats, key=lambda s: -(s["faces_in"] - s["faces_out"])):
            print("%-26s %9d %9d %7.1f%% %8d"
                  % (s["name"], s["faces_in"], s["faces_out"],
                     100 * (1 - s["faces_out"] / max(s["faces_in"], 1)), s["comp_deleted"]))


if __name__ == "__main__":
    sys.exit(main())
