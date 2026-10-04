#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""游戏内自动导航：按逻辑坐标点击 + 截图。

用法：
  nav.py shot <name>                 只截图
  nav.py click <x> <y> <name>        点击逻辑坐标后截图
  nav.py seq  x,y,label ...          连续点击并逐步截图

逻辑坐标系 = 游戏内部缓冲（日志里的 put 坐标），按客户区尺寸等比映射。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import winctl  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_nav')
os.makedirs(OUT, exist_ok=True)

# 日志里 put 的坐标系（见 ScreenW/ScreenH：dword_6862A4/6862A8）
LOGIC_W, LOGIC_H = 1280.0, 960.0


def get_win():
    h, t = winctl.wait_window(class_name='Seven_Kingdoms_2', timeout=20)
    if not h:
        raise SystemExit('[X] 找不到游戏窗口')
    return h


def scales(h):
    _, _, cw, ch = winctl.client_rect(h)
    return cw / LOGIC_W, ch / LOGIC_H, cw, ch


def shot(h, name):
    p = os.path.join(OUT, name + '.bmp')
    winctl.screenshot(h, p)
    print('[i] 截图 %s' % p)
    return p


def main():
    h = get_win()
    sx, sy, cw, ch = scales(h)
    print('[i] hwnd=%s 客户区=%dx%d 缩放=%.3f,%.3f' % (h, cw, ch, sx, sy))

    args = sys.argv[1:]
    if not args:
        shot(h, 'now')
        return

    cmd = args[0]
    if cmd == 'shot':
        shot(h, args[1] if len(args) > 1 else 'shot')
    elif cmd == 'click':
        x, y = int(args[1]), int(args[2])
        name = args[3] if len(args) > 3 else 'click_%d_%d' % (x, y)
        winctl.click_client(h, x, y, sx, sy)
        time.sleep(1.2)
        shot(h, name)
    elif cmd == 'seq':
        for i, spec in enumerate(args[1:]):
            parts = spec.split(',')
            x, y = int(parts[0]), int(parts[1])
            label = parts[2] if len(parts) > 2 else 'step%d' % i
            winctl.move_client(h, x, y, sx, sy)
            time.sleep(0.35)
            winctl.click_client(h, x, y, sx, sy)
            time.sleep(1.6)
            shot(h, '%02d_%s' % (i, label))
    elif cmd == 'move':
        x, y = int(args[1]), int(args[2])
        name = args[3] if len(args) > 3 else 'move'
        winctl.move_client(h, x, y, sx, sy)
        time.sleep(0.8)
        shot(h, name)
    else:
        print('unknown cmd', cmd)


if __name__ == '__main__':
    main()
