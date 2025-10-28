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

_LANG_MODE = 'both'  # zh | en | both

def set_language_mode(mode: str):
    global _LANG_MODE
    if mode not in ('zh','en','both'):
        return
    _LANG_MODE = mode

def get_language_mode() -> str:
    return _LANG_MODE

def translate(label: str) -> str:
    """按当前语言模式返回：
    - zh: 仅中文 (若输入英文且有反向映射则转中文)
    - en: 仅英文 (若输入中文且有映射则转英文)
    - both: bilingual(label)
    未知词保持原样。
    """
    if _LANG_MODE == 'both':
        return bilingual(label)
    if _LANG_MODE == 'zh':
        # 若是英文且有中文映射
        if label in _REVERSE:
            return _REVERSE[label]
        return label
    if _LANG_MODE == 'en':
        if label in _MAPPING:
            return _MAPPING[label]
        return label
    return label

def L(cn: str, en: str) -> str:
    """快捷双语文本: 根据模式返回中文 / 英文 / 组合"""
    mode = get_language_mode()
    if mode == 'zh':
        return cn
    if mode == 'en':
        return en
    return f"{cn} {en}"

__all__ = ["bilingual","set_language_mode","get_language_mode","translate","L"]
