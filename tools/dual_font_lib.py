# -*- coding: utf-8 -*-
"""共用库：字形烘焙 + fontdata 池读写。

渲染参数严格对齐 gen_extra.py / gen_fontdata.py：
  simsun.ttc、单元格 (px+1+pad) x (px+1+pad)（pad=1）、阈值 128、
  额外叠加 (1,1) 阴影、1bpp 打包、行内 MSB 优先。
"""
import os
import re

FONT_PATH = r'C:\Windows\Fonts\simsun.ttc'
B5_LEAD_MIN, B5_LEAD_MAX, B5_TC = 0xA1, 0xF9, 157
CUST_LEAD_MIN, CUST_LEAD_COUNT = 0x90, 17
BAD_TRAILS = (0x5B, 0x5C, 0x5D, 0x7B, 0x7C, 0x7D, 0x7E, 0x7F)

_rc = {}


def render_mask(ch, px):
    """渲染单字为 1bpp 掩码（含 (1,1) 阴影）。返回 bytes。"""
    key = (ch, px)
    if key in _rc:
        return _rc[key]
    from PIL import Image, ImageFont, ImageDraw
    pad = 1
    W = px + 1 + pad
    H = px + 1 + pad
    font = ImageFont.truetype(FONT_PATH, px)
    img = Image.new('L', (W, H), 0)
    ImageDraw.Draw(img).text((0, 0), ch, fill=255, font=font)
    mask = Image.new('L', (W, H), 0)
    mp, ip = mask.load(), img.load()
    for y in range(H):
        for x in range(W):
            if ip[x, y] >= 128:
                mp[x, y] = 255
    for y in range(H - 1):
        for x in range(W - 1):
            if ip[x, y] >= 128:
                mp[x + 1, y + 1] = 255
    rowb = (W + 7) // 8
    rows = bytearray(rowb * H)
    for y in range(H):
        for x in range(W):
            if mp[x, y]:
                rows[y * rowb + (x >> 3)] |= 0x80 >> (x & 7)
    _rc[key] = bytes(rows)
    return _rc[key]


def trail_of_ti(ti):
    return (0x40 + ti) if ti <= 62 else (0xA1 + (ti - 63))


def ti_of_trail(b2):
    return (b2 - 0x40) if b2 <= 0x7E else (63 + (b2 - 0xA1))


def read_text(path):
    return open(path, encoding='utf-8', errors='replace').read()


def arr(txt, name):
    """取 static const T name[...] = { ... }; 的数字列表（fontdata 全是十进制字面量）。"""
    m = re.search(r'\b' + re.escape(name) + r'\s*\[[^\]]*\]\s*=\s*\{', txt)
    if not m:
        return None
    st = m.end()
    en = txt.index('}', st)
    return [int(x) for x in re.findall(r'\d+', txt[st:en])]


def load_fontdata(path):
    """读一个 fontdata 头文件，返回含索引表与三个池的 dict。"""
    t = read_text(path)
    d = {}
    d['n_chars'] = int(re.search(r'#define\s+N_CHARS\s+(\d+)', t).group(1))
    d['big5idx'] = arr(t, 'big5idx')
    d['custidx'] = arr(t, 'custidx')
    for px in (13, 16, 24):
        d['goff%d' % px] = arr(t, 'goff%d' % px)
        d['gpool%d' % px] = arr(t, 'gpool%d' % px)
    return d


def load_pool_only(path, name):
    return arr(read_text(path), name)


def bytes_of_glyph(pool, off):
    """从池里取一个字形（含 [W,H] 头）的原始字节。"""
    W, H = pool[off], pool[off + 1]
    rb = (W + 7) >> 3
    return W, H, bytes(pool[off: off + 2 + rb * H])


def pool_header(px):
    W = H = px + 2
    return bytes([W, H])
