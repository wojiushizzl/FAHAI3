#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flow canvas (clean rebuild)
Public classes preserved: ModuleItem, ConnectionPoint, ConnectionLine, FlowCanvas.
Adds DEBUG_GUI flag to silence debug prints by default.
"""

from typing import Dict, Any, List, Optional, Tuple
from PyQt6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsItem,
    QGraphicsRectItem, QGraphicsTextItem, QMenu, QGraphicsPixmapItem
)
from PyQt6.QtCore import Qt, QRectF, pyqtSignal, QTimer
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QAction, QImage, QPixmap

DEBUG_GUI = False  # Set True to re-enable verbose debug prints


class ConnectionPoint(QGraphicsRectItem):
    def __init__(self, parent_item: 'ModuleItem', point_type: str, x: float, y: float, port_name: str, canvas=None, size: int = 10):
        super().__init__(0, 0, size, size, parent_item)
        self.parent_item = parent_item
        self.point_type = point_type  # 'input' or 'output'
        self.port_name = port_name
        self.canvas = canvas
        self.connections: List['ConnectionLine'] = []
        self.setPos(x, y)
        self.setBrush(QBrush(QColor(240, 210, 0) if point_type == 'input' else QColor(0, 170, 255)))
        self.setPen(QPen(QColor(120, 120, 0) if point_type == 'input' else QColor(0, 120, 200), 1))
        self.setToolTip(f"{parent_item.module_type}:{port_name} ({'输入' if point_type=='input' else '输出'})")
        self.setAcceptHoverEvents(True)

    def hoverEnterEvent(self, event):
        self.setBrush(QBrush(QColor(255, 240, 0) if self.point_type == 'input' else QColor(0, 200, 255)))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setBrush(QBrush(QColor(240, 210, 0) if self.point_type == 'input' else QColor(0, 170, 255)))
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if self.point_type == 'output' and event.button() == Qt.MouseButton.LeftButton and self.canvas:
            self.canvas._begin_temp_connection(self)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self.point_type == 'input' and event.button() == Qt.MouseButton.LeftButton and self.canvas and self.canvas.temp_connection_start:
            self.canvas._finalize_temp_connection(self)
        super().mouseReleaseEvent(event)

    def update_connections(self):
        for c in self.connections:
            c.update_line()


class ConnectionLine(QGraphicsItem):
    def __init__(self, start_point: ConnectionPoint, end_point: ConnectionPoint, canvas=None, temp: bool = False):
        super().__init__()
        self.start_point = start_point
        self.end_point = end_point
        self.canvas = canvas
        self.temp = temp
        if not temp:
            start_point.connections.append(self)
            end_point.connections.append(self)
        self._pen = QPen(QColor(80, 80, 80) if not temp else QColor(150, 150, 150, 140), 2)

    def setEndPoint(self, end_point: ConnectionPoint):
        self.end_point = end_point
        if self.temp:
            self.start_point.connections.append(self)
            self.end_point.connections.append(self)
            self.temp = False
        self.update_line()

    def boundingRect(self):
        s = self.start_point.scenePos()
        e = self.end_point.scenePos()
        return QRectF(s, e).normalized()

    def paint(self, painter, option, widget=None):
        painter.setPen(self._pen)
        painter.drawLine(self.start_point.scenePos(), self.end_point.scenePos())

    def update_line(self):
        self.prepareGeometryChange()
        self.update()

    def contextMenuEvent(self, event):
        if self.canvas:
            self.canvas._remove_connection(self)
            event.accept()


class ModuleItem(QGraphicsRectItem):
    def __init__(self, module_type: str, x=0, y=0, width=140, height=80, canvas=None,
                 module_ref=None, input_ports: Optional[List[str]] = None, output_ports: Optional[List[str]] = None):
        super().__init__(0, 0, width, height)
        self.canvas = canvas
        self.module_type = module_type
        self.module_ref = module_ref
        self.module_id = module_ref.module_id if module_ref else f"{module_type}_{id(self)}"
        self.setPos(x, y)
        self.setBrush(QBrush(QColor(200, 220, 255)))
        self.setPen(QPen(QColor(100, 150, 200), 2))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self.text_item = QGraphicsTextItem(module_type, self)
        self.text_item.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.text_item.setPos(8, 4)
        # Image viewer support
        self._is_image_viewer = (module_type == "图片展示")
        self._thumb_item = None
        if self._is_image_viewer:
            self._thumb_item = QGraphicsPixmapItem(self)
            self._thumb_item.setPos(8, 24)
            self._update_thumbnail(None)
        # Resize state
        self._resizing = False
        self._resize_margin = 14
        self._orig_size = (width, height)
        self._corner_handle_size = 14
        self._corner_handle = QGraphicsRectItem(width - 14, height - 14, 14, 14, self)
        self._corner_handle.setBrush(QBrush(QColor(120, 120, 120)))
        self._corner_handle.setPen(QPen(Qt.PenStyle.NoPen))
        self._corner_handle.setOpacity(0.55)
        self._corner_handle.setToolTip("拖拽调整大小")
        self._corner_handle.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        # Ports (reflect from module)
        if input_ports is None:
            input_ports = list(module_ref.input_ports.keys()) if module_ref else ["in"]
        if output_ports is None:
            output_ports = list(module_ref.output_ports.keys()) if module_ref else ["out"]
        self.input_ports_def = input_ports
        self.output_ports_def = output_ports
        self.input_points: List[ConnectionPoint] = []
        self.output_points: List[ConnectionPoint] = []
        self.input_labels: List[QGraphicsTextItem] = []
        self.output_labels: List[QGraphicsTextItem] = []
        self._create_ports()
        self._prev_has_img = None

    def _create_ports(self):
        for idx, name in enumerate(self.input_ports_def):
            y = 24 + idx * 18
            p = ConnectionPoint(self, 'input', -6, y - 5, name, canvas=self.canvas)
            self.input_points.append(p)
            label = QGraphicsTextItem(name, self)
            label.setFont(QFont("Arial", 8))
            label.setDefaultTextColor(QColor(40, 40, 40))
            label.setPos(2, y - 8)
            self.input_labels.append(label)
        for idx, name in enumerate(self.output_ports_def):
            y = 24 + idx * 18
            p = ConnectionPoint(self, 'output', self.rect().width() - 4, y - 5, name, canvas=self.canvas)
            self.output_points.append(p)
            label = QGraphicsTextItem(name, self)
            label.setFont(QFont("Arial", 8))
            label.setDefaultTextColor(QColor(40, 40, 40))
            br = label.boundingRect()
            label.setPos(self.rect().width() - br.width() - 8, y - 8)
            self.output_labels.append(label)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            for p in self.input_points + self.output_points:
                p.update_connections()
        return super().itemChange(change, value)

    def refresh_visual(self):
        if not self._is_image_viewer or not self.module_ref:
            return
        img = self.module_ref.outputs.get('image') or getattr(self.module_ref, 'last_image', None)
        now = img is not None and hasattr(img, 'shape')
        if self._prev_has_img is None or self._prev_has_img != now:
            if DEBUG_GUI:
                print(f"[DEBUG][{self.module_id}] refresh_visual -> {'image present' if now else 'no image'}")
            self._prev_has_img = now
        self._update_thumbnail(img)

    def _update_thumbnail(self, img):
        if not self._thumb_item:
            return
        w = int(self.module_ref.config.get('width', 160)) if self.module_ref else 160
        h = int(self.module_ref.config.get('height', 120)) if self.module_ref else 120
        need_h = 34 + h + 8
        if need_h > self.rect().height():
            self.setRect(0, 0, max(self.rect().width(), w + 20), need_h)
        if img is None or not hasattr(img, 'shape'):
            q = QImage(w, h, QImage.Format.Format_RGB32)
            q.fill(QColor(230, 230, 230))
            self._thumb_item.setPixmap(QPixmap.fromImage(q))
            return
        try:
            import numpy as np
            arr = img
            if len(arr.shape) == 2:
                arr = np.stack([arr] * 3, axis=-1)
            elif arr.shape[2] == 4:
                arr = arr[:, :, :3]
            arr_rgb = arr[:, :, ::-1].copy()  # BGR->RGB
            h0, w0 = arr_rgb.shape[:2]
            qimg = QImage(arr_rgb.data, w0, h0, w0 * 3, QImage.Format.Format_RGB888)
            pix = QPixmap.fromImage(qimg)
            pix_scaled = pix.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self._thumb_item.setPixmap(pix_scaled)
        except Exception as e:
            if DEBUG_GUI:
                print(f"[DEBUG][{self.module_id}] thumbnail error: {e}")
            q = QImage(w, h, QImage.Format.Format_RGB32)
            q.fill(QColor(200, 200, 200))
            self._thumb_item.setPixmap(QPixmap.fromImage(q))

    def hoverMoveEvent(self, event):
        pos = event.pos(); w = self.rect().width(); h = self.rect().height()
        near_r = abs(pos.x() - w) <= self._resize_margin; near_b = abs(pos.y() - h) <= self._resize_margin
        corner = False
        ch = QRectF(w - self._corner_handle_size, h - self._corner_handle_size, self._corner_handle_size, self._corner_handle_size)
        corner = ch.contains(pos)
        if corner or (near_r and near_b):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif near_r:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif near_b:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.pos(); w = self.rect().width(); h = self.rect().height()
            ch = QRectF(w - self._corner_handle_size, h - self._corner_handle_size, self._corner_handle_size, self._corner_handle_size)
            corner = ch.contains(pos)
            if corner or abs(pos.x() - w) <= self._resize_margin or abs(pos.y() - h) <= self._resize_margin:
                self._resizing = True; self._orig_size = (w, h); self._press_pos = pos
                if DEBUG_GUI:
                    print(f"[DEBUG][{self.module_id}] begin resize {w}x{h}")
                event.accept(); return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing:
            d = event.pos() - self._press_pos; new_w = max(100, self._orig_size[0] + d.x()); new_h = max(60, self._orig_size[1] + d.y())
            self.setRect(0, 0, new_w, new_h); self._relayout_ports(); self.refresh_visual()
            self._corner_handle.setRect(new_w - 14, new_h - 14, 14, 14)
            if DEBUG_GUI:
                print(f"[DEBUG][{self.module_id}] resizing -> {new_w}x{new_h}")
            event.accept(); return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing and event.button() == Qt.MouseButton.LeftButton:
            self._resizing = False; new_w = int(self.rect().width()); new_h = int(self.rect().height())
            if self.module_ref and isinstance(self.module_ref.config, dict):
                if 'width' in self.module_ref.config or 'height' in self.module_ref.config:
                    try:
                        self.module_ref.configure({'width': new_w, 'height': new_h})
                    except Exception:
                        pass
            self.refresh_visual()
            if DEBUG_GUI:
                print(f"[DEBUG][{self.module_id}] resize done {new_w}x{new_h}")
            event.accept(); return
        super().mouseReleaseEvent(event)

    def _relayout_ports(self):
        for idx, p in enumerate(self.input_points):
            y = 24 + idx * 18; p.setPos(-6, y - 5); self.input_labels[idx].setPos(2, y - 8); p.update_connections()
        for idx, p in enumerate(self.output_points):
            y = 24 + idx * 18; p.setPos(self.rect().width() - 4, y - 5); br = self.output_labels[idx].boundingRect(); self.output_labels[idx].setPos(self.rect().width() - br.width() - 8, y - 8); p.update_connections()
        if self._thumb_item:
            self._thumb_item.setPos(8, 24)
        self._corner_handle.setRect(self.rect().width() - 14, self.rect().height() - 14, 14, 14)


class FlowCanvas(QGraphicsView):
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
        self.scene.setSceneRect(0, 0, 2000, 2000)
        self.modules: List[ModuleItem] = []
        self.connections: List[Tuple[ConnectionLine, ConnectionPoint, ConnectionPoint]] = []
        self.temp_connection_start: Optional[ConnectionPoint] = None
        self.temp_line: Optional[ConnectionLine] = None
        self.scene.selectionChanged.connect(self._on_selection_changed)
        self._viewer_timer = QTimer(self)
        self._viewer_timer.setInterval(200)
        self._viewer_timer.timeout.connect(self._refresh_image_viewers)
        self._viewer_timer.start()

    def add_module(self, module_type: str):
        from app.pipeline.module_registry import get_module_class  # lazy import to avoid circular
        center = self.mapToScene(self.viewport().rect().center())
        module_ref = None
        cls = get_module_class(module_type)
        if cls:
            try:
                module_ref = cls(name=module_type)
            except Exception as e:
                print(f"创建模块实例失败: {module_type}: {e}")
        ins = list(module_ref.input_ports.keys()) if module_ref else None
        outs = list(module_ref.output_ports.keys()) if module_ref else None
        item = ModuleItem(module_type, center.x() - 70, center.y() - 40, canvas=self, module_ref=module_ref, input_ports=ins, output_ports=outs)
        self.scene.addItem(item)
        self.modules.append(item)
        self.module_added.emit(module_type)

    def clear(self):
        self.scene.clear()
        self.modules.clear()
        self.connections.clear()
        self.temp_connection_start = None
        self.temp_line = None

    def _on_selection_changed(self):
        sel = self.scene.selectedItems()
        if sel and isinstance(sel[0], ModuleItem):
            self.module_selected.emit(sel[0])

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        act_display = QAction("添加图片展示模块", self)
        act_display.triggered.connect(lambda: self.add_module("图片展示"))
        menu.addAction(act_display)
        menu.addSeparator()
        act_clear = QAction("清空画布", self)
        act_clear.triggered.connect(self.clear)
        menu.addAction(act_clear)
        menu.exec(event.globalPos())

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
            self.scale(factor, factor)
        else:
            super().wheelEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete:
            for it in self.scene.selectedItems():
                if isinstance(it, ModuleItem):
                    self.scene.removeItem(it)
                    if it in self.modules:
                        self.modules.remove(it)
            self._cleanup_orphan_connections()
        else:
            super().keyPressEvent(event)

    # Connection workflow -------------------------------------------------
    def _begin_temp_connection(self, start_point: ConnectionPoint):
        self.temp_connection_start = start_point
        self.temp_line = ConnectionLine(start_point, start_point, canvas=self, temp=True)
        self.scene.addItem(self.temp_line)

    def mouseMoveEvent(self, event):
        if self.temp_line and self.temp_connection_start:
            self.temp_line.update_line()
        super().mouseMoveEvent(event)

    def _finalize_temp_connection(self, end_point: ConnectionPoint):
        if not self.temp_connection_start or not self.temp_line:
            return
        if end_point.parent_item == self.temp_connection_start.parent_item:
            self._cancel_temp_connection()
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

    def _cancel_temp_connection(self):
        if self.temp_line:
            self.scene.removeItem(self.temp_line)
        self.temp_connection_start = None
        self.temp_line = None

    def _remove_connection(self, line_item: ConnectionLine):
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

    def _cleanup_orphan_connections(self):
        to_remove = [line for line, sp, ep in self.connections if sp.parent_item not in self.modules or ep.parent_item not in self.modules]
        for line in to_remove:
            self._remove_connection(line)

    def _refresh_image_viewers(self):
        for m in self.modules:
            if getattr(m, '_is_image_viewer', False):
                try:
                    m.refresh_visual()
                except Exception:
                    if DEBUG_GUI:
                        print(f"[DEBUG][{m.module_id}] refresh_visual error")

    def export_structure(self) -> Dict[str, Any]:
        modules = [{
            'module_id': m.module_id,
            'module_type': m.module_type,
            'x': m.scenePos().x(),
            'y': m.scenePos().y(),
            'width': m.rect().width(),
            'height': m.rect().height(),
            'inputs': m.input_ports_def,
            'outputs': m.output_ports_def
        } for m in self.modules]
        links = [{
            'source_module': sp.parent_item.module_id,
            'source_port': sp.port_name,
            'target_module': ep.parent_item.module_id,
            'target_port': ep.port_name
        } for line, sp, ep in self.connections]
        return {'modules': modules, 'connections': links}
