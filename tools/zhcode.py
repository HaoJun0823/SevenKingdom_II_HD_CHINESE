# -*- coding: utf-8 -*-
"""HD 引擎文字资源的中文编解码 + 「幻影自定义对」检测/修复。

背景（本轮逆向实证）
--------------------
旧汉化包的编码流程是：
   1. 中文按 Big5 落盘；
   2. `risky_map.remap_bytes()` 再走一遍字节流，把「尾字节 ∈ {~ { | } [ ]}」的
      汉字换成自定义安全对（领 0x90-0xA0），避免引擎把它们当模板控制符。

问题：第 2 步在某些位置**错位了一个字节**，把
    `[上一个汉字的尾字节][模板控制符]`
当成一个合法 Big5 对，于是：
    `商隊|` = B0D3 B6A4 7C
        ↓ 从 B6A4 的尾字节 A4 起读成 (A4,7C) = 「弋」（危险尾 → 需重映射）
    `B0D3 B6` + `<弋的自定义对 9069>`
结果：`|` 消失、且多出一个错误的字（弋）。
引擎的模板解析因此找不到配对的 `}`，把**下一行也吞进字符串**，
于是界面上出现 `…%1d[COMD]指揮官`、`…[RRS1]Reserved` 这类乱码。

本模块提供：
  * `encode_zh(text)`  把中文（含 `{ } |` 等控制符）编码为引擎需要的字节
                       —— 危险尾字自动走自定义对，控制符保持原样；
  * `decode_dbc(buf)`  反过来解码（自定义对还原成真实汉字），用于排查；
  * `scan_phantom(d)`  检出「幻影对」：`X [cust]` 且 `glyph(cust) == glyph(Y,ctrl)`、
                       ctrl ∈ 控制符、`X Y` 是合法 Big5 对 —— 长度不变可原地还原。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_text as rt

GAME = r'I:\LocalGames\Seven Kingdoms II HD'
UP = os.path.join(GAME, 'update', 'Resource')
ORIG = os.path.join(GAME, 'Resource')

# 引擎模板控制符（也是「尾字节危险」集合）
CTRL = {0x7E, 0x7B, 0x7C, 0x7D, 0x5B, 0x5D}
CUST_LEAD_MIN, CUST_LEAD_MAX = 0x90, 0xA0
TRAILS_STD = list(range(0x40, 0x7F)) + list(range(0xA1, 0xFF))

_FT = None


def ft():
    global _FT
    if _FT is None:
        _FT = rt.Font()
        globals()['_C2S'] = _build_cust2std(_FT)
        globals()['_S2C'] = {v: k for k, v in _C2S.items()}
    return _FT


def _build_cust2std(f):
    """自定义对 -> 标准 Big5 对（同字形）。只保留标准表里查得到的。"""
    g2c = {}
    for lead in range(0xA1, 0xFA):
        for tr in TRAILS_STD:
            g = f.glyph(lead, tr)
            if g is not None:
                g2c.setdefault(g, (lead, tr))
    out = {}
    for lead in range(CUST_LEAD_MIN, CUST_LEAD_MAX + 1):
        for tr in list(range(0x40, 0x7F)) + list(range(0xA1, 0xFF)):
            g = f.glyph(lead, tr)
            if g is None:
                continue
            std = g2c.get(g)
            if std:
                out[(lead, tr)] = std
    return out


def cust2std(c):
    ft()
    return globals()['_C2S'].get(c)


def std2cust(p):
    ft()
    return globals()['_S2C'].get(p)


def is_valid_pair(a, b):
    return 0xA1 <= a <= 0xF9 and ((0x40 <= b <= 0x7E) or (0xA1 <= b <= 0xFE))


def is_cust_pair(a, b):
    return CUST_LEAD_MIN <= a <= CUST_LEAD_MAX and ((0x40 <= b <= 0x7E) or (0xA1 <= b <= 0xFE))


def is_ctrl(b):
    return b in CTRL


# ── 编码 / 解码 ────────────────────────────────────────────
def encode_zh(text):
    """中文文本 -> 引擎字节。危险尾字走自定义对；ASCII 与 { } | 等原样保留。"""
    ft()
    out = bytearray()
    for ch in text:
        o = ord(ch)
        if o < 0x80:
            out.append(o)
            continue
        try:
            b = ch.encode('cp950')
        except Exception:
            raise ValueError('无法编码为 cp950: %r' % ch)
        if len(b) != 2:
            raise ValueError('%r 不是双字节' % ch)
        pair = (b[0], b[1])
        if b[1] in CTRL and 0xA1 <= b[0] <= 0xF9:
            c = std2cust(pair)
            if not c:
                raise ValueError('%r 尾字节危险但无自定义对' % ch)
            out += bytes(c)
        else:
            out += b
    return bytes(out)


def decode_dbc(buf):
    """引擎字节 -> 可读文本。自定义对还原为真实汉字；控制符原样显示。"""
    ft()
    out = []
    i = 0
    n = len(buf)
    while i < n:
        b = buf[i]
        if b < 0x80:
            out.append(chr(b))
            i += 1
            continue
        if i + 1 < n and is_cust_pair(b, buf[i + 1]):
            std = cust2std((b, buf[i + 1]))
            if std:
                try:
                    out.append(bytes(std).decode('cp950'))
                except Exception:
                    out.append('<CUST%02X%02X>' % (b, buf[i + 1]))
            else:
                out.append('<CUST%02X%02X>' % (b, buf[i + 1]))
            i += 2
            continue
        if i + 1 < n and is_valid_pair(b, buf[i + 1]):
            try:
                out.append(bytes(buf[i:i + 2]).decode('cp950'))
            except Exception:
                out.append('<%02X%02X>' % (b, buf[i + 1]))
            i += 2
            continue
        out.append('<%02X>' % b)
        i += 1
    return ''.join(out)


# ── 幻影对检测 ─────────────────────────────────────────────
def scan_phantom(d):
    """按 DBCS 正确游走，检出「幻影对」。

    判据（缺一不可）：
      1. 当前位置 b 是**孤立高位字节**（既不能与下一字节组成标准对，也不是自定义对的领）；
      2. b 之后的 2 字节是自定义对，且能解出标准对 (Y, ctrl)；
      3. ctrl 是模板控制符（~ { | } [ ]）；
      4. b + Y 是合法 Big5 对（即 (b,Y) 就是那个被劈开的汉字）。

    此时长度不变地把 `b [cust]` 还原成 `b Y ctrl`。
    """
    ft()
    hits = []
    i = 0
    n = len(d)
    while i < n:
        b = d[i]
        if b < 0x80:
            i += 1
            continue
        # 正常双字节（标准对或自定义对）—— 直接跳过
        if i + 1 < n and (is_valid_pair(b, d[i + 1]) or is_cust_pair(b, d[i + 1])):
            i += 2
            continue
        # 孤立高位字节：看它后面是不是幻影自定义对
        if i + 2 < n and is_cust_pair(d[i + 1], d[i + 2]):
            std = cust2std((d[i + 1], d[i + 2]))
            if std:
                Y, ctrl = std[0], std[1]
                if ctrl in CTRL and is_valid_pair(b, Y):
                    hits.append((i, b, d[i + 1], d[i + 2], Y, ctrl))
                    i += 3
                    continue
        i += 1
    return hits


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'scan'
    only = None
    if '--only' in sys.argv:
        only = sys.argv[sys.argv.index('--only') + 1].lower()
    if cmd == 'scan':
        total = 0
        for nm in sorted(os.listdir(UP)):
            if not nm.lower().endswith('.res'):
                continue
            if only and only not in nm.lower():
                continue
            d = open(os.path.join(UP, nm), 'rb').read()
            hits = scan_phantom(d)
            if hits:
                print('### %s  幻影对 %d 处' % (nm, len(hits)))
                for off, X, L, T, Y, ctrl in hits[:20]:
                    try:
                        ch = bytes((X, Y)).decode('cp950')
                    except Exception:
                        ch = '?'
                    ctx = d[max(0, off - 14):off + 16]
                    print('    @0x%-6X  %02X + %02X%02X  应还原为 %02X %02X %02X = %s%c'
                          % (off, X, L, T, X, Y, ctrl, ch, chr(ctrl)))
                    print('             ctx %r -> %r'
                          % (ctx, (ctx[:off - max(0, off - 14)] + bytes((X, Y, ctrl))
                                   + ctx[off - max(0, off - 14) + 3:]).decode('cp950', 'replace')))
                total += len(hits)
        print()
        print('==== 幻影对合计 %d 处 ====' % total)


if __name__ == '__main__':
    main()
