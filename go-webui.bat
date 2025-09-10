@echo off
chcp 65001 > nul
setlocal

echo =======================================================================
echo ==                                                                   ==
echo ==                      正在启动 IndexTTS 2 WebUI                     ==
echo ==                 (首次启动时加载模型较慢，请耐心等待)                 ==
echo ==                                                                   ==
echo =======================================================================
echo.

REM --- 设置隔离的 Python 环境 ---
SET PYTHON_PATH=%cd%\.venv\
SET PYTHONHOME=
SET PYTHONPATH=
SET PYTHONEXECUTABLE=%PYTHON_PATH%Scripts\python.exe
SET PATH=%PYTHON_PATH%;%PYTHON_PATH%\Scripts;%PATH%

REM --- 设置模型缓存和其他环境变量 ---
set HF_HOME=%cd%\checkpoints\hf_cache
set HF_ENDPOINT=https://hf-mirror.com

echo [INFO] 使用便携版 Python: %PYTHONEXECUTABLE%
echo [INFO] 模型缓存目录已指向: %HF_HOME%
echo.
echo [INFO] 正在启动程序，请稍候...
echo.

REM --- 直接调用便携版 Python 运行程序 ---
"%PYTHONEXECUTABLE%" -s webui.py

echo.
echo 程序已退出。按任意键关闭此窗口。
pause
endlocal