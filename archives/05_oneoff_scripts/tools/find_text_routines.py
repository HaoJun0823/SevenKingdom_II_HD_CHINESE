#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""在 0x602360（活动缓冲 blit）的调用点里，挑出「文字例程」候选。

判据：调用点前面 ~200 字节内出现对 Font 结构的
    +0x15 first_char / +0x17 last_char / +0x19 font_info(7 字节/字)
的读取，或出现 imul ..,7 的 7 字节步长计算。
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


def scan(target):
    hits = []
    for name, vaddr, vsize, raddr, rsize in SECS:
        if name != ".text":
            continue
        lo, hi = raddr, raddr + rsize
        i = lo
        while i < hi - 5:
            if DATA[i] == 0xE8:
                rel, = struct.unpack_from("<i", DATA, i + 1)
                nxt = IMAGE_BASE + vaddr + (i - lo) + 5
                if (nxt + rel) & 0xFFFFFFFF == target:
                    hits.append(IMAGE_BASE + vaddr + (i - lo))
            i += 1
    return hits


def main():
    target = int(sys.argv[1], 16)
    span = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0xC0
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = False
    hits = scan(target)
    print('调用点 %d 个' % len(hits))
    for a in hits:
        off = va2off(a)
        start = a - span
        ctx = DATA[va2off(start):off + 8]
        lines = []
        for ins in md.disasm(ctx, start):
            lines.append(ins)
        text = '\n'.join('    %08X  %-18s %-6s %s' % (x.address, x.bytes.hex(),
                                                     x.mnemonic, x.op_str)
                         for x in lines)
        low = text.lower()
        score = 0
        for key in ('0x19]', '+ 0x19', '0x15]', '+ 0x15', '0x17]', '+ 0x17',
                    ', 7', '0x7,'):
            if key in low:
                score += 1
        if score:
            print('\n==== call @ %08X  score=%d ====' % (a, score))
            print(text)


if __name__ == '__main__':
    main()
