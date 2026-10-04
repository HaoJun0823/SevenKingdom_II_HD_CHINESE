#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""暴力扫描 7K2.exe 里所有 call rel32 到指定 VA 的调用点（不依赖反汇编连续性）。"""
import struct
import sys
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

EXE = r"I:\LocalGames\Seven Kingdoms II HD\7K2.exe"
IMAGE_BASE = 0x400000
SECS = []


def load():
    data = open(EXE, "rb").read()
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
        base_va = IMAGE_BASE + vaddr
        i = lo
        end = hi - 5
        while i < end:
            if DATA[i] == 0xE8:
                rel, = struct.unpack_from("<i", DATA, i + 1)
                nxt = base_va + (i - lo) + 5
                dst = (nxt + rel) & 0xFFFFFFFF
                if dst == target:
                    hits.append(base_va + (i - lo))
            i += 1
    return hits


def main():
    target = int(sys.argv[1], 16)
    hits = scan(target)
    print("call 0x%X 的调用点: %d 处" % (target, len(hits)))
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = False
    for a in hits:
        off = va2off(a)
        print("\n---- call @ %08X ----" % a)
        ctx = DATA[off - 20:off + 8]
        for ins in md.disasm(ctx, a - 20):
            mark = "  >>" if ins.address == a else "    "
            print("%s %08X  %-20s %-6s %s" % (mark, ins.address, ins.bytes.hex(),
                                              ins.mnemonic, ins.op_str))


if __name__ == "__main__":
    main()
