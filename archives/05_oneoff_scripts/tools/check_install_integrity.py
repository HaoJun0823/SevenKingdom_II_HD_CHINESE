# -*- coding: utf-8 -*-
"""用 GOG 自带的 hashdb 校验游戏安装是否完整。

用法: python check_install_integrity.py [游戏目录]
"""
import zipfile, re, os, sys, hashlib, struct

GAME = sys.argv[1] if len(sys.argv) > 1 else r'I:\LocalGames\Seven Kingdoms II HD'
HDB = os.path.join(GAME, 'goggame-1207658723.hashdb')


def load_ref(path):
    """hashdb 记录布局（实测）：12 字节头 + 每条 **1056** 字节
       [ name: 1024 字节, NUL 填充 ][ md5: 32 字节 ASCII ]
       校验: (len(d) - 12) / 1056 == 头部第 3 个 u32（=745）
    """
    z = zipfile.ZipFile(path)
    d = z.read(z.namelist()[0])
    magic, ver, nrec = struct.unpack_from('<III', d, 0)
    assert (len(d) - 12) % 1056 == 0, '记录长度异常'
    n = (len(d) - 12) // 1056
    assert n == nrec, '记录数不符: 头部 %d vs 实际 %d' % (nrec, n)
    recs = {}
    for i in range(n):
        o = 12 + i * 1056
        nm = d[o:o + 1024].split(b'\x00')[0].decode('latin-1').replace('\\', '/')
        md5 = d[o + 1024:o + 1056].decode('latin-1')
        if nm:
            recs[nm] = md5
    return recs


def md5_of(p):
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    ref = load_ref(HDB)
    bad, missing, ok = [], [], 0
    for rel, want in sorted(ref.items()):
        p = os.path.join(GAME, rel.replace('/', os.sep))
        if not os.path.isfile(p):
            missing.append(rel)
            continue
        got = md5_of(p)
        if got.lower() == want.lower():
            ok += 1
        else:
            bad.append(rel)
    print('条目 %d   一致 %d   **不一致 %d**   缺失 %d' % (len(ref), ok, len(bad), len(missing)))
    for r in bad:
        print('  [损坏] %s' % r)
    for r in missing:
        print('  [缺失] %s' % r)


if __name__ == '__main__':
    main()
