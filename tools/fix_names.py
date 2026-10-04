# -*- coding: utf-8 -*-
"""
修复剩下这批「可见界面」里没翻好的名字：

  * RACENAME 里 ~100 条诺尔斯语名字是「半截」：译者把 Björn 翻成 Bjö（只留了
    前面的英文 + 半个字），界面上就是一串乱码。原文本身是 cp1252 的高字节
    （ö/ó/ð/þ 等），所以 cp950 解不开。
  * TECH / TECH_DUP 里 #16 的 DESC 是同上错位造成的脏字节（"Viking ??維京騎兵基地"）。
  * TECH_DUP #66 "Camouflaged Fortress" 只翻了后半截。

译法沿用各族已有的音译惯例（见 unpack_data_chs 里同族的已译邻条），
不新造用字：全部字符走 cp950 编码，编不出来的再退回字体补丁的自定义字形对。

用法:
    python fix_names.py [--apply]     # 不加 --apply 只干跑
"""
import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db_table as D  # noqa: E402
import fontlib as F  # noqa: E402

CHS = r'G:\Projects\SavenKingdom_II_HD_CHINESE\unpack_data_chs\Resource\STD.SET.unpacked'
ORIG = r'G:\Projects\SavenKingdom_II_HD_CHINESE\unpack_data_original\Resource\STD.SET.unpacked'

# (表, 记录下标, 字段, 正确中文)
FIX = [
    # ---- 诺尔斯/维京人名（原文本身带 cp1252 高字节，旧译只留了前半截）----
    ('RACENAME', 387, 'NAME', '比約恩'),
    ('RACENAME', 389, 'NAME', '格里姆'),
    ('RACENAME', 401, 'NAME', '赫羅爾夫'),
    ('RACENAME', 405, 'NAME', '埃約爾夫'),
    ('RACENAME', 406, 'NAME', '哈爾多'),
    ('RACENAME', 416, 'NAME', '阿諾爾'),
    ('RACENAME', 417, 'NAME', '赫羅德'),
    ('RACENAME', 419, 'NAME', '斯坦尼爾夫'),
    ('RACENAME', 423, 'NAME', '伯茲瓦爾'),
    ('RACENAME', 425, 'NAME', '約倫德'),
    ('RACENAME', 428, 'NAME', '埃裏克'),
    ('RACENAME', 432, 'NAME', '奧杜恩'),
    ('RACENAME', 434, 'NAME', '古德蒙德'),
    ('RACENAME', 436, 'NAME', '赫約爾夫'),
    ('RACENAME', 439, 'NAME', '海丁'),
    ('RACENAME', 441, 'NAME', '維蒙德'),
    ('RACENAME', 448, 'NAME', '瑟爾維'),
    ('RACENAME', 454, 'NAME', '艾利夫'),
    ('RACENAME', 466, 'NAME', '吉斯利'),
    ('RACENAME', 467, 'NAME', '古德拉格'),
    ('RACENAME', 470, 'NAME', '霍爾姆斯坦恩'),
    ('RACENAME', 472, 'NAME', '赫斯科德'),
    ('RACENAME', 479, 'NAME', '阿恩格林'),
    ('RACENAME', 481, 'NAME', '貝格索爾'),
    ('RACENAME', 485, 'NAME', '哈蒙德'),
    ('RACENAME', 486, 'NAME', '霍格尼'),
    ('RACENAME', 487, 'NAME', '卡裏'),
    ('RACENAME', 499, 'NAME', '布律尼爾夫'),
    ('RACENAME', 500, 'NAME', '伯茲瓦'),
    ('RACENAME', 501, 'NAME', '伯克爾'),
    ('RACENAME', 508, 'NAME', '格林爾夫'),
    ('RACENAME', 509, 'NAME', '古德雷夫'),
    ('RACENAME', 510, 'NAME', '剛涅恩'),
    ('RACENAME', 512, 'NAME', '貢諾爾夫'),
    ('RACENAME', 514, 'NAME', '哈康'),
    ('RACENAME', 515, 'NAME', '哈瓦德'),
    ('RACENAME', 517, 'NAME', '耶爾蒂'),
    ('RACENAME', 518, 'NAME', '赫約雷夫'),
    ('RACENAME', 519, 'NAME', '赫約瓦'),
    ('RACENAME', 522, 'NAME', '雷達爾'),
    ('RACENAME', 523, 'NAME', '赫羅阿爾'),
    ('RACENAME', 524, 'NAME', '英格爾夫'),
    ('RACENAME', 527, 'NAME', '卡爾夫'),
    ('RACENAME', 528, 'NAME', '卡裏'),
    ('RACENAME', 530, 'NAME', '克藍格'),
    ('RACENAME', 532, 'NAME', '科格林'),
    ('RACENAME', 534, 'NAME', '科納爾夫'),
    ('RACENAME', 538, 'NAME', '魯尼爾夫'),
    ('RACENAME', 539, 'NAME', '斯基迪'),
    ('RACENAME', 543, 'NAME', '斯坦莫德'),
    ('RACENAME', 549, 'NAME', '塞蒙德'),
    ('RACENAME', 569, 'NAME', '比約恩松'),
    ('RACENAME', 571, 'NAME', '格林松'),
    ('RACENAME', 583, 'NAME', '赫羅爾夫松'),
    ('RACENAME', 586, 'NAME', '巴爾茲'),
    ('RACENAME', 587, 'NAME', '埃約爾夫松'),
    ('RACENAME', 588, 'NAME', '哈爾多松'),
    ('RACENAME', 591, 'NAME', '西古爾'),
    ('RACENAME', 598, 'NAME', '阿諾爾松'),
    ('RACENAME', 599, 'NAME', '赫羅松'),
    ('RACENAME', 601, 'NAME', '斯坦爾夫松'),
    ('RACENAME', 605, 'NAME', '伯茲瓦松'),
    ('RACENAME', 607, 'NAME', '約倫松'),
    ('RACENAME', 608, 'NAME', '馬松'),
    ('RACENAME', 610, 'NAME', '埃裏克松'),
    ('RACENAME', 614, 'NAME', '奧杜恩松'),
    ('RACENAME', 616, 'NAME', '古德蒙德松'),
    ('RACENAME', 618, 'NAME', '赫約爾松'),
    ('RACENAME', 621, 'NAME', '海丁松'),
    ('RACENAME', 623, 'NAME', '維蒙德松'),
    ('RACENAME', 627, 'NAME', '約恩松'),
    ('RACENAME', 630, 'NAME', '塞維松'),
    ('RACENAME', 636, 'NAME', '艾利夫松'),
    ('RACENAME', 648, 'NAME', '吉斯利松'),
    ('RACENAME', 649, 'NAME', '古德拉松'),
    ('RACENAME', 652, 'NAME', '霍爾姆斯坦松'),
    ('RACENAME', 654, 'NAME', '赫斯科松'),
    ('RACENAME', 661, 'NAME', '阿恩格林松'),
    ('RACENAME', 663, 'NAME', '貝格索松'),
    ('RACENAME', 667, 'NAME', '哈蒙松'),
    ('RACENAME', 668, 'NAME', '霍尼松'),
    ('RACENAME', 669, 'NAME', '卡裏松'),
    ('RACENAME', 681, 'NAME', '布律尼松'),
    ('RACENAME', 682, 'NAME', '伯茲瓦松'),
    ('RACENAME', 683, 'NAME', '伯克松'),
    ('RACENAME', 690, 'NAME', '格林松'),
    ('RACENAME', 691, 'NAME', '古德雷松'),
    ('RACENAME', 692, 'NAME', '剛涅松'),
    ('RACENAME', 694, 'NAME', '貢諾松'),
    ('RACENAME', 696, 'NAME', '哈康松'),
    ('RACENAME', 697, 'NAME', '哈瓦松'),
    ('RACENAME', 700, 'NAME', '赫約雷松'),
    ('RACENAME', 701, 'NAME', '赫約瓦松'),
    ('RACENAME', 704, 'NAME', '雷達松'),
    ('RACENAME', 705, 'NAME', '赫羅松'),
    ('RACENAME', 706, 'NAME', '英格松'),
    ('RACENAME', 709, 'NAME', '卡爾松'),
    ('RACENAME', 710, 'NAME', '卡裏松'),
    ('RACENAME', 712, 'NAME', '克藍松'),
    ('RACENAME', 713, 'NAME', '科德蘭松'),
    ('RACENAME', 714, 'NAME', '科格林松'),
    ('RACENAME', 716, 'NAME', '科納松'),
    ('RACENAME', 717, 'NAME', '莫茲松'),
    ('RACENAME', 720, 'NAME', '魯尼松'),
    ('RACENAME', 721, 'NAME', '斯基松'),
    ('RACENAME', 731, 'NAME', '塞蒙松'),
    # ---- 特殊建筑描述 ----
    ('TECH',    16, 'DESC', '維京騎兵基地'),
    ('TECH_DUP', 16, 'DESC', '維京騎兵基地'),
    ('TECH_DUP', 66, 'DESC', '隱形要塞'),
]


def encode(text, width):
    """把中文编码成字段字节：优先 cp950，编码不出来的字退回自定义字形对。"""
    out = bytearray()
    miss = []
    for ch in text:
        try:
            b = ch.encode('cp950')
        except UnicodeEncodeError:
            pair = FT.pair_for_char(ch) if FT else None
            if pair:
                out += bytes(pair)
            else:
                miss.append(ch)
            continue
        out += b
    if miss:
        raise SystemExit('字体里也没有的字：%r（字段 %s 宽 %d）'
                         % (''.join(miss), text, width))
    if len(out) > width:
        raise SystemExit('超宽：%s = %d 字节 > 字段宽 %d' % (text, len(out), width))
    return bytes(out).ljust(width, b' ')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()

    FT = F.FontTable() if os.path.exists(F.FONTDATA) else None
    raw = {t: open(os.path.join(CHS, 'records', r['file']), 'rb').read()
           for t, r in _idx().items()}
    before = {t: bytes(b) for t, b in raw.items()}

    done = []
    for tname, ridx, fname, text in FIX:
        base = os.path.join(CHS, 'records', _idx()[tname]['file'])
        data = raw[tname]
        fo, rs, rl, n = D.record_layout(data)
        f = next((x for x in fo if x['name'] == fname), None)
        if f is None or ridx >= n:
            print('  跳过 %s#%s（表/记录不存在）' % (tname, ridx))
            continue
        off = rs + ridx * rl + f['off']
        new = encode(text, f['width'])
        raw[tname] = data[:off] + new + data[off + f['width']:]
        done.append((tname, ridx, fname, text))

    # ---- 四项结构校验（改前改后对比）----
    ok = True
    for tname in raw:
        a, b = before[tname], bytes(raw[tname])
        if len(a) != len(b):
            print('  [失败] %s 文件长度变了 %d -> %d' % (tname, len(a), len(b)))
            ok = False
        fa, rs, rl, na = D.record_layout(a)
        fb, _, _, nb = D.record_layout(b)
        if (na, nb) != (None, None) and na != nb:
            print('  [失败] %s 记录数变了 %d -> %d' % (tname, na, nb))
            ok = False
        if any(x['name'] != y['name'] for x, y in zip(fa, fb)):
            print('  [失败] %s 记录名变了' % tname)
            ok = False
        w_a = max((x['off'] + x['width'] for x in fa), default=0)
        w_b = max((x['off'] + x['width'] for x in fb), default=0)
        if w_a != w_b:
            print('  [失败] %s 记录长度变了' % tname)
            ok = False
    print('四项校验：%s' % ('通过' if ok else '未通过'))

    if not args.apply:
        print('干跑 %d 处，未写盘（加 --apply 生效）' % len(done))
        for t, i, f, x in done:
            print('   %s #%-4d %-5s -> %s' % (t, i, f, x))
        return

    if not ok:
        raise SystemExit('校验未过，拒绝写盘')
    for tname in raw:
        open(os.path.join(CHS, 'records', _idx()[tname]['file']), 'wb').write(raw[tname])
    print('已写盘 %d 处：' % len(done))
    for t, i, f, x in done:
        print('   %s #%-4d %-5s -> %s' % (t, i, f, x))


def _idx():
    m = json.load(open(os.path.join(CHS, 'manifest.json'), encoding='utf-8'))
    return {bytes.fromhex(r['name_raw']).rstrip(b'\x00').decode('latin1'): r
            for r in m['records'] if not r.get('sentinel') and r.get('file')}


if __name__ == '__main__':
    main()
