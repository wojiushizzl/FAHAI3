#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dock panel module: provides ModuleToolbox (left) and PropertyPanel (right).

Maintenance Note:
This file was previously corrupted by having an entire duplicate module (including a second
shebang and redefinitions of PropertyPanel and DockPanel) pasted INSIDE the method
PropertyPanel._show_default_message. That nesting prevented the top-level DockPanel class
from being defined at module scope, causing ImportError failures elsewhere.

The file has been cleaned so only one set of top-level class definitions remains. If you
need to experiment with an alternative implementation, create a temporary file (e.g.
`dock_panel_experiment.py`) rather than pasting code blocks inside methods. Keep DockPanel
and PropertyPanel defined at module scope.

Internationalization Strategy:
Labels use L(zh, en) and selective bilingual() display depending on language mode. When
adding new property sections, follow existing patterns and avoid hard-coded mixed-language
strings—wrap them with L().
"""
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QSpinBox,
                             QDoubleSpinBox, QComboBox, QCheckBox, QPushButton, QGroupBox,
                             QScrollArea, QTabWidget, QFormLayout, QTextEdit, QFileDialog)
from PyQt6.QtCore import Qt, pyqtSignal
import os
from typing import List
from .module_widgets import ModuleToolbox
from app.utils.i18n import L, get_language_mode, bilingual, translate


class PropertyPanel(QWidget):
    property_changed = pyqtSignal(str, object)
    def __init__(self):
        super().__init__()
        self.current_module = None
        self._current_apply_fn = None
        self._init_ui()
    def _init_ui(self):
        layout = QVBoxLayout(); self.setLayout(layout)
        self.title_label = QLabel(L("属性配置", "Properties"))
        self.title_label.setStyleSheet("QLabel {font-weight:bold;font-size:14px;padding:10px;background:#f0f0f0;border-bottom:1px solid #ccc;}")
        layout.addWidget(self.title_label)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        layout.addWidget(scroll)
        self.property_container = QWidget(); self.property_layout = QVBoxLayout(); self.property_container.setLayout(self.property_layout)
        scroll.setWidget(self.property_container)
        self._show_default_message()
    def _show_default_message(self):
        self._clear_properties()
        lbl = QLabel(L("请选择一个模块来配置属性", "Select a module to configure"))
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("QLabel {color:#666;font-size:12px;padding:20px;}")
        self.property_layout.addWidget(lbl)
    def _clear_properties(self):
        while self.property_layout.count():
            item = self.property_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
    def show_module_properties(self, module_item):
        self.current_module = module_item
        self._clear_properties()
        mtype = module_item.module_type
        mt_display = bilingual(mtype) if get_language_mode() == 'both' else translate(mtype)
        self.title_label.setText(L("模块属性", "Module Properties") + f" - {mt_display}")
        if not self._show_schema_properties(module_item):
            mapping = {
                "文本输入": self._show_text_input_properties,
                "打印": self._show_print_properties,
                "文本展示": self._show_text_display_properties,
                "相机": lambda _m: self._show_camera_properties(),
                "触发": lambda _m: self._show_trigger_properties(),
                "模型": lambda _m: self._show_model_properties(),
                "后处理": lambda _m: self._show_postprocess_properties(),
                "逻辑": self._show_logic_properties,
            }
            fn = mapping.get(mtype)
            if fn: fn(module_item)
    def refresh_model_sizes(self):
        ref = getattr(getattr(self,'current_module',None),'module_ref',None)
        if not ref or not hasattr(ref,'get_status'): return
        try: st = ref.get_status()
        except Exception: return
        raw_shape = st.get('last_raw_shape'); ann_shape = st.get('last_annotated_shape')
        if hasattr(self,'_model_raw_size_label') and raw_shape:
            self._model_raw_size_label.setText(f"{L('原始图尺寸','Raw Size')}: {raw_shape}")
        if hasattr(self,'_model_annotated_size_label') and ann_shape:
            self._model_annotated_size_label.setText(f"{L('标注结果尺寸','Annotated Size')}: {ann_shape}")
    def _show_schema_properties(self, module_item) -> bool:
        ref = getattr(module_item,'module_ref',None)
        if ref is None: return False
        ConfigModel = getattr(ref.__class__,'ConfigModel',None)
        if not ConfigModel or not hasattr(ConfigModel,'__fields__'): return False
        group = QGroupBox(L("配置 (自动生成)", "Config (Auto)"))
        form = QFormLayout(); group.setLayout(form)
        field_widgets = {}; current_cfg = ref.config if isinstance(ref.config,dict) else {}
        for fname, field in ConfigModel.__fields__.items():
            value = current_cfg.get(fname, field.default); w = None
            base_type = getattr(field,'type_',None) or getattr(field,'annotation',None)
            outer = getattr(field,'outer_type_',None); origin_outer = getattr(outer,'__origin__',None)
            is_list_type = isinstance(value,(list,tuple)) or (origin_outer in (list,List))
            if is_list_type:
                display = ",".join(str(v) for v in value) if value else ""
                w = QLineEdit(display); w.setPlaceholderText(L("逗号分隔列表","Comma-separated"))
            elif base_type in (int,):
                w = QSpinBox(); w.setRange(-999999,999999); w.setValue(int(value) if value is not None else 0)
            elif base_type in (float,):
                w = QDoubleSpinBox(); w.setDecimals(4); w.setRange(-1e9,1e9); w.setValue(float(value) if value is not None else 0.0)
            elif base_type in (bool,):
                w = QCheckBox(); w.setChecked(bool(value))
            elif base_type in (str,):
                if fname.lower().endswith('path') or fname.lower().endswith('_path'):
                    container = QWidget(); hl = QHBoxLayout(); hl.setContentsMargins(0,0,0,0); container.setLayout(hl)
                    le = QLineEdit(str(value) if value is not None else "")
                    btn = QPushButton(L("浏览...","Browse..."))
                    def browse():
                        current_text = le.text().strip(); import os
                        if current_text and os.path.isdir(current_text):
                            chosen = QFileDialog.getExistingDirectory(container, L("选择目录","Select Directory"), current_text)
                            if chosen: le.setText(chosen); return
                        chosen_file,_ = QFileDialog.getOpenFileName(container, L("选择文件","Select File"), current_text or "", L("所有文件 (*.*)","All Files (*.*)"))
                        if chosen_file: le.setText(chosen_file)
                    btn.clicked.connect(browse); hl.addWidget(le); hl.addWidget(btn); w = container; field_widgets[fname] = le
                else:
                    w = QLineEdit(str(value) if value is not None else "")
            else:
                w = QTextEdit(); w.setPlainText(str(value))
            if fname not in field_widgets: field_widgets[fname] = w
            form.addRow(fname, w)
        apply_btn = QPushButton(L("应用","Apply")); form.addRow("", apply_btn)
        def apply():
            new_cfg = {}
            for fname, w in field_widgets.items():
                if isinstance(w,QSpinBox): new_cfg[fname] = w.value()
                elif isinstance(w,QDoubleSpinBox): new_cfg[fname] = w.value()
                elif isinstance(w,QCheckBox): new_cfg[fname] = w.isChecked()
                elif isinstance(w,QLineEdit):
                    orig_field = ConfigModel.__fields__[fname]; orig_value = current_cfg.get(fname, orig_field.default)
                    outer = getattr(orig_field,'outer_type_',None); origin_outer = getattr(outer,'__origin__',None)
                    is_list_type = isinstance(orig_value,(list,tuple)) or (origin_outer in (list,List))
                    txt = w.text().strip()
                    if is_list_type:
                        parts = [p.strip() for p in txt.split(',') if p.strip()] if txt else []
                        inner_t = getattr(orig_field,'type_',None) or getattr(orig_field,'annotation',str)
                        converted = []
                        for p in parts:
                            if inner_t in (int,float):
                                try: converted.append(inner_t(p))
                                except Exception: converted.append(p)
                            else: converted.append(p)
                        new_cfg[fname] = converted
                    else:
                        new_cfg[fname] = txt
                elif isinstance(w,QTextEdit): new_cfg[fname] = w.toPlainText().strip()
            ref.configure(new_cfg)
        apply_btn.clicked.connect(apply)
        self.property_layout.addWidget(group); self._current_apply_fn = apply; return True
    def _show_text_input_properties(self, module_item):
        basic_group = QGroupBox(L("文本输入配置","Text Input Config"))
        form = QFormLayout(); basic_group.setLayout(form)
        ref = module_item.module_ref; current = ref.text_value if ref and hasattr(ref,'text_value') else ""
        text_edit = QLineEdit(current); form.addRow(L("当前文本:","Text:"), text_edit)
        apply_btn = QPushButton(L("应用","Apply")); form.addRow("", apply_btn)
        def apply():
            if ref and hasattr(ref,'set_text'): ref.set_text(text_edit.text())
        apply_btn.clicked.connect(apply); self._current_apply_fn = apply; self.property_layout.addWidget(basic_group)
    def _show_print_properties(self, module_item):
        basic_group = QGroupBox(L("打印显示 / 文本查看","Print / Text Viewer"))
        layout = QVBoxLayout(); basic_group.setLayout(layout)
        ref = module_item.module_ref
        from PyQt6.QtWidgets import QPlainTextEdit
        text_area = QPlainTextEdit(); text_area.setPlaceholderText(L("(无内容)","(empty)"))
        text_area.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        text_area.setStyleSheet("QPlainTextEdit {background:#fafafa;font-family:Consolas;font-size:11px;border:1px solid #bbb;}")
        lines = []
        if ref and hasattr(ref,'display_text'):
            try: lines = ref.display_text.splitlines()
            except Exception: lines = []
        text_area.setPlainText("\n".join(lines) if lines else ""); layout.addWidget(text_area)
        btn_row = QHBoxLayout(); buttons = {
            'copy': QPushButton(L("复制全部","Copy All")),
            'clear': QPushButton(L("清空","Clear")),
            'export': QPushButton(L("导出...","Export...")),
            'apply': QPushButton(L("应用到模块","Apply to Module")),
            'refresh': QPushButton(L("刷新","Refresh"))
        }
        for b in buttons.values(): btn_row.addWidget(b)
        layout.addLayout(btn_row)
        def do_copy(): text_area.selectAll(); text_area.copy(); text_area.moveCursor(text_area.textCursor().End)
        def do_clear(): text_area.clear()
        def do_export():
            path,_ = QFileDialog.getSaveFileName(self, L("导出文本","Export Text"), os.path.join(os.getcwd(),"print_display.txt"), "Text Files (*.txt);;All Files (*.*)")
            if path:
                try: open(path,'w',encoding='utf-8').write(text_area.toPlainText())
                except Exception as e: print(f"[PrintDisplay] 导出失败: {e}")
        def do_apply():
            if ref and hasattr(ref,'_lines'):
                raw = text_area.toPlainText().splitlines(); max_lines = int(getattr(ref,'config',{}).get('max_lines',10)) if hasattr(ref,'config') else 10
                ref._lines = raw[-max_lines:]; ref._last_text = ref._lines[-1] if ref._lines else None
        def do_refresh():
            if ref and hasattr(ref,'display_text'): text_area.setPlainText(getattr(ref,'display_text',''))
        buttons['copy'].clicked.connect(do_copy); buttons['clear'].clicked.connect(do_clear); buttons['export'].clicked.connect(do_export)
        buttons['apply'].clicked.connect(do_apply); buttons['refresh'].clicked.connect(do_refresh)
        self._current_apply_fn = do_apply; self.property_layout.addWidget(basic_group)
    def _show_text_display_properties(self, module_item):
        ref = module_item.module_ref
        basic_group = QGroupBox(L("文本展示配置","Text Display Config")); form = QFormLayout(); basic_group.setLayout(form)
        fs_spin = QSpinBox(); fs_spin.setRange(6,72); fs_spin.setValue(int(getattr(ref,'config', {}).get('font_size', 12))); form.addRow(L("字体大小","Font Size"), fs_spin)
        tc_line = QLineEdit(getattr(ref,'config', {}).get('text_color', '#222222')); pick_tc_btn = QPushButton(L("选色","Pick"))
        def pick_tc(): col = QColorDialog.getColor(); tc_line.setText(col.name()) if col.isValid() else None
        from PyQt6.QtWidgets import QColorDialog
        hl_tc = QHBoxLayout(); hl_tc.addWidget(tc_line); hl_tc.addWidget(pick_tc_btn); w_tc = QWidget(); w_tc.setLayout(hl_tc); form.addRow(L("文字颜色","Text Color"), w_tc); pick_tc_btn.clicked.connect(pick_tc)
        bg_line = QLineEdit(getattr(ref,'config', {}).get('background_color', '#ffffff')); pick_bg_btn = QPushButton(L("选色","Pick"))
        def pick_bg(): col = QColorDialog.getColor(); bg_line.setText(col.name()) if col.isValid() else None
        hl_bg = QHBoxLayout(); hl_bg.addWidget(bg_line); hl_bg.addWidget(pick_bg_btn); w_bg = QWidget(); w_bg.setLayout(hl_bg); form.addRow(L("背景颜色","Background"), w_bg); pick_bg_btn.clicked.connect(pick_bg)
        text_line = QLineEdit(getattr(ref,'config', {}).get('text_content', '')); form.addRow(L("展示文本","Display Text"), text_line)
        btn_row = QHBoxLayout(); apply_btn = QPushButton(L("应用配置","Apply")); export_btn = QPushButton(L("导出文本","Export Text")); btn_row.addWidget(apply_btn); btn_row.addWidget(export_btn); basic_group.layout().addLayout(btn_row)
        def do_apply():
            if not ref: return
            ref.configure({'font_size': fs_spin.value(),'text_color': tc_line.text().strip(),'background_color': bg_line.text().strip(),'text_content': text_line.text().strip()})
        def do_export():
            path,_ = QFileDialog.getSaveFileName(self, L("导出文本","Export Text"), os.path.join(os.getcwd(),"text_display.txt"), "Text Files (*.txt);;All Files (*.*)")
            if path:
                try: open(path,'w',encoding='utf-8').write(str(getattr(ref,'config', {}).get('text_content','')))
                except Exception as e: print(f"[文本展示] 导出失败: {e}")
        apply_btn.clicked.connect(do_apply); export_btn.clicked.connect(do_export); self.property_layout.addWidget(basic_group); self._current_apply_fn = do_apply
    def _show_camera_properties(self):
        basic_group = QGroupBox(L("基本信息","Basic")); basic_layout = QFormLayout(); basic_group.setLayout(basic_layout)
        name_edit = QLineEdit(L("相机模块","Camera Module")); basic_layout.addRow(L("名称:","Name:"), name_edit)
        id_edit = QLineEdit("camera_001"); basic_layout.addRow("ID:", id_edit); self.property_layout.addWidget(basic_group)
        camera_group = QGroupBox(L("相机配置","Camera Config")); camera_layout = QFormLayout(); camera_group.setLayout(camera_layout)
        type_combo = QComboBox(); type_combo.addItems([L("USB相机","USB"), L("网络相机","Network"), L("工业相机","Industrial")]); camera_layout.addRow(L("相机类型:","Camera Type:"), type_combo)
        res_combo = QComboBox(); res_combo.addItems(["640x480","1280x720","1920x1080", L("自定义","Custom")]); camera_layout.addRow(L("分辨率:","Resolution:"), res_combo)
        fps_spin = QSpinBox(); fps_spin.setRange(1,60); fps_spin.setValue(30); camera_layout.addRow(L("帧率(FPS):","FPS:"), fps_spin)
        exposure_spin = QDoubleSpinBox(); exposure_spin.setRange(0.1,100.0); exposure_spin.setValue(10.0); exposure_spin.setSuffix(" ms"); camera_layout.addRow(L("曝光时间:","Exposure:"), exposure_spin)
        self.property_layout.addWidget(camera_group)
    def _show_trigger_properties(self):
        basic_group = QGroupBox(L("基本信息","Basic")); basic_layout = QFormLayout(); basic_group.setLayout(basic_layout)
        name_edit = QLineEdit(L("触发模块","Trigger Module")); basic_layout.addRow(L("名称:","Name:"), name_edit)
        id_edit = QLineEdit("trigger_001"); basic_layout.addRow("ID:", id_edit); self.property_layout.addWidget(basic_group)
        trig_group = QGroupBox(L("触发配置","Trigger Config")); trig_layout = QFormLayout(); trig_group.setLayout(trig_layout)
        mode_combo = QComboBox(); mode_combo.addItems([L("手动触发","Manual"), L("定时触发","Interval"), L("外部信号","External Signal"), L("Modbus触发","Modbus")]); trig_layout.addRow(L("触发方式:","Trigger Mode:"), mode_combo)
        interval_spin = QDoubleSpinBox(); interval_spin.setRange(0.1,3600.0); interval_spin.setValue(1.0); interval_spin.setSuffix(L(" 秒"," s")); trig_layout.addRow(L("触发间隔:","Interval:"), interval_spin)
        enable_check = QCheckBox(L("启用触发","Enable")); enable_check.setChecked(True); trig_layout.addRow("", enable_check); self.property_layout.addWidget(trig_group)
    def _show_model_properties(self):
        basic_group = QGroupBox(L("基本信息","Basic")); basic_layout = QFormLayout(); basic_group.setLayout(basic_layout)
        name_edit = QLineEdit(L("模型模块","Model Module")); basic_layout.addRow(L("名称:","Name:"), name_edit)
        id_edit = QLineEdit("model_001"); basic_layout.addRow("ID:", id_edit); self.property_layout.addWidget(basic_group)
        model_group = QGroupBox(L("模型配置","Model Config")); model_layout = QFormLayout(); model_group.setLayout(model_layout)
        type_combo = QComboBox(); type_combo.addItems([L("目标检测","Detection"), L("图像分类","Classification"), L("语义分割","Segmentation"), L("自定义模型","Custom")]); model_layout.addRow(L("模型类型:","Model Type:"), type_combo)
        path_layout = QHBoxLayout(); path_edit = QLineEdit(); browse_btn = QPushButton(L("浏览...","Browse...")); path_layout.addWidget(path_edit); path_layout.addWidget(browse_btn); model_layout.addRow(L("模型文件:","Model File:"), path_layout)
        conf_spin = QDoubleSpinBox(); conf_spin.setRange(0.0,1.0); conf_spin.setSingleStep(0.01); conf_spin.setValue(0.5); model_layout.addRow(L("置信度阈值:","Confidence Threshold:"), conf_spin)
        gpu_check = QCheckBox(L("启用GPU加速","Enable GPU")); model_layout.addRow("", gpu_check)
        raw_check = QCheckBox(L("输出原始图像(image_raw)","Output Raw Image")); raw_check.setChecked(True); model_layout.addRow("", raw_check)
        filt_check = QCheckBox(L("仅输出指定类别","Filter Classes")); model_layout.addRow("", filt_check)
        cls_edit = QLineEdit(); cls_edit.setPlaceholderText(L("示例: person,car,dog","e.g. person,car,dog")); model_layout.addRow(L("目标类别:","Target Classes:"), cls_edit)
        raw_size = QLabel(L("原始图尺寸: (未推理)","Raw Size: (no inference)")); ann_size = QLabel(L("标注结果尺寸: (未推理)","Annotated Size: (no inference)"))
        model_layout.addRow(L("原始尺寸:","Raw:"), raw_size); model_layout.addRow(L("标注尺寸:","Annotated:"), ann_size)
        self._model_raw_size_label = raw_size; self._model_annotated_size_label = ann_size
        ref = getattr(getattr(self,'current_module',None),'module_ref',None)
        if ref and hasattr(ref,'get_status'):
            try:
                st = ref.get_status(); rs = st.get('last_raw_shape'); ashp = st.get('last_annotated_shape')
                if rs: raw_size.setText(f"{L('原始图尺寸','Raw Size')}: {rs}")
                if ashp: ann_size.setText(f"{L('标注结果尺寸','Annotated Size')}: {ashp}")
                cfg = getattr(ref,'config',{}) if isinstance(getattr(ref,'config',None),dict) else {}
                filt_check.setChecked(bool(cfg.get('enable_target_filter', False)))
                tc_list = cfg.get('target_classes', []) or []
                if isinstance(tc_list,(list,tuple)): cls_edit.setText(",".join(str(x) for x in tc_list))
            except Exception: pass
        raw_check.stateChanged.connect(lambda _: ref and isinstance(getattr(ref,'config',None),dict) and ref.config.__setitem__('export_raw', raw_check.isChecked()))
        filt_check.stateChanged.connect(lambda _: ref and isinstance(getattr(ref,'config',None),dict) and ref.config.__setitem__('enable_target_filter', filt_check.isChecked()))
        cls_edit.editingFinished.connect(lambda: ref and isinstance(getattr(ref,'config',None),dict) and ref.config.__setitem__('target_classes', [t.strip() for t in cls_edit.text().split(',') if t.strip()]))
        self.property_layout.addWidget(model_group)
    def _show_postprocess_properties(self):
        basic_group = QGroupBox(L("基本信息","Basic")); basic_layout = QFormLayout(); basic_group.setLayout(basic_layout)
        name_edit = QLineEdit(L("后处理模块","Postprocess Module")); basic_layout.addRow(L("名称:","Name:"), name_edit)
        id_edit = QLineEdit("postprocess_001"); basic_layout.addRow("ID:", id_edit); self.property_layout.addWidget(basic_group)
        post_group = QGroupBox(L("后处理配置","Postprocess Config")); post_layout = QFormLayout(); post_group.setLayout(post_layout)
        fmt_combo = QComboBox(); fmt_combo.addItems(["JSON","XML","CSV", L("自定义","Custom")]); post_layout.addRow(L("输出格式:","Format:"), fmt_combo)
        filter_check = QCheckBox(L("启用结果过滤","Enable Filter")); post_layout.addRow("", filter_check)
        save_check = QCheckBox(L("保存处理结果","Save Result")); post_layout.addRow("", save_check)
        out_layout = QHBoxLayout(); out_edit = QLineEdit(); out_btn = QPushButton(L("浏览...","Browse...")); out_layout.addWidget(out_edit); out_layout.addWidget(out_btn); post_layout.addRow(L("输出路径:","Output Path:"), out_layout)
        self.property_layout.addWidget(post_group)
    def _show_logic_properties(self, module_item):
        ref = module_item.module_ref
        group = QGroupBox(L("逻辑模块配置","Logic Module Config")); form = QFormLayout(); group.setLayout(form)
        op_combo = QComboBox(); op_combo.addItems(["AND","OR","XOR","NAND","NOR","NOT"]); current_op = getattr(ref,'op','AND').upper() if ref else 'AND'; idx = op_combo.findText(current_op);  
        if idx >= 0: op_combo.setCurrentIndex(idx)
        form.addRow(L("操作类型:","Operation:"), op_combo)
        expr_edit = QLineEdit(getattr(ref,'expr','') if ref else ''); form.addRow(L("表达式:","Expression:"), expr_edit)
        inputs_spin = QSpinBox(); inputs_spin.setRange(1,26); inputs_spin.setValue(getattr(ref,'inputs_count',2) if ref else 2); form.addRow(L("输入端口数:","Inputs:"), inputs_spin)
        invert_check = QCheckBox(L("结果取反","Invert Result")); invert_check.setChecked(bool(getattr(ref,'invert',False))); form.addRow(L("取反:","Invert:"), invert_check)
        history_spin = QSpinBox(); history_spin.setRange(1,200); history_spin.setValue(getattr(ref,'history_size',20) if ref else 20); form.addRow(L("历史容量:","History Size:"), history_spin)
        result_label = QLabel(str(ref.outputs.get('result')) if ref and 'result' in ref.outputs else L("(未执行)","(not run)")); form.addRow(L("当前结果:","Current Result:"), result_label)
        exec_label = QLabel(str(getattr(ref,'exec_count',0))); form.addRow(L("执行次数:","Exec Count:"), exec_label)
        errors_view = QTextEdit(); errors_view.setReadOnly(True); errors_view.setPlainText("\n".join(getattr(ref,'errors', []))); form.addRow(L("错误列表:","Errors:"), errors_view)
        history_view = QTextEdit(); history_view.setReadOnly(True); history_vals = getattr(ref,'history_results', []) if ref else []; history_view.setPlainText(",".join(["1" if v else "0" for v in history_vals])); form.addRow(L("历史结果(1/0):","History (1/0):"), history_view)
        apply_btn = QPushButton(L("应用","Apply")); form.addRow("", apply_btn)
        def apply():
            if ref:
                old_count = getattr(ref,'inputs_count',2)
                ref.configure({"op": op_combo.currentText(),"invert": invert_check.isChecked(),"expr": expr_edit.text(),"inputs_count": inputs_spin.value(),"history_size": history_spin.value()})
                if inputs_spin.value() != old_count and hasattr(module_item,'refresh_ports'): module_item.refresh_ports()
                result_label.setText(str(ref.outputs.get('result')) if 'result' in ref.outputs else L("(未执行)","(not run)"))
                exec_label.setText(str(getattr(ref,'exec_count',0)))
                errors_view.setPlainText("\n".join(getattr(ref,'errors', [])))
                history_view.setPlainText(",".join(["1" if v else "0" for v in getattr(ref,'history_results', [])]))
        apply_btn.clicked.connect(apply)
        refresh_btn = QPushButton(L("刷新状态","Refresh Status")); form.addRow("", refresh_btn); refresh_btn.clicked.connect(apply)
        self._current_apply_fn = apply; self.property_layout.addWidget(group)
    def apply_current(self):
        if callable(getattr(self,'_current_apply_fn',None)): self._current_apply_fn()

class DockPanel(QWidget):
    module_selected = pyqtSignal(str)
    def __init__(self):
        super().__init__(); self.setMinimumWidth(220)
        from PyQt6.QtWidgets import QSizePolicy
        sp = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding); sp.setHorizontalStretch(0); self.setSizePolicy(sp)
        self._init_ui()
    def _init_ui(self):
        layout = QVBoxLayout(); layout.setContentsMargins(0,0,0,0); self.setLayout(layout)
        tab_widget = QTabWidget(); layout.addWidget(tab_widget)
        self.module_toolbox = ModuleToolbox(); tab_widget.addTab(self.module_toolbox, L("模块","Modules"))
        from PyQt6.QtWidgets import QSizePolicy
        tw_sp = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding); tab_widget.setSizePolicy(tw_sp)
        self.module_toolbox.module_selected.connect(self.module_selected)
    def show_properties(self, module_item):
        pass