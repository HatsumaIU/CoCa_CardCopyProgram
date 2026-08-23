# -*- coding: utf-8 -*-
"""
7-Zip 集成模块：自动定位 7z.exe、执行 .7z 压缩并解析进度百分比。

依赖：系统安装 7-Zip（https://www.7-zip.org/）。
"""

import locale
import os
import re
import shutil
import subprocess
import threading

_PCT_RE = re.compile(r"(\d+)\s*%")


def find_7z():
    """自动定位 7z.exe；找不到返回 None。

    依次尝试：环境变量 7Z_EXE -> PATH 中的 7z -> 注册表 7-Zip 安装路径
    -> 常见安装目录（Program Files / Program Files (x86)）。
    """
    candidate = os.environ.get("7Z_EXE")
    if candidate and os.path.isfile(candidate):
        return candidate

    candidate = shutil.which("7z")
    if candidate and os.path.isfile(candidate):
        return candidate

    try:
        import winreg
    except ImportError:
        winreg = None
    if winreg is not None:
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for subkey in (r"SOFTWARE\7-Zip", r"SOFTWARE\WOW6432Node\7-Zip"):
                try:
                    with winreg.OpenKey(hive, subkey) as key:
                        path, _ = winreg.QueryValueEx(key, "Path")
                        exe = os.path.join(path, "7z.exe")
                        if os.path.isfile(exe):
                            return exe
                except OSError:
                    continue

    for env in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env)
        if base:
            exe = os.path.join(base, "7-Zip", "7z.exe")
            if os.path.isfile(exe):
                return exe
    return None


def compress_folder(seven_zip, folder, archive, level=5,
                    progress_cb=None, stop_event=None):
    """
    把 folder 压缩为 .7z 归档（归档内顶层目录为文件夹名）。

    参数：
        seven_zip    7z.exe 路径
        folder       待压缩目录（如 D:\\照片\\2026_08_23）
        archive      输出压缩包路径（如 D:\\照片\\2026_08_23.7z）
        level        压缩级别 0-9
        progress_cb  进度回调 fn(percent: int|None, info: str)，在子线程调用
        stop_event   置位后终止压缩

    返回 (ok, cancelled, error)。
    """
    stop_event = stop_event or threading.Event()

    if not seven_zip or not os.path.isfile(seven_zip):
        return False, False, "未找到 7-Zip（7z.exe），请安装 7-Zip 或在界面中手动指定路径。"
    folder = os.path.abspath(folder)
    if not os.path.isdir(folder):
        return False, False, f"待压缩目录不存在：{folder}"
    archive = os.path.abspath(archive)
    archive_dir = os.path.dirname(archive)
    if archive_dir:
        os.makedirs(archive_dir, exist_ok=True)

    parent = os.path.dirname(folder)
    base = os.path.basename(folder)
    # -bso0: 普通输出到 stdout 关闭；-bsp1: 进度输出到 stdout
    cmd = [seven_zip, "a", "-t7z", f"-mx={level}", "-bso0", "-bsp1",
           archive, base]
    encoding = locale.getpreferredencoding(False) or "utf-8"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        proc = subprocess.Popen(
            cmd, cwd=parent,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding=encoding, errors="replace",
            creationflags=flags)
    except OSError as e:
        return False, False, f"无法启动 7-Zip：{e}"

    try:
        for line in proc.stdout:
            if stop_event.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
                return False, True, "用户取消"
            line = line.strip()
            if not line:
                continue
            match = _PCT_RE.search(line)
            percent = int(match.group(1)) if match else None
            if progress_cb:
                progress_cb(percent, line)
    finally:
        if proc.stdout is not None:
            proc.stdout.close()

    code = proc.wait()
    if code == 0:
        return True, False, None
    return False, False, f"7-Zip 返回错误码 {code}"
