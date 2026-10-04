#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""启动游戏 -> 进入教学关 -> 鼠标依次悬停若干点 -> 截图 + 抓日志。

用法:
    hover_test.py x1,y1 x2,y2 ...
"""
import os
import re
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


def main():
    pts = []
    for a in sys.argv[1:]:
        x, y = a.split(',')
        pts.append((int(x), int(y)))
    if not pts:
        pts = [(710, 483), (690, 558)]

    if os.path.exists(LOG):
        os.remove(LOG)
    with open(os.path.join(GAME, 'update', 'stage.txt'), 'w') as f:
        f.write('3')
    os.makedirs(SHOT, exist_ok=True)

    p = subprocess.Popen([EXE], cwd=GAME)
    try:
        hwnd, title = winctl.wait_window(class_name='Seven_Kingdoms_2', timeout=45)
        if not hwnd:
            print('[X] 没找到窗口'); return
        x, y, cw, ch = winctl.client_rect(hwnd)
        print('[i] 客户区 %dx%d' % (cw, ch))
        time.sleep(14)                    # 等教学关加载完
        winctl.SetForegroundWindow(hwnd)
        for i, (cx, cy) in enumerate(pts):
            print('[i] 悬停 (%d,%d)' % (cx, cy))
            winctl.move_client(hwnd, cx, cy)
            time.sleep(3.0)
            winctl.screenshot(hwnd, os.path.join(SHOT, 'hover%d_%d_%d.bmp' % (i, cx, cy)))
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
    pat = re.compile(r'^\[ZH\] (\d+) (\w+) f=\w+ ret=\w+ \((\d+),(\d+)\)[^\n]*\r?\n'
                     r'\s+hex ([0-9A-F]+)\r?\n\s+txt ([^\n]*)\r?\n\s+uni ([^\n]*)', re.M)
    for m in pat.finditer(txt):
        idx, kind, gx, gy, h, t, uni = m.groups()
        print('%-4s %-5s (%4s,%4s) %-26s %-22s %s'
              % (idx, kind, gx, gy, t.strip(), h, uni.strip()))
    print('--- 关键行 ---')
    for line in txt.splitlines():
        s = line.strip()
        if s.startswith('[X]') or 'MISS' in s or 'OEM' in s:
            print('  ' + s)


if __name__ == '__main__':
    main()
