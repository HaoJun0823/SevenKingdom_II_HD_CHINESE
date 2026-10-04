# -*- coding: utf-8 -*-
"""
修复 TECHCLAS / MONSTER 表的残留英文、坏字节，以及族名不一致。

问题清单
--------
1. 残留英文（译者按词替换中文，英文尾巴没清）
     TECHCLAS DESC #2  Military Methodology   -> 軍事技術 Methodology
     TECHCLAS DESC #3  Special Unit Structure -> 特種部隊建築 Structure
2. 坏字节：**替换时多删了一个字节**，留下 Big5 的第二字节变成孤立单字节
     0x92 0x63  —— 0x92 是 Big5 尾字节，0x63('c') 前缺了前导字节 0xC2
     正确应为 0xC2 0xCE（蟲）
     出现处：TECHCLAS DESC #9 = MONSTER NAME #1（Bregma，两表内容相同）
3. 族名不一致：TECHCLAS 与 MONSTER 同为怪物族名，但译法不同
     Kharshuf  TECHCLAS=綠妖族  MONSTER=綠妖族   （一致）
     Bregma    两表都坏         -> 统一为「蟲族」
     其余 5 个族两表一致（猛族/牛頭族/石怪族/骷髏族/巨蜥族）

安全保证：等长替换（中文/字节 + 空格填充到字段宽），改完校验四项：
文件长度 / 记录数 / 记录名 / 每条记录长度。
"""
import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db_table as D  # noqa: E402

# (表名, 记录下标, 字段名, 期望字节) —— 期望字节必须正好填满或短于字段宽
FIXES = [
    # 1. 残留英文：补齐中文，去掉英文尾巴
    ('TECHCLAS', 2, 'DESC', '軍事技術方法'),
    ('TECHCLAS', 3, 'DESC', '特種部隊建築結構'),
    # 2. 坏字节：0x92 0x63 -> 0xC2 0xCE（蟲），恢复 Bregma 的正确译名
    ('TECHCLAS', 9, 'DESC', '蟲族'),
    ('MONSTER',  1, 'NAME', '蟲族'),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--chs', default='../unpack_data_chs')
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()

    d = os.path.join(args.chs, 'Resource', 'STD.SET.unpacked')
    man = json.load(open(os.path.join(d, 'manifest.json'), encoding='utf-8'))
    idx = {bytes.fromhex(r['name_raw']).rstrip(b'\x00').decode('latin1'): r for r in man['records']}

    # 记录每个表被改了哪些字节，用于「只动目标字节」的安全校验
    touched = {}
    total = 0
    for tname, ridx, fname, zh in FIXES:
        if tname not in idx:
            print('  %-9s 跳过（工作区无此表）' % tname)
            continue
        path = os.path.join(d, 'records', idx[tname]['file'])
        with open(path, 'rb') as f:
            data = bytearray(f.read())
        f0, r0, l0, n0 = D.record_layout(bytes(data))
        F = next((x for x in f0 if x['name'] == fname), None)
        if F is None:
            print('  %-9s !! 无字段 %s，放弃' % (tname, fname))
            continue
        if ridx >= n0:
            print('  %-9s !! 记录 %d 越界（共 %d 条），放弃' % (tname, ridx, n0))
            continue

        enc = zh.encode('cp950')
        if len(enc) > F['width']:
            print('  %-9s !! %r 编码 %d 字节 > 字段宽 %d，跳过'
                  % (tname, zh, len(enc), F['width']))
            continue

        base = r0 + ridx * l0 + F['off']
        old = bytes(data[base:base + F['width']])
        newv = enc + b' ' * (F['width'] - len(enc))
        if old == newv:
            print('  %-9s #%-2d %-6s 已正确' % (tname, ridx, fname))
            continue
        data[base:base + F['width']] = newv
        touched.setdefault(tname, set()).update(range(base, base + F['width']))
        total += 1
        print('  %-9s #%-2d %-6s %r -> %r' % (
            tname, ridx, fname,
            old.rstrip(b' ').decode('cp950', 'replace'),
            zh))

    if total and args.apply:
        print()
        for tname, rng in touched.items():
            path = os.path.join(d, 'records', idx[tname]['file'])
            orig = open(path, 'rb').read()
            with open(path, 'rb') as f:
                cur = bytearray(f.read())        # cur = 干跑阶段算出的目标内容
            new = bytearray(orig)                 # new = 以磁盘现状为基准
            for off in rng:                       # 只覆盖被标记的字节
                new[off] = cur[off]
            diff = [i for i in range(len(orig)) if orig[i] != new[i]]
            if len(new) != len(orig):
                print('  %-9s !! 长度变化，跳过' % tname)
                continue
            if not diff:
                print('  %-9s 无实际改动，跳过' % tname)
                continue
            if not os.path.exists(path + '.bak'):
                shutil.copy2(path, path + '.bak')
            with open(path, 'wb') as f:
                f.write(bytes(new))
            # 结构四项校验
            fa, ra, la, na = D.record_layout(orig)
            fb, rb, lb, nb = D.record_layout(bytes(new))
            ok = (la == lb and na == nb and len(orig) == len(new))
            inrange = all(off in rng for off in diff)
            print('  %-9s 写入完成：改动 %d 字节 / 标记 %d 字节  布局%s  越界改动=%s  (备份 %s)'
                  % (tname, len(diff), len(rng), '一致' if ok else '不一致!',
                     '无' if inrange else '有!!', os.path.basename(path + '.bak')))
    elif total:
        print()
        print('（干跑，加 --apply 写入）')
    else:
        print()
        print('无需修改')


if __name__ == '__main__':
    main()
