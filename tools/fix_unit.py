# -*- coding: utf-8 -*-
"""
翻译 UNIT 表 74 条（建造菜单兵种名 / 单位信息框 / 军事情报列表，之前整表是英文）。

译法（用户 2026-10-05 确认）：**意译为主，音译只用于没有通行译法的专名**。

  * 族名前缀沿用 RACE 表已译名，不新造：
    諾爾曼 / 維京 / 凱爾特 / 羅馬 / 希臘 / 迦太基 / 中國 / 日本 / 蒙古 / 埃及 /
    波斯 / 印度（见 tools/fix_names.py 留下的 RACE 译法）
  * 通用兵种：Civilian 平民 / Infantry 步兵 / Cavalry 騎兵 / Monk 僧侶 /
    Ninja 忍者 / Chriot 戰車 / Axethrower 投斧手 / Mahamatra 戰象
  * 神名意译：大天使 / 雷神 / 戰神 / 雅典娜 / 巴爾哈蒙 / 麒麟 / 天照 /
    騰格里 / 伊西斯 / 密特拉 / 哈奴曼 / 牛頭怪 / 獨角獸 / 豪豬 / 犀牛
  * 没有通行译法的专名（Dagodevas / Kharshuf / Grokken / …）走音译，
    保持与既有译文同一种「用常见字、不新造生僻字」的路线
  * Bregma 与 MONSTER / TECHCLAS 表已译作「蟲族」，这里保持一致

只翻 NAME 字段。RACE / CLASS / 各 ICONNAME 是内部 ID（NO_CIV / CATAPULT 之类），
翻了反而会断，一律不动。NAME 宽 30 字节，够 15 个中文字。

用法:
    python fix_unit.py [--apply]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db_table as D  # noqa: E402
import fix_names as X  # 复用编码与校验（内部按独立函数用）

CHS = r'G:\Projects\SavenKingdom_II_HD_CHINESE\unpack_data_chs\Resource\STD.SET.unpacked'

# (记录下标, 原文, 中文)   —— 以原版英文为锚点，防止行号漂移后改错行
UNIT = [
    (0,  'Norman Civilian',        '諾爾曼平民'),
    (1,  'Norman Infantry',        '諾爾曼步兵'),
    (2,  'Norman Cavalry',         '諾爾曼騎兵'),
    (3,  'Viking Civilian',        '維京平民'),
    (4,  'Viking Infantry',        '維京步兵'),
    (5,  'Viking Axethrower',      '維京投斧手'),
    (6,  'Celt Civilian',          '凱爾特平民'),
    (7,  'Celt Infantry',          '凱爾特步兵'),
    (8,  'Celt Deruvid',           '凱爾特德魯伊'),
    (9,  'Roman Civilian',         '羅馬平民'),
    (10, 'Roman Infantry',         '羅馬步兵'),
    (11, 'Roman Cavalry',          '羅馬騎兵'),
    (12, 'Greek Civilian',         '希臘平民'),
    (13, 'Greek Infantry',         '希臘步兵'),
    (14, 'Greek Cavalry',          '希臘騎兵'),
    (15, 'Carthaginian Civilian',  '迦太基平民'),
    (16, 'Carthaginian Infantry',  '迦太基步兵'),
    (17, 'Carth. Elephant Cavalry', '迦太基戰象騎兵'),
    (18, 'Chinese Civilian',       '中國平民'),
    (19, 'Chinese Infantry',       '中國步兵'),
    (20, 'Chinese Monk',           '中國僧侶'),
    (21, 'Japanese Civilian',      '日本平民'),
    (22, 'Japanese Infantry',      '日本步兵'),
    (23, 'Japanese Ninja',         '日本忍者'),
    (24, 'Mongol Civilian',        '蒙古平民'),
    (25, 'Mongol Infantry',        '蒙古步兵'),
    (26, 'Mongol Cavalry',         '蒙古騎兵'),
    (27, 'Egyptian Civilian',      '埃及平民'),
    (28, 'Egyptian Infantry',      '埃及步兵'),
    (29, 'Egyptian Chriot',        '埃及戰車'),
    (30, 'Persian Civilian',       '波斯平民'),
    (31, 'Persian Infantry',       '波斯步兵'),
    (32, 'Persian Cavalry',        '波斯騎兵'),
    (33, 'Indian Civilian',        '印度平民'),
    (34, 'Indian Infantry',        '印度步兵'),
    (35, 'Indian Mahamatra',       '印度戰象'),
    (36, 'Wagon',                  '馬車'),
    (37, 'Caravan',                '商隊'),
    (38, 'Catapult',               '投石機'),
    (39, 'Ballista',               '弩砲'),
    (40, 'Spitfire',               '噴火器'),
    (41, 'Cannon',                 '火砲'),
    (42, 'Porcupine',              '豪豬'),
    (43, 'Unicorn',                '獨角獸'),
    (44, 'Mega Cannon',            '超級火砲'),
    (45, 'Mega Unicon',            '超級獨角獸'),
    (46, 'Mega Saw',               '超級巨齒獸'),
    (47, 'Nemezez',                '涅墨茲'),
    (48, 'Cobrez',                 '科布萊茲'),
    (49, 'Peltez',                 '佩爾特茲'),
    (50, 'Archangel',              '大天使'),
    (51, 'Thor',                   '雷神'),
    (52, 'Dagodevas',              '達戈德瓦'),
    (53, 'Mars',                   '戰神'),
    (54, 'Athena',                 '雅典娜'),
    (55, 'Baal-Hammon',            '巴爾哈蒙'),
    (56, 'Chi Lin',                '麒麟'),
    (57, 'Amaterasu',              '天照'),
    (58, 'Tengri',                 '騰格里'),
    (59, 'Isis',                   '伊西斯'),
    (60, 'Mithra',                 '密特拉'),
    (61, 'Hanuman',                '哈奴曼'),
    (62, 'Kharshuf',               '卡爾舒夫'),
    (63, 'Bregma',                 '蟲族'),
    (64, 'Kerassos',               '凱拉索斯'),
    (65, 'Minotauros',             '牛頭怪'),
    (66, 'Grokken',                '格羅肯'),
    (67, 'Ezpinez',                '艾茲皮涅茲'),
    (68, 'Exovum',                 '艾克索伍姆'),
    (69, 'Bheema',                 '毗摩'),
    (70, 'Tarmes',                 '塔爾梅斯'),
    (71, 'Jaguara',                '迦瓜拉'),
    (72, 'Goril',                  '大猩猩'),
    (73, 'Rhinokeros',             '犀牛'),
]

ORIG = r'G:\Projects\SavenKingdom_II_HD_CHINESE\unpack_data_original\Resource\STD.SET.unpacked'


def _idx(base):
    m = json.load(open(os.path.join(base, 'manifest.json'), encoding='utf-8'))
    return {bytes.fromhex(r['name_raw']).rstrip(b'\x00').decode('latin1'): r
            for r in m['records'] if not r.get('sentinel') and r.get('file')}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()

    ot = _idx(ORIG)['UNIT']
    ct = _idx(CHS)['UNIT']
    orig = open(os.path.join(ORIG, 'records', ot['file']), 'rb').read()
    cur = open(os.path.join(CHS, 'records', ct['file']), 'rb').read()

    fo, rs, rl, n = D.record_layout(cur)
    f = next(x for x in fo if x['name'] == 'NAME')
    data = bytearray(cur)

    # 1) 行号 / 原文 双重锚点：原版那行对不上就停，绝不错行
    for ridx, expect_en, _ in UNIT:
        _d, _ = D.str_field(orig, rs, rl, ridx, f)
        got = _d.rstrip(b'\x00 ').decode('latin1')
        if got != expect_en:
            raise SystemExit('行号漂移：UNIT #%d 原版是 %r，脚本预期 %r'
                             % (ridx, got, expect_en))

    # 2) 编码 + 写回（只动 NAME 那一段，字段外一个字节都不碰）
    for ridx, _, zh in UNIT:
        off = rs + ridx * rl + f['off']
        new = X.encode(zh, f['width'])
        data[off:off + f['width']] = new

    # 3) 四项结构校验
    check(orig, bytes(data), 'UNIT')
    print('四项校验：通过')

    if not args.apply:
        print('干跑 %d 条，未写盘（加 --apply 生效）' % len(UNIT))
        return
    open(os.path.join(CHS, 'records', ct['file']), 'wb').write(bytes(data))
    print('已写盘 %d 条 UNIT.Name' % len(UNIT))


def check(a, b, tag):
    fa, rs_, rl_, na = D.record_layout(a)
    fb, _, _, nb = D.record_layout(b)
    assert len(a) == len(b), '%s 文件长度变了 %d -> %d' % (tag, len(a), len(b))
    assert na == nb, '%s 记录数变了 %d -> %d' % (tag, na, nb)
    assert [x['name'] for x in fa] == [x['name'] for x in fb], '%s 字段名变了' % tag
    wa = max(x['off'] + x['width'] for x in fa)
    wb = max(x['off'] + x['width'] for x in fb)
    assert wa == wb, '%s 记录长度变了 %d -> %d' % (tag, wa, wb)


if __name__ == '__main__':
    main()
