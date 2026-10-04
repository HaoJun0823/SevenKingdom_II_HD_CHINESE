# -*- coding: utf-8 -*-
"""minidump 解析：异常/模块/线程/栈回溯（x86）。

偏移全部按 MINIDUMP_* 官方结构手工核对：
  MINIDUMP_THREAD  : ThreadId0 Susp4 PrioC8 Prio12 Teb16 Stack24(StartOfMemoryRange24,
                     DataSize32,Rva36) ThreadContext(DataSize40,Rva44)   size=48
  MINIDUMP_MODULE  : Base0 SizeOfImage8 CheckSum12 TimeDateStamp16 ModuleNameRva20 ...
  MINIDUMP_EXCEPTION_STREAM : ThreadId0 __align4 ExceptionRecord8 ThreadContext160(DataSize160,Rva164)
  MINIDUMP_EXCEPTION : Code0 Flags4 Record8 Address16 NumberParameters24 pad28 Info[15]32  size=152
"""
import struct, sys, os

ST = {0: 'Unused', 3: 'ThreadList', 4: 'ModuleList', 5: 'Memory64List',
      6: 'ExceptionStream', 7: 'SystemInfo', 9: 'MemoryList',
      11: 'ThreadInfoList', 16: 'MemoryInfoList', 17: 'ThreadNames'}


class MD:
    def __init__(self, path):
        self.d = open(path, 'rb').read()
        d = self.d
        sig, ver, nstream, dirrva = struct.unpack_from('<IIII', d, 0)
        assert sig == 0x504D444D, 'not a minidump'
        self.streams = {}
        for i in range(nstream):
            t, sz, rva = struct.unpack_from('<III', d, dirrva + i * 12)
            self.streams.setdefault(t, []).append((sz, rva))

    def u32(self, o):
        return struct.unpack_from('<I', self.d, o)[0]

    def u64(self, o):
        return struct.unpack_from('<Q', self.d, o)[0]

    # ---------- 顶层 ----------
    def exception(self):
        if 6 not in self.streams:
            return None
        sz, rva = self.streams[6][0]
        tid = self.u32(rva)
        code = self.u32(rva + 8)
        flags = self.u32(rva + 12)
        addr = self.u64(rva + 24)
        npar = self.u32(rva + 32)
        info = [self.u64(rva + 40 + 8 * k) for k in range(min(npar, 15))]
        csz, crva = struct.unpack_from('<II', self.d, rva + 160)
        return dict(ThreadId=tid, Code=code, Flags=flags, Address=addr,
                    NumParams=npar, Info=info, CtxRva=crva, CtxSize=csz)

    def threads(self):
        out = []
        if 3 not in self.streams:
            return out
        sz, rva = self.streams[3][0]
        n = self.u32(rva)
        for i in range(n):
            o = rva + 4 + i * 48
            out.append(dict(ThreadId=self.u32(o), Teb=self.u64(o + 16),
                            StackStart=self.u64(o + 24),
                            StackSize=self.u32(o + 32),
                            StackRva=self.u32(o + 36),
                            CtxDataSize=self.u32(o + 40),
                            CtxRva=self.u32(o + 44)))
        return out

    def modules(self):
        out = []
        if 4 not in self.streams:
            return out
        sz, rva = self.streams[4][0]
        n = self.u32(rva)
        for i in range(n):
            o = rva + 4 + i * 108
            base = self.u64(o)
            size = self.u32(o + 8)
            nameRva = self.u32(o + 20)
            name = self.wstr(nameRva)
            out.append(dict(Base=base, Size=size, Name=name))
        return out

    def wstr(self, rva):
        if not rva:
            return ''
        n = self.u32(rva)
        raw = self.d[rva + 4:rva + 4 + n]
        try:
            return raw.decode('utf-16-le', 'replace')
        except Exception:
            return repr(raw)

    def sysinfo(self):
        if 7 not in self.streams:
            return None
        sz, rva = self.streams[7][0]
        arch, level, rev, nproc, ptype, major, minor, build = struct.unpack_from('<HHHBBIII', self.d, rva)
        return dict(Arch=arch, NumProc=nproc, Major=major, Minor=minor, Build=build)

    def meminfo(self, addr):
        """在 MemoryInfoList 里找包含 addr 的区域"""
        if 16 not in self.streams:
            return None
        sz, rva = self.streams[16][0]
        n = self.u64(rva)
        for i in range(n):
            o = rva + 16 + i * 48
            base, rsize = self.u64(o), self.u64(o + 8)
            state, protect = self.u32(o + 24), self.u32(o + 28)
            if base <= addr < base + rsize:
                return dict(Base=base, Size=rsize, State=state, Protect=protect)
        return None

    def _ranges(self):
        """返回 [(start, size, file_off)] —— 统一 MemoryList(9) 与 Memory64List(5)"""
        if getattr(self, '_rg', None) is not None:
            return self._rg
        rg = []
        if 9 in self.streams:
            sz, rva = self.streams[9][0]
            cnt = self.u32(rva)
            for i in range(cnt):
                o = rva + 4 + i * 16
                rg.append((self.u64(o), self.u32(o + 8), self.u32(o + 12)))
        if 5 in self.streams:
            sz, rva = self.streams[5][0]
            # ★ 这个 dump（WER 写法）是「ULONG32 计数 + 16 字节 MINIDUMP_MEMORY_DESCRIPTOR」
            #   校验: 4 + n*16 == DataSize
            cnt = self.u32(rva)
            if 4 + cnt * 16 == sz:
                for i in range(cnt):
                    o = rva + 4 + i * 16
                    rg.append((self.u64(o), self.u32(o + 8), self.u32(o + 12)))
            else:
                # 规范写法：ULONG64 计数 + RVA64 BaseRva + 16 字节 64 位描述符
                cnt64 = self.u64(rva)
                base = self.u64(rva + 8)
                cur = base
                for i in range(cnt64):
                    o = rva + 16 + i * 16
                    start = self.u64(o)
                    dsz = self.u64(o + 8)
                    rg.append((start, dsz, cur))
                    cur += dsz
        rg.sort()
        self._rg = rg
        return rg

    def read_mem(self, addr, n):
        for start, msz, off0 in self._ranges():
            if start <= addr < start + msz:
                off = addr - start
                take = min(msz - off, n)
                return self.d[off0 + off: off0 + off + take]
        return None


EIP_OFF, ESP_OFF, EBP_OFF = 0xB8, 0xC4, 0xB4
# x86 CONTEXT 通用寄存器布局（勿错位）：
#   0x9C Edi | 0xA0 Esi | 0xA4 Ebx | 0xA8 Edx | 0xAC Ecx | 0xB0 Eax
#   0xB4 Ebp | 0xB8 Eip | 0xBC SegCs | 0xC0 EFlags | 0xC4 Esp | 0xC8 SegSs
EAX, ECX, EDX, EBX = 0xB0, 0xAC, 0xA8, 0xA4
ESI, EDI = 0xA0, 0x9C


def main():
    path = sys.argv[1]
    md = MD(path)
    print('=' * 78)
    print('文件:', path, ' (%.1f MB)' % (os.path.getsize(path) / 1048576.0))
    si = md.sysinfo()
    if si:
        arch = {0: 'x86', 9: 'x64', 5: 'ARM', 12: 'ARM64'}.get(si['Arch'], si['Arch'])
        print('系统: %s  CPU=%d  OS %d.%d build %d' % (arch, si['NumProc'], si['Major'], si['Minor'], si['Build']))
    print('流:', ', '.join('%s(%d)' % (ST.get(k, k), len(v)) for k, v in sorted(md.streams.items())))

    ex = md.exception()
    mods = md.modules()
    print()
    print('=== 异常 ===')
    if not ex:
        print('  (无 ExceptionStream)')
        return
    CODES = {0xC0000005: 'ACCESS_VIOLATION', 0xC000001D: 'ILLEGAL_INSTRUCTION',
             0xC0000094: 'INT_DIVIDE_BY_ZERO', 0xC00000FD: 'STACK_OVERFLOW',
             0xC0000409: 'STACK_BUFFER_OVERRUN', 0x80000003: 'BREAKPOINT',
             0xC0000374: 'HEAP_CORRUPTION', 0xC000008C: 'ARRAY_BOUNDS_EXCEEDED'}
    print('  代码 0x%08X %s   线程 %d' % (ex['Code'], CODES.get(ex['Code'], '?'), ex['ThreadId']))
    print('  地址 0x%08X' % ex['Address'])
    if ex['NumParams']:
        for k, v in enumerate(ex['Info']):
            print('    Info[%d] = 0x%08X' % (k, v))
    if ex['NumParams'] >= 2 and ex['Code'] == 0xC0000005:
        op = {0: '读', 1: '写', 8: 'DEP执行'}.get(ex['Info'][0], '?%d' % ex['Info'][0])
        print('  → 访问类型: %s 目标地址 0x%08X' % (op, ex['Info'][1]))
        mi = md.meminfo(ex['Info'][1])
        print('  → 目标内存区:', ('无 MemoryInfoList' if not mi else
              'Base=0x%08X Size=0x%X State=0x%X Protect=0x%X' % (mi['Base'], mi['Size'], mi['State'], mi['Protect'])))

    # 模块归属
    def owner(a):
        best = None
        for m in mods:
            if m['Base'] <= a < m['Base'] + m['Size']:
                best = m
        return best

    print()
    print('=== 模块 %d 个（含 7K2）===' % len(mods))
    for m in sorted(mods, key=lambda x: x['Base']):
        if '7K2' in m['Name'] or 'sk2_zh' in m['Name'] or 'MILES' in m['Name'].upper() or 'dsound' in m['Name'].lower():
            print('  0x%08X - 0x%08X  %-40s' % (m['Base'], m['Base'] + m['Size'], os.path.basename(m['Name'])))

    # 定位出错线程上下文
    ctx = None
    tex = None
    for t in md.threads():
        if t['ThreadId'] == ex['ThreadId']:
            tex = t
    if ex['CtxRva']:
        ctx = ex['CtxRva']
    elif tex:
        ctx = tex['CtxRva']
    if ctx:
        eip = md.u32(ctx + EIP_OFF)
        esp = md.u32(ctx + ESP_OFF)
        ebp = md.u32(ctx + EBP_OFF)
        def reg(o):
            return md.u32(ctx + o)
        print()
        print('=== 故障线程上下文 ===')
        print('  EIP=0x%08X  ESP=0x%08X  EBP=0x%08X' % (eip, esp, ebp))
        print('  EAX=0x%08X EBX=0x%08X ECX=0x%08X EDX=0x%08X' % (reg(EAX), reg(EBX), reg(ECX), reg(EDX)))
        print('  ESI=0x%08X EDI=0x%08X' % (reg(ESI), reg(EDI)))
        m = owner(eip)
        print('  EIP 归属: %s' % (('%s + 0x%X' % (os.path.basename(m['Name']), eip - m['Base'])) if m else '(未知模块)'))
        if m and '7K2' in m['Name']:
            print('  EIP RVA = 0x%X   (IDA VA = 0x%X)' % (eip - m['Base'], 0x400000 + (eip - m['Base'])))
        code = md.read_mem(eip, 32)
        if code:
            print('  故障点机器码: %s' % code.hex(' '))
        # 栈回溯
        print()
        print('=== 栈回溯（EBP 链）===')
        fp = ebp
        seen = set()
        for depth in range(24):
            if not fp or fp in seen:
                break
            seen.add(fp)
            nxt = md.read_mem(fp, 8)
            if not nxt or len(nxt) < 8:
                break
            prev, ret = struct.unpack('<II', nxt)
            mm = owner(ret)
            tag = '%s + 0x%X' % (os.path.basename(mm['Name']), ret - mm['Base']) if mm else '???'
            print('  #%-2d ret=0x%08X  %s' % (depth, ret, tag))
            if not prev or prev <= fp:
                break
            fp = prev
        # 栈顶原始数据（含未帧指针的部分）
        print()
        print('=== 栈顶 96 字节（ESP 起）===')
        st = md.read_mem(esp, 96)
        if st:
            for k in range(0, len(st), 16):
                row = st[k:k + 16]
                print('  0x%08X  %s   %s' % (esp + k, row.hex(' '),
                      ''.join(chr(c) if 32 <= c < 127 else '.' for c in row)))
        # 寄存器指向的可读字符串（快速看是哪条文本在手上）
        print()
        print('=== 寄存器指向的内存（前 64 字节，找字符串）===')
        for name, val in (('EAX', reg(EAX)), ('EBX', reg(EBX)), ('ECX', reg(ECX)),
                          ('EDX', reg(EDX)), ('ESI', reg(ESI)), ('EDI', reg(EDI))):
            if not val:
                continue
            mm = md.read_mem(val, 64)
            if mm:
                s = ''.join(chr(c) if 32 <= c < 127 else '.' for c in mm)
                print('  %s -> 0x%08X  %s' % (name, val, s))
                print('       hex %s' % mm.hex(' '))


if __name__ == '__main__':
    main()
