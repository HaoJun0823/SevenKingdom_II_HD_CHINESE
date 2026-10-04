# -*- coding: utf-8 -*-
"""修复模板资源里的结构损坏（幻影对 / 控制符丢失）。

两类问题
--------
A. 「幻影对」——旧包编码器错位一格，把 `[汉字尾字节][模板控制符]` 当成了一个
   Big5 对并重映射，导致 `|`/`}` 被吞掉、且多出一个错误的字。
   → 长度不变，原地还原为 `[汉字领][汉字尾][控制符]`（zhcode.scan_phantom）。

B. 含**无法反解的自定义对**（9175/9177/9244/925A —— 这些字形在标准 Big5 表里
   查不到对应码位，无法机械还原）→ 用 MANUAL 表整条重写原文，再用
   zhcode.encode_zh() 正确编码（危险尾字自动走自定义对，控制符保持原样）。

安全阀
------
落盘前对**每个条目**校验「格式骨架」与原版英文一致：
  * `%Nd %Ns %Nz %Nq %Np` 等格式码的多重集合必须相同；
  * `{}` `|` `[]` `~` 等控制符计数必须相同。
任一条目不符 → 整体拒绝写盘（除非 --force）。

用法
----
    python fix_template.py            # 干跑，打印将要做的修改
    python fix_template.py --apply    # 真正写盘（自动备份到项目 res_backup/）
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zhcode
import check_struct as cs

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP = os.path.join(PROJ, 'res_backup')

ROOTS = [
    os.path.join(zhcode.GAME, 'update', 'Resource'),      # 部署目标
    os.path.join(PROJ, 'update_res_staged', 'Resource'),  # 工程暂存（进 git）
]

# ── B 类：整条重写 ────────────────────────────────────────
# (文件名, 条目键, 新的中文内容)  —— 键里的 `[` `]` 不要写
MANUAL = [
    ('t_reps.res', b'[TCTZ]', '%1p{平民|平民}總數﹕%1d'),
    ('t_reps.res', b'[TPEA]', '%1p{農民|農民}總數﹕%1d'),
    ('t_reps.res', b'[DUHM]', '%1z%1q{|小時|小時}%2d%2p{分鐘|分鐘}'),
    ('t_news.res', b'[<town name>,<number>,<nation name>TRBL]',
     '%2d個%2p{農民|農民}在%1s(%3s)%2p{進行|進行}叛亂。 '),
]


def fix_bytes(d, name):
    """返回 (新字节, 自动还原处数, 重写条目数, 说明列表)"""
    notes = []
    ph = zhcode.scan_phantom(d)
    if ph:
        out = bytearray(d)
        for off, X, L, T, Y, ctrl in ph:
            out[off + 1] = Y
            out[off + 2] = ctrl
            try:
                ch = bytes((X, Y)).decode('cp950')
            except Exception:
                ch = '?'
            notes.append('  [还原] @0x%-6X  %02X+%02X%02X -> %02X %02X %02X (%s%c)'
                         % (off, X, L, T, X, Y, ctrl, ch, chr(ctrl)))
        d = bytes(out)

    n_manual = 0
    for fn, key, text in MANUAL:
        if fn != name:
            continue
        val = zhcode.encode_zh(text)
        head, entries = cs.split_entries(d)
        rebuilt = []
        hit = False
        for k, v in entries:
            if k == key:
                rebuilt.append((k, val))
                hit = True
                notes.append('  [重写] %s  %r -> %r' % (key.decode('cp950', 'replace'),
                                                        v[:50], val[:50]))
            else:
                rebuilt.append((k, v))
        if hit:
            d = head + b'\r\n'.join(k + v for k, v in rebuilt) if head else b'\r\n'.join(k + v for k, v in rebuilt)
            # split_entries 丢掉行尾，这里按原格式重组
            d = b'\r\n'.join(k + v for k, v in rebuilt)
            n_manual += 1
        else:
            notes.append('  [!] 未找到条目 %s' % key.decode('cp950', 'replace'))
    return d, len(ph), n_manual, notes


def verify(name, d):
    """与同名的原版比格式骨架，返回不匹配条目列表"""
    op = os.path.join(zhcode.ORIG, name)
    if not os.path.exists(op):
        return None
    orig = open(op, 'rb').read()
    _, oe = cs.split_entries(orig)
    _, ue = cs.split_entries(d)
    bad = []
    if len(oe) != len(ue):
        bad.append(('条目数', len(oe), len(ue)))
    for i in range(min(len(oe), len(ue))):
        (ok, ov), (uk, uv) = oe[i], ue[i]
        if ok != uk:
            bad.append((i, '键不符 %r/%r' % (ok, uk)))
            continue
        oc, octrl = cs.skeleton(ov)
        uc, uctrl = cs.skeleton(uv)
        if sorted(oc) != sorted(uc):
            bad.append((i, ok, '格式码 %s -> %s' % (list(oc), list(uc))))
        for c in cs.CTRL_BYTES:
            if octrl[c] != uctrl[c]:
                bad.append((i, ok, '%r %d->%d' % (chr(c), octrl[c], uctrl[c])))
    return bad


def main():
    apply = '--apply' in sys.argv
    force = '--force' in sys.argv
    names = sorted(f for f in os.listdir(ROOTS[0]) if f.lower().endswith('.res'))
    total_ph = total_mn = 0
    for nm in names:
        src = os.path.join(ROOTS[0], nm)
        d = open(src, 'rb').read()
        new, nph, nmn, notes = fix_bytes(d, nm)
        if not notes:
            continue
        print('### %s' % nm)
        for n in notes:
            print(n)
        bad = verify(nm, new)
        if bad is None:
            print('  (无同名校验基准，跳过结构校验)')
        elif bad:
            print('  [!!] 结构校验未通过：')
            for b in bad[:10]:
                print('       %s' % (b,))
            if not force:
                print('  -> 拒绝写盘（需要 --force 才能跳过校验）')
                continue
        else:
            print('  [OK] 结构校验通过（全部条目骨架与原版一致）')
        total_ph += nph
        total_mn += nmn
        if apply:
            os.makedirs(BACKUP, exist_ok=True)
            for root in ROOTS:
                p = os.path.join(root, nm)
                if not os.path.exists(p):
                    continue
                bak = os.path.join(BACKUP, '%s_%s' % (nm, os.path.basename(root)))
                if not os.path.exists(bak):
                    shutil.copy2(p, bak)
                open(p, 'wb').write(new)
                print('  [写入] %s  (备份 %s)' % (p, bak))
        print()
    print('==== 自动还原幻影对 %d 处，整条重写 %d 条 ====' % (total_ph, total_mn))
    if not apply:
        print('(干跑模式，未写盘。加 --apply 执行)')


if __name__ == '__main__':
    main()
