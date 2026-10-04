# -*- coding: utf-8 -*-
"""按 otxtres.cpp 的 TextResource::vprocess 逐行复刻，验证格式串输出。

目的：确认 `%2d%2p{a|b}`（汉化版，无空格）与 `%2d %2p{a|b}`（原版）
输出是否真有差别 —— 不靠猜，跑出来看。

用法
----
    python sim_vprocess.py
"""
import os

GAME = r'I:\LocalGames\Seven Kingdoms II HD'

MAX_ARG = 20


def fmt_int(v, fmt_type=1):
    # TextResource::format(int,int) 的简化：千分位不影响 0/1/30 的判定
    return str(int(v))


def vprocess(fmt, args):
    """args: dict{argId: value}；返回结果字节串"""
    out = bytearray()
    i, n = 0, len(fmt)

    def isd(c):
        return 0x30 <= c <= 0x39

    def find(ch, start):
        j = fmt.find(bytes([ch]), start)
        return j

    while i < n:
        c = fmt[i]
        if c == 0x25:                       # '%'
            i += 1
            if i >= n:
                break
            if fmt[i] == 0x25:              # '%%'
                out.append(0x25)
                i += 1
                continue
            if isd(fmt[i]):
                argId = 0
                while i < n and isd(fmt[i]):
                    argId = argId * 10 + (fmt[i] - 0x30)
                    i += 1
                if i >= n:
                    break
                fmtId = 0
                if fmt[i] == 0x2C:          # ','
                    i += 1
                    if i >= n:
                        break
                    while i < n and isd(fmt[i]):
                        fmtId = fmtId * 10 + (fmt[i] - 0x30)
                        i += 1
                    if i >= n:
                        break
                t = chr(fmt[i])
                v = args.get(argId)

                if t == 'd':
                    if v is not None:
                        out += fmt_int(v, fmtId or 1).encode('latin1')
                elif t == 'z':              # 零时抑制
                    if v:
                        out += fmt_int(v, fmtId or 1).encode('latin1')
                elif t == 's':
                    if v is not None:
                        out += v if isinstance(v, bytes) else str(v).encode('latin1')
                elif t == 'p':              # %Np{单|复}
                    if v is not None:
                        if v in (0, 1):
                            if i + 1 < n and fmt[i + 1] == 0x7B:   # '{'
                                i += 2
                                while i < n and fmt[i] != 0x7C:
                                    out.append(fmt[i]); i += 1
                                if i >= n:
                                    return bytes(out)
                                j = find(0x7D, i)              # '}'
                                if j >= 0:
                                    i = j
                        else:
                            if i + 1 < n and fmt[i + 1] == 0x7B:
                                j = find(0x7C, i + 2)          # '|'
                                if j >= 0:
                                    i = j + 1
                                    while i < n and fmt[i] != 0x7D:
                                        out.append(fmt[i]); i += 1
                                    if i >= n:
                                        return bytes(out)
                elif t == 'q':              # %Nq{零|单|复}
                    if v is not None:
                        if v == 0:
                            if i + 1 < n and fmt[i + 1] == 0x7B:
                                i += 2
                                while i < n and fmt[i] != 0x7C:
                                    out.append(fmt[i]); i += 1
                                if i >= n:
                                    return bytes(out)
                                j = find(0x7D, i)
                                if j >= 0:
                                    i = j
                        elif v == 1:
                            if i + 1 < n and fmt[i + 1] == 0x7B:
                                j = find(0x7C, i + 2)
                                if j >= 0:
                                    i = j + 1
                                    while i < n and fmt[i] != 0x7C:
                                        out.append(fmt[i]); i += 1
                                    if i >= n:
                                        return bytes(out)
                                    j2 = find(0x7D, i)
                                    if j2 >= 0:
                                        i = j2
                        else:
                            if i + 1 < n and fmt[i + 1] == 0x7B:
                                j = find(0x7C, i + 2)
                                if j >= 0:
                                    j2 = find(0x7C, j + 1)
                                    if j2 >= 0:
                                        i = j2 + 1
                                        while i < n and fmt[i] != 0x7D:
                                            out.append(fmt[i]); i += 1
                                        if i >= n:
                                            return bytes(out)
                elif t == '?':
                    if v is not None:
                        if v:
                            if i + 1 < n and fmt[i + 1] == 0x7B:
                                i += 2
                                while i < n and fmt[i] != 0x7C:
                                    out.append(fmt[i]); i += 1
                                if i >= n:
                                    return bytes(out)
                                j = find(0x7D, i)
                                if j >= 0:
                                    i = j
                        else:
                            if i + 1 < n and fmt[i + 1] == 0x7B:
                                j = find(0x7C, i + 2)
                                if j >= 0:
                                    i = j + 1
                                    while i < n and fmt[i] != 0x7D:
                                        out.append(fmt[i]); i += 1
                                    if i >= n:
                                        return bytes(out)
        else:
            out.append(c)
        i += 1
    return bytes(out)


def load_key(path, key):
    d = open(path, 'rb').read()
    for ln in d.replace(b'\r\n', b'\n').split(b'\n'):
        if ln.startswith(key):
            return ln[len(key):]
    return None


def show(tag, raw, hours, minutes):
    r = vprocess(raw, {1: hours, 2: minutes})
    try:
        s = r.decode('cp950')
    except Exception:
        s = repr(r)
    print('  %-10s hours=%d minutes=%d -> %r' % (tag, hours, minutes, s))


def main():
    orig = load_key(os.path.join(GAME, 'Resource', 't_reps.res'), b'[DUHM]')
    cur = load_key(os.path.join(GAME, 'update', 'Resource', 't_reps.res'), b'[DUHM]')
    print('原版  [DUHM] = %r' % orig)
    print('汉化  [DUHM] = %r' % cur)
    print()
    for h, m in [(0, 0), (0, 1), (0, 30), (1, 5), (2, 0)]:
        show('原版', orig, h, m)
        show('汉化', cur, h, m)
        print()


if __name__ == '__main__':
    main()
