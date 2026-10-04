#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""自动走一段游戏流程，用日志验证渲染。

用法:
    auto_play.py [步骤名...]

步骤（按游戏缓冲坐标，实测自主菜单日志）:
    menu    主菜单
    single  点「單人遊戲」(318,714)
    race    再点「新戰役」(470,714)  -> 种族选择
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import winctl                                             # noqa: E402

GAME = r'I:\LocalGames\Seven Kingdoms II HD'
EXE = os.path.join(GAME, '7K2.exe')
LOG = os.path.join(GAME, 'update', 'sk2_zh.log')
SHOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    'tools', '_shots')

# 游戏缓冲坐标（日志实测）
MENU_SINGLE = (318, 714)
SUB_NEW = (470, 714)
SUB_TRAIN = (337, 714)


def main():
    steps = sys.argv[1:] or ['single', 'race']
    if os.path.exists(LOG):
        os.remove(LOG)
    with open(os.path.join(GAME, 'update', 'stage.txt'), 'w') as f:
        f.write('3')
    os.makedirs(SHOT, exist_ok=True)

    p = subprocess.Popen([EXE], cwd=GAME)
    hwnd = None
    try:
        hwnd, title = winctl.wait_window(class_name='Seven_Kingdoms_2',
                                         timeout=45)
        if not hwnd:
            print('[X] 没找到窗口'); return
        print('[i] 窗口: %r  hwnd=%s' % (title, hwnd))
        x, y, cw, ch = winctl.client_rect(hwnd)
        print('[i] 客户区 %dx%d' % (cw, ch))
        # 实测客户区就是 1280x960，与游戏缓冲 1:1
        sx = cw / 1280.0
        sy = ch / 960.0
        print('[i] 缩放 %.3f %.3f' % (sx, sy))

        time.sleep(6)          # 等主菜单稳定
        winctl.SetForegroundWindow(hwnd)
        for i, st in enumerate(steps):
            pt = {'single': MENU_SINGLE, 'race': SUB_NEW,
                  'train': SUB_TRAIN}.get(st)
            if not pt:
                continue
            print('[i] 步骤 %s -> 点击 %s' % (st, pt))
            winctl.click_client(hwnd, pt[0], pt[1], sx, sy)
            time.sleep(4)
            winctl.screenshot(hwnd, os.path.join(SHOT, 'step%d_%s.bmp' % (i, st)))
        time.sleep(3)
    finally:
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=8)
            except Exception:
                p.kill()
        time.sleep(1)

    if not os.path.exists(LOG):
        print('[X] 无日志'); return
    txt = open(LOG, 'rb').read().decode('utf-8', 'replace')
    print('[i] 日志 %d 字节' % len(txt))
    import re
    pat = re.compile(r'^\[ZH\] (\d+) \w+ f=\w+ ret=\w+ \((\d+),(\d+)\)[^\n]*\r?\n'
                     r'\s+hex ([0-9A-F]+)\r?\n\s+txt ([^\n]*)\r?\n\s+uni ([^\n]*)', re.M)
    n = 0
    print('--- 渲染的中文串 ---')
    for m in pat.finditer(txt):
        idx, x, y, h, t, uni = m.groups()
        n += 1
        bad = '-1' in uni
        print('%s %-46s %s' % ('!!' if bad else '  ', t.strip(), uni.strip()))
    print('--- 共 %d 条 ---' % n)
    for line in txt.splitlines():
        s = line.strip()
        if s.startswith('[X]') or s.startswith('[!]') or 'MISS' in s or 'OEM' in s:
            print('  ' + s)


if __name__ == '__main__':
    main()
