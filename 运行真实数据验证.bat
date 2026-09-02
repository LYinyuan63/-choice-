@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "clients\自动获取验证数据.py"
) else (
  python "clients\自动获取验证数据.py"
)
echo.
pause
