#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Windows 窗口控制 / 点击 / 截图（纯 ctypes，不依赖 pywin32）。"""
import ctypes
import ctypes.wintypes as wt
import time

u = ctypes.windll.user32
g = ctypes.windll.gdi32
k = ctypes.windll.kernel32

SetForegroundWindow = u.SetForegroundWindow
FindWindowW = u.FindWindowW
GetClientRect = u.GetClientRect
ClientToScreen = u.ClientToScreen
GetWindowTextW = u.GetWindowTextW
EnumWindows = u.EnumWindows
IsWindowVisible = u.IsWindowVisible

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("u", _U)]


def _find(title_part=None, cls=None):
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(h, l):
        if not IsWindowVisible(h):
            return True
        buf = ctypes.create_unicode_buffer(256)
        GetWindowTextW(h, buf, 256)
        t = buf.value
        if title_part is None or title_part.lower() in t.lower():
            found.append((h, t))
        return True
    EnumWindows(cb, 0)
    return found


def wait_window(title_part=None, timeout=40, class_name=None):
    """按标题子串或类名等窗口。class_name 优先级更高（游戏窗口类名稳定）。"""
    if class_name:
        h = FindWindowW(class_name, None)
        t0 = time.time()
        while not h and time.time() - t0 < timeout:
            time.sleep(0.5)
            h = FindWindowW(class_name, None)
        if h:
            buf = ctypes.create_unicode_buffer(256)
            GetWindowTextW(h, buf, 256)
            return h, buf.value
        return None, None
    t0 = time.time()
    while time.time() - t0 < timeout:
        for h, t in _find(title_part):
            return h, t
        time.sleep(0.5)
    return None, None


def client_rect(h):
    r = wt.RECT()
    GetClientRect(h, ctypes.byref(r))
    return 0, 0, r.right - r.left, r.bottom - r.top


def click_client(h, cx, cy, scale_x=1.0, scale_y=1.0, delay=0.08):
    """点击窗口客户区坐标（游戏缓冲坐标 -> 客户区）"""
    _, _, cw, ch = client_rect(h)
    sx = int(cx * scale_x)
    sy = int(cy * scale_y)
    pt = wt.POINT(sx, sy)
    ClientToScreen(h, ctypes.byref(pt))
    # 用绝对坐标 SendInput
    sw = u.GetSystemMetrics(0)
    sh = u.GetSystemMetrics(1)
    ax = int(pt.x * 65535 / max(1, sw - 1))
    ay = int(pt.y * 65535 / max(1, sh - 1))

    def send(flags):
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.u.mi.dx = ax
        inp.u.mi.dy = ay
        inp.u.mi.dwFlags = flags | MOUSEEVENTF_ABSOLUTE
        u.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

    SetForegroundWindow(h)
    time.sleep(0.05)
    send(MOUSEEVENTF_MOVE)
    # 注意：下面不要再 import ctypes（会遮蔽模块级 ctypes）
    time.sleep(delay)
    send(MOUSEEVENTF_LEFTDOWN)
    time.sleep(delay)
    send(MOUSEEVENTF_LEFTUP)
    time.sleep(delay)


def move_client(h, cx, cy, scale_x=1.0, scale_y=1.0):
    """把鼠标移到窗口客户区坐标（不点击）"""
    sx = int(cx * scale_x)
    sy = int(cy * scale_y)
    pt = wt.POINT(sx, sy)
    ClientToScreen(h, ctypes.byref(pt))
    sw = u.GetSystemMetrics(0)
    sh = u.GetSystemMetrics(1)
    ax = int(pt.x * 65535 / max(1, sw - 1))
    ay = int(pt.y * 65535 / max(1, sh - 1))
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.u.mi.dx = ax
    inp.u.mi.dy = ay
    inp.u.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
    SetForegroundWindow(h)
    u.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def key(vk, delay=0.08):
    def send(flags):
        inp = INPUT()
        inp.type = 1  # INPUT_KEYBOARD
        inp.u.ki.wVk = vk
        inp.u.ki.dwFlags = flags
        u.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
    send(0)
    time.sleep(delay)
    send(0x0002)  # KEYEVENTF_KEYUP
    time.sleep(delay)


def screenshot(h, path):
    """把窗口客户区截图保存为 BMP（不依赖 PIL）"""
    left, top, cw, ch = client_rect(h)
    hdc = u.GetDC(h)
    mem = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, cw, ch)
    old = g.SelectObject(mem, bmp)
    g.BitBlt(mem, 0, 0, cw, ch, hdc, left, top, 0x00CC0020)  # SRCCOPY
    g.SelectObject(mem, old)
    # 写 BMP
    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint), ("biWidth", ctypes.c_int),
                    ("biHeight", ctypes.c_int), ("biPlanes", ctypes.c_ushort),
                    ("biBitCount", ctypes.c_ushort), ("biCompression", ctypes.c_uint),
                    ("biSizeImage", ctypes.c_uint), ("biXPelsPerMeter", ctypes.c_int),
                    ("biYPelsPerMeter", ctypes.c_int), ("biClrUsed", ctypes.c_uint),
                    ("biClrImportant", ctypes.c_uint)]
    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(bi)
    bi.biWidth = cw
    bi.biHeight = ch
    bi.biPlanes = 1
    bi.biBitCount = 24
    bi.biCompression = 0
    stride = ((cw * 3 + 3) // 4) * 4
    bi.biSizeImage = stride * ch
    buf = ctypes.create_string_buffer(bi.biSizeImage)
    g.GetDIBits(mem, bmp, 0, ch, buf, ctypes.byref(bi), 0)
    with open(path, 'wb') as f:
        hdr = b'BM'
        off = 14 + ctypes.sizeof(bi)
        size = off + bi.biSizeImage
        import struct
        f.write(hdr + struct.pack('<IHHI', size, 0, 0, off))
        f.write(bytes(bi))
        f.write(buf.raw)
    g.DeleteObject(bmp)
    g.DeleteDC(mem)
    u.ReleaseDC(h, hdc)
    return path
