# -*- coding: utf-8 -*-
"""检查 update\\ 里重建的资源：是否有记录比原版更长。

容器格式（索引型 .res/.stg/.evt/.DLG/.TXR/.plt）：
    int16 count
    count+1 条索引，每条 13 字节 = 名字[9] + uint32 偏移
    末尾那条是「结束哨兵」，其偏移应等于文件长度

风险：引擎部分读取路径用定长缓冲区，汉化后如果某条记录变长，
就可能溢出。本脚本把「变长」的条目全列出来，供人工复核。
"""
import struct
import os
import sys

G = r'I:\LocalGames\Seven Kingdoms II HD'
U = os.path.join(G, 'update')


def read_idx(path):
    """返回 {name: raw_bytes}；不是本格式则返回 None。"""
    try:
        d = open(path, 'rb').read()
    except OSError:
        return None
    if len(d) < 16:
        return None
    cnt = struct.unpack('<h', d[0:2])[0]
    if cnt < 0 or cnt > 4000:
        return None
    hdr = 2 + 13 * (cnt + 1)
    if hdr > len(d):
        return None
    idx = []
    for i in range(cnt + 1):
        off = 2 + i * 13
        nm = d[off:off + 9].rstrip(b'\x00').decode('latin-1')
        idx.append((nm, struct.unpack('<I', d[off + 9:off + 13])[0]))
    if not all(idx[i][1] <= idx[i + 1][1] for i in range(cnt)):
        return None
    if idx[-1][1] != len(d):
        return None
    out = {}
    for i in range(cnt):
        out[idx[i][0]] = d[idx[i][1]:idx[i + 1][1]]
    return out


def main():
    bad = []
    checked = 0
    for root, _dirs, files in os.walk(U):
        rel_dir = os.path.relpath(root, U)
        if rel_dir.split(os.sep)[0] not in ('Campaign', 'Resource', 'Scenario'):
            continue
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), U)
            o = os.path.join(G, rel)
            if not os.path.exists(o):
                continue
            a = read_idx(o)
            b = read_idx(os.path.join(root, f))
            if not a or not b:
                continue
            checked += 1
            for k in b:
                if k not in a:
                    continue
                la = len(a[k].split(b'\x00')[0])
                lb = len(b[k].split(b'\x00')[0])
                if lb > la:
                    bad.append((rel.replace(os.sep, '/'), k, la, lb))
    print('已检查容器文件 %d 个；变长条目 %d 条' % (checked, len(bad)))
    for x in sorted(bad, key=lambda t: -(t[3] - t[2]))[:60]:
        print('   %-30s %-10s %5d -> %5d  (+%d)' % (x[0], x[1], x[2], x[3], x[3] - x[2]))
    # 顺带检查纯文本文件是否变长
    print()
    print('--- 纯文本/其它文件尺寸对比 ---')
    for root, _dirs, files in os.walk(U):
        rel_dir = os.path.relpath(root, U)
        if rel_dir.split(os.sep)[0] not in ('Campaign', 'Resource', 'Scenario'):
            continue
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), U)
            o = os.path.join(G, rel)
            if not os.path.exists(o):
                continue
            if read_idx(o):
                continue
            sa = os.path.getsize(o)
            sb = os.path.getsize(os.path.join(root, f))
            flag = '  ★变长' if sb > sa else ''
            print('   %-38s %8d -> %8d%s' % (rel.replace(os.sep, '/'), sa, sb, flag))


if __name__ == '__main__':
    main()
