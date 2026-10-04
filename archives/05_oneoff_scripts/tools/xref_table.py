#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
离线扫描 7K2.exe，找所有引用 cp437->Latin1 转换表 (VA 0x67F028) 的位置。
表的绝对地址作为 32 位立即数出现在指令里，通常是:
    mov   al, byte_67F028[ecx]      -> 8A 81 28 F0 67 00
    movzx eax, byte_67F028[ebx]     -> 0F B6 83 28 F0 67 00
    cmp   byte_67F028[eax], 0x3F    -> 80 B8 28 F0 67 00 3F
    mov   ecx, offset byte_67F028   -> B9 28 F0 67 00
所以只要搜 "28 F0 67 00" 这 4 个字节即可。
"""
import struct
import sys

EXE = r"I:\LocalGames\Seven Kingdoms II HD\7K2.exe"
IMAGE_BASE = 0x400000
IMAGE_END = IMAGE_BASE + 0x2000
for _va in (0x681028, 0x67F028):
    pass
TABLE_VA = 0x681028
PATTERN = struct.pack("<I", TABLE_VA)


def main():
    data = open(EXE, "rb").read()
    if data[:2] != b"MZ":
        print("not a PE")
        return
    pe_off = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe_off:pe_off + 4] != b"PE\0\0":
        print("bad PE sig")
        return
    coff = pe_off + 4
    nsec, = struct.unpack_from("<H", data, coff + 2)
    opt_size, = struct.unpack_from("<H", data, coff + 16)
    opt = coff + 20
    nsec_off = opt + opt_size

    secs = []
    for i in range(nsec):
        base = nsec_off + i * 40
        name = data[base:base + 8].rstrip(b"\0").decode("ascii", "replace")
        vsize, vaddr, rsize, raddr = struct.unpack_from("<IIII", data, base + 8)
        chars, = struct.unpack_from("<I", data, base + 36)
        secs.append((name, vaddr, vsize, raddr, rsize, chars))
        print("sec %-8s VA=%08X VS=%08X RA=%08X RS=%08X flags=%08X"
              % (name, IMAGE_BASE + vaddr, vsize, raddr, rsize, chars))

    def va2off(va):
        rva = va - IMAGE_BASE
        for name, vaddr, vsize, raddr, rsize, _ in secs:
            if vaddr <= rva < vaddr + max(vsize, rsize):
                return raddr + (rva - vaddr)
        return None

    def off2va(off):
        for name, vaddr, vsize, raddr, rsize, _ in secs:
            if raddr <= off < raddr + rsize:
                return IMAGE_BASE + vaddr + (off - raddr)
        return None

    # 确认表内容
    toff = va2off(TABLE_VA)
    print("\n表 文件偏移 = 0x%X" % toff)
    print("表前 32 字节:", data[toff:toff + 32].hex(" ").upper())
    print("表 128..160 :", data[toff + 128:toff + 160].hex(" ").upper())

    hits = []
    pos = data.find(PATTERN)
    while pos != -1:
        hits.append(pos)
        pos = data.find(PATTERN, pos + 1)
    print("\n立即数命中 %d 处:" % len(hits))
    for off in hits:
        va = off2va(off)
        # 打印上下文：从 off-8 开始的 16 字节
        lo = max(0, off - 8)
        ctx = data[lo:off + 8]
        print("  VA=%08X  off=0x%06X  ... %s | %s | %s"
              % (va, off,
                 ctx[:8].hex(" ").upper(),
                 data[off:off + 4].hex(" ").upper(),
                 data[off + 4:off + 8].hex(" ").upper()))


if __name__ == "__main__":
    main()
