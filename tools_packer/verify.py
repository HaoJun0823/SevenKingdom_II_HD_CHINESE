# -*- coding: utf-8 -*-
"""用原版资源验证 解包->打包 字节级往返。

遍历指定的原版目录（默认 GAME/update 下的 Resource/Campaign/Scenario），
对每个文件：
  1. 解包到临时目录
  2. 重新打包为字节流
  3. 与原文件做 SHA-256 比对
  4. 报告 PASS / FAIL，并统计各容器类型命中情况。

用法:
  python verify.py [--src <update根目录>] [--tmp <临时目录>]
"""
import os
import sys
import tempfile
import argparse
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import packlib as P

DEFAULT_SRC = r'I:\LocalGames\Seven Kingdoms II HD\update'


def collect_files(src):
    files = []
    for sub in ('Resource', 'Campaign', 'Scenario'):
        d = os.path.join(src, sub)
        if not os.path.isdir(d):
            continue
        for root, dirs, fs in os.walk(d):
            for f in fs:
                files.append(os.path.join(root, f))
    return sorted(files)


def verify_file(infile, tmp):
    data = open(infile, 'rb').read()
    typ = P.detect_type(data)
    outdir = os.path.join(tmp, 'u')
    if os.path.isdir(outdir):
        shutil.rmtree(outdir)
    P.unpack_to_dir(infile, outdir)
    reb = P.pack_from_dir(outdir)
    ok = reb == data
    orig_sha = P.sha256_file(infile)
    new_sha = P.sha256_file(infile)  # placeholder
    new_sha = hashlib_sha(reb)
    return typ, ok, len(data), orig_sha, new_sha


def hashlib_sha(b):
    import hashlib
    return hashlib.sha256(b).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', default=DEFAULT_SRC)
    ap.add_argument('--tmp', default=None)
    args = ap.parse_args()

    files = collect_files(args.src)
    if not files:
        print('未在 %s 找到任何文件' % args.src)
        return 1

    tmp = args.tmp or tempfile.mkdtemp(prefix='sk2_verify_')
    os.makedirs(tmp, exist_ok=True)

    stats = {'residx': 0, 'resource': 0, 'blob': 0}
    fails = []
    print('%-52s %-9s %8s  %s' % ('file', 'type', 'bytes', 'result'))
    print('-' * 92)
    for f in files:
        typ, ok, sz, osha, nsha = verify_file(f, tmp)
        stats[typ] = stats.get(typ, 0) + 1
        rel = os.path.relpath(f, args.src)
        if ok:
            print('%-52s %-9s %8d  PASS' % (rel, typ, sz))
        else:
            print('%-52s %-9s %8d  FAIL  (%s vs %s)' % (rel, typ, sz, osha[:12], nsha[:12]))
            fails.append((rel, osha, nsha))
    print('-' * 92)
    print('总计 %d 个文件；类型分布: %s' % (len(files), stats))
    print('失败 %d 个' % len(fails))
    # 清理
    try:
        shutil.rmtree(tmp)
    except Exception:
        pass
    return 0 if not fails else 1


if __name__ == '__main__':
    sys.exit(main())
