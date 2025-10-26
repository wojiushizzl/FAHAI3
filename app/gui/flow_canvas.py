#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
流程画布组件
提供可视化的流程设计画布，支持拖拽、连线等操作
"""

from PyQt6.QtWidgets import (QGraphicsView, QGraphicsScene, QGraphicsItem,
                             QGraphicsRectItem, QGraphicsTextItem, QMenu, QGraphicsPixmapItem)
from PyQt6.QtCore import QTimer
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal
from typing import Dict, Any, List
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QAction


class ModuleItem(QGraphicsRectItem):
    """流程模块图形项，支持多端口可视化和动态端口反射"""

    def __init__(self, module_type: str, x=0, y=0, width=140, height=80, canvas=None,
                 module_ref=None, input_ports: List[str] = None, output_ports: List[str] = None):
        super().__init__(0, 0, width, height)
        self.canvas = canvas
        self.module_type = module_type  # 显示名称
        self.module_ref = module_ref    # 实际 BaseModule 实例（可选）
        self.module_id = module_ref.module_id if module_ref else f"{module_type}_{id(self)}"
        self.setPos(x, y)

        # 外观
        self.setRect(0, 0, width, height)
        self.setBrush(QBrush(QColor(200, 220, 255)))
        self.setPen(QPen(QColor(100, 150, 200), 2))

        # 交互标志
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        # 允许 hover 事件用于尺寸调整
        self.setAcceptHoverEvents(True)

        # 标题
        self.text_item = QGraphicsTextItem(module_type, self)
        self.text_item.setFont(QFont("Arial", 10))
        self.text_item.setPos(10, 8)

        # 图片展示支持：如果是图片展示模块，添加缩略显示区域
        self._is_image_viewer = (module_type == "图片展示")
        self._thumb_item = None  # 缩略图 QGraphicsPixmapItem 实例
        if self._is_image_viewer:
            self._thumb_item = QGraphicsPixmapItem(self)
            self._thumb_item.setPos(8, 24)
            # 初始占位背景
            self._update_thumbnail(None)

        # ---- 可调整大小支持 ----
        self._resizing = False
        self._resize_margin = 14  # 边缘感应区域扩大，提升易用性
        self._orig_size = (width, height)
        self.input_labels = []  # 端口标签引用，便于重定位
        self.output_labels = []

        # 右下角拖拽手柄（视觉提示）
        self._corner_handle_size = 14
        self._corner_handle = QGraphicsRectItem(
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
        # 让事件传递给父项，避免遮挡 hover 区域
        self._corner_handle.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._corner_handle.setAcceptHoverEvents(False)

        # 端口集合（反射或默认）
        if input_ports is None:
            input_ports = list(module_ref.input_ports.keys()) if module_ref else ["in"]
        if output_ports is None:
            output_ports = list(module_ref.output_ports.keys()) if module_ref else ["out"]
        self.input_ports_def = input_ports
        self.output_ports_def = output_ports
        self.input_points = []
        self.output_points = []
        self._create_connection_points()
        
    def _create_connection_points(self):
        """根据端口定义创建连接点 (初始调用)"""
        # 输入端口排列（左侧竖直）
        for idx, port_name in enumerate(self.input_ports_def):
            y = 20 + idx * 20
            point = ConnectionPoint(self, "input", -6, y - 5, port_name, canvas=self.canvas)
            self.input_points.append(point)
            label = QGraphicsTextItem(port_name, self)
            label.setFont(QFont("Arial", 8))
            label.setDefaultTextColor(QColor(50, 50, 50))
            label.setPos(2, y - 8)
            self.input_labels.append(label)
        # 输出端口排列（右侧竖直）
        for idx, port_name in enumerate(self.output_ports_def):
            y = 20 + idx * 20
            point = ConnectionPoint(self, "output", self.rect().width() - 4, y - 5, port_name, canvas=self.canvas)
            self.output_points.append(point)
            label = QGraphicsTextItem(port_name, self)
            label.setFont(QFont("Arial", 8))
            label.setDefaultTextColor(QColor(50, 50, 50))
            label.setPos(self.rect().width() / 2 - 10, y - 8)
            self.output_labels.append(label)
        
    def itemChange(self, change, value):
        """项目变化时的回调"""
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            # 更新连接线
            for point in self.input_points + self.output_points:
                point.update_connections()
        return super().itemChange(change, value)

    # ---- 缩略图刷新 ----
    def refresh_visual(self):
        """由外部调用（执行结果回调）刷新缩略图显示。"""
        if not self._is_image_viewer or not self.module_ref:
            return
        # 优先使用最新输出，其次使用模块内部 last_image 缓存
        img = self.module_ref.outputs.get("image")
        if img is None:
            img = getattr(self.module_ref, 'last_image', None)
        prev_has = getattr(self, '_prev_has_img', None)
        has_now = img is not None and hasattr(img, 'shape')
        if prev_has is None or prev_has != has_now:
            try:
                if not has_now:
                    print(f"[DEBUG][{self.module_id}] refresh_visual: 无图像")
                else:
                    print(f"[DEBUG][{self.module_id}] refresh_visual: shape={getattr(img,'shape',None)}, dtype={getattr(img,'dtype',None)}")
            except Exception as e:
                print(f"[DEBUG][{self.module_id}] refresh_visual: 打印信息异常: {e}")
            self._prev_has_img = has_now
        self._update_thumbnail(img)

    def _update_thumbnail(self, img):
        if not self._thumb_item:
            return
        from PyQt6.QtGui import QImage, QPixmap
        from PyQt6.QtCore import Qt
        # 读取配置尺寸
        w = int(self.module_ref.config.get("width", 160)) if self.module_ref else 160
        h = int(self.module_ref.config.get("height", 120)) if self.module_ref else 120
        # 动态调整外框高度以容纳缩略图
        base_h = 30 + h + 10
        if base_h > self.rect().height():
            self.setRect(0, 0, max(self.rect().width(), w + 20), base_h)
        if img is None or not hasattr(img, 'shape'):
            # 生成灰背景占位
            print(f"[DEBUG][{self.module_id}] _update_thumbnail: 使用占位图 w={w}, h={h}, img={type(img)}")
            placeholder = QImage(w, h, QImage.Format.Format_RGB32)
            placeholder.fill(QColor(230, 230, 230))
            self._thumb_item.setPixmap(QPixmap.fromImage(placeholder))
            return
        try:
            import numpy as np
            arr = img
            # 将单通道扩展为 RGB 方便显示
            if len(arr.shape) == 2:
                print(f"[DEBUG][{self.module_id}] _update_thumbnail: 单通道扩展 -> RGB")
                arr = np.stack([arr] * 3, axis=-1)
            elif arr.shape[2] == 4:  # RGBA 或 BGRA -> 丢 alpha
                print(f"[DEBUG][{self.module_id}] _update_thumbnail: 丢弃 alpha 通道")
                arr = arr[:, :, :3]
            # 颜色格式假设为 BGR -> 转换为 RGB 供 QImage 显示
            print(f"[DEBUG][{self.module_id}] _update_thumbnail: 原始 shape={arr.shape}, dtype={arr.dtype}")
            arr_rgb = arr[:, :, ::-1].copy()
            h0, w0 = arr_rgb.shape[:2]
            qimg = QImage(arr_rgb.data, w0, h0, w0 * 3, QImage.Format.Format_RGB888)
            pix = QPixmap.fromImage(qimg)
            # 缩放
            pix_scaled = pix.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self._thumb_item.setPixmap(pix_scaled)
            print(f"[DEBUG][{self.module_id}] _update_thumbnail: 更新成功 -> 显示尺寸 {w}x{h}")
        except Exception as e:
            print(f"[DEBUG][{self.module_id}] _update_thumbnail: 处理异常: {e}")
            placeholder = QImage(w, h, QImage.Format.Format_RGB32)
            placeholder.fill(QColor(200, 200, 200))
            self._thumb_item.setPixmap(QPixmap.fromImage(placeholder))

    def mouseDoubleClickEvent(self, event):
        """双击图片展示模块放大/还原尺寸。"""
        if self._is_image_viewer and self.module_ref:
            cur_w = int(self.module_ref.config.get("width", 160))
            cur_h = int(self.module_ref.config.get("height", 120))
            # 简单切换 160x120 <-> 320x240
            if cur_w <= 160:
                self.module_ref.configure({"width": 320, "height": 240})
            else:
                self.module_ref.configure({"width": 160, "height": 120})
            self.refresh_visual()
        super().mouseDoubleClickEvent(event)

    # ---------- 尺寸调整交互 ----------
    def hoverMoveEvent(self, event):
        pos = event.pos()
        w = self.rect().width(); h = self.rect().height()
        near_right = abs(pos.x() - w) <= self._resize_margin
        near_bottom = abs(pos.y() - h) <= self._resize_margin
        in_corner_handle = False
        if self._corner_handle:
            ch_rect = QRectF(
                self.rect().width() - self._corner_handle_size,
                self.rect().height() - self._corner_handle_size,
                self._corner_handle_size,
                self._corner_handle_size
            )
            in_corner_handle = ch_rect.contains(pos)
        if in_corner_handle:
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif near_right and near_bottom:
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
            pos = event.pos()
            w = self.rect().width(); h = self.rect().height()
            corner_hit = False
            if self._corner_handle:
                ch_rect = QRectF(
                    self.rect().width() - self._corner_handle_size,
                    self.rect().height() - self._corner_handle_size,
                    self._corner_handle_size,
                    self._corner_handle_size
                )
                corner_hit = ch_rect.contains(pos)
            if corner_hit or (abs(pos.x() - w) <= self._resize_margin) or (abs(pos.y() - h) <= self._resize_margin):
                self._resizing = True
                self._orig_size = (w, h)
                self._press_pos = pos
                print(f"[DEBUG][{self.module_id}] 开始尺寸调整: orig=({w},{h}), press=({pos.x()},{pos.y()})")
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing:
            delta = event.pos() - self._press_pos
            new_w = max(100, self._orig_size[0] + delta.x())
            new_h = max(60, self._orig_size[1] + delta.y())
            self.setRect(0, 0, new_w, new_h)
            self._relayout_ports()
            self.refresh_visual()
            if self._corner_handle:
                self._corner_handle.setRect(
                    new_w - self._corner_handle_size,
                    new_h - self._corner_handle_size,
                    self._corner_handle_size,
                    self._corner_handle_size
                )
            print(f"[DEBUG][{self.module_id}] 调整中 -> new=({new_w},{new_h})")
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing and event.button() == Qt.MouseButton.LeftButton:
            self._resizing = False
            # 将新尺寸写回模块配置（若存在宽高字段）便于后续保存/刷新
            new_w = int(self.rect().width())
            new_h = int(self.rect().height())
            if self.module_ref and isinstance(self.module_ref.config, dict):
                # 仅在存在 width/height 时更新（避免污染非相关模块配置）
                if 'width' in self.module_ref.config or 'height' in self.module_ref.config:
                    self.module_ref.configure({
                        'width': new_w if new_w > 0 else self.module_ref.config.get('width', new_w),
                        'height': new_h if new_h > 0 else self.module_ref.config.get('height', new_h)
                    })
            self.refresh_visual()
            print(f"[DEBUG][{self.module_id}] 尺寸调整完成 -> ({new_w},{new_h})")
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _relayout_ports(self):
        """根据当前尺寸重新布局端口与标签。"""
        # 基于原来垂直间距保持：仍按 20 起始 + 20 * idx
        for idx, point in enumerate(self.input_points):
            y = 20 + idx * 20
            point.setPos(-6, y - 5)
            if idx < len(self.input_labels):
                self.input_labels[idx].setPos(2, y - 8)
            point.update_connections()
        for idx, point in enumerate(self.output_points):
            y = 20 + idx * 20
            point.setPos(self.rect().width() - 4, y - 5)
            if idx < len(self.output_labels):
                self.output_labels[idx].setPos(self.rect().width() / 2 - 10, y - 8)
            point.update_connections()
        # 缩略图区域保持左上偏移
        if self._thumb_item:
            self._thumb_item.setPos(8, 24)
        if self._corner_handle:
            self._corner_handle.setRect(
                self.rect().width() - self._corner_handle_size,
                self.rect().height() - self._corner_handle_size,
                self._corner_handle_size,
                self._corner_handle_size
            )


class ConnectionPoint(QGraphicsRectItem):
    """连接点，支持交互拖拽创建连接"""

    def __init__(self, parent_item, point_type, x, y, port_name, canvas=None, size=10):
        super().__init__(0, 0, size, size, parent_item)
        self.parent_item = parent_item
        self.point_type = point_type  # "input" 或 "output"
        self.port_name = port_name
        self.canvas = canvas
        self.connections = []
        self.setPos(x, y)
        self.setBrush(QBrush(QColor(240, 210, 0) if point_type == 'input' else QColor(0, 170, 255)))
        self.setPen(QPen(QColor(120, 120, 0) if point_type == 'input' else QColor(0, 120, 200), 1))
        self.setToolTip(f"{parent_item.module_type}:{port_name} ({'输入' if point_type=='input' else '输出'})")

    def hoverEnterEvent(self, event):
        self.setBrush(QBrush(QColor(255, 240, 0) if self.point_type == 'input' else QColor(0, 200, 255)))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setBrush(QBrush(QColor(240, 210, 0) if self.point_type == 'input' else QColor(0, 170, 255)))
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if self.point_type == 'output' and event.button() == Qt.MouseButton.LeftButton:
            if self.canvas:
                self.canvas._begin_temp_connection(self)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self.point_type == 'input' and event.button() == Qt.MouseButton.LeftButton:
            if self.canvas and self.canvas.temp_connection_start:
                self.canvas._finalize_temp_connection(self)
        super().mouseReleaseEvent(event)

    def update_connections(self):
        for connection in self.connections:
            connection.update_line()


class ConnectionLine(QGraphicsItem):
    """连接线，支持右键删除"""

    def __init__(self, start_point, end_point, canvas=None, temp=False):
        super().__init__()
        self.start_point = start_point
        self.end_point = end_point
        self.canvas = canvas
        self.temp = temp
        if not temp:
            start_point.connections.append(self)
            end_point.connections.append(self)
        self._pen = QPen(QColor(80, 80, 80) if not temp else QColor(150, 150, 150, 120), 2, Qt.PenStyle.SolidLine)

    def setEndPoint(self, end_point):
        self.end_point = end_point
        if self.temp:
            self.start_point.connections.append(self)
            self.end_point.connections.append(self)
            self.temp = False

    def boundingRect(self):
        start = self.start_point.scenePos()
        end = self.end_point.scenePos()
        return QRectF(start, end).normalized()

    def paint(self, painter, option, widget):
        start = self.start_point.scenePos()
        end = self.end_point.scenePos()
        painter.setPen(self._pen)
        painter.drawLine(start, end)

    def update_line(self):
        self.prepareGeometryChange()
        self.update()

    def contextMenuEvent(self, event):
        if self.canvas:
            self.canvas._remove_connection(self)
        event.accept()


class FlowCanvas(QGraphicsView):
    """流程画布，支持模块端口连接"""

    module_selected = pyqtSignal(object)
    module_added = pyqtSignal(str)
    connection_added = pyqtSignal(dict)
    connection_removed = pyqtSignal(dict)
    
    def __init__(self):
        super().__init__()
        
        # 创建场景
        self.scene = QGraphicsScene()
        self.setScene(self.scene)
        
        # 设置画布属性
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setInteractive(True)
        
        # 设置场景大小
        self.scene.setSceneRect(0, 0, 2000, 2000)
        
        # 模块与连接
        self.modules = []
        self.connections = []  # (ConnectionLine, start_point, end_point)
        self.temp_connection_start = None
        self.temp_line = None
        
        # 连接信号
        self.scene.selectionChanged.connect(self._on_selection_changed)

        # 图片展示模块自动刷新定时器（避免依赖外部结果回调未实现时无法更新）
        self._viewer_timer = QTimer(self)
        self._viewer_timer.setInterval(200)  # 200ms 刷新
        self._viewer_timer.timeout.connect(self._refresh_image_viewers)
        self._viewer_timer.start()
        
    def add_module(self, module_type: str):
        """添加模块到画布（支持注册表反射端口）"""
        from app.pipeline.module_registry import get_module_class  # 延迟导入避免循环
        center = self.mapToScene(self.viewport().rect().center())

        module_ref = None
        cls = get_module_class(module_type)
        if cls:
            try:
                module_ref = cls(name=module_type)  # 使用显示名称作为实例名称
            except Exception as e:
                print(f"创建模块实例失败: {module_type}: {e}")
                module_ref = None

        # 通过真实实例端口反射
        input_ports = list(module_ref.input_ports.keys()) if module_ref else None
        output_ports = list(module_ref.output_ports.keys()) if module_ref else None
        module_item = ModuleItem(module_type, center.x() - 70, center.y() - 40, canvas=self,
                                 module_ref=module_ref, input_ports=input_ports, output_ports=output_ports)

        self.scene.addItem(module_item)
        self.modules.append(module_item)
        self.module_added.emit(module_type)

        
    def clear(self):
        """清空画布"""
        self.scene.clear()
        self.modules.clear()
        self.connections.clear()
        self.temp_connection_start = None
        self.temp_line = None
    # 清空后仍保持定时器运行（或可根据需要停止）
        
    def _on_selection_changed(self):
        """选择变化时的回调"""
        selected_items = self.scene.selectedItems()
        if selected_items and isinstance(selected_items[0], ModuleItem):
            self.module_selected.emit(selected_items[0])
            
    def contextMenuEvent(self, event):
        """右键菜单事件"""
        # 创建右键菜单
        menu = QMenu(self)
        
        # 添加模块菜单项
        add_camera_action = QAction("添加相机模块", self)
        add_camera_action.triggered.connect(lambda: self.add_module("相机"))
        menu.addAction(add_camera_action)
        
        add_trigger_action = QAction("添加触发模块", self)
        add_trigger_action.triggered.connect(lambda: self.add_module("触发"))
        menu.addAction(add_trigger_action)
        
        add_model_action = QAction("添加模型模块", self)
        add_model_action.triggered.connect(lambda: self.add_module("模型"))
        menu.addAction(add_model_action)
        
        add_postprocess_action = QAction("添加后处理模块", self)
        add_postprocess_action.triggered.connect(lambda: self.add_module("后处理"))
        menu.addAction(add_postprocess_action)

        add_image_import_action = QAction("添加图片导入模块", self)
        add_image_import_action.triggered.connect(lambda: self.add_module("图片导入"))
        menu.addAction(add_image_import_action)

        add_image_display_action = QAction("添加图片展示模块", self)
        add_image_display_action.triggered.connect(lambda: self.add_module("图片展示"))
        menu.addAction(add_image_display_action)
        
        menu.addSeparator()
        
        # 清空画布
        clear_action = QAction("清空画布", self)
        clear_action.triggered.connect(self.clear)
        menu.addAction(clear_action)
        
        # 显示菜单
        # PyQt6 使用 exec 而不是 exec_
        menu.exec(event.globalPos())
        
    def wheelEvent(self, event):
        """鼠标滚轮事件，用于缩放"""
        # Ctrl + 滚轮缩放
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            scale_factor = 1.2
            if event.angleDelta().y() < 0:
                scale_factor = 1.0 / scale_factor
                
            self.scale(scale_factor, scale_factor)
        else:
            super().wheelEvent(event)
            
    def keyPressEvent(self, event):
        """键盘按下事件"""
        if event.key() == Qt.Key.Key_Delete:
            # 删除选中的模块
            selected_items = self.scene.selectedItems()
            for item in selected_items:
                if isinstance(item, ModuleItem):
                    self.scene.removeItem(item)
                    if item in self.modules:
                        self.modules.remove(item)
            # 删除孤立连接
            self._cleanup_orphan_connections()
        else:
            super().keyPressEvent(event)

    # ---------- 连接管理 ----------
    def _begin_temp_connection(self, start_point):
        self.temp_connection_start = start_point
        dummy_end = start_point  # 初始重用起点
        self.temp_line = ConnectionLine(start_point, dummy_end, canvas=self, temp=True)
        self.scene.addItem(self.temp_line)

    def mouseMoveEvent(self, event):
        if self.temp_line and self.temp_connection_start:
            # 临时线终点跟随鼠标
            pos = self.mapToScene(event.pos())
            # 创建一个临时虚拟点
            end_point = self.temp_connection_start  # reuse for boundingRect
            self.temp_line.end_point = end_point
            self.temp_line.update_line()
        super().mouseMoveEvent(event)

    def _finalize_temp_connection(self, end_point):
        if not self.temp_connection_start or not self.temp_line:
            return
        if end_point.parent_item == self.temp_connection_start.parent_item:
            # 同一模块不允许自连接（可改）
            self._cancel_temp_connection()
            return
        self.temp_line.setEndPoint(end_point)
        self.connections.append((self.temp_line, self.temp_connection_start, end_point))
        payload = {
            "source_module": self.temp_connection_start.parent_item.module_id,
            "source_port": self.temp_connection_start.port_name,
            "target_module": end_point.parent_item.module_id,
            "target_port": end_point.port_name
        }
        self.connection_added.emit(payload)
        self.temp_connection_start = None
        self.temp_line = None

    def _cancel_temp_connection(self):
        if self.temp_line:
            self.scene.removeItem(self.temp_line)
        self.temp_connection_start = None
        self.temp_line = None

    def _remove_connection(self, line_item):
        for idx, (line, sp, ep) in enumerate(self.connections):
            if line is line_item:
                payload = {
                    "source_module": sp.parent_item.module_id,
                    "source_port": sp.port_name,
                    "target_module": ep.parent_item.module_id,
                    "target_port": ep.port_name
                }
                # 从连接列表删除
                sp.connections.remove(line)
                ep.connections.remove(line)
                self.scene.removeItem(line)
                del self.connections[idx]
                self.connection_removed.emit(payload)
                break

    def _cleanup_orphan_connections(self):
        # 移除已经不存在模块的连接
        to_remove = []
        for line, sp, ep in self.connections:
            if sp.parent_item not in self.modules or ep.parent_item not in self.modules:
                to_remove.append(line)
        for line in to_remove:
            self._remove_connection(line)

    def _refresh_image_viewers(self):
        """定时刷新图片展示模块缩略图。"""
        for m in self.modules:
            if getattr(m, '_is_image_viewer', False):
                try:
                    m.refresh_visual()
                except Exception:
                    pass

    def export_structure(self) -> Dict[str, Any]:
        modules = []
        for m in self.modules:
            modules.append({
                "module_id": m.module_id,
                "module_type": m.module_type,
                "x": m.scenePos().x(),
                "y": m.scenePos().y(),
                "width": m.rect().width(),
                "height": m.rect().height(),
                "inputs": m.input_ports_def,
                "outputs": m.output_ports_def
            })
        links = []
        for line, sp, ep in self.connections:
            links.append({
                "source_module": sp.parent_item.module_id,
                "source_port": sp.port_name,
                "target_module": ep.parent_item.module_id,
                "target_port": ep.port_name
            })
        return {"modules": modules, "connections": links}