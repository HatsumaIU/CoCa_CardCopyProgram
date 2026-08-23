# -*- coding: utf-8 -*-
"""
核心拷贝逻辑：扫描源目录 -> 按格式分类 -> 建日期目录 -> 拷贝 -> 可选校验。

目标目录结构：
    目标根目录/
    └── 2026_08_23/            （日期文件夹，格式 yyyy_MM_dd）
        ├── 原图/              （原始照片）
        │   ├── JPG/           （按格式分类，如 .jpg -> JPG）
        │   ├── RAW/           （如 .nef -> RAW）
        │   ├── PNG/
        │   └── ...
        └── 修图/              （留给后期处理后的照片，初始为空）
"""

import hashlib
import os
import shutil
import threading
from datetime import date

from config import DATE_PATTERN, EDITED_FOLDER, FORMAT_MAP, ORIGINAL_FOLDER, UNKNOWN_FOLDER


# --------------------------------------------------------------------------
# 工具函数
# --------------------------------------------------------------------------

def classify(ext: str) -> str:
    """根据扩展名（可带点、大小写不限）返回分类文件夹名。"""
    return FORMAT_MAP.get(ext.lower().lstrip("."), UNKNOWN_FOLDER)


def today_str() -> str:
    """返回 yyyy_MM_dd 格式的今天日期，例如 2026_08_23。"""
    return date.today().strftime(DATE_PATTERN)


def human_size(nbytes) -> str:
    """把字节数格式化成人类可读大小。"""
    size = float(nbytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{nbytes} B"


def scan_files(root: str) -> list:
    """递归扫描目录，返回所有文件的绝对路径列表。"""
    files = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            files.append(os.path.join(dirpath, name))
    return files


def scan_images(root: str) -> list:
    """递归扫描目录，返回图片/视频文件列表，元素为 (路径, 格式文件夹名, 扩展名)。

    仅包含 FORMAT_MAP 中已识别的格式（用于预览页等场景）。
    """
    items = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            ext = os.path.splitext(name)[1].lstrip(".").lower()
            if ext in FORMAT_MAP:
                items.append((os.path.join(dirpath, name), FORMAT_MAP[ext], ext))
    return items


def build_dest_tree(dest_root: str, date_dir: str) -> dict:
    """创建 日期/原图/<格式> 与 日期/修图 目录，返回相关路径。"""
    date_path = os.path.join(dest_root, date_dir)
    original = os.path.join(date_path, ORIGINAL_FOLDER)
    edited = os.path.join(date_path, EDITED_FOLDER)
    os.makedirs(original, exist_ok=True)
    os.makedirs(edited, exist_ok=True)
    return {"date": date_path, "original": original, "edited": edited}


def sha256(path: str, chunk: int = 1024 * 1024) -> str:
    """计算文件 SHA-256（分块读取，节省内存）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


# --------------------------------------------------------------------------
# 拷贝器
# --------------------------------------------------------------------------

class CameraCopier:
    """
    相机拷卡拷贝器。

    参数：
        source         源目录（相机存储卡，如 D:\\ 或 D:\\DCIM）
        dest_root      目标根目录
        date_dir       日期文件夹名，默认今天（yyyy_MM_dd）
        verify         拷贝后是否做 Hash 校验（较慢）
        skip_existing  目标已有同名文件时是否跳过（False 则覆盖）
        copy_unknown   是否拷贝未识别格式的文件（放入「其他」文件夹）
        callback       进度回调 fn(event: dict)，在工作线程中调用
    """

    def __init__(self, source, dest_root, date_dir=None, verify=False,
                 skip_existing=True, copy_unknown=True, callback=None):
        self.source = os.path.abspath(source)
        self.dest_root = os.path.abspath(dest_root)
        self.date_dir = date_dir or today_str()
        self.verify = verify
        self.skip_existing = skip_existing
        self.copy_unknown = copy_unknown
        self.callback = callback
        self._stop = threading.Event()
        self.total_files = 0
        self._written = set()  # 本次运行已写入的目标路径（用于同名去重）
        self.summary = {
            "copied": 0,
            "skipped": 0,
            "failed": 0,
            "verified": 0,
            "mismatch": 0,
            "total_bytes": 0,
            "by_format": {},
            "failed_list": [],
        }

    # -- 对外控制 ---------------------------------------------------------

    def stop(self):
        """请求停止（下一次文件拷贝前生效）。"""
        self._stop.set()

    # -- 内部辅助 ---------------------------------------------------------

    def _notify(self, **kw):
        if self.callback:
            try:
                self.callback(kw)
            except Exception:
                pass

    def _unique_dest(self, folder: str, filename: str) -> str:
        """同格式下不同子目录可能出现同名文件，重名时追加 _1、_2 后缀。"""
        base, ext = os.path.splitext(filename)
        candidate = os.path.join(folder, filename)
        n = 1
        while os.path.exists(candidate):
            candidate = os.path.join(folder, f"{base}_{n}{ext}")
            n += 1
        return candidate

    def _copy_one(self, src: str, folder: str, idx: int):
        name = os.path.basename(src)
        fmt = classify(os.path.splitext(name)[1])
        dst = os.path.join(folder, name)

        # 本次运行已写过同名文件（例如不同子目录同名）→ 追加后缀保留两者
        if dst in self._written:
            dst = self._unique_dest(folder, name)
        elif os.path.exists(dst) and self.skip_existing:
            # 目标盘上原本就有该文件且选择跳过
            self.summary["skipped"] += 1
            self._notify(type="file", current=idx, total=self.total_files,
                         name=name, status="skipped", src=src, dst=dst)
            return
        # 其余情况：目标不存在，或覆盖模式下直接覆盖

        try:
            shutil.copy2(src, dst)  # copy2 保留修改时间等元数据
            self._written.add(dst)
            self.summary["copied"] += 1
            size = os.path.getsize(src)
            self.summary["total_bytes"] += size
            self.summary["by_format"][fmt] = self.summary["by_format"].get(fmt, 0) + 1
            status = "copied"

            if self.verify:
                self._notify(type="log", message=f"正在校验：{name}")
                if sha256(src) != sha256(dst):
                    self.summary["mismatch"] += 1
                    self.summary["failed_list"].append((src, dst, "Hash 校验不一致"))
                    status = "mismatch"
                else:
                    self.summary["verified"] += 1

            self._notify(type="file", current=idx, total=self.total_files,
                         name=name, status=status, src=src, dst=dst)
        except OSError as e:
            self.summary["failed"] += 1
            self.summary["failed_list"].append((src, dst, str(e)))
            self._notify(type="file", current=idx, total=self.total_files,
                         name=name, status="failed", src=src, dst=dst, error=str(e))

    # -- 主流程 -----------------------------------------------------------

    def run(self):
        try:
            if not os.path.isdir(self.source):
                raise FileNotFoundError(f"源目录不存在：{self.source}")
            if not os.path.isdir(self.dest_root):
                os.makedirs(self.dest_root, exist_ok=True)

            # 防呆：目标不能在源目录内部
            if (self.dest_root == self.source
                    or self.dest_root.startswith(self.source + os.sep)):
                raise ValueError("目标根目录不能位于源目录内部，否则会拷贝到自身！")

            self._notify(type="start", phase="scan", total=0)
            files = scan_files(self.source)
            if self._stop.is_set():
                self._notify(type="done", summary=self.summary, cancelled=True)
                return

            # 按格式分组
            groups = {}
            ignored = 0
            for f in files:
                ext = os.path.splitext(f)[1].lstrip(".").lower()
                if ext not in FORMAT_MAP and not self.copy_unknown:
                    ignored += 1
                    continue
                fmt = classify(ext)
                groups.setdefault(fmt, []).append(f)

            if not groups:
                self._notify(type="error",
                             message="源目录中没有找到图片/视频文件"
                                     + ("（或未识别格式已被排除）。" if ignored else "。"))
                return

            self.total_files = sum(len(v) for v in groups.values())
            tree = build_dest_tree(self.dest_root, self.date_dir)
            self._notify(type="start", phase="copy", total=self.total_files)
            self._notify(type="log", message=f"日期目录：{tree['date']}")
            self._notify(type="log",
                         message=f"已创建「{ORIGINAL_FOLDER}」「{EDITED_FOLDER}」文件夹，"
                                 f"{ORIGINAL_FOLDER} 下按格式分文件夹。")

            idx = 0
            for fmt in sorted(groups):
                folder = os.path.join(tree["original"], fmt)
                os.makedirs(folder, exist_ok=True)
                self._notify(type="log", message=f"格式 {fmt}：{len(groups[fmt])} 个文件")
                for src in groups[fmt]:
                    if self._stop.is_set():
                        self._notify(type="log", message="已收到停止请求，正在收尾…")
                        break
                    idx += 1
                    self._copy_one(src, folder, idx)
                if self._stop.is_set():
                    break

            self._notify(type="done", summary=self.summary,
                         cancelled=self._stop.is_set())
        except Exception as e:
            self._notify(type="error", message=f"拷贝失败：{e}")


# --------------------------------------------------------------------------
# 命令行模式
# --------------------------------------------------------------------------

def run_cli(source, dest_root, date_dir=None, verify=False,
            skip_existing=True, copy_unknown=True):
    """命令行模式：直接拷贝并打印进度。"""
    def on_event(ev):
        t = ev.get("type")
        if t == "start":
            if ev.get("phase") == "scan":
                print("正在扫描源目录…")
            else:
                print(f"开始拷贝，共 {ev.get('total', 0)} 个文件")
        elif t == "log":
            print(f"  {ev.get('message', '')}")
        elif t == "file":
            mark = {"copied": "OK", "skipped": "跳过", "failed": "失败",
                    "mismatch": "校验不一致"}.get(ev.get("status"), ev.get("status"))
            extra = f"  <- {ev.get('error', '')}" if ev.get("error") else ""
            print(f"[{ev.get('current', 0)}/{ev.get('total', 0)}] {ev.get('name')} {mark}{extra}")
        elif t == "error":
            print(f"错误：{ev.get('message', '')}")
        elif t == "done":
            s = ev.get("summary", {})
            print("\n=== 结果 ===")
            print("按格式：", "，".join(f"{k} {v}" for k, v in sorted(s.get("by_format", {}).items())))
            print(f"成功 {s.get('copied', 0)} | 跳过 {s.get('skipped', 0)} | 失败 {s.get('failed', 0)}")
            print(f"校验通过 {s.get('verified', 0)} | 不一致 {s.get('mismatch', 0)}")
            print(f"总大小：{human_size(s.get('total_bytes', 0))}")
            if s.get("failed_list"):
                print("失败文件：")
                for a, b, err in s["failed_list"]:
                    print(f"  {a} -> {b} ({err})")

    copier = CameraCopier(source, dest_root, date_dir=date_dir, verify=verify,
                          skip_existing=skip_existing, copy_unknown=copy_unknown,
                          callback=on_event)
    copier.run()
    return copier.summary


if __name__ == "__main__":
    # 简单自测：python copier.py <源> <目标>
    import sys
    if len(sys.argv) >= 3:
        run_cli(sys.argv[1], sys.argv[2])
    else:
        print("用法：python copier.py <源目录> <目标根目录>")
