# -*- coding: utf-8 -*-
"""译文 vs 原版：结构与格式骨架校验 + 固定宽度字段「尾巴残留」检测。

为什么要这个
-------------
HD 引擎的文字资源不是纯文本，里面有一层**模板语言**：
    [KEY]文本                     每个条目的键
    %1d %2s %1z %1q               按序取参数的格式码
    %1p{a|b}                      二选一（按参数 1 的单/复数）
    %1z%1q{a|b|c}                 三选一（零/单/复）
    ~                             分页符（help.res / tips.res）
    {} | []  < >                  都是控制字符，**不能被译文吞掉**

旧汉化包的翻译工具只做「整段替换」，因此经常出现：
  1) `%1p{商隊|商隊}` 里的 `|` / `}` 被换成别的字节 → 引擎的 `{` 永不闭合
     → 格式化时把**下一行也吞进字符串**（现象：`...%1d[COMD]指揮官`）
  2) 固定宽度字段（STD.SET 的 16 字节名字表）里，短译文覆写后**没清尾巴**
     （现象：`Rouen` → `恩uen`）

本工具：
  A. 对 update/ 下每个 .res，找同名的原版，逐条目比对「格式骨架」；
  B. 扫描固定宽度字段里的「汉字 + ASCII 字母」残留；
  C. STD.SET 另做专区扫描（race rows / 名字表）。

用法：
    python check_struct.py                 # 全量
    python check_struct.py --only t_reps   # 只看某文件
"""
import os
import re
import sys

GAME = r'I:\LocalGames\Seven Kingdoms II HD'
UP = os.path.join(GAME, 'update', 'Resource')
ORIG = os.path.join(GAME, 'Resource')

# ── Big5 判定 ──────────────────────────────────────────────
def is_std_lead(b):
    return 0xA1 <= b <= 0xF9

def is_std_trail(b):
    return (0x40 <= b <= 0x7E) or (0xA1 <= b <= 0xFE)

def is_cust_lead(b):
    return 0x90 <= b <= 0xA0

def is_ascii_letter(b):
    return (0x41 <= b <= 0x5A) or (0x61 <= b <= 0x7A)

# ── 格式骨架 ───────────────────────────────────────────────
# 提取：全部 %N<type> 码 + 全部控制字符（{ } | [ ] ~）
FMT_RE = re.compile(rb'%[0-9]?[a-zA-Z]')
CTRL_BYTES = b'{}|[]~<>'

def strip_cust(buf):
    """剔除自定义对（0x90-0xA0 领）。

    自定义对是「危险尾汉字」的另一种表示，其**尾字节本身**可能就是 ~ { | } 之一
    （分配表里 0x7E/0x7B/0x7C/0x7D 都在候选尾字节内），若不剔除统计控制符就会
    把 `917E` 这类当成真的分页符 —— 全是误报。
    """
    out = bytearray()
    i = 0
    n = len(buf)
    while i < n:
        b = buf[i]
        if 0x90 <= b <= 0xA0 and i + 1 < n and (
                (0x40 <= buf[i + 1] <= 0x7E) or (0xA1 <= buf[i + 1] <= 0xFE)):
            i += 2
            continue
        out.append(b)
        i += 1
    return bytes(out)


def skeleton(buf):
    """返回 (格式码序列, 控制字符计数)"""
    codes = tuple(FMT_RE.findall(buf))
    c = strip_cust(buf)
    ctrl = {b: c.count(bytes([b])) for b in CTRL_BYTES}
    return codes, ctrl


def split_entries(data):
    """把 .res 按 '[' 开头的行切成 (key, value_bytes)。返回 (前导, [(key, val, 原始)])

    条目从行首 '[' 开始，到下一个行首 '[' 结束。key = '[' 到第一个 ']'。
    保留原始字节以便原样写回。
    """
    lines = data.split(b'\r\n')
    out = []
    cur_key = None
    cur = []
    head = []
    for ln in lines:
        if ln.startswith(b'['):
            if cur_key is not None:
                out.append((cur_key, b'\r\n'.join(cur)))
            else:
                head = []
            rb = ln.find(b']')
            cur_key = ln[:rb + 1] if rb != -1 else ln
            cur = [ln[rb + 1:] if rb != -1 else b'']
        else:
            if cur_key is None:
                head.append(ln)
            else:
                cur.append(ln)
    if cur_key is not None:
        out.append((cur_key, b'\r\n'.join(cur)))
    return b'\r\n'.join(head), out


def scan_stale_tail(buf):
    """找「汉字(2字节) + ASCII 字母」残留。返回命中位置列表。"""
    hits = []
    i = 0
    n = len(buf)
    while i < n - 2:
        b = buf[i]
        if is_std_lead(b) and is_std_trail(buf[i + 1]):
            if is_ascii_letter(buf[i + 2]):
                hits.append((i, buf[i:i + 2], buf[i + 2:i + 14]))
            i += 2
            continue
        if is_cust_lead(b) and is_std_trail(buf[i + 1]):
            if is_ascii_letter(buf[i + 2]):
                hits.append((i, buf[i:i + 2], buf[i + 2:i + 14]))
            i += 2
            continue
        i += 1
    return hits


def check_res(name, only=None):
    op = os.path.join(UP, name)
    ep = os.path.join(ORIG, name)
    if not os.path.exists(ep):
        ep2 = os.path.join(GAME, name)
        ep = ep2 if os.path.exists(ep2) else None
    ours = open(op, 'rb').read()
    if not ep:
        print('  [%s] 找不到原版，跳过骨架比对' % name)
        return
    orig = open(ep, 'rb').read()
    _, oe = split_entries(orig)
    _, ue = split_entries(ours)
    print('=' * 96)
    print('### %s   原版 %d 字节/%d 条目    我方 %d 字节/%d 条目'
          % (name, len(orig), len(oe), len(ours), len(ue)))
    if len(oe) != len(ue):
        print('  [!!] 条目数不一致')
    bad = 0
    for i in range(min(len(oe), len(ue))):
        (ok, ov), (uk, uv) = oe[i], ue[i]
        if ok != uk:
            print('  [!!] #%d 键不一致: 原版 %r / 我方 %r' % (i, ok, uk)); bad += 1; continue
        oc, octrl = skeleton(ov)
        uc, uctrl = skeleton(uv)
        prob = []
        # 格式码按**多重集合**比较：引擎按 %N 取参数，顺序可随语序调整，
        # 但数量与种类必须一致（少一个 %1s 就会读到野参数）。
        if sorted(oc) != sorted(uc):
            prob.append('格式码 %s -> %s' % (list(oc), list(uc)))
        for c in CTRL_BYTES:
            if octrl[c] != uctrl[c]:
                prob.append('%r %d->%d' % (chr(c), octrl[c], uctrl[c]))
        if prob:
            bad += 1
            print('  [!!] #%-3d %-12s %s' % (i, ok.decode('cp950', 'replace'), '; '.join(prob)))
            print('        原: %r' % ov[:80])
            print('        我: %r' % uv[:80])
    if bad == 0:
        print('  [OK] 全部 %d 条目的格式骨架一致' % min(len(oe), len(ue)))
    # 尾巴残留
    hits = scan_stale_tail(ours)
    if hits:
        print('  [!!] 疑似「汉字 + ASCII 尾巴」残留 %d 处：' % len(hits))
        for off, pre, tail in hits[:12]:
            print('        @0x%-6X %02X%02X + %r' % (off, pre[0], pre[1], tail))
    return bad


def scan_stdset():
    p = os.path.join(UP, 'STD.SET')
    if not os.path.exists(p):
        print('(无 STD.SET)'); return
    d = open(p, 'rb').read()
    print('=' * 96)
    print('### STD.SET  %d 字节' % len(d))
    hits = scan_stale_tail(d)
    print('  疑似「汉字 + ASCII 尾巴」残留: %d 处' % len(hits))
    for off, pre, tail in hits[:40]:
        ctx = d[max(0, off - 20):off + 20]
        print('    @0x%-7X %02X%02X(%s) + %-14r   ctx %r'
              % (off, pre[0], pre[1], pre.decode('cp950', 'replace'),
                 tail.decode('latin1'), ctx.decode('cp950', 'replace')))
    if len(hits) > 40:
        print('    ... 其余 %d 处' % (len(hits) - 40))


def main():
    only = None
    if '--only' in sys.argv:
        only = sys.argv[sys.argv.index('--only') + 1].lower()
    names = sorted(f for f in os.listdir(UP) if f.lower().endswith('.res'))
    if only:
        names = [f for f in names if only in f.lower()]
    total = 0
    for nm in names:
        total += check_res(nm, only) or 0
    if not only:
        scan_stdset()
    print()
    print('==== 汇总：格式骨架异常条目 %d 个 ====' % total)


if __name__ == '__main__':
    main()
