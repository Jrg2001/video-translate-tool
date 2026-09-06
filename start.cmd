@echo off
setlocal
chcp 65001 >nul
title Video Translate Tool
cd /d "%~dp0"
if errorlevel 1 goto directory_error

set "APP_PYTHON="
set "APP_PYTHON_ARGS="
if exist ".venv\Scripts\python.exe" (
    set "APP_PYTHON=%~dp0.venv\Scripts\python.exe"
    goto check_python
)
if exist "venv\Scripts\python.exe" (
    set "APP_PYTHON=%~dp0venv\Scripts\python.exe"
    goto check_python
)
where python >nul 2>&1
if not errorlevel 1 (
    set "APP_PYTHON=python"
    goto check_python
)
where py >nul 2>&1
if not errorlevel 1 (
    set "APP_PYTHON=py"
    set "APP_PYTHON_ARGS=-3"
    goto check_python
)
goto python_error

:check_python
"%APP_PYTHON%" %APP_PYTHON_ARGS% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 goto python_error

"%APP_PYTHON%" %APP_PYTHON_ARGS% -c "import streamlit, faster_whisper, budoux, openai"
if errorlevel 1 (
    echo.
    echo [启动失败] 当前 Python 环境缺少依赖，或依赖无法加载。请先执行：
    echo "%APP_PYTHON%" %APP_PYTHON_ARGS% -m pip install -r "%~dp0requirements.txt"
    goto failed
)

echo.
echo 正在启动 Video Translate Tool，浏览器将自动打开。
echo 如果没有自动打开，请访问：http://localhost:8501
echo 使用期间请保留本窗口，关闭本窗口即可停止服务。
echo.
"%APP_PYTHON%" %APP_PYTHON_ARGS% -m streamlit run "%~dp0app.py" --server.address=127.0.0.1 --server.port=8501 --server.headless=false
if errorlevel 1 (
    echo.
    echo 服务已中断或启动失败，请查看上方提示。
    goto failed
)
exit /b 0

:python_error
echo.
echo [启动失败] 未找到可用的 Python 3.10 或更新版本。
echo 请安装 Python 并勾选 Add Python to PATH，然后重新双击本脚本。
echo 本脚本优先使用项目中的 .venv 或 venv 虚拟环境。
goto failed

:directory_error
echo [启动失败] 无法进入项目目录，请检查脚本所在位置及访问权限。

:failed
echo.
pause
exit /b 1
