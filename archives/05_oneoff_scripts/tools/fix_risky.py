# -*- coding: utf-8 -*-
"""把「危险尾字节」的常用字重新映射为自定义安全对。

背景（来自旧汉化包 docs/问题档案 #10）
--------------------------------------
HD 引擎沿用了 `~`(0x7E) 作为超链接/分页标记，`_`(0x5F) 作为下划线开关。
若某个汉字的 Big5 **尾字节**恰好是 0x7E / 0x7B / 0x7C / 0x7D / 0x5B / 0x5D，
引擎在解析时会把半个字当成控制符 → 字符串被腰斩、后半段字节错位 → 乱码。

旧包的对策：把这批常用字改写为 **自定义安全对**（lead 0x90-0xA0，
Big5 不可能出现，且避开国家色 0x80-0x8F），运行期查 custidx 表还原字形。

本脚本用**旧包自己的 risky_map.py + collect_charset()** 复现同一套分配，
这样生成的自定义对与 fontdata.h 的 custidx 表严格对应。

安全保证
--------
写入前对每一处替换做校验：`GlyphIndex(自定义对) == GlyphIndex(原标准对)`。
任何一处不一致就整体中止，不落盘。

用法：
  python fix_risky.py           预览
  python fix_risky.py --apply   写回（自动备份 .orig）
"""
import os
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)
import render_text as rt

OLD_ROOT = r'I:\LocalGames\Seven Kingdoms II HD\七个王国2'
OLD_TOOLS = os.path.join(OLD_ROOT, 'tools')
GAME = r'I:\LocalGames\Seven Kingdoms II HD'
TARGET_ROOT = os.path.join(GAME, 'update')

RISKY = {0x7E, 0x7B, 0x7C, 0x7D, 0x5B, 0x5D}


def load_risky_map(ft):
    """从我们自己的 fontdata.h 反推 标准危险对 -> 自定义对 的映射。

    为什么不用旧包的 risky_map.py + collect_charset()：
    collect_charset() 依赖旧项目 work\\extract 里的中间产物，现已不完整
    （实测只能复现 2137 字、分配 53 个，与 fontdata.h 的 custidx 不对应）。
    而 render_text.Font.custmap 是「自定义对 -> 等价标准对，且字形索引相同」
    的关系，直接反转即得权威映射 —— 天然与运行期 custidx 表严格一致。
    """
    rev = {}
    for cust, std in ft.custmap.items():
        rev.setdefault(std, cust)
    print('从 fontdata.h 反推映射: %d 条' % len(rev))
    return _RiskyShim(rev)


class _RiskyShim:
    """给 remap_verified 用的薄封装：pair_of(char) -> (lead, trail) 或 None"""
    def __init__(self, rev):
        self.rev = rev

    def pair_of(self, ch):
        try:
            b = ch.encode('cp950')
        except Exception:
            return None
        if len(b) != 2:
            return None
        return self.rev.get((b[0], b[1]))


def find_risky_files():
    out = []
    for dp, _, fs in os.walk(TARGET_ROOT):
        for f in fs:
            if f.lower().endswith(('.log', '.ini', '.bak', '.prev', '.txt')):
                continue
            p = os.path.join(dp, f)
            d = open(p, 'rb').read()
            i, n, c = 0, len(d), 0
            while i < n - 1:
                b = d[i]
                if 0xA1 <= b <= 0xF9 and ((0x40 <= d[i + 1] <= 0x7E) or (0xA1 <= d[i + 1] <= 0xFE)):
                    if d[i + 1] in RISKY:
                        c += 1
                    i += 2
                    continue
                i += 1
            if c:
                out.append((p, c))
    return out


def remap_verified(ft, risky, data):
    """按 risky_map 的分配做替换，并逐处校验字形一致。返回 (新数据, 替换数, 未覆盖)"""
    out = bytearray(data)
    n_repl = 0
    uncovered = {}
    i, n = 0, len(out)
    while i < n - 1:
        b = out[i]
        if 0xA1 <= b <= 0xF9:
            t = out[i + 1]
            if ((0x40 <= t <= 0x7E) or (0xA1 <= t <= 0xFE)) and t in RISKY:
                try:
                    ch = bytes(out[i:i + 2]).decode('cp950')
                except Exception:
                    i += 2
                    continue
                pair = risky.pair_of(ch)
                if not pair:
                    uncovered[ch] = uncovered.get(ch, 0) + 1
                    i += 2
                    continue
                # 关键校验：替换前后必须是同一个字形
                g_old = ft.glyph(b, t)
                g_new = ft.glyph(pair[0], pair[1])
                if g_old is None or g_old != g_new:
                    raise SystemExit(
                        '校验失败：%s %02X%02X(字形%s) -> %02X%02X(字形%s)'
                        % (ch, b, t, g_old, pair[0], pair[1], g_new))
                out[i], out[i + 1] = pair
                n_repl += 1
                i += 2
                continue
        i += 1
    return bytes(out), n_repl, uncovered


def main():
    apply_ = '--apply' in sys.argv
    ft = rt.Font()
    risky = load_risky_map(ft)

    files = find_risky_files()
    print()
    print('含危险尾字节的文件 %d 个:' % len(files))
    total_repl = 0
    all_uncovered = {}
    results = []
    for p, c in files:
        data = open(p, 'rb').read()
        new, n_repl, unc = remap_verified(ft, risky, data)
        assert len(new) == len(data)
        results.append((p, data, new, c, n_repl))
        total_repl += n_repl
        for k, v in unc.items():
            all_uncovered[k] = all_uncovered.get(k, 0) + v
        print('   %-44s 危险 %-5d -> 已重映射 %-5d' %
              (os.path.relpath(p, TARGET_ROOT), c, n_repl))

    print()
    print('合计重映射 %d 处' % total_repl)
    if all_uncovered:
        print('以下字在旧包分配里没有自定义对，保持原样（旧包同样未覆盖）：')
        for ch, c in sorted(all_uncovered.items(), key=lambda x: -x[1]):
            try:
                b = ch.encode('cp950')
                print('   %s %02X%02X ×%d' % (ch, b[0], b[1], c))
            except Exception:
                print('   %s ×%d' % (ch, c))
    else:
        print('所有危险字都已覆盖 ✓')

    print()
    print('   映射表 %d 条（示例: %s）' % (
        len(risky.rev),
        '  '.join('%02X%02X->%02X%02X' % (k[0], k[1], v[0], v[1])
                  for k, v in list(sorted(risky.rev.items()))[:6])))

    if not apply_:
        print()
        print('（预览模式，未写盘。加 --apply 生效）')
        return

    for p, data, new, c, n_repl in results:
        if n_repl == 0:
            continue
        bak = p + '.orig'
        if not os.path.exists(bak):
            open(bak, 'wb').write(data)
        open(p, 'wb').write(new)
    print()
    print('[OK] 已写回 %d 个文件（原文件备份为 *.orig）'
          % sum(1 for r in results if r[4] > 0))


if __name__ == '__main__':
    main()
