# -*- coding: utf-8 -*-
"""7K2 资源容器 解包/打包 核心库（字节级精确往返）。

支持的容器（依据 7k2-master 源码）：
  * ResourceIdx  : 命名索引包。struct ResIndex{ char name[9]; uint32 pointer; } #pragma pack(1)
                   (oresx.h / oresx.cpp)。记录 i(0-based, 索引顺序) 数据位于
                   [index_buf[i].pointer, index_buf[i+1].pointer)。索引项共
                   (rec_count+1) 个，末项(name 全 0) 仅用其 pointer 计算最后一条大小。
                   用于 INTROTXT/CPG_INTR/TUT_TEXT/TUT_INTR/Hotkey(.res)、STD.SET、
                   Campaign 的 *.stg/*.evt/*.plt/*.DLG/*.TXR。
  * Resource     : 无名索引包。int16 rec_count + (rec_count+1) 个 uint32 offset
                   (ores.cpp)。本批 update\\ 文件未命中，仍实现以便通用。
  * blob         : 非索引容器（纯文本 .res / .sct 等），整体作为一条不透明字节流。
                   打包时原样回写，保证字节级一致。

设计要点（保证与原版逐字节相同）：
  * 记录按「索引顺序」保存，打包时严格按同序重排。
  * 每条记录保存其原始 9 字节 name（含哨兵项），打包时原样写回，不猜测填充。
  * 保留零长度记录与原始 record 字节。
  * 复用原始 name 字节，即便其中含非打印字符也照存。
"""
import os
import struct
import json
import hashlib

# ---- 容器特征常量 ----
RESIDX_HDR_BASE = 2          # int16 rec_count
RESIDX_ENTRY = 13            # 9(name) + 4(pointer)
RES_HDR_BASE = 2


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for blk in iter(lambda: f.read(1 << 20), b''):
            h.update(blk)
    return h.hexdigest()


def is_residx(data):
    """判定是否为命名 ResourceIdx。"""
    n = len(data)
    if n < RESIDX_HDR_BASE + RESIDX_ENTRY:
        return False
    cnt = struct.unpack_from('<h', data, 0)[0]
    if cnt < 0 or cnt > 200000:
        return False
    hsize = RESIDX_HDR_BASE + (cnt + 1) * RESIDX_ENTRY
    if hsize > n:
        return False
    ptrs = []
    for i in range(cnt + 1):
        off = RESIDX_HDR_BASE + i * RESIDX_ENTRY
        ptrs.append(struct.unpack_from('<I', data, off + 9)[0])
    if ptrs[0] != hsize:
        return False
    if ptrs[-1] != n:
        return False
    for i in range(1, len(ptrs)):
        if ptrs[i] < ptrs[i - 1]:
            return False
    return True


def is_resource(data):
    """判定是否为无名 Resource（uint32 offset 表）。"""
    n = len(data)
    if n < RES_HDR_BASE + 4:
        return False
    cnt = struct.unpack_from('<h', data, 0)[0]
    if cnt < 0 or cnt > 200000:
        return False
    hsize = RES_HDR_BASE + (cnt + 1) * 4
    if hsize > n:
        return False
    ptrs = [struct.unpack_from('<I', data, RES_HDR_BASE + i * 4)[0] for i in range(cnt + 1)]
    if ptrs[0] != hsize:
        return False
    if ptrs[-1] != n:
        return False
    for i in range(1, len(ptrs)):
        if ptrs[i] < ptrs[i - 1]:
            return False
    return True


# ---------------------------------------------------------------------------
# ResourceIdx
# ---------------------------------------------------------------------------
def read_residx(data):
    """返回 (count, [ (name_raw9(bytes), data_bytes_or_None), ... len=count+1 ])。
    末项为哨兵（data=None）。"""
    cnt = struct.unpack_from('<h', data, 0)[0]
    entries = []
    for i in range(cnt + 1):
        off = RESIDX_HDR_BASE + i * RESIDX_ENTRY
        name_raw = data[off:off + 9]
        ptr = struct.unpack_from('<I', data, off + 9)[0]
        if i < cnt:
            nxt = struct.unpack_from('<I', data, RESIDX_HDR_BASE + (i + 1) * RESIDX_ENTRY + 9)[0]
            rec = data[ptr:nxt]
        else:
            rec = None
        entries.append((name_raw, rec))
    return cnt, entries


def write_residx(entries):
    """entries: [ (name_raw9(bytes), data_bytes_or_None), ... ]，长度 = count+1。
    返回重组后的完整文件字节。
    注意：entries 已含 (count+1) 个索引项，末项为哨兵（rec=None），
    其 pointer 即为文件总长，因此索引区写完即完整，无需额外追加。"""
    cnt = len(entries) - 1
    hsize = RESIDX_HDR_BASE + (cnt + 1) * RESIDX_ENTRY
    out = bytearray()
    out += struct.pack('<h', cnt)
    ptr = hsize
    for i, (name_raw, rec) in enumerate(entries):
        if len(name_raw) != 9:
            raise ValueError('name_raw 必须为 9 字节，得到 %d' % len(name_raw))
        out += name_raw
        out += struct.pack('<I', ptr)
        if rec is not None:
            ptr += len(rec)
    # 末项（哨兵）的 pointer 此时等于 ptr = 文件总长；数据紧随索引区之后写出。
    for name_raw, rec in entries[:-1]:
        if rec is not None:
            out += rec
    return bytes(out)


# ---------------------------------------------------------------------------
# Resource (无名)
# ---------------------------------------------------------------------------
def read_resource(data):
    cnt = struct.unpack_from('<h', data, 0)[0]
    ptrs = [struct.unpack_from('<I', data, RES_HDR_BASE + i * 4)[0] for i in range(cnt + 1)]
    recs = [data[ptrs[i]:ptrs[i + 1]] for i in range(cnt)]
    return cnt, recs


def write_resource(recs):
    cnt = len(recs)
    hsize = RES_HDR_BASE + (cnt + 1) * 4
    out = bytearray()
    out += struct.pack('<h', cnt)
    ptr = hsize
    for r in recs:
        out += struct.pack('<I', ptr)
        ptr += len(r)
    out += struct.pack('<I', ptr)
    for r in recs:
        out += r
    return bytes(out)


# ---------------------------------------------------------------------------
# 上层 API：解包到一个目录
# ---------------------------------------------------------------------------
def _safe_name(index, name_raw):
    s = name_raw.rstrip(b'\x00').decode('ascii', 'replace')
    s = ''.join(c if (c.isalnum() or c in '-_') else '_' for c in s)
    if not s:
        s = 'rec'
    return '%03d_%s' % (index, s)


def unpack_to_dir(infile, outdir, as_text=False):
    """解包单个文件到 outdir（outdir 会被创建）。
    返回 manifest dict（也写入 outdir/manifest.json）。"""
    data = open(infile, 'rb').read()
    base = os.path.basename(infile)
    os.makedirs(outdir, exist_ok=True)
    manifest = {'source': base, 'size': len(data), 'sha256': sha256_file(infile)}

    if is_residx(data):
        cnt, entries = read_residx(data)
        recs_dir = os.path.join(outdir, 'records')
        os.makedirs(recs_dir, exist_ok=True)
        rec_meta = []
        for i, (name_raw, rec) in enumerate(entries):
            name_str = name_raw.rstrip(b'\x00').decode('latin-1')
            slug = _safe_name(i, name_raw)
            if i < cnt:
                fname = slug + '.bin'
                open(os.path.join(recs_dir, fname), 'wb').write(rec)
                if as_text:
                    try:
                        txt = rec.decode('cp950', 'replace')
                        open(os.path.join(recs_dir, slug + '.txt'), 'w', encoding='utf-8').write(txt)
                    except Exception:
                        pass
                rec_meta.append({'index': i, 'name': name_str,
                                 'name_raw': name_raw.hex(), 'file': fname, 'size': len(rec)})
            else:
                rec_meta.append({'index': i, 'name': name_str,
                                 'name_raw': name_raw.hex(), 'file': None, 'size': 0,
                                 'sentinel': True})
        manifest.update({'type': 'residx', 'count': cnt, 'records': rec_meta})
    elif is_resource(data):
        cnt, recs = read_resource(data)
        recs_dir = os.path.join(outdir, 'records')
        os.makedirs(recs_dir, exist_ok=True)
        rec_meta = []
        for i, rec in enumerate(recs):
            fname = '%03d.bin' % i
            open(os.path.join(recs_dir, fname), 'wb').write(rec)
            rec_meta.append({'index': i, 'file': fname, 'size': len(rec)})
        manifest.update({'type': 'resource', 'count': cnt, 'records': rec_meta})
    else:
        # blob：原样保存
        fname = 'blob.bin'
        open(os.path.join(outdir, fname), 'wb').write(data)
        if as_text:
            try:
                txt = data.decode('cp950', 'replace')
                open(os.path.join(outdir, 'blob.txt'), 'w', encoding='utf-8').write(txt)
            except Exception:
                pass
        manifest.update({'type': 'blob', 'file': fname})

    with open(os.path.join(outdir, 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return manifest


def pack_from_dir(outdir):
    """从 unpack_to_dir 生成的 outdir 重组文件字节。"""
    manifest = json.load(open(os.path.join(outdir, 'manifest.json'), encoding='utf-8'))
    t = manifest['type']
    if t == 'residx':
        entries = []
        recs_dir = os.path.join(outdir, 'records')
        for rm in manifest['records']:
            name_raw = bytes.fromhex(rm['name_raw'])
            if rm.get('sentinel'):
                entries.append((name_raw, None))
            else:
                entries.append((name_raw, open(os.path.join(recs_dir, rm['file']), 'rb').read()))
        return write_residx(entries)
    elif t == 'resource':
        recs_dir = os.path.join(outdir, 'records')
        recs = [open(os.path.join(recs_dir, rm['file']), 'rb').read() for rm in manifest['records']]
        return write_resource(recs)
    else:  # blob
        return open(os.path.join(outdir, manifest['file']), 'rb').read()


def detect_type(data):
    if is_residx(data):
        return 'residx'
    if is_resource(data):
        return 'resource'
    return 'blob'


if __name__ == '__main__':
    print('packlib loaded; self-test quick:')
    import io
    # 自建一个最小 ResourceIdx 验证 write/read 往返
    a = b'hello world'
    b = b''
    c = b'\x00\x01\x02\x03'
    ents = [(b'ONE\x00\x00\x00\x00\x00\x00', a), (b'TWO\x00\x00\x00\x00\x00\x00', b),
            (b'THREE\x00\x00\x00\x00', c), (b'\x00\x00\x00\x00\x00\x00\x00\x00\x00', None)]
    buf = write_residx(ents)
    cnt2, ents2 = read_residx(buf)
    ok = (cnt2 == 3 and ents2[0][1] == a and ents2[1][1] == b and ents2[2][1] == c
          and ents2[3][0] == b'\x00\x00\x00\x00\x00\x00\x00\x00\x00')
    print('ResourceIdx roundtrip:', 'OK' if ok else 'FAIL')
    rb = write_resource([a, b, c])
    c2, r2 = read_resource(rb)
    print('Resource roundtrip:', 'OK' if (r2 == [a, b, c]) else 'FAIL')
