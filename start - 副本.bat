@echo off
chcp 65001 >nul 2>&1
setlocal

:: ===== 配置 =====
set "ROOT=D:\桌面\trae\C clean\c-drive-scanner"
set "PYTHON=C:\Users\12706\.workbuddy\binaries\python\versions\3.13.12\pythonw.exe"
set "PORT=5001"

:: 切到脚本所在目录，保证相对路径(.env/app.py)正确
pushd "%~dp0" >nul 2>&1

echo [1/3] 正在清理占用端口 %PORT% 的旧进程（python / pythonw）...
:: 按端口精准杀（无论进程名是 python.exe 还是 pythonw.exe）
for /f "tokens=5" %%p in ('netstat -ano 2^>nul ^| findstr /i "127.0.0.1:%PORT% " ^| findstr /i "LISTEN"') do (
  taskkill /pid %%p /f >nul 2>&1
  echo   已结束占用端口的进程 PID %%p
)

echo [2/3] 兜底：清理命令行含 c-drive-scanner 的所有残留 python 进程...
for %%img in (python.exe pythonw.exe) do (
  for /f "tokens=2" %%p in ('tasklist /fi "imagename eq %%img" /fo list 2^>nul ^| findstr /i "PID:"') do (
    wmic process where "ProcessId=%%p" get CommandLine 2^>nul | findstr /i "c-drive-scanner" >nul && (
      taskkill /pid %%p /f >nul 2>&1
      echo   已结束残留进程 PID %%p
    )
  )
)
timeout /t 1 >nul 2>&1

echo [3/3] 启动服务（后台无窗口）...
start "" "%PYTHON%" "%ROOT%\app.py"

:: 轮询等待端口就绪（最多 ~15 秒）；端口已清空，新进程必绑 PORT
set "READY=0"
for /l %%i in (1, 1, 15) do (
  netstat -ano 2>nul | findstr /i "127.0.0.1:%PORT% " | findstr /i "LISTEN" >nul 2>&1
  if not errorlevel 1 (
    set "READY=1"
    goto :OPEN
  )
  timeout /t 1 >nul 2>&1
)

:OPEN
if "%READY%"=="1" (
  echo 服务已就绪，正在打开网页 http://127.0.0.1:%PORT% ...
  start "" "http://127.0.0.1:%PORT%"
) else (
  echo 服务启动超时，请检查 app.py 报错（见 scan_out.log / scan_err.log）
)
popd >nul 2>&1
endlocal
