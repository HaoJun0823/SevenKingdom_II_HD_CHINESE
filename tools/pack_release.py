#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""pack_release.py — 装配可发布的 zip（纯 Python，跨平台，CI 与本地同一套逻辑）

输入：
    build/sk2_zh.asi         编译产物（tools/build.py 产出）
    update_res_staged/       资源树（tools/stage_resources.py 产出）
    packaging/               非资源文件：dsound.dll、update\\render.ini、*.bak、说明 txt
    仓库根 LICENSE、LICENSES/ 按清单原样带上

输出：
    release/7K2-CHS-Common-<stamp>.zip
        <stamp> 缺省取当天日期（YYYY-MM-DD），可 --stamp 覆盖，保证可重放。

校验（任一不过就非零退出，绝不产出半成品）：
    1. 清单 tools/release_manifest.txt 里的每个文件都找得到；
    2. zip 内的路径集合与清单**完全相同**（多一个、少一个都算错）；
    3. scripts/sk2_zh.asi 是 PE32 x86 DLL 且导出 DllMain（防止链接成 x64/控制台程序）；
    4. 打印逐文件 CRC32 与体积，方便和上一版对比。

用法：
    python tools/pack_release.py
    python tools/pack_release.py --stamp 2026-11-15 --outdir release
    python tools/pack_release.py --verify release/7K2-CHS-Common-2026-11-15.zip
"""
import argparse
import os
import struct
import sys
import time
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MANIFEST = os.path.join(HERE, "release_manifest.txt")
ASI = os.path.join(ROOT, "build", "sk2_zh.asi")
STAGE = os.path.join(ROOT, "update_res_staged")
PACKAGING = os.path.join(ROOT, "packaging")

# zip 内条目的固定时间戳（可重放：同输入同输出，CI 上便于比对）
FIXED_DATE = (2020, 1, 1, 0, 0, 0)

# 面向玩家的文本统一转 CRLF：老版记事本（Win7/8）不认 LF，会把整份说明显示成一行。
# 转换放在这里而不是依赖 git 的 eol 设置 —— 保证本地与 CI 产出的 zip 逐字节一致。
TEXT_SUFFIXES = (".txt", ".ini")
TEXT_EXACT = ("LICENSE",)          # 无扩展名但确实是文本的文件


def normalize_text(data, path):
    if not (path.lower().endswith(TEXT_SUFFIXES) or path in TEXT_EXACT):
        return data
    txt = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return txt.replace(b"\n", b"\r\n")


def read_manifest():
    paths = []
    with open(MANIFEST, encoding="utf-8") as f:
        for line in f:
            p = line.strip()
            if p and not p.startswith("#"):
                paths.append(p)
    dup = {p for p in paths if paths.count(p) > 1}
    if dup:
        raise SystemExit("清单里有重复项：%s" % sorted(dup))
    return paths


def resolve(path):
    """按优先级找文件：编译产物 → 暂存资源树 → packaging/ → 仓库根。"""
    if path == "scripts/sk2_zh.asi":
        return ASI
    if path.startswith("update/"):
        return os.path.join(STAGE, *path[len("update/"):].split("/"))
    pkg = os.path.join(PACKAGING, *path.split("/"))
    if os.path.isfile(pkg):
        return pkg
    return os.path.join(ROOT, *path.split("/"))


def pe_check(path):
    """解析 PE 头，返回 (机器码, 是否 DLL, 子系统, 入口点 RVA)。非 PE 直接抛错。

    注意：本插件**不导出任何符号**（DllMain 是 DLL 入口点，不是导出函数），
    所以不能拿「导出表里有 DllMain」当门禁 —— 只能查 PE 头本身。
    """
    d = open(path, "rb").read()
    if d[:2] != b"MZ":
        raise SystemExit("%s 不是 PE 文件（缺 MZ 头）" % path)
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    if d[pe:pe + 4] != b"PE\0\0":
        raise SystemExit("%s 不是合法 PE（缺 PE 签名）" % path)
    machine, nsec = struct.unpack_from("<HH", d, pe + 4)
    characteristics = struct.unpack_from("<H", d, pe + 22)[0]   # COFF 头 +18
    opt_size = struct.unpack_from("<H", d, pe + 20)[0]
    opt = pe + 24
    entry = struct.unpack_from("<I", d, opt + 16)[0]            # AddressOfEntryPoint
    subsystem = struct.unpack_from("<H", d, opt + 68)[0]        # PE32/PE32+ 同偏移
    return machine, bool(characteristics & 0x2000), subsystem, entry


# 插件里一定会出现的 UTF-8 字面量（证明这确实是我们编出来的插件，不是空壳）
PLUGIN_MARKERS = ("字形语言".encode("utf-8"), b"sk2_zh.log")


def build(stamp, outdir):
    paths = read_manifest()
    missing = [p for p in paths if not os.path.isfile(resolve(p))]
    if missing:
        raise SystemExit("缺少下列文件，拒绝打包：\n  " + "\n  ".join(missing))

    # ── 插件产物体检 ─────────────────────────────────────────
    asi_blob = open(ASI, "rb").read()
    machine, is_dll, subsystem, entry = pe_check(ASI)
    if machine != 0x014C:
        raise SystemExit("sk2_zh.asi 的机器码是 0x%04X，不是 x86(0x014C) —— 链错了目标" % machine)
    if not is_dll:
        raise SystemExit("sk2_zh.asi 不是 DLL（PE Characteristics 缺 IMAGE_FILE_DLL）")
    if subsystem != 2:
        raise SystemExit("sk2_zh.asi 的子系统是 %d，应为 2(WINDOWS) —— 链成控制台程序了" % subsystem)
    if not entry:
        raise SystemExit("sk2_zh.asi 的入口点 RVA 为 0（DllMain 丢了）")
    for m in PLUGIN_MARKERS:
        if m not in asi_blob:
            raise SystemExit("sk2_zh.asi 里找不到标记串 %r —— 产物可疑，拒绝打包" % m)
    asi_size = os.path.getsize(ASI)
    # 体积护栏：字形池是内嵌的，正常在 2.0~3.0MB。异常说明字体池没生成或编译失败。
    if not (1_800_000 <= asi_size <= 4_200_000):
        raise SystemExit("sk2_zh.asi 体积异常：%d B（预期 1.8~4.2MB，检查 fontdata_pools_*.h 是否就位）"
                         % asi_size)

    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, "7K2-CHS-Common-%s.zip" % stamp)
    if os.path.exists(out):
        os.remove(out)

    # ── 写 zip（UTF-8 文件名标志位，Linux/Windows 双向可解）──────
    total = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in paths:
            src = resolve(path)
            info = zipfile.ZipInfo(path, date_time=FIXED_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0x20
            # 0x800 = UTF-8 文件名（含中文名的条目必需）
            info.flag_bits |= 0x800
            data = normalize_text(open(src, "rb").read(), path)
            z.writestr(info, data, compresslevel=9)
            total += len(data)
            print("  %-58s %8d B  crc=%08x" % (path, len(data), zlib.crc32(data) & 0xFFFFFFFF))

    # ── 回读自检：路径集合必须与清单完全一致 ────────────────
    with zipfile.ZipFile(out) as z:
        got = z.namelist()
        if sorted(got) != sorted(paths):
            extra = sorted(set(got) - set(paths))
            lack = sorted(set(paths) - set(got))
            raise SystemExit("zip 内容与清单不符：多=%s 少=%s" % (extra, lack))
        if z.testzip() is not None:
            raise SystemExit("zip 自检失败")

    print("\n[O] %s" % out)
    print("    条目 %d 个，解压后 %.2f MB，zip %.2f MB"
          % (len(paths), total / 1048576.0, os.path.getsize(out) / 1048576.0))
    print("    sk2_zh.asi %d B（PE32 x86 DLL，子系统 WINDOWS，入口点已就位）" % asi_size)
    return out


def verify(zip_path):
    paths = read_manifest()
    with zipfile.ZipFile(zip_path) as z:
        got = z.namelist()
        if sorted(got) != sorted(paths):
            print("!! 路径集合与清单不符：多=%s 少=%s"
                  % (sorted(set(got) - set(paths)), sorted(set(paths) - set(got))))
            return 1
        bad = z.testzip()
        if bad:
            print("!! 条目损坏：%s" % bad)
            return 1
        asi = z.read("scripts/sk2_zh.asi")
        tmp = zip_path + ".asi.tmp"
        open(tmp, "wb").write(asi)
        try:
            machine, is_dll, subsystem, entry = pe_check(tmp)
        finally:
            os.remove(tmp)
        if machine != 0x014C or not is_dll or subsystem != 2 or not entry:
            print("!! 包内 asi 不合格：machine=0x%04X dll=%s subsystem=%d entry=0x%X"
                  % (machine, is_dll, subsystem, entry))
            return 1
        for m in PLUGIN_MARKERS:
            if m not in asi:
                print("!! 包内 asi 缺标记串 %r" % m)
                return 1
    print("✓ %s：%d 个条目，路径集合与清单一致，包内 asi 合格" % (zip_path, len(paths)))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stamp", default=None, help="版本戳，缺省为当天日期 YYYY-MM-DD")
    ap.add_argument("--outdir", default=os.path.join(ROOT, "release"))
    ap.add_argument("--verify", default=None, help="只校验已存在的 zip")
    args = ap.parse_args()

    if args.verify:
        return verify(args.verify)
    stamp = args.stamp or time.strftime("%Y-%m-%d")
    build(stamp, args.outdir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
