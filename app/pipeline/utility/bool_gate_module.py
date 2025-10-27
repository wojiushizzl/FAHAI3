#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""布尔闸门模块 BoolGateModule

功能: 接收一个布尔输入 flag。
 - flag 为 True: 输出 passed=True，流程继续。
 - flag 为 False: 输出 passed=False，并请求当前执行轮次后续模块中断 (顺序执行模式)。

执行器支持: 在顺序执行 (sequential) 和 run_once 路径中检测模块属性 request_abort 来提前结束。
并行/自适应并发暂未实现级联终止——如果在并行模式下使用将仅影响已执行层后的顺序部分。
"""
from __future__ import annotations
from typing import Dict, Any
from app.pipeline.base_module import BaseModule, ModuleType

class BoolGateModule(BaseModule):
    name = "布尔闸门"

    def _define_ports(self):
        # 覆盖默认端口定义
        self.input_ports = {}
        self.output_ports = {}
        self.register_input_port('flag', port_type='bool', desc='布尔条件', required=True)
        self.register_output_port('passed', port_type='bool', desc='是否通过')

    @property
    def module_type(self) -> ModuleType:  # 归为自定义，分类逻辑按名称映射到 逻辑
        return ModuleType.CUSTOM

    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        flag = bool(inputs.get('flag', False))
        # 将上一轮的请求清除
        if hasattr(self, 'request_abort'):
            try:
                delattr(self, 'request_abort')
            except Exception:
                pass
        if not flag:
            # 标记请求执行器终止当前剩余节点
            self.request_abort = True  # 执行器顺序模式检查此属性
        return {'passed': flag}

__all__ = ['BoolGateModule']
