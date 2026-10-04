# -*- coding: utf-8 -*-
"""生成 fontdata_std.h：STD.SET 专用码位表。

== 为什么需要 ==

引擎读取 STD.SET 的文本字段时，会把 >=0x80 的字节逐个过一张映射表
（7K2.exe 偏移 0x27F028）。表在高位区是**部分函数**：

    95 个高位输入 -> 95 个不同输出（其中 33 个输入被映射成 '?'）
    另有 2 个输入落到低位区（D5->0x27, F2->0x3D，会变成引号/等号）

所以并不是所有字节都能「写进去、再被引擎还原」。写盘字节 S 必须满足
`table[S] == 目标字节`，即目标字节必须在**可生成集合**内。

实测**不可生成的高位字节**（35 个）：

    0x80-0xA0 整段（33 个，含 0x90-0xA0 自定义对区间）
    0xAD  0xAF  0xB8

对 Big5 而言，只有 **AD / AF / B8** 三个字节落在 Big5 有效范围
（lead 0xA1-0xF9，trail 0x40-0x7E / 0xA1-0xFE）内且不可生成，
实测影响 **213 个汉字**（爾/特/納/迪/蒂/烏/索/倫/茲/萬…）。

== 解法 ==

字库 big5idx 共占用 4467 个 Big5 码位，剩余「可达且空闲」的码位有
**9082 个**，足够安置这 213 个字。于是：

  - 不动 big5idx（既有资源索引必须保持）
  - 新增 stdCode[] / stdGlyph[] 两张表，把这 213 个字形挂到可达码位上
  - fix_stdset.py 编码时优先用 stdCode，再做引擎预映射
  - cjk.cpp 的 GlyphIndex 查完 big5idx 后再查 stdCode

这样每个字形只多一个入口码位，字形池（gpool*）完全复用。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import zhconv                                          # noqa: E402
from fontlib import FontTable, decode_display           # noqa: E402

GAME = r'I:\LocalGames\Seven Kingdoms II HD'
ORIG = os.path.join(GAME, 'Resource', 'STD.SET')
SRC = r'I:\LocalGames\Seven Kingdoms II HD\七个王国2\七国2汉化包\zh_CN\Resource\STD.SET'
OUT = os.path.join(os.path.dirname(HERE), 'SavenKingdom_II_HD_CHINESE', 'fontdata_std.h')
TABLE_OFF = 0x27F028
TC = 157
DELIM = {0x00, 0x0D, 0x0A}

# 异体字归一（zhconv 偶尔给出 cp950 没有的异体）
VARIANT = {'爲': '為', '衆': '眾', '裏': '裡'}

_exe = open(os.path.join(GAME, '7K2.exe'), 'rb').read()
# 表按字节值索引，但**只对 >=0x80 生效**：低位 ASCII 在原版里完全正常，
# 若低位也查表，英文必被破坏。表在 0x00-0x7F 的内容是相邻的代码字节，不是映射。
T = list(_exe[TABLE_OFF:TABLE_OFF + 0x100])


def engine_map(b):
    """引擎对单个字节的映射；<0x80 原样返回"""
    return T[b] if b >= 0x80 else b


NOIMG = set(i for i in range(0x80, 0x100)
            if all(T[j] != i for j in range(0x80, 0x100)))


def to_trad(s):
    s = ''.join(VARIANT.get(c, c) for c in s)
    return zhconv.convert(s, 'zh-hant')


def premap_std(code):
    """备用码位 -> 写入 STD.SET 的字节（仅高位 lead 需要预映射）"""
    b1, b2 = code
    out = bytearray()
    for c in (b1, b2):
        if c < 0x80:
            out.append(c)
            continue
        cands = [i for i in range(0x80, 0x100) if T[i] == c]
        if not cands:
            return None
        out.append(cands[0])
    return bytes(out)


def enc_std(text):
    """显示文本 -> 标准 Big5 字节（逐字，失败返回 None）"""
    out = bytearray()
    for ch in to_trad(text):
        for c in (ch, VARIANT.get(ch, ch)):
            try:
                b = c.encode('cp950')
            except Exception:
                continue
            if len(b) == 2:
                out += b
                break
        else:
            return None
    return bytes(out)


def main():
    ft = FontTable()
    orig = open(ORIG, 'rb').read()
    src = open(SRC, 'rb').read()
    n = len(orig)

    # ---- 1) 收集 STD.SET 里用到的所有汉字及其出现次数 ----
    want = {}
    p = 0
    while p < n:
        if src[p] in DELIM:
            p += 1
            continue
        q = p
        while q < n and src[q] not in DELIM:
            q += 1
        tok = src[p:q]
        # 只处理「旧包真正翻译过」的 token（与原版不同），否则会把
        # STD.SET 里游戏自带的原始数据表也当成译文，白补上千个字形。
        if any(c >= 0x80 for c in tok) and tok != orig[p:q]:
            text = decode_display(tok, ft)
            for ch in to_trad(text):
                o = ord(ch)
                if not (0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF):
                    continue
                b = enc_std(ch)
                if b is None:
                    continue
                if b[0] in NOIMG or b[1] in NOIMG:
                    want[b] = want.get(b, 0) + 1
        p = q

    print('受不可达字节影响的汉字: %d 种' % len(want))

    # ---- 2) 收集「可达且空闲」的码位 ----
    # 备用码位只用「低位 trail (0x40-0x7E)」：
    #   - trail < 0x80 -> 引擎不查表，只需 lead 可达 -> 约束最松
    #   - 但 trail 不能是引擎控制符 [ ] { | } ~ (0x5B 0x5D 0x7B 0x7C 0x7D 0x7E)
    BAD_TRAILS = {0x5B, 0x5D, 0x7B, 0x7C, 0x7D, 0x7E, 0x7F}
    free = []
    for lead in range(0xA1, 0xFA):
        if lead in NOIMG:
            continue                          # lead 必须可达
        for ti in range(63):                   # 0x40-0x7E
            t = 0x40 + ti
            if t in BAD_TRAILS:
                continue
            if ft.big5[(lead - 0xA1) * TC + ti]:
                continue                      # 已被 big5idx 占用
            free.append((lead, t))
    print('可达且空闲码位: %d' % len(free))
    if len(free) < len(want):
        print('★ 空闲码位不足，无法安置全部汉字')
        return 1

    # ---- 3) 分配：按 (lead, ti) 升序取空闲位（确定性，可复现）----
    std = {}
    used = set()
    missing = []
    for code in sorted(want, key=lambda c: -want[c]):
        gi = ft.glyph_of_std(code)
        if gi == 0:
            missing.append(code)
            continue
        for slot in free:
            if slot in used:
                continue
            # 该空闲位在 big5idx 里必须是 0（否则会与既有资源冲突）
            lead, t = slot
            ti = (t - 0x40) if t <= 0x7E else (63 + (t - 0xA1))
            if ft.big5[(lead - 0xA1) * TC + ti] != 0:
                continue
            used.add(slot)
            std[code] = (slot, gi)
            break

    print('已分配 STD 专用码位: %d' % len(std))
    print('主字库无字形（需补字形）: %d' % len(missing))
    if missing:
        miss_txt = []
        for code in missing:
            try:
                ch = bytes(code).decode('cp950')
            except Exception:
                ch = '?'
            miss_txt.append('%s=%s' % (code.hex(' ').upper(), ch))
        print('  ' + ' '.join(miss_txt))
        import json
        json.dump(['%02X%02X' % (c[0], c[1]) for c in missing],
                  open(os.path.join(HERE, 'std_missing.json'), 'w'))

    # ---- 4) 写出 fontdata_std.h ----
    codes = sorted(std.keys())
    L = []
    A = L.append
    A('/* auto-generated by gen_stdmap.py -- do not edit */')
    A('/* STD.SET specific code table.')
    A(' * The engine maps every byte >= 0x80 read from STD.SET through a')
    A(' * 256-entry table in 7K2.exe @ 0x27F028. The high half is a partial')
    A(' * function: only 95 outputs are reachable, and Big5 bytes AD / AF / B8')
    A(' * are NOT among them. Characters whose Big5 code uses those bytes')
    A(' * cannot be written directly -- the engine could not restore them.')
    A(' * Here they are re-homed onto reachable AND unused Big5 codes, so the')
    A(' * existing glyph pools (gpool13/16/24) are reused as-is.')
    A(' */')
    A('#ifndef FONTDATA_STD_H')
    A('#define FONTDATA_STD_H')
    A('')
    A('#define STD_N %d' % len(std))
    A('')
    A('/* original Big5 code (tools only, not used at runtime) */')
    A('static const unsigned short g_stdOrig[STD_N] = {%s};'
      % ','.join('%d' % (c[0] << 8 | c[1]) for c in codes))
    A('')
    A('/* code actually written to STD.SET (engine maps it back to g_stdOrig) */')
    A('static const unsigned short g_stdCode[STD_N] = {%s};'
      % ','.join('%d' % (std[c][0][0] << 8 | std[c][0][1]) for c in codes))
    A('')
    A('/* glyph index into gpool13/16/24 */')
    A('static const unsigned short g_stdGlyph[STD_N] = {%s};'
      % ','.join('%d' % (std[c][1] - 1) for c in codes))
    A('')
    A('#endif /* FONTDATA_STD_H */')

    open(OUT, 'w', encoding='ascii').write('\n'.join(L) + '\n')
    print('written %s' % OUT)

    # ---- 5) 回环校验：预映射后能否被引擎还原 ----
    bad = []
    for c in codes:
        slot = std[c][0]
        pm = premap_std(slot)
        if pm is None:
            bad.append((c, slot, None))
            continue
        back = bytes(engine_map(x) for x in pm)
        # 引擎查表后必须恰好还原为 slot 本身（渲染器按 slot 查表）
        if back != bytes((slot[0], slot[1])):
            bad.append((c, slot, back))
    print('round-trip: %d / %d ok' % (len(codes) - len(bad), len(codes)))
    for c, slot, back in bad[:8]:
        print('  ! orig %02X%02X -> slot %02X%02X -> got %s'
              % (c[0], c[1], slot[0], slot[1],
                 ('%02X%02X' % (back[0], back[1])) if back else 'None'))
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
