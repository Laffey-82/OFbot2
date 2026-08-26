@echo off
chcp 65001 > nul
title OFbot 2
cls

echo 启动 OFbot 2...
echo 提示：按 Ctrl+C 停止，日志在 logs 目录

where py >nul 2>nul
if %errorlevel%==0 (
    py -m app.cli run
) else (
    python -m app.cli run
)

echo.
echo 机器人已停止或异常退出
pause
