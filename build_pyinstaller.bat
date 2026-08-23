@echo off
rem ============================================================
rem  在能联网的机器上运行本脚本，生成完全独立的单文件 exe
rem  （不依赖目标机器安装 Python）
rem
rem  python build_pyinstaller.bat
rem  或直接：
rem    pip install pyinstaller
rem    pyinstaller --noconfirm --clean --onefile --windowed --name CoCa main.py
rem    pyinstaller --noconfirm --clean --onefile --console   --name CoCa-cli main.py
rem ============================================================
chcp 65001 >nul
echo 安装 PyInstaller...
pip install pyinstaller
if errorlevel 1 goto :err

echo 构建图形界面版（无控制台）...
pyinstaller --noconfirm --clean --onefile --windowed --name CoCa main.py
if errorlevel 1 goto :err

echo 构建命令行版（带控制台）...
pyinstaller --noconfirm --clean --onefile --console --name CoCa-cli main.py
if errorlevel 1 goto :err

echo.
echo 完成！exe 位于 dist\ 目录：
echo   dist\CoCa.exe      （图形界面，双击运行）
echo   dist\CoCa-cli.exe  （命令行）
goto :eof

:err
echo 构建失败，请检查上面的错误信息。
exit /b 1
