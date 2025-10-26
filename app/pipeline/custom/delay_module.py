#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""(moved) 延时模块"""
import time
from typing import Dict, Any
from app.pipeline.base_module import BaseModule, ModuleType, ModuleCapabilities
try:
    from pydantic import BaseModel, validator
except ImportError:
    BaseModel = object  # type: ignore

class DelayModule(BaseModule):
    CAPABILITIES = ModuleCapabilities(
        supports_async=False,
        supports_batch=False,
        may_block=True,
        resource_tags=["delay"],
        throughput_hint=5.0,
    )

    class ConfigModel(BaseModel):  # type: ignore
        delay_seconds: float = 0.5

        @validator("delay_seconds")
        def _non_negative(cls, v):
            if v < 0:
                raise ValueError("delay_seconds 必须 >= 0")
            return v

    def __init__(self, name: str = "延时模块"):
        self.delay_seconds = 0.5
        super().__init__(name)
    @property
    def module_type(self) -> ModuleType:
        return ModuleType.CUSTOM
    def _define_ports(self):
        if not self.input_ports:
            self.register_input_port("text", port_type="string", desc="输入文本", required=True)
        if not self.output_ports:
            self.register_output_port("delayed_text", port_type="string", desc="延时后的文本")
    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        txt = inputs.get("text")
        if txt is None:
            return {"delayed_text": "(无输入)"}
        time.sleep(self.delay_seconds)
        return {"delayed_text": txt}
    def _on_configure(self, config: Dict[str, Any]):
        if "delay_seconds" in config:
            # pydantic 已验证非负
            self.delay_seconds = float(config["delay_seconds"])
    def get_status(self) -> Dict[str, Any]:
        base = super().get_status(); base["delay_seconds"] = self.delay_seconds; return base
