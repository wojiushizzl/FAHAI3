#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Modbus 监听模块
输入: connect (Modbus 客户端)
定期读取指定地址 (coil/discrete/holding/input register) 并输出布尔值。
支持上升沿检测: 输出 edge True 仅在 False->True 转换的周期。
"""
from typing import Any, Dict
from app.pipeline.base_module import BaseModule, ModuleType, ModuleCapabilities

try:
    from pydantic import BaseModel, validator
except ImportError:
    BaseModel = object  # type: ignore

class ModbusListenerModule(BaseModule):
    CAPABILITIES = ModuleCapabilities(may_block=True, resource_tags=["modbus"], throughput_hint=10.0)

    class ConfigModel(BaseModel):  # type: ignore
        address: int = 0
        unit_id: int = 1
        function: str = "coil"  # coil | discrete | holding | input
        edge_mode: str = "rising"  # rising | falling | any | level
        invert: bool = False

        @validator("function")
        def _func_ok(cls, v):
            if v not in {"coil", "discrete", "holding", "input"}:
                raise ValueError("function 必须是 coil|discrete|holding|input 之一")
            return v

        @validator("edge_mode")
        def _edge_ok(cls, v):
            if v not in {"rising", "falling", "any", "level"}:
                raise ValueError("edge_mode 必须是 rising|falling|any|level 之一")
            return v

    def __init__(self, name: str = "modbus监听"):
        super().__init__(name)
        self._prev_raw = False

    @property
    def module_type(self) -> ModuleType:
        return ModuleType.CUSTOM

    def _define_ports(self):
        self.register_input_port("connect", port_type="modbus", desc="Modbus连接", required=True)
        self.register_output_port("value", port_type="bool", desc="当前布尔值")
        self.register_output_port("edge", port_type="bool", desc="上升沿触发")

    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        client = inputs.get("connect")
        if client is None:
            return {"value": False, "edge": False}
        addr = int(self.config.get("address", 0))
        unit = int(self.config.get("unit_id", 1))
        fn = self.config.get("function", "coil")
        invert = bool(self.config.get("invert", False))
        raw = False
        try:
            if fn == "coil":
                rr = client.read_coils(addr, 1, unit=unit)
                if rr and hasattr(rr, 'bits'):
                    raw = bool(rr.bits[0])
            elif fn == "discrete":
                rr = client.read_discrete_inputs(addr, 1, unit=unit)
                if rr and hasattr(rr, 'bits'):
                    raw = bool(rr.bits[0])
            elif fn == "holding":
                rr = client.read_holding_registers(addr, 1, unit=unit)
                if rr and hasattr(rr, 'registers'):
                    raw = rr.registers[0] != 0
            elif fn == "input":
                rr = client.read_input_registers(addr, 1, unit=unit)
                if rr and hasattr(rr, 'registers'):
                    raw = rr.registers[0] != 0
        except Exception as e:
            self.logger.error(f"读取地址异常: {e}")
        if invert:
            raw = not raw
        prev = self._prev_raw
        rising = (raw and not prev)
        falling = ((not raw) and prev)
        any_change = (raw != prev)
        self._prev_raw = raw
        mode = self.config.get("edge_mode", "rising")
        if mode == "rising":
            edge_out = rising
        elif mode == "falling":
            edge_out = falling
        elif mode == "any":
            edge_out = any_change
        else:  # level
            edge_out = False  # 仅提供电平值在 value，edge 不触发
        return {"value": raw, "edge": edge_out}
