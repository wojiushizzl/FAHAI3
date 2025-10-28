#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""改进的连接线与交互支持
包含 BetterConnectionLine 提供拖拽过程中光标跟随、箭头绘制与删除菜单。
"""
from PyQt6.QtWidgets import QGraphicsItem, QGraphicsSceneContextMenuEvent
from PyQt6.QtGui import QPen, QColor, QBrush, QPainter
from PyQt6.QtCore import QPointF, QRectF, Qt

class BetterConnectionLine(QGraphicsItem):
    """改进连接线: 支持临时拖拽光标跟随、箭头、右键删除"""
    def __init__(self, start_point, end_point, canvas=None, temp=False):
        super().__init__()
        # 允许被选择
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        # 启用鼠标悬停事件
        self.setAcceptHoverEvents(True)
        self.start_point = start_point
        self.end_point = end_point
        self.canvas = canvas
        self.temp = temp
        self.temp_cursor_pos: QPointF | None = None
        if not temp:
            start_point.connections.append(self)
            end_point.connections.append(self)
        self._pen = QPen(QColor(80, 80, 80) if not temp else QColor(150, 150, 150, 160), 2, Qt.PenStyle.SolidLine)
        # 动画与状态扩展
        self.status: str = 'normal'  # normal|active|error|warning|cached
        self._anim_phase: float = 0.0
        self._dash_pattern = [10, 6]
        self._last_update_ms: int = 0

    # ---- 状态与动画接口 ----
    def set_status(self, status: str):
        """设置连接线状态并刷新颜色样式。"""
        valid = {'normal','active','error','warning','cached'}
        if status not in valid:
            return
        self.status = status
        base = QColor(80,80,80)
        if status == 'active':
            base = QColor(40,170,255)
        elif status == 'error':
            base = QColor(220,40,40)
        elif status == 'warning':
            base = QColor(255,170,0)
        elif status == 'cached':
            base = QColor(140,140,140)
        w = 2 if status in ('normal','cached') else 3
        self._pen = QPen(base, w, Qt.PenStyle.SolidLine)
        if status == 'active':
            self._pen.setStyle(Qt.PenStyle.DashLine)
            self._pen.setDashPattern(self._dash_pattern)
        else:
            self._pen.setStyle(Qt.PenStyle.SolidLine)
        self.update_line()

    def advance_animation(self, delta_phase: float = 1.0):
        """推进动画相位，用于 active 状态的流动效果。"""
        if self.status != 'active':
            return
        self._anim_phase = (self._anim_phase + delta_phase) % sum(self._dash_pattern)
        try:
            # Qt6 支持 dash offset
            self._pen.setDashOffset(self._anim_phase)
        except Exception:
            pass
        self.update()

    def set_temp_cursor(self, pos: QPointF):
        if self.temp:
            self.temp_cursor_pos = pos
            self.update_line()

    def setEndPoint(self, end_point):
        self.end_point = end_point
        if self.temp:
            self.start_point.connections.append(self)
            self.end_point.connections.append(self)
            self.temp = False
            self.temp_cursor_pos = None
        self.update_line()

    def boundingRect(self):
        start = self.start_point.scenePos()
        end = self.end_point.scenePos() if (self.end_point and not self.temp) else (self.temp_cursor_pos or start)
        return QRectF(start, end).normalized()

    def shape(self):
        """精确命中区域: 使用细路径而非整个 boundingRect 避免矩形大面积难以选择

        默认 boundingRect 过大导致点击空白处也可能命中, 这里构造一条较宽的 QPainterPath (6px) 贴合直线, 提高选择精准度。
        """
        start = self.start_point.scenePos()
        end = self.end_point.scenePos() if (self.end_point and not self.temp) else (self.temp_cursor_pos or start)
        from PyQt6.QtGui import QPainterPath, QPainterPathStroker
        path = QPainterPath(start)
        path.lineTo(end)
        stroker = QPainterPathStroker()
        stroker.setWidth(6.0)  # 可调命中宽度
        return stroker.createStroke(path)

    def paint(self, painter: QPainter, option, widget):
        start = self.start_point.scenePos()
        if self.temp and self.temp_cursor_pos is not None:
            end = self.temp_cursor_pos
        else:
            end = self.end_point.scenePos()
        pen = QPen(self._pen)
        if self.isSelected():
            # 选中时高亮显示
            c = pen.color()
            pen.setColor(QColor(min(c.red()+80,255), min(c.green()+80,255), min(c.blue()+80,255)))
            pen.setWidth(pen.width()+1)
        painter.setPen(pen)
        painter.drawLine(start, end)
        # 若处于 active 状态且不支持 dash 偏移，可绘制额外流动点作为降级
        if self.status == 'active' and self._pen.style() != Qt.PenStyle.DashLine:
            length_vec = end - start
            if length_vec.manhattanLength() > 12:
                import math
                total = math.hypot(length_vec.x(), length_vec.y())
                if total > 0:
                    seg = 28
                    phase = self._anim_phase % seg
                    t = phase / seg
                    px = start.x() + length_vec.x() * t
                    py = start.y() + length_vec.y() * t
                    painter.setBrush(QBrush(QColor(40,170,255)))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawEllipse(QPointF(px, py), 4, 4)
        if not self.temp:
            direction = end - start
            if direction.manhattanLength() > 6:
                import math
                angle = math.atan2(direction.y(), direction.x())
                arrow_size = 8
                p1 = end
                p2 = QPointF(end.x() - arrow_size * math.cos(angle - 0.3), end.y() - arrow_size * math.sin(angle - 0.3))
                p3 = QPointF(end.x() - arrow_size * math.cos(angle + 0.3), end.y() - arrow_size * math.sin(angle + 0.3))
                painter.setBrush(QBrush(self._pen.color()))
                painter.drawPolygon(p1, p2, p3)

    def update_line(self):
        self.prepareGeometryChange()
        self.update()

    def contextMenuEvent(self, event: QGraphicsSceneContextMenuEvent):
        if self.canvas:
            # 单独删除所选连接线（支持批量：若多条选中则统一删除）
            selected = [it for it in self.canvas.scene.selectedItems() if isinstance(it, BetterConnectionLine)]
            if selected:
                for line in selected:
                    self.canvas._remove_connection(line)
            else:
                self.canvas._remove_connection(self)
        event.accept()

    # ---- 悬停高亮 ----
    def hoverEnterEvent(self, event):  # type: ignore
        # 仅在未选中时稍微提高亮度与宽度
        if not self.isSelected():
            c = self._pen.color()
            hl = QColor(min(c.red()+60,255), min(c.green()+60,255), min(c.blue()+60,255))
            w = self._pen.width()+1
            self._hover_backup = (self._pen.color(), self._pen.width())
            self._pen.setColor(hl)
            self._pen.setWidth(w)
            self.update()
        event.accept()

    def hoverLeaveEvent(self, event):  # type: ignore
        if hasattr(self, '_hover_backup') and not self.isSelected():
            orig_color, orig_w = self._hover_backup
            self._pen.setColor(orig_color)
            self._pen.setWidth(orig_w)
            self.update()
        event.accept()
