# FAHAI 项目资源说明

本目录包含 FAHAI 图形化流程设计器的所有资源文件。

## 目录结构

```
resources/
├── icons/          # 图标文件
├── styles/         # 样式表文件
├── images/         # 图片资源
├── fonts/          # 字体文件
├── themes/         # 主题配置
└── README.md       # 本说明文件
```

## 图标资源 (icons/)

包含应用程序使用的所有图标文件，建议使用 SVG 格式以支持高DPI显示。

推荐图标：
- app_icon.svg/png - 应用程序图标
- camera.svg - 相机模块图标
- trigger.svg - 触发模块图标
- model.svg - 模型模块图标
- postprocess.svg - 后处理模块图标
- play.svg - 运行按钮图标
- stop.svg - 停止按钮图标
- pause.svg - 暂停按钮图标
- settings.svg - 设置图标
- connect.svg - 连接图标
- disconnect.svg - 断开图标

## 样式表 (styles/)

包含 Qt 样式表文件，用于定制应用程序外观。

推荐样式文件：
- main.qss - 主要样式表
- dark_theme.qss - 深色主题
- light_theme.qss - 浅色主题
- module_widgets.qss - 模块控件样式
- canvas.qss - 画布样式

## 图片资源 (images/)

包含应用程序使用的图片文件。

推荐图片：
- splash_screen.png - 启动画面
- background.png - 背景图片
- logo.png - 项目标志

## 字体文件 (fonts/)

包含自定义字体文件。

## 主题配置 (themes/)

包含主题配置文件，定义不同主题的颜色方案和样式设置。

## 使用方法

在代码中使用资源文件的示例：

```python
import os
from PyQt6.QtGui import QIcon, QPixmap

# 获取资源路径
def get_resource_path(filename):
    return os.path.join(os.path.dirname(__file__), '..', 'resources', filename)

# 加载图标
icon = QIcon(get_resource_path('icons/camera.svg'))

# 加载图片
pixmap = QPixmap(get_resource_path('images/logo.png'))

# 加载样式表
with open(get_resource_path('styles/main.qss'), 'r', encoding='utf-8') as f:
    stylesheet = f.read()
    app.setStyleSheet(stylesheet)
```

## 资源管理建议

1. 使用 SVG 格式的矢量图标以支持高DPI显示
2. 图标尺寸建议使用 16x16, 24x24, 32x32, 48x48 等标准尺寸
3. 样式表使用相对单位 (em, %) 以适应不同分辨率
4. 图片文件压缩以减小应用程序体积
5. 使用一致的命名约定便于管理

## 版权信息

请确保所有资源文件符合相应的版权要求，建议使用开源或自制资源。

## 模块说明：保存图片模块 (SaveImageModule)

保存图片模块用于接收上游图像并按配置或动态输入路径写入磁盘。支持按帧序号自动命名、图像格式选择、缩放、间隔/变更触发及仅运行一次模式。

### 输入端口
- `image` (frame, required): 上游提供的 `numpy.ndarray` 图像 (BGR 格式)。
- `path` (meta, optional): 动态保存路径。当为目录时覆盖 `output_dir`；当包含文件扩展名 (`.png/.jpg/.jpeg`) 时视为完整文件名直接保存。

### 输出端口
- `path`: 实际保存的文件路径。
- `index`: 保存序号（从0开始）。
- `timestamp`: 保存时间戳 (Unix 秒)。
- `status`: 状态字符串：`saved` / `exists` / `no-image` / `skipped` / `mkdir-fail:...` / `write-fail` / `error:...`。

### 主要配置字段
| 字段 | 说明 |
|------|------|
| `output_dir` | 默认输出目录（动态 `path` 为目录时被覆盖）。 |
| `filename_pattern` | 文件名格式，支持 `{index:05d}`。仅在未提供完整文件名时使用。 |
| `create_dir` | 目录不存在是否自动创建。 |
| `overwrite` | 已存在文件是否覆盖。 |
| `image_format` | 保存格式 `PNG` 或 `JPG`。 |
| `quality` | JPG 质量 (1-100)。 |
| `update_mode` | 触发模式：`every` 每次都保存；`on_change` 图像对象变更时保存；`interval` 间隔(ms)；`once` 仅首次保存一次。 |
| `interval_ms` | 与 `interval` 搭配的最小间隔毫秒。 |
| `downscale_max` | 大于0时若宽或高超过该值，按比例缩小。 |

### once 模式说明
将 `update_mode` 设置为 `once` 后，模块只会保存第一次收到的有效图像，后续全部返回 `skipped`。适用于仅需快照的场景。

### 动态路径用法示例

1. 动态目录：上游模块输出 `/custom/session_001` 连接到 `path` 输入，则保存目录改为该值，文件名仍使用 `filename_pattern`。
2. 完整路径：上游输出 `C:/data/snap.png` 连接到 `path` 输入，则直接写入该文件（忽略 `filename_pattern`）。

### 示例
```python
# 假设 executor 已经构建
save_mod = executor.get_module_by_id('保存图片模块')
save_mod.configure({
    'output_dir': 'outputs/images',
    'filename_pattern': 'frame_{index:05d}.png',
    'image_format': 'PNG',
    'update_mode': 'interval',
    'interval_ms': 500,
    'downscale_max': 1280,
})
```

### 常见状态
- `saved`: 保存成功
- `exists`: 文件已存在且未覆盖
- `skipped`: 未满足触发条件（如 interval 未到、once 已执行）
- `no-image`: 输入为空或类型不符
- `write-fail`: OpenCV 返回失败
- `mkdir-fail:...` / `error:...`: 文件系统或写入异常

## 模块说明：打印显示模块 (PrintDisplayModule)

打印显示模块用于在画布内实时展示上游任意数据的格式化文本。支持行缓冲、时间戳、字典合并与截断。

### 输入端口
- `data` (meta): 任意可序列化/可打印对象。

### 输出端口
- `text`: 最新行文本
- `changes`: 更新次数

### 主要配置字段
| 字段 | 说明 |
|------|------|
| `max_lines` | 保留的行数上限。 |
| `truncate` | 单行最大长度，超出截断追加 `...`。 |
| `prefix` | 每行前缀字符串。 |
| `update_mode` | `every` / `on_change` / `interval` 三种。 |
| `interval_ms` | 间隔模式的最小毫秒。 |
| `merge_dict` | dict 自动拼接为 `k=v` 形式。 |
| `show_timestamp` | 前缀显示 `[HH:MM:SS]` 时间戳。 |

### 示例
```python
print_mod = executor.get_module_by_id('打印显示')
print_mod.configure({'max_lines': 15, 'update_mode': 'on_change'})
```

### 画布显示
模块自动扩展高度以适应多行文本，空内容显示为 `(无内容)`。

## 模块说明：路径选择器 (PathSelectorModule)

用于在流程中提供可配置的路径输出，双击模块弹出系统选择对话框。

### 输出端口
- `path`: 当前选择的目录或文件路径。

### 配置字段
| 字段 | 说明 |
|------|------|
| `selection_mode` | `directory` 或 `file`，控制弹窗类型。 |
| `dialog_title` | 对话框标题。 |
| `default_path` | 初始目录或文件路径。 |
| `remember_last` | 选中后是否写回 `default_path` 以便下次起始位置。 |

### 使用
1. 在右键菜单添加“路径选择器”模块。
2. 双击模块 → 选择目录或文件 → 输出端口 `path` 即可被其它模块消费（例如保存图片的动态路径输入）。

## 快捷键汇总
- F5 运行连续流程
- F6 暂停
- F7 恢复
- F8 停止
- F9 运行一次（单轮执行，不启动后台线程）
- Ctrl+S 保存（首次需使用另存为后建立当前路径）
