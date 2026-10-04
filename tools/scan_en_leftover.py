# -*- coding: utf-8 -*-
"""在已翻译资源里扫描「英文残留」——找出记录**内部**漏译的条目。

为什么需要它
------------
整条记录对比只能发现「整条没翻」。但像 STD.SET 的 FBUILD 表，
里面是一堆「名字 + 空格填充 + 数字」的条目，翻译时漏掉其中几个
（例如 Immortal's Academy），整条记录内容仍然「不同」，
diff 会判为已翻译 —— 漏译就这样藏起来了。

判定思路
--------
提取连续 ASCII 字母串（>=3 个字母），再排除掉本来就该是英文的东西：
  * 全大写且带下划线的 ID（STAB_PE / T_ENENGY / PE_STAB）
  * 纯数字/单位/格式符
  * 常见的资源键名
剩下的就是「疑似漏译的英文词」，人工确认后补译。

用法:
    python scan_en_leftover.py <解包根目录> [--min 4] [--json out.json]
"""
import os
import re
import sys
import json
import argparse

WORD = re.compile(rb"[A-Za-z][A-Za-z'\-]*(?: [A-Za-z][A-Za-z'\-]*)*")

# 允许保留的英文（资源内部 ID / 文件名 / 常见技术串）
ALLOW = re.compile(r'^(?:[A-Z][A-Z0-9_]{2,}|[A-Za-z0-9_]+\.(?:res|RES|sct|tut|wav|bmp))$')


def is_texty(b, thresh=0.9):
    if not b or b.count(0) > len(b) * 0.02:
        return False
    try:
        s = b.decode('cp950')
    except Exception:
        return False
    ok = sum(1 for c in s if c.isprintable() or c in '\r\n\t')
    return ok >= len(s) * thresh


def scan_blob(b, minlen):
    """返回 [(词, 是否可疑)]"""
    out = []
    for m in WORD.finditer(b):
        w = m.group().decode('latin1')
        if len(w) < minlen:
            continue
        if ALLOW.match(w):
            continue
        # 纯大写短串多半是 ID
        if w.isupper() and len(w) <= 8 and ' ' not in w:
            continue
        out.append(w)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('root')
    ap.add_argument('--min', type=int, default=4)
    ap.add_argument('--json', default=None)
    a = ap.parse_args()

    total = 0
    report = {}
    for dirpath, _, fs in os.walk(a.root):
        if 'manifest.json' not in fs:
            continue
        m = json.load(open(os.path.join(dirpath, 'manifest.json'), encoding='utf-8'))
        rel = os.path.relpath(dirpath, a.root).replace('\\', '/')
        if rel.endswith('.unpacked'):
            rel = rel[:-len('.unpacked')]
        hits = []
        if m['type'] in ('residx', 'resource'):
            for rec in m['records']:
                if rec.get('sentinel'):
                    continue
                b = open(os.path.join(dirpath, 'records', rec['file']), 'rb').read()
                if not is_texty(b):
                    continue
                nm = bytes.fromhex(rec['name_raw']).rstrip(b'\x00').decode('latin1')
                ws = scan_blob(b, a.min)
                if ws:
                    hits.append((rec['index'], nm, len(b), ws[:12]))
        else:
            b = open(os.path.join(dirpath, m['file']), 'rb').read()
            if is_texty(b):
                ws = scan_blob(b, a.min)
                if ws:
                    hits.append((-1, os.path.basename(rel), len(b), ws[:12]))
        if hits:
            report[rel] = hits
            total += sum(len(h[3]) for h in hits)

    for rel in sorted(report):
        print('=== %s ===' % rel)
        for i, nm, sz, ws in report[rel]:
            print('   #%-4s %-10s %7dB  %s' % (i, nm, sz, ws))
        print()
    print('合计 %d 处疑似英文残留，分布在 %d 个文件' % (total, len(report)))

    if a.json:
        json.dump(report, open(a.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
