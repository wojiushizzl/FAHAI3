#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
停靠面板模块
包含模块工具箱和属性配置面板
"""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox,
                             QCheckBox, QPushButton, QGroupBox, QScrollArea,
                             QTabWidget, QFormLayout, QTextEdit, QFileDialog)
from PyQt6.QtCore import Qt, pyqtSignal
import os
from typing import List  # 用于 List 类型检测

from .module_widgets import ModuleToolbox


class PropertyPanel(QWidget):
    """属性配置面板"""
    
    # 信号定义
    property_changed = pyqtSignal(str, object)  # 属性变化信号
    
    def __init__(self):
        super().__init__()
        
        self.current_module = None
        self._current_apply_fn = None
        self._init_ui()
        
    def _init_ui(self):
        """初始化用户界面"""
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        # 标题
        self.title_label = QLabel("属性配置")
        self.title_label.setStyleSheet("""
            QLabel {
                font-weight: bold;
                font-size: 14px;
                padding: 10px;
                background-color: #f0f0f0;
                border-bottom: 1px solid #ccc;
            }
        """)
        layout.addWidget(self.title_label)
        
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        layout.addWidget(scroll_area)
        
        # 属性容器
        self.property_container = QWidget()
        self.property_layout = QVBoxLayout()
        self.property_container.setLayout(self.property_layout)
        scroll_area.setWidget(self.property_container)
        
        # 默认显示提示信息
        self._show_default_message()
        
    def _show_default_message(self):
        """显示默认提示信息"""
        self._clear_properties()
        
        message_label = QLabel("请选择一个模块来配置属性")
        message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message_label.setStyleSheet("""
            QLabel {
                color: #666;
                font-size: 12px;
                padding: 20px;
            }
        """)
        self.property_layout.addWidget(message_label)
        
    def _clear_properties(self):
        """清空属性面板"""
        while self.property_layout.count():
            child = self.property_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
                
    def show_module_properties(self, module_item):
        """显示模块属性"""
        self.current_module = module_item
        self._clear_properties()
        
        module_type = module_item.module_type
        self.title_label.setText(f"{module_type}模块属性")
        
        # 优先 schema 自动生成，如果失败则回退到特化逻辑
        if not self._show_schema_properties(module_item):
            if module_type == "文本输入":
                self._show_text_input_properties(module_item)
            elif module_type == "打印":
                self._show_print_properties(module_item)
            elif module_type == "文本展示":
                self._show_text_display_properties(module_item)
            elif module_type == "相机":
                self._show_camera_properties()
            elif module_type == "触发":
                self._show_trigger_properties()
            elif module_type == "模型":
                self._show_model_properties()
            elif module_type == "后处理":
                self._show_postprocess_properties()
            elif module_type == "逻辑":
                self._show_logic_properties(module_item)

    def refresh_model_sizes(self):
        """在外部调用以刷新模型的原始/标注尺寸显示 (例如推理后)."""
        ref = getattr(getattr(self, 'current_module', None), 'module_ref', None)
        if not ref or not hasattr(ref, 'get_status'):
            return
        try:
            st = ref.get_status()
        except Exception:
            return
        raw_shape = st.get('last_raw_shape')
        ann_shape = st.get('last_annotated_shape')
        if hasattr(self, '_model_raw_size_label') and self._model_raw_size_label:
            if raw_shape:
                self._model_raw_size_label.setText(f"原始图尺寸: {raw_shape}")
        if hasattr(self, '_model_annotated_size_label') and self._model_annotated_size_label:
            if ann_shape:
                self._model_annotated_size_label.setText(f"标注结果尺寸: {ann_shape}")

    def _show_schema_properties(self, module_item) -> bool:
        """根据模块的 ConfigModel 自动生成配置表单。返回是否成功生成。"""
        ref = getattr(module_item, 'module_ref', None)
        if ref is None:
            return False
        ConfigModel = getattr(ref.__class__, 'ConfigModel', None)
        if not ConfigModel or not hasattr(ConfigModel, '__fields__'):
            return False
        group = QGroupBox("配置 (自动生成)")
        form = QFormLayout(); group.setLayout(form)
        field_widgets = {}
        current_cfg = ref.config if isinstance(ref.config, dict) else {}
        for fname, field in ConfigModel.__fields__.items():  # type: ignore
            value = current_cfg.get(fname, field.default)
            w = None
            # 安全获取字段基础类型（pydantic v1 有 type_, 若不存在回退 annotation / outer_type_）
            base_type = getattr(field, 'type_', None) or getattr(field, 'annotation', None)
            outer = getattr(field, 'outer_type_', None)
            origin_outer = getattr(outer, '__origin__', None)
            is_list_type = isinstance(value, (list, tuple)) or (origin_outer in (list, List))
            if is_list_type:
                display = ",".join(str(v) for v in value) if value else ""
                w = QLineEdit(display)
                w.setPlaceholderText("逗号分隔列表")
            elif base_type in (int,):
                w = QSpinBox(); w.setRange(-999999, 999999)
                try:
                    w.setValue(int(value) if value is not None else 0)
                except Exception:
                    w.setValue(0)
            elif base_type in (float,):
                w = QDoubleSpinBox(); w.setDecimals(4); w.setRange(-1e9, 1e9)
                try:
                    w.setValue(float(value) if value is not None else 0.0)
                except Exception:
                    w.setValue(0.0)
            elif base_type in (bool,):
                w = QCheckBox(); w.setChecked(bool(value))
            elif base_type in (str,):
                # 路径类型字段：名称以 path 或 _path 结尾 -> 提供文件/目录选择按钮
                if fname.lower().endswith("path") or fname.lower().endswith("_path"):
                    container = QWidget(); hl = QHBoxLayout(); hl.setContentsMargins(0,0,0,0); container.setLayout(hl)
                    le = QLineEdit(str(value) if value is not None else "")
                    browse_btn = QPushButton("浏览...")
                    def do_browse():
                        # 简单策略：如果当前值是目录或为空 -> 选目录；否则选文件
                        current_text = le.text().strip()
                        if current_text and (QFileDialog.getExistingDirectory.__name__):
                            # 判断是否目录
                            import os
                            if os.path.isdir(current_text):
                                chosen = QFileDialog.getExistingDirectory(container, "选择目录", current_text)
                                if chosen:
                                    le.setText(chosen)
                                    return
                        # 文件选择
                        chosen_file, _ = QFileDialog.getOpenFileName(container, "选择文件", current_text or "", "所有文件 (*.*)")
                        if chosen_file:
                            le.setText(chosen_file)
                    browse_btn.clicked.connect(do_browse)
                    hl.addWidget(le)
                    hl.addWidget(browse_btn)
                    w = container
                    # 记录实际输入组件供应用阶段读取
                    field_widgets[fname] = le
                else:
                    w = QLineEdit(str(value) if value is not None else "")
            else:
                # 复杂类型：使用文本编辑器，可手动调整（未来可扩展 JSON 解析）
                w = QTextEdit(); w.setReadOnly(False); w.setPlainText(str(value))
            if fname not in field_widgets:  # 普通字段
                field_widgets[fname] = w
            form.addRow(fname, w)
        apply_btn = QPushButton("应用")
        form.addRow("", apply_btn)
        def apply():
            new_cfg = {}
            for fname, w in field_widgets.items():
                if isinstance(w, QSpinBox):
                    new_cfg[fname] = w.value()
                elif isinstance(w, QDoubleSpinBox):
                    new_cfg[fname] = w.value()
                elif isinstance(w, QCheckBox):
                    new_cfg[fname] = w.isChecked()
                elif isinstance(w, QLineEdit):
                    # 判断是否列表字段：如果原值是列表或 schema 是 List 则解析
                    orig_field = ConfigModel.__fields__[fname]
                    orig_value = current_cfg.get(fname, orig_field.default)
                    outer = getattr(orig_field, 'outer_type_', None)
                    origin_outer = getattr(outer, '__origin__', None)
                    is_list_type = isinstance(orig_value, (list, tuple)) or (origin_outer in (list, List))
                    txt = w.text().strip()
                    if is_list_type:
                        if txt == "":
                            new_cfg[fname] = []
                        else:
                            parts = [p.strip() for p in txt.split(',') if p.strip()]
                            # 根据内部类型尝试数字转换
                            inner_t = getattr(orig_field, 'type_', None) or getattr(orig_field, 'annotation', str)
                            converted = []
                            for p in parts:
                                if inner_t in (int, float):
                                    try:
                                        converted.append(inner_t(p))
                                    except Exception:
                                        # 保留原字符串以免丢失信息
                                        converted.append(p)
                                else:
                                    converted.append(p)
                            new_cfg[fname] = converted
                    else:
                        new_cfg[fname] = txt
                elif isinstance(w, QTextEdit):
                    # 尝试解析为 JSON / Python literal，将来可扩展
                    txt = w.toPlainText().strip()
                    new_cfg[fname] = txt
            ref.configure(new_cfg)
        apply_btn.clicked.connect(apply)
        self.property_layout.addWidget(group)
        self._current_apply_fn = apply
        return True

    def _show_text_input_properties(self, module_item):
        basic_group = QGroupBox("文本输入配置")
        form = QFormLayout(); basic_group.setLayout(form)
        ref = module_item.module_ref
        current = ref.text_value if ref and hasattr(ref, 'text_value') else ""
        text_edit = QLineEdit(current)
        form.addRow("当前文本:", text_edit)
        apply_btn = QPushButton("应用")
        form.addRow("", apply_btn)
        def apply():
            if ref and hasattr(ref, 'set_text'):
                ref.set_text(text_edit.text())
        apply_btn.clicked.connect(apply)
        self._current_apply_fn = apply
        self.property_layout.addWidget(basic_group)

    def _show_print_properties(self, module_item):
        basic_group = QGroupBox("打印显示 / 文本查看")
        layout = QVBoxLayout(); basic_group.setLayout(layout)
        ref = module_item.module_ref
        # 文本区域（可编辑）
        from PyQt6.QtWidgets import QPlainTextEdit, QHBoxLayout, QFileDialog
        text_area = QPlainTextEdit()
        text_area.setPlaceholderText("(无内容)")
        text_area.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        text_area.setStyleSheet("QPlainTextEdit {background:#fafafa;font-family:Consolas;font-size:11px;border:1px solid #bbb;}")
        lines = []
        if ref and hasattr(ref, 'display_text'):
            try:
                lines = ref.display_text.splitlines()
            except Exception:
                lines = []
        text_area.setPlainText("\n".join(lines) if lines else "")
        layout.addWidget(text_area)
        # 操作按钮行
        btn_row = QHBoxLayout()
        copy_btn = QPushButton("复制全部")
        clear_btn = QPushButton("清空")
        export_btn = QPushButton("导出...")
        apply_btn = QPushButton("应用到模块")
        refresh_btn = QPushButton("刷新")
        btn_row.addWidget(copy_btn)
        btn_row.addWidget(clear_btn)
        btn_row.addWidget(export_btn)
        btn_row.addWidget(apply_btn)
        btn_row.addWidget(refresh_btn)
        layout.addLayout(btn_row)
        def do_copy():
            text_area.selectAll(); text_area.copy(); text_area.moveCursor(text_area.textCursor().End)
        def do_clear():
            text_area.clear()
        def do_export():
            path, _ = QFileDialog.getSaveFileName(self, "导出文本", os.path.join(os.getcwd(), "print_display.txt"), "Text Files (*.txt);;All Files (*.*)")
            if path:
                try:
                    with open(path, 'w', encoding='utf-8') as f:
                        f.write(text_area.toPlainText())
                except Exception as e:
                    print(f"[PrintDisplay] 导出失败: {e}")
        def do_apply():
            if ref and hasattr(ref, '_lines'):
                raw = text_area.toPlainText().splitlines()
                max_lines = int(getattr(ref, 'config', {}).get('max_lines', 10)) if hasattr(ref, 'config') else 10
                ref._lines = raw[-max_lines:]
                ref._last_text = ref._lines[-1] if ref._lines else None
        def do_refresh():
            if ref and hasattr(ref, 'display_text'):
                text_area.setPlainText(getattr(ref, 'display_text', ''))
        copy_btn.clicked.connect(do_copy)
        clear_btn.clicked.connect(do_clear)
        export_btn.clicked.connect(do_export)
        apply_btn.clicked.connect(do_apply)
        refresh_btn.clicked.connect(do_refresh)
        self._current_apply_fn = do_apply
        self.property_layout.addWidget(basic_group)
        """外部快捷键触发当前属性的应用（仅对有 apply 函数的模块类型）"""
        if self._current_apply_fn:
            self._current_apply_fn()

    def _show_text_display_properties(self, module_item):
        """文本展示模块属性编辑: 字体大小/文字颜色/背景颜色/展示文本内容"""
        ref = module_item.module_ref
        basic_group = QGroupBox("文本展示配置")
        form = QFormLayout(); basic_group.setLayout(form)
        from PyQt6.QtWidgets import QLineEdit, QSpinBox, QColorDialog, QPushButton, QHBoxLayout, QFileDialog
        # 字体大小
        fs_spin = QSpinBox(); fs_spin.setRange(6,72); fs_spin.setValue(int(getattr(ref, 'config', {}).get('font_size', 12)))
        form.addRow("字体大小", fs_spin)
        # 文字颜色
        tc_line = QLineEdit(getattr(ref, 'config', {}).get('text_color', '#222222'))
        pick_tc_btn = QPushButton("选色")
        def pick_tc():
            col = QColorDialog.getColor()
            if col.isValid(): tc_line.setText(col.name())
        hl_tc = QHBoxLayout(); hl_tc.addWidget(tc_line); hl_tc.addWidget(pick_tc_btn)
        w_tc = QWidget(); w_tc.setLayout(hl_tc)
        form.addRow("文字颜色", w_tc)
        pick_tc_btn.clicked.connect(pick_tc)
        # 背景颜色
        bg_line = QLineEdit(getattr(ref, 'config', {}).get('background_color', '#ffffff'))
        pick_bg_btn = QPushButton("选色")
        def pick_bg():
            col = QColorDialog.getColor()
            if col.isValid(): bg_line.setText(col.name())
        hl_bg = QHBoxLayout(); hl_bg.addWidget(bg_line); hl_bg.addWidget(pick_bg_btn)
        w_bg = QWidget(); w_bg.setLayout(hl_bg)
        form.addRow("背景颜色", w_bg)
        pick_bg_btn.clicked.connect(pick_bg)
        # 展示文本内容
        text_line = QLineEdit(getattr(ref, 'config', {}).get('text_content', ''))
        form.addRow("展示文本", text_line)
        btn_row = QHBoxLayout()
        apply_btn = QPushButton("应用配置")
        export_btn = QPushButton("导出文本")
        btn_row.addWidget(apply_btn); btn_row.addWidget(export_btn)
        basic_group.layout().addLayout(btn_row)
        def do_apply():
            if not ref: return
            ref.configure({
                'font_size': fs_spin.value(),
                'text_color': tc_line.text().strip(),
                'background_color': bg_line.text().strip(),
                'text_content': text_line.text().strip(),
            })
        def do_export():
            path, _ = QFileDialog.getSaveFileName(self, "导出文本", os.path.join(os.getcwd(), "text_display.txt"), "Text Files (*.txt);;All Files (*.*)")
            if path:
                try:
                    with open(path,'w',encoding='utf-8') as f:
                        f.write(str(getattr(ref,'config', {}).get('text_content', '')))
                except Exception as e:
                    print(f"[文本展示] 导出失败: {e}")
        apply_btn.clicked.connect(do_apply)
        export_btn.clicked.connect(do_export)
        self.property_layout.addWidget(basic_group)
        self._current_apply_fn = do_apply

            
    def _show_camera_properties(self):
        """显示相机模块属性"""
        # 基本信息组
        basic_group = QGroupBox("基本信息")
        basic_layout = QFormLayout()
        basic_group.setLayout(basic_layout)
        
        # 模块名称
        name_edit = QLineEdit("相机模块")
        basic_layout.addRow("名称:", name_edit)
        
        # 模块ID
        id_edit = QLineEdit("camera_001")
        basic_layout.addRow("ID:", id_edit)
        
        self.property_layout.addWidget(basic_group)
        
        # 相机配置组
        camera_group = QGroupBox("相机配置")
        camera_layout = QFormLayout()
        camera_group.setLayout(camera_layout)
        
        # 相机类型
        camera_type_combo = QComboBox()
        camera_type_combo.addItems(["USB相机", "网络相机", "工业相机"])
        camera_layout.addRow("相机类型:", camera_type_combo)
        
        # 分辨率
        resolution_combo = QComboBox()
        resolution_combo.addItems(["640x480", "1280x720", "1920x1080", "自定义"])
        camera_layout.addRow("分辨率:", resolution_combo)
        
        # 帧率
        fps_spin = QSpinBox()
        fps_spin.setRange(1, 60)
        fps_spin.setValue(30)
        camera_layout.addRow("帧率(FPS):", fps_spin)
        
        # 曝光时间
        exposure_spin = QDoubleSpinBox()
        exposure_spin.setRange(0.1, 100.0)
        exposure_spin.setValue(10.0)
        exposure_spin.setSuffix(" ms")
        camera_layout.addRow("曝光时间:", exposure_spin)
        
        self.property_layout.addWidget(camera_group)
        
    def _show_trigger_properties(self):
        """显示触发模块属性"""
        # 基本信息组
        basic_group = QGroupBox("基本信息")
        basic_layout = QFormLayout()
        basic_group.setLayout(basic_layout)
        
        name_edit = QLineEdit("触发模块")
        basic_layout.addRow("名称:", name_edit)
        
        id_edit = QLineEdit("trigger_001")
        basic_layout.addRow("ID:", id_edit)
        
        self.property_layout.addWidget(basic_group)
        
        # 触发配置组
        trigger_group = QGroupBox("触发配置")
        trigger_layout = QFormLayout()
        trigger_group.setLayout(trigger_layout)
        
        # 触发方式
        trigger_mode_combo = QComboBox()
        trigger_mode_combo.addItems(["手动触发", "定时触发", "外部信号", "Modbus触发"])
        trigger_layout.addRow("触发方式:", trigger_mode_combo)
        
        # 触发间隔
        interval_spin = QDoubleSpinBox()
        interval_spin.setRange(0.1, 3600.0)
        interval_spin.setValue(1.0)
        interval_spin.setSuffix(" 秒")
        trigger_layout.addRow("触发间隔:", interval_spin)
        
        # 启用状态
        enable_check = QCheckBox("启用触发")
        enable_check.setChecked(True)
        trigger_layout.addRow("", enable_check)
        
        self.property_layout.addWidget(trigger_group)
        
    def _show_model_properties(self):
        """显示模型模块属性 (统一的模型配置面板)"""
        # 基本信息组
        basic_group = QGroupBox("基本信息")
        basic_layout = QFormLayout(); basic_group.setLayout(basic_layout)
        name_edit = QLineEdit("模型模块"); basic_layout.addRow("名称:", name_edit)
        id_edit = QLineEdit("model_001"); basic_layout.addRow("ID:", id_edit)
        self.property_layout.addWidget(basic_group)

        # 模型配置组
        model_group = QGroupBox("模型配置")
        model_layout = QFormLayout(); model_group.setLayout(model_layout)

        # 模型类型
        model_type_combo = QComboBox(); model_type_combo.addItems(["目标检测", "图像分类", "语义分割", "自定义模型"])
        model_layout.addRow("模型类型:", model_type_combo)

        # 模型文件路径
        model_path_layout = QHBoxLayout(); model_path_edit = QLineEdit(); model_path_button = QPushButton("浏览...")
        model_path_layout.addWidget(model_path_edit); model_path_layout.addWidget(model_path_button)
        model_layout.addRow("模型文件:", model_path_layout)

        # 置信度阈值
        confidence_spin = QDoubleSpinBox(); confidence_spin.setRange(0.0, 1.0); confidence_spin.setSingleStep(0.01); confidence_spin.setValue(0.5)
        model_layout.addRow("置信度阈值:", confidence_spin)

        # GPU加速
        gpu_check = QCheckBox("启用GPU加速"); model_layout.addRow("", gpu_check)

        # 输出原始图开关
        export_raw_check = QCheckBox("输出原始图像(image_raw)"); export_raw_check.setChecked(True); model_layout.addRow("", export_raw_check)

        # 目标过滤开关 & 目标类别
        target_filter_check = QCheckBox("仅输出指定类别"); target_filter_check.setChecked(False); model_layout.addRow("", target_filter_check)
        target_classes_edit = QLineEdit(); target_classes_edit.setPlaceholderText("示例: person,car,dog"); model_layout.addRow("目标类别:", target_classes_edit)

        # 最近尺寸显示
        raw_size_label = QLabel("原始图尺寸: (未推理)"); annotated_size_label = QLabel("标注结果尺寸: (未推理)")
        model_layout.addRow("原始尺寸:", raw_size_label); model_layout.addRow("标注尺寸:", annotated_size_label)


        # 缓存引用供后续更新
        self._model_raw_size_label = raw_size_label
        self._model_annotated_size_label = annotated_size_label
        self._model_export_raw_check = export_raw_check
        self._model_target_filter_check = target_filter_check
        self._model_target_classes_edit = target_classes_edit

        # 获取模块引用
        ref = getattr(getattr(self, 'current_module', None), 'module_ref', None)
        if ref and hasattr(ref, 'get_status'):
            try:
                st = ref.get_status()
                raw_shape = st.get('last_raw_shape'); ann_shape = st.get('last_annotated_shape')
                if raw_shape: raw_size_label.setText(f"原始图尺寸: {raw_shape}")
                if ann_shape: annotated_size_label.setText(f"标注结果尺寸: {ann_shape}")
                cfg = getattr(ref, 'config', {}) if isinstance(getattr(ref, 'config', None), dict) else {}
                target_filter_check.setChecked(bool(cfg.get('enable_target_filter', False)))
                tc_list = cfg.get('target_classes', []) or []
                if isinstance(tc_list, (list, tuple)): target_classes_edit.setText(",".join(str(x) for x in tc_list))
            except Exception:
                pass

        # 回调: 原始图开关
        def on_export_raw_changed(checked: bool):
            if ref and isinstance(getattr(ref, 'config', None), dict): ref.config['export_raw'] = bool(checked)
        export_raw_check.stateChanged.connect(lambda _: on_export_raw_changed(export_raw_check.isChecked()))

        # 回调: 目标过滤开关
        def on_target_filter_changed(checked: bool):
            if ref and isinstance(getattr(ref, 'config', None), dict): ref.config['enable_target_filter'] = bool(checked)
        target_filter_check.stateChanged.connect(lambda _: on_target_filter_changed(target_filter_check.isChecked()))

        # 回调: 目标类别名称应用
        def on_target_classes_apply():
            if ref and isinstance(getattr(ref, 'config', None), dict):
                text = target_classes_edit.text().strip()
                ref.config['target_classes'] = [t.strip() for t in text.split(',') if t.strip()] if text else []
        target_classes_edit.editingFinished.connect(on_target_classes_apply)


        self.property_layout.addWidget(model_group)
        
    def _show_postprocess_properties(self):
        """显示后处理模块属性"""
        # 基本信息组
        basic_group = QGroupBox("基本信息")
        basic_layout = QFormLayout()
        basic_group.setLayout(basic_layout)
        
        name_edit = QLineEdit("后处理模块")
        basic_layout.addRow("名称:", name_edit)
        
        id_edit = QLineEdit("postprocess_001")
        basic_layout.addRow("ID:", id_edit)
        
        self.property_layout.addWidget(basic_group)
        
        # 后处理配置组
        postprocess_group = QGroupBox("后处理配置")
        postprocess_layout = QFormLayout()
        postprocess_group.setLayout(postprocess_layout)
        
        # 输出格式
        output_format_combo = QComboBox()
        output_format_combo.addItems(["JSON", "XML", "CSV", "自定义"])
        postprocess_layout.addRow("输出格式:", output_format_combo)
        
        # 结果过滤
        filter_check = QCheckBox("启用结果过滤")
        postprocess_layout.addRow("", filter_check)
        
        # 保存结果
        save_result_check = QCheckBox("保存处理结果")
        postprocess_layout.addRow("", save_result_check)
        
        # 结果输出路径
        output_path_layout = QHBoxLayout()
        output_path_edit = QLineEdit()
        output_path_button = QPushButton("浏览...")
        output_path_layout.addWidget(output_path_edit)
        output_path_layout.addWidget(output_path_button)
        postprocess_layout.addRow("输出路径:", output_path_layout)
        
        self.property_layout.addWidget(postprocess_group)

    def _show_logic_properties(self, module_item):
        """显示逻辑模块属性 (LogicModule) 扩展：表达式 / 动态端口 / 历史 / 错误"""
        ref = module_item.module_ref
        group = QGroupBox("逻辑模块配置")
        form = QFormLayout(); group.setLayout(form)
        # 操作类型下拉
        op_combo = QComboBox(); op_combo.addItems(["AND","OR","XOR","NAND","NOR","NOT"])
        current_op = getattr(ref, 'op', 'AND').upper() if ref else 'AND'
        idx = op_combo.findText(current_op);  
        if idx >= 0: op_combo.setCurrentIndex(idx)
        form.addRow("操作类型:", op_combo)
        # 表达式输入（存在表达式则优先）
        from PyQt6.QtWidgets import QLineEdit, QTextEdit
        expr_edit = QLineEdit(getattr(ref, 'expr', '') if ref else '')
        form.addRow("表达式:", expr_edit)
        # 端口数量
        inputs_spin = QSpinBox(); inputs_spin.setRange(1, 26); inputs_spin.setValue(getattr(ref, 'inputs_count', 2) if ref else 2)
        form.addRow("输入端口数:", inputs_spin)
        # invert 复选
        invert_check = QCheckBox("结果取反")
        invert_check.setChecked(bool(getattr(ref, 'invert', False)))
        form.addRow("取反:", invert_check)
        # 历史容量
        history_spin = QSpinBox(); history_spin.setRange(1, 200); history_spin.setValue(getattr(ref, 'history_size', 20) if ref else 20)
        form.addRow("历史容量:", history_spin)
        # 当前结果 / 执行次数
        result_label = QLabel(str(ref.outputs.get('result')) if ref and 'result' in ref.outputs else "(未执行)")
        form.addRow("当前结果:", result_label)
        exec_count_label = QLabel(str(getattr(ref, 'exec_count', 0)))
        form.addRow("执行次数:", exec_count_label)
        # 错误列表
        errors_view = QTextEdit(); errors_view.setReadOnly(True)
        errors_view.setPlainText("\n".join(getattr(ref, 'errors', [])))
        form.addRow("错误列表:", errors_view)
        # 历史结果
        history_view = QTextEdit(); history_view.setReadOnly(True)
        history_vals = getattr(ref, 'history_results', []) if ref else []
        history_view.setPlainText(",".join(["1" if v else "0" for v in history_vals]))
        form.addRow("历史结果(1/0):", history_view)
        # 应用按钮
        apply_btn = QPushButton("应用")
        form.addRow("", apply_btn)
        def apply():
            if ref:
                old_count = getattr(ref, 'inputs_count', 2)
                cfg = {
                    "op": op_combo.currentText(),
                    "invert": invert_check.isChecked(),
                    "expr": expr_edit.text(),
                    "inputs_count": inputs_spin.value(),
                    "history_size": history_spin.value()
                }
                ref.configure(cfg)
                # 端口数变化则刷新 ModuleItem 端口呈现
                if inputs_spin.value() != old_count and hasattr(module_item, 'refresh_ports'):
                    module_item.refresh_ports()
                # 刷新界面相关显示
                result_label.setText(str(ref.outputs.get('result')) if 'result' in ref.outputs else "(未执行)")
                exec_count_label.setText(str(getattr(ref, 'exec_count', 0)))
                errors_view.setPlainText("\n".join(getattr(ref, 'errors', [])))
                history_vals2 = getattr(ref, 'history_results', [])
                history_view.setPlainText(",".join(["1" if v else "0" for v in history_vals2]))
        apply_btn.clicked.connect(apply)
        # 刷新按钮
        refresh_btn = QPushButton("刷新状态")
        form.addRow("", refresh_btn)
        def refresh():
            if ref:
                result_label.setText(str(ref.outputs.get('result')) if 'result' in ref.outputs else "(未执行)")
                exec_count_label.setText(str(getattr(ref, 'exec_count', 0)))
                errors_view.setPlainText("\n".join(getattr(ref, 'errors', [])))
                history_view.setPlainText(",".join(["1" if v else "0" for v in getattr(ref, 'history_results', [])]))
        refresh_btn.clicked.connect(refresh)
        self._current_apply_fn = apply
        self.property_layout.addWidget(group)

    def apply_current(self):
        """外部快捷键触发应用当前模块属性修改"""
        if callable(getattr(self, '_current_apply_fn', None)):
            self._current_apply_fn()


class DockPanel(QWidget):
    """停靠面板，包含工具箱 (左侧可调宽度)
    自适应宽度: 去除固定宽度, 通过 QSplitter 用户拖拽调整。
    """
    
    # 信号定义
    module_selected = pyqtSignal(str)  # 模块选择信号
    
    def __init__(self):
        super().__init__()
        # 不使用固定宽度, 设置一个合理的最小宽度并允许在 splitter 中调整
        self.setMinimumWidth(220)
        from PyQt6.QtWidgets import QSizePolicy
        sp = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        sp.setHorizontalStretch(0)
        self.setSizePolicy(sp)
        self._init_ui()
        
    def _init_ui(self):
        """初始化用户界面"""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)
        
        # 创建选项卡控件
        tab_widget = QTabWidget()
        layout.addWidget(tab_widget)
        
        # 仅保留模块工具箱（属性面板移至右侧主布局）
        self.module_toolbox = ModuleToolbox()
        tab_widget.addTab(self.module_toolbox, "模块")
        # 调整 tab_widget 尺寸策略, 使其在面板中填充并响应宽度变化
        from PyQt6.QtWidgets import QSizePolicy
        tw_sp = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        tab_widget.setSizePolicy(tw_sp)
        # 连接信号
        self.module_toolbox.module_selected.connect(self.module_selected)

    def show_properties(self, module_item):
        # 属性面板不再在左侧显示
        pass