# -*- coding: utf-8 -*-
"""gen_dual_pools.py —— 生成「简体 / 繁体」两套完整字形池（13/16/24px）。

背景（已由 verify_regen.py 逐字节证实）：
  现有 fontdata.h 的字库是**混合体**——
    · 标准 Big5 槽位：简体字形（旧工程把繁→简映射烘进了字表）
    · 自定义对槽位（lead 0x90-0xA0）：繁体字形（49 个，尾字节撞引擎控制符的字）
  这就是「简繁混合」的根源，而不是什么「原始繁体状态」。

本脚本产出两个自洽的池：
  简体池 = 每个字形都用 zhconv(字符, hans) 渲染
  繁体池 = 每个字形都用字符本身渲染

安全策略（关键）：
  只有「池中现存位图 == 某形的渲染结果」时才认定该字形属于哪一形，
  并对另一套池做替换。两种形都不匹配的字形（cp950 未定义码位、旧工程
  自造符号等）**一律保持原字节**，两套池都不动 —— 绝不猜测、不误伤。

用法：
  python gen_dual_pools.py            # 生成
  python gen_dual_pools.py --dry      # 只统计，不写文件
"""
import os
import re
import sys
import io
import json
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dual_font_lib import (B5_LEAD_MIN, B5_LEAD_MAX, B5_TC, CUST_LEAD_MIN,
                           CUST_LEAD_COUNT, BAD_TRAILS, trail_of_ti,
                           render_mask, arr, read_text)

ROOT = r'G:\Projects\SavenKingdom_II_HD_CHINESE'
SRC = os.path.join(ROOT, 'SavenKingdom_II_HD_CHINESE')
GAME = r'I:\LocalGames\Seven Kingdoms II HD'

PXS = (13, 16, 24)
TOL = 3          # 容错像素数（bit 差）；严格匹配为 0


def load_index(srcdir):
    """读索引表与三个原始池（原始池在 fontdata.h.bak，含 13/16/24）。"""
    t = read_text(os.path.join(srcdir, 'fontdata.h'))
    n = int(re.search(r'#define\s+N_CHARS\s+(\d+)', t).group(1))
    idx = {
        'n': n,
        'big5': arr(t, 'big5idx'),
        'cust': arr(t, 'custidx'),
    }
    for px in PXS:
        idx['goff%d' % px] = arr(t, 'goff%d' % px)
    bak = read_text(os.path.join(srcdir, 'fontdata.h.bak'))
    for px in PXS:
        idx['gpool%d' % px] = arr(bak, 'gpool%d' % px)
    return idx


def build_glyph_char_map(idx, plan_by_gi, verbose=True):
    """建立 glyph 索引 -> 显示字符（繁体形式）的映射。

    三个来源，按可靠性排序：
      1) 标准 Big5 码位引用的字形 —— cp950 解码（最权威）
      2) 仅被自定义对引用的字形 —— 用「危险尾字节候选字」的繁体形位图反查
      3) patch_plan.json 的 current 字段 —— 兜底（已知 51 项）
    """
    n = idx['n']
    big5 = idx['big5']
    gi2ch = {}
    src = {}

    for lead in range(B5_LEAD_MIN, B5_LEAD_MAX + 1):
        base = (lead - B5_LEAD_MIN) * B5_TC
        for ti in range(B5_TC):
            v = big5[base + ti]
            if not v:
                continue
            gi = v - 1
            if gi in gi2ch:
                continue
            try:
                ch = bytes([lead, trail_of_ti(ti)]).decode('cp950')
            except Exception:
                continue
            gi2ch[gi] = ch
            src[gi] = 'std'
    n_std = len(gi2ch)

    # ---- 自定义对：位图反查 ----
    cust = idx['cust']
    cust_glyphs = {}
    for li in range(CUST_LEAD_COUNT):
        base = li * B5_TC
        for ti in range(B5_TC):
            v = cust[base + ti]
            if v:
                cust_glyphs[v - 1] = '%02X%02X' % (CUST_LEAD_MIN + li, trail_of_ti(ti))

    need_reverse = [g for g in cust_glyphs if g not in gi2ch]
    n_from_plan = 0
    if need_reverse:
        # 候选：尾字节为引擎控制符的 Big5 汉字（这些才需要自定义对）
        cands = []
        for lead in range(B5_LEAD_MIN, B5_LEAD_MAX + 1):
            for b2 in BAD_TRAILS:
                try:
                    ch = bytes([lead, b2]).decode('cp950')
                except Exception:
                    continue
                if '\u4e00' <= ch <= '\u9fff':
                    cands.append(ch)
        if verbose:
            print('  危险尾字节候选汉字 = %d' % len(cands))
        # 用 16px 繁体形位图建索引
        index16 = {}
        for ch in cands:
            try:
                index16.setdefault(render_mask(ch, 16), []).append(ch)
            except Exception:
                continue
        pool16 = idx['gpool16']
        go16 = idx['goff16']
        for gi in need_reverse:
            o = go16[gi]
            W, H = pool16[o], pool16[o + 1]
            rb = (W + 7) >> 3
            blob = bytes(pool16[o + 2: o + 2 + rb * H])
            hit = index16.get(blob)
            if hit:
                gi2ch[gi] = hit[0]
                src[gi] = 'cust'
            elif gi in plan_by_gi:
                gi2ch[gi] = plan_by_gi[gi].get('current', '')
                src[gi] = 'plan'
                n_from_plan += 1

    if verbose:
        n_cust = sum(1 for g in src if src[g] == 'cust')
        n_plan = sum(1 for g in src if src[g] == 'plan')
        print('  映射来源: 标准=%d  自定义反查=%d  patch_plan=%d  合计=%d'
              % (n_std, n_cust, n_plan, len(gi2ch)))
    return gi2ch, src, cust_glyphs


def diff_bits(a, b):
    """两个同长字节串的位差异数。"""
    if len(a) != len(b):
        return -1
    d = 0
    for x, y in zip(a, b):
        z = x ^ y
        while z:
            d += z & 1
            z >>= 1
    return d


def classify_and_build(idx, gi2ch, cust_glyphs, verbose=True):
    """判定每个字形的简/繁归属，产出两套池。"""
    import zhconv
    n = idx['n']
    pools = {px: bytearray(idx['gpool%d' % px]) for px in PXS}
    trad_pool = {px: bytearray(idx['gpool%d' % px]) for px in PXS}

    stat = {px: {'simp': 0, 'trad': 0, 'same': 0, 'unknown': 0, 'fail': 0} for px in PXS}
    rec = []          # 明细记录
    t0 = time.time()

    for gi in range(n):
        ch = gi2ch.get(gi)
        if not ch:
            for px in PXS:
                stat[px]['unknown'] += 1
            continue
        s = zhconv.convert(ch, 'zh-hans')
        kinds = {}
        for px in PXS:
            goff = idx['goff%d' % px]
            o = goff[gi]
            base = idx['gpool%d' % px]
            W, H = base[o], base[o + 1]
            rb = (W + 7) >> 3
            ln = 2 + rb * H
            cur = bytes(base[o:o + ln])
            if len(cur) != ln or W < 3:
                stat[px]['fail'] += 1
                kinds[px] = 'fail'
                continue
            if s == ch:
                stat[px]['same'] += 1
                kinds[px] = 'same'
                continue
            px_size = W - 2
            try:
                blob_t = bytes([W, H]) + render_mask(ch, px_size)
            except Exception:
                blob_t = None
            try:
                blob_s = bytes([W, H]) + render_mask(s, px_size)
            except Exception:
                blob_s = None

            # 空白保护：任一方渲染为全空（CJK 扩展区字，simsun 无此字形）
            # 时绝不替换 —— 否则会把一个正常汉字变成空白。
            if (blob_s and not any(blob_s[2:])) or (blob_t and not any(blob_t[2:])):
                stat[px]['unknown'] += 1
                kinds[px] = 'blank'
                continue

            d_t = diff_bits(cur, blob_t) if blob_t else 1 << 30
            d_s = diff_bits(cur, blob_s) if blob_s else 1 << 30
            is_t = (d_t <= TOL) and (d_t < d_s)
            is_s = (d_s <= TOL) and (d_s < d_t)
            if not (is_t or is_s):
                stat[px]['unknown'] += 1
                kinds[px] = 'unknown'
                continue
            if is_s:
                # 现为简体形 → 繁体池改为繁体形
                stat[px]['simp'] += 1
                kinds[px] = 'simponly'
                if blob_t and len(blob_t) == ln:
                    trad_pool[px][o:o + ln] = blob_t
            else:
                # 现为繁体形 → 简体池改为简体形
                stat[px]['trad'] += 1
                kinds[px] = 'tradonly'
                if blob_s and len(blob_s) == ln:
                    pools[px][o:o + ln] = blob_s

        # 明细只记一次（三档一致才算数）
        k16 = kinds.get(16, '')
        if k16 in ('simponly', 'tradonly'):
            allsame = all(kinds.get(px) == k16 for px in PXS)
            rec.append((gi, ch, s, cust_glyphs.get(gi, ''),
                        k16 if allsame else k16 + '(mixed)'))
    if verbose:
        print('  用时 %.1fs' % (time.time() - t0))
        for px in PXS:
            d = stat[px]
            print('  %dpx: 原为简体=%d 原为繁体=%d 简繁同形=%d 无法判定=%d 异常=%d'
                  % (px, d['simp'], d['trad'], d['same'], d['unknown'], d['fail']))
    return pools, trad_pool, stat, rec


def write_pool_file(path, pools, suffix, note):
    """写一个池头文件（含 13/16/24 三个池）。注释用 ASCII，避免 MSVC 代码页问题。"""
    with open(path, 'w', encoding='ascii', newline='\n') as f:
        f.write('/* auto-generated by gen_dual_pools.py -- %s */\n' % note)
        f.write('/* DO NOT EDIT. regenerate: python tools/gen_dual_pools.py */\n')
        for px in PXS:
            data = pools[px]
            f.write('static const unsigned char gpool%d%s[%d] = {' % (px, suffix, len(data)))
            CHUNK = 8192
            for i in range(0, len(data), CHUNK):
                part = data[i:i + CHUNK]
                f.write(','.join(str(b) for b in part))
                f.write(',\n' if i + CHUNK < len(data) else '')
            f.write('};\n')


def build_extra_pools():
    """补充表 fontdata_extra.h 的简繁双份。

    实测这 45 字里有 17 个简繁不同，且当前烤的全是**简体**，
    所以繁体模式下必须换一份繁体字形，否则「寬/課/鳴/緒」会露馅。
    """
    import zhconv
    t = read_text(os.path.join(SRC, 'fontdata_extra.h'))
    codes = arr(t, 'g_extraCode')
    n = len(codes)
    src_pools = {}
    src_offs = {}
    for px in PXS:
        src_pools[px] = arr(t, 'g_extraPool%d' % px)
        src_offs[px] = arr(t, 'g_extraOff%d' % px)

    pools_s = {px: bytearray(src_pools[px]) for px in PXS}
    pools_t = {px: bytearray(src_pools[px]) for px in PXS}
    stat = {px: {'simp': 0, 'trad': 0, 'same': 0, 'unknown': 0} for px in PXS}

    for i, c in enumerate(codes):
        lead, trail = (c >> 8) & 0xFF, c & 0xFF
        try:
            ch = bytes([lead, trail]).decode('cp950')
        except Exception:
            for px in PXS:
                stat[px]['unknown'] += 1
            continue
        s = zhconv.convert(ch, 'zh-hans')
        if s == ch:
            for px in PXS:
                stat[px]['same'] += 1
            continue
        kinds = {}
        for px in PXS:
            pool = src_pools[px]
            o = src_offs[px][i]
            W, H = pool[o], pool[o + 1]
            rb = (W + 7) >> 3
            ln = 2 + rb * H
            cur = bytes(pool[o:o + ln])
            px_size = W - 2
            try:
                blob_t = bytes([W, H]) + render_mask(ch, px_size)
                blob_s = bytes([W, H]) + render_mask(s, px_size)
            except Exception:
                kinds[px] = 'unknown'
                stat[px]['unknown'] += 1
                continue
            if not any(blob_t[2:]) or not any(blob_s[2:]):
                kinds[px] = 'blank'
                stat[px]['unknown'] += 1
                continue
            d_t = diff_bits(cur, blob_t)
            d_s = diff_bits(cur, blob_s)
            if d_s <= TOL and d_s < d_t:
                # 现为简体 → 繁体池补繁体形
                stat[px]['simp'] += 1
                kinds[px] = 'simp'
                if len(blob_t) == ln:
                    pools_t[px][o:o + ln] = blob_t
            elif d_t <= TOL and d_t < d_s:
                stat[px]['trad'] += 1
                kinds[px] = 'trad'
                if len(blob_s) == ln:
                    pools_s[px][o:o + ln] = blob_s
            else:
                stat[px]['unknown'] += 1
                kinds[px] = 'unknown'
    return pools_s, pools_t, stat


def write_extra_file(path, pools, suffix, note):
    """写补充表池文件（含 code 表 + 13/16/24 池）。"""
    src_t = read_text(os.path.join(SRC, 'fontdata_extra.h'))
    codes = arr(src_t, 'g_extraCode')
    with open(path, 'w', encoding='ascii', newline='\n') as f:
        f.write('/* auto-generated by gen_dual_pools.py -- %s */\n' % note)
        f.write('/* DO NOT EDIT. regenerate: python tools/gen_dual_pools.py */\n')
        f.write('#define EXTRA_N_%s %d\n' % (suffix.lstrip('_').upper(), len(codes)))
        f.write('static const unsigned short g_extraCode%s[%d] = {%s};\n'
                % (suffix, len(codes), ','.join(str(v) for v in codes)))
        for px in PXS:
            data = pools[px]
            f.write('static const unsigned int g_extraOff%d%s[%d] = {%s};\n'
                    % (px, suffix, len(codes),
                       ','.join(str(v) for v in arr(src_t, 'g_extraOff%d' % px))))
            f.write('static const unsigned char g_extraPool%d%s[%d] = {'
                    % (px, suffix, len(data)))
            CHUNK = 8192
            for i in range(0, len(data), CHUNK):
                part = data[i:i + CHUNK]
                f.write(','.join(str(b) for b in part))
                f.write(',\n' if i + CHUNK < len(data) else '')
            f.write('};\n')


def main():
    dry = '--dry' in sys.argv
    print('=== 读入现有字库 ===')
    idx = load_index(SRC)
    print('  N_CHARS=%d  big5idx=%d  custidx=%d' % (idx['n'], len(idx['big5']), len(idx['cust'])))
    for px in PXS:
        print('  %dpx: goff=%d pool=%d' % (px, len(idx['goff%d' % px]), len(idx['gpool%d' % px])))

    plan = []
    pp = os.path.join(GAME, 'patch_plan.json')
    if os.path.exists(pp):
        plan = json.load(open(pp, encoding='utf-8'))
    plan_by_gi = {it['glyph']: it for it in plan}
    print('  patch_plan 项数 =', len(plan))

    print()
    print('=== 建立 glyph -> 字符 映射 ===')
    gi2ch, src, cust_glyphs = build_glyph_char_map(idx, plan_by_gi)
    print('  自定义对个数 =', len(cust_glyphs))

    print()
    print('=== 判定简繁并生成双池 ===')
    pools_s, pools_t, stat, rec = classify_and_build(idx, gi2ch, cust_glyphs)

    # ---- 补充表（fontdata_extra.h）双份 ----
    print()
    print('=== 补充表处理 ===')
    ext_s, ext_t, ext_stat = build_extra_pools()
    for px in PXS:
        print('  %dpx: 原为简体=%d 原为繁体=%d 同形=%d 无法判定=%d'
              % (px, ext_stat[px]['simp'], ext_stat[px]['trad'],
                 ext_stat[px]['same'], ext_stat[px]['unknown']))

    # ---- 自检：简体池 16px 应与现有 fontdata_simp.h 完全一致 ----
    print()
    print('=== 自检 ===')
    simp_ref = os.path.join(SRC, 'fontdata_simp.h')
    if os.path.exists(simp_ref):
        ref = arr(read_text(simp_ref), 'gpool16_simp')
        got = list(pools_s[16])
        d = sum(1 for a, b in zip(ref, got) if a != b)
        print('  简体池16px vs 现有 fontdata_simp.h: %s (差异字节 %d)'
              % ('IDENTICAL' if d == 0 else 'DIFFERENT', d))
    trad_ref = os.path.join(SRC, 'fontdata_trad.h')
    if os.path.exists(trad_ref):
        ref = arr(read_text(trad_ref), 'gpool16_trad')
        got = list(pools_t[16])
        d = sum(1 for a, b in zip(ref, got) if a != b)
        print('  繁体池16px vs 现有 fontdata_trad.h: %s (差异字节 %d)'
              % ('IDENTICAL' if d == 0 else 'DIFFERENT(expected)', d))
    for px in PXS:
        d = sum(1 for a, b in zip(pools_s[px], pools_t[px]) if a != b)
        print('  %dpx 简繁两池差异字节 = %d' % (px, d))

    if dry:
        print()
        print('(--dry) 未写文件')
        return

    print()
    print('=== 写出 ===')
    out_s = os.path.join(SRC, 'fontdata_pools_simp.h')
    out_t = os.path.join(SRC, 'fontdata_pools_trad.h')
    write_pool_file(out_s, pools_s, '_simp', 'SIMPLIFIED glyph pools (chslang=1 / lang=simp)')
    write_pool_file(out_t, pools_t, '_trad', 'TRADITIONAL glyph pools (chslang=0 / lang=trad)')
    print('  %s  (%d 字节)' % (out_s, os.path.getsize(out_s)))
    print('  %s  (%d 字节)' % (out_t, os.path.getsize(out_t)))

    out_es = os.path.join(SRC, 'fontdata_extra_simp.h')
    out_et = os.path.join(SRC, 'fontdata_extra_trad.h')
    write_extra_file(out_es, ext_s, '_simp', 'SIMPLIFIED extra glyphs')
    write_extra_file(out_et, ext_t, '_trad', 'TRADITIONAL extra glyphs')
    print('  %s  (%d 字节)' % (out_es, os.path.getsize(out_es)))
    print('  %s  (%d 字节)' % (out_et, os.path.getsize(out_et)))

    # 明细
    det = os.path.join(GAME, 'dual_pool_detail.txt')
    with open(det, 'w', encoding='utf-8') as f:
        f.write('glyph\t字符\t简体\t自定义对\t原形\n')
        for gi, ch, s, cu, kind in rec:
            f.write('%d\t%s\t%s\t%s\t%s\n' % (gi, ch, s, cu or '-', kind))
    print('  %s (%d 条明细)' % (det, len(rec)))


if __name__ == '__main__':
    main()
