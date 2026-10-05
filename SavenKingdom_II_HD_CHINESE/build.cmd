@echo off
REM ============================================================
REM  build.cmd - 一键编译 sk2_zh.asi (x86)
REM  用法：双击运行，或从命令行 build.cmd [Debug^|Release]
REM ============================================================
setlocal
set CFG=%1
if "%CFG%"=="" set CFG=Release

set VCDIR=C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat
if not exist "%VCDIR%" (
  echo [X] 找不到 vcvars32.bat: %VCDIR%
  echo     请用 Visual Studio 命令行工具，或修改本脚本的 VCDIR。
  pause
  exit /b 1
)

call "%VCDIR%"
if errorlevel 1 ( echo [X] vcvars32 执行失败 & pause & exit /b 1 )

cd /d "%~dp0"

REM 删旧产物
if exist obj_test rmdir /s /q obj_test
mkdir obj_test

set CFLAGS=/nologo /c /EHsc /std:c++17 /W3 /utf-8 /D_CRT_SECURE_NO_WARNINGS
set LFLAGS=/nologo /DLL /OUT:sk2_zh.asi /SUBSYSTEM:WINDOWS /OPT:REF /OPT:ICF /MACHINE:X86

set SRCS=pch.cpp core.cpp hooks.cpp cjk.cpp diag.cpp dllmain.cpp
set OBJS=obj_test\pch.obj obj_test\core.obj obj_test\hooks.obj obj_test\cjk.obj obj_test\diag.obj obj_test\dllmain.obj

if /i "%CFG%"=="Debug" (
  set CFLAGS=%CFLAGS% /Od /Zi
  set LFLAGS=%LFLAGS% /DEBUG
) else (
  set CFLAGS=%CFLAGS% /O2 /Oi
  set LFLAGS=%LFLAGS% /RELEASE
)

echo [1/2] 编译...
cl %CFLAGS% /Foobj_test\ %SRCS%
if errorlevel 1 ( echo [X] 编译失败 & pause & exit /b 1 )

echo [2/2] 链接...
link %LFLAGS% %OBJS%
if errorlevel 1 ( echo [X] 链接失败 & pause & exit /b 1 )

echo.
echo [O] 生成成功: %~dp0sk2_zh.asi
echo     复制到游戏目录，并用 ASI Loader 加载。
pause
endlocal
