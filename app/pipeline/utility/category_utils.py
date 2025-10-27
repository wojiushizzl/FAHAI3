#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模块分类与配色工具

集中维护: 名称/类型 -> 分类 逻辑，及分类 -> 颜色 对应，避免 GUI 多处重复硬编码。

分类集合: 输入 / 模型 / 显示 / 存储 / 协议 / 脚本 / 逻辑 / 其它
"""
from __future__ import annotations
from typing import Tuple, Optional
from app.pipeline.base_module import ModuleType
from PyQt6.QtGui import QColor

CATEGORY_NAMES = ['输入', '模型', '显示', '存储', '协议', '脚本', '逻辑', '其它']

def classify_module(display_name: str, module_type: Optional[ModuleType]) -> str:
    """根据显示名称与基础 ModuleType 推断统一分类。
    Args:
        display_name: 注册显示名称 (中文/英文)
        module_type: 基础模块类型 (可能为 None)
    Returns: 分类名称 (在 CATEGORY_NAMES 中)
    """
    if not display_name:
        return '其它'
    name = display_name
    low = name.lower()
    try:
        if (module_type in [ModuleType.CAMERA, ModuleType.TRIGGER]) or ('路径' in name):
            return '输入'
        if (module_type == ModuleType.MODEL) or ('yolov8' in low) or ('model' in low) or ('模型' in name):
            return '模型'
        if ('展示' in name) or ('显示' in name):
            return '显示'
        if ('保存' in name) or ('save' in low):
            return '存储'
        if 'modbus' in low:
            return '协议'
        if ('脚本' in name) or ('script' in low):
            return '脚本'
        if ('逻辑' in name) or ('延时' in name) or ('示例' in name) or ('文本输入' in name) or (name == '打印') or ('print' in low) or ('布尔' in name):
            return '逻辑'
    except Exception:
        return '其它'
    return '其它'

def category_color_pair(category: str, dark: bool = False) -> Tuple[QColor, QColor]:
    """返回分类对应的 (c1,c2) 渐变颜色。dark 为暗色主题调整。
    未知分类回退到 '其它'。
    """
    mapping = {
        '输入': (QColor(76,175,80), QColor(102,187,106)),
        '模型': (QColor(142,36,170), QColor(171,71,188)),
        '显示': (QColor(30,136,229), QColor(66,165,245)),
        '存储': (QColor(109,76,65), QColor(141,110,99)),
        '协议': (QColor(251,140,0), QColor(255,167,38)),
        '脚本': (QColor(84,110,122), QColor(120,144,156)),
        '逻辑': (QColor(57,73,171), QColor(92,107,192)),
        '其它': (QColor(117,117,117), QColor(158,158,158)),
    }
    c1, c2 = mapping.get(category, mapping['其它'])
    if dark:
        def dim(col, f):
            return QColor(int(col.red()*f), int(col.green()*f), int(col.blue()*f))
        c1 = dim(c1, 0.55); c2 = dim(c2, 0.65)
    return c1, c2

__all__ = ['classify_module', 'category_color_pair', 'CATEGORY_NAMES']
