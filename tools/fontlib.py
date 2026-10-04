# -*- coding: utf-8 -*-
"""公共库：从 fontdata.h 反推「字符 → 自定义对」映射，并提供重映射与字形覆盖检查。

为什么要反推：旧工程用 risky_map.init(charset) 按字符集排序确定性分配自定义对，
而字符集已无法完整重建；但 fontdata.h 的 custidx + big5idx 保留了结果，可反推。

约定：字符集里存的是**简体显示形**，所以查表要用 zhconv 转成简体后查。
"""
import os, re, sys, struct

FONTDATA = r'G:\Projects\SavenKingdom_II_HD_CHINESE\SavenKingdom_II_HD_CHINESE\fontdata.h'
OURS = r'G:\Projects\SavenKingdom_II_HD_CHINESE\update_res_staged'
GAME = r'I:\LocalGames\Seven Kingdoms II HD'

B5_LEAD_MIN, B5_LEAD_MAX, B5_TC = 0xA1, 0xF9, 157
CUST_LEAD_MIN, CUST_LEAD_COUNT = 0x90, 17
BAD_TRAILS = {0x5B, 0x5D, 0x7B, 0x7C, 0x7D, 0x7E, 0x7F}


def _arr(txt, name):
    m = re.search(r'%s\[[^]]*\]\s*=\s*\{' % name, txt)
    st = m.end()
    en = txt.index('}', st)
    return [int(x) for x in re.findall(r'\d+', txt[st:en])]


class FontTable(object):
    def __init__(self, path=FONTDATA):
        t = open(path, encoding='ascii').read()
        self.n_chars = int(re.search(r'#define N_CHARS\s+(\d+)', t).group(1))
        self.big5 = _arr(t, 'big5idx')
        self.cust = _arr(t, 'custidx')
        self._build_maps()

    def std_code(self, ch):
        """字符 → 标准 Big5 码 (b1,b2)；失败返回 None"""
        try:
            b = ch.encode('cp950')
        except Exception:
            return None
        return (b[0], b[1]) if len(b) == 2 else None

    def glyph_of_std(self, pair):
        b1, b2 = pair
        if not (B5_LEAD_MIN <= b1 <= B5_LEAD_MAX):
            return 0
        ti = (b2 - 0x40) if b2 <= 0x7E else (63 + (b2 - 0xA1))
        if not (0 <= ti < B5_TC):
            return 0
        return self.big5[(b1 - B5_LEAD_MIN) * B5_TC + ti]

    def _build_maps(self):
        # glyph -> 代表字符（取第一个遇到的 cp950 码，按 lead/ti 顺序）
        g2c = {}
        for lead in range(B5_LEAD_MIN, B5_LEAD_MAX + 1):
            for ti in range(B5_TC):
                v = self.big5[(lead - B5_LEAD_MIN) * B5_TC + ti]
                if v:
                    t = 0x40 + ti if ti < 63 else 0xA1 + (ti - 63)
                    try:
                        ch = bytes([lead, t]).decode('cp950')
                    except Exception:
                        continue
                    g2c.setdefault(v - 1, ch)
        self.glyph2char = g2c
        # 字符 -> 自定义对
        self.char2pair = {}
        self.pair2glyph = {}
        for li in range(CUST_LEAD_COUNT):
            for ti in range(B5_TC):
                v = self.cust[li * B5_TC + ti]
                if not v:
                    continue
                t = 0x40 + ti if ti < 63 else 0xA1 + (ti - 63)
                if t > 0x7E:
                    continue
                path = (CUST_LEAD_MIN + li, t)
                self.pair2glyph[path] = v - 1
                ch = g2c.get(v - 1)
                if ch:
                    self.char2pair.setdefault(ch, path)

    # ---- 简体形式查表 ----
    def _simp(self, ch):
        try:
            import zhconv
            return zhconv.convert(ch, 'zh-hans')
        except Exception:
            return ch

    def pair_for_char(self, ch):
        p = self.char2pair.get(ch)
        if p:
            return p
        s = self._simp(ch)
        return self.char2pair.get(s)

    def has_glyph(self, pair):
        return self.glyph_of_std(pair) != 0

    def is_risky(self, ch):
        c = self.std_code(ch)
        return bool(c) and c[1] in BAD_TRAILS


def iter_pairs(data):
    """遍历字节流里的 2 字节字符对，产出 (位置, 类型, 字符, 原始字节)
       类型: 'std' / 'cust'"""
    i = 0
    n = len(data)
    while i < n - 1:
        b = data[i]
        if CUST_LEAD_MIN <= b <= CUST_LEAD_MIN + CUST_LEAD_COUNT - 1:
            t = data[i + 1]
            if 0x40 <= t <= 0x7E:
                yield (i, 'cust', (b, t), data[i:i + 2])
                i += 2
                continue
        if B5_LEAD_MIN <= b <= B5_LEAD_MAX:
            t = data[i + 1]
            if 0x40 <= t <= 0x7E or 0xA1 <= t <= 0xFE:
                yield (i, 'std', (b, t), data[i:i + 2])
                i += 2
                continue
        i += 1


def remap_inplace(data, ft):
    """把危险的标准对替换为对应的自定义对（长度不变：都是 2 字节）"""
    out = bytearray(data)
    sub = 0
    miss = []
    for pos, kind, pair, raw in iter_pairs(bytes(out)):
        if kind != 'std':
            continue
        b2 = pair[1]
        if b2 not in BAD_TRAILS:
            continue
        try:
            ch = bytes(pair).decode('cp950')
        except Exception:
            continue
        p = ft.pair_for_char(ch)
        if p:
            out[pos] = p[0]
            out[pos + 1] = p[1]
            sub += 1
        else:
            miss.append(ch)
    return bytes(out), sub, miss


def decode_display(data, ft):
    """把字节流解码为「显示字符」列表（自定义对 → 字符；标准对 → cp950）"""
    # pair -> 字符 反查用 glyph 反推
    glyph2char = ft.glyph2char
    out = []
    i = 0
    n = len(data)
    while i < n:
        b = data[i]
        if CUST_LEAD_MIN <= b <= CUST_LEAD_MIN + CUST_LEAD_COUNT - 1 and i + 1 < n:
            t = data[i + 1]
            if 0x40 <= t <= 0x7E:
                g = ft.pair2glyph.get((b, t))
                ch = glyph2char.get(g) if g is not None else None
                out.append(ch if ch else '')
                i += 2
                continue
        if B5_LEAD_MIN <= b <= B5_LEAD_MAX and i + 1 < n:
            t = data[i + 1]
            if 0x40 <= t <= 0x7E or 0xA1 <= t <= 0xFE:
                try:
                    out.append(bytes([b, t]).decode('cp950'))
                except Exception:
                    out.append('')
                i += 2
                continue
        out.append(chr(b) if b < 0x80 else '')
        i += 1
    return ''.join(out)


if __name__ == '__main__':
    ft = FontTable()
    print('字符集大小 N_CHARS =', ft.n_chars)
    print('可反推的自定义映射 =', len(ft.char2pair), '/ 共', len(ft.pair2glyph), '对')
    for ch in '魔年外因包久徒尚破會現認開稅設財课碎閥':
        p = ft.pair_for_char(ch)
        c = ft.std_code(ch)
        print('  %r std=%s risky=%s pair=%s' % (
            ch, ('%02X%02X' % c) if c else None, ft.is_risky(ch),
            ('%02X%02X' % p) if p else None))
