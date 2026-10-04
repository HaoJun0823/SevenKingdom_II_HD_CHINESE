# -*- coding: utf-8 -*-
"""检查 .res 文本资源「条目序号是否与原版对齐」。

为什么关键
----------
引擎取值走的是 `TextResource::get_format_str(textId, checkMark)`：
    process( get_format_str( 20, "DUHM" ), hours, minutes );
textId 是**序号**（1-based，第 20 条），checkMark 只在找不到时报错用。
所以只要汉化时多一条、少一条、或换了顺序，**后面所有条目全部错位** ——
表现就是「某个界面显示了别的界面的文本」或「数字/单位丢失」。

用法
----
    python check_res_align.py                 # 检查 update\Resource 下全部 .res
    python check_res_align.py t_reps.res      # 只查指定文件
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
GAME = r'I:\LocalGames\Seven Kingdoms II HD'

ORIG = os.path.join(GAME, 'Resource')                 # 原版（英文）
CUR  = os.path.join(GAME, 'update', 'Resource')       # 部署的汉化版


def read_entries(path):
    """按行切条目：以 '[' 开头的行算一条。返回 (键, 整行) 列表。"""
    d = open(path, 'rb').read()
    out = []
    for ln in d.replace(b'\r\n', b'\n').split(b'\n'):
        if ln.startswith(b'['):
            r = ln.find(b']')
            key = ln[:r + 1] if r >= 0 else ln
            out.append((key, ln))
    return out


def dec(b):
    return b.decode('cp950', 'replace')


def check(name):
    po = os.path.join(ORIG, name)
    pc = os.path.join(CUR, name)
    if not os.path.exists(po) or not os.path.exists(pc):
        return None
    a = read_entries(po)
    b = read_entries(pc)
    print('### %s   原版 %d 条 / 汉化 %d 条' % (name, len(a), len(b)))
    if len(a) != len(b):
        print('    [!!] 条目数不一致 —— 必然整体错位')

    bad = []
    for i in range(min(len(a), len(b))):
        if a[i][0] != b[i][0]:
            bad.append((i + 1, a[i][0], b[i][0]))
    if bad:
        print('    [!!] 首次错位在 第 %d 条：原版 %s / 汉化 %s'
              % (bad[0][0], dec(bad[0][1]), dec(bad[0][2])))
        print('         共 %d 处键不符' % len(bad))
        for r in bad[:8]:
            print('           第%3d条  原 %-14s 汉 %-14s'
                  % (r[0], dec(r[1]), dec(r[2])))
    else:
        print('    [OK] 全部条目序号对齐')

    # 顺带列出格式骨架有差异的条目（占位符数量/类型对不上）
    import re
    pat = re.compile(rb'%(\d)(?:,(\d))?([a-z%?])')
    for i in range(min(len(a), len(b))):
        so = sorted(pat.findall(a[i][1]))
        sc = sorted(pat.findall(b[i][1]))
        if so != sc:
            print('    [%s] 第%d条 %s  格式码 %s -> %s'
                  % ('!!' if len(so) != len(sc) else '~', i + 1,
                     dec(b[i][0]), so, sc))
    print()
    return bad


def main():
    if len(sys.argv) > 1:
        names = sys.argv[1:]
    else:
        names = sorted(f for f in os.listdir(CUR) if f.lower().endswith('.res'))
    total_bad = 0
    for nm in names:
        r = check(nm)
        if r:
            total_bad += len(r)
    print('==== 合计错位 %d 处 ====' % total_bad)


if __name__ == '__main__':
    main()
