# -*- coding: utf-8 -*-
"""把 gap_zh.json 的补充翻译编码为 Big5 资源，写入 update_res_staged/。

处理两类：
  A) ResourceIdx 容器（EAST.TXR / EAST.DLG / INTROTXT.RES / TUT_INTR.RES）
     —— 保留原记录顺序与各块尾部结构，仅替换文本字节，重建索引偏移。
  B) tag 型资源（t_*.res）—— 在 [TAG] 之后插入/替换文本。

编码：简体 → 繁体 → cp950（v2 方案：数据存 Big5，运行时映射简体字形）
用法： python build_gap.py [--dry]
"""
import os, re, sys, json, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fontlib import FontTable, remap_inplace

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = r'I:\LocalGames\Seven Kingdoms II HD'
OURS = r'G:\Projects\SavenKingdom_II_HD_CHINESE\update_res_staged'
DRY = '--dry' in sys.argv

_conv = None


def to_trad(s):
    global _conv
    if _conv is None:
        try:
            from zhconv import convert
            _conv = lambda t: convert(t, 'zh-hant')
        except Exception:
            _conv = lambda t: t
            print('  [警告] 未安装 zhconv，简体→繁体将退化为原样（可能编不出字）')
    return _conv(s)


FALLBACK = []

# 异体字归一：zhconv 偶尔给出 cp950 里没有的异体（如 爲/衆），换成标准 Big5 字形
VARIANT = {
    '\u7232': '\u70ba',   # 爲 -> 為
    '\u8846': '\u773e',   # 衆 -> 眾
    '\u88cf': '\u88e1',   # 裏 -> 裡
    '\u9ebc': '\u9ebc',   # 麼（cp950 有，占位）
    '\u6c92': '\u6c92',
}


def try_encode(ch):
    import unicodedata
    c = [to_trad(ch), ch]
    c += [unicodedata.normalize('NFKC', x) for x in list(c)]
    c += [VARIANT[x] for x in list(c) if x in VARIANT]
    for x in c:
        try:
            return x.encode('cp950')
        except Exception:
            pass
    return None


def enc_zh(text):
    """简体文本 → Big5 字节；\\n → CRLF；ASCII 标记原样"""
    out = bytearray()
    for ch in text:
        if ch == '\n':
            out += b'\r\n'
            continue
        if ch == '\r':
            continue
        if ord(ch) < 0x80:
            out += ch.encode('latin-1')
            continue
        e = try_encode(ch)
        if e is None:
            FALLBACK.append(ch)
            out += '　'.encode('cp950')
        else:
            out += e
    return bytes(out)


_FT = None


def enc(text):
    """编码 + 危险尾字节重映射（与既有资源保持一致）"""
    global _FT
    if _FT is None:
        _FT = FontTable()
    raw = enc_zh(text)
    out, n, miss = remap_inplace(raw, _FT)
    if miss:
        print('      [注意] 无自定义对、按标准 Big5 输出的字: %s' % ''.join(sorted(set(miss))))
    return out


def read_res_idx(path):
    data = open(path, 'rb').read()
    count = struct.unpack('<h', data[0:2])[0]
    recs = []
    for i in range(count + 1):
        off = 2 + i * 13
        nm = data[off:off + 9].rstrip(b'\x00').decode('latin-1')
        ptr = struct.unpack('<I', data[off + 9:off + 13])[0]
        recs.append((nm, ptr))
    return data, [(recs[i][0], recs[i][1], recs[i + 1][1] - recs[i][1]) for i in range(count)]


def write_res_idx(path, recs):
    hdr_size = 2 + 13 * (len(recs) + 1)
    cur = hdr_size
    ent = []
    blob = bytearray()
    for nm, raw in recs:
        ent.append((nm, cur))
        blob += raw
        cur += len(raw)
    hdr = bytearray(struct.pack('<h', len(recs)))
    for nm, off in ent:
        hdr += nm.encode('latin-1')[:9].ljust(9, b'\x00') + struct.pack('<I', off)
    hdr += b'\x00' * 9 + struct.pack('<I', cur)      # 终止记录指向文件末尾
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, 'wb').write(bytes(hdr) + bytes(blob))
    return len(hdr) + len(blob)


def build_container(rel, zmap):
    src = os.path.join(GAME, *rel.split('/'))
    data, recs = read_res_idx(src)
    out = []
    changed = 0
    for name, off, size in recs:
        raw = data[off:off + size]
        text_end = raw.find(b'\x00')
        if text_end < 0:
            text_end = len(raw)
        core, tail = raw[:text_end], raw[text_end:]
        if name in zmap and core.strip(b' \r\n\t'):
            new = enc(zmap[name])
            out.append((name, new + tail))
            changed += 1
            print('    [%s] %d -> %d 字节 (尾 %d)' % (name, len(core), len(new), len(tail)))
        else:
            out.append((name, raw))
    dst = os.path.join(OURS, *rel.split('/'))
    if DRY:
        print('  %-24s 干跑：将替换 %d/%d 条 -> %s' % (rel, changed, len(recs), dst))
    else:
        n = write_res_idx(dst, out)
        print('  %-24s 已写入 %s (%d 字节, 替换 %d 条)' % (rel, dst, n, changed))


# 标签名可能很长（如 [<enemy/friendly/...><unit description>UNRD] 有 44 字符），
# 之前限制 40 字符导致长标签不被识别、被当成上一个标签的正文吞掉
# （见 t_unit.res 的 RESV 事故：UNRD 标签消失，其后所有标签在引擎里失效）。
# 现在放宽到 80，且改为「字节级拼接」——只替换标签的值，其余字节原样保留。
TAG = re.compile(rb'\[([^\[\]\r\n]{1,80})\]')


def build_tags(fname, zmap):
    """在 tag 型资源里替换/插入 tag 文本（字节级拼接，绝不改动其它字节）。

    只识别**位于行首**的标签（偏移 0 或紧跟在 CR/LF 之后），这样
    "[RESV]xx[UNRD]yy" 这种同行双标签不会被误当成一条记录。
    """
    dst = None
    d = os.path.join(OURS, 'Resource')
    for f in os.listdir(d):
        if f.lower() == fname.lower():
            dst = os.path.join(d, f)
    if not dst:
        return False, '未找到 %s' % fname

    data = open(dst, 'rb').read()
    spans = []
    for m in TAG.finditer(data):
        s0 = m.start()
        if s0 == 0 or data[s0-1:s0] in (b'\r', b'\n'):
            spans.append(m)
    if not spans:
        return False, '无 tag'

    out = bytearray(data[:spans[0].start()])
    done = set()
    for i, m in enumerate(spans):
        tag = m.group(1).decode('latin-1')
        vstart = m.end()
        vend = spans[i + 1].start() if i + 1 < len(spans) else len(data)
        seg = data[vstart:vend]
        body = seg.rstrip(b'\r\n\x1a')
        tail = seg[len(body):]          # 保留原有换行/EOF 标记
        if tag in zmap:
            out += m.group(0) + enc(zmap[tag]) + tail
            done.add(tag)
        else:
            out += m.group(0) + seg     # 原样保留
    missing = [t for t in zmap if t not in done]
    if missing:
        add = bytearray()
        for t in missing:
            add += b'\r\n[' + t.encode('latin-1') + b']' + enc(zmap[t])
        if out.endswith(b'\x1a'):
            out = bytearray(bytes(out[:-1]) + bytes(add) + b'\r\n\x1a')
        else:
            out += add + b'\r\n'
    if not DRY:
        open(dst, 'wb').write(bytes(out))
    return True, '替换 %d 条%s' % (len(done), ('，追加 %s' % missing) if missing else '')


def main():
    zh = json.load(open(os.path.join(HERE, 'gap_zh.json'), encoding='utf-8'))
    print('=' * 72)
    print('A. ResourceIdx 容器')
    print('=' * 72)
    for rel in ['Campaign/EAST.TXR', 'Campaign/EAST.DLG',
                'Resource/INTROTXT.RES', 'Resource/CPG_INTR.RES',
                'Campaign/INTROTXT.RES', 'Resource/TUT_INTR.RES']:
        if rel in zh:
            build_container(rel, zh[rel])

    print()
    print('=' * 72)
    print('B. tag 型资源补缺')
    print('=' * 72)
    for fname, zmap in zh.get('__tags', {}).items():
        ok, msg = build_tags(fname, zmap)
        print('  %-16s %s %s' % (fname, 'OK' if ok else '失败', msg))

    print()
    if FALLBACK:
        print('★无法编入 Big5 的字符 %d 个: %s' % (len(FALLBACK), ''.join(sorted(set(FALLBACK)))))
    else:
        print('编码校验：全部字符均可编入 Big5（无回退）')
    print('干跑完成（未写盘）' if DRY else '全部写入完成')


if __name__ == '__main__':
    main()
