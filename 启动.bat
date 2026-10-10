@echo off
chcp 65001 >nul
title 街景定位 Street Geolocator 启动器

set "ROOT=C:\Users\yifen\Desktop\project\应用项目\geo-projects\street-geolocator-streetclip"
set "BKDIR=%ROOT%\backend"
set "FTDIR=%ROOT%\frontend"
set "EXTDIR=%ROOT%\browser-extension"
set "PY=python"

echo ============================================
echo   街景定位 Street Geolocator
echo   网页 + 浏览器插件 一键启动
echo ============================================
echo   项目: %ROOT%
echo.

if not exist "%BKDIR%\app\main.py" (
  echo [错误] 未找到项目: %BKDIR%
  echo 请确认项目路径未变动。
  pause
  exit /b 1
)

echo [1/5] 清理占用 8200/5173 端口的旧进程...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8200 " ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173 " ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1

echo [2/5] 启动后端（首次预热 40-90 秒：加载 StreetCLIP / DINOv2）...
start "SG-Backend" cmd /k "cd /d %BKDIR% && %PY% -m uvicorn app.main:app --host 127.0.0.1 --port 8200"

echo [3/5] 启动前端...
start "SG-Frontend" cmd /k "cd /d %FTDIR% && npm run dev"

echo [4/5] 等待后端就绪...
set /a n=0
:WAIT
timeout /t 3 /nobreak >nul
set /a n+=3
curl -s http://127.0.0.1:8200/api/health 2>nul | findstr /c:"\"warming_up\":false" >nul && goto READY
if %n% GEQ 180 goto READY
goto WAIT

:READY
echo [5/5] 打开网页界面...
start http://localhost:5173

echo ============================================
echo  启动完成（等待 %n% 秒）
echo.
echo  网页界面:   http://localhost:5173
echo  后端接口:   http://127.0.0.1:8200
echo.
echo  浏览器插件（网页与插件共用同一后端）:
echo    1. chrome://extensions 打开开发者模式
echo    2. 加载已解压的扩展程序 -^> %EXTDIR%
echo    3. 工具栏点图标 -^> 右侧侧边栏常驻
echo.
echo  关闭本窗口不影响服务；关闭两个服务窗口即停止
echo ============================================
pause
