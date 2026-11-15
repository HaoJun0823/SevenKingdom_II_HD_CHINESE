#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build.py — 命令行编译 sk2_zh.asi（x86 DLL，免 MSBuild / VS IDE）

两条路径，同一套源码、同一组编译选项：

  · Windows 本地：直接调 cl.exe。工具集按 SK2_MSVC / SK2_SDK / SK2_SDKV 环境变量
    指定的版本，缺省自动探测（vswhere → 取最新一套 VC 工具集）。
  · Linux CI：读 MSVC_WINE_PREFIX 指向 msvc-wine 装好的工具链，用
    <prefix>/bin/x86/cl 包装脚本（wine 跑真 cl.exe；INCLUDE/LIB 由包装脚本负责，
    这里不要再设环境变量，否则会盖掉它探测出来的路径）。

产物：build/sk2_zh.asi（+ 中间 .obj）

用法：
    python tools/build.py
    SK2_MSVC="C:/.../VC/Tools/MSVC/14.29.30133" python tools/build.py
"""
import argparse
import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC_DIR = os.path.join(ROOT, "SavenKingdom_II_HD_CHINESE")
OUT_DIR = os.path.join(ROOT, "build")

SOURCES = ["dllmain.cpp", "core.cpp", "hooks.cpp", "cjk.cpp", "diag.cpp", "pch.cpp"]

# 与 build.cmd / 历史产物一致的编译选项。/MT 静态 CRT，避免玩家机器缺 VC 运行库。
CFLAGS = ["/nologo", "/c", "/std:c++17", "/utf-8", "/EHsc", "/MT", "/O2",
          "/DWIN32", "/D_WINDOWS", "/DNDEBUG", "/DUNICODE", "/D_UNICODE"]
LINK_FLAGS = ["/link", "/DLL", "/MACHINE:X86", "/SUBSYSTEM:WINDOWS",
              "kernel32.lib", "user32.lib", "advapi32.lib"]

DEFAULT_SDK = r"C:\Program Files (x86)\Windows Kits\10"


def _looks_like_cl(path):
    return path and os.path.isfile(path) and os.access(path, os.X_OK)


def resolve_toolchain():
    """返回 (cl 路径, INCLUDE, LIB)；INCLUDE/LIB 为 None 表示交给包装脚本。

    优先级：
      1. SK2_CL —— 显式指定的 cl（CI 应急口子）
      2. MSVC_WINE_PREFIX —— Linux CI 的 msvc-wine 包装脚本
      3. SK2_MSVC / SK2_SDK / SK2_SDKV —— 本地指定版本
      4. Windows 自动探测（vswhere 优先，其次扫已知安装目录取最新）
    """
    # 1) 显式 cl
    cl = os.environ.get("SK2_CL")
    if _looks_like_cl(cl):
        return cl, None, None

    # 2) msvc-wine（Linux）：bin/x86 是 64 位宿主 + 32 位目标的交叉包装
    prefix = os.environ.get("MSVC_WINE_PREFIX")
    if prefix:
        for rel in ("bin/x86/cl", "bin/x86/cl.exe", "bin/x64/cl", "bin/x64/cl.exe"):
            p = os.path.join(prefix, *rel.split("/"))
            if _looks_like_cl(p):
                return p, None, None
        raise SystemExit("[X] MSVC_WINE_PREFIX=%s 下找不到 bin/x86/cl（msvc-wine 没装好？）" % prefix)

    # 3) 本地指定版本
    msvc = os.environ.get("SK2_MSVC")
    if not msvc:
        msvc = _detect_msvc()
    if not msvc:
        raise SystemExit("[X] 找不到 MSVC 工具集：请设 SK2_MSVC，或安装 Visual Studio（含 C++ 桌面开发）")

    sdk = os.environ.get("SK2_SDK", DEFAULT_SDK)
    sdkv = os.environ.get("SK2_SDKV") or _detect_sdkv(sdk)
    if not sdkv:
        raise SystemExit("[X] %s\\Include 下没有可用的 SDK 版本" % sdk)

    cl = os.path.join(msvc, "bin", "Hostx86", "x86", "cl.exe")
    if not os.path.isfile(cl):
        cl = os.path.join(msvc, "bin", "Hostx64", "x64", "cl.exe")
    if not os.path.isfile(cl):
        raise SystemExit("[X] %s 下找不到 cl.exe" % msvc)

    inc = os.pathsep.join([
        os.path.join(msvc, "include"),
        os.path.join(sdk, "Include", sdkv, "ucrt"),
        os.path.join(sdk, "Include", sdkv, "um"),
        os.path.join(sdk, "Include", sdkv, "shared"),
    ])
    lib = os.pathsep.join([
        os.path.join(msvc, "lib", "x86"),
        os.path.join(sdk, "Lib", sdkv, "ucrt", "x86"),
        os.path.join(sdk, "Lib", sdkv, "um", "x86"),
    ])
    return cl, inc, lib


def _detect_msvc():
    """vswhere 找 VS 安装 → 取其中版本号最大的 VC 工具集目录。"""
    vswhere = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                           "Microsoft Visual Studio", "Installer", "vswhere.exe")
    roots = []
    if os.path.isfile(vswhere):
        try:
            out = subprocess.run(
                [vswhere, "-products", "*", "-requires",
                 "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                 "-property", "installationPath"],
                capture_output=True, text=True, timeout=30).stdout
            roots += [ln.strip() for ln in out.splitlines() if ln.strip()]
        except Exception:
            pass
    # 兜底：扫已知安装根（vswhere 缺失或被策略拦下时）
    for base in (r"C:\Program Files\Microsoft Visual Studio",
                 r"C:\Program Files (x86)\Microsoft Visual Studio"):
        for pat in ("*/VC/Tools/MSVC", "/*/VC/Tools/MSVC"):
            roots_glob = glob.glob(os.path.join(base, pat))
            for g in roots_glob:
                roots.append(os.path.dirname(os.path.dirname(os.path.dirname(g))))

    cands = []
    for r in roots:
        for d in glob.glob(os.path.join(r, "VC", "Tools", "MSVC", "*")):
            if os.path.isdir(d):
                cands.append(d)
    if not cands:
        return None

    def ver(p):
        try:
            return tuple(int(x) for x in os.path.basename(p).split(".")[:3])
        except ValueError:
            return (0,)
    return max(cands, key=ver)


def _detect_sdkv(sdk):
    inc = os.path.join(sdk, "Include")
    if not os.path.isdir(inc):
        return None
    vers = [d for d in os.listdir(inc) if d[:2].isdigit()]
    if not vers:
        return None

    def ver(v):
        try:
            return tuple(int(x) for x in v.split("."))
        except ValueError:
            return (0,)
    return max(vers, key=ver)


def run(cmd, env, cwd):
    r = subprocess.run(cmd, env=env, cwd=cwd, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=OUT_DIR)
    ap.add_argument("--keep-obj", action="store_true", help="保留中间 .obj（默认保留）")
    args = ap.parse_args()

    cl, inc, lib = resolve_toolchain()
    os.makedirs(args.outdir, exist_ok=True)

    env = dict(os.environ)
    if inc:
        env["INCLUDE"] = inc
        env["LIB"] = lib
        env["PATH"] = os.path.dirname(cl) + os.pathsep + env.get("PATH", "")

    print("cl      : %s" % cl)
    if inc:
        print("INCLUDE : %s" % inc.replace(os.pathsep, "\n          "))
        print("LIB     : %s" % lib.replace(os.pathsep, "\n          "))
    else:
        print("INCLUDE : （由工具链包装脚本设置）")

    objs = []
    for s in SOURCES:
        base = os.path.splitext(s)[0]
        obj = os.path.join(args.outdir, base + ".obj")
        rc, txt = run([cl] + CFLAGS + ["/Fo:" + obj, os.path.join(SRC_DIR, s)], env, args.outdir)
        nerr = txt.lower().count(" error ")
        ok = (rc == 0 and nerr == 0)
        print("=== %-12s %s" % (s, "OK" if ok else "FAIL"))
        if not ok:
            print(txt[:6000])
            return 1
        objs.append(obj)

    asi = os.path.join(args.outdir, "sk2_zh.asi")
    rc, txt = run([cl, "/nologo", "/LD", "/Fe:" + asi] + objs + LINK_FLAGS, env, args.outdir)
    print("=== link       returncode=%d" % rc)
    if txt.strip():
        print(txt[:6000])
    if not os.path.isfile(asi):
        print("[X] 未生成 %s" % asi)
        return 1
    print("[O] 产物: %s  (%d 字节)" % (asi, os.path.getsize(asi)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
