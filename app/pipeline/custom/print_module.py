#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""(moved) 打印模块"""
from typing import Dict, Any
from app.pipeline.base_module import BaseModule, ModuleType

class PrintModule(BaseModule):
    def __init__(self, name: str = "打印模块"):
        self.last_text = None
        super().__init__(name)
    @property
    def module_type(self) -> ModuleType:
        return ModuleType.CUSTOM
    def _define_ports(self):
        if not self.input_ports:
            self.register_input_port("text", port_type="string", desc="待打印文本", required=True)
        if not self.output_ports:
            self.register_output_port("printed_text", port_type="string", desc="已打印文本")
    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        txt = inputs.get("text")
        if txt is None:
            return {"printed_text": "(无输入)"}
        self.last_text = txt
        print(f"[PrintModule] {txt}")
        return {"printed_text": txt}
