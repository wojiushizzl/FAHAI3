#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""改进的连接线与交互支持
包含 BetterConnectionLine 提供拖拽过程中光标跟随、箭头绘制与删除菜单。
"""
from PyQt6.QtWidgets import QGraphicsItem
from PyQt6.QtGui import QPen, QColor, QBrush, QPainter
from PyQt6.QtCore import QPointF, QRectF, Qt

class BetterConnectionLine(QGraphicsItem):
    """改进连接线: 支持临时拖拽光标跟随、箭头、右键删除"""
    def __init__(self, start_point, end_point, canvas=None, temp=False):
        super().__init__()
        self.start_point = start_point
        self.end_point = end_point
        self.canvas = canvas
        self.temp = temp
        self.temp_cursor_pos: QPointF | None = None
        if not temp:
            start_point.connections.append(self)
            end_point.connections.append(self)
        self._pen = QPen(QColor(80, 80, 80) if not temp else QColor(150, 150, 150, 160), 2, Qt.PenStyle.SolidLine)

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

    def paint(self, painter: QPainter, option, widget):
        start = self.start_point.scenePos()
        if self.temp and self.temp_cursor_pos is not None:
            end = self.temp_cursor_pos
        else:
            end = self.end_point.scenePos()
        painter.setPen(self._pen)
        painter.drawLine(start, end)
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

    def contextMenuEvent(self, event):
        if self.canvas:
            # 调用画布删除连接逻辑
            self.canvas._remove_connection(self)
        event.accept()
