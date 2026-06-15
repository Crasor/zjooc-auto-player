@echo off
chcp 65001 >nul
cd /d "%~dp0"
D:\conda_envs\envs\zjooc\python.exe main.py %*
pause
