# -*- coding: utf-8 -*-
"""打包 7K2 资源容器（与 unpack.py 配对）。

用法:
  python pack.py <解包目录> [输出文件]
      -> 把单个解包目录重组为 输出文件（默认 <解包目录 去 .unpacked>/<原名>）
  python pack.py --dir <解包根目录> <输出根目录>
      -> 遍历 解包根目录 下所有 *.unpacked 目录，分别打包到
         <输出根目录>/<相对路径>（保留原名）。

重建严格依据 manifest.json，保证字节级一致（不含任何文本重编码）。
"""
import os
import sys
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import packlib as P


def pack_dir(outdir, outfile):
    buf = P.pack_from_dir(outdir)
    os.makedirs(os.path.dirname(outfile) or '.', exist_ok=True)
    open(outfile, 'wb').write(buf)
    print('%-44s -> %s (%d B)' % (outdir, outfile, len(buf)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('input')
    ap.add_argument('output', nargs='?', default=None)
    ap.add_argument('--dir', action='store_true', help='把 input 当作解包根目录递归处理')
    args = ap.parse_args()

    if args.dir:
        indir = args.input
        outroot = args.output or indir
        n = 0
        for root, dirs, files in os.walk(indir):
            if 'manifest.json' in files and root.endswith('.unpacked'):
                rel = os.path.relpath(root, indir)
                # 还原原名：去掉尾部的 .unpacked
                base_rel = rel[:-len('.unpacked')] if rel.endswith('.unpacked') else rel
                outfile = os.path.join(outroot, base_rel)
                pack_dir(root, outfile)
                n += 1
        print('\n完成：%d 个目录已打包到 %s' % (n, outroot))
    else:
        outdir = args.input
        if args.output:
            outfile = args.output
        else:
            # 默认：<parent>/<name without .unpacked>
            parent = os.path.dirname(outdir)
            name = os.path.basename(outdir)
            if name.endswith('.unpacked'):
                name = name[:-len('.unpacked')]
            outfile = os.path.join(parent, name)
        pack_dir(outdir, outfile)
        print('\n完成：%s' % outfile)


if __name__ == '__main__':
    main()
