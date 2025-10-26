#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Modbus 写入模块
输入: connect (Modbus 客户端), value (布尔)
根据配置对指定地址写入指定值。
支持: coil 写 0/1, holding register 写入 true_value / false_value。
"""
from typing import Any, Dict
from app.pipeline.base_module import BaseModule, ModuleType, ModuleCapabilities

try:
    from pydantic import BaseModel, validator
except ImportError:
    BaseModel = object  # type: ignore

class ModbusWriteModule(BaseModule):
    CAPABILITIES = ModuleCapabilities(may_block=True, resource_tags=["modbus"], throughput_hint=15.0)

    class ConfigModel(BaseModel):  # type: ignore
        address: int = 0
        unit_id: int = 1
        function: str = "coil"  # coil | holding
        true_value: int = 1
        false_value: int = 0
        write_on_change: bool = True
        safe_mode: bool = True  # 失败时不抛异常，只记录错误

        @validator("function")
        def _func_ok(cls, v):
            if v not in {"coil", "holding"}:
                raise ValueError("function 必须是 coil 或 holding")
            return v

    def __init__(self, name: str = "modbus输出"):
        super().__init__(name)
        self._prev_written = None  # 记录上次写入的布尔值

    @property
    def module_type(self) -> ModuleType:
        return ModuleType.CUSTOM

    def _define_ports(self):
        self.register_input_port("connect", port_type="modbus", desc="Modbus连接", required=True)
        self.register_input_port("value", port_type="bool", desc="要写入的布尔", required=True)
        self.register_output_port("written", port_type="bool", desc="本周期是否执行写入")
        self.register_output_port("result", port_type="bool", desc="写入逻辑状态")

    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        client = inputs.get("connect")
        val = inputs.get("value")
        if client is None or val is None:
            return {"written": False, "result": False}
        addr = int(self.config.get("address", 0))
        unit = int(self.config.get("unit_id", 1))
        fn = self.config.get("function", "coil")
        write_on_change = bool(self.config.get("write_on_change", True))
        tv = int(self.config.get("true_value", 1))
        fv = int(self.config.get("false_value", 0))
        bool_val = bool(val)
        need_write = True
        if write_on_change and self._prev_written is not None and self._prev_written == bool_val:
            need_write = False
        success = False
        if need_write:
            try:
                if fn == "coil":
                    # pymodbus 2.x/3.x: write_coil(address, value, unit=unit)
                    rr = client.write_coil(addr, bool_val, unit=unit)
                    success = (getattr(rr, 'isError', lambda: False)() is False)
                else:  # holding
                    value_to_write = tv if bool_val else fv
                    rr = client.write_register(addr, value_to_write, unit=unit)
                    success = (getattr(rr, 'isError', lambda: False)() is False)
            except Exception as e:
                self.logger.error(f"写入异常: {e}")
                if not self.config.get("safe_mode", True):
                    raise
        if need_write and success:
            self._prev_written = bool_val
        return {"written": need_write and success, "result": bool_val}
