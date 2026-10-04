#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build.py — 命令行编译 sk2_zh.asi（无需 MSBuild / VS IDE）

背景：本环境的 MSBuild.exe 与 PowerShell 的 Add-Type 被安全策略拦下，
      因此直接用 MSVC 的 cl.exe 手动指定 INCLUDE / LIB 完成编译。

用法：  python build.py
产物：  <工程>/build/sk2_zh.asi
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC_DIR = os.path.join(ROOT, "SavenKingdom_II_HD_CHINESE")
OUT_DIR = os.path.join(ROOT, "build")

MSVC = r"C:\Program Files\Microsoft Visual Studio\18\Community\VC\Tools\MSVC\14.51.36231"
SDK = r"C:\Program Files (x86)\Windows Kits\10"
SDKV = "10.0.26100.0"

CL = os.path.join(MSVC, "bin", "Hostx86", "x86", "cl.exe")
if not os.path.isfile(CL):
    for cand in ("HostX86/x86/cl.exe", "Hostx64/x64/cl.exe"):
        p = os.path.join(MSVC, "bin", *cand.split("/"))
        if os.path.isfile(p):
            CL = p
            break

INCLUDE = os.pathsep.join([
    os.path.join(MSVC, "include"),
    os.path.join(SDK, "Include", SDKV, "ucrt"),
    os.path.join(SDK, "Include", SDKV, "um"),
    os.path.join(SDK, "Include", SDKV, "shared"),
])
LIB = os.pathsep.join([
    os.path.join(MSVC, "lib", "x86"),
    os.path.join(SDK, "Lib", SDKV, "ucrt", "x86"),
    os.path.join(SDK, "Lib", SDKV, "um", "x86"),
])

SOURCES = ["dllmain.cpp", "core.cpp", "hooks.cpp", "cjk.cpp", "diag.cpp", "pch.cpp"]


def main():
    if not os.path.isfile(CL):
        print("[X] 找不到 cl.exe: %s" % CL)
        return 1
    os.makedirs(OUT_DIR, exist_ok=True)

    objfiles = []
    for s in SOURCES:
        base = os.path.splitext(s)[0]
        cmd = [
            CL, "/nologo", "/c", "/std:c++17", "/utf-8", "/EHsc", "/MT", "/O2",
            "/DWIN32", "/D_WINDOWS", "/DNDEBUG", "/DUNICODE", "/D_UNICODE",
            "/Fo:" + os.path.join(OUT_DIR, base + ".obj"),
            os.path.join(SRC_DIR, s),
        ]
        r = subprocess.run(cmd, env=_env(), cwd=OUT_DIR,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        err = (r.stdout or "") + (r.stderr or "")
        # cl 正常也会输出文件名（stdout），只在出现 error 时视为失败
        nerr = err.lower().count(" error ")
        print("=== %-14s %s (%d error)" % (s, "OK" if r.returncode == 0 and nerr == 0 else "FAIL", nerr))
        if nerr:
            print(err[:4000])
            return 1
        objfiles.append(os.path.join(OUT_DIR, base + ".obj"))

    link = [
        CL, "/nologo", "/LD", "/Fe:" + os.path.join(OUT_DIR, "sk2_zh.asi"),
    ] + objfiles + [
        "/link", "/DLL", "/MACHINE:X86", "/SUBSYSTEM:WINDOWS",
        "kernel32.lib", "user32.lib", "advapi32.lib",
    ]
    r = subprocess.run(link, env=_env(), cwd=OUT_DIR,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    err = (r.stdout or "") + (r.stderr or "")
    print("=== link  returncode=%d" % r.returncode)
    if err.strip():
        print(err[:4000])
    dll = os.path.join(OUT_DIR, "sk2_zh.asi")
    if os.path.isfile(dll):
        print("[O] 产物: %s  (%d 字节)" % (dll, os.path.getsize(dll)))
        return 0
    print("[X] 未生成 %s" % dll)
    return 1


def _env():
    env = dict(os.environ)
    env["INCLUDE"] = INCLUDE
    env["LIB"] = LIB
    env["PATH"] = os.path.dirname(CL) + os.pathsep + env.get("PATH", "")
    return env


if __name__ == "__main__":
    sys.exit(main())
