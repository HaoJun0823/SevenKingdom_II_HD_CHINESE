#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""启动 7K2.exe，等一段时间，然后结束进程并打印日志要点。

用法:
    run_game.py [等待秒数]       默认 22 秒
"""
import os
import subprocess
import sys
import time

GAME = r'I:\LocalGames\Seven Kingdoms II HD'
EXE = os.path.join(GAME, '7K2.exe')
LOG = os.path.join(GAME, 'update', 'sk2_zh.log')


def main():
    wait = int(sys.argv[1]) if len(sys.argv) > 1 else 22

    if os.path.exists(LOG):
        os.remove(LOG)
    # stage.txt: 3 = 全功能（含 CJK 渲染）
    with open(os.path.join(GAME, 'update', 'stage.txt'), 'w') as f:
        f.write('3')

    print('[i] 启动 %s' % EXE)
    p = subprocess.Popen([EXE], cwd=GAME)
    try:
        for i in range(wait):
            time.sleep(1)
            if p.poll() is not None:
                print('[!] 进程已自行退出，code=%s' % p.returncode)
                break
    finally:
        if p.poll() is None:
            print('[i] 结束进程')
            p.terminate()
            try:
                p.wait(timeout=8)
            except Exception:
                p.kill()
        time.sleep(1)

    if not os.path.exists(LOG):
        print('[X] 没有生成日志')
        return
    txt = open(LOG, 'rb').read().decode('utf-8', 'replace')
    print('[i] 日志 %d 字节' % len(txt))
    for line in txt.splitlines():
        s = line.strip()
        if not s:
            continue
        if (s.startswith('[X]') or s.startswith('[!]')
                or 'OEM' in s or 'MISS' in s or '缺字形' in s
                or 'hook' in s or '差分' in s):
            print('   ' + s)


if __name__ == '__main__':
    main()
