#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""简易中英文双语辅助
提供 bilingual(label) 将常见关键词补充英文或中文。
后续可扩展为读取配置或使用更完整的翻译表。
"""
from __future__ import annotations

_MAPPING = {
    '输入': 'Input',
    '模型': 'Model',
    '显示': 'Display',
    '存储': 'Storage',
    '协议': 'Protocol',
    '脚本': 'Script',
    '逻辑': 'Logic',
    '其它': 'Other',
    '相机': 'Camera',
    '触发': 'Trigger',
    '后处理': 'Postprocess',
    '自定义': 'Custom',
    '检测': 'Detect',
    '分割': 'Segment',
    '分类': 'Classify',
    '图像': 'Image',
    '控制': 'Control',
}

# 反向也支持: 如果英文传入则补中文
_REVERSE = {v: k for k, v in _MAPPING.items()}

def bilingual(label: str) -> str:
    """返回 "中文 English" 组合, 如果 label 本身是英文尝试反向映射。
    已经包含两种语言时直接返回原值。
    """
    if not label:
        return label
    # 已经双语的简单检测: 空格分隔后同时有中文字符与英文字符
    has_space = ' ' in label
    if has_space:
        return label
    if label in _MAPPING:
        return f"{label} {_MAPPING[label]}"
    if label in _REVERSE:
        return f"{_REVERSE[label]} {label}"
    # 未知: 若包含中文字符则原样+首字母大写英文占位
    if any('\u4e00' <= ch <= '\u9fff' for ch in label):
        # 简单英文占位: 可后续完善
        return label
    return label  # 英文未知保持原样

__all__ = ["bilingual"]
