# -*- coding: utf-8 -*-
"""对比「原版解包」与「汉化解包」，找出三类问题：

  1. 结构损坏 —— 记录数 / 记录名(name_raw) 与原版不一致
                 （汉化时动过索引区，是最危险的改动）
  2. 漏翻     —— 记录内容与原版**完全相同**（没动过）
  3. 骨架损坏 —— 文本里 %Nx 占位符 / 控制符({ } | ~ _) 的数量与原版不符
                 （翻译时丢了占位符，游戏里就会少数字、少单位、断行错乱）

用法:
    python diff_unpack.py [--orig <目录>] [--cht <目录>] [--json <报告.json>]
"""
import os
import re
import sys
import json
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)

DEFAULT_ORIG = os.path.join(PROJ, 'unpack_data_original')
DEFAULT_CHT = os.path.join(PROJ, 'unpack_data_cht')

# 运行产物，不参与对比
SKIP = {'render.ini', 'sk2_zh.log'}

PAT = re.compile(rb'%(\d)(?:,(\d))?([a-zA-Z%?])')
CTRL = [0x7B, 0x7D, 0x7C, 0x7E, 0x5F, 0x5B, 0x5D]   # { } | ~ _ [ ]


def trail_ok(t):
    """Big5 合法尾字节（也覆盖我们自定义对的尾字节范围）"""
    return (0x40 <= t <= 0x7E) or (0xA1 <= t <= 0xFE)


def ctrl_counts(b):
    """按「双字节优先」解析，只统计**单字节位置**的控制符。

    ★ 必须这样：Big5 汉字的尾字节正好落在 0x40-0x7E，也就是 `{}|~[]_` 所在区间。
      若对原始字节直接 count()，中文会被大量误判成「控制符丢失」——
      例如 `A4 7C` 的尾字节 0x7C 就是 '|'。早期版本正是这么误报的。
    """
    cnt = {c: 0 for c in CTRL}
    i, n = 0, len(b)
    while i < n:
        c = b[i]
        if c >= 0x81 and i + 1 < n and trail_ok(b[i + 1]):
            i += 2                      # 双字节字符，整体跳过
            continue
        if c in cnt:
            cnt[c] += 1
        i += 1
    return [cnt[c] for c in CTRL]


def find_set(root):
    """返回 {相对路径小写(去 .unpacked): 目录绝对路径}"""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        if 'manifest.json' in filenames and dirpath.endswith('.unpacked'):
            rel = os.path.relpath(dirpath, root)[:-len('.unpacked')]
            out[rel.replace('\\', '/').lower()] = dirpath
    return out


def load(d):
    m = json.load(open(os.path.join(d, 'manifest.json'), encoding='utf-8'))
    t = m['type']
    if t in ('residx', 'resource'):
        recs = []
        for rm in m['records']:
            if rm.get('sentinel'):
                recs.append((rm['index'], bytes.fromhex(rm['name_raw']), None))
            else:
                b = open(os.path.join(d, 'records', rm['file']), 'rb').read()
                recs.append((rm['index'], bytes.fromhex(rm['name_raw']), b))
        return t, recs
    b = open(os.path.join(d, m['file']), 'rb').read()
    return t, [(-1, b'', b)]


def dec(b):
    try:
        return b.decode('cp950')
    except Exception:
        return b.decode('cp950', 'replace')


def is_texty(b):
    """粗略判定：能当 cp950 解码且可打印比例高"""
    if not b:
        return False
    if b.count(0) > len(b) * 0.02:
        return False
    try:
        s = b.decode('cp950')
    except Exception:
        try:
            b.decode('latin1')
        except Exception:
            return False
        return False
    printable = sum(1 for c in s if c.isprintable() or c in '\r\n\t')
    return printable >= len(s) * 0.92


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--orig', default=DEFAULT_ORIG)
    ap.add_argument('--cht', default=DEFAULT_CHT)
    ap.add_argument('--json', default=None)
    a = ap.parse_args()

    O, C = find_set(a.orig), find_set(a.cht)
    only_o = sorted(set(O) - set(C))
    only_c = sorted(set(C) - set(O))
    common = sorted(set(O) & set(C))

    print('原版解包 %d 个 | 汉化解包 %d 个 | 共有 %d 个'
          % (len(O), len(C), len(common)))
    print()

    # ── 一、覆盖情况 ────────────────────────────────────────
    print('=' * 78)
    print('一、覆盖情况')
    print('=' * 78)
    print('汉化未覆盖（原版有、汉化无）: %d 个' % len(only_o))
    for k in only_o:
        print('    - %s' % k)
    if only_c:
        print('汉化多出（汉化有、原版无）: %d 个' % len(only_c))
        for k in only_c:
            print('    + %s' % k)
    print()

    # ── 二、逐文件对比 ──────────────────────────────────────
    struct_bad, miss, skel_bad, trans = [], [], [], []
    text_files = []

    for k in common:
        base = os.path.basename(k)
        if base in SKIP:
            continue
        to, ro = load(O[k])
        tc, rc = load(C[k])
        if to != tc:
            struct_bad.append((k, '容器类型不同 %s -> %s' % (to, tc)))
            continue
        if to in ('residx', 'resource'):
            if len(ro) != len(rc):
                struct_bad.append((k, '记录数 %d -> %d' % (len(ro), len(rc))))
                continue
            for (io, no, bo), (ic, nc, bc) in zip(ro, rc):
                if no != nc:
                    struct_bad.append((k, '第 %d 条名不同 %r -> %r' % (io, no, nc)))
                if bo is None or bc is None:
                    continue
                if bo == bc:
                    miss.append((k, io, no))
                else:
                    trans.append((k, io, no))
                    if is_texty(bo) and is_texty(bc):
                        if sorted(PAT.findall(bo)) != sorted(PAT.findall(bc)):
                            skel_bad.append((k, io, no, '占位符',
                                             sorted(PAT.findall(bo)), sorted(PAT.findall(bc))))
                        co, cc = ctrl_counts(bo), ctrl_counts(bc)
                        if co != cc:
                            skel_bad.append((k, io, no, '控制符', co, cc))
        else:
            bo, bc = ro[0][2], rc[0][2]
            if is_texty(bo):
                text_files.append(k)
            if bo == bc:
                miss.append((k, -1, b''))
            else:
                trans.append((k, -1, b''))
                if is_texty(bo) and is_texty(bc):
                    if sorted(PAT.findall(bo)) != sorted(PAT.findall(bc)):
                        skel_bad.append((k, -1, b'', '占位符',
                                         sorted(PAT.findall(bo)), sorted(PAT.findall(bc))))
                    co, cc = ctrl_counts(bo), ctrl_counts(bc)
                    if co != cc:
                        skel_bad.append((k, -1, b'', '控制符', co, cc))

    # ── 三、结果 ────────────────────────────────────────────
    print('=' * 78)
    print('二、结构损坏（记录数 / 记录名与原版不一致）')
    print('=' * 78)
    if struct_bad:
        for x in struct_bad:
            print('  [!!] %s  %s' % (x[0], x[1]))
    else:
        print('  无 —— 所有共有文件的记录数、记录名与原版一致 ✓')
    print()

    print('=' * 78)
    print('三、格式骨架损坏（占位符 / 控制符数量与原版不符）')
    print('=' * 78)
    if skel_bad:
        for k, i, n, what, o, c in skel_bad[:60]:
            print('  [!!] %s #%s %s  %s  %s -> %s'
                  % (k, i, dec(n) if n else '', what, o, c))
        if len(skel_bad) > 60:
            print('  ... 共 %d 处' % len(skel_bad))
    else:
        print('  无 —— 占位符与控制符均与原版一致 ✓')
    print()

    print('=' * 78)
    print('四、漏翻（内容与原版完全相同）')
    print('=' * 78)
    print('  合计 %d 条未翻译' % len(miss))
    agg = {}
    for k, i, n in miss:
        agg[k] = agg.get(k, 0) + 1
    for k in sorted(agg, key=lambda x: -agg[x]):
        print('    %-52s %d 条' % (k, agg[k]))
    print()

    print('=' * 78)
    print('五、统计')
    print('=' * 78)
    print('  已翻译记录: %d 条' % len(trans))
    print('  未翻译记录: %d 条' % len(miss))
    print('  结构损坏  : %d 处' % len(struct_bad))
    print('  骨架损坏  : %d 处' % len(skel_bad))
    print('  文本类非容器文件: %d 个' % len(text_files))
    for k in text_files:
        print('    - %s' % k)

    if a.json:
        json.dump({
            'only_orig': only_o, 'only_cht': only_c,
            'struct_bad': [[k, m] for k, m in struct_bad],
            'skel_bad': [[k, i, what, str(o), str(c)] for k, i, n, what, o, c in skel_bad],
            'missing': [[k, i] for k, i, n in miss],
            'translated': len(trans),
            'text_files': text_files,
        }, open(a.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        print('\n报告已写入 %s' % a.json)


if __name__ == '__main__':
    main()
