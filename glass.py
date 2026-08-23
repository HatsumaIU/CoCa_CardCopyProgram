# -*- coding: utf-8 -*-
"""
毛玻璃（Glassmorphism）效果模块：
  1. enable_acrylic(root)  —— 用 Windows DWM API 把窗口本身变成 Acrylic 磨砂
     （模糊桌面壁纸 + 半透明着色），Win10 1809+ 支持；Win11 额外开启圆角。
  2. draw_gradient / draw_glow —— 在 Canvas 上绘制深色渐变背景和彩色柔光光斑。
  3. rounded_rect —— 用"单个平滑多边形"画圆角矩形，避免矩形+圆弧拼接产生锯齿毛刺。
"""

import ctypes
import math
import os
import tkinter as tk

from config import GLASS_BLOBS, GLASS_GRADIENT

# --------------------------------------------------------------------------
# 窗口级 Acrylic 磨砂
# --------------------------------------------------------------------------

_ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
_WCA_ACCENT_POLICY = 19
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWCP_ROUND = 2


class _ACCENT_POLICY(ctypes.Structure):
    _fields_ = [("AccentState", ctypes.c_int),
                ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_uint),
                ("AnimationId", ctypes.c_int)]


class _WINCOMPATTRDATA(ctypes.Structure):
    _fields_ = [("Attribute", ctypes.c_int),
                ("Data", ctypes.c_void_p),
                ("SizeOfData", ctypes.c_ulong)]


def _top_hwnd(root: tk.Tk):
    """获取 tkinter 窗口的顶层 Windows 句柄。"""
    if os.name != "nt":
        return None
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(root.winfo_id())
        return hwnd
    except Exception:
        return None


def enable_acrylic(root: tk.Tk, tint: int = 0xE610131C) -> bool:
    """给窗口开启 Acrylic 磨砂效果。

    tint 为 ABGR 着色（默认半透明深蓝黑）。
    返回是否成功开启。失败（如 Win10 1809 以下）返回 False，调用方应退回普通背景。
    """
    if os.name != "nt":
        return False
    try:
        hwnd = _top_hwnd(root)
        if not hwnd:
            return False
        accent = _ACCENT_POLICY()
        accent.AccentState = _ACCENT_ENABLE_ACRYLICBLURBEHIND
        accent.AccentFlags = 2
        accent.GradientColor = tint
        data = _WINCOMPATTRDATA()
        data.Attribute = _WCA_ACCENT_POLICY
        data.Data = ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p)
        data.SizeOfData = ctypes.sizeof(accent)
        ok = ctypes.windll.user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
        # Win11 圆角（失败无妨）
        try:
            from ctypes import wintypes
            pref = ctypes.c_int(_DWMWCP_ROUND)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, _DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(pref), ctypes.sizeof(pref))
        except Exception:
            pass
        return bool(ok)
    except Exception:
        return False


def apply_glass_background(root: tk.Tk):
    """开启磨砂并把主背景切换为透明色，让窗口空隙露出磨砂效果。
    返回是否开启成功。"""
    if enable_acrylic(root):
        try:
            root.wm_attributes("-transparentcolor", GLASS_TRANSPARENT)
            root.configure(bg=GLASS_TRANSPARENT)
            return True
        except Exception:
            root.configure(bg="#10131C")
            return False
    return False


# --------------------------------------------------------------------------
# 渐变与光斑绘制（Canvas）
# --------------------------------------------------------------------------

def draw_gradient(canvas: tk.Canvas, width: int, height: int, colors=GLASS_GRADIENT):
    """在画布上绘制纵向渐变背景（颜色插值，分段画横条）。"""
    if width <= 0 or height <= 0:
        return
    canvas.delete("grad")
    n = max(1, len(colors) - 1)
    seg = max(1, height // (n * 24))
    for y in range(0, height, seg):
        t = y / max(1, height - 1)
        # 找到 t 所在的颜色区间
        pos = min(n - 1, int(t * n))
        f = (t * n) - pos
        c1 = colors[pos]
        c2 = colors[pos + 1]
        r = int(int(c1[1:3], 16) + (int(c2[1:3], 16) - int(c1[1:3], 16)) * f)
        g = int(int(c1[3:5], 16) + (int(c2[3:5], 16) - int(c1[3:5], 16)) * f)
        b = int(int(c1[5:7], 16) + (int(c2[5:7], 16) - int(c1[5:7], 16)) * f)
        color = f"#{r:02x}{g:02x}{b:02x}"
        canvas.create_rectangle(0, y, width, min(height, y + seg + 1),
                                fill=color, outline="", tags="grad")


def draw_glow(canvas: tk.Canvas, width: int, height: int, blobs=GLASS_BLOBS):
    """绘制柔光光斑：同心圆 + stipple 半透明，模拟网页模糊色块。"""
    if width <= 0 or height <= 0:
        return
    canvas.delete("blob")
    for color, (fx, fy) in blobs:
        cx, cy = int(width * fx), int(height * fy)
        radius = int(max(width, height) * 0.38)
        # 由外到内，逐层加深、逐层缩小（stipple 模拟半透明）
        for i, stipple in enumerate(("gray50", "gray25", "")):
            r = max(8, radius - i * int(radius * 0.22))
            canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                               fill=color, outline="", stipple=stipple, tags="blob")


def paint_backdrop(canvas: tk.Canvas, width: int, height: int):
    """绘制完整背景：渐变 + 光斑。"""
    draw_gradient(canvas, width, height)
    draw_glow(canvas, width, height)


def _rrect_points(x1, y1, x2, y2, r, n=32):
    """生成圆角矩形边界点：单个多边形，四角圆弧密集采样（每角 n 点），无接缝、近圆滑。"""
    r = max(1, min(r, (x2 - x1) // 2, (y2 - y1) // 2))
    pts = []

    def arc(cx, cy, a0, a1):
        for i in range(n):
            a = math.radians(a0 + (a1 - a0) * i / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))

    arc(x1 + r, y1 + r, 180, 270)   # 左上
    arc(x2 - r, y1 + r, 270, 360)   # 右上
    arc(x2 - r, y2 - r, 0, 90)      # 右下
    arc(x1 + r, y2 - r, 90, 180)    # 左下
    flat = []
    for px, py in pts:
        flat.append(px)
        flat.append(py)
    return flat


def rounded_rect(canvas: tk.Canvas, x1, y1, x2, y2, radius=14,
                 fill=None, outline=None, width=1, tags=None):
    """圆角矩形：单个密集多边形绘制（每角 32 点），边缘直、角近圆、无接缝毛刺。
    有 outline 时先画稍大的圆角多边形当边框色，再画内缩圆角多边形填内容色。"""
    r = max(1, min(radius, (x2 - x1) // 2, (y2 - y1) // 2))

    def draw(xa, ya, xb, yb, rr, col):
        canvas.create_polygon(_rrect_points(xa, ya, xb, yb, rr),
                              fill=col, outline="", tags=tags)

    if outline:
        draw(x1, y1, x2, y2, r, outline)
        inset = max(1, width)
        draw(x1 + inset, y1 + inset, x2 - inset, y2 - inset,
             max(1, r - inset), fill)
    else:
        draw(x1, y1, x2, y2, r, fill)
