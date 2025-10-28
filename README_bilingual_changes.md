# Bilingual UI Enhancements (中英双语改进)

本次更新引入了完整的中文 / 英文 / 双语模式支持，覆盖模块工具箱、属性面板以及流程画布中模块标题。

## 覆盖范围 / Coverage
- 模块工具箱 (Module Toolbox) 标题与搜索占位符动态切换。
- 属性面板 (Property Panel) 全部分组标题、表单标签、按钮文本、占位符双语化。
- 模块标题 (Module Titles) 使用语言模式自动转换；语言切换时即时刷新。
- 模块注册表新增辅助函数 `list_registered_modules_display()` 可在非 GUI 输出场景按语言显示。

## 技术要点 / Technical Notes
- 统一采用 `app.utils.i18n` 中的 `L()`, `translate()`, `bilingual()`。
- 新增 `ModuleItem.refresh_title_language()` 用于语言切换时保持标题居中和同步翻译。
- 主窗口语言菜单切换后：重建菜单、工具栏、刷新工具箱、刷新所有已存在模块标题、刷新属性面板标题。
- `dock_panel.py` 已重写为干净实现，修复之前缩进破坏问题。

## 语言切换行为 / Language Switch Behavior
切换语言 (中文 zh / 英文 en / 中英 both) 后：
1. 菜单与工具栏全部重新构建。
2. 模块工具箱调用 `refresh_modules()` 重建分类与标题。
3. 画布中所有 `ModuleItem` 调用 `refresh_title_language()`。
4. 若属性面板已选中某模块，重新显示其属性时会使用当前语言。

## 模块注册表辅助 / Registry Helper
`list_registered_modules_display()` 根据当前语言模式返回适合展示的模块名称，便于未来命令行或日志输出。

## 后续建议 / Next Steps
- 扩展 i18n 字典，对运行日志与状态消息也提供双语。
- 为用户配置文件增加记忆最近使用的语言模式（已通过 settings.json 实现）。
- 将属性面板自动表单生成的字段名映射为可翻译的友好标签（未来可添加 schema 元信息）。

## 回退机制 / Fallback
若某标签未提供英文，`translate()` 将返回原始中文；双语模式下 `bilingual()` 自动拼接。

---
Updated: 2025-10-28
