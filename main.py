# -*- coding: utf-8 -*-
"""
相机拷卡工具 —— Pixcall 风格深色界面（tkinter）+ 命令行模式。

运行：
    图形界面：  python main.py          （或 pythonw main.py 不弹控制台）
    命令行：    python main.py --cli <源目录> <目标根目录> [选项]

功能：
    · 存储卡拷贝，按格式分类到 日期/原图/<格式>，并建 日期/修图 空文件夹
    · 实时进度条 + 百分比 + 当前文件详情
    · 7-Zip 集成：拷贝完成后自动压缩日期文件夹为 .7z，或单独压缩任意文件夹
"""

import argparse
import os
import queue
import re
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
import tkinter.ttk as ttk
from tkinter import filedialog, messagebox

import glass
from archive import compress_folder, find_7z
from config import DEFAULT_7Z_LEVEL, FORMAT_MAP, THEME, UNKNOWN_FOLDER
from copier import CameraCopier, human_size, run_cli, scan_images, today_str

FONT = "SimHei"   # 黑体

# 圆角卡片常量
INSET = 14      # 卡片内容嵌入偏移（需 >= 圆角半径，避免内容尖角戳出圆角）
RADIUS = 14     # 卡片圆角半径

# Pillow 可选：未安装时预览页降级为文件名列表
try:
    from PIL import Image, ImageTk
    HAVE_PIL = True
except ImportError:
    Image = ImageTk = None
    HAVE_PIL = False

# Pillow 能直接解码出缩略图的格式；其余格式（RAW/HEIC/视频等）显示占位块
PIL_PREVIEW_EXTS = {"jpg", "jpeg", "png", "gif", "bmp", "tif", "tiff", "webp"}


# --------------------------------------------------------------------------
# 平台辅助
# --------------------------------------------------------------------------

def list_drives():
    """Windows 下枚举所有盘符及类型（可移动磁盘排前面）；非 Windows 返回空。"""
    if os.name != "nt":
        return []
    drives = []
    try:
        import ctypes
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        type_names = {2: "可移动磁盘", 3: "本地磁盘", 4: "网络驱动器",
                      5: "光盘", 6: "内存盘"}
        for i in range(26):
            if bitmask & (1 << i):
                letter = chr(ord("A") + i)
                root = f"{letter}:\\"
                dtype = ctypes.windll.kernel32.GetDriveTypeW(root)
                drives.append((root, type_names.get(dtype, "其他")))
    except Exception:
        pass
    drives.sort(key=lambda d: d[1] != "可移动磁盘")
    return drives


# --------------------------------------------------------------------------
# 主界面
# --------------------------------------------------------------------------

class CopyToolApp:
    def __init__(self, root):
        self.root = root
        root.title("CoCa")
        # 窗口图标（icon.ico 与 main.py 同目录；缺失则忽略）
        try:
            _ico = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
            if os.path.isfile(_ico):
                root.iconbitmap(_ico)
        except Exception:
            pass
        root.geometry("960x660")
        root.minsize(800, 540)   # 小屏幕也能完整显示（按钮在顶部，永不裁剪）
        root.configure(bg=THEME["bg"])
        root.update_idletasks()
        # 原生窗口标题栏设为浅色（DWM 深色模式关闭），与浅色界面协调，不再是黑条
        self._set_titlebar_dark(False)

        self.msg_queue = queue.Queue()
        self.copier = None
        self.copy_thread = None
        self.phase = "idle"                # idle / copy / zip-copy / zip-page
        self.zip_stop_event = None
        self.seven_zip = find_7z()
        self.last_dst = ""
        self.last_date = ""
        self.settings = self._load_settings()   # 环境提示的"不再提示"记忆
        self.side_log_box = None                # 右侧「日志」页日志区
        self.side_log = None
        # 全局滚轮目标
        self._wheel_targets = []
        self.root.bind_all("<MouseWheel>", self._on_global_wheel)

        # 页面容器：侧边栏(left)在左，页面区(left fill/expand)在右
        self._build_sidebar()
        self.main = tk.Frame(root, bg=THEME["bg"])
        self.main.pack(side="left", fill="both", expand=True)
        self.main.grid_rowconfigure(0, weight=1)
        self.main.grid_columnconfigure(0, weight=1)

        self._build_log_page()
        self._build_copy_page()
        self._build_preview_page()
        self._build_zip_page()
        self._apply_settings()          # 恢复上次设置的界面状态
        self._show_page("copy")
        self._update_7z_status()
        self.root.after(300, self._check_env)   # 环境自检（缺 7-Zip/Pillow 弹窗）
        self.root.protocol("WM_DELETE_WINDOW", self._quit)   # 关窗时保存设置

        self.root.after(100, self._pump)

    # ================= 深色标题栏（Windows 原生按钮） =================

    def _set_titlebar_dark(self, dark=False):
        """设置系统标题栏明暗（DWMWA_USE_IMMERSIVE_DARK_MODE=20）。浅色应用用 False。"""
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            value = ctypes.c_int(1 if dark else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
        except Exception:
            pass

    # ================= 全局鼠标滚轮 =================

    def _register_wheel(self, widget, handler, page=None):
        """注册一个可用滚轮滚动的控件（page 为所属页面，用于只在当前页生效）。"""
        self._wheel_targets.append((widget, handler, page))

    def _on_global_wheel(self, event):
        """全局滚轮：仅当停在「日志」页时，在日志面板上滚日志（到底/顶联动滚页面）；别处滚页面/预览。"""
        delta = event.delta
        px, py = self.root.winfo_pointerx(), self.root.winfo_pointery()
        logbox, logtext = getattr(self, "side_log_box", None), getattr(self, "side_log", None)
        on_log_page = logbox is not None and self.current_page is self.pages.get("log")
        if on_log_page and self._in_bounds(logbox, px, py):
            try:
                first, last = logtext.yview()
            except Exception:
                first, last = 0.0, 1.0
            if (delta < 0 and first > 1e-6) or (delta > 0 and last < 1 - 1e-6):
                logtext.yview_scroll(int(-delta / 120), "units")
                self._sb_draw(logtext._sb)
                return
            # 日志到顶/底 -> 接力滚页面
            self._fallback_page_scroll(delta)
            return
        # 非日志区域：用注册目标（预览/列表/页面），winfo_containing 从下往上找
        under = self.root.winfo_containing(px, py)
        if under is not None:
            target_map = {w: (h, p) for w, h, p in self._wheel_targets}
            cur = under
            while cur is not None:
                entry = target_map.get(cur)
                if entry is not None:
                    handler, tpage = entry
                    if tpage is None or tpage is self.current_page:
                        try:
                            first, last = cur.yview()
                        except Exception:
                            first, last = 0.0, 1.0
                        if (delta < 0 and first > 1e-6) or (delta > 0 and last < 1 - 1e-6):
                            handler(delta)
                            return
                cur = cur.master
        self._fallback_page_scroll(delta)

    def _in_bounds(self, widget, px, py):
        try:
            x0 = widget.winfo_rootx()
            y0 = widget.winfo_rooty()
            return x0 <= px <= x0 + widget.winfo_width() and y0 <= py <= y0 + widget.winfo_height()
        except Exception:
            return False

    def _fallback_page_scroll(self, delta):
        """找到当前页面的页面滚动面板并滚动。"""
        for w, h, page in self._wheel_targets:
            if getattr(w, "_is_page_scroll", False) and (page is None or page is self.current_page):
                h(delta)
                return

    def _make_sb(self, parent, canvas, bg=None):
        """创建圆角 Canvas 滚动条，绑定到内容 canvas。由调用方 pack。
        bg 为滚动条画布背景色（白底上用白色，页面底上用主题色）。"""
        sb = tk.Canvas(parent, width=12, bg=bg or THEME["bg"], highlightthickness=0,
                       cursor="hand2")
        sb._target = canvas
        canvas._sb = sb
        sb.bind("<Button-1>", self._sb_drag)
        sb.bind("<B1-Motion>", self._sb_drag)
        sb.bind("<Configure>", lambda e: self._sb_draw(sb))
        return sb

    def _sb_draw(self, sb):
        """按内容比例绘制圆角轨道 + 圆角滑块（兼容 Canvas 与 Text，用 yview 分数）。"""
        target = sb._target
        w = max(sb.winfo_width(), 12)
        h = max(sb.winfo_height(), 10)
        rr = (w - 2) // 2
        sb.delete("all")
        glass.rounded_rect(sb, 1, 1, w - 2, h - 2, rr, fill="#E2E8F3")
        try:
            first, last = target.yview()
        except Exception:
            return
        view_frac = last - first
        if view_frac >= 1 - 1e-6:
            y0, thumb_h = 1, h - 2
        else:
            thumb_h = max(12, int((h - 2) * view_frac))
            span = max(0.001, 1 - view_frac)
            scroll_frac = max(0.0, min(1.0, first / span))
            y0 = 1 + int(((h - 2) - thumb_h) * scroll_frac)
        glass.rounded_rect(sb, 1, y0, w - 2, y0 + thumb_h, rr, fill=THEME["accent"])

    def _sb_drag(self, event):
        """拖动滑块：把光标在轨道上的位置映射为滚动进度（兼容 Canvas/Text）。"""
        sb = event.widget
        target = sb._target
        w = max(sb.winfo_width(), 12)
        h = max(sb.winfo_height(), 10)
        try:
            first, last = target.yview()
        except Exception:
            return
        view_frac = last - first
        if view_frac >= 1 - 1e-6:
            return
        thumb_h = max(12, int((h - 2) * view_frac))
        span = max(1, (h - 2) - thumb_h)
        frac = (event.y - 1 - thumb_h / 2) / span
        target.yview_moveto(max(0.0, min(1.0, frac)))
        self._sb_draw(sb)

    def _sb_sync(self, canvas):
        """内容滚动后刷新对应滚动条。"""
        sb = getattr(canvas, "_sb", None)
        if sb:
            self._sb_draw(sb)

    # ================= 通用控件工厂 =================

    def _add_backdrop(self, page):
        """页面背景：纯平浅色（干净不混乱）。不再画渐变/光斑，避免重叠与噪点。"""
        canvas = tk.Canvas(page, bg=THEME["bg"], highlightthickness=0)
        canvas.place(x=0, y=0, relwidth=1, relheight=1)
        return canvas

    def _scroll_panel(self, page):
        """页面中部可滚动区域：顶部标题与底部按钮固定，中间内容过长时滚动。
        使用自绘圆角滚动条。返回 inner 帧。"""
        canvas = tk.Canvas(page, bg=THEME["bg"], highlightthickness=0)
        canvas._is_page_scroll = True
        sb = self._make_sb(page, canvas)
        sb.pack(side="right", fill="y", padx=(0, 8))
        canvas.pack(side="left", fill="both", expand=True, padx=(16, 0))
        inner = tk.Frame(canvas, bg=THEME["bg"])
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: (canvas.configure(scrollregion=canvas.bbox("all")),
                              self._sb_draw(sb)))
        canvas.bind("<Configure>",
                    lambda e: (canvas.itemconfigure(win, width=max(e.width, 1)),
                               self._sb_draw(sb)))

        def _wheel(delta):
            bbox = canvas.bbox("all")
            if bbox and (bbox[3] - bbox[1]) <= canvas.winfo_height():
                return   # 内容未超出，不滚
            canvas.yview_scroll(int(-delta / 120), "units")
            self._sb_draw(sb)

        self._register_wheel(canvas, _wheel, page)
        return inner

    def _card(self, parent, title, hint=None):
        """浅色磨砂圆角卡片：Canvas 绘制白色圆角面板 + 柔和阴影，内容嵌入其中。
        返回 (card_canvas, body_frame)。"""
        card = tk.Canvas(parent, bg=THEME["bg"], highlightthickness=0)
        content = tk.Frame(card, bg=THEME["card"])
        tk.Label(content, text=title, bg=THEME["card"], fg=THEME["text"],
                 font=(FONT, 11, "bold"), anchor="w").pack(fill="x", padx=8, pady=(13, 2))
        if hint:
            tk.Label(content, text=hint, bg=THEME["card"], fg=THEME["dim"],
                     font=(FONT, 8), anchor="w").pack(fill="x", padx=8, pady=(0, 2))
        body = tk.Frame(content, bg=THEME["card"])
        body.pack(fill="x", padx=8, pady=(0, 12))
        content_id = card.create_window(INSET, INSET, window=content, anchor="nw")
        _last_w = [0]

        def redraw(_event=None):
            w = card.winfo_width()
            if w <= 1 or w == _last_w[0]:
                return   # 宽度未变：避免 Configure 无限循环
            _last_w[0] = w
            h = content.winfo_reqheight()
            card.configure(height=h + INSET * 2)
            card.itemconfigure(content_id, width=w - INSET * 2, height=h)
            card.delete("panel")
            # 白色圆角面板（无边框无阴影，去"灰白色方框"感）
            glass.rounded_rect(card, 3, 3, w - 3, h + INSET * 2 - 3, radius=RADIUS,
                               fill=THEME["card"], tags="panel")

        content.bind("<Configure>", redraw)
        card.bind("<Configure>", redraw)
        return card, body

    def _btn(self, parent, text, cmd, accent=False, width=None):
        if accent:
            bg, fg, hover = THEME["accent"], "#FFFFFF", THEME["accent_hover"]
        else:
            bg, fg, hover = "#EDF1F8", THEME["text"], "#E1E8F3"
        kw = dict(relief="flat", bd=0, bg=bg, fg=fg,
                  activebackground=hover, activeforeground="#FFFFFF",
                  font=(FONT, 10), cursor="hand2", padx=14, pady=6)
        if width:
            kw["width"] = width
        return tk.Button(parent, text=text, command=cmd, **kw)

    def _btn_small(self, parent, text, cmd):
        """与输入框同尺寸/同字体的行内小按钮，光滑四角圆角（浏览/刷新/重置/检测 等）。"""
        return self._round_btn(parent, text, cmd, accent=False, fontsize=9)

    def _round_btn(self, parent, text, cmd, accent=False, fontsize=10):
        """四角圆角按钮（Canvas 自绘，单击触发 cmd）。用于标题/底部等按钮。"""
        if accent:
            bg, fg, hover = THEME["accent"], "#FFFFFF", THEME["accent_hover"]
        else:
            bg, fg, hover = "#EDF1F8", THEME["text"], "#E1E8F3"
        f = tkfont.Font(font=(FONT, fontsize))
        w = f.measure(text) + 22
        h = f.metrics("linespace") + 12
        cv = tk.Canvas(parent, bg=THEME["bg"], highlightthickness=0,
                       width=w, height=h, cursor="hand2")
        cv._enabled = True

        def draw(cur):
            cv.delete("all")
            if not cv._enabled:
                cur = "#E8EDF5"
            glass.rounded_rect(cv, 0, 0, w - 1, h - 1, 10, fill=cur)
            cv.create_text(w / 2, h / 2, text=text,
                           fill=fg if cv._enabled else THEME["dim"],
                           font=(FONT, fontsize))

        def down(_e):
            if cv._enabled:
                cmd()
        cv.bind("<Button-1>", down)
        cv.bind("<Enter>", lambda e: draw(hover))
        cv.bind("<Leave>", lambda e: draw(bg))
        draw(bg)
        cv._redraw = lambda: draw(bg)
        return cv

    def _set_state(self, btn, state):
        """统一启用/禁用按钮（兼容普通 Button 与自绘圆角按钮）。"""
        if isinstance(btn, tk.Canvas) and hasattr(btn, "_redraw"):
            btn._enabled = (state != "disabled")
            btn._redraw()
        else:
            btn.config(state=state)

    def _entry(self, parent, var):
        return tk.Entry(parent, textvariable=var, bg=THEME["input_bg"],
                        fg=THEME["text"], insertbackground=THEME["text"],
                        relief="flat", bd=0, highlightthickness=1,
                        highlightbackground=THEME["input_border"],
                        highlightcolor=THEME["accent"],
                        font=(FONT, 10))

    def _check(self, parent, text, var):
        return tk.Checkbutton(parent, text=text, variable=var, bg=THEME["card"],
                              fg=THEME["text"], selectcolor=THEME["card"],
                              activebackground=THEME["card"],
                              activeforeground=THEME["text"],
                              font=(FONT, 10), cursor="hand2")

    def _progress_widgets(self, parent):
        """进度区：圆角画布进度条（头尾半圆，百分比居中），下方为状态信息。
        返回 dict，含 bar(Canvas) 与 info(Label)。"""
        bar = tk.Canvas(parent, height=22, bg=THEME["bg"], highlightthickness=0)
        bar.pack(fill="x")
        info = tk.Label(parent, text="", bg=THEME["bg"], fg=THEME["dim"],
                        font=(FONT, 9), anchor="w")
        info.pack(fill="x", pady=(2, 0))
        bar._state = (None, "就绪")
        bar.bind("<Configure>", lambda e: self._draw_progress_bar(bar, *bar._state))
        self._draw_progress_bar(bar, None, "就绪")
        return {"bar": bar, "info": info}

    def _draw_progress_bar(self, canvas, percent, status="就绪", _h=22):
        """绘制圆角进度条：轨道圆角、填充圆角（头尾半圆），文字居中。"""
        w = max(canvas.winfo_width(), 10)
        h = _h
        r = h // 2
        canvas.delete("all")
        # 圆角轨道
        glass.rounded_rect(canvas, 1, 1, w - 1, h - 1, r, fill="#E2E8F3")
        p = 0
        run = percent is not None
        if run:
            p = max(0, min(100, int(percent)))
        if run and p > 0:
            fw = max(h, int((w - 2) * p / 100))
            glass.rounded_rect(canvas, 1, 1, min(fw, w - 1), h - 1, r,
                               fill=THEME["accent"])
        # 居中文字：未做任务=就绪；任务中=百分比
        ctext = f"{p}%" if run else "就绪"
        color = "#FFFFFF" if (run and p > 50) else THEME["dim"]
        canvas.create_text(w // 2, h // 2, text=ctext, fill=color,
                           font=(FONT, 9, "bold"))
        canvas._state = (percent, status)

    def _set_progress(self, widgets, percent, status, detail=""):
        self._draw_progress_bar(widgets["bar"], percent, status)
        parts = []
        if status and status != "就绪":
            parts.append(status)
        if detail:
            parts.append(detail)
        widgets["info"].config(text="  ".join(parts))

    def _log_widget(self, parent, page=None, outer_bg=None, panel_fill=None):
        """日志区：四角圆角面板（滚动条移到面板外面，右侧）。
        outer_bg 为外围底色（页面底或白色侧边栏），panel_fill 为日志面板填充色。"""
        outer_bg = outer_bg or THEME["bg"]
        panel_fill = panel_fill or "#FFFFFF"
        wrap = tk.Frame(parent, bg=outer_bg)
        panel = tk.Canvas(wrap, bg=outer_bg, highlightthickness=0, height=140)
        text = tk.Text(panel, bg=panel_fill, fg=THEME["text"],
                       insertbackground=THEME["text"], relief="flat", bd=0,
                       font=(FONT, 9), wrap="word", state="disabled",
                       padx=10, pady=6)
        # 滚动条在面板外面（右侧，外围底色）
        sb = self._make_sb(wrap, text, outer_bg)
        sb.pack(side="right", fill="y", padx=(8, 0), pady=2)
        panel.pack(side="left", fill="both", expand=True)
        inner_id = panel.create_window(24, 24, window=text, anchor="nw")

        def redraw(_event=None):
            w = panel.winfo_width()
            h = panel.winfo_height()
            if w <= 52 or h <= 52:
                return
            panel.delete("bg")
            glass.rounded_rect(panel, 1, 1, w - 1, h - 1, 20, fill=panel_fill, tags="bg")
            panel.itemconfigure(inner_id, width=w - 48, height=h - 48)
            self._sb_draw(sb)

        panel.bind("<Configure>", redraw)
        text.bind("<Configure>", lambda e: redraw())
        self._register_wheel(text, lambda d: (text.yview_scroll(int(-d / 120), "units"),
                                              self._sb_draw(sb)), page)
        redraw()
        return wrap, text

    def _log(self, text_widget, msg):
        text_widget.configure(state="normal")
        text_widget.insert("end", msg + "\n")
        count = int(text_widget.index("end-1c").split(".")[0])
        if count > 3000:
            text_widget.delete("1.0", f"{count - 3000}.0")
        text_widget.see("end")
        text_widget.configure(state="disabled")
        sb = getattr(text_widget, "_sb", None)
        if sb:
            self._sb_draw(sb)

    # ================= 侧边栏（圆角毛玻璃面板） =================

    def _build_sidebar(self):
        WHITE = "#FFFFFF"
        wrap = tk.Frame(self.root, bg=THEME["bg"], width=228)
        wrap.pack(side="left", fill="y", padx=(10, 6), pady=10)
        wrap.pack_propagate(False)
        panel = tk.Canvas(wrap, bg=THEME["bg"], highlightthickness=0)
        panel.pack(fill="both", expand=True)

        content = tk.Frame(panel, bg=WHITE)
        # Logo：纯文字名称
        tk.Label(content, text="CoCa", bg=WHITE, fg=THEME["text"],
                 font=(FONT, 17, "bold"), anchor="w").pack(fill="x", padx=16, pady=(20, 24))

        tk.Label(content, text="菜单", bg=WHITE, fg=THEME["dim"],
                 font=(FONT, 8, "bold"), anchor="w").pack(fill="x", padx=16, pady=(0, 6))

        self.nav_buttons = {}
        for key, text in (("copy", "拷贝"), ("preview", "预览"), ("zip", "压缩"), ("log", "日志")):
            cv = tk.Canvas(content, bg=WHITE, highlightthickness=0, height=36, cursor="hand2")
            cv.pack(fill="x", padx=10, pady=3)
            cv._key, cv._text, cv._active = key, text, False
            cv.bind("<Button-1>", lambda e, k=key: self._show_page(k))
            cv.bind("<Configure>", lambda e: self._draw_nav(cv, cv._active))
            self.nav_buttons[key] = cv
        self._redraw_navs("copy")

        # 底部一行：7-Zip 状态 + 「重置不再提示」链接
        env_row = tk.Frame(content, bg=WHITE)
        env_row.pack(side="bottom", fill="x", padx=16, pady=(8, 0))
        self.sevenz_label = tk.Label(env_row, text="", bg=WHITE,
                                     fg=THEME["dim"], font=(FONT, 8), anchor="w")
        self.sevenz_label.pack(side="left")
        tk.Button(env_row, text="重置不再提示", command=self._reset_dont_ask,
                  relief="flat", bg=WHITE, fg=THEME["accent"], font=(FONT, 8),
                  activebackground=WHITE, activeforeground=THEME["accent_hover"],
                  cursor="hand2", bd=0).pack(side="right")
        tk.Button(content, text="环境检测", command=lambda: self._check_env(manual=True),
                  relief="flat", bg="#EDF1F8", fg=THEME["text"], font=(FONT, 9),
                  activebackground="#E1E8F3", activeforeground=THEME["text"],
                  cursor="hand2", padx=10, pady=5).pack(side="bottom", fill="x", padx=14, pady=(0, 14))

        content_id = panel.create_window(INSET, INSET, window=content, anchor="nw")
        _last = [0, 0]

        def redraw(_event=None):
            w, h = panel.winfo_width(), panel.winfo_height()
            if w <= INSET * 2 or h <= INSET * 2:
                return
            if (w, h) == tuple(_last):
                return
            _last[:] = [w, h]
            panel.delete("p")
            # 圆角毛玻璃面板（白色）
            glass.rounded_rect(panel, 3, 3, w - 3, h - 3, radius=RADIUS,
                               fill=WHITE, tags="p")
            panel.itemconfigure(content_id, width=w - INSET * 2, height=h - INSET * 2)

        content.bind("<Configure>", lambda e: redraw())
        panel.bind("<Configure>", lambda e: redraw())

    def _draw_nav(self, cv, active):
        """绘制导航项：选中为四角圆角的蓝色块（非胶囊），无毛边。"""
        w = max(cv.winfo_width(), 180)
        h = max(cv.winfo_height(), 36)
        cv.delete("all")
        if active:
            glass.rounded_rect(cv, 1, 1, w - 2, h - 2, 10, fill=THEME["accent"])
            fg = "#FFFFFF"
        else:
            fg = THEME["dim"]
        cv.create_text(18, h // 2, text=cv._text, anchor="w", fill=fg,
                       font=(FONT, 11))

    def _redraw_navs(self, key):
        for k, cv in self.nav_buttons.items():
            cv._active = (k == key)
            self._draw_nav(cv, k == key)

    def _show_page(self, key):
        self._redraw_navs(key)
        self.current_page = self.pages[key]
        self.pages[key].tkraise()

    def _update_7z_status(self):
        if self.seven_zip:
            self.sevenz_label.config(text="7-Zip：已就绪", fg=THEME["ok"])
        else:
            self.sevenz_label.config(text="7-Zip：未安装", fg=THEME["danger"])

    def _reset_dont_ask(self):
        """重置「不再提示」，下次缺失依赖时重新弹窗。"""
        self.settings["dont_ask_7zip"] = False
        self.settings["dont_ask_pillow"] = False
        self._save_settings()
        messagebox.showinfo("环境检测",
                            "已重置「不再提示」。\n下次缺失 7-Zip / Pillow 时会再次弹窗询问。")

    # ---- 设置记忆（上次选择下次启动恢复）----

    def _apply_settings(self):
        """把上次保存的设置应用到界面控件。"""
        s = self.settings
        if hasattr(self, "verify_var"):
            self.verify_var.set(s.get("verify", True))
            self.skip_var.set(s.get("skip", True))
            self.unknown_var.set(s.get("unknown", False))
            self.auto_zip_var.set(s.get("auto_zip", True))
            self.auto_level_var.set(s.get("auto_level", "0 仅存储(最快)"))
            self.zip_level_var.set(s.get("zip_level", "0 仅存储(最快)"))
            self.zip_out_var.set(s.get("zip_out", ""))
            if s.get("dst"):
                self.dst_var.set(s["dst"])

    def _save_all_settings(self):
        """把当前界面设置收集进 self.settings 并写盘。"""
        try:
            s = self.settings
            if hasattr(self, "verify_var"):
                s["verify"] = bool(self.verify_var.get())
                s["skip"] = bool(self.skip_var.get())
                s["unknown"] = bool(self.unknown_var.get())
                s["auto_zip"] = bool(self.auto_zip_var.get())
                s["auto_level"] = self.auto_level_var.get()
                s["zip_level"] = self.zip_level_var.get()
                s["zip_out"] = self.zip_out_var.get()
                s["dst"] = self.dst_var.get()
            self._save_settings()
        except Exception:
            pass

    def _quit(self):
        self._save_all_settings()
        self.root.destroy()

    # ================= 环境自检 =================

    def _check_env(self):
        """启动后自检：缺 7-Zip / Pillow 时弹窗询问是否安装。"""
        if self.seven_zip is None:
            if messagebox.askyesno("环境检测",
                                   "未检测到 7-Zip。\n「压缩」功能需要它（免费开源）。\n\n"
                                   "是否前往 7-Zip 官网下载安装？"):
                try:
                    import webbrowser
                    webbrowser.open("https://www.7-zip.org/")
                except Exception:
                    pass
        if not HAVE_PIL:
            if messagebox.askyesno("环境检测",
                                   "未检测到 Pillow。\n「预览」页将只显示文件名（无缩略图）。\n\n"
                                   "是否现在安装（需联网，约几秒）？"):
                self._install_pillow()

    def _open_url(self, url):
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass

    # ---- 环境提示设置（"不再提示"持久化）----

    def _settings_path(self):
        # 设置文件放在 main.py 同目录（安装目录可写，便于随程序持久化）
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.ini")

    def _load_settings(self):
        s = {
            "dont_ask_7zip": False, "dont_ask_pillow": False,
            "verify": True, "skip": True, "unknown": False,
            "auto_zip": True, "auto_level": "0 仅存储(最快)",
            "zip_level": "0 仅存储(最快)", "zip_out": "",
            "dst": self._default_dest(),
        }
        try:
            with open(self._settings_path(), "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line:
                        k, v = line.split("=", 1)
                        val = v.strip()
                        # 布尔键按 1/0 转，其余存原值
                        s[k.strip()] = (val == "1") if val in ("0", "1") else val
        except Exception:
            pass
        return s

    def _save_settings(self):
        try:
            with open(self._settings_path(), "w", encoding="utf-8") as f:
                for k, v in self.settings.items():
                    if isinstance(v, bool):
                        f.write(f"{k}={'1' if v else '0'}\n")
                    else:
                        f.write(f"{k}={v}\n")
        except Exception:
            pass

    def _prompt_install(self, title, message):
        """自定义弹窗：消息 + 「不再提示」勾选 + 是/否。居中显示在程序窗口内。返回 (yes, dont_ask)。"""
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()
        tk.Label(dlg, text=message, justify="left", wraplength=400, anchor="w",
                 bg=THEME["bg"], fg=THEME["text"], font=(FONT, 10)).pack(
            fill="x", padx=18, pady=(16, 4), anchor="w")
        dont = tk.BooleanVar(value=False)
        tk.Checkbutton(dlg, text="不再提示", variable=dont, bg=THEME["bg"],
                       fg=THEME["dim"], selectcolor=THEME["bg"],
                       font=(FONT, 9)).pack(anchor="w", padx=18)
        result = {"yes": False}
        bf = tk.Frame(dlg, bg=THEME["bg"])
        bf.pack(pady=(12, 10))
        tk.Button(bf, text="是", command=lambda: (result.__setitem__("yes", True), dlg.destroy()),
                  relief="flat", bg=THEME["accent"], fg="#FFFFFF", font=(FONT, 10),
                  padx=18, pady=5).pack(side="left", padx=6)
        tk.Button(bf, text="否", command=dlg.destroy, relief="flat", bg="#EDF1F8",
                  fg=THEME["text"], font=(FONT, 10), padx=18, pady=5).pack(side="left")
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        # 居中在程序窗口内
        dlg.update_idletasks()
        _w = dlg.winfo_reqwidth()
        _h = dlg.winfo_reqheight()
        _x = self.root.winfo_rootx() + (self.root.winfo_width() - _w) // 2
        _y = self.root.winfo_rooty() + (self.root.winfo_height() - _h) // 2
        dlg.geometry(f"+{max(0,_x)}+{max(0,_y)}")
        self.root.wait_window(dlg)
        return result["yes"], dont.get()

    def _check_env(self, manual=False):
        """环境自检：重检测 7-Zip 与 Pillow（实时），缺失时弹窗（尊重「不再提示」）。"""
        # 每次检测先实时刷新依赖状态（运行中装了也能立刻识别）
        self.seven_zip = find_7z()
        self._update_7z_status()
        have_pil = self._have_pil()
        if self.seven_zip is None and not self.settings.get("dont_ask_7zip"):
            yes, dont = self._prompt_install(
                "环境检测",
                "未检测到 7-Zip。\n「压缩」功能需要它（免费开源）。\n\n"
                "是否打开 7-Zip 官网，按引导自行下载并安装？")
            if dont:
                self.settings["dont_ask_7zip"] = True
                self._save_settings()
            if yes:
                self._open_url("https://www.7-zip.org/")
        if not have_pil and not self.settings.get("dont_ask_pillow"):
            yes, dont = self._prompt_install(
                "环境检测",
                "未检测到 Pillow。\n「预览」页将只显示文件名（无缩略图）。\n\n"
                "是否打开 Pillow 下载页，按引导自行安装（pip install Pillow）？")
            if dont:
                self.settings["dont_ask_pillow"] = True
                self._save_settings()
            if yes:
                self._open_url("https://pypi.org/project/Pillow/")
        if manual:
            messagebox.showinfo("环境检测",
                                "环境检测完成：\n"
                                "  Python：已在运行 ✓\n"
                                "  7-Zip：" + ("已就绪" if self.seven_zip else "未安装") + "\n"
                                "  Pillow：" + ("已就绪" if have_pil else "未安装"))

    def _have_pil(self):
        """运行时实时检测 Pillow（启动后安装也能识别）。"""
        try:
            import PIL
            return True
        except Exception:
            return False

    # ================= 拷贝页 =================

    def _page_header(self, parent, title, subtitle, buttons=()):
        """页面头部：标题+副标题（背景色=页面色，无黑块），右侧操作按钮。
        返回 (header, [创建出的按钮...])。"""
        header = tk.Frame(parent, bg=THEME["bg"])
        header.pack(fill="x", padx=20, pady=(14, 2))
        right = tk.Frame(header, bg=THEME["bg"])
        right.pack(side="right", padx=(10, 0))   # 先占右侧，动作按钮不被标题挤走
        created = []
        for text, cmd, accent in reversed(buttons):
            btn = self._round_btn(right, text, cmd, accent=accent)
            btn.pack(side="right", padx=(0, 6))
            created.append(btn)
        left = tk.Frame(header, bg=THEME["bg"])
        left.pack(side="left", fill="x", expand=True)   # 标题区用剩余空间（文字过长自动裁剪）
        tk.Label(left, text=title, bg=THEME["bg"], fg=THEME["text"],
                 font=(FONT, 17, "bold"), anchor="w").pack(fill="x")
        if subtitle:
            tk.Label(left, text=subtitle, bg=THEME["bg"], fg=THEME["dim"],
                     font=(FONT, 9), anchor="w").pack(fill="x")
        return header, list(reversed(created))

    def _page_footer(self, parent, hint="", buttons=()):
        """页面底部：提示文字+右侧按钮（背景色=页面色，无黑块）。返回 (footer, [按钮...])。"""
        footer = tk.Frame(parent, bg=THEME["bg"])
        footer.pack(side="bottom", fill="x", padx=20, pady=(8, 10))
        if hint:
            tk.Label(footer, text=hint, bg=THEME["bg"], fg=THEME["dim"],
                     font=(FONT, 8), anchor="w").pack(side="left")
        right = tk.Frame(footer, bg=THEME["bg"])
        right.pack(side="right")
        created = []
        for text, cmd, accent in buttons:
            btn = self._round_btn(right, text, cmd, accent=accent)
            btn.pack(side="left", padx=(0, 6))
            created.append(btn)
        return footer, created

    def _build_log_page(self):
        """日志页：作为独立导航项，右侧主区显示实时日志（可清空、可滚动）。"""
        page = tk.Frame(self.main, bg=THEME["bg"])
        self.pages = {"log": page}
        page.grid(row=0, column=0, sticky="nsew")
        self._add_backdrop(page)

        header, buttons = self._page_header(
            page, "日志", "拷贝与压缩的实时进度日志",
            buttons=[("清空日志", self._clear_log, False)])
        self._page_footer(page, hint="日志会实时追加；内容过长时可滚动。",
                          buttons=[("退出", self._quit, False)])

        # 日志面板：占满中部区域
        log_wrap, self.side_log = self._log_widget(page, page,
                                                   outer_bg=THEME["bg"],
                                                   panel_fill="#F7F9FC")
        log_wrap.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        self.side_log_box = log_wrap

    def _clear_log(self):
        """清空日志页内容。"""
        if self.side_log is None:
            return
        self.side_log.configure(state="normal")
        self.side_log.delete("1.0", "end")
        self.side_log.configure(state="disabled")
        sb = getattr(self.side_log, "_sb", None)
        if sb:
            self._sb_draw(sb)

    def _build_copy_page(self):
        page = tk.Frame(self.main, bg=THEME["bg"])
        self.pages["copy"] = page
        page.grid(row=0, column=0, sticky="nsew")
        self._add_backdrop(page)   # 毛玻璃渐变底色（最底层）

        # 操作按钮放在顶部，任何窗口尺寸下都可见
        header, buttons = self._page_header(
            page, "拷贝",
            "从相机存储卡拷贝照片，按格式自动归档，可压缩为 .7z",
            buttons=[("停止", self.stop_current, False),
                     ("开始拷贝", self.start_copy, True)])
        self.cp_stop_btn, self.cp_start_btn = buttons
        self._set_state(self.cp_stop_btn, "disabled")
        self._page_footer(page, hint="内容过长时可滚动；顶部按钮已固定。",
                          buttons=[("退出", self._quit, False)])

        # 日志统一写入右侧「日志」页（导航项），此处共享同一实例
        self.cp_log = self.side_log

        # 中部可滚动区域
        inner = self._scroll_panel(page)

        # 1. 源目录
        card, body = self._card(inner, "源目录（相机存储卡）")
        self.src_display = tk.StringVar()
        self.src_combo = ttk.Combobox(body, textvariable=self.src_display,
                                      state="normal", style="Dark.TCombobox",
                                      font=(FONT, 10))
        self.src_combo.pack(side="left", fill="x", expand=True)
        self.src_combo.bind("<<ComboboxSelected>>", self._on_src_selected)
        self.src_combo.bind("<KeyRelease>", self._on_src_selected)
        self._btn_small(body, "浏览…", self._pick_source).pack(side="left", padx=(6, 0))
        self._btn_small(body, "刷新", self.refresh_drives).pack(side="left", padx=(6, 0))
        card.pack(fill="x", padx=16, pady=(0, 10))
        self.src_real_path = ""

        # 2. 目标根目录 + 日期
        card, body = self._card(inner, "目标根目录与日期文件夹")
        self.dst_var = tk.StringVar(value=self._default_dest())
        row = tk.Frame(body, bg=THEME["card"])
        row.pack(fill="x", pady=(4, 0))
        tk.Label(row, text="目标根目录", bg=THEME["card"], fg=THEME["dim"],
                 font=(FONT, 9), width=10, anchor="w").pack(side="left")
        self._entry(row, self.dst_var).pack(side="left", fill="x", expand=True)
        self._btn_small(row, "浏览…", self._pick_dest).pack(side="left", padx=(6, 0))
        row2 = tk.Frame(body, bg=THEME["card"])
        row2.pack(fill="x", pady=(6, 0))
        tk.Label(row2, text="日期文件夹", bg=THEME["card"], fg=THEME["dim"],
                 font=(FONT, 9), width=10, anchor="w").pack(side="left")
        self.date_var = tk.StringVar(value=today_str())
        self._entry(row2, self.date_var).pack(side="left", fill="x", expand=True)
        self._btn_small(row2, "重置",
                  lambda: self.date_var.set(today_str())).pack(side="left", padx=(6, 0))
        card.pack(fill="x", padx=16, pady=(0, 10))

        # 3. 选项（三行，一行一项；默认勾选一、二，不勾选三）
        card, body = self._card(inner, "选项")
        self.verify_var = tk.BooleanVar(value=True)
        self.skip_var = tk.BooleanVar(value=True)
        self.unknown_var = tk.BooleanVar(value=False)
        self._check(body, "拷贝后 Hash 校验", self.verify_var).pack(anchor="w", pady=2)
        self._check(body, "跳过已存在文件", self.skip_var).pack(anchor="w", pady=2)
        self._check(body, f"未识别格式拷到「{UNKNOWN_FOLDER}」", self.unknown_var).pack(anchor="w", pady=2)
        card.pack(fill="x", padx=16, pady=(0, 10))

        # 4. 7-Zip 压缩
        card, body = self._card(inner, "7-Zip 压缩（需安装 7-Zip）")
        self.auto_zip_var = tk.BooleanVar(value=True)
        self._check(body, "拷贝后自动压缩为 .7z", self.auto_zip_var).pack(side="left", padx=(0, 14))
        tk.Label(body, text="压缩级别", bg=THEME["card"], fg=THEME["dim"],
                 font=(FONT, 9)).pack(side="left", padx=(0, 6))
        levels = [("0 仅存储(最快)", 0), ("1", 1), ("3", 3), ("5 标准", 5),
                  ("7", 7), ("9 极限(最慢)", 9)]
        self.auto_level_var = tk.StringVar(value="0 仅存储(最快)")
        combo = ttk.Combobox(body, textvariable=self.auto_level_var,
                             values=[lbl for lbl, _ in levels],
                             state="readonly", width=12, style="Dark.TCombobox",
                             font=(FONT, 9))
        combo.pack(side="left")
        card.pack(fill="x", padx=16, pady=(0, 10))
        self._level_choices = levels

        # 5. 进度
        self.cp_progress = self._progress_widgets(inner)

    def _level_value(self, display):
        for lbl, val in self._level_choices:
            if lbl == display:
                return val
        return DEFAULT_7Z_LEVEL

    # ================= 预览页 =================

    def _build_preview_page(self):
        page = tk.Frame(self.main, bg=THEME["bg"])
        self.pages["preview"] = page
        page.grid(row=0, column=0, sticky="nsew")
        self._add_backdrop(page)

        self._page_header(page, "预览",
                          "浏览存储卡上的照片",
                          buttons=[("扫描", self.preview_scan, True)])

        card, body = self._card(page, "源目录")
        self.pv_dir_var = tk.StringVar()
        self._entry(body, self.pv_dir_var).pack(side="left", fill="x", expand=True)
        self._btn_small(body, "浏览…", self._pick_preview_dir).pack(side="left", padx=(6, 0))
        card.pack(fill="x", padx=16, pady=(0, 8))

        self.pv_status = tk.Label(page, text="", bg=THEME["bg"], fg=THEME["dim"],
                                  font=(FONT, 9), anchor="w")
        self.pv_status.pack(fill="x", padx=18)

        # 缩略图网格（Pillow 可用时）或文件名列表（降级）
        self.pv_canvas = tk.Canvas(page, bg=THEME["bg"], highlightthickness=0)
        self.pv_scroll = self._make_sb(page, self.pv_canvas)
        self.pv_grid = tk.Frame(self.pv_canvas, bg=THEME["bg"])
        self.pv_window = self.pv_canvas.create_window((0, 0), window=self.pv_grid, anchor="nw")
        self.pv_grid.bind("<Configure>",
                          lambda e: (self.pv_canvas.configure(scrollregion=self.pv_canvas.bbox("all")),
                                     self._sb_sync(self.pv_canvas)))
        self._register_wheel(self.pv_canvas,
                             lambda d: (self.pv_canvas.yview_scroll(int(-d / 120), "units"),
                                        self._sb_sync(self.pv_canvas)), page)
        # 窗口宽度变化时：网格宽度跟随 + 缩略图自动重排
        self.pv_canvas.bind("<Configure>", self._pv_resize)

        self.pv_list = tk.Listbox(page, bg=THEME["input_bg"], fg=THEME["text"],
                                  selectbackground=THEME["accent"],
                                  selectforeground="#FFFFFF", relief="flat",
                                  highlightthickness=1, highlightbackground=THEME["border"],
                                  font=(FONT, 9))
        pv_list_scroll = self._make_sb(page, self.pv_list)
        self._register_wheel(self.pv_list,
                             lambda d: (self.pv_list.yview_scroll(int(-d / 120), "units"),
                                        self._sb_sync(self.pv_list)), page)

        if HAVE_PIL:
            self.pv_scroll.pack(side="right", fill="y", padx=(0, 16))
            self.pv_canvas.pack(side="left", fill="both", expand=True, padx=(16, 0))
            self.pv_list_visible = False
        else:
            pv_list_scroll.pack(side="right", fill="y", padx=(0, 16))
            self.pv_list.pack(side="left", fill="both", expand=True, padx=(16, 0))
            self.pv_canvas.pack_forget()
            self.pv_list_visible = True
            tk.Label(page, text="未安装 Pillow，仅显示文件名列表。"
                                "运行  pip install Pillow  后可启用缩略图预览。",
                     bg=THEME["bg"], fg=THEME["accent"], font=(FONT, 9),
                     anchor="w").pack(fill="x", padx=18, pady=(4, 0))

        self._page_footer(page, hint="预览页：选择目录后点右上角「扫描」。",
                          buttons=[("退出", self._quit, False)])

        self.pv_items = []
        self.pv_tiles = {}
        self.pv_frames = {}
        self.pv_photos = {}
        self.pv_max = 400   # 预览上限，防止内存爆炸

    def _pv_on_wheel(self, event):
        self.pv_canvas.yview_scroll(int(-event.delta / 120), "units")

    def _pv_resize(self, _event=None):
        """画布宽度变化：内部网格跟随宽度，并重新计算列数重排缩略图。"""
        width = self.pv_canvas.winfo_width()
        if width > 10:
            self.pv_canvas.itemconfigure(self.pv_window, width=width)
        if not getattr(self, "pv_frames", None):
            return
        cols = max(1, (width - 8) // 140)
        for idx, frame in self.pv_frames.items():
            frame.grid_configure(row=idx // cols, column=idx % cols)
        self.pv_canvas.configure(scrollregion=self.pv_canvas.bbox("all"))

    def _pick_preview_dir(self):
        try:
            path = filedialog.askdirectory(parent=self.root,
                                           title="选择要预览的目录（相机存储卡）")
            if path:
                self.pv_dir_var.set(path)
        except Exception as e:
            messagebox.showerror("错误", f"打开文件夹对话框失败：{e}\n可以手动在输入框中输入路径。")

    def _clear_preview(self):
        for child in self.pv_grid.winfo_children():
            child.destroy()
        self.pv_tiles = {}
        self.pv_frames = {}
        self.pv_photos = {}
        if not self.pv_list_visible:
            self.pv_canvas.configure(scrollregion=(0, 0, 0, 0))
        else:
            self.pv_list.delete(0, "end")

    def _pv_make_tile(self, idx, path, fmt, ext):
        """创建缩略图格子；返回 (box, 图片标签)。Pillow 生成缩略图后替换图片标签。"""
        color = {"RAW": "#D9C4A8", "VIDEO": "#C8DCF0"}.get(fmt, "#E4E9F2")
        frame = tk.Frame(self.pv_grid, bg=THEME["card"],
                         highlightbackground=THEME["border"], highlightthickness=1)
        box = tk.Frame(frame, width=128, height=128, bg=color)
        box.pack_propagate(False)
        box.pack(padx=4, pady=(4, 0))
        label = tk.Label(box, text=fmt, bg=color, fg="#6B5A3E" if fmt == "RAW" else "#3A4761",
                         font=(FONT, 12, "bold"))
        label.pack(expand=True)
        tk.Label(frame, text=os.path.basename(path), bg=THEME["card"],
                 fg=THEME["dim"], font=(FONT, 8), wraplength=128,
                 justify="center").pack(pady=(2, 4))
        self.pv_tiles[idx] = (box, label)
        self.pv_frames[idx] = frame
        return frame

    def preview_scan(self):
        root_dir = self.pv_dir_var.get().strip()
        if not os.path.isdir(root_dir):
            messagebox.showerror("错误", "请选择有效的目录。")
            return
        self._clear_preview()
        files = scan_images(root_dir)
        if not files:
            self.pv_status.config(text="未找到已识别的图片/视频文件。")
            return
        self.pv_items = files
        shown = files[:self.pv_max]

        if not self.pv_list_visible:
            self.pv_status.config(text=f"扫描到 {len(files)} 个文件"
                                       + (f"，显示前 {len(shown)} 个。" if len(files) > self.pv_max else "。"))
            self.pv_grid.update_idletasks()
            for idx, (path, fmt, ext) in enumerate(shown):
                tile = self._pv_make_tile(idx, path, fmt, ext)
                tile.grid(row=idx, column=0, padx=6, pady=6)  # 先按单列摆放
            self._pv_resize()  # 按当前画布宽度重排为多列
            self.pv_status.config(text=f"扫描到 {len(files)} 个文件，正在生成缩略图…")
            threading.Thread(target=self._pv_worker, args=(shown,), daemon=True).start()
        else:
            for path, fmt, ext in shown:
                self.pv_list.insert("end", f"[{fmt:5s}] {path}")
            self.pv_status.config(text=f"扫描到 {len(files)} 个文件"
                                       + (f"，显示前 {len(shown)} 个。" if len(files) > self.pv_max else "。"))

    def _pv_worker(self, shown):
        """后台线程：生成可预览格式的缩略图，PIL Image 通过队列交给主线程。"""
        for idx, (path, fmt, ext) in enumerate(shown):
            if ext not in PIL_PREVIEW_EXTS:
                continue
            try:
                with Image.open(path) as im:
                    im.thumbnail((124, 124))
                    img = im.convert("RGB")
            except Exception:
                continue
            self.msg_queue.put({"type": "pv_tile", "idx": idx, "img": img})
        self.msg_queue.put({"type": "pv_done", "total": len(shown)})


    # ================= 压缩页 =================

    def _build_zip_page(self):
        page = tk.Frame(self.main, bg=THEME["bg"])
        self.pages["zip"] = page
        page.grid(row=0, column=0, sticky="nsew")
        self._add_backdrop(page)

        header, buttons = self._page_header(
            page, "压缩",
            "批量把多个文件夹压缩为 .7z",
            buttons=[("停止", self.stop_current, False),
                     ("开始批量压缩", self.start_zip, True)])
        self.zp_stop_btn, self.zp_start_btn = buttons
        self._set_state(self.zp_stop_btn, "disabled")
        self._page_footer(page, hint="输出目录留空时，压缩包生成在每个文件夹旁边（同名 .7z）。",
                          buttons=[("退出", self._quit, False)])

        # 日志统一写入右侧「日志」页（导航项），此处共享同一实例
        self.zp_log = self.side_log

        inner = self._scroll_panel(page)

        card, body = self._card(inner, "待压缩文件夹（可添加多个）")
        # 圆角灰色列表面板（待压缩文件下方的灰框，四角圆角）
        lp = tk.Canvas(body, bg=THEME["card"], highlightthickness=0, height=112)
        lp.pack(fill="x")
        inner_l = tk.Frame(lp, bg=THEME["input_bg"])
        self.zip_list = tk.Listbox(inner_l, bg=THEME["input_bg"], fg=THEME["text"],
                                   selectbackground=THEME["accent"],
                                   selectforeground="#FFFFFF", relief="flat",
                                   bd=0, highlightthickness=0,
                                   font=(FONT, 9),
                                   selectmode="extended", activestyle="none")
        scroll = self._make_sb(inner_l, self.zip_list, THEME["input_bg"])
        scroll.pack(side="right", fill="y", padx=(0, 4), pady=4)
        self.zip_list.pack(side="left", fill="both", expand=True)
        lid = lp.create_window(16, 16, window=inner_l, anchor="nw")

        def lredraw(_event=None):
            w = lp.winfo_width()
            h = lp.winfo_height()
            if w <= 40 or h <= 40:
                return
            lp.delete("g")
            glass.rounded_rect(lp, 1, 1, w - 1, h - 1, 14, fill=THEME["input_bg"], tags="g")
            lp.itemconfigure(lid, width=w - 32, height=h - 32)
            self._sb_draw(scroll)

        lp.bind("<Configure>", lredraw)
        inner_l.bind("<Configure>", lambda e: lredraw())
        lredraw()
        btn_row = tk.Frame(body, bg=THEME["card"])
        btn_row.pack(fill="x", pady=(8, 0))
        self._btn(btn_row, "添加文件夹…", self._pick_zip_src).pack(side="left")
        self._btn(btn_row, "移除选中", self._remove_zip_srcs).pack(side="left", padx=(6, 0))
        self._btn(btn_row, "清空列表", self._clear_zip_srcs).pack(side="left", padx=(6, 0))
        card.pack(fill="x", padx=16, pady=(0, 10))

        card, body = self._card(inner, "输出设置")
        tk.Label(body, text="压缩级别", bg=THEME["card"], fg=THEME["dim"],
                 font=(FONT, 9)).pack(side="left", padx=(0, 6))
        self.zip_level_var = tk.StringVar(value="0 仅存储(最快)")
        combo = ttk.Combobox(body, textvariable=self.zip_level_var,
                             values=[lbl for lbl, _ in self._level_choices],
                             state="readonly", width=12, style="Dark.TCombobox",
                             font=(FONT, 9))
        combo.pack(side="left")
        tk.Label(body, text="  输出目录", bg=THEME["card"], fg=THEME["dim"],
                 font=(FONT, 9)).pack(side="left", padx=(8, 6))
        self.zip_out_var = tk.StringVar(value="")
        self._entry(body, self.zip_out_var).pack(side="left", fill="x", expand=True)
        self._btn_small(body, "浏览…", self._pick_zip_out).pack(side="left", padx=(6, 0))
        card.pack(fill="x", padx=16, pady=(0, 10))

        self.zp_progress = self._progress_widgets(inner)

    # ================= 拷贝页行为 =================

    def _default_dest(self):
        # 默认目标根目录：C:/Users/hatsu/Pictures/摄影
        return r"C:/Users/hatsu/Pictures/摄影"

    def refresh_drives(self):
        values = [f"{root}（{kind}）" for root, kind in list_drives()]
        self.src_combo["values"] = values
        if values and not self.src_display.get():
            self.src_combo.current(0)
            self._on_src_selected()

    def _on_src_selected(self, _event=None):
        disp = self.src_display.get()
        if "（" in disp:
            self.src_real_path = disp.split("（", 1)[0].strip()
        else:
            self.src_real_path = disp.strip()

    def _pick_source(self):
        try:
            path = filedialog.askdirectory(parent=self.root,
                                           title="选择相机存储卡目录（如 D:\\ 或 D:\\DCIM）")
            if path:
                self.src_display.set(path)
                self._on_src_selected()
        except Exception as e:
            messagebox.showerror("错误", f"打开文件夹对话框失败：{e}\n可以手动在输入框中输入路径。")

    def _pick_dest(self):
        try:
            path = filedialog.askdirectory(parent=self.root, title="选择目标根目录")
            if path:
                self.dst_var.set(path)
        except Exception as e:
            messagebox.showerror("错误", f"打开文件夹对话框失败：{e}\n可以手动在输入框中输入路径。")

    def _pick_zip_src(self):
        try:
            path = filedialog.askdirectory(parent=self.root,
                                           title="选择待压缩文件夹（可连续添加多个）")
            if path:
                path = os.path.normpath(path)
                existing = set(self.zip_list.get(0, "end"))
                if path not in existing:
                    self.zip_list.insert("end", path)
                    self._sb_sync(self.zip_list)
                else:
                    messagebox.showinfo("提示", "该文件夹已在列表中。")
        except Exception as e:
            messagebox.showerror("错误", f"打开文件夹对话框失败：{e}")

    def _remove_zip_srcs(self):
        for idx in reversed(self.zip_list.curselection()):
            self.zip_list.delete(idx)
        self._sb_sync(self.zip_list)

    def _clear_zip_srcs(self):
        self.zip_list.delete(0, "end")
        self._sb_sync(self.zip_list)

    def _pick_zip_out(self):
        try:
            path = filedialog.askdirectory(parent=self.root,
                                           title="选择输出目录（留空则生成在每个文件夹旁边）")
            if path:
                self.zip_out_var.set(path)
        except Exception as e:
            messagebox.showerror("错误", f"打开文件夹对话框失败：{e}")

    # ================= 拷贝流程 =================

    def start_copy(self):
        if self.phase != "idle":
            return
        src = self.src_real_path.strip()
        if not src or not os.path.isdir(src):
            messagebox.showerror("错误", "请先选择有效的源目录（相机存储卡）。")
            return
        dst = self.dst_var.get().strip()
        if not dst:
            messagebox.showerror("错误", "请填写目标根目录。")
            return
        date_dir = self.date_var.get().strip()
        if not re.fullmatch(r"\d{4}_\d{2}_\d{2}", date_dir):
            messagebox.showerror("错误", "日期文件夹格式应为 yyyy_MM_dd，例如 2026_08_23。")
            return
        src_abs = os.path.abspath(src)
        dst_abs = os.path.abspath(dst)
        if dst_abs == src_abs or dst_abs.startswith(src_abs + os.sep):
            messagebox.showerror("错误", "目标根目录不能位于源目录内部，否则会拷贝到自身。")
            return

        self.last_dst, self.last_date = dst, date_dir
        self.phase = "copy"
        self._set_progress(self.cp_progress, 0, "正在扫描源目录…")
        self._log(self.cp_log, "=" * 60)
        self._log(self.cp_log, f"源目录：{src}")
        self._log(self.cp_log, f"目标：{dst}\\{date_dir}")
        self._set_state(self.cp_start_btn, "disabled")
        self._set_state(self.cp_stop_btn, "normal")

        self.copier = CameraCopier(
            source=src, dest_root=dst, date_dir=date_dir,
            verify=self.verify_var.get(),
            skip_existing=self.skip_var.get(),
            copy_unknown=self.unknown_var.get(),
            callback=lambda ev: self.msg_queue.put(ev),
        )
        self.copy_thread = threading.Thread(target=self.copier.run, daemon=True)
        self.copy_thread.start()

    # ================= 压缩流程 =================

    def start_zip(self):
        if self.phase != "idle":
            return
        if self.seven_zip is None:
            messagebox.showerror("错误", "未检测到 7-Zip。\n请安装 7-Zip 后点击「重新检测 7-Zip」。")
            return
        folders = [f for f in self.zip_list.get(0, "end")]
        folders = [os.path.normpath(f) for f in folders]
        missing = [f for f in folders if not os.path.isdir(f)]
        if not folders:
            messagebox.showerror("错误", "请先添加待压缩文件夹。")
            return
        if missing:
            messagebox.showerror("错误", "以下文件夹不存在：\n" + "\n".join(missing))
            return
        out_dir = self.zip_out_var.get().strip()
        jobs = []
        for folder in folders:
            if out_dir:
                archive = os.path.join(out_dir, os.path.basename(folder) + ".7z")
            else:
                archive = folder + ".7z"   # 生成在文件夹旁边
            jobs.append((folder, archive))
        self._run_zip_batch("zip", jobs, self._level_value(self.zip_level_var.get()))

    def _run_zip_batch(self, page, jobs, level):
        """批量压缩：jobs 为 [(folder, archive), ...]。逐个压缩，共用进度区。"""
        self.phase = f"zip-{page}"
        widgets = self.cp_progress if page == "copy" else self.zp_progress
        log_widget = self.cp_log if page == "copy" else self.zp_log
        start_btn = self.cp_start_btn if page == "copy" else self.zp_start_btn
        stop_btn = self.cp_stop_btn if page == "copy" else self.zp_stop_btn

        self._set_state(start_btn, "disabled")
        self._set_state(stop_btn, "normal")
        self.zip_stop_event = threading.Event()

        def worker():
            for i, (folder, archive) in enumerate(jobs, 1):
                if self.zip_stop_event.is_set():
                    break
                self.msg_queue.put({"type": "zip_start", "page": page,
                                    "idx": i, "total": len(jobs),
                                    "folder": folder, "archive": archive})
                self.msg_queue.put({"type": "zip_log", "page": page,
                                    "message": f"压缩 {i}/{len(jobs)}：{folder} -> {archive}（级别 {level}）"})

                def cb(percent, info):
                    self.msg_queue.put({"type": "zip_p", "page": page,
                                        "percent": percent, "file": info,
                                        "idx": i, "total": len(jobs)})

                ok, cancelled, err = compress_folder(
                    self.seven_zip, folder, archive, level,
                    progress_cb=cb, stop_event=self.zip_stop_event)
                self.msg_queue.put({"type": "zip_folder_done", "page": page,
                                    "ok": ok, "cancelled": cancelled, "error": err,
                                    "folder": folder, "archive": archive,
                                    "idx": i, "total": len(jobs)})
                if cancelled:
                    break

            self.msg_queue.put({"type": "zip_all_done", "page": page,
                                "cancelled": self.zip_stop_event.is_set()})

        threading.Thread(target=worker, daemon=True).start()

    def stop_current(self):
        if self.phase.startswith("zip") and self.zip_stop_event:
            self.zip_stop_event.set()
            self._log(self.zp_log if self.phase == "zip-zip" else self.cp_log,
                      "已请求停止压缩…")
        elif self.phase == "copy" and self.copier:
            self.copier.stop()
            self._log(self.cp_log, "已请求停止拷贝（拷贝完当前文件后停止）…")

    # ================= 消息泵 =================

    def _pump(self):
        try:
            while True:
                self._handle_event(self.msg_queue.get_nowait())
        except queue.Empty:
            pass
        self.root.after(100, self._pump)

    def _handle_event(self, ev):
        t = ev.get("type")

        if t == "start":
            if ev.get("phase") == "scan":
                self._set_progress(self.cp_progress, 0, "正在扫描源目录…")
            else:
                total = ev.get("total", 0) or 1
                self._set_progress(self.cp_progress, 0, f"共 {total} 个文件，开始拷贝…")

        elif t == "log":
            self._log(self.cp_log, ev.get("message", ""))

        elif t == "file":
            current = ev.get("current", 0)
            total = ev.get("total", 0) or 1
            pct = round(current / total * 100)
            name = ev.get("name", "")
            status = ev.get("status", "")
            label = {"copied": "已拷贝", "skipped": "已存在，跳过",
                     "failed": "失败", "mismatch": "校验不一致"}.get(status, status)
            self._set_progress(self.cp_progress, pct,
                               f"[{current}/{total}] {name}（{label}）",
                               f"{ev.get('dst', '')}"
                               + (f"  错误：{ev.get('error', '')}" if ev.get("error") else ""))
            if status in ("copied", "failed", "mismatch"):
                self._log(self.cp_log, f"{name}  {label}"
                          + (f"  错误：{ev.get('error', '')}" if ev.get("error") else ""))

        elif t == "zip_start":
            page = ev.get("page")
            widgets = self.cp_progress if page == "copy" else self.zp_progress
            idx, total = ev.get("idx", 1), ev.get("total", 1)
            self._set_progress(widgets, 0,
                               f"正在压缩 {idx}/{total}：{os.path.basename(ev.get('folder', ''))}")

        elif t == "zip_log":
            page = ev.get("page")
            log_widget = self.cp_log if page == "copy" else self.zp_log
            self._log(log_widget, ev.get("message", ""))

        elif t == "zip_p":
            page = ev.get("page")
            widgets = self.cp_progress if page == "copy" else self.zp_progress
            percent = ev.get("percent")
            info = ev.get("file", "")
            idx, total = ev.get("idx", 1), ev.get("total", 1)
            if percent is None:
                self._set_progress(widgets, 0, f"正在压缩 {idx}/{total}… {info}")
            else:
                self._set_progress(widgets, percent,
                                   f"正在压缩 {idx}/{total}… {info}")

        elif t == "zip_folder_done":
            page = ev.get("page")
            log_widget = self.cp_log if page == "copy" else self.zp_log
            ok, cancelled, err = ev.get("ok"), ev.get("cancelled"), ev.get("error")
            archive = ev.get("archive", "")
            idx, total = ev.get("idx", 1), ev.get("total", 1)
            if ok:
                size = human_size(os.path.getsize(archive)) if os.path.exists(archive) else "?"
                self._log(log_widget, f"[{idx}/{total}] 压缩完成：{archive}（{size}）")
            elif cancelled:
                self._log(log_widget, f"[{idx}/{total}] 压缩已取消。")
            else:
                self._log(log_widget, f"[{idx}/{total}] 压缩失败：{err}")

        elif t == "zip_all_done":
            page = ev.get("page")
            widgets = self.cp_progress if page == "copy" else self.zp_progress
            log_widget = self.cp_log if page == "copy" else self.zp_log
            start_btn = self.cp_start_btn if page == "copy" else self.zp_start_btn
            stop_btn = self.cp_stop_btn if page == "copy" else self.zp_stop_btn
            cancelled = ev.get("cancelled", False)
            self.phase = "idle"
            self.zip_stop_event = None
            self._set_state(start_btn, "normal")
            self._set_state(stop_btn, "disabled")
            if cancelled:
                self._set_progress(widgets, 0, "已停止")
                self._log(log_widget, "批量压缩已停止。")
            else:
                self._set_progress(widgets, 100, "批量压缩完成")
                self._log(log_widget, "批量压缩全部完成。")
                messagebox.showinfo("压缩完成", "批量压缩全部完成，详见日志。")

        elif t == "pv_tile":
            idx = ev.get("idx")
            img = ev.get("img")
            tile = self.pv_tiles.get(idx)
            if tile and img is not None:
                box, label = tile
                photo = ImageTk.PhotoImage(img)   # 必须在主线程创建
                self.pv_photos[idx] = photo       # 持有引用防止被回收
                label.config(image=photo, text="")

        elif t == "pv_done":
            self.pv_status.config(text=f"缩略图生成完成，共 {ev.get('total', 0)} 个。")

        elif t == "error":
            self._log(self.cp_log, "错误：" + ev.get("message", ""))
            self._set_progress(self.cp_progress, 0, "出错")
            self.phase = "idle"
            self._set_state(self.cp_start_btn, "normal")
            self._set_state(self.cp_stop_btn, "disabled")
            messagebox.showerror("错误", ev.get("message", ""))

        elif t == "done":
            s = ev.get("summary") or {}
            cancelled = ev.get("cancelled", False)
            lines = ["拷贝已停止（未完成）。" if cancelled else "拷贝完成！",
                     f"成功 {s.get('copied', 0)}  |  跳过 {s.get('skipped', 0)}"
                     f"  |  失败 {s.get('failed', 0)}",
                     f"校验通过 {s.get('verified', 0)}  |  不一致 {s.get('mismatch', 0)}",
                     f"总大小 {human_size(s.get('total_bytes', 0))}"]
            by_fmt = s.get("by_format") or {}
            if by_fmt:
                lines.append("按格式：" + "，".join(
                    f"{k} {v}" for k, v in sorted(by_fmt.items())))
            if s.get("failed_list"):
                lines.append("失败文件：")
                lines += [f"  {a} -> {b}（{err}）"
                          for a, b, err in s["failed_list"][:20]]
            for ln in lines:
                self._log(self.cp_log, ln)
            self.phase = "idle"
            self._set_state(self.cp_start_btn, "normal")
            self._set_state(self.cp_stop_btn, "disabled")

            if not cancelled and self.auto_zip_var.get():
                if self.seven_zip:
                    folder = os.path.join(self.last_dst, self.last_date)
                    archive = os.path.join(self.last_dst, self.last_date + ".7z")
                    self._log(self.cp_log, "开始自动压缩…")
                    self._run_zip_batch("copy", [(folder, archive)],
                                        self._level_value(self.auto_level_var.get()))
                    return
                self._log(self.cp_log, "未检测到 7-Zip，已跳过自动压缩。")
            messagebox.showinfo("结果", "\n".join(lines))


# --------------------------------------------------------------------------
# 命令行模式
# --------------------------------------------------------------------------

def main_cli(argv):
    parser = argparse.ArgumentParser(
        description="相机拷卡工具（命令行版）：按格式分类拷贝到 日期/原图/格式 目录")
    parser.add_argument("source", help="源目录（相机存储卡，如 D:\\ 或 D:\\DCIM）")
    parser.add_argument("dest", help="目标根目录")
    parser.add_argument("-d", "--date", default=None,
                        help="日期文件夹名（yyyy_MM_dd），默认今天")
    parser.add_argument("--verify", action="store_true",
                        help="拷贝后做 Hash 校验（较慢）")
    parser.add_argument("--no-skip", action="store_true",
                        help="覆盖目标已有同名文件（默认跳过）")
    parser.add_argument("--no-unknown", action="store_true",
                        help="不拷贝未识别格式的文件")
    parser.add_argument("--compress", action="store_true",
                        help="拷贝完成后把日期文件夹压缩为 .7z")
    parser.add_argument("--7z", dest="seven_zip", default=None,
                        help="7z.exe 路径（默认自动检测）")
    parser.add_argument("--level", type=int, default=DEFAULT_7Z_LEVEL,
                        help="压缩级别 0-9（默认 5）")
    args = parser.parse_args(argv)

    summary = run_cli(args.source, args.dest, date_dir=args.date,
                      verify=args.verify, skip_existing=not args.no_skip,
                      copy_unknown=not args.no_unknown)

    # 一个都没拷/没跳过 = 拷贝失败（如源目录不存在），返回非零退出码
    if summary.get("copied", 0) == 0 and summary.get("skipped", 0) == 0:
        print("错误：没有成功拷贝任何文件（请检查源目录是否正确）。")
        sys.exit(1)

    if args.compress:
        date_dir = args.date or today_str()
        folder = os.path.join(args.dest, date_dir)
        archive = folder + ".7z"
        seven_zip = args.seven_zip or find_7z()
        if not seven_zip:
            print("跳过压缩：未找到 7-Zip（7z.exe）。可用 --7z 指定路径。")
            return summary
        print(f"\n正在压缩：{folder} -> {archive}（级别 {args.level}）")
        ok, cancelled, err = compress_folder(
            seven_zip, folder, archive, level=args.level,
            progress_cb=lambda p, info: print(f"\r压缩进度 {p}%  {info}", end="", flush=True))
        print()
        if ok:
            print(f"压缩完成：{archive}（{human_size(os.path.getsize(archive))}）")
        else:
            print(f"压缩失败：{err}")
    return summary


def main_zip_cli(argv):
    """批量压缩模式：python main.py --cli --zip-mode <文件夹> [<文件夹> …]"""
    parser = argparse.ArgumentParser(
        description="批量压缩模式：把多个文件夹分别压缩为 .7z")
    parser.add_argument("folders", nargs="+", help="待压缩文件夹（可多个）")
    parser.add_argument("--out", default=None,
                        help="输出目录（默认生成在每个文件夹旁边）")
    parser.add_argument("--7z", dest="seven_zip", default=None,
                        help="7z.exe 路径（默认自动检测）")
    parser.add_argument("--level", type=int, default=DEFAULT_7Z_LEVEL,
                        help="压缩级别 0-9（默认 5）")
    args = parser.parse_args(argv)

    seven_zip = args.seven_zip or find_7z()
    if not seven_zip:
        print("未找到 7-Zip（7z.exe），可用 --7z 指定路径。")
        return

    ok_count = 0
    total = len(args.folders)
    for folder in args.folders:
        folder = os.path.normpath(folder)
        if not os.path.isdir(folder):
            print(f"跳过（目录不存在）：{folder}")
            continue
        if args.out:
            archive = os.path.join(args.out, os.path.basename(folder) + ".7z")
        else:
            archive = folder + ".7z"
        print(f"[{ok_count + 1}/{total}] 压缩：{folder} -> {archive}（级别 {args.level}）")
        ok, cancelled, err = compress_folder(
            seven_zip, folder, archive, level=args.level,
            progress_cb=lambda p, info: print(f"\r  进度 {p}%  {info}", end="", flush=True))
        print()
        if ok:
            ok_count += 1
            print(f"  完成：{archive}（{human_size(os.path.getsize(archive))}）")
        else:
            print(f"  失败：{err}")
    print(f"批量压缩结束：成功 {ok_count}/{total}")


if __name__ == "__main__":
    if "--cli" in sys.argv:
        if "--zip-mode" in sys.argv:
            main_zip_cli(sys.argv[sys.argv.index("--zip-mode") + 1:])
        else:
            main_cli(sys.argv[sys.argv.index("--cli") + 1:])
    else:
        # 开启最佳 DPI 感知：高分屏按原生分辨率渲染，文字(边缘)更清晰
        try:
            import ctypes
            # Per-Monitor-Aware V2（Win10 1703+，最清晰的方案）
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)      # Per-Monitor-Aware
            except Exception:
                try:
                    ctypes.windll.user32.SetProcessDPIAware()       # 旧版
                except Exception:
                    pass
        # 注意顺序：必须先创建主窗口再创建 ttk.Style。
        # 若先 Style() 再 Tk()，tkinter 会偷偷建一个隐藏根窗口，
        # 使 filedialog 弹在隐藏窗口上，导致"文件夹选不了"。
        root = tk.Tk()
        # 字体：优先经典黑体 SimHei，没有则用同为黑体的微软雅黑（保证黑体风格且可用）
        try:
            import tkinter.font as tkfont
            fams = tkfont.families(root)
            if "SimHei" in fams:
                FONT = "SimHei"
            elif "Microsoft YaHei UI" in fams:
                FONT = "Microsoft YaHei UI"
        except Exception:
            pass
        # 让 Tk 字体缩放严格匹配系统 DPI，文字按原生像素渲染，更清晰不发虚
        try:
            import ctypes
            root.tk.call("tk", "scaling", ctypes.windll.user32.GetDpiForSystem() / 72.0)
        except Exception:
            pass
        style = ttk.Style(root)
        # 用 clam 主题，把下拉框/进度条自绘成与界面一致的浅色，避免原生控件出现"色块"
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        try:
            style.configure("Dark.TCombobox",
                            fieldbackground=THEME["input_bg"],
                            background="#FFFFFF",
                            foreground=THEME["text"],
                            arrowcolor=THEME["accent"],
                            bordercolor=THEME["input_border"],
                            lightcolor="#FFFFFF",
                            darkcolor="#FFFFFF")
            style.map("Dark.TCombobox", fieldbackground=[("readonly", THEME["input_bg"])])
            style.configure("Dark.Horizontal.TProgressbar",
                            background=THEME["accent"],
                            troughcolor="#E2E8F3",
                            bordercolor="#E2E8F3",
                            lightcolor=THEME["accent"],
                            darkcolor=THEME["accent"])
        except tk.TclError:
            pass
        CopyToolApp(root)
        # 窗口自动居中（适配不同分辨率屏幕）
        root.update_idletasks()
        _w, _h = 920, 640
        _sw, _sh = root.winfo_screenwidth(), root.winfo_screenheight()
        _x = max(0, (_sw - _w) // 2)
        _y = max(0, (_sh - _h) // 2)
        root.geometry(f"{_w}x{_h}+{_x}+{_y}")
        root.mainloop()
