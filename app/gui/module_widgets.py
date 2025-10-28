#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GUI 模块控件
包含相机、触发、模型、后处理等模块的控件定义
"""

from PyQt6.QtWidgets import (QWidget, QLabel, QVBoxLayout, QTreeWidget, QTreeWidgetItem, QLineEdit, QApplication)
from PyQt6.QtCore import Qt, pyqtSignal, QMimeData
from PyQt6.QtGui import QDrag, QPixmap, QIcon, QPainter, QShortcut, QKeySequence, QColor
from app.pipeline.module_registry import list_registered_modules, get_module_class
from app.pipeline.base_module import ModuleType
from app.pipeline.utility.category_utils import classify_module
from app.utils.i18n import bilingual, translate, get_language_mode, L


class ModuleToolbox(QWidget):
    """模块工具箱树状+搜索+拖拽+快捷键
    自适应宽度: 去除固定宽度, 允许随父级 DockPanel / QSplitter 调整。
    """
    module_selected = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        # 使用尺寸策略而非固定宽度, 最小宽度避免过窄
        from PyQt6.QtWidgets import QSizePolicy
        sp = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        sp.setHorizontalStretch(0)
        self.setSizePolicy(sp)
        self.setMinimumWidth(180)
        self.search_box = QLineEdit()
        # Placeholder bilingual per mode
        self._update_search_placeholder()
        self.search_box.textChanged.connect(self._filter_tree)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemDoubleClicked.connect(self._on_item_activate)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.setDragEnabled(True)
        self.tree.viewport().setAcceptDrops(False)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        layout = QVBoxLayout(self)
        title = QLabel(L("模块工具箱", "Module Toolbox"))
        title.setStyleSheet("""QLabel {font-weight:bold;font-size:14px;padding:6px;background:#f0f0f0;border-bottom:1px solid #ccc;}""")
        # 让树控件获得垂直伸展空间: 使用 stretch=1
        self.tree.setSizePolicy(sp.horizontalPolicy(), QSizePolicy.Policy.Expanding)
        layout.addWidget(title)
        layout.addWidget(self.search_box)
        layout.addWidget(self.tree, 1)
        # 快捷键
        QShortcut(QKeySequence("Ctrl+F"), self, activated=lambda: self.search_box.setFocus())
        QShortcut(QKeySequence("Return"), self, activated=self._add_selected_via_enter)
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self.refresh_modules)
        self.refresh_modules()

    def _update_search_placeholder(self):
        mode = get_language_mode()
        if mode == 'zh':
            self.search_box.setPlaceholderText("搜索模块 (Ctrl+F)...")
        elif mode == 'en':
            self.search_box.setPlaceholderText("Search modules (Ctrl+F)...")
        else:
            self.search_box.setPlaceholderText("搜索/搜索 Search modules (Ctrl+F)...")

    def refresh_modules(self):
        """刷新模块树，按新分类体系分组: 输入 / 模型 / 显示 / 存储 / 协议 / 脚本 / 逻辑 / 其它
        规则与 EnhancedFlowCanvas.contextMenuEvent 中保持一致，避免分类不一致。
        """
        self.tree.clear()
        groups = {k: [] for k in ['输入', '模型', '显示', '存储', '协议', '脚本', '逻辑', '其它']}

        def classify_local(name: str, cls) -> str:
            try:
                mtype = cls(name=name).module_type if cls else None
            except Exception:
                mtype = None
            return classify_module(name, mtype)

        for display in list_registered_modules():
            cls = get_module_class(display)
            cat = classify_local(display, cls)
            groups[cat].append(display)

        # 构建树节点
        for gname, items in groups.items():
            if not items:
                continue
            # 根据语言模式: both=双语, 其它=translate
            label = bilingual(gname) if get_language_mode() == 'both' else translate(gname)
            gnode = QTreeWidgetItem([label])
            # 分组节点不允许直接拖拽
            gnode.setFlags(gnode.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
            self.tree.addTopLevelItem(gnode)
            for mod in sorted(items):
                mod_label = bilingual(mod) if get_language_mode() == 'both' else translate(mod)
                inode = QTreeWidgetItem([mod_label])
                inode.setData(0, Qt.ItemDataRole.UserRole, mod)  # 保留原始标识在 UserRole
                inode.setIcon(0, self._make_icon(mod, gname))
                gnode.addChild(inode)
            gnode.setExpanded(True)
        # 最小列宽保障可读性
        self.tree.resizeColumnToContents(0)
        if self.tree.columnWidth(0) < 140:
            self.tree.setColumnWidth(0, 140)
        self._filter_tree(self.search_box.text())

    def _make_icon(self, name: str, category: str | None = None) -> QIcon:
        """生成简易彩色方块图标。根据分类而非旧 ModuleType 上色。"""
        if category is None:
            cls = get_module_class(name)
            try:
                mtype = cls(name=name).module_type if cls else None
            except Exception:
                mtype = None
            category = classify_module(name, mtype)
        color_map = {
            '输入': '#4CAF50',
            '模型': '#9C27B0',
            '显示': '#2196F3',
            '存储': '#795548',
            '协议': '#FF5722',
            '脚本': '#607D8B',
            '逻辑': '#3F51B5',
            '其它': '#9E9E9E'
        }
        col = color_map.get(category, '#607D8B')
        px = QPixmap(16,16)
        px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(Qt.GlobalColor.white)
        p.setPen(Qt.GlobalColor.transparent)
        p.drawRect(0,0,16,16)
        p.setBrush(Qt.GlobalColor.transparent)
        p.setPen(Qt.GlobalColor.transparent)
        # colored circle
        p.setBrush(Qt.GlobalColor.white)
        p.setPen(Qt.GlobalColor.transparent)
        p.drawEllipse(0,0,16,16)
        p.setBrush(Qt.GlobalColor.white)
        p.drawEllipse(2,2,12,12)
        p.setBrush(Qt.GlobalColor.transparent)
        # overlay color ring
        p.setPen(Qt.GlobalColor.transparent)
        p.setBrush(Qt.GlobalColor.transparent)
        p.end()
        # simple solid color fill rectangle for now
        p2 = QPainter(px)
        p2.fillRect(2,2,12,12, Qt.GlobalColor.white)
        p2.fillRect(2,2,12,12, QColor(col))
        p2.end()
        return QIcon(px)

    def _filter_tree(self, text: str):
        text = text.strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            gnode = self.tree.topLevelItem(i)
            any_visible = False
            for j in range(gnode.childCount()):
                inode = gnode.child(j)
                name = inode.data(0, Qt.ItemDataRole.UserRole)
                visible = (not text) or (name and text in name.lower())
                inode.setHidden(not visible)
                if visible:
                    any_visible = True
            gnode.setHidden(not any_visible)

    def _on_item_activate(self, item: QTreeWidgetItem, col: int):
        name = item.data(0, Qt.ItemDataRole.UserRole)
        if name:
            self.module_selected.emit(name)

    def _on_item_clicked(self, item: QTreeWidgetItem, col: int):
        name = item.data(0, Qt.ItemDataRole.UserRole)
        if name:
            self.module_selected.emit(name)

    def _add_selected_via_enter(self):
        item = self.tree.currentItem()
        if not item:
            return
        name = item.data(0, Qt.ItemDataRole.UserRole)
        if name:
            self.module_selected.emit(name)

    def startDrag(self, supportedActions):
        item = self.tree.currentItem()
        if not item:
            return
        name = item.data(0, Qt.ItemDataRole.UserRole)
        if not name:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData('application/x-fahai-module', name.encode('utf-8'))
        # 端口预览：实例化类
        cls = get_module_class(name)
        ports_str = ''
        if cls:
            try:
                inst = cls(name=name)
                ins = ','.join(inst.input_ports.keys())
                outs = ','.join(inst.output_ports.keys())
                # bilingual ports 仅在常见端口进行映射
                bins = ','.join(bilingual(p) for p in inst.input_ports.keys())
                bouts = ','.join(bilingual(p) for p in inst.output_ports.keys())
                ports_str = f"{bins}|{bouts}"
                mime.setData('application/x-fahai-ports', ports_str.encode('utf-8'))
            except Exception:
                pass
        mime.setText(name)
        drag.setMimeData(mime)
        px = QPixmap(140, 40)
        px.fill(Qt.GlobalColor.white)
        p = QPainter(px)
        p.drawRect(0,0,139,39)
        nm = bilingual(name) if get_language_mode() == 'both' else translate(name)
        p.drawText(4,16, nm)
        if ports_str:
            p.drawText(4,32, ports_str)
        p.end()
        drag.setPixmap(px)
        drag.exec(Qt.DropAction.CopyAction)