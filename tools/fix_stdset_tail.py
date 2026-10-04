# -*- coding: utf-8 -*-
"""清理 STD.SET 固定宽度字段里的「英文尾巴残留」。

现象
----
旧汉化包把 16/8 字节固定字段里的英文名**原地覆写**成中文，但中文更短，
后面的英文字母没被清掉，于是：
    Kerassos -> 猛族ssos        (8 字节字段)
    Inn      -> 酒n             ( " )
    Rouen    -> 恩uen
    Sun Tsun -> 子n Tsun
界面上就显示成「恩uen」「堡壘 恩uen」这类乱码。

修复
----
只把**紧贴汉字之后**的 ASCII 字母（连续的字母，可含其后的空格+字母组）改成空格：
  * 绝不改动任何汉字字节（标准对与自定义对都原样保留）；
  * 长度不变（只做字节替换）；
  * 只处理「汉字后面直接跟 ASCII 字母」这一种形状 —— 中文与 ASCII 之间有空格
    的（如 `皮 Yi` 这类原文就带拉丁字母的字段）保持不动。

用法
----
    python fix_stdset_tail.py            # 干跑
    python fix_stdset_tail.py --apply    # 写盘（备份到 res_backup/）
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zhcode

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP = os.path.join(PROJ, 'res_backup')
ROOTS = [
    os.path.join(zhcode.GAME, 'update', 'Resource'),
    os.path.join(PROJ, 'update_res_staged', 'Resource'),
]


def is_letter(b):
    return (0x41 <= b <= 0x5A) or (0x61 <= b <= 0x7A)


def is_space(b):
    return b == 0x20


def walk_chinese(d):
    """DBCS 游走，返回 [(offset, length)]：汉字占用的字节区间（标准对 + 自定义对）"""
    spans = []
    i = 0
    n = len(d)
    while i < n:
        b = d[i]
        if b < 0x80:
            i += 1
            continue
        if i + 1 < n and zhcode.is_cust_pair(b, d[i + 1]):
            spans.append((i, 2))
            i += 2
            continue
        if i + 1 < n and zhcode.is_valid_pair(b, d[i + 1]):
            spans.append((i, 2))
            i += 2
            continue
        i += 1
    return spans


def plan(d):
    """返回 [(off, 原字节, 新字节, 说明)]"""
    fixes = []
    spans = walk_chinese(d)
    n = len(d)
    for off, ln in spans:
        end = off + ln
        if end >= n:
            continue
        if not is_letter(d[end]):
            continue
        # 汉字后紧贴字母 —— 清到「字母 + (空格+字母)* 结束」
        j = end
        blanks = []
        while j < n:
            if is_letter(d[j]):
                blanks.append(j)
                j += 1
                continue
            # 只允许「字母 + 恰好 1 个空格 + 字母」这样的连续残留
            # （如 `子n Tsun`）。间隔更大的说明已经越过字段边界，
            # 再往下清就会误伤后面的关键字（如 HOBGLOB / INN）。
            k = j
            while k < n and is_space(d[k]):
                k += 1
            if k == j + 1 and k < n and is_letter(d[k]) and len(blanks) <= 12:
                blanks.append(j)
                j = k
                continue
            break
        if not blanks:
            continue
        try:
            before = d[max(0, off - 1):off + 1].decode('cp950', 'replace')
        except Exception:
            before = '?'
        fixes.append((off, end, blanks,
                      d[off:end].decode('cp950', 'replace'),
                      bytes(d[b] for b in blanks).decode('latin1')))
    return fixes


def main():
    apply = '--apply' in sys.argv
    for root in ROOTS:
        p = os.path.join(root, 'STD.SET')
        if not os.path.exists(p):
            print('(跳过，不存在) %s' % p)
            continue
        d = open(p, 'rb').read()
        fixes = plan(d)
        print('### %s' % p)
        print('  汉字后紧贴 ASCII 尾巴: %d 处' % len(fixes))
        for off, end, blanks, ch, tail in fixes[:25]:
            ctx = d[max(0, off - 12):off + 24].decode('cp950', 'replace')
            print('    @0x%-7X %s + %-12r  ctx=%r' % (off, ch, tail, ctx))
        if len(fixes) > 25:
            print('    ... 其余 %d 处' % (len(fixes) - 25))
        out = bytearray(d)
        for off, end, blanks, ch, tail in fixes:
            for b in blanks:
                out[b] = 0x20
        # 安全阀：长度不变；所有汉字区间逐字节不变
        assert len(out) == len(d), '长度变了！'
        changed = [i for i in range(len(d)) if d[i] != out[i]]
        assert all(is_letter(d[i]) or is_space(d[i]) for i in changed), '改动了非 ASCII 字节！'
        print('  改动 %d 字节，全部落在 ASCII 字母上，长度不变不变式通过' % len(changed))
        if apply:
            os.makedirs(BACKUP, exist_ok=True)
            bak = os.path.join(BACKUP, 'STD.SET_%s' % os.path.basename(root))
            if not os.path.exists(bak):
                shutil.copy2(p, bak)
            open(p, 'wb').write(bytes(out))
            print('  [写入] %s  (备份 %s)' % (p, bak))
        print()
    if not apply:
        print('(干跑模式，未写盘。加 --apply 执行)')


if __name__ == '__main__':
    main()
