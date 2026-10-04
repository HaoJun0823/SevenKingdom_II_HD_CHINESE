# -*- coding: utf-8 -*-
"""校验「[u32 偏移][名字\\0] 索引 + 数据段」型资源的索引自洽性。

背景
----
部分 .res 不是纯文本，而是**索引 + 数据**容器：
    [u32 offset][ASCII name\0]  × N  ...  然后才是数据段
引擎按索引取名字对应的数据。旧汉化包把这些文件替换成更短的译文版本时，
**必须同步重建每个 offset**，否则引擎就会按旧偏移读到别处 ——
表现出来就是"位图/RLE 数据的行距远大于实际数据"→ 解码器读飞 → 崩溃。

本工具：解析索引，检查
  1. offset 单调递增且 < 文件长度；
  2. 段长度 = 下一个 offset - 本 offset，且 > 0；
  3. 与**同名的原版**做「名字集合」比对（应完全一致）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zhcode

GAME = zhcode.GAME
UP = zhcode.UP
ORIG = zhcode.ORIG


def _scan_from(d, i0, max_entries=512):
    out = []
    i = i0
    n = len(d)
    while i + 5 <= n and len(out) < max_entries:
        off = int.from_bytes(d[i:i + 4], 'little')
        j = i + 4
        k = j
        while k < n and d[k] != 0 and 0x20 <= d[k] < 0x7F:
            k += 1
        if k == j or k >= n or d[k] != 0:
            break
        name = d[j:k]
        if not (1 <= len(name) <= 32):
            break
        if off <= 0 or off >= n:
            break
        out.append((off, name, i))
        i = k + 1
    return out


def parse_index(d, max_entries=512):
    """自动探测 [u32 偏移][名字\\0] 索引的起点。

    这些文件前面可能有块头（如 `14 00 'FLC2'`），所以从 0..64 逐个起点试，
    取能连续解析出最多条目的那个（且 offset 必须单调递增）。
    """
    best = []
    for i0 in range(0, min(65, max(1, len(d) - 5))):
        got = _scan_from(d, i0, max_entries)
        if len(got) < 2:
            continue
        offs = [g[0] for g in got]
        if any(offs[k] >= offs[k + 1] for k in range(len(offs) - 1)):
            continue
        if len(got) > len(best):
            best = got
    return best


def check(name):
    op = os.path.join(UP, name)
    ep = os.path.join(ORIG, name)
    if not os.path.exists(op):
        return
    b = open(op, 'rb').read()
    a = open(ep, 'rb').read() if os.path.exists(ep) else None
    idx_b = parse_index(b)
    idx_a = parse_index(a) if a is not None else None
    print('### %-16s 我方 %7d 字节, 索引 %3d 条' % (name, len(b), len(idx_b)), end='')
    if idx_a is not None:
        print('   原版 %7d 字节, 索引 %3d 条' % (len(a), len(idx_a)))
    else:
        print('   (无原版)')
    if not idx_b:
        print('    -> 非索引型，跳过')
        return
    # 1) offset 单调 & 越界
    bad = []
    prev = None
    for off, nm, at in idx_b:
        if prev is not None and off <= prev:
            bad.append('非单调/重复: %r off=0x%X <= 前 0x%X' % (nm, off, prev))
        if off >= len(b):
            bad.append('越界: %r off=0x%X >= %d' % (nm, off, len(b)))
        prev = off
    # 2) 段长
    for k, (off, nm, at) in enumerate(idx_b):
        end = idx_b[k + 1][0] if k + 1 < len(idx_b) else (
            (idx_a[k + 1][0] if idx_a and k + 1 < len(idx_a) else len(b)))
        # 最后一段长度用「文件尾 - 索引区尾」的上界估计
        if k + 1 >= len(idx_b):
            end = len(b)
        if end - off <= 0:
            bad.append('段长为 0 或负: %r 0x%X..0x%X' % (nm, off, end))
    # 3) 名字集合
    if idx_a:
        na = [x[1] for x in idx_a]
        nb = [x[1] for x in idx_b]
        if na != nb:
            only_a = [x for x in na if x not in nb]
            only_b = [x for x in nb if x not in na]
            bad.append('名字集合/顺序不一致; 仅原版有=%r 仅我方有=%r' % (only_a[:6], only_b[:6]))
    if bad:
        print('   [!!] %d 个问题:' % len(bad))
        for x in bad[:8]:
            print('        %s' % x)
    else:
        print('   [OK] 索引自洽（offset 单调、无越界、段长>0、名字集合与原版一致）')
    print('        索引区结束于 0x%X，首段 0x%X..0x%X' % (
        idx_b[-1][2] + 5, idx_b[0][0],
        idx_b[1][0] if len(idx_b) > 1 else len(b)))


def main():
    names = sorted(f for f in os.listdir(UP) if f.lower().endswith('.res'))
    for nm in names:
        check(nm)


if __name__ == '__main__':
    main()
