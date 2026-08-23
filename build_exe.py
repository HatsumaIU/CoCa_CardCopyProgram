# -*- coding: utf-8 -*-
"""
用 Windows 自带 .NET Framework 的 csc.exe 编译 exe 启动器（无需联网、无需 pip）。

用法：python build_exe.py
输出：dist\\CoCa.exe（图形界面） 和 dist\\CoCa-cli.exe（命令行）

说明：
  这两个 exe 是启动器，运行时会自动找到同目录/上级目录的 main.py，
  并用本机 Python（pythonw.exe / python.exe）启动程序，因此目标机器仍需安装 Python 3。
  若需要不依赖 Python 的完全独立 exe，请在能联网的机器上运行 build_pyinstaller.bat。
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CSC = r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
DIST = os.path.join(HERE, "dist")


def build(name, target, refs, source):
    out = os.path.join(DIST, name)
    cmd = [CSC, "/nologo", f"/target:{target}", f"/out:{out}"]
    # 程序图标（icon.ico 与脚本同目录）
    icon = os.path.join(HERE, "icon.ico")
    if os.path.isfile(icon):
        cmd.append(f"/win32icon:{icon}")
    for r in refs:
        cmd.append(f"/r:{r}")
    cmd.append(os.path.join(HERE, source))
    print("编译:", name)
    result = subprocess.run(cmd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.stdout.strip():
        print(result.stdout)
    if result.stderr.strip():
        print(result.stderr)
    if result.returncode != 0 or not os.path.isfile(out):
        print(f"编译失败：{name}")
        sys.exit(1)
    print(f"完成：{out}")


def main():
    if not os.path.isfile(CSC):
        print(f"未找到 csc.exe：{CSC}")
        sys.exit(1)
    os.makedirs(DIST, exist_ok=True)
    build("CoCa.exe", "winexe", ["System.Windows.Forms.dll"], "gui_launcher.cs")
    build("CoCa-cli.exe", "exe", [], "cli_launcher.cs")
    print("\n构建完成。exe 位于 dist\\ 目录。")


if __name__ == "__main__":
    main()
