@echo off
REM ============================================================
REM  play.cmd - 按指定阶段启动游戏
REM
REM  用法：
REM    play.cmd          Stage 1  只定位自检（默认，不打补丁，画面无变化）
REM    play.cmd 2        Stage 2  挂钩 text_width（含离线自测）
REM
REM  阶段通过 update\stage.txt 传给插件（比环境变量可靠，
REM  start 启动的子进程不一定继承环境变量）
REM
REM  日志： update\sk2_zh.log
REM ============================================================
setlocal

set STAGE=%1
if "%STAGE%"=="" set STAGE=1

set GAME=I:\LocalGames\Seven Kingdoms II HD

if not exist "%GAME%\7K2.exe" (
  echo [X] 未找到 %GAME%\7K2.exe
  echo     请修改 play.cmd 里的 GAME 变量。
  pause
  exit /b 1
)

if not exist "%GAME%\scripts\sk2_zh.asi" (
  echo [X] 未找到 scripts\sk2_zh.asi，请先运行 deploy.cmd
  pause
  exit /b 1
)

if not exist "%GAME%\update" mkdir "%GAME%\update"

REM 写阶段文件
echo %STAGE%> "%GAME%\update\stage.txt"

REM 清掉旧日志，便于只看本次
if exist "%GAME%\update\sk2_zh.log" del "%GAME%\update\sk2_zh.log"

echo [i] 阶段已写入 update\stage.txt = %STAGE%
echo.
if "%STAGE%"=="1" (
  echo     Stage 1：只定位自检，不打补丁。
  echo     画面与原版【完全一致】是正常的。
) else (
  echo     Stage %STAGE%：将挂钩 text_width。
  echo     资源仍为英文，排版可能有细微变化。
)
echo.
echo     日志: %GAME%\update\sk2_zh.log
echo.
start "" "%GAME%\7K2.exe"
endlocal
