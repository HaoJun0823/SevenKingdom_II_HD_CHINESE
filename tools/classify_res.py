#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""普查 update\\Resource 下每个资源用的是哪种编码约定。

判据：把文件里的每个双字节对，分别按两种假设去字形库里查：
    RAW   : 直接用 (b1, b2)                 -> 引擎不过表时引擎看到的码
    MAPPED: 用 (T[b1], T[b2])               -> 引擎过 cp437->Latin1 表后看到的码
哪个命中率高，哪个就是该文件的真实约定。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from fontlib import FontTable, iter_pairs, B5_LEAD_MIN, B5_LEAD_MAX  # noqa: E402
from gen_stdmap import T                                             # noqa: E402

RES = r'I:\LocalGames\Seven Kingdoms II HD\update\Resource'


def engine_map(b):
    return T[b] if b >= 0x80 else b


def is_pair(b1, b2):
    if B5_LEAD_MIN <= b1 <= B5_LEAD_MAX and (0x40 <= b2 <= 0x7E or 0xA1 <= b2 <= 0xFE):
        return True
    if 0x90 <= b1 <= 0xA0 and 0x40 <= b2 <= 0x7E:
        return True
    return False


def glyph_hit(ft, b1, b2):
    """返回 (是否有字形, 说明)"""
    if 0x90 <= b1 <= 0xA0:
        return ft.pair2glyph.get((b1, b2)) is not None
    if B5_LEAD_MIN <= b1 <= B5_LEAD_MAX:
        return ft.glyph_of_std((b1, b2)) != 0
    return False


def main():
    ft = FontTable()
    files = sorted(f for f in os.listdir(RES)
                   if os.path.isfile(os.path.join(RES, f)))
    print('%-24s %8s %9s %9s  %s' % ('file', 'pairs', 'raw-hit', 'map-hit', '判定'))
    print('-' * 78)
    verdicts = {}
    for f in files:
        data = open(os.path.join(RES, f), 'rb').read()
        nraw = nmap = tot = 0
        for pos, kind, pair, raw in iter_pairs(data):
            b1, b2 = pair
            tot += 1
            if glyph_hit(ft, b1, b2):
                nraw += 1
            m1, m2 = engine_map(b1), engine_map(b2)
            if is_pair(m1, m2) and glyph_hit(ft, m1, m2):
                nmap += 1
        if tot == 0:
            print('%-24s %8d %9s %9s  %s' % (f, 0, '-', '-', '无双字节对'))
            continue
        pr = 100.0 * nraw / tot
        pm = 100.0 * nmap / tot
        if pr >= pm + 3:
            v = 'RAW  (引擎不过表)'
        elif pm >= pr + 3:
            v = '★MAP (引擎过表 -> 需预补偿)'
        else:
            v = '? 两者接近'
        verdicts[f] = (tot, pr, pm, v)
        print('%-24s %8d %8.1f%% %8.1f%%  %s' % (f, tot, pr, pm, v))

    print()
    print('== 需要在恒等化后重新生成的（当前是 MAP 约定）==')
    any_map = False
    for f, (tot, pr, pm, v) in verdicts.items():
        if v.startswith('★MAP'):
            print('   %-24s pairs=%-7d raw=%.1f%% map=%.1f%%' % (f, tot, pr, pm))
            any_map = True
    if not any_map:
        print('   （无）')


if __name__ == '__main__':
    main()
