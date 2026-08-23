# -*- coding: utf-8 -*-
"""
配置模块：格式映射表、未识别文件处理方式。

只需维护 FORMAT_MAP 即可增删格式分类：
  键   = 文件扩展名（小写，不含点）
  值   = 拷贝后存放的文件夹名称
"""

# 图片/视频格式 -> 分类文件夹名（可自行增删）
FORMAT_MAP = {
    # ---- JPEG ----
    "jpg": "JPG",
    "jpeg": "JPG",
    "jpe": "JPG",
    "jfif": "JPG",
    # ---- RAW（各家相机原始格式，统一归入 RAW）----
    "nef": "RAW",   # 尼康
    "cr2": "RAW",   # 佳能
    "cr3": "RAW",   # 佳能
    "arw": "RAW",   # 索尼
    "raf": "RAW",   # 富士
    "orf": "RAW",   # 奥之心 / 奥林巴斯
    "rw2": "RAW",   # 松下
    "pef": "RAW",   # 宾得
    "srw": "RAW",   # 三星
    "dng": "RAW",   # Adobe 通用 RAW
    "x3f": "RAW",   # 适马
    "erf": "RAW",   # 爱普生
    "mrw": "RAW",   # 美能达
    "raw": "RAW",   # 其他 RAW
    # ---- 其他常见图片 ----
    "png": "PNG",
    "tif": "TIFF",
    "tiff": "TIFF",
    "heic": "HEIC",
    "heif": "HEIF",
    "gif": "GIF",
    "bmp": "BMP",
    "webp": "WEBP",
    # ---- 相机视频 ----
    "mp4": "VIDEO",
    "mov": "VIDEO",
    "mts": "VIDEO",
    "m2ts": "VIDEO",
    "avi": "VIDEO",
}

# 不在映射表中的文件归入的文件夹名称
UNKNOWN_FOLDER = "其他"

# 目标目录结构中的两个固定文件夹
ORIGINAL_FOLDER = "原图"
EDITED_FOLDER = "修图"

# 日期文件夹格式（例如 2026_08_23）
DATE_PATTERN = "%Y_%m_%d"

# --------------------------------------------------------------------------
# 界面主题（ECHO Next 风格 · 浅色毛玻璃）
# --------------------------------------------------------------------------
THEME = {
    "bg": "#EAEFF7",            # 页面底色（浅蓝灰）
    "sidebar": "#F3F6FC",       # 左侧导航面板（浅霜白）
    "card": "#FFFFFF",          # 卡片（白色磨砂）
    "border": "#DCE4F0",        # 卡片边框
    "text": "#1C2B4A",          # 正文（深藏青）
    "dim": "#8492AC",           # 次要文字
    "accent": "#4A7DE0",        # 强调色（蓝）
    "accent_hover": "#5B8DEF",
    "danger": "#E5534B",
    "ok": "#2E9E6B",
    "input_bg": "#F1F4FA",      # 输入框背景
    "input_border": "#D8E2F0",  # 输入框边框
}

# 背景渐变（顶部 -> 底部）：极浅的蓝灰渐变，干净清爽。
# GLASS_BLOBS 设为空列表 = 不画光斑（stipple 光斑在真实屏幕上会变成噪点、显得混乱）。
GLASS_GRADIENT = ("#EEF3FA", "#E4EBF6")
GLASS_BLOBS = []

# --------------------------------------------------------------------------
# 7-Zip 压缩默认值
# --------------------------------------------------------------------------
DEFAULT_7Z_LEVEL = 5           # 0=仅存储(最快) … 5=标准 … 9=极限(最慢)
