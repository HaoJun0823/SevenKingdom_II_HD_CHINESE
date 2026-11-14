#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""stage_resources.py — 由解包源重新装配 update_res_staged\\（发布用资源树）

背景
----
`update_res_staged/` 以前是手工同步的，于是长期落后于真正的真源
`unpack_data_chs/`：V5 发布包里的 east.evt / east.plt / STD.SET 比它新，
发布包与仓库对不上。本脚本把「装配」变成可重放的一步：

    unpack_data_chs/  ──pack──▶  update_res_staged/  ──zip──▶  发布包 update/

三件事：
  1. 逐一打包 `unpack_data_chs/**/<NAME>.unpacked`（只打发布清单里要的那些）；
  2. 按 `tools/residx_order.json` 把 EAST.EVT / EAST.PLT 的索引顺序对齐原版；
  3. 把 `packaging/update/` 里的非资源文件（render.ini、*.bak）覆盖进来。

用法：
    python tools/stage_resources.py            # 重建 update_res_staged/
    python tools/stage_resources.py --check    # 只比对，不写盘（CI 用）
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools_packer"))
import packlib as P  # noqa: E402

UNPACK_ROOT = os.path.join(ROOT, "unpack_data_chs")
STAGE_DIR = os.path.join(ROOT, "update_res_staged")
PACKAGING = os.path.join(ROOT, "packaging")
MANIFEST = os.path.join(HERE, "release_manifest.txt")
ORDER_JSON = os.path.join(HERE, "residx_order.json")


def read_manifest():
    """发布清单 → (update/ 下的相对路径列表, 其余路径列表)。"""
    update_paths, other = [], []
    with open(MANIFEST, encoding="utf-8") as f:
        for line in f:
            p = line.strip()
            if not p or p.startswith("#"):
                continue
            (update_paths if p.startswith("update/") else other).append(p)
    return update_paths, other


def index_unpacked():
    """{小写相对路径: 实际解包目录}，兼容 Windows 与 Linux 的大小写差异。"""
    idx = {}
    for dirpath, _dirs, files in os.walk(UNPACK_ROOT):
        if "manifest.json" in files and dirpath.endswith(".unpacked"):
            rel = os.path.relpath(dirpath, UNPACK_ROOT).replace("\\", "/")
            idx[rel[: -len(".unpacked")].lower()] = dirpath
    return idx


def reorder(blob, names):
    """把 residx 容器的索引顺序改为 names 给定的顺序（记录字节原样搬运）。"""
    cnt, entries = P.read_residx(blob)
    have = [e[0].rstrip(b"\x00").decode("latin1") for e in entries[:-1]]
    if len(have) != len(names):
        raise SystemExit("记录数不符：容器 %d 条 / 基准 %d 条" % (len(have), len(names)))
    if sorted(have) != sorted(names):
        only_have = sorted(set(have) - set(names))[:5]
        only_want = sorted(set(names) - set(have))[:5]
        raise SystemExit("名字集合不符：容器独有=%s 基准独有=%s" % (only_have, only_want))
    if have == names:
        return blob
    # 键统一用 bytes 比对（read_residx 给的 name_raw 是 9 字节定长，尾部补 \0）
    body = {e[0].rstrip(b"\x00"): (e[0], e[1]) for e in entries[:-1]}
    new_entries = [(body[n.encode("latin1")][0], body[n.encode("latin1")][1]) for n in names]
    new_entries.append((entries[-1][0], None))       # 哨兵
    return P.write_residx(new_entries)


def build_update_tree():
    """返回 {相对路径(update/ 之后): 字节}。"""
    update_paths, _ = read_manifest()
    idx = index_unpacked()
    with open(ORDER_JSON, encoding="utf-8") as f:
        order = json.load(f)["files"]
    order_by_target = {v["target"]: v["order"] for v in order.values()}

    out = {}
    for path in update_paths:
        rel = path[len("update/"):]
        key = rel.lower()
        # 1) packaging/update/ 里的非资源文件优先（render.ini、*.bak 等）
        pkg = os.path.join(PACKAGING, "update", *rel.split("/"))
        if os.path.isfile(pkg):
            out[rel] = open(pkg, "rb").read()
            continue
        # 2) 否则由解包源打包
        if key not in idx:
            raise SystemExit("清单里的 %s 既不在 packaging/update/ 也没有对应解包目录" % path)
        blob = P.pack_from_dir(idx[key])
        if rel in order_by_target:
            blob = reorder(blob, order_by_target[rel])
        out[rel] = blob
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只比对，不写盘（不一致则退出码 1）")
    args = ap.parse_args()

    tree = build_update_tree()
    bad = 0
    for rel in sorted(tree):
        want = tree[rel]
        dst = os.path.join(STAGE_DIR, *rel.split("/"))
        if os.path.isfile(dst) and open(dst, "rb").read() == want:
            continue
        if args.check:
            print("!! 与解包源不一致: update/%s" % rel)
            bad += 1
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, "wb").write(want)
            print("写入 update/%s (%d B)" % (rel, len(want)))

    # 反向检查：暂存目录里是否有清单之外的多余文件
    if os.path.isdir(STAGE_DIR):
        want_set = {r.replace("/", os.sep) for r in tree}
        for dirpath, _dirs, files in os.walk(STAGE_DIR):
            for f in files:
                rel = os.path.relpath(os.path.join(dirpath, f), STAGE_DIR)
                if rel not in want_set:
                    print("!! update_res_staged/ 多出清单外的文件: %s" % rel)
                    bad += 1

    if args.check:
        if bad:
            print("\n[check] %d 处不一致 —— 请运行 python tools/stage_resources.py 重建" % bad)
            return 1
        print("[check] update_res_staged/ 与解包源一致（%d 个文件）" % len(tree))
    else:
        print("\n装配完成：%d 个文件 → update_res_staged/" % len(tree))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
