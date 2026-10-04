#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""反汇编 7K2.exe 里的一段代码（capstone, x86-32）。"""
import struct
import sys
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

EXE = r"I:\LocalGames\Seven Kingdoms II HD\7K2.exe"
IMAGE_BASE = 0x400000
SECS = []          # (rva_start, rva_end, raw_off)


def load():
    data = open(EXE, "rb").read()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    coff = pe + 4
    nsec, = struct.unpack_from("<H", data, coff + 2)
    opt_size, = struct.unpack_from("<H", data, coff + 16)
    opt = coff + 20
    base = opt + opt_size
    for i in range(nsec):
        b = base + i * 40
        name = data[b:b + 8].rstrip(b"\0").decode("ascii", "replace")
        vsize, vaddr, rsize, raddr = struct.unpack_from("<IIII", data, b + 8)
        SECS.append((name, vaddr, max(vsize, rsize), raddr))
    return data


DATA = load()


def va2off(va):
    rva = va - IMAGE_BASE
    for name, vaddr, vsize, raddr in SECS:
        if vaddr <= rva < vaddr + vsize:
            return raddr + (rva - vaddr)
    return None


def main():
    start_va = int(sys.argv[1], 16)
    n = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x120
    off = va2off(start_va)
    if off is None:
        print("地址不在任何节内"); return
    code = DATA[off:off + n]
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = False
    for ins in md.disasm(code, start_va):
        print("%08X  %-24s %-8s %s" % (ins.address, ins.bytes.hex(), ins.mnemonic, ins.op_str))


if __name__ == "__main__":
    main()
