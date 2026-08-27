@echo off
chcp 65001 >nul 2>&1
setlocal

:: ===== 配置（按需修改）=====
set "ROOT=D:\桌面\trae\C clean\c-drive-scanner"
set "PYTHON=C:\Users\12706\.workbuddy\binaries\python\versions\3.13.12\pythonw.exe"
set "PORT=5001"
set "URL=http://127.0.0.1:%PORT%"

:: 切到脚本所在目录，保证相对路径(.env/app.py)正确
pushd "%~dp0" >nul 2>&1

:: 1) 杀掉所有旧的 scanner 进程，避免占用端口 / 旧逻辑残留
for /f "tokens=2" %%p in ('tasklist /fi "imagename eq python.exe" /fo list 2^>nul ^| findstr /i "PID:"') do (
  for /f "usebackq" %%c in (`wmic process where "ProcessId=%%p" get CommandLine 2^>nul ^| findstr /i "c-drive-scanner"`) do (
    taskkill /pid %%p /f >nul 2>&1
  )
)

:: 2) 用 pythonw 后台启动（无黑窗口）
start "" "%PYTHON%" "%ROOT%\app.py"

:: 3) 轮询等待端口就绪（最多 ~15 秒）
set "READY=0"
for /l %%i in (1,1,15) do (
  netstat -an 2>nul | findstr /i "127.0.0.1:%PORT%" | findstr /i "LISTEN" >nul 2>&1
  if not errorlevel 1 (
    set "READY=1"
    goto :OPEN
  )
  timeout /t 1 >nul 2>&1
)

:OPEN
if "%READY%"=="1" (
  echo 服务已启动，正在打开网页...
  start "" "%URL%"
) else (
  echo 服务启动超时，请检查 app.py 报错（见 scan_out.log / scan_err.log）
)
popd >nul 2>&1
endlocal
