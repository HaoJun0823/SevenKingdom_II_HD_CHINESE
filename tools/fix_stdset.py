# -*- coding: utf-8 -*-
"""修正 STD.SET 的「引擎侧字符映射」问题。

== 问题根源 ==
引擎在读取 STD.SET 的文本字段时，会把 **>=0x80 的字节逐个查表替换**
（表在 `7K2.exe` 文件偏移 `0x27F028`，按字节值索引；实测只对高位生效，
低位 ASCII 原样通过 —— 否则原版英文也会被破坏）。

英文全是低位，所以原版正常；旧汉化包把文本写成 Big5，高位字节被查表
替换 -> 显示乱码（实测：`諾曼` -> `鵔漫動`）。

该表在高位区是**部分函数**：128 个输入里 33 个被映射成 `?`，
只有 95 个不同输出。因此**并非所有字节都能「写进去再被引擎还原」**。
Big5 范围内不可生成的字节是 **AD / AF / B8**（另加 0x80-0xA0 整段，
但那不属于 Big5），实测影响 **77 个汉字**。

== 三步编码 ==
1. `decode_display`：旧包字节 -> 显示文本（自定义对 0x90-0xA0 也要解）
2. `to_std_big5`   ：显示文本 -> 标准 Big5（简->繁，异体归一）
   若某字的标准 Big5 含 AD/AF/B8 -> 改用 `gen_stdmap.py` 分配的
   **STD 专用码位**（可达且 big5idx 空闲，字形直接复用主池）
3. `premap_std`    ：把最终码位做逆映射后写盘，引擎查表后正好还原

纯 ASCII 与无法处理的 token 一律回退原版（英文），零风险。
字段 padding 沿用原版的空格风格。
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = r'I:\LocalGames\Seven Kingdoms II HD'
ORIG = os.path.join(GAME, 'Resource', 'STD.SET')      # 原版（英文，做底）
SRC = r'I:\LocalGames\Seven Kingdoms II HD\七个王国2\七国2汉化包\zh_CN\Resource\STD.SET'
OUT = r'G:\Projects\SavenKingdom_II_HD_CHINESE\update_res_staged\Resource\STD.SET'
TABLE_OFF = 0x27F028
DELIM = {0x00, 0x0D, 0x0A}

sys.path.insert(0, HERE)
from fontlib import FontTable, decode_display          # noqa: E402
from gen_stdmap import (T, engine_map, premap_std, to_trad,   # noqa: E402
                        enc_std, NOIMG)

# STD 专用码位表：原 Big5 码 -> 备用码位
_stdmap = {}
_stdpath = os.path.join(os.path.dirname(HERE), 'SavenKingdom_II_HD_CHINESE',
                        'fontdata_std.h')
if os.path.exists(_stdpath):
    import re as _re
    _t = open(_stdpath, encoding='ascii').read()
    _orig = [int(x) for x in _re.search(r'g_stdOrig\[STD_N\] = \{([^}]*)\}', _t).group(1).split(',')]
    _slot = [int(x) for x in _re.search(r'g_stdCode\[STD_N\] = \{([^}]*)\}', _t).group(1).split(',')]
    _stdmap = {(_orig[i] >> 8, _orig[i] & 0xFF): (_slot[i] >> 8, _slot[i] & 0xFF)
               for i in range(len(_orig))}



# ---- 按需槽位分配 ---------------------------------------------------------
# gen_stdmap.py 只收录「旧包已译字段里出现过」的不可达字形，但我们也会
# 引入新译名（如 RACE_FIX 里的「諾爾曼」「日本」），其中的字可能从未出现
# 在旧包语料里 -> 那时 _stdmap 没有对应条目。这里按同样规则现场分配：
# 只用「低位 trail (0x40-0x7E)」且 big5idx 中空闲的码位。
_FT = None
_FREE = None
_SLOT_USED = set()
_BAD_TRAILS = {0x5B, 0x5D, 0x7B, 0x7C, 0x7D, 0x7E, 0x7F}
_TC = 157
_slotpath = os.path.join(os.path.dirname(HERE), 'SavenKingdom_II_HD_CHINESE',
                         'fontdata_std.h')
if os.path.exists(_slotpath):
    import re as _re2
    _t2 = open(_slotpath, encoding='ascii').read()
    _o2 = _re2.search(r'g_stdCode\[STD_N\] = \{([^}]*)\}', _t2)
    if _o2:
        for _v in _o2.group(1).split(','):
            _v = int(_v)
            _SLOT_USED.add((_v >> 8, _v & 0xFF))


def _free_slots():
    global _FT, _FREE
    if _FREE is not None:
        return _FREE
    from fontlib import FontTable as _FTcls
    _FT = _FTcls()
    out = []
    for lead in range(0xA1, 0xFA):
        if lead in NOIMG:
            continue
        for ti in range(63):
            t = 0x40 + ti
            if t in _BAD_TRAILS:
                continue
            if _FT.big5[(lead - 0xA1) * _TC + ti]:
                continue
            out.append((lead, t))
    _FREE = out
    return _FREE


_NEW_SLOTS = []      # 本次运行新分配的槽位（需要回写 fontdata_std.h）

# RAW=1：直接写原始 Big5（配合 DLL 的 oem=1 恒等化补丁）。
# RAW=0：旧行为，写盘前做 T 的逆映射。
RAW = False


def _emap(b):
    """引擎实际看到的字节（RAW 模式下引擎不做变换）"""
    return b if RAW else engine_map(b)


def alloc_slot(code):
    """为不可达码位现场申请一个可达空闲槽位，并登记到 _stdmap"""
    for slot in _free_slots():
        if slot in _SLOT_USED:
            continue
        _SLOT_USED.add(slot)
        _stdmap[code] = slot
        _NEW_SLOTS.append((code, slot))
        return slot
    return None

def encode_text(text):
    """显示文本 -> 写盘字节；任一字无法处理则返回 None

    RAW=0（旧行为）：先走槽位替换避开不可达字节，再对整串做 T 的逆映射，
                     使引擎过表后正好还原成目标 Big5。
    RAW=1（配合 DLL 把 OEM 表恒等化）：直接写原始 Big5，不做任何变换。
    """
    out = bytearray()
    for ch in text:
        o = ord(ch)
        if o < 0x80:
            out.append(o)
            continue
        if not (0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF
                or 0xF900 <= o <= 0xFAFF or ch in '，。、；：？！“”‘’（）《》—…'):
            return None                      # 制表符/箭头/框线等，不处理
        std = enc_std(ch)
        if std is None:
            return None
        b1, b2 = std[0], std[1]
        if not RAW and (b1 in NOIMG or b2 in NOIMG):
            slot = _stdmap.get((b1, b2))
            if slot is None:
                slot = alloc_slot((b1, b2))   # 新字首次出现：现场申请槽位
                if slot is None:
                    return None
            b1, b2 = slot
        out += bytes((b1, b2))
    if RAW:
        return bytes(out)
    pm = premap_std_bytes(bytes(out))
    return pm


def premap_std_bytes(data):
    """把一串「引擎查表后应得的字节」转成写盘字节"""
    res = bytearray()
    for c in data:
        if c < 0x80:
            res.append(c)
            continue
        cands = [i for i in range(0x80, 0x100) if T[i] == c]
        if not cands:
            return None
        res.append(cands[0])
    return bytes(res)



# ---- 定点修正：旧包自身的错字 ----------------------------------------
# 旧包把 NORMAN 写成「日爾曼」——A4E9 在 cp950 里是「日」，
# 显然是把「諾」误存成了「日」（字形相近，繁体录入时易错）。
# 这里按记录名（RACE 行的 CODE）修正为正确译名。
# 注意：这里写的字可能不在旧包语料里（如「諾」），其 Big5 码 A4E9/BFD5
# 含不可达字节，必须走 alloc_slot() 现场分配槽位，否则 encode_text 会
# 返回 None 或产出引擎无法还原的字节。
RACE_FIX = {
    'NORMAN': '諾爾曼',        # 旧包写成「日爾曼」：A4E9 在 cp950 里是「日」
    'JAPANES': '日本',        # 旧包 NAME 写成 'E日本'，E 挤掉了前导空格
}


def _is_pair(b1, b2):
    """是否构成一个合法双字节对（标准 Big5 或自定义对 0x90-0xA0 头）"""
    if 0xA1 <= b1 <= 0xF9 and (0x40 <= b2 <= 0x7E or 0xA1 <= b2 <= 0xFE):
        return True
    if 0x90 <= b1 <= 0xA0 and 0x40 <= b2 <= 0x7E:
        return True
    return False


def dbcs_runs(buf, start, end):
    """在 buf[start:end] 里找出「连续合法双字节对」的区间（绝对偏移）。

    这是整个修正的关键：STD.SET 的一行里常常既有中文文本，又紧跟着
    数字/ID/二进制字段。替换粒度必须收紧到**纯双字节串**本身，
    绝不能像早期版本那样把译文之后到 token 末尾整段填空格 ——
    那会把紧随其后的数值字段一起抹掉，游戏拿这些 0 去查表就会
    算出野指针并崩溃（实测 crash @ 7K2.exe+0x180AED）。
    """
    runs = []
    i = start
    while i < end - 1:
        if _is_pair(buf[i], buf[i + 1]):
            st = i
            while i < end - 1 and _is_pair(buf[i], buf[i + 1]):
                i += 2
            runs.append((st, i))
        else:
            i += 1
    return runs


def apply_race_fixes(out, orig):
    """按 RACE 记录的 CODE 字段修正译名；返回修正条数"""
    n = struct.unpack_from('<h', orig, 0)[0]
    rec = None
    for k in range(n + 1):
        o = 2 + k * 13
        if orig[o:o + 9].rstrip(b'\x00') == b'RACE':
            rec = struct.unpack_from('<I', orig, o + 9)[0]
    if rec is None:
        return 0
    fixed = 0
    for r in range(12):
        code_off = rec + 0xC1 + 45 * r
        code = bytes(out[code_off:code_off + 8]).strip(b' \x00').decode('latin-1')
        want = RACE_FIX.get(code)
        if not want:
            continue
        pm = encode_text(want)
        if not pm:
            continue
        # RACE 行布局（GOG/Steam 一致，实测 45 字节/行）:
        #   [+0]   1 字节行首空格
        #   [+1]   CODE[8]   'NORMAN  '
        #   [+9]   NAME[12]  'Norman      '   <- 内容直接从 +9 开始，无内部空格
        #   [+21]  ADJ[12]   'Norman      '
        #   [+33]  ICON[8]   'S_NORMAN'
        #   [+41]  ICONPTR[4]
        # 之前误写成 code_off+8（CODE 的最后一个填充字节），译文首字节
        # 落在 NAME 之外 -> 引擎从 NAME[+1] 读起，丢掉第 1 个字节 -> 乱码。
        for field_off, flen in ((9, 12), (21, 12)):
            base = code_off + field_off
            for k in range(base, base + flen):
                out[k] = 0x20
            out[base:base + len(pm)] = pm
        fixed += 1
    return fixed


def main():
    global RAW
    dry = '--dry' in sys.argv
    RAW = '--raw' in sys.argv
    if RAW:
        print('[i] RAW 模式：直接写原始 Big5，不做逆映射/槽位替换'
              '（要求 DLL 侧 render.ini oem=1）')
    orig = open(ORIG, 'rb').read()
    src = open(SRC, 'rb').read()
    if len(orig) != len(src):
        print('! length mismatch: orig %d / src %d' % (len(orig), len(src)))
        return 1

    ft = FontTable()
    out = bytearray(orig)
    n = len(orig)

    stat = {'tok': 0, 'ok': 0, 'revert': 0, 'slots': 0, 'long': 0, 'binary': 0}
    detail = []
    p = 0
    while p < n:
        if src[p] in DELIM:
            p += 1
            continue
        q = p
        while q < n and src[q] not in DELIM:
            q += 1
        runs = dbcs_runs(src, p, q)
        stat['tok'] += len(runs)
        for (a, b) in runs:
            # 二进制保护区：原版同一位置必须是可打印 ASCII（英文文本字段）。
            # 若原版这里是控制符/高位字节，说明这条其实是二进制记录，
            # 早期版本正是在这里把数值字段抹成空格，导致进入游戏崩溃。
            if not all(0x20 <= c < 0x7F or c == 0x00 for c in orig[a:b]):
                stat['binary'] += 1
                continue
            text = decode_display(bytes(src[a:b]), ft)
            if not text:
                stat['revert'] += 1
                continue
            pm = encode_text(text)
            if pm is None:
                stat['revert'] += 1
                continue
            if len(pm) > (b - a):
                stat['long'] += 1
                continue
            out[a:a + len(pm)] = pm
            # 清除残留英文：英文原文通常比中文长，换写完还会剩几个字母。
            # 判据必须同时满足两条才算残留，缺一不可：
            #   1) 旧包同一位置是填充（0x00 或 0x20）—— 旧包常用 0x00 填充
            #   2) 原版同一位置是英文字母
            # 这样既不会越过下一个字段（旧包那里是真实内容，非填充），
            # 也不会碰到数字/ID/二进制字段（不是字母）。
            e = a + len(pm)
            cap = min(n, a + len(pm) + 128)
            while e < cap and src[e] in (0x00, 0x20) and (
                    0x41 <= orig[e] <= 0x5A or 0x61 <= orig[e] <= 0x7A):
                e += 1
            for k in range(a + len(pm), e):
                out[k] = 0x20
            stat['ok'] += 1
            detail.append((a, bytes(src[a:b]), text, pm))
        p = q

    nf = apply_race_fixes(out, orig)
    print('race name fixes: %d' % nf)

    if not dry:
        open(OUT, 'wb').write(bytes(out))
        print('written %s' % OUT)

    print('translated tokens: %d' % stat['tok'])
    print('  pre-mapped OK   : %d' % stat['ok'])
    print('  reverted to EN  : %d  (unencodable chars)' % stat['revert'])
    print('  reverted to EN  : %d  (exceeds field capacity)' % stat['long'])
    print('  skipped binary  : %d  (原版同位置非可打印 -> 二进制区)' % stat['binary'])
    print('  STD slots used  : %d' % len(_stdmap))
    print()
    print('samples:')
    for (p, tok, text, pm) in detail[:14]:
        back = bytes(_emap(x) for x in pm)
        try:
            shown = back.decode('cp950')
        except Exception:
            shown = repr(back)
        print('  @%-8d src=%-16s %-10s -> wrote %-16s engine sees %-16s %s'
              % (p, tok.hex(' '), text, pm.hex(' '), back.hex(' '), shown))

    # RACE 抽样
    cnt = struct.unpack_from('<h', orig, 0)[0]
    rec = None
    for k in range(cnt + 1):
        o = 2 + k * 13
        if orig[o:o + 9].rstrip(b'\x00') == b'RACE':
            rec = struct.unpack_from('<I', orig, o + 9)[0]
    print()
    print('RACE 12 rows  (CODE / NAME@+9 / ADJ@+21，槽位已还原为原字):')
    rev = {v: k for k, v in _stdmap.items()}
    bad = 0
    for r in range(12):
        base = rec + 0xC1 + 45 * r
        code = bytes(out[base:base + 9]).strip(b' \x00').decode('latin-1')
        cells = []
        for field_off, flen, tag in ((9, 12, 'NAME'), (21, 12, 'ADJ')):
            off = base + field_off
            seen = bytes(_emap(x) for x in out[off:off + flen])
            shown, ok = decode_seen(seen, rev)
            if not ok:
                bad += 1
            cells.append('%s=%s' % (tag, shown))
        print('  row%-2d %-9s %s' % (r, code, '  '.join(cells)))
    print('  %s' % ('%d 个字段异常' % bad if bad else '12 行全部正常'))
    return 0


def decode_seen(seen, rev):
    """引擎还原后的字节 -> 可读文本；STD 槽位还原成原 Big5 再解 cp950"""
    buf = bytearray()
    p = 0
    while p < len(seen):
        c = seen[p]
        if c < 0x80:
            if c == 0x20 or c == 0x00:
                p += 1
                continue
            buf.append(c)
            p += 1
            continue
        if p + 1 < len(seen) and seen[p + 1] != 0x00:
            pair = (c, seen[p + 1])
            pair = rev.get(pair, pair)
            buf += bytes(pair)
            p += 2
        else:
            p += 1
    try:
        return buf.decode('cp950'), True
    except Exception:
        return '<%s>' % bytes(buf).hex(' ').upper(), False


if __name__ == '__main__':
    sys.exit(main())
