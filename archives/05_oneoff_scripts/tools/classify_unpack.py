# -*- coding: utf-8 -*-
"""判定解包目录里哪些 .unpacked 需要入库（含可翻译文本），哪些是纯二进制。

判定规则
--------
* 容器（residx/resource）：**只要 records 里有 >=1 条可当 cp950 解码的文本记录**，
  就整体入库（例如 STD.SET 一半是二进制表、一半是文本，必须整体保留）。
* blob：内容可当 cp950 解码且可打印比例高 -> 入库。
* 其余（wav / 图形 / 字体位图）：排除 —— 它们只是游戏目录原文件的副本，
  体积大且对翻译毫无价值。

用法:
    python classify_unpack.py <解包根目录> [--write-gitignore <目标文件>]
"""
import os
import sys
import json


def texty(b, thresh=0.92):
    if not b or b.count(0) > len(b) * 0.02:
        return False
    try:
        s = b.decode('cp950')
    except Exception:
        return False
    ok = sum(1 for c in s if c.isprintable() or c in '\r\n\t')
    return ok >= len(s) * thresh


def classify(root):
    keep, drop = [], []
    for dirpath, _, fs in os.walk(root):
        if 'manifest.json' not in fs:
            continue
        m = json.load(open(os.path.join(dirpath, 'manifest.json'), encoding='utf-8'))
        rel = os.path.relpath(dirpath, root).replace('\\', '/')
        if rel.endswith('.unpacked'):
            rel = rel[:-len('.unpacked')]
        if m['type'] in ('residx', 'resource'):
            size = 0
            has_text = False
            for rm in m['records']:
                if rm.get('sentinel'):
                    continue
                p = os.path.join(dirpath, 'records', rm['file'])
                size += os.path.getsize(p)
                if not has_text and texty(open(p, 'rb').read()):
                    has_text = True
            (keep if has_text else drop).append((rel, size, m['type']))
        else:
            p = os.path.join(dirpath, m['file'])
            size = os.path.getsize(p)
            (keep if texty(open(p, 'rb').read()) else drop).append((rel, size, 'blob'))
    return keep, drop


def main():
    root = sys.argv[1]
    keep, drop = classify(root)
    ksz = sum(s for _, s, _ in keep)
    dsz = sum(s for _, s, _ in drop)
    print('入库（含文本）%d 个 / %.2f MB' % (len(keep), ksz / 1048576))
    print('排除（纯二进制）%d 个 / %.2f MB' % (len(drop), dsz / 1048576))
    print()
    print('--- 入库清单 ---')
    for r, s, t in sorted(keep):
        print('  %-52s %9d  %s' % (r, s, t))
    print()
    print('--- 排除清单（前 20）---')
    for r, s, t in sorted(drop)[:20]:
        print('  %-52s %9d  %s' % (r, s, t))

    for i, a in enumerate(sys.argv):
        if a == '--write-gitignore' and i + 1 < len(sys.argv):
            with open(sys.argv[i + 1], 'w', encoding='utf-8') as f:
                f.write('# 由 classify_unpack.py 生成：解包产物中纯二进制资产，排除出库\n')
                f.write('# （它们只是游戏目录原文件的副本，可由 pack.py/unpack.py 一键重建）\n')
                for r, s, t in sorted(drop):
                    f.write('%s/\n' % r)
            print('\n排除规则已写入 %s（%d 行）' % (sys.argv[i + 1], len(drop)))


if __name__ == '__main__':
    main()
