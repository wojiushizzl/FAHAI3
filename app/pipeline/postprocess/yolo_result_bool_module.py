#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检测结果布尔判断模块 / Detection Result Boolean Judge (YoloResultBoolModule)

功能 / Purpose:
    读取上游 YOLO 检测(或其它检测)输出的列表/结构, 判断是否包含目标关键字/类别, 输出布尔标志 flag。
    Read upstream YOLO (or other) detection outputs and decide if any element matches target tokens.

判定规则 / Matching Rules:
    - 字符串: 使用 substring 包含匹配 (target in element)
    - dict: 检查键 name/label/class/category/class_name 以及所有字符串值
    - 对象: 若具备上述属性之一则读取并匹配; 否则转为字符串匹配
    - target 为空: 结果非空即可 True
    - 多 token (runtime 输入) 时: 任意一个 token 命中即可

配置 / Config Fields:
    - target: 默认匹配子串 (default 'x')
    - invert: 是否反转最终结果 / invert final flag
    - input_key: 输入中结果的键名 / key holding results

新增运行时输入 / New Runtime Input:
    - target_text: 运行时覆盖 target, 支持逗号/空格/分号分隔多个 token。
        Overrides config target with comma/space/semi-colon separated tokens.

输入端口 / Input Ports:
    - results: 检测结果列表或结构 / detection result list or structure
    - target_text: 动态匹配目标文本(覆盖配置) / dynamic target tokens overriding config

输出端口 / Output Ports:
    - flag: 最终布尔 (考虑 invert) / final bool (after invert)
    - matched: 原始匹配 (未反转) / raw matched before invert

说明 / Notes:
    模块不直接中断流程，若需中断请连接布尔闸门模块。
    This module does not itself gate execution; chain to BoolGateModule to skip branches.
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
        # 新增动态目标文本输入: 若提供则覆盖 config.target, 支持逗号/空格/分号分隔多个 token
        self.register_input_port(
            'target_text',
            port_type='text',
            desc='动态匹配目标文本(覆盖配置) / runtime target tokens',
            required=False
        )
        self.register_output_port('flag', port_type='bool', desc='布尔判定输出')
        self.register_output_port('matched', port_type='bool', desc='原始匹配(未反转)')

    @property
    def module_type(self) -> ModuleType:
        # 归类为后处理
        return ModuleType.POSTPROCESS

    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        cfg = self.config
        target = str(cfg.get('target', 'x'))
        # 若存在运行时输入 target_text 则覆盖配置 target
        runtime_target_text = inputs.get('target_text')
        runtime_tokens: list[str] = []
        if isinstance(runtime_target_text, str) and runtime_target_text.strip():
            # 允许逗号/分号/空格分隔
            for part in runtime_target_text.replace(';', ' ').split(','):
                for tok in part.split():
                    t = tok.strip()
                    if t:
                        runtime_tokens.append(t)
            if runtime_tokens:
                # 多 token 时只要任意一个匹配即视为 matched
                target_tokens = runtime_tokens
            else:
                target_tokens = [target]
        else:
            target_tokens = [target]
        input_key = cfg.get('input_key', 'results')
        invert = bool(cfg.get('invert', False))

        data = inputs.get(input_key)
        matched = False
        if data is not None:
            # 多 token 匹配: 任意一个命中视为 True；空字符串 token 特殊: 只要有数据即 True
            for tk in target_tokens:
                single_match = self._match_any(data, tk)
                if tk == '':  # 空 token: 有数据即可
                    try:
                        if isinstance(data, (list, tuple, set, dict)):
                            single_match = len(data) > 0
                        else:
                            single_match = True
                    except Exception:
                        single_match = True
                if single_match:
                    matched = True
                    break
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
