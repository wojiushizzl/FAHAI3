#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""(moved) 文本输入模块"""
from typing import Dict, Any
from app.pipeline.base_module import BaseModule, ModuleType

class TextInputModule(BaseModule):
    def __init__(self, name: str = "文本输入模块", initial_text: str = "Hello"):
        self.text_value = initial_text
        super().__init__(name)
    @property
    def module_type(self) -> ModuleType:
        return ModuleType.CUSTOM
    def _define_ports(self):
        if not self.output_ports:
            self.register_output_port("text", port_type="string", desc="文本内容")
    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        return {"text": self.text_value}
    def set_text(self, value: str):
        self.text_value = value
    def _on_configure(self, config: Dict[str, Any]):
        if "text" in config:
            self.text_value = config["text"]
