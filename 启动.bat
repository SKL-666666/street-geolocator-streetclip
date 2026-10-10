@echo off
chcp 65001 >nul
title Street Geolocator 启动器

set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
set "BKDIR=%ROOT%\backend"
set "FTDIR=%ROOT%\frontend"
set "PY=python"

echo ====================================
echo   Street Geolocator 启动器
echo ====================================
echo   项目目录: %ROOT%
echo.

echo [1/4] 清理占用 8200/5173 端口的旧进程...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8200 " ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173 " ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1

echo [2/4] 启动后端（首次预热约 40-90 秒：加载 StreetCLIP / DINOv2）...
start "SG-Backend" cmd /k "cd /d %BKDIR% && %PY% -m uvicorn app.main:app --host 127.0.0.1 --port 8200"

echo [3/4] 启动前端...
start "SG-Frontend" cmd /k "cd /d %FTDIR% && npm run dev"

echo [4/4] 等待后端就绪...
set /a n=0
:WAIT
timeout /t 3 /nobreak >nul
set /a n+=3
curl -s http://127.0.0.1:8200/api/health 2>nul | findstr /c:"\"warming_up\":false" >nul && goto READY
if %n% GEQ 180 goto READY
goto WAIT

:READY
start http://localhost:5173
echo ====================================
echo  启动完成（等待 %n% 秒）
echo  前端界面: http://localhost:5173
echo  后端接口: http://127.0.0.1:8200
echo.
echo  浏览器插件: 加载 backend 同级 browser-extension 目录
echo  关闭本窗口不影响服务；关闭两个服务窗口即停止
echo ====================================
pause
