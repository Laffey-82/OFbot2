@echo off
chcp 65001 > nul
title OFbot 2 安装
cls

echo 开始安装 OFbot 2...

where py >nul 2>nul
if %errorlevel%==0 (
    set PYTHON=py
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        set PYTHON=python
    ) else (
        echo 错误：未找到 Python，请先安装 Python 3.11+ 并加入 PATH。
        pause
        exit /b 1
    )
)

echo 安装依赖...
%PYTHON% -m pip install -r requirements.txt
if errorlevel 1 (
    echo 依赖安装失败。
    pause
    exit /b 1
)

if not exist logs mkdir logs
if not exist data mkdir data
if not exist plugins mkdir plugins

if not exist config.yaml (
    echo 生成默认 config.yaml...
    %PYTHON% -c "from app.core.config import load_settings, save_settings; save_settings(load_settings('config.yaml'))"
    if errorlevel 1 (
        echo 配置生成失败。
        pause
        exit /b 1
    )
)

echo 运行环境自检...
%PYTHON% -m app.cli doctor

echo 安装完成。
echo 请编辑 config.yaml（协议与 Token）后运行 start_bot.bat 启动。
pause
