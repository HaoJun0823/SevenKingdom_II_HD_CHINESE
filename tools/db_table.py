# -*- coding: utf-8 -*-
"""
STD.SET 内嵌数据库表（UNIT / RACE / MONSTER / FIRM / TECH ...）的定位与字段提取。

表格式（实测，与原版 STD.SET 完全吻合）：
    [0:32]                    文件头
    [32 : 32+32*N]            字段定义区，每字段 32 字节：
                                  name[11] + type[1] + offset[4] + width[4] + 保留[12]
    [32+32*N : EOF-1]         记录区，记录宽 = 各字段 (offset+width) 的最大值
    [EOF-1]                   EOF (0x1A)
    每条记录首字节为删除标记（0x20 = 有效，0x0D / 0x2A = 已删除），
    字段 offset 相对「记录内容」即不含首字节删除标记。
"""
import struct


def parse_fields(data, max_fields=64):
    """解析字段定义区，返回 [{'name','type','off','width'}, ...]"""
    fields = []
    p = 32
    while p + 32 <= len(data) and len(fields) < max_fields:
        blk = data[p:p + 32]
        name_b = blk[:11].split(b'\x00')[0]
        typ = blk[11:12]
        if not name_b or not all(32 <= c < 127 for c in name_b):
            break
        if typ not in b'CNDLF':
            break
        off, width = struct.unpack('<II', blk[12:20])
        fields.append({'name': name_b.decode('latin1'), 'type': chr(typ[0]),
                       'off': off, 'width': width})
        p += 32
    return fields


def record_layout(data):
    """返回 (fields, rec_start, rec_len, n_records)"""
    fields = parse_fields(data)
    if not fields:
        return None, None, None, None
    # 数据区起点 = 头(32) + 字段定义(32*N) + 1 个分隔字节（实测 RACE/MONSTER/UNIT 均为 +1）
    rec_start = 32 + 32 * len(fields) + 1
    rec_len = max(f['off'] + f['width'] for f in fields)
    body = len(data) - rec_start
    if body > 0 and data[-1] == 0x1A:
        body -= 1
    n = body // rec_len if rec_len else 0
    return fields, rec_start, rec_len, n


def str_field(data, rec_start, rec_len, rec_index, field, deleted_mark=b'\r*'):
    """取某记录某字符串字段的 (原始字节, 是否删除)"""
    base = rec_start + rec_index * rec_len
    if base + rec_len > len(data):
        return None, None
    mark = data[base:base + 1]
    raw = data[base + field['off']: base + field['off'] + field['width']]
    return raw, (mark in [bytes([m]) for m in deleted_mark])


def list_strings(data, field_names=('NAME', 'ADJECTIVE', 'CODE', 'ICONNAME')):
    """列出指定名字字段的所有取值"""
    fields, rs, rl, n = record_layout(data)
    if not fields:
        return []
    out = []
    for f in fields:
        if f['name'] not in field_names or f['type'] != 'C':
            continue
        for i in range(n):
            raw, dele = str_field(data, rs, rl, i, f)
            if raw is None:
                continue
            txt = raw.rstrip(b'\x00 ')
            out.append((i, f['name'], txt, dele))
    return out
