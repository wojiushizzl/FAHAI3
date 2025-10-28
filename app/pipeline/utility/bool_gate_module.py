#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""布尔闸门模块 BoolGateModule

功能: 接收一个布尔/状态输入 flag。
 - flag 为 True: 输出 passed=True，仅继续该分支。
 - flag 为 False: 输出 passed=False，并请求跳过“当前节点的所有后继节点(其可达子图)”，不再全局中断其它独立分支。

兼容输入自动转换 (_coerce_bool):
    支持常见字符串: OK/ok/true/yes/1/pass/success -> True; NOK/nok/false/no/0/ng/fail/error -> False
    支持数值: 0 为 False, 非 0 为 True
    其它类型按 Python bool() 规则

可选 invert 输入端口: invert=True 时对结果取反。

与旧行为差异: 之前使用 request_abort 直接终止整轮执行，导致未连接到闸门的其它模块也被跳过；现在改为设置 request_gate_block，由执行器只跳过该闸门的后继节点。
未连接任何后继模块时，闸门为 False 不再影响其它模块。
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
        self.register_input_port('flag', port_type='bool', desc='布尔条件/OKNOK', required=True)
        self.register_input_port('invert', port_type='bool', desc='反向解析', required=False)
        # 输出两个端口：passed(用于逻辑流转)，flag_out(原始/反转后布尔值直通)
        self.register_output_port('passed', port_type='bool', desc='是否通过')
        self.register_output_port('flag_out', port_type='bool', desc='闸门最终布尔值')
        self.register_output_port('gate_trigger', port_type='meta', desc='本轮是否触发阻断(true=阻断)')

    def _coerce_bool(self, value: Any) -> bool:
        """
        将各种输入强制转换为 bool。

        支持:
          - bool 直接返回
          - int/float: 0 -> False, 其他 -> True
          - str: true/yes/y/1/ok/pass/success -> True; false/no/n/0/nok/ng/fail/error -> False
          - 其他类型: Python bool() 计算
        """
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            v = value.strip().lower()
            true_set = {"true", "1", "yes", "y", "ok", "pass", "passed", "success"}
            false_set = {"false", "0", "no", "n", "nok", "ng", "fail", "failed", "error"}
            if v in true_set:
                return True
            if v in false_set:
                return False
            try:
                return float(v) != 0.0
            except Exception:
                return bool(v)
        return bool(value)

    @property
    def module_type(self) -> ModuleType:  # 归为自定义，分类逻辑按名称映射到 逻辑
        return ModuleType.CUSTOM

    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        raw_flag = inputs.get('flag', False)
        flag = self._coerce_bool(raw_flag)
        invert = self._coerce_bool(inputs.get('invert')) if 'invert' in inputs else False
        if invert:
            flag = not flag
        # 清除上一轮标记
        if hasattr(self, 'request_gate_block'):
            try:
                delattr(self, 'request_gate_block')
            except Exception:
                pass
        blocked = False
        if not flag:
            self.request_gate_block = True
            blocked = True
        return {'passed': flag, 'flag_out': flag, 'gate_trigger': blocked}

__all__ = ['BoolGateModule']
