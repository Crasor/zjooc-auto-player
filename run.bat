@echo off
chcp 65001 >nul
cd /d "%~dp0"

:: 尝试 conda 环境的 Python
set PYTHON=
if exist "D:\conda_envs\envs\zjooc\python.exe" (
    set PYTHON=D:\conda_envs\envs\zjooc\python.exe
) else (
    :: 用系统 python
    where python >nul 2>&1 && set PYTHON=python
)

if "%PYTHON%"=="" (
    echo Python not found! Install with: conda create -n zjooc python=3.11
    pause
    exit /b 1
)

%PYTHON% main.py %*
pause
