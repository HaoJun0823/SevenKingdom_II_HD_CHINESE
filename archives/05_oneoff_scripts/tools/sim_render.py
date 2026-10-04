# -*- coding: utf-8 -*-
"""离线复刻 cjk.cpp 的双字节切分与字形查询，用于定位渲染侧丢字问题。"""
import os
import re
import sys

ROOT = r'G:\Projects\SavenKingdom_II_HD_CHINESE'
SRC = os.path.join(ROOT, 'SavenKingdom_II_HD_CHINESE')
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from fontlib import FontTable                                     # noqa: E402

ft = FontTable()
H = open(os.path.join(SRC, 'fontdata.h'), encoding='ascii').read()
HS = open(os.path.join(SRC, 'fontdata_std.h'), encoding='ascii').read()
HE = open(os.path.join(SRC, 'fontdata_extra.h'), encoding='ascii').read()


def arr(txt, n):
    m = re.search(r'%s\[[^]]*\]\s*=\s*\{' % n, txt)
    st = m.end()
    en = txt.index('}', st)
    return [int(x) for x in re.findall(r'\d+', txt[st:en])]


custidx = arr(H, 'custidx')
big5idx = arr(H, 'big5idx')
origs = arr(HS, 'g_stdOrig')
slots = arr(HS, 'g_stdCode')
excodes = arr(HE, 'g_extraCode')
EXTRA_N = int(re.search(r'#define EXTRA_N\s+(\d+)', HE).group(1))
N_CHARS = ft.n_chars
STD_N = len(origs)

B5_LEAD_MIN, B5_LEAD_MAX, B5_TRAIL_COUNT = 0xA1, 0xF9, 157
CUST_LEAD_MIN, CUST_LEAD_COUNT = 0x90, 17

# STD 表：槽位码 -> 字形下标
STD_SLOT2GLYPH = {}
for i in range(STD_N):
    STD_SLOT2GLYPH[slots[i]] = ft.glyph_of_std((origs[i] >> 8, origs[i] & 0xFF))

# 槽位 lead 集合（用于判断字节是否落在槽位区）
STD_LEADS = sorted(set(s >> 8 for s in slots))
STD_TRAILS = sorted(set(s & 0xFF for s in slots))


def TrailOk(t):
    return (0x40 <= t <= 0x7E) or (0xA1 <= t <= 0xFE)


def GlyphIndex(lead, trail):
    if trail >= 0x40 and trail <= 0x7E:
        ti = trail - 0x40
    elif trail >= 0xA1 and trail <= 0xFE:
        ti = 63 + (trail - 0xA1)
    else:
        return -1
    if CUST_LEAD_MIN <= lead < CUST_LEAD_MIN + CUST_LEAD_COUNT:
        v = custidx[(lead - CUST_LEAD_MIN) * B5_TRAIL_COUNT + ti]
        return v - 1 if v else -1
    gi = -1
    if B5_LEAD_MIN <= lead <= B5_LEAD_MAX:
        v = big5idx[(lead - B5_LEAD_MIN) * B5_TRAIL_COUNT + ti]
        if v:
            gi = v - 1
    if gi >= 0:
        return gi
    code = (lead << 8) | trail
    if code in STD_SLOT2GLYPH:
        return STD_SLOT2GLYPH[code] - 1
    for i in range(EXTRA_N):
        if excodes[i] == code:
            return N_CHARS + i
    return -1


def simulate(s, label):
    print('=== %s: %s ===' % (label, s.hex(' ')))
    p = 0
    n = len(s)
    parts = []
    lost = 0
    while p < n:
        b = s[p]
        t = s[p + 1] if p + 1 < n else 0
        pair = (b < 0x80 or (TrailOk(t) and (CUST_LEAD_MIN <= b < CUST_LEAD_MIN
                                               + CUST_LEAD_COUNT or B5_LEAD_MIN <= b <= B5_LEAD_MAX)))
        if b >= 0x80 and pair:
            gi = GlyphIndex(b, t)
            tag = 'g%d' % gi if gi >= 0 else '★缺字形'
            if gi < 0:
                lost += 1
            parts.append('%02X%02X->%s' % (b, t, tag))
            p += 2
        else:
            if b < 0x80:
                parts.append('%02X=ASCII(%r)' % (b, chr(b)))
            else:
                parts.append('%02X=★孤立高位(丢字)' % b)
                lost += 1
            p += 1
    print('   ' + ' | '.join(parts))
    print('   丢字数 = %d' % lost)
    print()
    return lost


print('STD 槽位 lead 集合: %s' % (' '.join('%02X' % x for x in STD_LEADS)))
print('STD 槽位 trail 范围: %02X - %02X' % (min(STD_TRAILS), max(STD_TRAILS)))
print()

simulate(bytes.fromhex('BFD5A144B0D2'), '诺尔曼 row0 (日志: D5 A1 44 B0 D2)')
simulate(bytes.fromhex('E9A5BB'), '日本   row7 (日志: E9 A5 BB)')
simulate(bytes.fromhex('BAFBA8CA'), '维京   row1')
simulate(bytes.fromhex('B3CDA144A145'), '凯尔特 row2')
simulate(bytes.fromhex('C3B9B0A8'), '罗马   row3')
simulate(bytes.fromhex('A7C6C3BE'), '希腊   row4')
simulate(bytes.fromhex('A159A4D3B0F2'), '迦太基 row5')
simulate(bytes.fromhex('A4A4B0EA'), '中国   row6')
simulate(bytes.fromhex('BB58A56A'), '蒙古   row8')
simulate(bytes.fromhex('AE4AA4CE'), '埃及   row9')
simulate(bytes.fromhex('AA69B4B5'), '波斯   row10')
simulate(bytes.fromhex('A64CABD7'), '印度   row11')
