# -*- coding: utf-8 -*-
"""抽取「整文件缺失」的英文原文，生成翻译工作单 tools/gap_en.json"""
import os, json, sys, struct, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

GAME = r'I:\LocalGames\Seven Kingdoms II HD'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gap_en.json')


def read_res_idx(path):
    data = open(path, 'rb').read()
    count = struct.unpack('<h', data[0:2])[0]
    recs = []
    for i in range(count + 1):
        off = 2 + i * 13
        name = data[off:off + 9].rstrip(b'\x00').decode('latin-1')
        ptr = struct.unpack('<I', data[off + 9:off + 13])[0]
        recs.append((name, ptr))
    return data, [(recs[i][0], recs[i][1], recs[i + 1][1] - recs[i][1]) for i in range(count)]


def show_bytes(path, n=64):
    d = open(path, 'rb').read()
    return '%s | %s' % (d[:n].hex(' '), re.sub(rb'[^\x20-\x7e]', b'.', d[:n]).decode('latin-1'))


def idx_text(path):
    """ResourceIdx 容器：把每个记录的可见文本抽出来"""
    data, recs = read_res_idx(path)
    out = []
    for name, off, size in recs:
        raw = data[off:off + size]
        txt = raw.decode('cp950', errors='replace')
        vis = ''.join(c if (c >= ' ' or c == '\n') else '' for c in txt)
        vis = vis.strip('\x00 \r\n\t')
        if len(re.findall(r'[A-Za-z]{3,}', vis)) >= 1:
            out.append({'rec': name, 'size': size, 'text': vis})
    return out


def main():
    work = {}

    print('=' * 72)
    print('ResourceIdx 容器（英文原文）')
    print('=' * 72)
    for rel in ['Campaign/tutorial.stg', 'Campaign/tutorial.evt',
                'Campaign/EAST.TXR', 'Campaign/EAST.DLG']:
        p = os.path.join(GAME, *rel.split('/'))
        if not os.path.exists(p):
            print('  缺文件', rel)
            continue
        items = idx_text(p)
        total = sum(len(i['text']) for i in items)
        print('  %-24s 有文本记录 %3d 条，共 %6d 字符' % (rel, len(items), total))
        work[rel] = items

    print()
    print('=' * 72)
    print('其他 .RES（先看格式）')
    print('=' * 72)
    for rel in ['Resource/INTROTXT.RES', 'Resource/CPG_INTR.RES',
                'Resource/TUT_INTR.RES', 'Resource/CREDIT.RES',
                'Campaign/INTROTXT.RES']:
        p = os.path.join(GAME, *rel.split('/'))
        if not os.path.exists(p):
            print('  缺文件', rel)
            continue
        d = open(p, 'rb').read()
        print('  %-26s size=%-8d %s' % (rel, len(d), show_bytes(p)))
        # 若是 ResourceIdx 就抽
        try:
            items = idx_text(p)
            if items:
                print('        -> ResourceIdx: %d 条文本记录' % len(items))
                work[rel] = items
                continue
        except Exception:
            pass
        # 否则当纯文本
        txt = d.decode('cp950', errors='replace')
        vis = ''.join(c if (c >= ' ' or c == '\n') else '' for c in txt).strip()
        if len(re.findall(r'[A-Za-z]{3,}', vis)) >= 1:
            print('        -> 纯文本 %d 字符' % len(vis))
            work[rel] = [{'rec': 'whole', 'size': len(d), 'text': vis}]

    json.dump(work, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print()
    print('已写入', OUT)
    tot = sum(len(i['text']) for v in work.values() for i in v)
    print('待译合计 %d 条记录 / %d 字符' % (sum(len(v) for v in work.values()), tot))


if __name__ == '__main__':
    main()
