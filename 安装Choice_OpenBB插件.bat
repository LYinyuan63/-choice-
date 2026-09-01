@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  set "QIANJI_PYTHON=.venv\Scripts\python.exe"
) else (
  set "QIANJI_PYTHON=python"
)
%QIANJI_PYTHON% -m pip install -e "extensions\openbb_choice"
if errorlevel 1 goto :failed
%QIANJI_PYTHON% -c "import openbb; openbb.build()"
if errorlevel 1 goto :failed
echo.
echo Choice OpenBB插件已安装并完成OpenBB构建，请重启VS Code和Jupyter内核。
pause
exit /b 0

:failed
echo.
echo 安装或构建失败，请保留上方完整错误信息。
pause
exit /b 1
