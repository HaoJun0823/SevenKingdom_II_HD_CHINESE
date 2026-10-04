# -*- coding: utf-8 -*-
"""生成补充字形表 fontdata_extra.h

背景：主字库 fontdata.h 的字符集来自旧工程的翻译语料，其中不含我们新增译文用到的
少数汉字（实测 14 个，如 课/碎/阀/陲/涌/恭/滓…）。为了**完全不动**主表的索引
（改动会连带既有资源全部错位），这里为缺字生成一张独立的追加表：

    cjk.cpp 的 GlyphIndex() 先查主表 big5idx；为 0 时再查本表。
    本表条目索引 = N_CHARS + (v-1)，与主表共用同一「字形序号空间」。

字形渲染方式与 gen_fontdata.py 完全一致（simsun.ttc，13/16/24px，单元格 px+2，
内含 (1,1) 阴影，1bpp 打包），保证与主表字形风格一致。
用法： python gen_extra.py
"""
import os, re, sys, zlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fontlib import FontTable, iter_pairs, CUST_LEAD_MIN, CUST_LEAD_COUNT, OURS, decode_display

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = r'G:\Projects\SavenKingdom_II_HD_CHINESE\SavenKingdom_II_HD_CHINESE\fontdata_extra.h'
FONT_PATH = r'C:\Windows\Fonts\simsun.ttc'
SIZES = [13, 16, 24]

# 额外需要的字（手工补：批次二的教程战役文本会用到，先占位，脚本会自行核对）
# 螢：exe 内置标签「全螢幕模式」用字（主表与 gap_zh.json 语料都没有这个字形）
EXTRA_SEED = '螢'


def render_mask(ch, px):
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
    return W, H, bytes(rows)



def is_glyph_char(ch):
    """只接受「能作为汉字显示」的字符。

    STD.SET 里混有进制符号、箭头、框线字符（╔ ╣ ╘ 等），
    它们不是汉字，渲染出来是乱码，直接跳过。
    """
    if not ch or ch < ' ':
        return False
    o = ord(ch)
    # CJK 统一表意文字 + 扩展A + 兼容表意文字
    if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or 0xF900 <= o <= 0xFAFF:
        return True
    # 假名 / 谚文（游戏里可能出现）
    if 0x3040 <= o <= 0x30FF or 0xAC00 <= o <= 0xD7AF:
        return True
    # 常用中文标点
    if ch in '，。、；：？！“”‘’（）《》—…':
        return True
    return False


def collect_missing_std(ft):
    """收集 STD.SET 的**已翻译字段**里用到、但主字库没有字形的汉字。

    注意只扫「与原版有差异」的 token：STD.SET 里还有大量游戏自带的原始
    数据（英文名、符号表、注音等），它们不需要汉化，若一并收录会
    引入近 2000 个用不到的字形，浪费空间。
    """
    import zhconv
    GAME = r'I:////LocalGames////Seven Kingdoms II HD'
    SRC = GAME + r'\\七个王国2\\七国2汉化包\\zh_CN\\Resource\\STD.SET'
    ORIG = GAME + r'\\Resource\\STD.SET'
    DELIM = {0x00, 0x0D, 0x0A}
    try:
        data = open(SRC, 'rb').read()
        orig = open(ORIG, 'rb').read()
    except Exception as e:
        print('  ! cannot read STD.SET: %s' % e)
        return {}
    n = min(len(data), len(orig))
    simp = lambda c: zhconv.convert(c, 'zh-hans')
    need = {}
    p = 0
    while p < n:
        if data[p] in DELIM:
            p += 1
            continue
        q = p
        while q < n and data[q] not in DELIM:
            q += 1
        tok = data[p:q]
        if any(c >= 0x80 for c in tok) and tok != orig[p:q]:
            for ch in decode_display(tok, ft):
                if not is_glyph_char(ch):
                    continue
                try:
                    b = ch.encode('cp950')
                except Exception:
                    continue
                if len(b) == 2 and ft.glyph_of_std((b[0], b[1])) == 0:
                    need[(b[0], b[1])] = simp(ch)
        p = q
    return need


def collect_missing(ft):
    """返回 {码位对(b1,b2): 显示字符(简体)}

    注意：码位取自我们编码后的字节（原文，可能是繁体字如 寬），
    而字形要渲染**简体显示形**（如 宽）——二者必须分开，否则遇到
    cp950 不含的简体字（宽/课）会编不出来。
    """
    import json
    import build_gap
    try:
        import zhconv
        simp = lambda c: zhconv.convert(c, 'zh-hans')
    except Exception:
        simp = lambda c: c

    zh = json.load(open(os.path.join(HERE, 'gap_zh.json'), encoding='utf-8'))
    texts = []

    def walk(o):
        if isinstance(o, str):
            texts.append(o)
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(zh)
    if EXTRA_SEED:
        texts.append(EXTRA_SEED)

    need = {}
    for t in texts:
        data = build_gap.enc(t)
        for pos, kind, pair, raw in iter_pairs(data):
            if kind != 'std':
                continue
            if ft.glyph_of_std(pair) != 0:
                continue
            try:
                ch = bytes(pair).decode('cp950')
            except Exception:
                continue
            need[pair] = simp(ch)
    return need


def main():
    ft = FontTable()
    need = collect_missing(ft)
    need.update(collect_missing_std(ft))
    codes = sorted(need)
    print('main N_CHARS =', ft.n_chars)
    print('missing glyph chars: %d' % len(codes))
    for c in codes:
        print('   %02X%02X -> %r' % (c[0], c[1], need[c]))
    if not codes:
        print('nothing to add')
        return

    print()
    print('rendering glyphs (simsun %s) ...' % SIZES)
    pools = {}
    offs = {}
    for px in SIZES:
        pool = bytearray()
        o = []
        for c in codes:
            W, H, rows = render_mask(need[c], px)
            o.append(len(pool))
            pool.append(W)
            pool.append(H)
            pool.extend(rows)
        pools[px] = bytes(pool)
        offs[px] = o
        print('  %dpx: cell %dx%d, pool %d bytes' % (px, W, H, len(pool)))

    with open(OUT, 'w', encoding='ascii') as f:
        f.write('/* auto-generated by gen_extra.py -- extra glyphs (index = N_CHARS + i) */\n')
        f.write('#define EXTRA_N %d\n' % len(codes))
        cvals = [(c[0] << 8) | c[1] for c in codes]
        f.write('static const unsigned short g_extraCode[%d] = {%s};\n'
                % (len(cvals), ','.join(str(v) for v in cvals)))
        for px in SIZES:
            f.write('static const unsigned int g_extraOff%d[%d] = {%s};\n'
                    % (px, len(codes), ','.join(str(v) for v in offs[px])))
            f.write('static const unsigned char g_extraPool%d[%d] = {%s};\n'
                    % (px, len(pools[px]), ','.join(str(b) for b in pools[px])))
    print()
    print('written', OUT)


if __name__ == '__main__':
    main()
