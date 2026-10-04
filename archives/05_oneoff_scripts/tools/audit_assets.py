# -*- coding: utf-8 -*-
"""汉化资产体检：把 update\\Resource 下所有文件过一遍，回答
   ① 有没有「编不出/查不到字形」的字（会显示成空白或方块）
   ② 有没有非法双字节对（字节错位、写坏）
   ③ 有没有残留的英文长串（可能漏译）
   ④ STD.SET 另按「结构化数据」单独体检

用法：
  python audit_assets.py              体检 update\\Resource
  python audit_assets.py --dir <路径>
"""
import os
import re
import sys
import collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_text as rt
from fontlib import BAD_TRAILS

GAME = r'I:\LocalGames\Seven Kingdoms II HD'
RES = os.path.join(GAME, 'update', 'Resource')
ORIG_RES = os.path.join(GAME, 'Resource')

ft = rt.Font()

SKIP_PAIRSCAN = {'STD.SET'}          # 结构化二进制，另处理
ASCII_RUN = re.compile(rb'[A-Za-z][A-Za-z0-9 ,.\'/()\-]{5,}')


def pairs_of(data):
    """按 Big5 规则切出双字节对与孤立单字节位置"""
    pairs, loose = [], []
    i, n = 0, len(data)
    while i < n:
        b = data[i]
        if b >= 0x80 and i + 1 < n and rt.ispair(b, data[i + 1]):
            pairs.append((i, b, data[i + 1]))
            i += 2
        else:
            if b >= 0x80:
                loose.append((i, b))
            i += 1
    return pairs, loose


def audit_res(path, name):
    data = open(path, 'rb').read()
    r = {'name': name, 'size': len(data), 'pairs': 0, 'missing': [],
         'loose': 0, 'bad_loose': [], 'english': [], 'text_bad': 0}
    if name.upper() in SKIP_PAIRSCAN:
        r['skip'] = True
        return r

    pairs, loose = pairs_of(data)
    r['pairs'] = len(pairs)
    r['loose'] = len(loose)

    seen_missing = {}
    for off, b1, b2 in pairs:
        if ft.glyph(b1, b2) is None:
            if (b1, b2) not in seen_missing:
                seen_missing[(b1, b2)] = (off, data[off:off + 22])
    r['missing'] = seen_missing

    # 孤立高位字节：真文本里不该出现（除结构化字段）
    for off, b in loose:
        if len(r['bad_loose']) < 8:
            r['bad_loose'].append((off, b))

    # 残留英文长串
    for m in ASCII_RUN.finditer(data):
        s = m.group(0)
        # 纯数字/ID 之类噪声过滤
        if len(re.sub(rb'[^A-Za-z]', b'', s)) >= 5:
            if len(r['english']) < 12:
                r['english'].append((m.start(), s.decode('latin1')))

    # 整文件按 cp950 解，统计解不出来的位置
    bad = 0
    for i, ch in enumerate(data.decode('cp950', 'replace')):
        if ch == '\ufffd':
            bad += 1
    r['text_bad'] = bad
    return r


def main():
    d = RES
    if '--dir' in sys.argv:
        d = sys.argv[sys.argv.index('--dir') + 1]
    files = sorted(os.listdir(d))
    print('体检目录:', d)
    print('=' * 96)
    print('%-16s %8s %7s %7s %8s %8s  %s' %
          ('文件', '字节', '双字节对', '孤立高位', '缺字形', '坏字节', '残留英文串'))
    print('-' * 96)
    total_missing = {}
    problems = []
    rows = []
    for f in files:
        p = os.path.join(d, f)
        if not os.path.isfile(p):
            continue
        r = audit_res(p, f)
        if r.get('skip'):
            print('%-16s %8d %7s %7s %8s %8s  (结构化，单独体检)' %
                  (f, r['size'], '-', '-', '-', '-'))
            continue
        nm = len(r['missing'])
        print('%-16s %8d %7d %7d %8d %8d  %s' %
              (f, r['size'], r['pairs'], r['loose'], nm, r['text_bad'],
               ('%d 处' % len(r['english'])) if r['english'] else ''))
        for k, v in r['missing'].items():
            total_missing[k] = (f, v[0], v[1])
        if nm or r['text_bad'] or r['loose'] > 0:
            problems.append((f, r))
        rows.append((f, r))

    print('=' * 96)
    print()
    print('【缺字形汇总】共 %d 种' % len(total_missing))
    if not total_missing:
        print('   （无 —— 所有译文字都能画出来）')
    for (b1, b2), (f, off, ctx) in sorted(total_missing.items()):
        try:
            ch = bytes((b1, b2)).decode('cp950')
        except Exception:
            ch = '?'
        print('   %02X%02X %-4s  %s @0x%X  上下文 %r' % (b1, b2, ch, f, off, ctx[:18]))
    print()

    print('【可能漏译的英文串】（不一定有问题：单位/建筑名、文件名、内部标识）')
    print()
    for f, r in rows:
        if not r['english']:
            continue
        print('  %s:' % f)
        for off, s in r['english'][:8]:
            print('     0x%-6X %s' % (off, s))
    print()

    print('【孤立高位字节】（真文本里不该有，多为结构化字段，需人判）')
    any_loose = False
    for f, r in rows:
        if r['loose']:
            any_loose = True
            print('  %-16s %d 个  例: %s' % (f, r['loose'],
                  ' '.join('0x%X:%02X' % (o, b) for o, b in r['bad_loose'][:5])))
    if not any_loose:
        print('   （无）')
    print()

    print('【坏字节（cp950 解不出）】')
    anybad = [(f, r['text_bad']) for f, r in rows if r['text_bad']]
    if anybad:
        for f, n in anybad:
            print('  %-16s %d 处' % (f, n))
    else:
        print('   （无）')


if __name__ == '__main__':
    main()
