# -*- coding: utf-8 -*-
"""对「会被引擎 OEM 转换」的 .res 资源做写盘形态预补偿。

== 背景 ==
引擎读某些资源（已确证：STD.SET、tut_list.res）时，会把每个 >=0x80 的字节
过一张 cp437(OEM) -> Latin-1(ANSI) 的映射表（`7K2.exe` @ 0x27F028）：

    apply(b) = T[b] if (b >= 0x80 and T[b] != 0x3F) else b

`0x3F` 是「该 OEM 字符在 Latin-1 里没有对应」的标记 —— 引擎遇到它就**保留原值**。

== 双赢编码 ==
为了让同一份字节在「过表」和「不过表」两种加载路径下都显示正确，
优先选择**稳定字节**（T[b] == 0x3F，过表后不变）：
  * 显示形态 D 若全由稳定字节/低位组成 -> 直接写 D，两条路径都对；
  * 否则写 inv_apply(D)（找 s 使 apply(s)=D），只在过表路径下正确。

== 处理粒度 ==
只动「双字节对」：
  * 自定义对 (lead 0x90-0xA0, trail 0x40-0x7E) -> 解出字符 -> 标准 Big5
  * 标准 Big5 对 (lead 0xA1-0xF9)              -> 逐字节 inv_apply
其余字节（ASCII 标签、二进制字段）原样保留。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from fontlib import FontTable                      # noqa: E402
from gen_stdmap import T, enc_std                  # noqa: E402

STABLE = {b for b in range(0x80, 0x100) if T[b] == 0x3F}
_BAD_TRAILS = {0x5B, 0x5D, 0x7B, 0x7C, 0x7D, 0x7E, 0x7F}
_CUST_MIN, _CUST_N = 0x90, 17
_B5_MIN, _B5_MAX = 0xA1, 0xF9


def is_stable(b):
    return b < 0x80 or b in STABLE


def inv_apply(b):
    """找写盘字节 s，使 apply(s) == b。不可达返回 None。"""
    if b < 0x80:
        return b
    if T[b] == 0x3F:          # b 本身过表不变
        return b
    for s in range(0x80, 0x100):
        if T[s] == b:
            return s
    return None


def _is_cust_pair(b1, b2):
    return _CUST_MIN <= b1 < _CUST_MIN + _CUST_N and 0x40 <= b2 <= 0x7E


def _is_std_pair(b1, b2):
    return _B5_MIN <= b1 <= _B5_MAX and (0x40 <= b2 <= 0x7E or 0xA1 <= b2 <= 0xFE)


def encode_display(b1, b2, ft):
    """把「显示形态」的双字节对转成写盘字节；无法处理返回 None（保持原样）"""
    if _is_cust_pair(b1, b2):
        g = ft.pair2glyph.get((b1, b2))
        ch = ft.glyph2char.get(g) if g is not None else None
        if not ch:
            return None
        std = enc_std(ch)
        if std is None:
            return None
        b1, b2 = std
    p1 = inv_apply(b1)
    p2 = inv_apply(b2)
    if p1 is None or p2 is None:
        return None
    return bytes((p1, p2))


def convert(data, ft, verbose=False):
    out = bytearray(data)
    n = len(data)
    i = 0
    stat = {'cust': 0, 'std': 0, 'skip': 0}
    changes = []
    while i < n - 1:
        b1, b2 = data[i], data[i + 1]
        if _is_cust_pair(b1, b2) or _is_std_pair(b1, b2):
            rep = encode_display(b1, b2, ft)
            if rep is None:
                stat['skip'] += 1
            elif rep != bytes((b1, b2)):
                out[i:i + 2] = rep
                if _is_cust_pair(b1, b2):
                    stat['cust'] += 1
                else:
                    stat['std'] += 1
                changes.append((i, bytes((b1, b2)), rep))
            i += 2
            continue
        i += 1
    return bytes(out), stat, changes


def main():
    if len(sys.argv) < 2:
        print('usage: fix_res.py <file.res> [more...]  [--dry]')
        return 1
    dry = '--dry' in sys.argv
    ft = FontTable()
    for path in [a for a in sys.argv[1:] if not a.startswith('--')]:
        data = open(path, 'rb').read()
        newv, stat, changes = convert(data, ft)
        print('== %s  (%d 字节) ==' % (os.path.basename(path), len(data)))
        print('   自定义对改写 %d, 标准对预补偿 %d, 无法处理 %d'
              % (stat['cust'], stat['std'], stat['skip']))
        for (o, a, b) in changes[:16]:
            try:
                sa = a.decode('cp950')
            except Exception:
                sa = a.hex(' ')
            try:
                sb = b.decode('cp950')
            except Exception:
                sb = b.hex(' ')
            print('     @0x%04X  %-14s -> %s' % (o, sa if sa.strip() else a.hex(' '), b.hex(' ')))
        if len(changes) > 16:
            print('     ... 共 %d 处' % len(changes))
        if not dry:
            # 只改动了「双字节对」，长度必定不变
            assert len(newv) == len(data), 'length changed!'
            bail = path + '.orig'
            if not os.path.exists(bail):
                open(bail, 'wb').write(data)
                print('   已备份 -> %s' % bail)
            open(path, 'wb').write(newv)
            print('   已写回')
    return 0


if __name__ == '__main__':
    sys.exit(main())
