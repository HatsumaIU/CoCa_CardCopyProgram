# CoCa（相机拷卡工具）

相机存储卡拷贝 + 自动分类归档 + 7-Zip 压缩 + 照片预览。纯 Python 标准库实现（tkinter 图形界面），界面为 **ECHO Next 播放器同款浅色毛玻璃**：浅蓝灰渐变背景 + 白色磨砂圆角卡片 + 蓝色强调 + 左侧圆角胶囊导航（分组标题 + PRO 徽标），窗口实底不透明、质感来自卡片与底层背景。

**压缩功能需要安装 [7-Zip](https://www.7-zip.org/)**（免费开源），程序会自动检测安装位置，也可手动指定。
**缩略图预览需要 [Pillow](https://pypi.org/project/Pillow/)**（`pip install Pillow`）；未安装时预览页自动降级为文件名列表。

## 功能

- **拷贝**：从相机存储卡（自动识别可移动磁盘）拷贝照片，按格式自动分类归档
- **目录结构**：目标根目录下创建 `日期（yyyy_MM_dd）/ 原图 / <格式>` + `日期/修图` 空文件夹，如 `2026_08_23`
- **格式分类**：`.jpg` → `JPG`、`.nef` → `RAW`（内置各家 RAW 映射，可在 `config.py` 自定义）
- **进度显示**：进度条 + 大号百分比 + 当前文件详情
- **7-Zip 压缩**：拷贝完成后自动把日期文件夹压成 `.7z`；也可**批量压缩多个文件夹**（每个生成独立 .7z），压缩级别 0-9
- **照片预览**：浏览存储卡上的照片缩略图（RAW/视频显示占位块）
- **浅色毛玻璃界面**：ECHO Next 风格——浅蓝灰渐变背景、白色磨砂圆角卡片（**矩形 + 四角圆弧的真圆角**、无灰色边框，消除"方框感"）、蓝色强调按钮、左侧**圆角毛玻璃功能栏**（白色圆角面板 + 分组标题 + PRO 徽标）。中部内容区可滚动。
- **标准标题栏**：采用 Windows 原生设计，用 DWM 设为**深色标题栏**——最小化/最大化/关闭为 Windows 原生按钮且全部可用，标题栏不再是白条。窗口可正常拖动、缩放。
- **Windows 系统滚动条**：界面采用 Windows 原生 `vista` 主题，滚动条、下拉框、进度条为系统原生样式。
- **全局鼠标滚轮**：指针停在哪个可滚动区域（页面/日志/预览/列表）就滚动哪个，修复了滚轮无效问题。
- **高清渲染**：开启 DPI 感知，高分屏下按原生分辨率渲染，界面清晰不模糊（画面更细致）。
- **窗口自适应**：启动自动居中，任意分辨率/窗口比例下完整显示；操作按钮常驻页面顶部、退出按钮常驻底部，预览网格随窗口宽度自动重排
- 可选 Hash 拷贝校验、跳过已存在文件、同名文件自动加 `_1` 后缀
- 图形界面 + 命令行两种用法

## 拷贝后的目录结构

```
目标根目录/
└── 2026_08_23/                  ← 日期文件夹（yyyy_MM_dd）
    ├── 原图/                    ← 原始照片
    │   ├── JPG/                 ← .jpg .jpeg 等
    │   ├── RAW/                 ← .nef .cr2 .arw .dng 等
    │   ├── PNG/  TIFF/  HEIC/  VIDEO/  其他/
    └── 修图/                    ← 留给后期处理后的照片（初始为空）

2026_08_23.7z                    ← （可选）拷贝完成后自动生成的压缩包
```

## 使用方法

### 图形界面（推荐）

```bash
python main.py          # 或 pythonw main.py（不弹控制台）
```

界面左侧是导航栏，共三个页面：

- **拷贝页**：选择源存储卡 → 目标根目录 → 日期 → 勾选选项 → 开始拷贝
  - 进度条实时显示百分比和当前文件
  - 勾选「拷贝完成后自动压缩日期文件夹为 .7z」即可自动生成压缩包
- **预览页**：选择目录 → 点「扫描」，以缩略图网格浏览照片（安装 Pillow 后显示图片，否则显示文件名列表）
- **压缩页**：点「添加文件夹…」加入一个或多个文件夹 → 设置压缩级别和输出目录 → 开始批量压缩
  - 输出目录留空时，压缩包生成在每个文件夹旁边（同名 `.7z`）
- 左侧底部显示 7-Zip 状态；未安装时压缩功能会提示，安装后可点「重新检测 7-Zip」

### 命令行

```bash
# 拷贝 + 自动压缩
python main.py --cli <源目录> <目标根目录> [选项]

# 批量压缩多个文件夹
python main.py --cli --zip-mode <文件夹1> [<文件夹2> …] [--out 输出目录] [--level 9]

# 示例
python main.py --cli D:\ D:\照片 --compress
python main.py --cli D:\DCIM D:\照片 --verify -d 2026_08_23 --compress --level 9
python main.py --cli --zip-mode "D:\照片\2026_08_23" "D:\照片\2026_08_24" --level 7
```

拷贝模式选项：

| 选项 | 说明 |
| --- | --- |
| `-d, --date` | 日期文件夹名（yyyy_MM_dd），默认今天 |
| `--verify` | 拷贝后 Hash 校验（较慢） |
| `--no-skip` | 覆盖已存在文件（默认跳过） |
| `--no-unknown` | 不拷贝未识别格式的文件 |
| `--compress` | 拷贝完成后压缩日期文件夹为 .7z |
| `--7z <路径>` | 指定 7z.exe 路径（默认自动检测） |
| `--level <0-9>` | 压缩级别，默认 5 |

## 打包为 exe

### 方式一：启动器 exe（本机即可构建，无需联网）

用 Windows 自带的 C# 编译器（csc.exe）编译原生启动器，双击即可运行程序：

```bash
cd camera_copy_tool
python build_exe.py
```

生成到 `dist\` 目录：

| exe | 用途 |
| --- | --- |
| `dist\CoCa.exe` | 图形界面版，双击运行（无控制台窗口） |
| `dist\CoCa-cli.exe` | 命令行版，透传参数和退出码 |

启动器会自动在自身同目录 / 上级 / 上上级找到 `main.py`，并用本机 Python 运行。
**要求目标机器安装 Python 3**（`pythonw.exe` / `python.exe` 在 PATH 中即可）。

```bash
# 命令行版用法与 python main.py 完全一致
dist\CoCa-cli.exe --cli D:\ D:\照片 --compress
```

### 方式二：完全独立的单文件 exe（需联网安装 PyInstaller）

在**能联网的机器**上运行（会生成不依赖 Python 的独立 exe，体积约 10-30 MB）：

```bash
cd camera_copy_tool
build_pyinstaller.bat
```

等价命令：
```bash
pip install pyinstaller
pyinstaller --noconfirm --clean --onefile --windowed --name CoCa main.py
pyinstaller --noconfirm --clean --onefile --console   --name CoCa-cli main.py
```

生成 `dist\CoCa.exe`（GUI）和 `dist\CoCa-cli.exe`（CLI），
可拷贝到任何 Windows 机器直接运行，无需安装 Python。

## 自定义格式分类

编辑 `config.py` 中的 `FORMAT_MAP`：

```python
FORMAT_MAP = {
    "jpg": "JPG",     # 扩展名（小写，不带点） -> 文件夹名
    "nef": "RAW",
    "cr2": "RAW",
    ...
}
```

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `main.py` | Pixcall 风格图形界面（拷贝/预览/压缩三页）+ 命令行入口 |
| `copier.py` | 拷贝核心：扫描、分类、建目录、拷贝、校验 |
| `archive.py` | 7-Zip 集成：自动定位 7z.exe、压缩并解析进度 |
| `config.py` | 格式映射、浅色毛玻璃主题色、压缩默认值 |
| `glass.py` | 毛玻璃效果：渐变背景、柔光光斑、圆角卡片绘制 |
| `build_exe.py` | 用 csc.exe 编译启动器 exe（无需联网） |
| `gui_launcher.cs` / `cli_launcher.cs` | exe 启动器 C# 源码 |
| `build_pyinstaller.bat` | 联网机器上生成完全独立 exe 的脚本 |

## 环境要求

- Windows（盘符自动识别依赖 Windows API；其他系统需手动浏览选择源目录）
- Python 3.8+（自带 tkinter）
- 压缩功能：安装 [7-Zip](https://www.7-zip.org/)
- 缩略图预览（可选）：`pip install Pillow`
