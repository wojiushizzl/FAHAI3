#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检测结果布尔判断模块 (YoloResultBoolModule)

读取上游 YOLO 检测(或其它检测)输出的列表/结构, 判断是否包含目标关键字/类别, 输出布尔标志 flag。

判定规则(尽量宽松):
- 若元素为字符串: substr 匹配 (target in element)
- 若元素为 dict: 依次检查键: name/label/class/category 以及所有字符串值是否包含 target
- 若元素具备属性 name/label/class_name: 读取并匹配
- 否则将元素转为字符串再匹配
- 若 target 为空字符串: 只要结果非空即 True

配置:
- target: str  要匹配的子串 (默认 'x')
- invert: bool  是否反转输出 (默认 False)
- input_key: str 输入端口或输入字典中使用的键 (默认 'results')

输入端口:
- results (泛型, list/tuple/any)

输出端口:
- flag (bool) 判定结果 (invert 后)
- matched (bool) 未反转的原始匹配标志 (便于调试)

说明:
该模块不直接中断流程，如需根据 flag 中断，请连接到 布尔闸门 模块。
"""
from __future__ import annotations
from typing import Dict, Any, Iterable
from app.pipeline.base_module import BaseModule, ModuleType

try:
    from pydantic import BaseModel, Field
except ImportError:  # 兼容缺少 pydantic 的环境
    class BaseModel:  # type: ignore
        def __init__(self, **data):
            for k,v in data.items():
                setattr(self, k, v)
        def dict(self):
            return self.__dict__
    def Field(default=None, **kwargs):  # type: ignore
        return default

class YoloResultBoolModule(BaseModule):
    class ConfigModel(BaseModel):
        target: str = Field('x', description='要匹配的目标子串 (为空则只要结果非空即 True)')
        invert: bool = Field(False, description='是否反转最终输出 flag')
        input_key: str = Field('results', description='输入中检测结果的键名')

    def _define_ports(self):
        self.input_ports = {}
        self.output_ports = {}
        self.register_input_port('results', port_type='generic', desc='检测结果列表或结构', required=False)
        self.register_output_port('flag', port_type='bool', desc='布尔判定输出')
        self.register_output_port('matched', port_type='bool', desc='原始匹配(未反转)')

    @property
    def module_type(self) -> ModuleType:
        # 归类为后处理
        return ModuleType.POSTPROCESS

    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        cfg = self.config
        target = str(cfg.get('target', 'x'))
        input_key = cfg.get('input_key', 'results')
        invert = bool(cfg.get('invert', False))

        data = inputs.get(input_key)
        matched = False
        if data is not None:
            matched = self._match_any(data, target)
            if target == '':  # 空 target: 只要有数据
                try:
                    if isinstance(data, (list, tuple, set, dict)):
                        matched = len(data) > 0
                    else:
                        matched = True  # 任意非 None 即 True
                except Exception:
                    matched = True
        flag = (not matched) if invert else matched
        return {'flag': flag, 'matched': matched}

    # ---- 内部工具 ----
    def _match_any(self, data: Any, target: str) -> bool:
        if target == '':
            # 空 target 交由外层逻辑
            return False
        try:
            # 如果是 YOLOv8 Results 对象或类似, 尝试常见属性
            # 这里不强依赖ultralytics, 避免导入失败
            pass
        except Exception:
            pass
        if isinstance(data, (list, tuple, set)):
            for item in data:
                if self._match_item(item, target):
                    return True
            return False
        if isinstance(data, dict):
            # dict 视为: maybe {"detections": [...]} 等
            for v in data.values():
                if self._match_item(v, target):
                    return True
            return False
        # 单一对象
        return self._match_item(data, target)

    def _match_item(self, item: Any, target: str) -> bool:
        try:
            if item is None:
                return False
            # 字符串
            if isinstance(item, str):
                return target in item
            # dict 逐字段检查
            if isinstance(item, dict):
                # 优先常见键
                for key in ('name','label','class','class_name','category'):
                    if key in item and isinstance(item[key], str) and target in item[key]:
                        return True
                # 任意字符串值
                for v in item.values():
                    if isinstance(v, str) and target in v:
                        return True
                return False
            # 具名属性
            for attr in ('name','label','class_name','category'):
                if hasattr(item, attr):
                    val = getattr(item, attr)
                    if isinstance(val, str) and target in val:
                        return True
            # YOLOv8 detection boxes 可能有 .cls 属性 (数字); 需要映射 names 列表但此处无法获取
            # 退化为字符串化匹配
            s = str(item)
            return target in s
        except Exception:
            return False

__all__ = ['YoloResultBoolModule']
