# -*- coding: utf-8 -*-
"""汉化资产批量提取 + 字形校验。

为什么需要它
------------
游戏里的文字散落在几十种容器里（.res 键值表 / STD.SET 结构化二进制 /
战役脚本 .stg .evt .sct .plt / 以及写在 C++ 源码里的 exe 内置标签）。
靠人眼在游戏里一个个界面点过去找「哪个字没显示」不可行。

本脚本：
  1) 按各文件**自身格式**提取文本（不做全局贪心扫字节，避免错位漏判）
  2) 校验每个双字节对在字形表里是否存在 → 缺字清单
  3) 【关键】用「段内有效字形占比」过滤二进制段。
     STD.SET / TUT_TEXT.RES 里的索引表恰好也能通过 cp950 严格解码，
     不加这道过滤会产生近千条生僻字假缺字。
  4) 可选：与系统 simsun 同字号渲染比对（IoU），抓「字形挂错字」

用法：
  python check_glyphs.py                     提取 + 缺字校验
  python check_glyphs.py --shapes --top 60   追加字形相似度校验
  python check_glyphs.py --only STD.SET      只看某个文件
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_text as rt

GAME = r'I:\LocalGames\Seven Kingdoms II HD'
STAGE_ROOT = os.path.join(GAME, 'update')

TOKEN_FILES = {'STD.SET'}                       # 按 token（00/0D/0A）切
KV_EXT = {'.res', '.txt'}                       # 按 CRLF 行切，取 ']' 之后
SCRIPT_EXT = {'.stg', '.evt', '.sct', '.plt', '.dlg', '.txr'}

SKIP_NAMES = ('stage.txt',)
SKIP_SUFFIX = ('.log', '.bak', '.prev', '.ini', '.orig')
SKIP_PREFIX = ('sk2_zh.log',)

# 段内「有字形」占比低于此值 → 判为二进制段，整体不计入缺字
GOOD_RATIO = 0.60
MIN_PAIRS = 3

# 写在 C++ 源码里的 exe 内置标签（不落盘，必须单独校验）
CPP_LABELS = ['小', '大', '選擇', '更改顯示模式', '全螢幕模式', '視窗模式',
              '外交請求', '正常', '自動提示盟友', '停火']


def skip_file(name):
    n = name.lower()
    return (name in SKIP_NAMES or n.startswith(SKIP_PREFIX)
            or n.endswith(SKIP_SUFFIX))


def is_trail(b):
    return (0x40 <= b <= 0x7E) or (0xA1 <= b <= 0xFE)


def is_lead(b):
    """本工程使用的 Big5 前导范围：0xA1-0xF9 标准 / 0x90-0xA0 自定义对。
    0x81-0x8F 与 0xFA-0xFE 不在字库索引范围内，不当作文字。"""
    return (0xA1 <= b <= 0xF9) or (0x90 <= b <= 0xA0)


def plausible(seg):
    """必须整体严格 cp950 可解，且不含控制字符 —— 先挡掉明显二进制。"""
    if len(seg) < 2 or b'\x00' in seg:
        return False
    for b in seg:
        if b < 0x20 and b != 0x09:
            return False
    try:
        seg.decode('cp950')
    except Exception:
        return False
    return any(b >= 0x80 for b in seg)


# ---------------------------------------------------------------- 文本提取

def seg_texts(data, ext, name):
    out = []
    if name.upper() in TOKEN_FILES:
        p, n = 0, len(data)
        while p < n:
            if data[p] in (0, 0x0D, 0x0A):
                p += 1
                continue
            q = p
            while q < n and data[q] not in (0, 0x0D, 0x0A):
                q += 1
            tok = data[p:q]
            if len(tok) >= 2 and any(b >= 0x80 for b in tok):
                out.append((p, tok))
            p = q
        return out

    if ext in KV_EXT or ext == '.res':
        pos = 0
        for line in data.split(b'\r\n'):
            body, off = line, 0
            if body[:1] == b'[':
                k = body.find(b']')
                if k >= 0:
                    off = k + 1
                    body = body[off:]
            z = body.find(b'\x00')
            if z >= 0:
                body = body[:z]
            if len(body) >= 2 and any(b >= 0x80 for b in body):
                out.append((pos + off, body))
            pos += len(line) + 2
        return out

    # 脚本类：切「可读字符连续段」
    i, n = 0, len(data)
    start, buf = -1, bytearray()
    while i < n:
        b = data[i]
        if 0x20 <= b < 0x7F:
            if start < 0:
                start = i
            buf.append(b)
            i += 1
            continue
        if is_lead(b) and i + 1 < n and is_trail(data[i + 1]):
            if start < 0:
                start = i
            buf.append(b)
            buf.append(data[i + 1])
            i += 2
            continue
        if len(buf) >= 2 and any(x >= 0x80 for x in buf):
            out.append((start, bytes(buf)))
        start, buf = -1, bytearray()
        i += 1
    if len(buf) >= 2 and any(x >= 0x80 for x in buf):
        out.append((start, bytes(buf)))
    return out


def split_pairs(seg):
    """切成 [(lead,trail)] 或 [(byte,None)]（孤立高位字节）"""
    pairs, i, n = [], 0, len(seg)
    while i < n:
        b = seg[i]
        if b < 0x80:
            i += 1
            continue
        if i + 1 < n and is_lead(b) and is_trail(seg[i + 1]):
            pairs.append((b, seg[i + 1]))
            i += 2
            continue
        pairs.append((b, None))
        i += 1
    return pairs


# ---------------------------------------------------------------- 主流程

def main():
    do_shapes = '--shapes' in sys.argv
    top = 40
    if '--top' in sys.argv:
        top = int(sys.argv[sys.argv.index('--top') + 1])
    only = None
    if '--only' in sys.argv:
        only = sys.argv[sys.argv.index('--only') + 1].lower()
    root_dir = STAGE_ROOT
    if '--root' in sys.argv:
        root_dir = sys.argv[sys.argv.index('--root') + 1]

    ft = rt.Font()
    print('字形表 N_CHARS=%d  EXTRA_N=%d' % (ft.n, len(ft.extra_code)))
    print('扫描目录:', root_dir)
    print('=' * 100)

    miss = {}          # (b1,b2) -> 次数（可信：来自「像文本」的段）
    miss_ctx = {}      # (b1,b2) -> [(file, off, text)]
    junk = {}          # (b1,b2) -> 次数（不可信：来自疑似二进制段）
    badbytes = {}
    used_all = set()
    files = segs = good_segs = 0

    for root, _, fs in os.walk(root_dir):
        for f in sorted(fs):
            if skip_file(f):
                continue
            if only and f.lower() != only:
                continue
            ext = os.path.splitext(f)[1].lower()
            p = os.path.join(root, f)
            try:
                data = open(p, 'rb').read()
            except Exception:
                continue
            rel = os.path.relpath(p, STAGE_ROOT)
            files += 1
            for off, seg in seg_texts(data, ext, f):
                if not plausible(seg):
                    continue
                pairs = split_pairs(seg)
                if len(pairs) < MIN_PAIRS:
                    continue
                segs += 1
                ok = sum(1 for a, b in pairs
                         if b is not None and ft.glyph(a, b) is not None)
                ratio = ok / float(len(pairs))
                textual = ratio >= GOOD_RATIO
                if textual:
                    good_segs += 1
                txt = seg.decode('cp950', 'replace')
                for a, b in pairs:
                    if b is None:
                        badbytes[a] = badbytes.get(a, 0) + 1
                        continue
                    used_all.add((a, b))
                    if ft.glyph(a, b) is None:
                        if textual:
                            miss[(a, b)] = miss.get((a, b), 0) + 1
                            miss_ctx.setdefault((a, b), []).append((rel, off, txt[:60]))
                        else:
                            junk[(a, b)] = junk.get((a, b), 0) + 1

    for lab in CPP_LABELS:
        try:
            b = lab.encode('big5')
        except Exception:
            print('  !! 标签无法 Big5 编码:', lab)
            continue
        for i in range(0, len(b), 2):
            pair = (b[i], b[i + 1])
            used_all.add(pair)
            if ft.glyph(*pair) is None:
                miss[pair] = miss.get(pair, 0) + 1
                miss_ctx.setdefault(pair, []).append(('(c++ exe label)', 0, lab))

    print('文件 %d 个；文本段 %d 段（其中判为「像文本」%d 段）；用到双字节对 %d 种'
          % (files, segs, good_segs, len(used_all)))
    print()

    print('【缺字形 —— 可信清单】%d 种' % len(miss))
    if miss:
        for pair in sorted(miss, key=lambda x: -miss[x]):
            try:
                ch = bytes(pair).decode('cp950')
            except Exception:
                ch = '?'
            ctx = miss_ctx.get(pair, [])
            where = '%s@0x%X %r' % (ctx[0][0], ctx[0][1], ctx[0][2]) if ctx else ''
            print('   %02X%02X  %-4s  ×%-3d  %s' % (pair[0], pair[1], ch, miss[pair], where))
    else:
        print('   （无 —— 所有译文都有字形）')
    print()

    print('【疑似二进制段里的「缺字」—— 仅供参照，通常不是文字】%d 种'
          % len(junk))
    if junk:
        tb = sorted(junk.items(), key=lambda x: -x[1])[:10]
        print('   ' + '  '.join('%02X%02X×%d' % (k[0], k[1], v) for k, v in tb))
    else:
        print('   （无）')
    print()

    print('【孤立高位字节（不成对）】%d 种' % len(badbytes))
    if badbytes:
        tb = sorted(badbytes.items(), key=lambda x: -x[1])[:10]
        print('   ' + '  '.join('0x%02X×%d' % (k, v) for k, v in tb))
    else:
        print('   （无）')
    print()

    if miss:
        seed = ''.join(bytes(pl).decode('cp950', 'replace') for pl in sorted(miss))
        print('【可直接粘贴到 tools/gen_extra.py 的 EXTRA_SEED】')
        print("EXTRA_SEED = '%s'" % seed)
        print()

    if do_shapes:
        print('=' * 100)
        verify_shapes(ft, sorted(used_all), top)


# ---------------------------------------------------------------- 形状校验

def _ref_mask(ch, px):
    import gen_extra
    try:
        W, H, rows = gen_extra.render_mask(ch, px)
    except Exception:
        return None
    rowb = (W + 7) >> 3
    return [[bool(rows[y * rowb + (x >> 3)] & (0x80 >> (x & 7))) for x in range(W)]
            for y in range(H)]


def _iou(a, b):
    if not a or not b:
        return 0.0
    h, w = min(len(a), len(b)), min(len(a[0]), len(b[0]))
    inter = uni = 0
    for y in range(h):
        ra, rb = a[y], b[y]
        for x in range(w):
            pa, pb = ra[x], rb[x]
            if pa and pb:
                inter += 1
            if pa or pb:
                uni += 1
    return inter / float(uni) if uni else 0.0


def verify_shapes(ft, pairs, top):
    try:
        import zhconv
    except Exception:
        print('  (zhconv 不可用，只比对本字)')
        zhconv = None
    rows = []
    for pair in pairs:
        gi = ft.glyph(*pair)
        if gi is None:
            continue
        try:
            ch = bytes(pair).decode('cp950')
        except Exception:
            continue
        m = ft.mask(gi, 16)
        if not m:
            continue
        cands = {ch}
        if zhconv:
            try:
                cands.add(zhconv.convert(ch, 'zh-hans'))
            except Exception:
                pass
        best, bestch = 0.0, ch
        for c in cands:
            r = _ref_mask(c, 16)
            s = _iou(m, r)
            if s > best:
                best, bestch = s, c
        rows.append((best, pair, ch, bestch, gi))
    rows.sort()
    print('【字形相似度校验】已比对 %d 个字形，IoU 最低的 %d 个：'
          % (len(rows), min(top, len(rows))))
    for s, pair, ch, bestch, gi in rows[:top]:
        print('    IoU=%.3f  %02X%02X  应为「%s」 参照最佳「%s」 字形#%d' %
              (s, pair[0], pair[1], ch, bestch, gi))


if __name__ == '__main__':
    main()
