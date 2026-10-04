# -*- coding: utf-8 -*-
"""
修复「坏字节」：替换时错位导致 Big5 前导字节丢失，中文变乱码。

症状
----
译文字段解码后出现 U+FFFD（cp950 解不出的字节），例如
    OVERTITLE  92 63 B1 DA ...  ->  '<坏字>c族'
原版该字段是纯英文 'Fryhtan '（9 字节）。

成因
----
译者做「英文 → 中文」等长替换时，把 'Fr'（46 72）替换成了 '異'（B2 A7），
但整体**右移了 1 字节**（可能是按字符数而非字节数对齐），导致
'異' 的前导字节 B2 丢失、尾字节 A7 与后续 '族' 的 B1 拼成 A7 B1（非法），
剩下一组孤立尾字节。此类损坏在 FIRM/FIRM2 的 OVERTITLE/WORKTITLE
（宽 10 字节，最容易发生）与 MONSTER/TECHCLAS 都能看到。

处理原则
--------
1. **只按字节定位，不做模糊猜测**：每条修复都写明「表 / 记录下标 / 字段 /
   原英文名」，用原版同位置的英文内容作为锚点。
2. 等长替换（中文 + 空格填充到字段宽），改完校验文件长度 / 记录数 /
   记录名 / 每条记录长度四项不变。
3. 只覆盖目标字段的字节范围，杜绝误伤其它字段。
"""
import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db_table as D  # noqa: E402

# (表, 记录下标, 字段, 该字段原版英文, 正确中文)
BAD = [
    # FIRM / FIRM2 的 Fryhtan 系（记录 11~20 共 10 条，OVERTITLE+WORKTITLE）
    # 'Fr' 替换成 '異' 时右移 1 字节 -> 92 63 残留
    *[('FIRM',  i, fld, 'Fryhtan', '異族') for i in range(11, 21) for fld in ('OVERTITLE', 'WORKTITLE')],
    *[('FIRM2', i, fld, 'Fryhtan', '異族') for i in range(11, 21) for fld in ('OVERTITLE', 'WORKTITLE')],
    # MONSTER / TECHCLAS 的 Bregma（'Br' 替换成 '蟲' 时同样错位）
    ('MONSTER',   1, 'NAME', 'Bregma', '蟲族'),
    ('TECHCLAS',  9, 'DESC', 'Bregma', '蟲族'),
    # RACE #5 Carthaginian：'Ca' 替换成 '迦' 时错位
    ('RACE',      5, 'NAME',      'Carthaginian', '迦太基'),
    ('RACE',      5, 'ADJECTIVE', 'Carthaginian', '迦太基'),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--chs', default='../unpack_data_chs')
    ap.add_argument('--orig', default='../unpack_data_original')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args()

    d_o = os.path.join(args.orig, 'Resource', 'STD.SET.unpacked')
    d_c = os.path.join(args.chs, 'Resource', 'STD.SET.unpacked')
    mo = json.load(open(os.path.join(d_o, 'manifest.json'), encoding='utf-8'))
    mc = json.load(open(os.path.join(d_c, 'manifest.json'), encoding='utf-8'))
    ro = {bytes.fromhex(r['name_raw']).rstrip(b'\x00').decode('latin1'): r for r in mo['records']}
    rc = {bytes.fromhex(r['name_raw']).rstrip(b'\x00').decode('latin1'): r for r in mc['records']}

    # 每个表：干跑算出目标字节，记录要改的偏移
    target = {}
    touched = {}
    hit = 0
    for tname, ridx, fname, expect_en, zh in BAD:
        if tname not in rc or tname not in ro:
            continue
        po = os.path.join(d_o, 'records', ro[tname]['file'])
        pc = os.path.join(d_c, 'records', rc[tname]['file'])
        bo = open(po, 'rb').read()
        bc = target.get(tname) or bytearray(open(pc, 'rb').read())

        fo, ro_, lo, no = D.record_layout(bo)
        F = next((x for x in fo if x['name'] == fname), None)
        if F is None or ridx >= no:
            print('  !! %-9s #%-3d %-10s 字段或记录不存在' % (tname, ridx, fname))
            continue
        # 锚点校验：原版该字段必须等于我们以为的英文
        oa, _ = D.str_field(bo, ro_, lo, ridx, F)
        oa_t = (oa or b'').rstrip(b'\x00 ').decode('latin1', 'replace')
        if oa_t != expect_en:
            if args.verbose:
                print('  ~~ %-9s #%-3d %-10s 原版是 %r 不是 %r，跳过'
                      % (tname, ridx, fname, oa_t, expect_en))
            continue

        fc, rc_, lc, nc = D.record_layout(bytes(bc))
        base = rc_ + ridx * lc + F['off']
        cur = bytes(bc[base:base + F['width']])
        want = zh.encode('cp950')
        if len(want) > F['width']:
            print('  !! %-9s #%-3d %-10s %r 需 %d 字节 > 宽 %d，跳过'
                  % (tname, ridx, fname, zh, len(want), F['width']))
            continue
        newv = want + b' ' * (F['width'] - len(want))
        if cur == newv:
            continue
        bc[base:base + F['width']] = newv
        target[tname] = bc
        touched.setdefault(tname, set()).update(range(base, base + F['width']))
        hit += 1
        print('  %-9s #%-3d %-10s %r -> %r' % (
            tname, ridx, fname,
            cur.rstrip(b' ').decode('cp950', 'replace'), zh))

    print()
    print('命中 %d 处' % hit)
    if not hit:
        return
    if not args.apply:
        print('（干跑，加 --apply 写入）')
        return

    for tname, rng in touched.items():
        path = os.path.join(d_c, 'records', rc[tname]['file'])
        orig = open(path, 'rb').read()
        new = bytearray(orig)
        cur = target[tname]
        for off in rng:
            new[off] = cur[off]
        diff = [i for i in range(len(orig)) if orig[i] != new[i]]
        if len(new) != len(orig):
            print('  %-9s !! 长度变化，跳过' % tname)
            continue
        if not diff:
            print('  %-9s 无实际改动' % tname)
            continue
        if not os.path.exists(path + '.bak'):
            shutil.copy2(path, path + '.bak')
        with open(path, 'wb') as f:
            f.write(bytes(new))
        fa, ra, la, na = D.record_layout(orig)
        fb, rb, lb, nb = D.record_layout(bytes(new))
        ok = (la == lb and na == nb)
        inr = all(o in rng for o in diff)
        print('  %-9s 写入 %d 字节 / 标记 %d 字节  布局%s  越界改动=%s'
              % (tname, len(diff), len(rng), '一致' if ok else '不一致!',
                 '无' if inr else '有!!'))


if __name__ == '__main__':
    main()
