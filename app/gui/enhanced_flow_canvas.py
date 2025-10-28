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
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal, QTimer, QTime
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QAction
from typing import Dict, Any, List
import json, os

from app.gui.connection_graphics import BetterConnectionLine
from app.pipeline.module_registry import get_module_class
from app.pipeline.pipeline_executor import PipelineExecutor

DEBUG_GUI = False  # 全局调试开关: 设为 True 可恢复 [DEBUG] 打印

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
        self.text_item.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.text_item.setPos(0, 4)  # will center after ports created
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

        # 文本查看分类拆分：
        # _is_text_viewer 仅用于可编辑的打印显示系列；_is_text_display 用于参考 OK/NOK 的只读文本展示
        self._is_text_viewer = (module_type in ("打印显示", "打印显示模块"))
        self._is_text_display = (module_type == "文本展示")
        self._text_item = None
        self._text_edit_widget = None
        self._text_display_rect = None
        if self._is_text_viewer:
            from PyQt6.QtWidgets import QPlainTextEdit, QGraphicsProxyWidget
            self._text_edit_widget = QPlainTextEdit()
            self._text_edit_widget.setReadOnly(False)
            self._text_edit_widget.setPlaceholderText("(无内容)")
            self._text_edit_widget.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            self._text_edit_widget.setStyleSheet("QPlainTextEdit {background:#fafafa;border:1px solid #bbb;font-family:Consolas;font-size:11px;color:#222;} ::selection {background:#cceeff;}")
            proxy = QGraphicsProxyWidget(self); proxy.setWidget(self._text_edit_widget); proxy.setPos(8,24); self._text_proxy = proxy
            def _on_user_change():
                if self.module_ref and hasattr(self.module_ref,'_lines'):
                    txt = self._text_edit_widget.toPlainText()
                    self.module_ref._lines = txt.splitlines()[-int(self.module_ref.config.get('max_lines',10)):] or []
                    self.module_ref._last_text = self.module_ref._lines[-1] if self.module_ref._lines else None
            self._text_edit_widget.textChanged.connect(_on_user_change)
            self._auto_scroll = True
        elif self._is_text_display:
            # 使用内部矩形 + QGraphicsTextItem 展示，只读无编辑
            from PyQt6.QtWidgets import QGraphicsRectItem
            self._text_display_rect = QGraphicsRectItem(self)
            self._text_display_rect.setBrush(QBrush(QColor(255,255,255)))
            self._text_display_rect.setPen(QPen(QColor(170,170,170),1))
            self._text_item = QGraphicsTextItem("(无内容)", self._text_display_rect)
            self._text_item.setFont(QFont("Consolas", 11))
            self._text_item.setDefaultTextColor(QColor(34,34,34))
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

    def _center_title(self):
        """精确居中标题：考虑左右内边距与当前笔宽，避免因字体渲染导致的半像素偏移。"""
        try:
            if not hasattr(self, 'text_item') or self.text_item is None:
                return
            br = self.text_item.boundingRect()
            pad_left = 4
            pad_right = 4
            avail_w = self.rect().width() - pad_left - pad_right
            cx = pad_left + (avail_w - br.width()) / 2
            # 四舍五入避免模糊
            cx = int(round(cx))
            self.text_item.setPos(cx, 4)
        except Exception:
            pass

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
            point_x = self.rect().width() - 4
            point = ConnectionPoint(self, "output", point_x, y - 5, name, canvas=self.canvas)
            self.output_points.append(point)
            label = QGraphicsTextItem(name, self)
            label.setFont(QFont("Arial", 8))
            label.setDefaultTextColor(QColor(50, 50, 50))
            # 输出标签右对齐到端口左侧  (文本右边缘靠近 point_x - 6)
            br = label.boundingRect()
            label.setPos(point_x - br.width() - 6, y - 8)
            self.output_labels.append(label)
        # 计算内容区起始 y
        self._content_offset = title_h + max_rows * row_h + 12  # 增加端口区与内容区间隔
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
        # 打印显示编辑组件随尺寸/端口变化重新定位与尺寸调整
        if getattr(self, '_text_edit_widget', None):
            try:
                proxy = getattr(self, '_text_proxy', None)
                content_top = self._content_offset
                # 内容可用高度: 总高度 - 内容偏移 - 底部内边距
                avail_h = max(40, int(self.rect().height() - content_top - 8))
                avail_w = max(60, int(self.rect().width() - 16))
                if proxy:
                    proxy.setPos(8, content_top)
                # 同步 QPlainTextEdit 尺寸
                self._text_edit_widget.setMinimumWidth(avail_w)
                self._text_edit_widget.setMaximumWidth(avail_w)
                self._text_edit_widget.setMinimumHeight(avail_h)
                self._text_edit_widget.setMaximumHeight(avail_h)
            except Exception:
                pass
        # 初始创建后立即居中标题
        if hasattr(self, '_center_title'):
            self._center_title()

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
        if hasattr(self, '_center_title'):
            self._center_title()

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
                        if DEBUG_GUI:
                            print(f"[DEBUG][{self.module_id}] refresh_visual: 无图像")
                    else:
                        if DEBUG_GUI:
                            print(f"[DEBUG][{self.module_id}] refresh_visual: shape={getattr(img,'shape',None)} dtype={getattr(img,'dtype',None)}")
                except Exception as e:
                    if DEBUG_GUI:
                        print(f"[DEBUG][{self.module_id}] refresh_visual: 打印异常: {e}")
                self._prev_has_img = has_img_now
            self._update_thumbnail(img)
        # ----- 文本展示处理 -----
        if self._is_text_viewer and self._text_edit_widget:
            try:
                text = getattr(self.module_ref, 'display_text', '') or ''
            except Exception:
                text = ''
            # 打印显示模块不涉及样式颜色配置
            prev_text = getattr(self, '_prev_text_content', None)
            if prev_text != text:
                self._prev_text_content = text
                display = text if text.strip() else "(无内容)"
                # 若用户正在编辑，不强制覆盖其修改：仅当当前内容与模块缓冲不同或我们是首次建立
                widget_txt = self._text_edit_widget.toPlainText()
                if widget_txt.strip() != display.strip():
                    self._text_edit_widget.blockSignals(True)
                    self._text_edit_widget.setPlainText(display)
                    self._text_edit_widget.blockSignals(False)
                    # 自动滚动：仅在内容更新时而且未手动上滚
                    if getattr(self, '_auto_scroll', True):
                        scrollbar = self._text_edit_widget.verticalScrollBar()
                        scrollbar.setValue(scrollbar.maximum())
                # 统一使用内容偏移计算编辑区域与整体高度，避免文本区域超出模块矩形
                self._update_text_widget_geometry(display)
            else:
                # 即使文本未变化，仍确保几何同步（用户 resize 后）
                self._update_text_widget_geometry(self._prev_text_content or '')
        elif self._is_text_display and self._text_display_rect and self._text_item and self.module_ref:
            # 文本展示：固定矩形，不随行数膨胀，内部居中文本
            try:
                cfg = getattr(self.module_ref, 'config', {})
                font_size = int(cfg.get('font_size', 12))
                text_color = cfg.get('text_color', '#222222')
                bg_color = cfg.get('background_color', '#ffffff')
                self._text_item.setFont(QFont('Consolas', max(6,min(font_size,72))))
                self._text_item.setDefaultTextColor(QColor(text_color))
                self._text_display_rect.setBrush(QBrush(QColor(bg_color)))
            except Exception:
                pass
            text = ''
            try:
                text = getattr(self.module_ref,'display_text','') or ''
            except Exception:
                pass
            display = text if text.strip() else "(无内容)"
            if getattr(self, '_prev_text_display', None) != display:
                self._prev_text_display = display
                self._text_item.setPlainText(display)
            content_offset = getattr(self, '_content_offset', 40)
            inner_w = max(60, self.rect().width() - 16)
            inner_h = max(34, self.rect().height() - content_offset - 8)
            self._text_display_rect.setRect(8, content_offset, inner_w, inner_h)
            # 居中文本
            try:
                b = self._text_item.boundingRect()
                tx = 8 + (inner_w - b.width())/2
                ty = content_offset + (inner_h - b.height())/2
                self._text_item.setPos(tx, ty)
            except Exception:
                pass
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
            if DEBUG_GUI:
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
            # 若点击在输出端口矩形区域附近，优先保持连接拖拽，不触发 resize
            # 解决: 同时命中右边缘与输出点导致 _resizing 与 temp_line 并存的崩溃
            pos = event.pos(); w = self.rect().width(); h = self.rect().height()
            # 检查是否命中任一输出端口 (使用局部坐标比较)
            hit_output_point = False
            for p in self.output_points:
                try:
                    pr = p.mapRectToParent(p.rect())
                    if pr.contains(pos):
                        hit_output_point = True
                        break
                except Exception:
                    pass
            corner_hit = False
            if self._corner_handle:
                ch = QRectF(
                    self.rect().width() - self._corner_handle_size,
                    self.rect().height() - self._corner_handle_size,
                    self._corner_handle_size,
                    self._corner_handle_size
                )
                corner_hit = ch.contains(pos)
            resize_zone = corner_hit or (abs(pos.x()-w) <= self._resize_margin) or (abs(pos.y()-h) <= self._resize_margin)
            if resize_zone and not hit_output_point:
                # 开始 resize 前取消可能存在的从本模块发起的临时连接
                if self.canvas and getattr(self.canvas, 'temp_connection_start', None):
                    if getattr(self.canvas.temp_connection_start, 'parent_item', None) is self:
                        try:
                            self.canvas.cancel_temp_connection()
                        except Exception:
                            pass
                self._resizing = True
                self._orig_size = (w, h)
                self._press_pos = pos
                if DEBUG_GUI:
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
            if hasattr(self, '_center_title'):
                self._center_title()
            if self._corner_handle:
                self._corner_handle.setRect(new_w - self._corner_handle_size, new_h - self._corner_handle_size,
                                            self._corner_handle_size, self._corner_handle_size)
            if DEBUG_GUI:
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
            if hasattr(self, '_center_title'):
                self._center_title()
            if DEBUG_GUI:
                print(f"[DEBUG][{self.module_id}] 尺寸调整完成 ({new_w},{new_h})")
            event.accept(); return
        super().mouseReleaseEvent(event)

    def _relayout_ports(self):
        # 重新计算内容偏移（端口区高度可能受矩形宽度变化影响 label 定位不大）
        title_h = 20
        row_h = 18
        max_rows = max(len(self.input_points), len(self.output_points))
        self._content_offset = title_h + max_rows * row_h + 12
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
                br = self.output_labels[idx].boundingRect()
                self.output_labels[idx].setPos(self.rect().width() - 4 - br.width() - 6, y - 8)
            point.update_connections()
        # 内容项位置
        if self._thumb_item:
            self._thumb_item.setPos(8, self._content_offset)
        if getattr(self, '_text_item', None):
            self._text_item.setPos(8, self._content_offset)
        if hasattr(self, '_center_title'):
            self._center_title()
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

    def paint(self, painter: QPainter, option, widget=None):
        """高级美化：圆角、双层阴影、类型颜色、暗色主题适配、选中辉光、错误徽章。"""
        rect = self.rect()
        painter.save()
        dark = False
        if hasattr(self, 'canvas') and hasattr(self.canvas, '_dark_theme'):
            dark = bool(getattr(self.canvas, '_dark_theme'))
        # 统一分类 + 颜色工具
        try:
            from app.pipeline.utility.category_utils import classify_module, category_color_pair
            from app.pipeline.base_module import ModuleType
            # 尝试获取底层 module_type (BaseModule.module_type 为 Enum) 供更精准分类
            module_type_enum = None
            if self.module_ref is not None:
                try:
                    module_type_enum = getattr(self.module_ref, 'module_type', None)
                except Exception:
                    module_type_enum = None
            category = classify_module(self.module_type, getattr(module_type_enum, 'value', None) and module_type_enum)
            c1, c2 = category_color_pair(category, dark)
        except Exception:
            category = '其它'
            c1, c2 = QColor(95,125,170), QColor(120,155,195)
        if dark:
            # 暗色下整体降低亮度并稍微提高饱和度
            def dim(col: QColor, f=0.55):
                return QColor(int(col.red()*f), int(col.green()*f), int(col.blue()*f))
            c1 = dim(c1, 0.45); c2 = dim(c2, 0.60)
        # 选中态加亮
        if self.isSelected():
            def brighten(col: QColor, d=30):
                return QColor(min(255,col.red()+d), min(255,col.green()+d), min(255,col.blue()+d))
            c1 = brighten(c1, 25); c2 = brighten(c2, 45)
        # 渐变背景
        from PyQt6.QtGui import QLinearGradient
        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        grad.setColorAt(0, c1)
        grad.setColorAt(1, c2)
        # 阴影层（外层 + 内层轻描）
        shadow_color = QColor(0,0,0,90 if not dark else 140)
        shadow_rect_outer = QRectF(rect.x()+2, rect.y()+3, rect.width(), rect.height())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(shadow_color)
        painter.drawRoundedRect(shadow_rect_outer, 7, 7)
        inner_shadow = QColor(0,0,0,55 if not dark else 80)
        shadow_rect_inner = QRectF(rect.x()+1, rect.y()+1, rect.width(), rect.height())
        painter.setBrush(inner_shadow)
        painter.drawRoundedRect(shadow_rect_inner, 7, 7)
        # 主面板
        painter.setBrush(QBrush(grad))
        border_base = c1.darker(140) if not dark else c1.darker(180)
        if self.isSelected():
            border_base = border_base.lighter(130)
        pen = QPen(border_base, 2 if not self.isSelected() else 3)
        painter.setPen(pen)
        painter.drawRoundedRect(rect, 7, 7)
        # 选中辉光（外圈柔和）
        if self.isSelected():
            glow = QPen(QColor(255,255,255,70 if not dark else 110), 4)
            painter.setPen(glow)
            painter.drawRoundedRect(rect.adjusted(-2,-2,2,2), 9, 9)
        # 标题栏分隔线
        line_col = QColor(255,255,255,90) if dark else QColor(245,245,245,160)
        painter.setPen(QPen(line_col, 1))
        from PyQt6.QtCore import QPointF as _QPF
        painter.drawLine(_QPF(rect.left()+4, rect.top()+20), _QPF(rect.right()-4, rect.top()+20))
        # 分类标记文字（在右上角轻描显示分类首字）
        try:
            painter.setPen(QPen(QColor(255,255,255,90 if not dark else 140), 1))
            f = QFont('Arial', 7)
            painter.setFont(f)
            abbrev = category[0] if category else '?'
            painter.drawText(rect.adjusted(0,0,-4,0), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight, abbrev)
        except Exception:
            pass
        # 状态徽章绘制（错误/警告/缓存）
        status_color = None
        label_text = ''
        if self.module_ref:
            # 简单规则：存在 last_error -> 错误；有警告列表 -> 警告；输出未变化超过 N 次 -> 缓存
            try:
                if getattr(self.module_ref, 'last_error', None):
                    status_color = QColor(235,60,60); label_text = 'E'
                elif getattr(self.module_ref, 'warnings', None):
                    wlist = getattr(self.module_ref, 'warnings')
                    if isinstance(wlist, (list, tuple)) and len(wlist) > 0:
                        status_color = QColor(255,190,40); label_text = 'W'
                # 缓存标记（输出哈希重复次数）
                rep = getattr(self.module_ref, '_repeat_outputs_count', 0)
                if status_color is None and rep >= 5:
                    status_color = QColor(150,150,150); label_text = 'C'
            except Exception:
                pass
        if status_color:
            badge_rect = QRectF(rect.right()-18, rect.top()+2, 16, 16)
            painter.setBrush(QBrush(status_color))
            painter.setPen(QPen(QColor(255,255,255), 1))
            painter.drawEllipse(badge_rect.center(), 8, 8)
            if label_text:
                painter.setPen(QPen(QColor(255,255,255)))
                f = QFont('Arial', 8, QFont.Weight.Bold)
                painter.setFont(f)
                painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, label_text)
        painter.restore()

    def _update_text_widget_geometry(self, display: str):
        """根据当前文本计算合适的编辑区域与模块整体高度，确保文本框不大于内容矩形并填满可用空间。
        规则:
        - 行数 * 行高 + 内边距 得到建议编辑区高度。
        - 模块总高度 = 内容偏移 + 编辑区高度 + 底部边距。
        - 行高固定 14，顶部留 4px，底部留 8px，最大高度限制 500。
        - 用户手动拖拽放大后不自动收缩到比拖拽更小（除非文本显著变短且多余空间超过阈值）。
        """
        if not (self._is_text_viewer and self._text_edit_widget):
            return
        try:
            lines = max(1, display.count('\n') + 1)
            line_h = 14
            desired_edit_h = min(480, 8 + lines * line_h + 4)  # 内部高度（不含标题与端口区）
            content_offset = getattr(self, '_content_offset', 40)
            # 当前模块高度
            current_total_h = self.rect().height()
            min_total_h = content_offset + 40 + 8  # 最小编辑区 40
            desired_total_h = content_offset + desired_edit_h + 8
            # 若当前高度不足则扩展；若高度大出 120 且文本行很少则收缩
            target_h = current_total_h
            if current_total_h < desired_total_h:
                target_h = desired_total_h
            elif current_total_h > desired_total_h + 120:
                # 收缩上限：不能低于最小高度
                target_h = max(min_total_h, desired_total_h)
            if target_h != current_total_h:
                self.setRect(0,0,self.rect().width(), target_h)
                if self.canvas:
                    self.canvas._ensure_scene_margin()
            # 计算编辑区尺寸（宽度 = 模块宽-16，高度 = 模块高 - content_offset - 底部边距）
            edit_w = max(60, int(self.rect().width() - 16))
            edit_h = max(40, int(self.rect().height() - content_offset - 8))
            self._text_edit_widget.setFixedWidth(edit_w)
            self._text_edit_widget.setFixedHeight(edit_h)
            # 重新定位代理位置
            if getattr(self, '_text_proxy', None):
                try:
                    self._text_proxy.setPos(8, content_offset)
                except Exception:
                    pass
        except Exception as e:
            print(f"[打印显示] 更新文本几何失败: {e}")

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
        # 画布锁定：锁定后禁止添加/删除/移动/连线编辑，仍可查看与缩放、运行。
        self._locked = False
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
        # 暗色主题标记（由 MainWindow 调用 set_dark_theme 来设置）
        self._dark_theme = False
        # 右键平移参数
        self._pan_active = False
        self._pan_last_pos = None  # type: ignore
        self._pan_moved = False
        self._pan_threshold = 4  # 像素阈值：超过认为是拖拽，不弹菜单
        self._suppress_next_context = False  # 右键平移结束后抑制一次菜单
        # 右键平移增强：记录按下开始时间与累计距离，处理长按/慢拖也视为平移
        self._pan_press_time = None  # ms 时间戳
        self._pan_accum_dist = 0
        self._pan_time_threshold = 180  # ms 超过认为是平移意图
        self._pan_accum_threshold = 10  # 像素 累计超过认为是平移意图
        # 执行高亮原始样式缓存 {module_id: (brush, pen)}
        self._exec_highlight_original = {}
        # 图片展示模块定时器刷新（避免依赖结果回调）
        self._viewer_timer = QTimer(self)
        self._viewer_timer.setInterval(200)
        self._viewer_timer.timeout.connect(self._refresh_image_viewers)
        self._viewer_timer.start()

    def add_module(self, module_type: str):
        if self._locked:
            return
        center = self.mapToScene(self.viewport().rect().center())
        self.add_module_at(module_type, QPointF(center.x()-70, center.y()-40))

    def add_module_at(self, module_type: str, pos: QPointF):
        if self._locked:
            return
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
        if self._locked:
            return
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
        if getattr(self, '_dark_theme', False):
            pen_small = QPen(QColor(70,70,70,120))  # 更暗更透明
        else:
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
        if getattr(self, '_dark_theme', False):
            pen_big = QPen(QColor(95,95,95,160))
        else:
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

    def set_dark_theme(self, dark: bool):
        """外部通知暗色主题状态，刷新视图背景与网格颜色"""
        if self._dark_theme != dark:
            self._dark_theme = dark
            self.viewport().update()

    # ---------- 视图状态持久化 ----------
    def export_view_state(self) -> Dict[str, Any]:
        """导出当前视图状态 (缩放、中心点、场景矩形、网格、主题)。
        使用中心点而非滚动条，避免 DPI 与滚动范围变化导致偏移。"""
        m = self.transform()
        sr = self.scene.sceneRect()
        center_scene = self.mapToScene(self.viewport().rect().center())
        return {
            'scale': m.m11(),
            'center_x': center_scene.x(),
            'center_y': center_scene.y(),
            'scene_rect': (sr.x(), sr.y(), sr.width(), sr.height()),
            'show_grid': self.show_grid,
            'dark_theme': getattr(self, '_dark_theme', False)
        }

    def import_view_state(self, state: Dict[str, Any]):
        """恢复视图状态"""
        try:
            # 先恢复场景矩形，确保滚动范围正确
            if 'scene_rect' in state and isinstance(state['scene_rect'], (list, tuple)) and len(state['scene_rect']) == 4:
                x,y,w,h = state['scene_rect']
                try:
                    self.scene.setSceneRect(x,y,w,h)
                except Exception:
                    pass
            if 'scale' in state:
                cur = self.transform().m11()
                target = float(state['scale'])
                if target > 0 and abs(target - cur) > 1e-3:
                    factor = target / cur
                    self.scale(factor, factor)
            if 'center_x' in state and 'center_y' in state:
                cx = float(state['center_x']); cy = float(state['center_y'])
                self.centerOn(cx, cy)
                # 二次延迟校正：模块增量加载或字体渲染完成后可能改变 boundingRect
                from PyQt6.QtCore import QTimer
                def _second_pass():
                    try:
                        self.centerOn(cx, cy)
                    except Exception:
                        pass
                QTimer.singleShot(200, _second_pass)
            if 'show_grid' in state:
                self.show_grid = bool(state['show_grid'])
            if 'dark_theme' in state:
                self.set_dark_theme(bool(state['dark_theme']))
            self.viewport().update()
        except Exception as e:
            print(f"恢复视图状态失败: {e}")

    def _on_selection_changed(self):
        try:
            sel = self.scene.selectedItems()
        except RuntimeError:
            return
        if sel and isinstance(sel[0], ModuleItem):
            self.module_selected.emit(sel[0])

    # Context menu
    def contextMenuEvent(self, event):
        if getattr(self, '_suppress_next_context', False):
            self._suppress_next_context = False
            return
        if self._locked:
            return  # 锁定时不弹编辑菜单
        from app.pipeline.module_registry import list_registered_modules, get_module_class
        from app.pipeline.base_module import ModuleType
        menu = QMenu(self)
        # 语言辅助
        try:
            from app.utils.i18n import get_language_mode
            def L(cn: str, en: str):
                mode = get_language_mode()
                if mode == 'zh': return cn
                if mode == 'en': return en
                return f"{cn} {en}"
        except Exception:
            def L(cn: str, en: str):
                return cn
        # 新分类映射 (名称/前缀模式归类): 输入 / 模型 / 显示 / 存储 / 协议 / 脚本 / 逻辑 / 其它
        groups = {'输入': [], '模型': [], '显示': [], '存储': [], '协议': [], '脚本': [], '逻辑': [], '其它': []}
        names = list_registered_modules()
        for name in names:
            low = name.lower()
            cls = get_module_class(name)
            # 模块类型用于基础分类，名称用于细化
            try:
                mtype = cls(name=name).module_type if cls else ModuleType.CUSTOM
            except Exception:
                mtype = ModuleType.CUSTOM
            target_key = '其它'
            if mtype in [ModuleType.CAMERA, ModuleType.TRIGGER] or ('路径' in name):
                target_key = '输入'
            elif mtype == ModuleType.MODEL or 'yolov8' in low or 'model' in low:
                target_key = '模型'
            elif ('展示' in name) or ('显示' in name):
                target_key = '显示'
            elif ('保存' in name) or ('save' in low):
                target_key = '存储'
            elif 'modbus' in low:
                target_key = '协议'
            elif '脚本' in name or 'script' in low:
                target_key = '脚本'
            elif ('逻辑' in name) or ('延时' in name) or ('示例' in name) or ('文本输入' in name) or ('打印' == name) or ('print' in low):
                target_key = '逻辑'
            groups[target_key].append(name)
        for g, items in groups.items():
            if not items:
                continue
            # 分类标题双语
            sub = menu.addMenu({
                '输入': L('输入','Input'),
                '模型': L('模型','Model'),
                '显示': L('显示','Display'),
                '存储': L('存储','Storage'),
                '协议': L('协议','Protocol'),
                '脚本': L('脚本','Script'),
                '逻辑': L('逻辑','Logic'),
                '其它': L('其它','Other')
            }[g])
            for it in sorted(items):
                act = QAction(it, self)
                act.triggered.connect(lambda checked, t=it: self.add_module(t))
                sub.addAction(act)
        menu.addSeparator()
        copy_act = QAction(L("复制","Copy"), self); copy_act.triggered.connect(self.copy_selection)
        paste_act = QAction(L("粘贴","Paste"), self); paste_act.triggered.connect(self.paste_selection)
        del_act = QAction(L("删除","Delete"), self); del_act.triggered.connect(self.delete_selection)
        undo_act = QAction(L("撤销","Undo"), self); undo_act.triggered.connect(self.undo)
        redo_act = QAction(L("重做","Redo"), self); redo_act.triggered.connect(self.redo)
        menu.addActions([copy_act, paste_act, del_act, undo_act, redo_act])
        menu.addSeparator()
        clear_act = QAction(L("清空画布","Clear Canvas"), self); clear_act.triggered.connect(self.clear)
        menu.addAction(clear_act)
        # 分组相关：若选择了多个模块，提供创建分组
        sel_modules = [it for it in self.scene.selectedItems() if isinstance(it, ModuleItem)]
        if len(sel_modules) >= 2:
            group_act = QAction(L("创建分组","Create Group"), self)
            group_act.triggered.connect(lambda: self._create_group_from_selection(sel_modules))
            menu.addAction(group_act)
        # 分组单选操作：重命名 / 删除
        sel_groups = [it for it in self.scene.selectedItems() if isinstance(it, GroupBoxItem)]
        if len(sel_groups) == 1:
            g = sel_groups[0]
            rename_act = QAction(L("重命名分组","Rename Group"), self); rename_act.triggered.connect(lambda: self._rename_group(g))
            del_act = QAction(L("删除分组","Delete Group"), self); del_act.triggered.connect(lambda: self._delete_group(g))
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
        if self._locked:
            event.ignore(); return
        if event.mimeData().hasFormat('application/x-fahai-module') or event.mimeData().text():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._locked:
            event.ignore(); return
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
        if self._locked:
            event.ignore(); QToolTip.hideText(); return
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
        if event.key() == Qt.Key.Key_Delete and not self._locked:
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
        if self._locked:
            return
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
                # 累计距离（缓慢拖动仍视为平移）
                self._pan_accum_dist += delta.manhattanLength()
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
            # 计算按住时长
            press_duration = 0
            try:
                if self._pan_press_time is not None:
                    now_ms = int(QTime.currentTime().msecsSinceStartOfDay())
                    press_duration = now_ms - self._pan_press_time
            except Exception:
                pass
            should_suppress = False
            if self._pan_moved:
                should_suppress = True
            elif press_duration >= self._pan_time_threshold:
                should_suppress = True
            elif self._pan_accum_dist >= self._pan_accum_threshold:
                should_suppress = True
            if should_suppress:
                self._pan_moved = False
                self._suppress_next_context = True
                self._pan_press_time = None
                self._pan_accum_dist = 0
                event.accept(); return
            # 没有满足平移意图 -> 视为普通点击
            self._pan_press_time = None
            self._pan_accum_dist = 0
        if self._locked:
            self.cancel_temp_connection()
            super().mouseReleaseEvent(event)
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
            try:
                self._pan_press_time = int(QTime.currentTime().msecsSinceStartOfDay())
            except Exception:
                self._pan_press_time = None
            self._pan_accum_dist = 0
            event.accept()
            return
        if self._locked and event.button() == Qt.MouseButton.LeftButton:
            event.accept(); return  # 锁定时左键不触发选择/拖动
        super().mousePressEvent(event)

    def finalize_temp_connection(self, end_point):
        if not self.temp_connection_start or not self.temp_line:
            return
        if end_point.parent_item == self.temp_connection_start.parent_item:
            self.cancel_temp_connection()
            return
        if self._locked:
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
            # 使用 scenePos() 而不是 rect.x()/rect.y()，避免位置总是保存为 0 导致重载偏移
            gpos = g.scenePos()
            groups.append({
                'group_id': getattr(g,'group_id',''),
                'title': g.title.toPlainText() if hasattr(g,'title') else '分组',
                'x': gpos.x(), 'y': gpos.y(), 'width': rect.width(), 'height': rect.height(),
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
        if self._locked:
            return
        sel = [it for it in self.scene.selectedItems() if isinstance(it, ModuleItem)]
        self._clipboard = []
        for m in sel:
            self._clipboard.append({'module_type': m.module_type,'x': m.scenePos().x(),'y': m.scenePos().y()})

    def paste_selection(self):
        if self._locked:
            return
        if not self._clipboard:
            return
        for m in self._clipboard:
            self.add_module_at(m['module_type'], QPointF(m['x']+30, m['y']+30))
        self._record_history()

    def duplicate_selection(self):
        if self._locked:
            return
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
        if self._locked:
            return
        removed_any = False
        # 支持仅删除连接线
        try:
            from app.gui.connection_graphics import BetterConnectionLine
        except Exception:
            BetterConnectionLine = None  # type: ignore
        if BetterConnectionLine:
            selected_lines = [it for it in self.scene.selectedItems() if isinstance(it, BetterConnectionLine)]
            for line in list(selected_lines):
                try:
                    self._remove_connection(line)
                    removed_any = True
                except Exception:
                    pass
        # 删除模块
        to_delete_modules = [it for it in self.scene.selectedItems() if isinstance(it, ModuleItem)]
        for m in to_delete_modules:
            # 断开关联连接
            try:
                for p in getattr(m, 'output_points', []):
                    for line in list(getattr(p, 'connections', [])):
                        self._remove_connection(line)
                for p in getattr(m, 'input_points', []):
                    for line in list(getattr(p, 'connections', [])):
                        self._remove_connection(line)
            except Exception:
                pass
        for m in to_delete_modules:
            try:
                if m in self.modules:
                    self.modules.remove(m)
                self.scene.removeItem(m)
                removed_any = True
            except Exception:
                pass
        if removed_any:
            self._cleanup_orphan_connections()
            self._record_history()

    def _record_history(self):
        snapshot = self.export_structure()
        if self._history_index < len(self._history)-1:
            self._history = self._history[:self._history_index+1]
        self._history.append(snapshot)
        self._history_index = len(self._history)-1

    def undo(self):
        if self._locked:
            return
        if self._history_index > 0:
            self._history_index -= 1
            self._restore_snapshot(self._history[self._history_index])

    def redo(self):
        if self._locked:
            return
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

    def set_locked(self, locked: bool):
        """外部设置锁定状态。锁定后禁止修改结构，仍允许查看与缩放。"""
        self._locked = bool(locked)
        # 视图交互：保持选择可见性但禁止拖动
        for m in self.modules:
            m.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, not self._locked)
        self.setDragMode(QGraphicsView.DragMode.NoDrag if self._locked else QGraphicsView.DragMode.RubberBandDrag)
        self.viewport().setCursor(Qt.CursorShape.ForbiddenCursor if self._locked else Qt.CursorShape.ArrowCursor)

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
            # 连接线数据流激活：源模块所有输出连接标记为 active
            for p in getattr(item, 'output_points', []):
                for line in getattr(p, 'connections', []):
                    try:
                        line.set_status('active')
                    except Exception:
                        pass
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
                # 在结束阶段，恢复连接线状态为 normal（若仍存在）
                for p in getattr(item, 'output_points', []):
                    for line in getattr(p, 'connections', []):
                        try:
                            line.set_status('normal')
                        except Exception:
                            pass
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
