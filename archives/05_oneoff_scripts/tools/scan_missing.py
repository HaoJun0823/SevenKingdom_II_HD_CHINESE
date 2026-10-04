# -*- coding: utf-8 -*-
"""全量扫描游戏资源，找出「有字节对但字形池里没有字形」的字。

这些字在游戏里会渲染成空白 / 引擎方块，也就是用户看到的「乱码」。
输出按出现次数排序，供 gen_extra.py 补字形使用。

用法:
    scan_missing.py            # 扫描 update/Resource 下所有 .res/.set
    scan_missing.py -v         # 附带每次出现的上下文
"""
import os, sys, collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_text import Font, glyphs_of, ispair  # noqa: E402

GAME = r'I:\LocalGames\Seven Kingdoms II HD'
B = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 'SavenKingdom_II_HD_CHINESE')

CUST_LEAD_MIN, CUST_LEAD_COUNT = 0x90, 17


def cust_label(ft, lead, trail, gi):
    """尽量把自定义对还原成可读标签"""
    std = ft.custmap.get((lead, trail))
    if std:
        return bytes(std).decode('cp950')
    return '(自建#%d)' % gi


def main():
    verbose = '-v' in sys.argv
    R = os.path.join(GAME, 'update', 'Resource')
    ft = Font()
    miss = collections.Counter()
    ctx = collections.defaultdict(list)

    files = sorted(f for f in os.listdir(R)
                   if f.lower().endswith(('.res', '.set')))
    for fn in files:
        data = open(os.path.join(R, fn), 'rb').read()
        if fn.upper() == 'STD.SET' and '--nostd' in sys.argv:
            # 现在 STD.SET 也是原始 Big5（DLL 侧 oem=1 恒等化），默认一起扫
            continue
        gl = glyphs_of(ft, data)
        for k, (rows, m, tag) in enumerate(gl):
            if isinstance(tag, tuple) and m:
                if tag[0] >= CUST_LEAD_MIN and tag[0] < CUST_LEAD_MIN + CUST_LEAD_COUNT:
                    # 自定义对缺字形：通过字形列反查真实编码
                    miss[('C', tag)] += 1
                label = '%s:%02X%02X' % (fn, tag[0], tag[1])
                try:
                    ch = bytes(tag).decode('cp950')
                except Exception:
                    ch = '?'
                key = (ch, tag)
                miss[key] += 1
                if verbose and len(ctx[key]) < 3:
                    lo, hi = max(0, k - 8), min(len(gl), k + 8)
                    around = []
                    for a in range(lo, hi):
                        t = gl[a][2]
                        if isinstance(t, tuple):
                            try:
                                around.append(bytes(t).decode('cp950'))
                            except Exception:
                                around.append('.')
                        else:
                            around.append(t if t.strip() else '.')
                    ctx[key].append('%s@%d  ...%s...' % (fn, k, ''.join(around)))

    print('缺字形统计（update/Resource，已排除 STD.SET）:')
    print('%-6s %-10s %-12s %s' % ('字', 'Big5', '次数', '示例'))
    items = sorted(miss.items(), key=lambda kv: (-kv[1], kv[0][0]))
    for (ch, tag), n in items:
        if ch == 'C':
            continue
        hexcode = '%02X%02X' % tag
        sample = ctx[(ch, tag)][0] if ctx.get((ch, tag)) else ''
        print('%-6s %-10s %-12d %s' % (ch, hexcode, n, sample))
    print()
    print('合计 %d 种缺字形，%d 次出现'
          % (len([k for k in miss if k[0] != 'C']),
             sum(v for k, v in miss.items() if k[0] != 'C')))


if __name__ == '__main__':
    main()
