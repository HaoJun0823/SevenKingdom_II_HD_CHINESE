@echo off
REM ============================================================
REM  deploy.cmd - 部署汉化组件到 GOG 版 Seven Kingdoms 2 HD
REM
REM  加载链（重要）：
REM    游戏自带的 dsound.dll 是 MILES 音频引擎，内置 modloader，
REM    它本身就是一个 ASI 加载器，会扫描 scripts\ / plugins\ / update\。
REM    所以【不需要】dinput8.dll —— 之前的 dinput8 方案对本游戏无效，
REM    因为 7K2.exe 导入的是 DINPUT.dll 而非 DINPUT8.dll。
REM
REM  目录约定：
REM    scripts\sk2_zh.asi    汉化插件（modloader 扫描 scripts\）
REM    update\Resource\...  中文资源（modloader 的 OverloadFromFolder）
REM    update\*.log         运行日志
REM
REM  卸载：删除 scripts\ 与 update\ 两个目录即可
REM ============================================================
setlocal

set GAME=I:\LocalGames\Seven Kingdoms II HD
set SRC=%~dp0

if not exist "%GAME%\7K2.exe" (
  echo [X] 未找到 %GAME%\7K2.exe
  echo     请修改本脚本的 GAME 变量为实际游戏目录。
  pause
  exit /b 1
)

if not exist "%SRC%\..\scripts\sk2_zh.asi" (
  echo [X] 缺少 %SRC%..\scripts\sk2_zh.asi
  echo     请先运行 build.cmd 编译，再把产物放到工程根的 scripts\ 下。
  pause
  exit /b 1
)

echo [1/3] 检查 MILES modloader...
if not exist "%GAME%\dsound.dll" (
  echo [X] 未找到 dsound.dll —— 该游戏版本可能不含 MILES modloader。
  echo     请改用 dinput8.dll 方案，或换用其他注入方式。
  pause
  exit /b 1
)
echo       dsound.dll 已就位（会自动加载 scripts\*.asi）

echo [2/3] 投放汉化插件到 scripts\ ...
if not exist "%GAME%\scripts" mkdir "%GAME%\scripts"
copy /y "%SRC%..\scripts\sk2_zh.asi" "%GAME%\scripts\" >nul
echo       scripts\sk2_zh.asi

REM ---- 资源投放分两档，由 deploy.cmd all 显式开启 ----
REM 原因：Stage 3 渲染器未实现前，中文资源会导致 Big5 字节被引擎
REM       当单字节 glyph 查找 -> 满屏乱码。只有渲染器就绪才能投资源。
set WITH_RES=0
if /i "%~1"=="all" set WITH_RES=1

if "%WITH_RES%"=="0" (
  echo [3/3] 跳过中文资源 ^(Stage 3 未完成，投了会乱码^)
  echo       如需强制投放: deploy.cmd all
  if exist "%GAME%\update\Resource" (
    echo       [i] 清理游戏目录里已有的中文资源...
    rmdir /s /q "%GAME%\update\Resource" 2>nul
    rmdir /s /q "%GAME%\update\Campaign" 2>nul
    rmdir /s /q "%GAME%\update\Scenario" 2>nul
  )
) else (
  echo [3/3] 投放中文资源到 update\ ...
  if not exist "%GAME%\update" mkdir "%GAME%\update"
  if exist "%SRC%..\update_res_staged" (
    xcopy /y /s /q /e "%SRC%..\update_res_staged\*" "%GAME%\update\" >nul
    echo       已投放全部中文资源
  ) else (
    echo       [X] 未找到 update_res_staged 目录
  )
)

if exist "%GAME%\dinput8.dll" (
  echo.
  echo [i] 游戏目录存在 dinput8.dll（之前尝试留下的）。
  echo     7K2.exe 导入 DINPUT.dll 而非 DINPUT8.dll，该文件对本游戏无效，
  echo     建议删除：del "%GAME%\dinput8.dll"
)

echo.
echo [O] 部署完成。
echo.
echo     游戏目录 : %GAME%
echo     插件     : scripts\sk2_zh.asi
echo     资源     : update\  (Resource / Campaign / Scenario)
echo     日志     : update\sk2_zh.log
echo.
echo     运行游戏后查看 update\sk2_zh.log
echo     卸载：删除 scripts\ 与 update\ 两个目录
echo.
echo     当前为 Stage 1（只定位不挂钩）
echo     此时游戏应显示【英文原版】，这是正确的
pause
endlocal
