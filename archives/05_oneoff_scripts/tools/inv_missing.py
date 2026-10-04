# -*- coding: utf-8 -*-
"""盘点汉化缺口：把英文原版资源与我们已投放的中文资源逐 tag 比对。

输出：
  1) 完全缺失的文件（我们没翻译）
  2) 已有文件中「仍是英文 / 缺 tag」的条目清单
  3) 纯文本文件（.sct）的中英文比例
用法： python inv_missing.py [--dump-missing]
"""
import os, re, sys, json

GAME = r'I:\LocalGames\Seven Kingdoms II HD'
OURS = r'G:\Projects\SavenKingdom_II_HD_CHINESE\update_res_staged'

TAG = re.compile(rb'\[([^\[\]\r\n]{1,40})\]')

# 文本类候选（相对游戏根目录）
TAGGED = [
    ('Resource', 't_basic.res'), ('Resource', 't_camp.res'), ('Resource', 't_endc.res'),
    ('Resource', 't_firm.res'), ('Resource', 't_gmenu.res'), ('Resource', 't_item.res'),
    ('Resource', 't_news.res'), ('Resource', 't_reps.res'), ('Resource', 't_sedit.res'),
    ('Resource', 't_talk.res'), ('Resource', 't_tutor.res'), ('Resource', 't_unit.res'),
    ('Resource', 'tips.res'), ('Resource', 'help.res'),
    ('Resource', 'TUT_TEXT.RES'), ('Resource', 'TUT_INTR.RES'),
    ('Resource', 'CPG_INTR.RES'), ('Resource', 'INTROTXT.RES'), ('Resource', 'CREDIT.RES'),
    ('Resource', 'HOTKEY.RES'), ('Resource', 'tut_list.res'),
    ('Campaign', 'INTROTXT.RES'),
]
PLAIN = [
    ('Scenario/Premade', 'Isis.sct'), ('Scenario/Premade', 'Jaws.sct'),
    ('Scenario/Premade', 'Lishorrs.sct'), ('Scenario/Premade', 'Rome.sct'),
    ('Scenario/Premade', 'Plasma.sct'), ('Scenario/Premade', 'gallic.sct'),
    ('Scenario/Premade', 'hashshas.sct'), ('Scenario/Premade', 'los_trib.sct'),
    ('Scenario/Premade', 'mong_hor.sct'),
]
IDX = [  # ResourceIdx 容器（含文本块）
    ('Campaign', 'EAST.STG'), ('Campaign', 'EAST.EVT'), ('Campaign', 'EAST.PLT'),
    ('Campaign', 'EAST.TXR'), ('Campaign', 'EAST.DLG'),
    ('Campaign', 'tutorial.stg'), ('Campaign', 'tutorial.evt'),
]


def cjk_count(b):
    s = b.decode('cp950', errors='replace')
    return sum(1 for c in s if '\u4e00' <= c <= '\u9fff')


def alpha_runs(b):
    """英文单词串（>=3 字母）计数"""
    return len(re.findall(rb'[A-Za-z][A-Za-z\'\- ]{2,}', b))


def tags_of(path):
    d = open(path, 'rb').read()
    out = {}
    for m in TAG.finditer(d):
        nm = TAG.search(d, m.end())
        end = nm.start() if nm else len(d)
        out[m.group(1).decode('latin-1')] = d[m.end():end].rstrip(b'\r\n')
    return out, d


def ours_path(rel_dir, name):
    """在我们的资源里按不区分大小写查找"""
    d = os.path.join(OURS, rel_dir)
    if not os.path.isdir(d):
        return None
    for f in os.listdir(d):
        if f.lower() == name.lower():
            return os.path.join(d, f)
    return None


def main():
    dump = '--dump-missing' in sys.argv
    print('=' * 78)
    print('一、tag 型资源比对')
    print('=' * 78)
    missing_files, eng_entries = [], []
    for rel_dir, name in TAGGED:
        gp = os.path.join(GAME, rel_dir, name)
        if not os.path.exists(gp):
            print('  [游戏无此文件] %s/%s' % (rel_dir, name))
            continue
        op = ours_path(rel_dir, name)
        gt, gd = tags_of(gp)
        if not op:
            print('  ★整文件缺失  %-28s 原版 %d 个 tag' % (rel_dir + '/' + name, len(gt)))
            missing_files.append((rel_dir, name, len(gt)))
            continue
        ot, od = tags_of(op)
        notr = []
        for k, v in gt.items():
            if k not in ot:
                notr.append((k, v))
            elif cjk_count(ot[k]) == 0 and alpha_runs(v) > 0:
                notr.append((k, v))
        print('  %-28s 原 %3d / 我 %3d  tag，未译 %3d' %
              (rel_dir + '/' + name, len(gt), len(ot), len(notr)))
        for k, v in notr:
            eng_entries.append((rel_dir + '/' + name, k, v))

    print()
    print('=' * 78)
    print('二、纯文本 .sct 比对')
    print('=' * 78)
    for rel_dir, name in PLAIN:
        gp = os.path.join(GAME, rel_dir, name)
        op = ours_path(rel_dir, name)
        if not os.path.exists(gp):
            continue
        gb = open(gp, 'rb').read()
        ob = open(op, 'rb').read() if op else b''
        print('  %-28s 原: cjk=%-5d 英文串=%-4d | 我: cjk=%-5d 英文串=%-4d %s' %
              (name, cjk_count(gb), alpha_runs(gb), cjk_count(ob), alpha_runs(ob),
               '' if ob else '★缺失'))

    print()
    print('=' * 78)
    print('三、ResourceIdx 容器比对（文本块）')
    print('=' * 78)
    for rel_dir, name in IDX:
        gp = os.path.join(GAME, rel_dir, name)
        op = ours_path(rel_dir, name)
        if not os.path.exists(gp):
            print('  [游戏无此文件] %s/%s' % (rel_dir, name))
            continue
        gb = open(gp, 'rb').read()
        ob = open(op, 'rb').read() if op else b''
        print('  %-28s 原: cjk=%-5d 英文串=%-4d | 我: cjk=%-5d 英文串=%-4d %s' %
              (name, cjk_count(gb), alpha_runs(gb), cjk_count(ob), alpha_runs(ob),
               '★缺失' if not ob else ''))

    print()
    print('=' * 78)
    print('四、Tutorial/*.tut')
    print('=' * 78)
    td = os.path.join(GAME, 'Tutorial')
    if os.path.isdir(td):
        for f in sorted(os.listdir(td)):
            b = open(os.path.join(td, f), 'rb').read()
            print('  %-16s cjk=%-5d 英文串=%-4d size=%d' % (f, cjk_count(b), alpha_runs(b), len(b)))

    print()
    print('=' * 78)
    print('五、未译 tag 明细：%d 条' % len(eng_entries))
    print('=' * 78)
    for src, k, v in eng_entries[:400 if dump else 60]:
        try:
            t = v.decode('cp950', errors='replace').replace('\r', ' ').replace('\n', ' ')
        except Exception:
            t = repr(v[:60])
        print('  [%s] %s = %s' % (src, k, t[:100]))
    if not dump and len(eng_entries) > 60:
        print('  ...（共 %d 条，加 --dump-missing 看全部）' % len(eng_entries))

    json.dump([{'file': s, 'tag': k, 'text': v.decode('cp950', errors='replace')}
               for s, k, v in eng_entries],
              open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'missing.json'),
                   'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print()
    print('明细已写入 tools/missing.json')


if __name__ == '__main__':
    main()
