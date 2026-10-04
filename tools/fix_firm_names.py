# -*- coding: utf-8 -*-
"""
修复 FIRM / FIRM2 表（建筑名）的半成品残留与错译。

问题
----
1. 残留英文：译者按词替换中文，没清掉剩下的英文尾巴
     Seat of Power      -> 神壇 of Power
     Tower of Science   -> 科技塔   Science
     Espionage College  -> 間諜學院 College
     Alchemist Tor      -> 煉金塔    Tor
2. 译文过短：Inn 只剩一个「酒」字，界面上建筑标签几乎看不见
     Inn                -> 酒
3. 上轮修 Lair/Tor 残留时对 FIRM 表做了等长替换，产生重复译名
     Bheema Hyfe        -> 蜂巢   蜂巢
     Tarmes Mownd       -> 蟻穴   蟻丘

处理原则
--------
NAME 字段宽 20 字节、SHORTNAME 宽 12 字节，一律**等长替换**
（中文 + 空格填充），因此容器结构、记录长度、偏移表全部不变。
译名取自本表现有的合理译法，保持前后一致。
"""
import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db_table as D  # noqa: E402

# 原版英文名 -> 正确中文译名（等长填充）
FIRM_NAMES = {
    'Seat of Power':      '神壇',            # 原译文留下 " of Power"
    'Tower of Science':   '科技塔',          # 原译文留下 "   Science"
    'Espionage College':  '間諜學院',        # 原译文留下 " College"
    'Alchemist Tor':      '煉金塔',          # 原译文留下 "    Tor"
    'Inn':                '酒館',            # 原译文只剩「酒」
    'Bheema Hyfe':        '比瑪蜂巢',        # 原译文重复成「蜂巢   蜂巢」
    'Tarmes Mownd':       '白蟻丘',          # 原译文重复成「蟻穴   蟻丘」
    'Fryhtan Lair':       '異族巢穴',        # 「族」前那字节是坏字
    'Mage Tor':           '法力塔',          # 同上
    'Keraal':             '巨獸酒',          # 「猛酒」不成词
}

# 需要检查的表（两版内容相同，处理一次即可）
TARGETS = ['FIRM', 'FIRM2']


def field_text(raw):
    """字段原始字节 -> 去尾空格后的展示文本（cp950）"""
    return raw.rstrip(b'\x00 ').rstrip(b'\x00').decode('cp950', 'replace')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--chs', default='../unpack_data_chs')
    ap.add_argument('--orig', default='../unpack_data_original')
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()

    d_orig = os.path.join(args.orig, 'Resource', 'STD.SET.unpacked')
    d_chs = os.path.join(args.chs, 'Resource', 'STD.SET.unpacked')
    mo = json.load(open(os.path.join(d_orig, 'manifest.json'), encoding='utf-8'))
    mc = json.load(open(os.path.join(d_chs, 'manifest.json'), encoding='utf-8'))
    ro = {bytes.fromhex(r['name_raw']).rstrip(b'\x00').decode('latin1'): r for r in mo['records']}
    rc = {bytes.fromhex(r['name_raw']).rstrip(b'\x00').decode('latin1'): r for r in mc['records']}

    total = 0
    for tname in TARGETS:
        if tname not in rc:
            print('  %-6s 跳过（工作区无此表）' % tname)
            continue
        po = os.path.join(d_orig, 'records', ro[tname]['file'])
        pc = os.path.join(d_chs, 'records', rc[tname]['file'])
        bo = open(po, 'rb').read()
        bc = bytearray(open(pc, 'rb').read())

        fo, ro_, lo, no = D.record_layout(bo)
        fc, rc_, lc, nc = D.record_layout(bytes(bc))
        if (lo, no) != (lc, nc):
            print('  %-6s !! 两版布局不一致，放弃' % tname)
            continue
        FN = next(f for f in fo if f['name'] == 'NAME')
        if FN['width'] < 20:
            print('  %-6s !! NAME 字段宽 %d < 20，放弃' % (tname, FN['width']))
            continue

        hits = 0
        for i in range(no):
            raw_o, _ = D.str_field(bo, ro_, lo, i, FN)
            en = (raw_o or b'').rstrip(b'\x00 ').decode('latin1')
            zh = FIRM_NAMES.get(en)
            if not zh:
                continue
            enc = zh.encode('cp950')
            if len(enc) > FN['width']:
                print('  %-6s !! %-22s 译名 %d 字节 > 字段宽 %d，跳过'
                      % (tname, en, len(enc), FN['width']))
                continue
            # 等长替换：中文 + 空格填充到字段宽
            newv = enc + b' ' * (FN['width'] - len(enc))
            base = rc_ + i * lo + FN['off']
            if bytes(bc[base:base + FN['width']]) == newv:
                continue
            old = field_text(bytes(bc[base:base + FN['width']]))
            bc[base:base + FN['width']] = newv
            hits += 1
            total += 1
            print('  %-6s #%-3d %-22s %r -> %r' % (tname, i, en, old, zh))

        if hits == 0:
            print('  %-6s 无需修改' % tname)
        elif args.apply:
            if not os.path.exists(pc + '.bak'):
                shutil.copy2(pc, pc + '.bak')
            open(pc, 'wb').write(bytes(bc))
            # 写回后校验结构零变化
            _, rc2, lc2, nc2 = D.record_layout(open(pc, 'rb').read())
            assert (lc2, nc2) == (lo, no), '写回后布局变化！已回滚'
            print('  %-6s 已写入 %d 处（布局不变，备份 %s）'
                  % (tname, hits, os.path.basename(pc + '.bak')))

    print()
    print('合计 %d 处%s' % (total, '' if args.apply else '（干跑，加 --apply 写入）'))


if __name__ == '__main__':
    main()
