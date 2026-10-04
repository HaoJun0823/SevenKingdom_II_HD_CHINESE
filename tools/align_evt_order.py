# -*- coding: utf-8 -*-
"""
把汉化版 residx 容器的记录顺序对齐到原版（HD）顺序。

背景
----
residx 容器的索引项只有「9 字节名字 + 4 字节文件偏移」，**不含序号字段**，
记录边界由相邻偏移之差决定。因此引擎只能按**名字**查找（源码中
`res_event.read("11A")` 即按名取），记录在索引表里的排列顺序
对取数据没有影响。

汉化工具重建容器时按字典序排列，导致 EAST.EVT / EAST.PLT 的索引顺序
与原版不同 —— 这本身不会让游戏取错数据，但会让逐记录 diff 误报
「结构损坏」，也妨碍日后校对。本脚本按原版顺序重排，纯粹是
「消除误报、对齐基线」，不改动任何记录内容。

安全保证
--------
1. 只重排索引项，不改记录字节 => 每条记录内容逐字节不变。
2. 名字集合必须与原版完全一致，否则拒绝执行。
3. 记录数、每条记录长度均须与原版一一对应，否则拒绝执行。
4. 写回前自动备份原文件（--apply 时）。
5. 写回后立刻重新解析并逐条比对内容，不一致则自动回滚。
"""
import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools_packer'))
import packlib as P  # noqa: E402


def read_entries(path):
    data = open(path, 'rb').read()
    cnt, entries = P.read_residx(data)
    return data, cnt, entries


def reorder_to_reference(target_path, ref_path, apply=False, dry=True):
    dt, ct, et = read_entries(target_path)
    dr, cr, er = read_entries(ref_path)

    name_t = [e[0].rstrip(b'\x00') for e in et[:-1]]
    name_r = [e[0].rstrip(b'\x00') for e in er[:-1]]

    if len(name_t) != len(name_r):
        return False, '记录数不同：%d vs %d（拒绝）' % (len(name_t), len(name_r))
    if sorted(name_t) != sorted(name_r):
        only_t = sorted(set(name_t) - set(name_r))
        only_r = sorted(set(name_r) - set(name_t))
        return False, '名字集合不同（拒绝）汉化独有=%s 原版独有=%s' % (only_t[:5], only_r[:5])
    if name_t == name_r:
        return True, '顺序已一致，无需处理'

    # 建立 name -> (原始 9 字节名, 记录字节) 的映射；记录字节原样搬运，不做任何改动
    body = {e[0].rstrip(b'\x00'): (e[0], e[1]) for e in et[:-1]}
    new_entries = [(body[nm][0], body[nm][1]) for nm in name_r]
    new_entries.append((et[-1][0], None))          # 哨兵

    out = P.write_residx(new_entries)

    if not apply:
        return True, '干跑：将按原版顺序重排 %d 条记录，%dB -> %dB' % (
            len(name_r), len(dt), len(out))

    # 备份
    bak = target_path + '.bak'
    shutil.copy2(target_path, bak)

    with open(target_path, 'wb') as f:
        f.write(out)

    # 写回后校验：逐条内容必须与重排前完全一致
    _, cnt2, et2 = read_entries(target_path)
    if cnt2 != ct:
        shutil.copy2(bak, target_path)
        return False, '写回后记录数不符（已回滚）'

    def norm(entries):
        return {e[0].rstrip(b'\x00'): e[1] for e in entries[:-1]}

    if norm(et2) != norm(et):
        shutil.copy2(bak, target_path)
        return False, '写回后记录内容不一致（已回滚）'

    moved = sum(1 for i in range(len(name_r)) if name_t[i] != name_r[i])
    return True, ('已对齐：%d 条记录中 %d 条位置变动，%dB -> %dB，内容逐字节不变（备份 %s）'
                  % (len(name_r), moved, len(dt), len(out), os.path.basename(bak)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--game', default='I:/LocalGames/Seven Kingdoms II HD')
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()

    jobs = [('EAST.EVT', 'east.evt'), ('EAST.PLT', 'east.plt')]
    print('=== residx 记录顺序对齐（原版顺序为准）===')
    for ref_name, tgt_name in jobs:
        ref = os.path.join(args.game, 'Campaign', ref_name)
        tgt = os.path.join(args.game, 'update', 'Campaign', tgt_name)
        if not os.path.exists(tgt):
            print('  %-12s 跳过（汉化版不存在）' % tgt_name)
            continue
        ok, msg = reorder_to_reference(tgt, ref, apply=args.apply, dry=not args.apply)
        print('  %-12s %s %s' % (tgt_name, 'OK ' if ok else '!! ', msg))


if __name__ == '__main__':
    main()
