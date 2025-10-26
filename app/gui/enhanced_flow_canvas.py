#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""增强版流程画布 (EnhancedFlowCanvas)
实现端口点击拖拽连线 (输出 -> 输入) :
- 按下输出端口左键开始拖拽
- 光标移动时临时线跟随
- 在输入端口释放左键则创建连接
- 在空白区域释放则取消
"""
from PyQt6.QtWidgets import (QGraphicsView, QGraphicsScene, QGraphicsItem,
                             QGraphicsRectItem, QGraphicsTextItem, QMenu, QToolTip)
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal, QTimer
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QAction
from typing import Dict, Any, List
import json, os

from app.gui.connection_graphics import BetterConnectionLine
from app.pipeline.module_registry import get_module_class
from app.pipeline.pipeline_executor import PipelineExecutor

class ModuleItem(QGraphicsRectItem):
    """模块项，支持动态端口反射"""
    def __init__(self, module_type: str, x=0, y=0, width=140, height=80, canvas=None,
                 module_ref=None, input_ports: List[str] = None, output_ports: List[str] = None):
        super().__init__(0, 0, width, height)
        self.canvas = canvas
        self.module_type = module_type
        self.module_ref = module_ref
        self.module_id = module_ref.module_id if module_ref else f"{module_type}_{id(self)}"
        self.setPos(x, y)
        self.setRect(0, 0, width, height)
        self.setBrush(QBrush(QColor(200, 220, 255)))
        self.setPen(QPen(QColor(100, 150, 200), 2))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)  # 用于尺寸调整与光标反馈
        self.text_item = QGraphicsTextItem(module_type, self)
        self.text_item.setFont(QFont("Arial", 10))
        self.text_item.setPos(10, 8)
        if input_ports is None:
            input_ports = list(module_ref.input_ports.keys()) if module_ref else ["in"]
        if output_ports is None:
            output_ports = list(module_ref.output_ports.keys()) if module_ref else ["out"]
        self.input_ports_def = input_ports
        self.output_ports_def = output_ports
        self.input_points = []
        self.output_points = []
        self.input_labels: List[QGraphicsTextItem] = []
        self.output_labels: List[QGraphicsTextItem] = []

        # 图片展示支持（与旧 flow_canvas 一致）
        self._is_image_viewer = (module_type == "图片展示")
        self._thumb_item = None
        if self._is_image_viewer:
            from PyQt6.QtWidgets import QGraphicsPixmapItem
            self._thumb_item = QGraphicsPixmapItem(self)
            self._thumb_item.setPos(8, 24)

        # 文本展示支持（打印显示模块）
        self._is_text_viewer = (module_type == "打印显示")
        self._text_item = None
        if self._is_text_viewer:
            self._text_item = QGraphicsTextItem("", self)
            self._text_item.setFont(QFont("Consolas", 9))
            self._text_item.setDefaultTextColor(QColor(30, 30, 30))
            self._text_item.setPos(8, 24)
        # OK/NOK 状态模块
        self._is_oknok_viewer = (module_type == "OK/NOK展示")
        self._oknok_rect = None
        self._oknok_text = None
        if self._is_oknok_viewer:
            from PyQt6.QtWidgets import QGraphicsRectItem
            self._oknok_rect = QGraphicsRectItem(self)
            self._oknok_rect.setBrush(QBrush(QColor(180, 180, 180)))
            self._oknok_rect.setPen(QPen(QColor(120,120,120),1))
            self._oknok_text = QGraphicsTextItem("?", self._oknok_rect)
            self._oknok_text.setFont(QFont("Arial", 12, QFont.Weight.Bold))
            self._oknok_text.setDefaultTextColor(QColor(255,255,255))

        # 可调整大小支持
        self._resizing = False
        self._resize_margin = 14
        self._orig_size = (width, height)
        self._corner_handle_size = 14
        from PyQt6.QtWidgets import QGraphicsRectItem as _QR
        self._corner_handle = _QR(
            self.rect().width() - self._corner_handle_size,
            self.rect().height() - self._corner_handle_size,
            self._corner_handle_size,
            self._corner_handle_size,
            self
        )
        self._corner_handle.setBrush(QBrush(QColor(120, 120, 120)))
        self._corner_handle.setPen(QPen(Qt.PenStyle.NoPen))
        self._corner_handle.setOpacity(0.55)
        self._corner_handle.setZValue(10)
        self._corner_handle.setToolTip("拖拽调整大小")
        # 让事件传递给父项
        self._corner_handle.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._corner_handle.setAcceptHoverEvents(False)

        self._create_points()
        if self._is_image_viewer:
            self._update_thumbnail(None)

    def _create_points(self):
        """创建端口并为后续展示内容预留下方区域。
        布局策略：
        - 顶部标题占约 20px 高度。
        - 端口自标题下开始，行高 18px。
        - 输入端口靠左，输出端口靠右（同一 Y 对齐）。
        - 预留内容区起始 y = 标题高度 + max(port_rows)*行高 + 下间距。
        - 缩略图或文本显示位于内容区，不与端口重叠。
        """
        title_h = 20
        row_h = 18
        max_rows = max(len(self.input_ports_def), len(self.output_ports_def))
        ports_start_y = title_h  # 第一行端口的顶部位置
        # 构建输入端口
        for idx, name in enumerate(self.input_ports_def):
            y = ports_start_y + idx * row_h
            point = ConnectionPoint(self, "input", -6, y - 5, name, canvas=self.canvas)
            self.input_points.append(point)
            label = QGraphicsTextItem(name, self)
            label.setFont(QFont("Arial", 8))
            label.setDefaultTextColor(QColor(50, 50, 50))
            label.setPos(2, y - 8)
            self.input_labels.append(label)
        # 构建输出端口
        for idx, name in enumerate(self.output_ports_def):
            y = ports_start_y + idx * row_h
            point = ConnectionPoint(self, "output", self.rect().width() - 4, y - 5, name, canvas=self.canvas)
            self.output_points.append(point)
            label = QGraphicsTextItem(name, self)
            label.setFont(QFont("Arial", 8))
            label.setDefaultTextColor(QColor(50, 50, 50))
            # 输出标签置于中间偏右，避免与输入标签重叠
            label.setPos(self.rect().width()/2 - 10, y - 8)
            self.output_labels.append(label)
        # 计算内容区起始 y
        self._content_offset = title_h + max_rows * row_h + 6  # 端口区下额外留白
        # 若当前矩形高度不足以展示最小内容区则扩展
        min_content_h = 60 if (self._is_image_viewer or self._is_text_viewer) else 0
        needed_h = self._content_offset + min_content_h + 8
        if needed_h > self.rect().height():
            self.setRect(0, 0, self.rect().width(), needed_h)
        # 初始内容项位置
        if self._thumb_item:
            self._thumb_item.setPos(8, self._content_offset)
        if getattr(self, '_text_item', None):
            self._text_item.setPos(8, self._content_offset)

    def refresh_ports(self):
        """根据 module_ref 的当前端口定义刷新图形端口。移除旧端口与标签并重建。
        注意：会删除与已移除端口相关的连接。"""
        if self.canvas is None:
            return
        # 收集要移除的子项（端口与端口标签）
        for child in list(self.childItems()):
            if isinstance(child, ConnectionPoint):
                # 删除相关连接线
                for line in list(child.connections):
                    try:
                        self.canvas._remove_connection(line)
                    except Exception:
                        pass
            if isinstance(child, ConnectionPoint) or (isinstance(child, QGraphicsTextItem) and child is not self.text_item):
                child.scene().removeItem(child)
        self.input_points.clear()
        self.output_points.clear()
        # 更新端口定义列表
        if self.module_ref:
            self.input_ports_def = list(self.module_ref.input_ports.keys())
            self.output_ports_def = list(self.module_ref.output_ports.keys())
        self._create_points()

    # ----- 缩略图与大小调整支持 -----
    def refresh_visual(self):
        """根据模块类型刷新视觉元素。
        图片展示：缩略图更新 + 动态高度调整。
        文本展示：多行文本更新 + 动态高度调整。
        """
        if not self.module_ref:
            return
        # ----- 图片展示处理 -----
        if self._is_image_viewer:
            img = self.module_ref.outputs.get("image")
            if img is None:
                img = getattr(self.module_ref, 'last_image', None)
            prev_has_img = getattr(self, '_prev_has_img', None)
            has_img_now = img is not None and hasattr(img, 'shape')
            if prev_has_img is None or prev_has_img != has_img_now:
                try:
                    if not has_img_now:
                        print(f"[DEBUG][{self.module_id}] refresh_visual: 无图像")
                    else:
                        print(f"[DEBUG][{self.module_id}] refresh_visual: shape={getattr(img,'shape',None)} dtype={getattr(img,'dtype',None)}")
                except Exception as e:
                    print(f"[DEBUG][{self.module_id}] refresh_visual: 打印异常: {e}")
                self._prev_has_img = has_img_now
            self._update_thumbnail(img)
        # ----- 文本展示处理 -----
        if self._is_text_viewer and self._text_item:
            try:
                text = getattr(self.module_ref, 'display_text', '') or ''
            except Exception:
                text = ''
            prev_text = getattr(self, '_prev_text_content', None)
            if prev_text != text:
                self._prev_text_content = text
                display = text if text.strip() else "(无内容)"
                self._text_item.setPlainText(display)
                # 设定文本宽度为内容区宽度
                content_width = max(20, self.rect().width() - 16)
                self._text_item.setTextWidth(content_width)
                try:
                    doc_height = self._text_item.document().size().height()
                except Exception:
                    doc_height = 0
                # 内容区所需高度 = doc_height + 内边距
                needed_h = self._content_offset + doc_height + 12
                if needed_h > self.rect().height():
                    self.setRect(0, 0, self.rect().width(), needed_h)
                    self._relayout_ports()
        # ----- OK/NOK 状态展示 -----
        if self._is_oknok_viewer and self._oknok_rect and self.module_ref:
            try:
                flag = self.module_ref.outputs.get('flag')
                txt = self.module_ref.outputs.get('text') or getattr(self.module_ref, 'display_text', '?')
                font_sz = int(self.module_ref.config.get('font_size', 12)) if isinstance(self.module_ref.config, dict) else 12
            except Exception:
                flag = None; txt = '?'; font_sz = 12
            # 颜色选择
            if flag is True:
                bg = QColor(46,125,50)   # 绿色
            elif flag is False:
                bg = QColor(198,40,40)   # 红色
            else:
                bg = QColor(120,120,120) # 未知
            self._oknok_rect.setBrush(QBrush(bg))
            self._oknok_text.setPlainText(str(txt))
            # 应用字体大小
            try:
                self._oknok_text.setFont(QFont("Arial", max(8, min(font_sz, 72)), QFont.Weight.Bold))
            except Exception:
                pass
            # 定位与尺寸：放置于内容区，填满可用宽度的一部分
            content_offset = getattr(self, '_content_offset', 40)
            inner_w = max(60, self.rect().width() - 16)
            inner_h = max(34, self.rect().height() - content_offset - 8)
            self._oknok_rect.setRect(8, content_offset, inner_w, inner_h)
            # 文本居中
            try:
                b = self._oknok_text.boundingRect()
                tx = 8 + (inner_w - b.width())/2
                ty = content_offset + (inner_h - b.height())/2 - 2
                self._oknok_text.setPos(tx, ty)
            except Exception:
                pass

    def _update_thumbnail(self, img):
        if not self._thumb_item:
            return
        from PyQt6.QtGui import QImage, QPixmap
        # 内容区尺寸：矩形总高减去内容偏移与底部内边距
        content_offset = getattr(self, '_content_offset', 40)
        available_w = int(self.rect().width()) - 16
        available_h = int(self.rect().height()) - content_offset - 8
        if available_w < 20: available_w = 20
        if available_h < 20: available_h = 20
        w, h = available_w, available_h
        if img is None or not hasattr(img, 'shape'):
            placeholder = QImage(w, h, QImage.Format.Format_RGB32)
            placeholder.fill(QColor(230, 230, 230))
            self._thumb_item.setPixmap(QPixmap.fromImage(placeholder))
            return
        try:
            import numpy as np
            arr = img
            if len(arr.shape) == 2:
                arr = np.stack([arr]*3, axis=-1)
            elif arr.shape[2] == 4:
                arr = arr[:, :, :3]
            arr_rgb = arr[:, :, ::-1].copy()  # BGR->RGB
            h0, w0 = arr_rgb.shape[:2]
            qimg = QImage(arr_rgb.data, w0, h0, w0*3, QImage.Format.Format_RGB888)
            pix = QPixmap.fromImage(qimg)
            from PyQt6.QtCore import Qt as _Qt
            pix_scaled = pix.scaled(w, h, _Qt.AspectRatioMode.KeepAspectRatio, _Qt.TransformationMode.SmoothTransformation)
            self._thumb_item.setPixmap(pix_scaled)
        except Exception as e:
            print(f"[DEBUG][{self.module_id}] _update_thumbnail 异常: {e}")
            placeholder = QImage(w, h, QImage.Format.Format_RGB32)
            placeholder.fill(QColor(200, 200, 200))
            self._thumb_item.setPixmap(QPixmap.fromImage(placeholder))

    def mouseDoubleClickEvent(self, event):
        if self._is_image_viewer and self.module_ref:
            cur_w = int(self.module_ref.config.get("width", 160))
            # 根据当前配置切换预设尺寸，并同步更新矩形大小以立即反映缩略图变化
            if cur_w <= 160:
                new_w, new_h = 320, 240
            else:
                new_w, new_h = 160, 120
            self.module_ref.configure({"width": new_w, "height": new_h})
            # 画布矩形含标题与边距：宽度加 16， 高度加 34
            self.setRect(0, 0, new_w + 16, new_h + 34)
            self._relayout_ports()
            self.refresh_visual()
        elif self.module_type == "路径选择器" and self.module_ref:
            # 打开选择对话框
            from PyQt6.QtWidgets import QFileDialog
            mode = self.module_ref.config.get("selection_mode", "directory")
            title = self.module_ref.config.get("dialog_title", "选择路径")
            start = self.module_ref.config.get("default_path", "") or ""
            chosen = None
            if mode == "directory":
                chosen = QFileDialog.getExistingDirectory(None, title, start)
            else:
                file_path, _ = QFileDialog.getOpenFileName(None, title, start, 'All (*)')
                chosen = file_path
            if chosen:
                try:
                    self.module_ref.set_path(chosen)
                    print(f"[路径选择器] 已选择: {chosen}")
                except Exception as e:
                    print(f"[路径选择器] 设置路径失败: {e}")
        super().mouseDoubleClickEvent(event)

    def hoverMoveEvent(self, event):
        pos = event.pos()
        w = self.rect().width(); h = self.rect().height()
        near_right = abs(pos.x() - w) <= self._resize_margin
        near_bottom = abs(pos.y() - h) <= self._resize_margin
        in_corner = False
        if self._corner_handle:
            ch = QRectF(
                self.rect().width() - self._corner_handle_size,
                self.rect().height() - self._corner_handle_size,
                self._corner_handle_size,
                self._corner_handle_size
            )
            in_corner = ch.contains(pos)
        if in_corner or (near_right and near_bottom):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif near_right:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif near_bottom:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.pos(); w = self.rect().width(); h = self.rect().height()
            corner_hit = False
            if self._corner_handle:
                ch = QRectF(
                    self.rect().width() - self._corner_handle_size,
                    self.rect().height() - self._corner_handle_size,
                    self._corner_handle_size,
                    self._corner_handle_size
                )
                corner_hit = ch.contains(pos)
            if corner_hit or (abs(pos.x()-w) <= self._resize_margin) or (abs(pos.y()-h) <= self._resize_margin):
                self._resizing = True
                self._orig_size = (w, h)
                self._press_pos = pos
                print(f"[DEBUG][{self.module_id}] 开始调整尺寸 orig=({w},{h}) @({pos.x()},{pos.y()})")
                event.accept(); return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if getattr(self, '_resizing', False):
            delta = event.pos() - self._press_pos
            new_w = max(100, self._orig_size[0] + delta.x())
            new_h = max(60, self._orig_size[1] + delta.y())
            self.setRect(0, 0, new_w, new_h)
            self._relayout_ports()
            self.refresh_visual()
            if self._corner_handle:
                self._corner_handle.setRect(new_w - self._corner_handle_size, new_h - self._corner_handle_size,
                                            self._corner_handle_size, self._corner_handle_size)
            print(f"[DEBUG][{self.module_id}] 调整中 new=({new_w},{new_h})")
            event.accept(); return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if getattr(self, '_resizing', False) and event.button() == Qt.MouseButton.LeftButton:
            self._resizing = False
            new_w = int(self.rect().width()); new_h = int(self.rect().height())
            if self.module_ref and isinstance(self.module_ref.config, dict):
                if 'width' in self.module_ref.config or 'height' in self.module_ref.config:
                    self.module_ref.configure({'width': new_w, 'height': new_h})
            self.refresh_visual()
            print(f"[DEBUG][{self.module_id}] 尺寸调整完成 ({new_w},{new_h})")
            event.accept(); return
        super().mouseReleaseEvent(event)

    def _relayout_ports(self):
        # 重新计算内容偏移（端口区高度可能受矩形宽度变化影响 label 定位不大）
        title_h = 20
        row_h = 18
        max_rows = max(len(self.input_points), len(self.output_points))
        self._content_offset = title_h + max_rows * row_h + 6
        # 输入端口位置更新
        for idx, point in enumerate(self.input_points):
            y = title_h + idx * row_h
            point.setPos(-6, y - 5)
            if idx < len(self.input_labels):
                self.input_labels[idx].setPos(2, y - 8)
            point.update_connections()
        # 输出端口位置更新
        for idx, point in enumerate(self.output_points):
            y = title_h + idx * row_h
            point.setPos(self.rect().width() - 4, y - 5)
            if idx < len(self.output_labels):
                self.output_labels[idx].setPos(self.rect().width()/2 - 10, y - 8)
            point.update_connections()
        # 内容项位置
        if self._thumb_item:
            self._thumb_item.setPos(8, self._content_offset)
        if getattr(self, '_text_item', None):
            self._text_item.setPos(8, self._content_offset)
        if self._corner_handle:
            self._corner_handle.setRect(
                self.rect().width() - self._corner_handle_size,
                self.rect().height() - self._corner_handle_size,
                self._corner_handle_size,
                self._corner_handle_size
            )
        if self._is_oknok_viewer and self._oknok_rect:
            content_offset = getattr(self, '_content_offset', 40)
            inner_w = max(60, self.rect().width() - 16)
            inner_h = max(34, self.rect().height() - content_offset - 8)
            self._oknok_rect.setRect(8, content_offset, inner_w, inner_h)
            if self._oknok_text:
                try:
                    b = self._oknok_text.boundingRect()
                    tx = 8 + (inner_w - b.width())/2
                    ty = content_offset + (inner_h - b.height())/2 - 2
                    self._oknok_text.setPos(tx, ty)
                except Exception:
                    pass

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            for p in self.input_points + self.output_points:
                p.update_connections()
        return super().itemChange(change, value)

class ConnectionPoint(QGraphicsRectItem):
    def __init__(self, parent_item, point_type, x, y, port_name, canvas=None, size=10):
        super().__init__(0, 0, size, size, parent_item)
        self.parent_item = parent_item
        self.point_type = point_type
        self.port_name = port_name
        self.canvas = canvas
        self.connections = []
        self.setPos(x, y)
        self.setBrush(QBrush(QColor(240,210,0) if point_type=='input' else QColor(0,170,255)))
        self.setPen(QPen(QColor(120,120,0) if point_type=='input' else QColor(0,120,200),1))
        self.setToolTip(f"{parent_item.module_type}:{port_name} ({'输入' if point_type=='input' else '输出'})")
        self.setAcceptHoverEvents(True)

    def hoverEnterEvent(self, event):
        self.setBrush(QBrush(QColor(255,240,0) if self.point_type=='input' else QColor(0,200,255)))
        super().hoverEnterEvent(event)
    def hoverLeaveEvent(self, event):
        self.setBrush(QBrush(QColor(240,210,0) if self.point_type=='input' else QColor(0,170,255)))
        super().hoverLeaveEvent(event)
    def mousePressEvent(self, event):
        if self.point_type=='output' and event.button()==Qt.MouseButton.LeftButton and self.canvas:
            self.canvas.begin_temp_connection(self)
        super().mousePressEvent(event)
    def mouseReleaseEvent(self, event):
        if self.point_type=='input' and event.button()==Qt.MouseButton.LeftButton and self.canvas and self.canvas.temp_connection_start:
            self.canvas.finalize_temp_connection(self)
        super().mouseReleaseEvent(event)
    def update_connections(self):
        for c in self.connections:
            c.update_line()

class EnhancedFlowCanvas(QGraphicsView):
    module_selected = pyqtSignal(object)
    module_added = pyqtSignal(str)
    connection_added = pyqtSignal(dict)
    connection_removed = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.scene = QGraphicsScene()
        self.setScene(self.scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setInteractive(True)
        # 扩大画布尺寸以支持更大流程
        self.scene.setSceneRect(0,0,4000,3000)
        # 缩放/调整锚点，使缩放以鼠标位置为中心
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        # 分组ID序号
        self._group_seq = 1
        self.setAcceptDrops(True)
        self.modules: List[ModuleItem] = []
        self.connections = []  # (line, start_point, end_point)
        self.temp_connection_start = None
        self.temp_line = None
        self.scene.selectionChanged.connect(self._on_selection_changed)
        # 剪贴板与历史
        self._clipboard = []
        self._history: List[Dict[str, Any]] = []
        self._history_index = -1
        self._suppress_history = False  # 在导入/恢复时抑制记录
        self._record_history()
        # 快捷键移除（交由 MainWindow 统一管理，避免 QAction 冲突）
        # 网格设置
        self.show_grid = True
        self.grid_small = 20
        self.grid_big = 100
        # 右键平移参数
        self._pan_active = False
        self._pan_last_pos = None  # type: ignore
        self._pan_moved = False
        self._pan_threshold = 4  # 像素阈值：超过认为是拖拽，不弹菜单
        # 执行高亮原始样式缓存 {module_id: (brush, pen)}
        self._exec_highlight_original: Dict[str, tuple] = {}
        # 图片展示模块定时器刷新（避免依赖结果回调）
        self._viewer_timer = QTimer(self)
        self._viewer_timer.setInterval(200)
        self._viewer_timer.timeout.connect(self._refresh_image_viewers)
        self._viewer_timer.start()

    def add_module(self, module_type: str):
        center = self.mapToScene(self.viewport().rect().center())
        self.add_module_at(module_type, QPointF(center.x()-70, center.y()-40))

    def add_module_at(self, module_type: str, pos: QPointF):
        from app.pipeline.module_registry import get_module_class
        module_ref = None
        cls = get_module_class(module_type)
        if cls:
            try:
                module_ref = cls(name=module_type)
            except Exception as e:
                print(f"创建模块实例失败: {module_type}: {e}")
        input_ports = list(module_ref.input_ports.keys()) if module_ref else None
        output_ports = list(module_ref.output_ports.keys()) if module_ref else None
        item = ModuleItem(module_type, pos.x(), pos.y(), canvas=self,
                          module_ref=module_ref, input_ports=input_ports, output_ports=output_ports)
        self.scene.addItem(item)
        self.modules.append(item)
        self.module_added.emit(module_type)
        self._ensure_scene_margin()
        if not self._suppress_history:
            self._record_history()

    def clear(self):
        self.scene.clear()
        self.modules.clear()
        self.connections.clear()
        self.temp_connection_start = None
        self.temp_line = None
        self._record_history()

    # ---------- 网格绘制 ----------
    def toggle_grid(self, show: bool | None = None):
        """开关网格显示"""
        if show is None:
            self.show_grid = not self.show_grid
        else:
            self.show_grid = bool(show)
        self.viewport().update()

    def drawBackground(self, painter: QPainter, rect: QRectF):
        super().drawBackground(painter, rect)
        if not self.show_grid:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        # 计算可见区域的网格范围
        left = int(rect.left()) - (int(rect.left()) % self.grid_small) - self.grid_small
        top = int(rect.top()) - (int(rect.top()) % self.grid_small) - self.grid_small
        right = int(rect.right()) + self.grid_small
        bottom = int(rect.bottom()) + self.grid_small
        # 小网格线
        pen_small = QPen(QColor(230,230,230))
        pen_small.setWidth(0)
        painter.setPen(pen_small)
        x = left
        while x <= right:
            painter.drawLine(x, top, x, bottom)
            x += self.grid_small
        y = top
        while y <= bottom:
            painter.drawLine(left, y, right, y)
            y += self.grid_small
        # 大网格线
        pen_big = QPen(QColor(200,200,200))
        pen_big.setWidth(0)
        painter.setPen(pen_big)
        x = left
        while x <= right:
            if x % self.grid_big == 0:
                painter.drawLine(x, top, x, bottom)
            x += self.grid_small
        y = top
        while y <= bottom:
            if y % self.grid_big == 0:
                painter.drawLine(left, y, right, y)
            y += self.grid_small
        painter.restore()

    def _on_selection_changed(self):
        try:
            sel = self.scene.selectedItems()
        except RuntimeError:
            return
        if sel and isinstance(sel[0], ModuleItem):
            self.module_selected.emit(sel[0])

    # Context menu
    def contextMenuEvent(self, event):
        if self._pan_moved:  # 刚拖拽过不弹菜单
            return
        from app.pipeline.module_registry import list_registered_modules, get_module_class
        from app.pipeline.base_module import ModuleType
        menu = QMenu(self)
        groups = {'输入': [], '处理': [], '输出': [], '自定义': []}
        for name in list_registered_modules():
            cls = get_module_class(name)
            try:
                mtype = cls(name=name).module_type if cls else ModuleType.CUSTOM
            except Exception:
                mtype = ModuleType.CUSTOM
            if mtype in [ModuleType.CAMERA, ModuleType.TRIGGER]:
                groups['输入'].append(name)
            elif mtype == ModuleType.MODEL:
                groups['处理'].append(name)
            elif mtype == ModuleType.POSTPROCESS:
                groups['输出'].append(name)
            else:
                groups['自定义'].append(name)
        for g, items in groups.items():
            if not items:
                continue
            sub = menu.addMenu(g)
            for it in sorted(items):
                act = QAction(it, self)
                act.triggered.connect(lambda checked, t=it: self.add_module(t))
                sub.addAction(act)
        menu.addSeparator()
        copy_act = QAction("复制", self); copy_act.triggered.connect(self.copy_selection)
        paste_act = QAction("粘贴", self); paste_act.triggered.connect(self.paste_selection)
        del_act = QAction("删除", self); del_act.triggered.connect(self.delete_selection)
        undo_act = QAction("撤销", self); undo_act.triggered.connect(self.undo)
        redo_act = QAction("重做", self); redo_act.triggered.connect(self.redo)
        menu.addActions([copy_act, paste_act, del_act, undo_act, redo_act])
        menu.addSeparator()
        clear_act = QAction("清空画布", self); clear_act.triggered.connect(self.clear)
        menu.addAction(clear_act)
        # 分组相关：若选择了多个模块，提供创建分组
        sel_modules = [it for it in self.scene.selectedItems() if isinstance(it, ModuleItem)]
        if len(sel_modules) >= 2:
            group_act = QAction("创建分组", self)
            group_act.triggered.connect(lambda: self._create_group_from_selection(sel_modules))
            menu.addAction(group_act)
        # 分组单选操作：重命名 / 删除
        sel_groups = [it for it in self.scene.selectedItems() if isinstance(it, GroupBoxItem)]
        if len(sel_groups) == 1:
            g = sel_groups[0]
            rename_act = QAction("重命名分组", self); rename_act.triggered.connect(lambda: self._rename_group(g))
            del_act = QAction("删除分组", self); del_act.triggered.connect(lambda: self._delete_group(g))
            menu.addAction(rename_act); menu.addAction(del_act)
        menu.exec(event.globalPos())

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.2 if event.angleDelta().y() > 0 else (1/1.2)
            self.scale(factor, factor)
            self._ensure_scene_margin()
        else:
            super().wheelEvent(event)

    # ---------- Drag & Drop from ModuleToolbox ----------
    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat('application/x-fahai-module') or event.mimeData().text():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat('application/x-fahai-module') or event.mimeData().text():
            event.acceptProposedAction()
            if event.mimeData().hasFormat('application/x-fahai-ports'):
                try:
                    ports_raw = bytes(event.mimeData().data('application/x-fahai-ports')).decode('utf-8')
                    ins, outs = ports_raw.split('|') if '|' in ports_raw else (ports_raw, '')
                    tip = f"输入: {ins or '-'}\n输出: {outs or '-'}"
                    QToolTip.showText(event.screenPos(), tip)
                except Exception:
                    pass
        else:
            event.ignore()

    def dropEvent(self, event):
        module_type = None
        if event.mimeData().hasFormat('application/x-fahai-module'):
            module_type = bytes(event.mimeData().data('application/x-fahai-module')).decode('utf-8')
        else:
            module_type = event.mimeData().text()
        if module_type:
            scene_pos = self.mapToScene(event.position().toPoint())
            self.add_module_at(module_type, QPointF(scene_pos.x()-70, scene_pos.y()-40))
            event.acceptProposedAction()
            QToolTip.hideText()
        else:
            event.ignore()
            QToolTip.hideText()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete:
            for it in self.scene.selectedItems():
                if isinstance(it, ModuleItem):
                    self.scene.removeItem(it)
                    if it in self.modules:
                        self.modules.remove(it)
            self._cleanup_orphan_connections()
            self._record_history()
        else:
            super().keyPressEvent(event)

    # ----- Connection drag logic -----
    def begin_temp_connection(self, start_point):
        self.temp_connection_start = start_point
        self.temp_line = BetterConnectionLine(start_point, start_point, canvas=self, temp=True)
        self.scene.addItem(self.temp_line)
        # 高亮兼容输入端口
        self._highlight_compatible_inputs(start_point)

    def mouseMoveEvent(self, event):
        # 右键平移优先
        if self._pan_active and self._pan_last_pos is not None:
            delta = event.pos() - self._pan_last_pos
            if delta.manhattanLength() > 0:
                if delta.manhattanLength() >= self._pan_threshold:
                    self._pan_moved = True
                hsb = self.horizontalScrollBar(); vsb = self.verticalScrollBar()
                # 若滚动范围为零（缩放导致场景全在视口内），使用视图矩阵平移
                if (hsb.maximum() - hsb.minimum()) == 0 and (vsb.maximum() - vsb.minimum()) == 0:
                    self.translate(delta.x(), delta.y())
                    self._ensure_scene_margin()
                else:
                    hsb.setValue(hsb.value() - delta.x())
                    vsb.setValue(vsb.value() - delta.y())
                self._pan_last_pos = event.pos()
            super().mouseMoveEvent(event)
            return
        if self.temp_line and self.temp_connection_start:
            pos = self.mapToScene(event.pos())
            self.temp_line.set_temp_cursor(pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton and self._pan_active:
            self._pan_active = False
            self._pan_last_pos = None
            if self._pan_moved:
                self._pan_moved = False
                event.accept()
                return
        if self.temp_connection_start and self.temp_line:
            scene_pos = self.mapToScene(event.pos())
            items = self.scene.items(scene_pos)
            target_point = None
            for it in items:
                if isinstance(it, ConnectionPoint) and it.point_type == 'input':
                    target_point = it
                    break
            if target_point:
                self.finalize_temp_connection(target_point)
            else:
                self.cancel_temp_connection()
        super().mouseReleaseEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self._pan_active = True
            self._pan_last_pos = event.pos()
            self._pan_moved = False
            event.accept()
            return
        super().mousePressEvent(event)

    def finalize_temp_connection(self, end_point):
        if not self.temp_connection_start or not self.temp_line:
            return
        if end_point.parent_item == self.temp_connection_start.parent_item:
            self.cancel_temp_connection()
            return
        self.temp_line.setEndPoint(end_point)
        self.connections.append((self.temp_line, self.temp_connection_start, end_point))
        payload = {
            'source_module': self.temp_connection_start.parent_item.module_id,
            'source_port': self.temp_connection_start.port_name,
            'target_module': end_point.parent_item.module_id,
            'target_port': end_point.port_name
        }
        self.connection_added.emit(payload)
        self.temp_connection_start = None
        self.temp_line = None
        self._clear_input_highlight()
        self._record_history()

    def cancel_temp_connection(self):
        if self.temp_line:
            self.scene.removeItem(self.temp_line)
        self.temp_connection_start = None
        self.temp_line = None
        self._clear_input_highlight()

    def _remove_connection(self, line_item):
        for idx, (line, sp, ep) in enumerate(self.connections):
            if line is line_item:
                payload = {
                    'source_module': sp.parent_item.module_id,
                    'source_port': sp.port_name,
                    'target_module': ep.parent_item.module_id,
                    'target_port': ep.port_name
                }
                sp.connections.remove(line)
                ep.connections.remove(line)
                self.scene.removeItem(line)
                del self.connections[idx]
                self.connection_removed.emit(payload)
                break
        self._record_history()

    def _cleanup_orphan_connections(self):
        to_remove = []
        for line, sp, ep in self.connections:
            if sp.parent_item not in self.modules or ep.parent_item not in self.modules:
                to_remove.append(line)
        for line in to_remove:
            self._remove_connection(line)

    def export_structure(self) -> Dict[str, Any]:
        modules = []
        for m in self.modules:
            modules.append({
                'module_id': m.module_id,
                'module_type': m.module_type,
                'x': m.scenePos().x(),
                'y': m.scenePos().y(),
                'width': m.rect().width(),
                'height': m.rect().height(),
                'inputs': m.input_ports_def,
                'outputs': m.output_ports_def,
                'config': (m.module_ref.config.copy() if m.module_ref else {}),
                'state': self._collect_module_state(m)
            })
        links = []
        for line, sp, ep in self.connections:
            links.append({
                'source_module': sp.parent_item.module_id,
                'source_port': sp.port_name,
                'target_module': ep.parent_item.module_id,
                'target_port': ep.port_name
            })
        groups = []
        for g in self.list_groups():
            rect = g.rect()
            groups.append({
                'group_id': getattr(g,'group_id',''),
                'title': g.title.toPlainText() if hasattr(g,'title') else '分组',
                'x': rect.x(), 'y': rect.y(), 'width': rect.width(), 'height': rect.height(),
                'members': g.members
            })
        return {'modules': modules, 'connections': links, 'groups': groups}

    # ---------- 分组支持 ----------
    def _create_group_from_selection(self, items):
        # 计算边界
        min_x = min([it.scenePos().x() for it in items])
        min_y = min([it.scenePos().y() for it in items])
        max_x = max([it.scenePos().x() + it.rect().width() for it in items])
        max_y = max([it.scenePos().y() + it.rect().height() for it in items])
        margin = 20
        group_rect = QRectF(min_x - margin, min_y - margin, (max_x - min_x) + 2*margin, (max_y - min_y) + 2*margin)
        gid = f"group_{self._group_seq}"; self._group_seq += 1
        grp = GroupBoxItem(group_rect.x(), group_rect.y(), group_rect.width(), group_rect.height(), canvas=self, members=[it.module_id for it in items], group_id=gid)
        self.scene.addItem(grp)
        grp.setZValue(-5)  # 在模块后面
        # 取消选择模块，选择分组框方便拖动
        for it in items:
            it.setSelected(False)
        grp.setSelected(True)

    def list_groups(self):
        return [it for it in self.scene.items() if isinstance(it, GroupBoxItem)]

    def _rename_group(self, group: 'GroupBoxItem'):
        from PyQt6.QtWidgets import QInputDialog
        old = group.title.toPlainText() if group.title else '分组'
        new, ok = QInputDialog.getText(self, '重命名分组', '名称:', text=old)
        if ok and new.strip():
            group.title.setPlainText(new.strip())

    def _delete_group(self, group: 'GroupBoxItem'):
        try:
            self.scene.removeItem(group)
        except Exception:
            pass

    def _ensure_scene_margin(self, margin: int = 400):
        items = [m for m in self.modules] + self.list_groups()
        if not items:
            return
        min_x = min([it.scenePos().x() for it in items])
        min_y = min([it.scenePos().y() for it in items])
        max_x = max([it.scenePos().x() + (it.rect().width() if hasattr(it,'rect') else 0) for it in items])
        max_y = max([it.scenePos().y() + (it.rect().height() if hasattr(it,'rect') else 0) for it in items])
        r = self.scene.sceneRect()
        new_left = min(r.left(), min_x - margin)
        new_top = min(r.top(), min_y - margin)
        new_right = max(r.right(), max_x + margin)
        new_bottom = max(r.bottom(), max_y + margin)
        if (new_left, new_top, new_right, new_bottom) != (r.left(), r.top(), r.right(), r.bottom()):
            self.scene.setSceneRect(new_left, new_top, new_right - new_left, new_bottom - new_top)


    def import_structure(self, data: Dict[str, Any]):
        # 重建（记录历史前不再次截断）
        self.scene.clear()
        self.modules.clear()
        self.connections.clear()
        id_map = {}
        self._suppress_history = True
        for m in data.get('modules', []):
            mtype = m.get('module_type')
            pos = QPointF(m.get('x',0), m.get('y',0))
            self.add_module_at(mtype, pos)
            item = self.modules[-1]
            item.module_id = m.get('module_id', item.module_id)
            if item.module_ref:
                item.module_ref.module_id = item.module_id
            # 恢复尺寸
            w = m.get('width'); h = m.get('height')
            try:
                if isinstance(w, (int,float)) and isinstance(h, (int,float)) and w>40 and h>40:
                    item.setRect(0,0,float(w),float(h))
                    item._relayout_ports()
            except Exception:
                pass
            id_map[item.module_id] = item
        for c in data.get('connections', []):
            sid = c.get('source_module'); spt = c.get('source_port')
            tid = c.get('target_module'); tpt = c.get('target_port')
            s_item = id_map.get(sid); t_item = id_map.get(tid)
            if not s_item or not t_item:
                continue
            sp = next((p for p in s_item.output_points if p.port_name == spt), None)
            tp = next((p for p in t_item.input_points if p.port_name == tpt), None)
            if not sp or not tp:
                continue
            line = BetterConnectionLine(sp, tp, canvas=self, temp=False)
            self.scene.addItem(line)
            sp.connections.append(line)
            tp.connections.append(line)
            self.connections.append((line, sp, tp))
        self._suppress_history = False
        self._record_history()
        # 分组重建
        for g in data.get('groups', []):
            try:
                grp = GroupBoxItem(g.get('x',0), g.get('y',0), g.get('width',200), g.get('height',120), canvas=self, members=g.get('members', []), group_id=g.get('group_id',''))
                if 'title' in g and grp.title:
                    grp.title.setPlainText(g['title'])
                self.scene.addItem(grp)
                grp.setZValue(-5)
            except Exception:
                pass

    # ---------- 剪贴板与历史 ----------
    def copy_selection(self):
        sel = [it for it in self.scene.selectedItems() if isinstance(it, ModuleItem)]
        self._clipboard = []
        for m in sel:
            self._clipboard.append({'module_type': m.module_type,'x': m.scenePos().x(),'y': m.scenePos().y()})

    def paste_selection(self):
        if not self._clipboard:
            return
        for m in self._clipboard:
            self.add_module_at(m['module_type'], QPointF(m['x']+30, m['y']+30))
        self._record_history()

    def duplicate_selection(self):
        """复制并立即粘贴选中模块，偏移更小便于连续操作"""
        sel = [it for it in self.scene.selectedItems() if isinstance(it, ModuleItem)]
        if not sel:
            return
        temp_clip = []
        for m in sel:
            temp_clip.append({'module_type': m.module_type,'x': m.scenePos().x(),'y': m.scenePos().y()})
        for m in temp_clip:
            self.add_module_at(m['module_type'], QPointF(m['x']+20, m['y']+20))
        self._record_history()

    def delete_selection(self):
        removed = False
        for it in self.scene.selectedItems():
            if isinstance(it, ModuleItem):
                self.scene.removeItem(it)
                if it in self.modules:
                    self.modules.remove(it)
                removed = True
        if removed:
            self._cleanup_orphan_connections()
            self._record_history()

    def _record_history(self):
        snapshot = self.export_structure()
        if self._history_index < len(self._history)-1:
            self._history = self._history[:self._history_index+1]
        self._history.append(snapshot)
        self._history_index = len(self._history)-1

    def undo(self):
        if self._history_index > 0:
            self._history_index -= 1
            self._restore_snapshot(self._history[self._history_index])

    def redo(self):
        if self._history_index + 1 < len(self._history):
            self._history_index += 1
            self._restore_snapshot(self._history[self._history_index])

    def _restore_snapshot(self, data: Dict[str, Any]):
        self.scene.clear()
        self.modules.clear()
        self.connections.clear()
        id_map = {}
        self._suppress_history = True
        for m in data.get('modules', []):
            mtype = m.get('module_type')
            pos = QPointF(m.get('x',0), m.get('y',0))
            self.add_module_at(mtype, pos)
            item = self.modules[-1]
            item.module_id = m.get('module_id', item.module_id)
            if item.module_ref:
                item.module_ref.module_id = item.module_id
            w = m.get('width'); h = m.get('height')
            try:
                if isinstance(w, (int,float)) and isinstance(h, (int,float)) and w>40 and h>40:
                    item.setRect(0,0,float(w),float(h))
                    item._relayout_ports()
            except Exception:
                pass
            id_map[item.module_id] = item
        for c in data.get('connections', []):
            sid = c.get('source_module'); spt = c.get('source_port')
            tid = c.get('target_module'); tpt = c.get('target_port')
            s_item = id_map.get(sid); t_item = id_map.get(tid)
            if not s_item or not t_item:
                continue
            sp = next((p for p in s_item.output_points if p.port_name == spt), None)
            tp = next((p for p in t_item.input_points if p.port_name == tpt), None)
            if not sp or not tp:
                continue
            line = BetterConnectionLine(sp, tp, canvas=self, temp=False)
            self.scene.addItem(line)
            sp.connections.append(line)
            tp.connections.append(line)
            self.connections.append((line, sp, tp))
        self._suppress_history = False

    def _collect_module_state(self, item: ModuleItem) -> Dict[str, Any]:
        """采集模块的自定义状态（简单策略：抓取常见自定义属性）。"""
        if not item.module_ref:
            return {}
        ref = item.module_ref
        state = {}
        # 针对已知模块做特化
        if hasattr(ref, 'text_value'):
            state['text_value'] = ref.text_value
        if hasattr(ref, 'last_text'):
            state['last_text'] = ref.last_text
        # 可扩展：遍历 __dict__ 过滤基本类型
        return state

    def save_to_file(self, path: str) -> bool:
        data = self.export_structure()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存流程失败: {e}")
            return False

    def load_from_file(self, path: str) -> bool:
        if not os.path.exists(path):
            print(f"文件不存在: {path}")
            return False
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"读取流程失败: {e}")
            return False
        self.clear()
        id_map = {}
        # 重建模块
        for m in data.get('modules', []):
            mtype = m.get('module_type')
            cls = get_module_class(mtype)
            module_ref = None
            if cls:
                try:
                    module_ref = cls(name=mtype)
                    # 应用配置
                    cfg = m.get('config') or {}
                    if cfg:
                        module_ref.configure(cfg)
                    # 应用状态
                    state = m.get('state') or {}
                    if 'text_value' in state and hasattr(module_ref, 'text_value'):
                        module_ref.text_value = state['text_value']
                    if 'last_text' in state and hasattr(module_ref, 'last_text'):
                        module_ref.last_text = state['last_text']
                except Exception as e:
                    print(f"实例化模块失败 {mtype}: {e}")
            # 恢复尺寸（若存在则传入构造函数，避免初始化后再二次布局）
            w = m.get('width', 140)
            h = m.get('height', 80)
            item = ModuleItem(mtype, m.get('x',0), m.get('y',0), width=w, height=h, canvas=self,
                              module_ref=module_ref,
                              input_ports=m.get('inputs'), output_ports=m.get('outputs'))
            # 若尺寸异常（过小或类型不对）回退到默认并重新布局
            try:
                if not isinstance(w, (int,float)) or not isinstance(h, (int,float)) or w < 40 or h < 40:
                    item.setRect(0,0,140,80)
                    item._relayout_ports()
            except Exception:
                pass
            # 强制使用保存的ID（避免冲突时追加后缀）
            saved_id = m.get('module_id')
            item.module_id = saved_id
            if module_ref:
                module_ref.module_id = saved_id
            self.scene.addItem(item)
            self.modules.append(item)
            id_map[saved_id] = item
        # 重建连接
        for c in data.get('connections', []):
            sid = c.get('source_module'); spt = c.get('source_port')
            tid = c.get('target_module'); tpt = c.get('target_port')
            s_item = id_map.get(sid)
            t_item = id_map.get(tid)
            if not s_item or not t_item:
                continue
            # 找到端点对象
            sp = next((p for p in s_item.output_points if p.port_name == spt), None)
            tp = next((p for p in t_item.input_points if p.port_name == tpt), None)
            if not sp or not tp:
                continue
            line = BetterConnectionLine(sp, tp, canvas=self, temp=False)
            self.scene.addItem(line)
            sp.connections.append(line)
            tp.connections.append(line)
            self.connections.append((line, sp, tp))
        # 重建分组
        for g in data.get('groups', []):
            try:
                grp = GroupBoxItem(g.get('x',0), g.get('y',0), g.get('width',200), g.get('height',120), canvas=self, members=g.get('members', []), group_id=g.get('group_id',''))
                if 'title' in g and grp.title:
                    grp.title.setPlainText(g['title'])
                self.scene.addItem(grp); grp.setZValue(-5)
            except Exception:
                pass
        return True

    # ---------- GUI → Executor Bridge ----------
    def build_executor(self, executor: PipelineExecutor) -> PipelineExecutor:
        """根据当前画布状态将模块与连接写入执行器。
        1. 确保每个 ModuleItem 有实际 module_ref，没有则实例化。
        2. 使用 module_ref.module_id 保持 ID 一致。
        3. 建立连接关系。
        Returns: 传入的 executor（便于链式使用）。"""
        id_collision_guard = set()
        for item in self.modules:
            if item.module_ref is None:
                cls = get_module_class(item.module_type)
                if cls:
                    try:
                        item.module_ref = cls(name=item.module_type)
                        item.module_id = item.module_ref.module_id
                    except Exception as e:
                        print(f"实例化模块失败: {item.module_type}: {e}")
                else:
                    print(f"未找到模块类: {item.module_type}")
            # ID 冲突处理
            original_id = item.module_ref.module_id if item.module_ref else item.module_id
            final_id = original_id
            suffix = 1
            while final_id in id_collision_guard or final_id in executor.nodes:
                final_id = f"{original_id}_{suffix}"
                suffix += 1
            if final_id != original_id and item.module_ref:
                item.module_ref.module_id = final_id
            item.module_id = final_id
            id_collision_guard.add(final_id)
            if item.module_ref:
                executor.add_module(item.module_ref, node_id=final_id)
        # 添加连接
        for line, sp, ep in self.connections:
            src_item = sp.parent_item
            dst_item = ep.parent_item
            if not src_item.module_ref or not dst_item.module_ref:
                continue
            try:
                executor.connect_modules(src_item.module_ref.module_id, sp.port_name,
                                         dst_item.module_ref.module_id, ep.port_name)
            except Exception as e:
                print(f"连接创建失败: {src_item.module_type}.{sp.port_name} -> {dst_item.module_type}.{ep.port_name}: {e}")
        return executor

    # ---------- 端口兼容高亮辅助 ----------
    def _highlight_compatible_inputs(self, start_point: 'ConnectionPoint'):
        mref = start_point.parent_item.module_ref
        if not mref:
            return
        out_def = mref.output_ports.get(start_point.port_name)
        out_type = out_def.get('type') if out_def else None
        self._highlighted_inputs = []
        for item in self.modules:
            if item is start_point.parent_item:
                continue
            pref = item.module_ref
            if not pref:
                continue
            for p in item.input_points:
                idef = pref.input_ports.get(p.port_name)
                if not idef:
                    continue
                in_type = idef.get('type')
                required = idef.get('required')
                compatible = (out_type is None) or (out_type == in_type)
                if compatible:
                    original_brush = p.brush()
                    p.setBrush(QBrush(QColor(60,255,120)))
                    if required:
                        p.setPen(QPen(QColor(200,40,40),2))
                    self._highlighted_inputs.append((p, original_brush))

    def _clear_input_highlight(self):
        if not hasattr(self, '_highlighted_inputs'):
            return
        for p, orig in self._highlighted_inputs:
            p.setBrush(orig)
            if p.point_type == 'input':
                p.setPen(QPen(QColor(120,120,0),1))
        self._highlighted_inputs.clear()

    # ---------- 执行过程模块高亮 ----------
    def highlight_execution(self, module_id: str, phase: str):
        """在执行过程中高亮指定模块。
        phase: 'start' 在开始时变为亮黄色边框；'end' 闪烁绿色后恢复。
        并行模式下可能快速交错调用，保持独立缓存。
        """
        item = next((m for m in self.modules if m.module_id == module_id), None)
        if not item:
            return
        # 开始阶段：保存原始样式并设置高亮
        if phase == 'start':
            if module_id not in self._exec_highlight_original:
                self._exec_highlight_original[module_id] = (item.brush(), item.pen())
            item.setBrush(QBrush(QColor(255, 240, 180)))
            item.setPen(QPen(QColor(255, 180, 0), 3))
        elif phase == 'end':
            # 如果未缓存原始样式，忽略恢复
            original = self._exec_highlight_original.get(module_id)
            if not original:
                return
            # 闪烁绿色再恢复
            item.setBrush(QBrush(QColor(190, 255, 190)))
            item.setPen(QPen(QColor(0, 180, 0), 3))
            def _restore():
                orig_brush, orig_pen = self._exec_highlight_original.get(module_id, (None, None))
                if orig_brush and orig_pen and item in self.modules:
                    item.setBrush(orig_brush)
                    item.setPen(orig_pen)
                # 清除缓存
                if module_id in self._exec_highlight_original:
                    del self._exec_highlight_original[module_id]
            QTimer.singleShot(220, _restore)

    def _refresh_image_viewers(self):
        for m in self.modules:
            if hasattr(m, 'refresh_visual'):
                try:
                    m.refresh_visual()
                except Exception:
                    pass


class GroupBoxItem(QGraphicsRectItem):
    """分组框：用于视觉分组多个模块，支持拖动、重命名、删除与持久化。
    修复：原实现错误地将 (x,y) 作为局部矩形坐标，导致重载后位置与尺寸错乱。
    现在：局部 rect 固定从 (0,0) 开始，(x,y) 通过 setPos 放入场景。
    group_id: 持久化唯一标识
    members: 模块ID列表
    """
    def __init__(self, x, y, w, h, canvas: 'EnhancedFlowCanvas', members: List[str], group_id: str = ""):
        super().__init__(0, 0, w, h)
        self.setPos(x, y)
        self.canvas = canvas
        self.members = members[:]
        self.group_id = group_id or f"group_{id(self)}"
        self.setBrush(QBrush(QColor(255,255,210,40)))
        self.setPen(QPen(QColor(200,170,0), 2, Qt.PenStyle.DashLine))
        self.setZValue(-5)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.title = QGraphicsTextItem("分组", self)
        self.title.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.title.setDefaultTextColor(QColor(120,90,0))
        self.title.setPos(6, 4)  # 固定距离左上角，避免因重载坐标偏移

    def paint(self, painter: QPainter, option, widget=None):
        # 动态高亮：选中时加粗边框并改变颜色
        pen = QPen(QColor(200,170,0) if not self.isSelected() else QColor(255,140,0))
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setWidth(2 if not self.isSelected() else 3)
        painter.setPen(pen)
        painter.setBrush(QBrush(QColor(255,255,210,40)))
        painter.drawRect(self.rect())  # rect 从 (0,0) 开始
        super().paint(painter, option, widget)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and hasattr(self, 'canvas'):
            try:
                old_pos = self.scenePos()
                new_pos = value
                delta = new_pos - old_pos
                for m in self.canvas.modules:
                    if m.module_id in self.members:
                        m.setPos(m.scenePos() + delta)
                        for p in m.input_points + m.output_points:
                            p.update_connections()
            except Exception:
                pass
        return super().itemChange(change, value)
