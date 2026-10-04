# -*- coding: utf-8 -*-
"""离线核验「游戏里的中文到底长什么样」。

不需要启动游戏、不需要点 UI、不需要看图 —— 直接用游戏实际使用的
字形池把资源字节渲染成**可读文本 / 文本网格**。

查找链严格对齐 cjk.cpp 的 GlyphIndex() + GlyphMask()：
    1) 主表   big5idx / custidx   -> 字形索引 0..N_CHARS-1
    2) 补充表 g_extraCode         -> N_CHARS + i   （早期版本漏了这步，
                                    把 課/陲/滲 等误报成缺字形）
字形池格式：m[0]=宽W  m[1]=高H  m[2..]=1bpp 行  rowb=(W+7)/8

用法:
    render_text.py          # 核对用户报告的乱码字 + 自定义对上下文
    render_text.py -all     # 额外扫描全部资源文件
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
B = os.path.join(os.path.dirname(HERE), 'SavenKingdom_II_HD_CHINESE')
GAME = r'I:\LocalGames\Seven Kingdoms II HD'
RES = os.path.join(GAME, 'update', 'Resource')

B5_LEAD_MIN, B5_LEAD_MAX, B5_TC = 0xA1, 0xF9, 157
CUST_LEAD_MIN, CUST_LEAD_COUNT = 0x90, 17


def arr(txt, name):
    """取出 static const T name[] = { ... }; 里的数字列表"""
    m = re.search(r'%s\[[^\]]*\]\s*=\s*\{' % name, txt)
    if not m:
        raise AttributeError(name)
    st = m.end()
    en = txt.index('}', st)
    return [int(x) for x in re.findall(r'\d+', txt[st:en])]


def _trail_of_ti(ti):
    """字形表列号 -> Big5 trail 字节"""
    return (0x40 + ti) if ti <= 62 else (0xA1 + (ti - 63))


class Font(object):
    def __init__(self):
        t = open(os.path.join(B, 'fontdata.h'), encoding='ascii').read()
        self.n = int(re.search(r'#define N_CHARS\s+(\d+)', t).group(1))
        self.big5 = arr(t, 'big5idx')
        self.cust = arr(t, 'custidx')
        self.go16 = arr(t, 'goff16')
        self.pool16 = arr(t, 'gpool16')
        self.load_extra()
        self.custmap = self._build_custmap()

    # ---------- 补充字形表 ----------
    def load_extra(self):
        self.extra_code = []
        self.extra_off = {}
        self.extra_pool = {}
        p = os.path.join(B, 'fontdata_extra.h')
        if not os.path.exists(p):
            return
        t = open(p, encoding='ascii').read()
        self.extra_code = arr(t, 'g_extraCode')
        for px in (13, 16, 24):
            try:
                self.extra_off[px] = arr(t, 'g_extraOff%d' % px)
                self.extra_pool[px] = arr(t, 'g_extraPool%d' % px)
            except AttributeError:
                pass

    def extra_index(self, lead, trail):
        code = (lead << 8) | trail
        if code in self.extra_code:
            return self.n + self.extra_code.index(code)
        return None

    # ---------- 自定义对 -> 原 Big5 反查 ----------
    def _build_custmap(self):
        """自定义对(lead 0x90-0xA0) -> 等价的标准 Big5 对。

        同一字形索引必定是同一个字，据此还原，不需要额外维护映射表，
        也避免了 glyph2char 那种「取首个遇到的码」的反查误判。
        """
        gi2std = {}
        for lead in range(B5_LEAD_MIN, B5_LEAD_MAX + 1):
            base = (lead - B5_LEAD_MIN) * B5_TC
            for ti in range(B5_TC):
                v = self.big5[base + ti]
                if v:
                    gi2std.setdefault(v - 1, (lead, _trail_of_ti(ti)))
        out = {}
        for lead in range(CUST_LEAD_MIN, CUST_LEAD_MIN + CUST_LEAD_COUNT):
            base = (lead - CUST_LEAD_MIN) * B5_TC
            for ti in range(B5_TC):
                v = self.cust[base + ti]
                if not v:
                    continue
                std = gi2std.get(v - 1)
                if std:
                    out[(lead, _trail_of_ti(ti))] = std
        return out

    # ---------- 核心查找 ----------
    def glyph(self, lead, trail):
        ti = (trail - 0x40) if trail <= 0x7E else (63 + (trail - 0xA1))
        if not (0 <= ti < B5_TC):
            return None
        if CUST_LEAD_MIN <= lead < CUST_LEAD_MIN + CUST_LEAD_COUNT:
            v = self.cust[(lead - CUST_LEAD_MIN) * B5_TC + ti]
        elif B5_LEAD_MIN <= lead <= B5_LEAD_MAX:
            v = self.big5[(lead - B5_LEAD_MIN) * B5_TC + ti]
        else:
            return None
        if v:
            return v - 1
        return self.extra_index(lead, trail)

    def mask(self, gi, px=16):
        if gi >= self.n:
            pool = self.extra_pool.get(px)
            if pool is None:
                return None
            o = self.extra_off[px][gi - self.n]
        elif px == 16:
            pool, o = self.pool16, self.go16[gi]
        else:
            raise NotImplementedError('主表只加载了 16px 偏移')
        W, H = pool[o], pool[o + 1]
        rowb = (W + 7) >> 3
        return [[1 if (pool[o + 2 + y * rowb + (x >> 3)] & (0x80 >> (x & 7)))
                 else 0 for x in range(W)] for y in range(H)]


def ispair(b1, b2):
    if 0xA1 <= b1 <= 0xF9 and (0x40 <= b2 <= 0x7E or 0xA1 <= b2 <= 0xFE):
        return True
    if 0x90 <= b1 <= 0xA0 and 0x40 <= b2 <= 0x7E:
        return True
    return False


def glyphs_of(ft, data):
    """拆成 [(rows|None, missing, tag)]，tag 为 (lead,trail) 或单字符"""
    out = []
    i = 0
    while i < len(data):
        b = data[i]
        if b < 0x80:
            out.append((None, False, chr(b)))
            i += 1
            continue
        if i + 1 < len(data) and ispair(b, data[i + 1]):
            gi = ft.glyph(b, data[i + 1])
            tag = ft.custmap.get((b, data[i + 1]), (b, data[i + 1]))
            if gi is None:
                out.append((None, True, tag))
            else:
                out.append((ft.mask(gi), False, tag))
            i += 2
            continue
        out.append((None, False, '<%02X>' % b))
        i += 1
    return out


def tag_text(tag):
    if isinstance(tag, tuple):
        try:
            return bytes(tag).decode('cp950')
        except Exception:
            return '<%02X%02X>' % tag
    return tag


def summarize(ft, label, data, out=None):
    gl = glyphs_of(ft, data)
    parts, miss = [], []
    for k, (rows, m, tag) in enumerate(gl):
        if isinstance(tag, tuple) and m:
            miss.append('<%02X%02X>@%d' % (tag[0], tag[1], k))
            parts.append('\u25a1')
        else:
            parts.append(tag_text(tag))
    text = re.sub(r'[\x00-\x08\x0b-\x1f]', '.', ''.join(parts))
    print('=== %s (%d 字节, %d 格) ===' % (label, len(data), len(gl)))
    print('  ' + text)
    print('  缺字形 %d 个 %s' % (len(miss), (' '.join(miss)) if miss else '(无)'))
    if out:
        try:
            render_png(ft, gl).save(out)
        except ImportError:
            pass
    print()
    return text, miss


def render_png(ft, gl, cw=18, ch=18, scale=2):
    from PIL import Image
    W = max(1, len(gl)) * cw
    img = Image.new('RGB', (W, ch), (255, 255, 255))
    px = img.load()
    for k, (rows, miss, tag) in enumerate(gl):
        ox = k * cw
        if miss:
            for x in range(cw):
                px[ox + x, ch - 1] = (255, 0, 0)
        elif rows is not None:
            for y, row in enumerate(rows):
                for x, v in enumerate(row):
                    if v:
                        px[ox + x, y] = (0, 0, 0)
    return img.resize((W * scale, ch * scale), Image.NEAREST)


def find_all(path, needle):
    d = open(path, 'rb').read()
    return [m.start() for m in re.finditer(re.escape(needle), d)]


def res_files():
    return sorted(f for f in os.listdir(RES)
                  if f.lower().endswith(('.res', '.set')))


def main():
    ft = Font()
    print('N_CHARS=%d  big5idx=%d  custidx=%d  goff16=%d  pool16=%d'
          % (ft.n, len(ft.big5), len(ft.cust), len(ft.go16), len(ft.pool16)))
    print('EXTRA=%d  custmap=%d' % (len(ft.extra_code), len(ft.custmap)))
    print()
    outdir = os.path.join(HERE, '_render')
    os.makedirs(outdir, exist_ok=True)

    target = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('-') \
        else '族訓賄'
    if '-all' in sys.argv:
        target = None

    if target:
        for ch in target:
            hits = []
            for fn in res_files():
                for off in find_all(os.path.join(RES, fn), ch.encode('cp950')):
                    hits.append((fn, off))
            print('[%s] 出现 %d 次' % (ch, len(hits)))
            for fn, off in hits[:6]:
                d = open(os.path.join(RES, fn), 'rb').read()
                seg = d[max(0, off - 6):off + 40].split(b'\x00')[0]
                summarize(ft, '%s @0x%X' % (fn, off), seg,
                          os.path.join(outdir, '%s_%X.png' % (fn, off)))
            print()
        return

    # -all: 全资源扫描
    import collections
    miss = collections.Counter()
    ctx = collections.defaultdict(list)
    for fn in res_files():
        data = open(os.path.join(RES, fn), 'rb').read()
        if fn.upper() == 'STD.SET':
            continue          # STD.SET 需先过引擎映射表，交给 fix_stdset 保证
        gl = glyphs_of(ft, data)
        for k, (rows, m, tag) in enumerate(gl):
            if not (m and isinstance(tag, tuple)):
                continue
            try:
                ch = bytes(tag).decode('cp950')
            except Exception:
                ch = '?'
            miss[(ch, tag)] += 1
            if len(ctx[(ch, tag)]) < 2:
                around = ''.join(tag_text(gl[a][2]) if not isinstance(gl[a][2], tuple)
                                 else tag_text(gl[a][2])
                                 for a in range(max(0, k - 8), min(len(gl), k + 8)))
                ctx[(ch, tag)].append('%s@%d ...%s...' % (fn, k, around))
    print('缺字形统计:')
    print('%-6s %-8s %-6s %s' % ('字', 'Big5', '次数', '上下文'))
    for (ch, tag), nn in sorted(miss.items(), key=lambda kv: -kv[1]):
        print('%-6s %-8s %-6d %s'
              % (ch, '%02X%02X' % tag, nn, ctx[(ch, tag)][0] if ctx.get((ch, tag)) else ''))
    print('\n合计 %d 种 / %d 次' % (len(miss), sum(miss.values())))


if __name__ == '__main__':
    main()
