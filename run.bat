@echo off
chcp 65001 >nul
title 路线啵啵机 · Travel Atlas
cd /d "%~dp0"

echo ========================================
echo   路线啵啵机 · Travel Atlas
echo ========================================
echo.

REM 检测 venv 是否已建好
if not exist ".venv\Scripts\python.exe" (
    echo [初次启动] 正在创建虚拟环境 .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo [错误] 创建 venv 失败 —— 请确认已安装 Python 3.10+ 并加入 PATH
        pause
        exit /b 1
    )
)

REM 检测依赖是否已装
if not exist ".venv\Lib\site-packages\flask" (
    echo [初次启动] 正在安装依赖（约 200MB，需要几分钟）...
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败 —— 请检查网络
        pause
        exit /b 1
    )
)

echo [启动] 服务器即将在 http://127.0.0.1:5000 运行
echo [提示] 关闭此窗口或按 Ctrl+C 即可停止
echo.

REM 自动打开浏览器（延迟 3 秒等服务起来）
start "" cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:5000"

.venv\Scripts\python.exe server.py

pause
