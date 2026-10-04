# -*- coding: utf-8 -*-
"""修复 STD.SET 里漏译的建筑/建筑单位名（繁体）。

问题
----
汉化时只翻了 TECH 表，同名的其它 6 张表（FBUILD / FBUILD2 / FDBUILD /
FDBUILD2 / FIRM / TECH_DUP）整片漏掉了 —— 游戏里表现为建造菜单出现
`IMMORTAL'S ACADEMY` 这种英文。

做法
----
精确名字映射 + **等长替换**：
  找到英文名 → 一直吃到它后面的连续空格（这就是原字段的宽度）→
  用「中文 + 空格填充」替换成同样长度。
这样记录总长、后续偏移、二进制字段全都不动，pack 回去不会碰坏任何东西。

译名依据
--------
* 前 12 个国家专属建筑：直接取自汉化版 TECH 表里**已有的译名**，保证一致；
* Kharshuf/Bregma/Kerassos/Minotauros/Grokken/Ezpinez/Exovum：7k2-master 源码
  oitemres.cpp 里它们是怪物名（有对应的 "XXX's Bane" 猎杀魔法书），故取音译 + 巢穴；
* Tarmes 是拉丁语「白蚁」、Mownd 是 mound 变体拼写 -> 白蟻丘；
* Tor = tower 的变体拼写 -> 塔；Lishorr 见 ofirm.cpp 属蜥蜴人种族。

用法
----
    python fix_stdset_names.py            # 干跑，只报告
    python fix_stdset_names.py --apply    # 写回（自动备份到 res_backup/）
"""
import os
import re
import sys
import json
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
BACKUP = os.path.join(PROJ, 'res_backup')

# 目标解包目录（chs 工作区 = 原版结构 + 现有译文）
ROOT = os.path.join(PROJ, 'unpack_data_chs', 'Resource', 'STD.SET.unpacked')

# 只在这些记录里替换（都含漏译的建筑名）
TARGET_RECS = {'FIRM', 'FIRM2', 'FBUILD', 'FBUILD2', 'FDBUILD', 'FDBUILD2', 'TECH', 'TECH_DUP'}

# 英文名 -> 繁体译名。★ 长名必须排在短名之前（先匹配长的，避免被部分吃掉）
NAMES = [
    # —— 前 12 个国家专属建筑：沿用汉化 TECH 里既有译名 ——
    ("Norman Estable",              "日爾曼騎兵基地"),
    ("Viking ksehus",               "維京騎兵基地"),
    ("Celtic Sacred Grove",         "凱爾特修道"),
    ("Roman Schola Equitatus",      "羅馬騎兵基地"),
    ("Greek Akademia Ippiku",       "希臘騎兵基地"),
    ("Carthaginian Elephant Training", "太基象兵基地"),
    ("Chinese Shao Lin Temple",     "中國少林寺"),
    ("Japanese Ninja Dojo",         "日本忍者學"),
    ("Mongol Naadam Field",         "蒙古騎兵基地"),
    ("Egyptian Chariot At'Saba",    "埃及車兵基地"),
    ("Persian Immortal's Academy",  "波斯騎兵基地"),
    ("Indian Kheddha",              "印度象兵基地"),
    # —— 不带国家前缀的形式（FBUILD 那一族里就是这么存的）——
    ("Estable",                     "日爾曼騎兵基地"),
    ("ksehus",                      "維京騎兵基地"),
    ("Sacred Grove",                "凱爾特修道"),
    ("Schola Equitatus",            "羅馬騎兵基地"),
    ("Akademia Ippiku",             "希臘騎兵基地"),
    ("Elephant Training",           "太基象兵基地"),
    ("Shao Lin Temple",             "中國少林寺"),
    ("Ninja Dojo",                  "日本忍者學"),
    ("Naadam Field",                "蒙古騎兵基地"),
    ("Chariot At'Saba",             "埃及車兵基地"),
    ("Immortal's Academy",          "波斯騎兵基地"),
    ("Kheddha",                     "印度象兵基地"),
    # —— 怪物巢穴 / 特殊建筑（源码 oitemres.cpp 证实为怪物名）——
    ("Kharshuf Lair",               "卡舒夫巢穴"),
    ("Bregma Lair",                 "布雷格馬巢穴"),
    ("Kerassos Lair",               "克拉索斯巢穴"),
    ("Minotauros Lair",             "米諾陶巢穴"),
    ("Grokken Lair",                "格羅肯巢穴"),
    ("Ezpinez Lair",                "埃茲皮內茲巢穴"),
    ("Exovum Lair",                 "埃克索姆巢穴"),
    ("Wilde Lishorr",               "野生利修爾"),
    ("Lishorr",                     "利修爾"),
    ("Bheema Hyfe",                 "比瑪蜂巢"),
    ("Tarmes Mownd",                "白蟻丘"),
    ("Alchemist Tor",               "煉金術士塔"),
    ("Mage Tor",                    "法師塔"),
    ("Fortress",                    "要塞"),
    ("Vapngart",                    "瓦普加特"),
    ("Keraal",                      "克拉爾"),
    ("Teledamunm",                  "特雷達蒙"),
    ("Preuser",                     "普雷澤"),
    ("Testudo",                     "龜甲堡"),
    ("Archimedetron",               "阿基米德器械"),
    # —— 单独出现的短名（FIRM/TECH 里 "<中文短名>  <英文长名>" 这种双字段）——
    #    必须排在 Bheema Hyfe / Tarmes Mownd 之后
    ("Hyfe",                        "蜂巢"),
    ("Mownd",                       "蟻丘"),
    # —— 清理汉化时「按词替换」留下的残留英文 ——
    #    TECH 表里翻译不彻底，成了「中文名 + 残留英文」：
    #      凱爾特修道 Grove / 中國少林寺 Lin Temple / 波斯騎兵基地 's Academy
    #    这里把残留部分抹成空格（字段宽度不变）。
    ("Lin Temple",                  ""),
    ("'s Academy",                  ""),
    ("At'Saba",                     ""),
    ("Grove",                       ""),
    ("Dojo",                        ""),
]


def recs(root):
    m = json.load(open(os.path.join(root, 'manifest.json'), encoding='utf-8'))
    out = []
    for rec in m['records']:
        if rec.get('sentinel'):
            continue
        nm = bytes.fromhex(rec['name_raw']).rstrip(b'\x00').decode('latin1')
        out.append((rec['index'], nm, os.path.join(root, 'records', rec['file'])))
    return out


def fix_one(b, only):
    """对记录字节做等长替换，返回 (新字节, [(英文, 中文, 位置, span)])"""
    out = bytearray(b)
    done = []
    for en, zh in NAMES:
        if only and en not in only:
            continue
        e = en.encode('latin1')
        z = zh.encode('cp950')
        i = 0
        while True:
            i = bytes(out).find(e, i)
            if i < 0:
                break
            # span = 名字 + 紧跟的连续空格（原字段宽度）
            j = i + len(e)
            while j < len(out) and out[j] == 0x20:
                j += 1
            span = j - i
            if len(z) > span:
                print('   [!!] 放不下: %s(%d) -> %s(%d) span=%d' % (en, len(e), zh, len(z), span))
                i = j
                continue
            out[i:j] = z + b' ' * (span - len(z))
            done.append((en, zh, i, span))
            i += span
    return bytes(out), done


def main():
    apply = '--apply' in sys.argv
    only = None
    for a in sys.argv:
        if a.startswith('--only='):
            only = set(a[7:].split(','))
    total = 0
    for idx, nm, path in recs(ROOT):
        if nm not in TARGET_RECS:
            continue
        b = open(path, 'rb').read()
        new, done = fix_one(b, only)
        if not done:
            continue
        print('#%-3d %-10s 替换 %d 处' % (idx, nm, len(done)))
        seen = set()
        for en, zh, off, span in done:
            if en in seen:
                continue
            seen.add(en)
            print('     @%-6d %-30s -> %-12s (span=%d)' % (off, en, zh, span))
        total += len(done)
        if apply:
            os.makedirs(BACKUP, exist_ok=True)
            bak = os.path.join(BACKUP, 'STD.SET_chs_%s.bin' % nm)
            if not os.path.exists(bak):
                shutil.copy2(path, bak)
            open(path, 'wb').write(new)
    print()
    print('合计替换 %d 处%s' % (total, '（已写回）' if apply else '（干跑，未写回）'))


if __name__ == '__main__':
    main()
