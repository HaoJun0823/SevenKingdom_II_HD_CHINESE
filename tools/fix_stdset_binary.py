# -*- coding: utf-8 -*-
"""修复 STD.SET 里「把二进制数值字段当成汉字」的误伤。

## 背景（实测取证）

STD.SET 是 52 段的结构化二进制。其中 SFRAME / FBITMAP / FBITMAP2 等段内
是「名字 + u32 偏移」的紧凑表，例如：

    "NO-A5-7 " | a8 7c 00 00 | " NO_CIV"   →  u32 偏移 = 0x00007ca8 = 31912

这些 u32 的低两字节是纯数值，但**恰好落在大五码危险尾字节范围**
（第二字节 ∈ {5B,5C,5D,7B,7C,7D,7E,7F}）时，我们的「危险尾字节 → 自定义对」
重映射会把它当成汉字改写：

    a8 7c  →  91 6f        偏移 31912 变成 28561

后果：引擎按错误偏移去读精灵/位图数据 → RLE 解码器越过缓冲区读飞
→ 崩溃在 7K2+0x2750（sub_40274B「在压缩流里跳过 N 个像素」）。

## 判据

只恢复**同时满足**以下几条的改动，绝不碰真正的汉化文本：
  1. 原版该处两字节是合法标准大五码对（lead 0xA1..0xF9）
  2. 且尾字节属于危险集（否则当初不会被重映射）
  3. 汉化版该处两字节是自定义对（lead 0x90..0xA0）
  4. 且紧随其后是「00 / 01 / 02 …」这类小数值的高位字节，
     即构成一个 u32 数值字段（偏移/长度/索引），而不是文本
  5. 或者该处位于明确的二进制段（SFRAME / FBITMAP / FBITMAP2）

用法：
    python fix_stdset_binary.py            # 干跑，只报告
    python fix_stdset_binary.py --apply    # 写盘（先备份到 res_backup/）
"""
import os
import struct
import shutil
import sys
import time

GAME = r'I:\LocalGames\Seven Kingdoms II HD'
ORIG = os.path.join(GAME, 'Resource', 'STD.SET')
OURS = os.path.join(GAME, 'update', 'Resource', 'STD.SET')
BACKUP = os.path.join(r'G:\Projects\SavenKingdom_II_HD_CHINESE', 'res_backup')

# 危险尾字节：与 fontlib.BAD_TRAILS 保持一致
BAD_TRAILS = {0x5B, 0x5C, 0x5D, 0x7B, 0x7C, 0x7D, 0x7E, 0x7F}
# 大五码标准 lead 范围
B5_LEAD_MIN, B5_LEAD_MAX = 0xA1, 0xF9
# 自定义对 lead 范围
CUST_LEAD_MIN, CUST_LEAD_MAX = 0x90, 0xA0
# 明确的二进制段（里面不含任何需要翻译的文本）
BINARY_SEGS = {'SFRAME', 'FBITMAP', 'FBITMAP2'}


def segments(d):
    """STD.SET 索引：u16 计数 + N+1 条 (name[9], u32 offset)。"""
    cnt = struct.unpack('<H', d[0:2])[0]
    idx = []
    for i in range(cnt + 1):
        off = 2 + i * 13
        name = d[off:off + 9].rstrip(b'\x00').decode('latin-1')
        idx.append((name, struct.unpack('<I', d[off + 9:off + 13])[0]))
    return cnt, idx


def is_u32_field(orig, pos):
    """原版 pos 处是否像一个 u32 数值字段（偏移/长度/索引）。

    特征：低 2 字节之后紧跟一个 <= 0x0F 的字节（值的高位字节），
    因为精灵/位图表里的偏移都远小于 0x100000。
    """
    if pos + 3 >= len(orig):
        return False
    b2, b3 = orig[pos + 2], orig[pos + 3]
    return b2 <= 0x0F and b3 == 0x00


def scan(orig, ours, seg_bounds):
    """返回误伤位置列表 [(文件绝对偏移, 段名, 原版2B, 汉化2B)]。"""
    hits = []
    for name, s, e in seg_bounds:
        in_binary = name in BINARY_SEGS
        for p in range(s, e - 1):
            if orig[p] == ours[p] and orig[p + 1] == ours[p + 1]:
                continue
            lead_o, trail_o = orig[p], orig[p + 1]
            lead_n, trail_n = ours[p], ours[p + 1]
            # 必须是「标准大五码对」被改成了「自定义对」
            if not (B5_LEAD_MIN <= lead_o <= B5_LEAD_MAX):
                continue
            if not (CUST_LEAD_MIN <= lead_n <= CUST_LEAD_MAX):
                continue
            if trail_o not in BAD_TRAILS:
                continue
            if not (in_binary or is_u32_field(orig, p)):
                continue
            hits.append((p, name, bytes(orig[p:p + 2]), bytes(ours[p:p + 2])))
    return hits


def main():
    apply_changes = '--apply' in sys.argv

    orig = open(ORIG, 'rb').read()
    ours = bytearray(open(OURS, 'rb').read())
    if len(orig) != len(ours):
        print('[!] 两版长度不同：原版 %d / 汉化 %d' % (len(orig), len(ours)))
        return 1

    cnt, idx = segments(orig)
    bounds = [(idx[i][0], idx[i][1], idx[i + 1][1]) for i in range(cnt)]

    hits = scan(orig, ours, bounds)
    print('原版 %d 字节，%d 段' % (len(orig), cnt))
    print('检出「二进制数值被当汉字改写」的位置：%d 处' % len(hits))
    print()

    by_seg = {}
    for p, name, o, n in hits:
        by_seg.setdefault(name, []).append((p, o, n))
    for name in sorted(by_seg, key=lambda k: -len(by_seg[k])):
        lst = by_seg[name]
        print('  %-10s %3d 处' % (name, len(lst)))
        for p, o, n in lst[:6]:
            print('      文件 0x%07X  %s -> %s   其后: %s' % (
                p, o.hex(), n.hex(), orig[p + 2:p + 6].hex()))
        if len(lst) > 6:
            print('      … 其余 %d 处略' % (len(lst) - 6))
    print()

    if not hits:
        print('没有需要修复的位置。')
        return 0

    if not apply_changes:
        print('（干跑，未写盘。加 --apply 实际修复）')
        return 0

    os.makedirs(BACKUP, exist_ok=True)
    bak = os.path.join(BACKUP, 'STD.SET_%s' % time.strftime('%m%d_%H%M%S'))
    shutil.copy2(OURS, bak)
    print('已备份 ->', bak)

    for p, _name, o, _n in hits:
        ours[p] = o[0]
        ours[p + 1] = o[1]
    open(OURS, 'wb').write(bytes(ours))
    print('已写回 %s，修复 %d 处' % (OURS, len(hits)))

    # 复核
    chk = open(OURS, 'rb').read()
    left = scan(orig, chk, bounds)
    print('复核：剩余误伤 %d 处' % len(left))
    return 0


if __name__ == '__main__':
    sys.exit(main())
