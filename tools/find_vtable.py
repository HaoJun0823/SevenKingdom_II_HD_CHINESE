#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""在 exe 的数据区里找出包含已知 Font 方法指针的虚表，并把整表打印出来。"""
import struct
import sys

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


def off2va(off):
    for name, vaddr, vsize, raddr, rsize in SECS:
        if raddr <= off < raddr + rsize:
            return IMAGE_BASE + vaddr + (off - raddr)
    return None


def va2off(va):
    rva = va - IMAGE_BASE
    for name, vaddr, vsize, raddr, rsize in SECS:
        if vaddr <= rva < vaddr + vsize:
            return raddr + (rva - vaddr)
    return None


KNOWN = {
    0x4C0780: 'text_width',
    0x4C0AE0: 'put',
    0x4C0FE0: 'put_char',
    0x4C1140: 'center_put',
    0x4C1480: 'put_paragraph',
}


def main():
    targets = [int(a, 16) for a in (sys.argv[1:] or
               ['4C0780', '4C0AE0', '4C0FE0', '4C1140', '4C1480'])]
    for t in targets:
        pat = struct.pack('<I', t)
        offs = []
        i = DATA.find(pat)
        while i != -1:
            offs.append(i)
            i = DATA.find(pat, i + 1)
        print('\n#### %08X (%s) 出现 %d 次' % (t, KNOWN.get(t, '?'), len(offs)))
        for off in offs:
            va = off2va(off)
            if va is None:
                continue
            rva = va - IMAGE_BASE
            # 只关心数据区
            for name, vaddr, vsize, raddr, rsize in SECS:
                if name in ('.rdata', '.data') and vaddr <= rva < vaddr + vsize:
                    print('  vtable? @ VA %08X (off 0x%X) 段=%s' % (va, off, name))
                    # 往前找表首：连续 4 字节指针且指向 .text
                    start = off
                    while start - 4 >= 0:
                        v, = struct.unpack_from('<I', DATA, start - 4)
                        if IMAGE_BASE + 0x1000 <= v < IMAGE_BASE + 0x25843F:
                            start -= 4
                        else:
                            break
                    n = 0
                    while True:
                        v, = struct.unpack_from('<I', DATA, start + n * 4)
                        if not (IMAGE_BASE + 0x1000 <= v < IMAGE_BASE + 0x25843F):
                            break
                        tag = KNOWN.get(v, '')
                        print('     [%2d] %08X  %s' % (n, v, tag))
                        n += 1
                        if n > 40:
                            break
                    break


if __name__ == '__main__':
    main()
