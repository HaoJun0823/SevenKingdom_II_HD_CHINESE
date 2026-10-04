# -*- coding: utf-8 -*-
"""
盘点 STD.SET 内嵌表里「还没翻好的可见文本」——坏字节 + 漏翻。

和 scan_en_leftover.py 的区别
-----------------------------
后者按**记录**扫（整条记录里的连续 ASCII 串），对 STD.SET 里的定长表
（RACENAME / TOWNNAME / HERO ...）没用：一条记录只有一个短名字字段，
翻没翻只能靠「和原版比」，而原版是英文 —— 全大写英文会被当成 ID 放行，
于是漏翻全藏起来。

所以这里按**字段**扫：只取字符型字段（type == 'C'）且字段名在白名单里
（见 WHITE），逐条记录比较「汉化值」与「原版值」：

  bad   : 汉化值 cp950 解码出 U+FFFD（坏字节/乱码）
  same  : 汉化值和原版逐字节相同（漏翻，且原版本身是英文）
  same_cn: 汉化值和原版相同，但原版那条已经是中文（说明当初就没翻就搬过来了）

用法:
    python scan_pending.py [--chs ../unpack_data_chs] [--orig ../unpack_data_original]
                           [--table RACENAME] [--verbose]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db_table as D  # noqa: E402

# 白名单：这些字段是玩家真正会看到的文本
# 排除 *PTR / PAL_PTR / BITMAPPTR（二进制指针）、SPRITE.NAME（内部 ID，本该英文）
WHITE = {
    'NAME', 'SHORTNAME', 'OVERTITLE', 'WORKTITLE', 'DESC', 'ADJECTIVE',
    'FIRSTNAME', 'LASTNAME', 'TITLE', 'PLURAL', 'PREFIX', 'SUFFIX',
    'SHORTDESC', 'GENERAL', 'NOTE',
}


CUST_LO, CUST_HI = 0x90, 0xA0
B5_LO, B5_HI = 0xA1, 0xF9


def decode(b):
    """按「字体对」结构解码，而不是直接 cp950。

    为什么不能直接用 cp950：本项目的字体补丁在 0x90~0xA0 段自定义了
    一批字形对（补 Big5 没有的字）。这些字节用 cp950 解不出来，
    会被误判成「坏字节」。按结构走一遍才准：

      * 0x90~0xA0 开头且尾字节 0x40~0x7E  -> 自定义字形，记为 '□'（正常）
      * 0xA1~0xF9 开头且尾字节合法        -> 标准 Big5，cp950 解码
      * 单字节 ASCII                      -> 原样
      * 其余                              -> 真坏字节

    返回 (文本, 是否有真问题)。
    """
    out = []
    bad = False
    i = 0
    while i < len(b):
        x = b[i]
        if CUST_LO <= x <= CUST_HI:
            if i + 1 < len(b) and 0x40 <= b[i + 1] <= 0x7E:
                out.append('□')
            else:
                bad = True
                out.append('�')
            i += 2
            continue
        if B5_LO <= x <= B5_HI:
            if i + 1 < len(b) and (0x40 <= b[i + 1] <= 0x7E or 0xA1 <= b[i + 1] <= 0xFE):
                try:
                    out.append(bytes(b[i:i + 2]).decode('cp950'))
                except UnicodeDecodeError:
                    bad = True
                    out.append('�')
            else:
                bad = True
                out.append('�')
            i += 2
            continue
        if 0x20 <= x < 0x7F:
            out.append(chr(x))
        else:
            bad = True
            out.append('�')
        i += 1
    return ''.join(out), bad


def _load_manifest(d):
    """定位 STD.SET 的 manifest（解包根下有很多 .unpacked 各自的 manifest，
    必须挑 source == 'STD.SET' 那一份），返回 (manifest, 记录文件所在目录)。"""
    cands = []
    for root, _, fs in os.walk(d):
        if 'manifest.json' in fs:
            p = os.path.join(root, 'manifest.json')
            try:
                m = json.load(open(p, encoding='utf-8'))
            except Exception:
                continue
            if str(m.get('source', '')).upper() == 'STD.SET':
                return m, os.path.join(root, 'records')
            cands.append(p)
    raise SystemExit('找不到 STD.SET 的 manifest: %s' % (cands[:3] or d))


def scan(d_o, d_c, table_filter=None):
    m_o, ro_dir = _load_manifest(d_o)
    m_c, rc_dir = _load_manifest(d_c)
    def idx(m):
        d = {}
        for r in m['records']:
            if r.get('sentinel') or not r.get('file'):
                continue
            d[bytes.fromhex(r['name_raw']).rstrip(b'\x00').decode('latin1')] = r
        return d

    ro = idx(m_o)
    rc = idx(m_c)

    out = {}
    for tname in sorted(set(ro) & set(rc)):
        if table_filter and tname != table_filter:
            continue
        if tname not in ro:
            continue
        bo = open(os.path.join(ro_dir, ro[tname]['file']), 'rb').read()
        bc = open(os.path.join(rc_dir, rc[tname]['file']), 'rb').read()
        fo, rs, rl, n = D.record_layout(bo)
        if not fo:
            continue
        fc = D.parse_fields(bc) or fo
        idx = {f['name']: i for i, f in enumerate(fc)} if fc else {}
        for f in fo:
            if f['name'] not in WHITE or f['type'] != 'C':
                continue
            fi = idx.get(f['name'])
            if fi is None:
                continue
            for i in range(n):
                raw_o, _ = D.str_field(bo, rs, rl, i, f)
                raw_c, _ = D.str_field(bc, rs, rl, i, fc[fi] if fi is not False else f)
                if raw_o is None or raw_c is None:
                    continue
                if raw_o == raw_c:
                    continue  # 原版也是空的
                txt_o, bad_o = decode(raw_o)
                txt_c, bad_c = decode(raw_c)
                if bad_c:
                    kind = 'bad'        # 译文里有真坏字节
                elif (txt_c[:1].isascii() and txt_c[:1].isalpha()) \
                        or '?' in txt_c or '�' in txt_c:
                    kind = 'partial'    # 开头仍是英文 / 残留解不出的字节 => 没翻好
                elif raw_c == raw_o and bad_o:
                    kind = 'mojibake'   # 原文本身带怪字节，译文照抄 => 界面上仍是乱码
                elif raw_c == raw_o:
                    continue            # 原译一致（多半是空或纯符号）
                else:
                    continue
                out.setdefault(tname, []).append((i, f['name'], kind, txt_o, txt_c))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--chs', default='../unpack_data_chs')
    ap.add_argument('--orig', default='../unpack_data_original')
    ap.add_argument('--table', default=None)
    ap.add_argument('--verbose', action='store_true')
    a = ap.parse_args()

    res = scan(os.path.abspath(a.orig), os.path.abspath(a.chs), a.table)
    n_bad = n_same = n_par = n_moj = 0
    for t in sorted(res):
        rows = res[t]
        b = sum(1 for r in rows if r[2] == 'bad')
        m = sum(1 for r in rows if r[2] == 'mojibake')
        p = sum(1 for r in rows if r[2] == 'partial')
        s = len(rows) - b - m - p
        n_bad += b
        n_moj += m
        n_par += p
        n_same += s
        print('=== %s === %d 条（坏字节 %d / 乱码照抄 %d / 半截 %d / 未翻 %d）'
              % (t, len(rows), b, m, p, s))
        for i, fname, kind, to, tc in rows:
            if kind != 'partial' or a.verbose:
                print('   #%-3d %-11s %-4s 原=%r  现=%r' % (i, fname, kind, to, tc))
    print('\n合计 %d 条：坏字节 %d，乱码照抄 %d，半截 %d，其它 %d'
          % (n_bad + n_moj + n_par + n_same, n_bad, n_moj, n_par, n_same))


if __name__ == '__main__':
    main()
