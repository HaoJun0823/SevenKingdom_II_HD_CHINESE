#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""扫描 .text，找「读 Font::first_char(+0x15) / last_char(+0x17)」的指令。

引擎用这两个字段做字符范围检查，再按 7 字节/字符 查 font_info 画点阵。
凡是逐字节用引擎字体画字的例程都会读它们 —— 这就是我们要找的
「绕过 Font::put 的文字路径」的指纹。
"""
import struct
import sys
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

EXE = r'I:\LocalGames\Seven Kingdoms II HD\7K2.exe'
IMAGE_BASE = 0x400000
SECS = []


def load():
    data = open(EXE, 'rb').read()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    coff = pe + 4
    nsec, = struct.unpack_from("<H", data, coff + 2)
    opt_size, = struct.unpack_from("<H", data, coff + 16)
    base = coff + 20 + opt_size
    for i in range(nsec):
        b = base + i * 40
        name = data[b:b + 8].rstrip(b"\0").decode("ascii", "replace")
        vsize, vaddr, rsize, raddr = struct.unpack_from("<IIII", data, b + 8)
        SECS.append((name, vaddr, max(vsize, rsize), raddr, rsize))
    return data


DATA = load()


def va2off(va):
    rva = va - IMAGE_BASE
    for name, vaddr, vsize, raddr, rsize in SECS:
        if vaddr <= rva < vaddr + vsize:
            return raddr + (rva - vaddr)
    return None


def find_func_start(va, back=0x800):
    """向前找函数起点：CC CC 填充后的第一个字节，或 push ebp;mov ebp,esp"""
    off = va2off(va)
    lo = max(va2off(IMAGE_BASE + 0x1000), off - back)
    seg = DATA[lo:off]
    # 从后往前找 int3 填充
    i = len(seg) - 1
    while i >= 1:
        if seg[i - 1] == 0xCC and seg[i] != 0xCC:
            return IMAGE_BASE + 0x1000 + (lo - va2off(IMAGE_BASE + 0x1000)) + i
        i -= 1
    return None


def main():
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = False
    hits = {}
    for name, vaddr, vsize, raddr, rsize in SECS:
        if name != ".text":
            continue
        code = DATA[raddr:raddr + rsize]
        base_va = IMAGE_BASE + vaddr
        # 先粗扫字节指纹：0F B7 ?? 15 / 0F B7 ?? 17
        for i in range(len(code) - 4):
            if code[i] == 0x0F and code[i + 1] == 0xB7 and code[i + 3] in (0x15, 0x17):
                va = base_va + i
                hits.setdefault(va, []).append(code[i + 3])
    print('指纹命中 %d 处' % len(hits))
    # 反汇编每处，确认是 [reg+0x15]/[reg+0x17]
    good = []
    for va in sorted(hits):
        off = va2off(va)
        chunk = DATA[off - 16:off + 24]
        ins = list(md.disasm(chunk, va - 16))
        for x in ins:
            if x.address == va and ('+ 0x15]' in x.op_str or '+ 0x17]' in x.op_str
                                    or '0x15]' in x.op_str or '0x17]' in x.op_str):
                good.append(va)
                break
    print('确认 %d 处' % len(good))
    # 按函数聚合
    funcs = {}
    for va in good:
        fs = find_func_start(va)
        funcs.setdefault(fs, []).append(va)
    print('涉及 %d 个函数：' % len(funcs))
    for fs in sorted(k for k in funcs if k):
        sites = funcs[fs]
        print('  func %08X  (%d 处: %s)' % (fs, len(sites),
              ' '.join('%08X' % s for s in sites[:6])))


if __name__ == '__main__':
    main()
