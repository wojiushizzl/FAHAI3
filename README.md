# FAHAI 图形化流程设计器

一个基于 PyQt6 的可视化流程编排与执行原型，支持模块动态端口反射、拖拽连线、执行器桥接、运行控制（运行/暂停/恢复/停止）、数据注入以及流程的保存与加载。

## 核心概念

### BaseModule
所有模块继承自 `app/pipeline/base_module.py` 中的 `BaseModule`：
- 标准生命周期：`start / stop / pause / resume / reset`
- IO 接口：`register_input_port` / `register_output_port`、`receive_inputs`、`produce_outputs`、`run_cycle`
- 扩展点：`_define_ports()` 定义端口；`process(inputs)` 完成一次业务处理；`_on_configure(config)` 自定义配置应用。
- `config`：可选 pydantic 校验。若模块定义 `ConfigModel`（继承自 `pydantic.BaseModel`）则 `configure()` 会执行严格验证后写入。
- 能力系统：模块可覆盖 `CAPABILITIES = ModuleCapabilities(...)` 用于调度与 UI 展示。

### 端口定义格式
```python
self.register_input_port("text", port_type="string", desc="输入文本", required=True)
self.register_output_port("delayed_text", port_type="string", desc="延时后的文本")
```
字段说明：
- name: 端口名称（字符串，唯一）
- port_type: 逻辑类型标记（string / image / generic / ...）
- desc: 端口描述
- required (仅输入): 是否必需输入

### 模块状态 & 配置
`get_status()` 默认返回：
```json
{
  "module_id": "uuid",
  "name": "模块名称",
  "type": "custom|camera|...",
  "status": "idle|running|paused|error|stopped",
  "config": {"...": "..."},
  "errors": [],
  "input_ports": {"port_name": {"type": "string", "desc": ""}},
  "output_ports": {"port_name": {"type": "string", "desc": ""}},
  "current_inputs": ["..."],
  "current_outputs": ["..."],
  "capabilities": {
    "supports_async": false,
    "supports_batch": false,
    "may_block": false,
    "resource_tags": [],
    "throughput_hint": 0.0
  }
}
```
自定义模块可覆盖 `get_status()` 添加专属字段（例如延时模块的 `delay_seconds`）。

### GUI 组成
- `EnhancedFlowCanvas`: 模块放置与端口连线；拖拽输出点到输入点生成连接。提供 `export_structure()`、`build_executor(executor)`、`save_to_file(path)`、`load_from_file(path)`。
- `DockPanel`: 左侧工具箱与属性编辑。已为“文本输入”“打印”模块提供特化面板，可实时更新文本或查看最后打印。
- `MainWindow`: 整体窗口，集成运行控制工具栏与菜单。执行器生命周期与后台馈送线程在此管理。

### 执行器 PipelineExecutor
路径 `app/pipeline/pipeline_executor.py`：
- 支持执行模式：顺序 (SEQUENTIAL) / 并行 (PARALLEL) / 流水线 (PIPELINE, 当前等同顺序)。
- 节点表示 `PipelineNode`，包含模块引用、前驱/后继、执行时间与最后结果缓存。
- 连接统一使用 `Connection` 数据对象：`source_module/source_port -> target_module/target_port`。
- 路由逻辑：执行结果写入全局上下文并根据显示连接将输出推送到目标模块的输入缓冲。
- 回调：`add_progress_callback`、`add_result_callback`、`add_error_callback`。

## 流程保存格式 (JSON)
`EnhancedFlowCanvas.export_structure()` 输出：
```json
{
  "modules": [
    {
      "module_id": "文本输入_xxx",
      "module_type": "文本输入",
      "x": 320.0,
      "y": 180.0,
      "inputs": [],
      "outputs": ["text"],
      "config": {},
      "state": {"text_value": "Hello"}
    }
  ],
  "connections": [
    {
      "source_module": "文本输入_xxx",
      "source_port": "text",
      "target_module": "打印_yyy",
      "target_port": "text"
    }
  ]
}
```
字段：
- modules[].state: 按已知模块特化抓取（示例：`text_value`, `last_text`）。
- modules[].config: 来自模块的 `config` 字典。
- connections: 显式端口级别连线记录。

## 扩展模块示例：延时模块
新增文件 `app/pipeline/delay_module.py`：
```python
class DelayModule(BaseModule):
    def _define_ports(self):
        self.register_input_port("text", port_type="string", desc="输入文本", required=True)
        self.register_output_port("delayed_text", port_type="string", desc="延时后的文本")
    def process(self, inputs):
        txt = inputs.get("text")
        if txt is None: return {"delayed_text": "(无输入)"}
        time.sleep(self.delay_seconds)
        return {"delayed_text": txt}
    def _on_configure(self, config):
        if "delay_seconds" in config:
            self.delay_seconds = max(0.0, float(config["delay_seconds"]))
```
注册：在 `module_registry.py` 添加：
```python
from .delay_module import DelayModule
register_module("延时", DelayModule)
```
使用：右键画布 -> 添加“延时”模块；与“文本输入”/“打印”组合，形成：文本输入(text) -> 延时(text->delayed_text) -> 打印(text)
(需先在延时模块与打印模块之间建立正确端口映射：目前打印模块期望输入端口名 text，可通过中转时在执行器阶段路由或创建一个简单“重命名”模块。)

## 添加新模块步骤摘要
1. 创建文件继承 `BaseModule`。
2. 在 `_define_ports()` 中注册输入/输出端口。
3. 实现 `process()` 返回 dict。
4. 可选：实现 `_on_configure()` 解析自定义配置。
5. 更新 `module_registry.py` 调用 `register_module("显示名", ModuleClass)`。
6. 运行应用，右键画布添加模块；属性面板可根据需要扩展显示。

## 常见配置字段建议
| 字段名 | 用途 | 类型 | 说明 |
|--------|------|------|------|
| delay_seconds | 延时模块延迟 | float | >=0，秒 |
| text | 文本输入初始值 | string | 配置或 UI 编辑覆盖 |
| confidence_threshold | 模型置信度阈值 | float | [0,1] 范围 |
| fps | 相机帧率 | int | 采集速率 |
| exposure_ms | 相机曝光时间 | float | 毫秒 |

## 运行控制
工具栏与菜单提供：
- 运行(F5)：构建执行器并开始循环。
- 暂停(F6)：暂停执行线程（保留队列）。
- 恢复(F7)：继续执行。
- 停止(F8)：终止执行器与馈送线程。
- 注入数据：弹窗输入 key/value 发送到 `input_queue`。
- 编辑模块：当前“文本输入”模块快速修改文本。

## 测试
示例测试文件：`tests/test_build_executor.py` 与 `tests/test_build_executor_unittest.py` 包含：
- 模块与连接数量验证
- ID 唯一性验证
- 序列化保存/加载回环一致性

（若当前测试运行工具未识别，可改用手动脚本或集成 pytest 调度。）

## 能力系统 (ModuleCapabilities)
字段说明：
- supports_async: 模块内部是否用线程/协程异步工作（例如相机采集）。
- supports_batch: 是否可接收批量输入（模型推理、后处理等）。
- may_block: 是否可能出现阻塞（网络 / IO / CPU 密集）。
- resource_tags: 标签用于分组或调度筛选（camera / model / logic / ...）。
- throughput_hint: 粗略吞吐提示（每秒处理帧/次数），用于 UI 和调度策略参考。

模块覆盖示例：
```python
class CameraModule(BaseModule):
  CAPABILITIES = ModuleCapabilities(supports_async=True, may_block=True, resource_tags=["camera"], throughput_hint=30.0)
```

## 配置模型 (ConfigModel)
在模块类内定义：
```python
class LogicModule(BaseModule):
  class ConfigModel(BaseModel):
    op: str = "AND"
    inputs_count: int = 2
```
调用：`logic.configure({"op": "OR", "inputs_count": 3})` —— 自动校验失败会返回 False 并记录错误。

## 自动生成配置面板
GUI 属性面板会优先尝试读取模块的 `ConfigModel.__fields__`，为每个字段生成相应控件（int -> QSpinBox, float -> QDoubleSpinBox, bool -> QCheckBox, str -> QLineEdit，复杂结构 -> QTextEdit）。点击“应用”后调用 `module.configure()` 完成校验与更新。

## 外部插件
通过 Python entry points 发现并注册模块：
在外部包的 `pyproject.toml` 或 `setup.cfg` 中声明：
```toml
[project.entry-points."fahai.modules"]
自定义模块显示名 = "your_package.module:YourModuleClass"
```
启动时 `module_registry.load_plugin_modules()` 会加载并调用 `register_module(display_name, klass)`。

## 后续可扩展方向
- 并行/流水线真实实现（管道队列分层执行）
- 连接有效性校验（类型匹配）
- 执行监控面板（吞吐/延迟折线图）
- 自定义模块热加载 (watch + importlib.reload)
- 端口类型注册 & 可视化颜色编码
- 更丰富的表单控件（枚举下拉、列表编辑、嵌套结构 JSON 编辑器）

---
欢迎继续提出需要的特性或改进方向。

## 最近更新 (Changelog)

### 2025-10-26
1. 分组功能初版：支持多选模块创建分组框；分组可拖动整体移动成员，支持重命名、删除。保存/加载流程时分组会被持久化 (`groups` 字段)。
2. 分组高亮：选中时分组边框加粗并采用高亮颜色，便于在复杂布局中定位。
3. 画布动态扩展：缩放或向外拖拽时自动扩展 `sceneRect`，解决“缩放后无法进一步拖到边缘”问题。
4. 平移体验优化：在缩放导致无滚动条时使用矩阵平移，不再被视口限制。
5. OK/NOK 展示模块：新增 `font_size` 配置，实时改变画布中状态文本的字号（8~72）。
6. 热加载优化：启动后延迟增量加载最近项目（批次加载模块并显示进度），降低初始卡顿。
7. 流程结构新增 `groups`：格式为 `{group_id, title, x, y, width, height, members}`，兼容旧版本（无该字段时忽略）。
8. YOLOv8 模型模块（检测/分类/分割）已集成，输出带注释图像与结构化结果，可与图片展示/保存模块串联。
9. YOLOv8 过滤增强：支持 `target_classes` (名称或数字索引混合) 与 `enable_target_filter` 开关，只输出/标注指定目标；提供 `export_raw` 控制是否输出原始图端口；检测与分割模块新增 `annotate_filtered_only` 开关仅绘制过滤后目标（减少视觉噪声）。

### 2025-10-20
1. 模块可调整大小（右下角拖拽或边缘）。
2. 图片展示模块缩略图自适应模块尺寸，双击切换预设 (160x120 / 320x240)。
3. 自动记忆并恢复模块宽高（保存文件内）。
4. 运行一次 (F9) 支持单步管线快速调试。
5. 路径选择器模块：双击弹出系统对话框写入路径。 
6. 保存节流与自动记录最近项目 `last_project.json`。

## 分组结构示例
```json
{
  "modules": [ ... ],
  "connections": [ ... ],
  "groups": [
    {
      "group_id": "group_1",
      "title": "前处理阶段",
      "x": 120.0,
      "y": 80.0,
      "width": 480.0,
      "height": 280.0,
      "members": ["图片导入_abc", "YOLO检测_def", "OK/NOK展示_xyz"]
    }
  ]
}
```

## OK/NOK 展示模块配置示例
```python
{
  "font_size": 24,
  "true_text": "OK",
  "false_text": "NOK"
}
```

## 热加载机制
启动时不直接阻塞式加载项目：
1. `showEvent` 中设置 `QTimer.singleShot` 延迟触发。
2. 使用 `load_from_file_incremental(path, batch_size=8, progress_cb, finished_cb)` 分批加入模块，主线程保持响应。
3. 进度在状态栏显示：`热加载进度: 已加载/总模块`。

## 已知后续改进方向
- 分组内快速“添加模块”按钮。
- 分组折叠/展开与缩略概览。
- YOLOv8 模型设备选择（显式 GPU/CPU 下拉）。
- 增量保存（仅变更数据写入）。
- 流程差异比较工具（JSON diff）。
- YOLOv8 模块更多可视化选项（调色板、按类别隐藏标签等）。

## YOLOv8 模块过滤与标注说明

### 过滤字段
| 字段 | 类型 | 说明 |
|------|------|------|
| enable_target_filter | bool | 启用后根据 `target_classes` 仅保留匹配结果 |
| target_classes | list[str] | 逗号分隔输入（UI），支持类别名称或数字索引混合，如 `person,0,car` |
| export_raw | bool | 是否输出原始图像到 `image_raw` 端口 |
| annotate_filtered_only | bool | (检测/分割) 标注图只绘制过滤后的结果子集 |

数字索引与名称匹配逻辑：
1. 预测前：若启用过滤，会将名称映射为内部 indices 传入 YOLO 以减少不必要目标。
2. 预测后：再次根据名称/索引集合进行安全过滤，确保结果稳定。

### 使用示例
```
enable_target_filter = true
target_classes = person,car,2
annotate_filtered_only = true
export_raw = true
confidence = 0.35
```
含义：预测只输出 person / car / 类别索引 2 的目标；标注图仅显示这些目标；仍同时提供原始图像端口用于对比与后续处理。

### 分割模块特殊说明
在 `annotate_filtered_only` 为 true 时，分割模块会同时裁剪 boxes 与 masks 子集再调用内部绘制函数，避免显示未保留的实例。若过滤结果为空则返回原图（不绘制任何标注）。

### 性能提示
预过滤（names -> indices）可降低后处理对象数量；标注仅绘制过滤子集减少绘制开销（特别是大量实例场景）。

## 保存文本模块 (保存文本)

`保存文本` 模块用于将流中的字符串写入文件，支持追加/覆盖与自动时间戳。

配置字段：
| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| file_path | str | outputs/text_log.txt | 目标文件路径（相对或绝对） |
| append | bool | True | True 追加写入；False 覆盖写入 |
| add_timestamp | bool | True | 每行前加 `[YYYY-MM-DD HH:MM:SS]` 时间戳 |
| encoding | str | utf-8 | 文件写入编码 |
| ensure_parent | bool | True | 不存在父目录时自动创建 |
| empty_placeholder | str | (empty) | 输入为空字符串时的替代内容 |

输出端口：
| 端口 | 类型 | 内容 |
|------|------|------|
| status | meta | `ok:<count>` 或 `error:<reason>` |
| saved_path | meta | 实际写入文件路径（失败时为 None） |

示例：
```
file_path = logs/run1.txt
append = true
add_timestamp = true
encoding = utf-8
```
串联方式：`模型/逻辑模块 -> 保存文本`，将上游的文本结果（例如检测统计、分类标签）持久化，便于后续分析。


若需更多示例或希望将上述功能拆分文档，请提出需求。

## 开发者：创建自定义模块示例 (SampleDevModule)

新增示例文件 `app/pipeline/custom/sample_dev_module.py`，演示最简可配置的自定义模块开发流程。该模块显示名为“示例模块”，在工具箱/右键菜单中出现，便于复制扩展。

示例结构：
```python
class SampleDevModule(BaseModule):
  CAPABILITIES = ModuleCapabilities(resource_tags=["cpu"], throughput_hint=200.0)
  def _define_ports(self):
    self.register_input_port("value", port_type="number", desc="输入数值", required=True)
    self.register_input_port("flag", port_type="bool", desc="开关标志")
    self.register_output_port("result", port_type="number", desc="计算结果")
    self.register_output_port("echo", port_type="any", desc="回显原始输入")
  def process(self, inputs):
    base = float(inputs.get("value", 0)) if isinstance(inputs.get("value"),(int,float,str)) else 0.0
    flag = inputs.get("flag", True)
    multiplier = self.config.get("multiplier", 1.0)
    enabled = self.config.get("enabled", True)
    if not enabled: return {"result": 0, "echo": inputs}
    return {"result": (base * multiplier) if flag else base, "echo": inputs}
```

配置模型 (Pydantic)：
```python
class SampleConfig(BaseModel):
  multiplier: float = Field(1.0, description="乘法因子")
  enabled: bool = Field(True, description="是否启用")
  note: str | None = Field(None, description="备注")
```
模块 `configure({...})` 会自动校验并写入 `self.config`。GUI 属性面板会根据字段类型生成合适的编辑控件。

### 创建你自己的模块步骤 (快速参考)
1. 在 `app/pipeline/custom/` 下新建 `<your_module>_module.py`，继承 `BaseModule`。
2. 在 `_define_ports()` 中注册输入/输出端口（避免仅使用默认 in/out，利于语义清晰）。
3. 可选：定义 `ConfigModel`；在 `_initialize()` 中实例化或在首次 `configure()` 时构建。
4. 在 `process(inputs)` 中读取 `inputs` 并返回 dict 输出（未返回 dict 时框架会包装为 `{"out": value}`）。
5. 在文件尾部调用 `register_module("显示名", YourModuleClass)` 或在 `module_registry.py` 中添加集中注册块。
6. 重启应用或触发热加载（未来将支持开发时热重载）。

### 命名与显示名建议
- 文件名使用功能短语 + `_module.py`（如 `resize_module.py`）。
- 显示名（register_module 第一个参数）可使用中文，需保持唯一。
- 端口名尽量短小：`image`, `mask`, `count`, `flag`，避免包含空格。

### 端口类型与调度
`port_type` 当前主要用于 UI 标记与未来类型匹配校验，可自定义：`number`, `image`, `string`, `bool`, `any`。保持简单的一致性有助于后续做自动连线建议。

### 错误与调试
- 在 `process` 中捕获异常并追加到 `self.errors` (可在属性面板展示)。
- 使用 `self.logger.info()/warning()/error()` 输出到统一日志；可在后续添加日志视图 Dock。
- 返回结果时若结构不符合期望，下游模块不会收到对应端口数据，可在执行器调试时打印上下文。

### 高级扩展 (可选)
- 支持批量：定义端口类型 `list[image]` 并在 `process` 中迭代。
- 异步采集：在模块内启动线程写入 `self.outputs` 并在 `run_cycle` 返回已有缓存。
- 资源标记：`CAPABILITIES = ModuleCapabilities(resource_tags=["gpu"], may_block=True)` 为后续调度优化做准备。

### 发布为外部插件
在你的包 `pyproject.toml` 中添加：
```toml
[project.entry-points."fahai.modules"]
示例扩展模块 = "your_pkg.sample_module:SampleModule"
```
安装后启动应用即自动加载。

---
如需更详细的教程（端口类型规范、属性面板控件映射、热重载机制）请提出需求。示例模块是后续文档的基础模板，建议先复制再替换端口与处理逻辑。

## 目录结构更新（模块分类）

已将原先平铺在 `app/pipeline/` 下的模块按功能分类迁移：

```
app/pipeline/
  base_module.py
  module_registry.py
  pipeline_executor.py
  camera/            # 相机相关模块
    camera_module.py
    image_import_module.py   # 图片导入/播放模块 (离线帧来源)
  model/             # 模型推理模块
    model_module.py
  trigger/           # 触发控制模块
    trigger_module.py
  postprocess/       # 推理结果后处理模块
    postprocess_module.py
  custom/            # 通用/演示/辅助模块集合
    text_input_module.py
    print_module.py
    delay_module.py
    logic_module.py
    image_display_module.py   # 图片展示模块 (画布缩略图显示)
```

兼容占位文件现已移除（`camera_module.py`、`model_module.py` 等已删除），请统一使用分类路径导入：

```
from app.pipeline.camera.camera_module import CameraModule
from app.pipeline.model.model_module import ModelModule
from app.pipeline.trigger.trigger_module import TriggerModule
from app.pipeline.postprocess.postprocess_module import PostprocessModule
from app.pipeline.custom.logic_module import LogicModule
```

说明：流程保存格式仅使用显示名，不受这一结构调整影响。若您有旧脚本，请更新导入路径；否则将出现 `ModuleNotFoundError`。

迁移的好处：
- 更清晰的分层（采集 / 推理 / 触发 / 后处理 / 自定义）。
- 便于后续扩展同类别多实现（例如多个 CameraModule 子类）。
- 减少主目录文件拥挤，提高可维护性。

如果你需要添加新的模块类别，只需：
1. 创建新子目录与 `__init__.py`。  
2. 放置模块实现。  
3. 在 `module_registry.py` 中按分组方式尝试导入并注册显示名。  
4. （可选）定义 `ConfigModel` 与 `CAPABILITIES` 改善校验与调度。  
5. （可选）发布为插件：添加 entry point 到 `fahai.modules`。  


### 新增：图片导入模块 (ImageImportModule)

用于将磁盘图片作为“相机帧”顺序或循环发送，使用场景：
- 离线复现生产样品批次
- 无真实相机场景下调试模型/后处理
- 对比不同预处理参数影响

主要配置字段：
| 字段 | 说明 | 示例 |
|------|------|------|
| source_type | file/directory/pattern/list | directory |
| path | 单文件或目录路径 | D:/images |
| pattern | 匹配模式 | *.png |
| recursive | 目录/模式递归 | True |
| loop | 播放结束后循环 | True |
| interval_ms | 两帧最小间隔(ms) | 33 |
| resize | 可选缩放 [w,h] | [640,480] |
| color_format | BGR/RGB/GRAY | RGB |
| max_files | 最大文件数 (0=不限) | 0 |
| file_list | source_type=list 时使用 | ["a.jpg","b.jpg"] |

输出端口：`image` (numpy)、`path`、`index`、`timestamp`。

提示：`interval_ms` > 0 时若未到间隔返回空 `{}`；读取失败返回 `{"error": "读取失败: xxx"}`。与模型模块串联可实现离线批量推理评估。

### 新增：图片展示模块 (ImageDisplayModule)

用途：在流程画布中直接显示输入图像的缩略图，支持双击在 160x120 与 320x240 之间切换，方便快速观察流经的帧内容。

配置字段：
| 字段 | 说明 | 示例 |
|------|------|------|
| width | 缩略宽度 | 160 |
| height | 缩略高度 | 120 |
| maintain_aspect | 保持原图比例（当前占位，后续扩展） | True |
| downscale_only | 只缩小不放大（当前占位） | True |
| update_mode | 刷新模式 on_change/interval | on_change |
| interval_ms | 间隔模式下最小刷新间隔(ms) | 100 |
| channel_format | 输入颜色假定 BGR/RGB/GRAY | BGR |
| autoskip_error | 非图像输入静默跳过 | True |

端口：
| 输入端口 | 类型 | 说明 |
|----------|------|------|
| image | frame | 上游图像帧 |

| 输出端口 | 类型 | 说明 |
|----------|------|------|
| image | frame | 原样输出图像（可继续传下游） |
| meta | meta | 显示元信息（shape/changes/timestamp） |

使用：右键菜单暂未列出，可通过工具箱添加显示名“图片展示”。与“图片导入”或“相机”模块连接其 image -> image 端口即可。执行后画布中模块会显示缩略图。

注意：当前缩略图刷新是通过结果回调/模块输出刷新机制调用 `refresh_visual()`（如果未自动刷新，可在后续加入集中更新定时器）。

### 交互增强：模块可调整大小 & 路径字段浏览

近期新增：
1. 画布中模块支持拖拽右/下边缘或右下角斜对角进行缩放（最小尺寸 100x60）。图片展示模块缩放后缩略图区域自动适配。双击图片展示模块仍可快速切换预设尺寸。
2. 自动生成配置面板中凡是字段名以 `path` 或 `_path` 结尾的字符串都提供“浏览...”按钮，可直接选择文件或目录，减少手动输入路径错误。

后续可扩展：
- 记忆单模块上次尺寸
- 路径字段区分文件/目录（通过额外 schema 标记）
- 自适应端口标签布局防止拥挤或换行显示

