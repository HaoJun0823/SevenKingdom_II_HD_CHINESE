# -*- coding: utf-8 -*-
"""解包 7K2 资源容器。

用法:
  python unpack.py <输入文件> [输出目录]
      -> 把单个文件解包到 输出目录（默认 <输入文件>.unpacked）
  python unpack.py --dir <输入目录> <输出根目录>
      -> 递归遍历 输入目录 下所有文件，分别解包到
         <输出根目录>/<相对路径>.unpacked/

可选:
  --text   额外把文本记录/整体导出为 UTF-8 .txt（cp950 解码，仅便于阅读，
           重新打包仍以 .bin 原字节为准，不影响字节级一致）。
"""
import os
import sys
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import packlib as P


def unpack_file(infile, outdir, as_text):
    m = P.unpack_to_dir(infile, outdir, as_text=as_text)
    print('%-40s -> %-10s recs=%-4s %s' % (
        os.path.basename(infile), m['type'], m.get('count', '-'), outdir))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('input')
    ap.add_argument('output', nargs='?', default=None)
    ap.add_argument('--dir', action='store_true', help='把 input 当作目录递归处理')
    ap.add_argument('--text', action='store_true', help='额外导出 UTF-8 文本预览')
    args = ap.parse_args()

    if args.dir:
        indir = args.input
        outroot = args.output or (indir.rstrip('/\\') + '.unpacked')
        n = 0
        for root, dirs, files in os.walk(indir):
            for f in files:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, indir)
                outdir = os.path.join(outroot, rel + '.unpacked')
                unpack_file(full, outdir, args.text)
                n += 1
        print('\n完成：%d 个文件已解包到 %s' % (n, outroot))
    else:
        infile = args.input
        outdir = args.output or (infile + '.unpacked')
        unpack_file(infile, outdir, args.text)
        print('\n完成：%s' % outdir)


if __name__ == '__main__':
    main()
