# -*- coding: utf-8 -*-
"""
构建 CoCa_Setup.exe。
安装包内嵌：应用运行文件 + 卸载程序 + 图标。缺失依赖时由程序弹窗引导到官网自行下载。

用法：python build_setup.py
输出：release\\CoCa_Setup.exe
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CSC = r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
DIST = os.path.join(HERE, "dist")
RELEASE = os.path.join(HERE, "release")


def build(name, target, refs, source, resources, icon):
    out = os.path.join(RELEASE, name)
    cmd = [CSC, "/nologo", f"/target:{target}", f"/out:{out}", f"/win32icon:{icon}"]
    for r in refs:
        cmd.append(f"/r:{r}")
    for src, res in resources:
        cmd.append(f"/resource:{src},{res}")
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
    os.makedirs(RELEASE, exist_ok=True)
    icon = os.path.join(HERE, "icon.ico")
    resources = [
        ("main.py", "main.py"),
        ("copier.py", "copier.py"),
        ("archive.py", "archive.py"),
        ("config.py", "config.py"),
        ("glass.py", "glass.py"),
        (os.path.join(DIST, "CoCa.exe"), "CoCa.exe"),
        (os.path.join(HERE, "_uninstall_tmp.exe"), "CoCa_Uninstall.exe"),
        (os.path.join(HERE, "icon.ico"), "icon.ico"),
    ]
    build("CoCa_Setup.exe", "winexe", ["System.Windows.Forms.dll"],
          "installer.cs", resources, icon)


if __name__ == "__main__":
    main()
