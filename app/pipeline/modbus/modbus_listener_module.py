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
        count: int = 1  # 读取数量 (寄存器/位数)

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

        @validator("count")
        def _count_ok(cls, v):
            if v <= 0:
                raise ValueError("count 必须 > 0")
            # 常见 Modbus 限制: 一次最多读取 125 个 holding/input register, 2000 bits for coils (这里简单限制 1000)
            if v > 1000:
                raise ValueError("count 太大 (<=1000)")
            return v

    def __init__(self, name: str = "modbus监听"):
        super().__init__(name)
        self._prev_raw = False

    @property
    def module_type(self) -> ModuleType:
        return ModuleType.CUSTOM

    def _define_ports(self):
        self.register_input_port("connect", port_type="modbus", desc="Modbus连接", required=True)
        self.register_output_port("value", port_type="bool", desc="当前布尔值 / Current level")
        self.register_output_port("result", port_type="bool", desc="边沿结果: 触发为 True / Edge detect output")

    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        client = inputs.get("connect")
        if client is None:
            return {"value": False, "result": False}
        addr = int(self.config.get("address", 0))
        unit = int(self.config.get("unit_id", 1))
        fn = self.config.get("function", "coil")
        invert = bool(self.config.get("invert", False))
        count = int(self.config.get("count", 1))
        raw_bool = False
    # regs_list removed per simplified output requirement
        # 兼容不同 pymodbus 版本: 有的 read_* 方法不接受 unit 关键字参数
        def _read_call(method_name: str, *m_args, **m_kwargs):
            method = getattr(client, method_name, None)
            if not method:
                return None
            try:
                return method(*m_args, unit=unit, **m_kwargs)
            except TypeError as e:
                if 'unexpected keyword argument' in str(e) and 'unit' in str(e):
                    try:
                        return method(*m_args, **m_kwargs)
                    except Exception:
                        return None
                return None
            except Exception:
                return None
        try:
            if fn == "coil":
                rr = _read_call('read_coils', addr, count)
                if rr and hasattr(rr, 'isError') and rr.isError():
                    self.logger.warning(f"读取 coil 失败: {rr}")
                if rr and hasattr(rr, 'bits') and rr.bits:
                    raw_bool = bool(rr.bits[0])
            elif fn == "discrete":
                rr = _read_call('read_discrete_inputs', addr, count)
                if rr and hasattr(rr, 'isError') and rr.isError():
                    self.logger.warning(f"读取 discrete 输入失败: {rr}")
                if rr and hasattr(rr, 'bits') and rr.bits:
                    raw_bool = bool(rr.bits[0])
            elif fn == "holding":
                rr = _read_call('read_holding_registers', addr, count)
                if rr and hasattr(rr, 'isError') and rr.isError():
                    self.logger.warning(f"读取 holding register 失败: {rr}")
                if rr and hasattr(rr, 'registers') and rr.registers:
                    raw_bool = bool(rr.registers[0])
            elif fn == "input":
                rr = _read_call('read_input_registers', addr, count)
                if rr and hasattr(rr, 'isError') and rr.isError():
                    self.logger.warning(f"读取 input register 失败: {rr}")
                if rr and hasattr(rr, 'registers') and rr.registers:
                    raw_bool = bool(rr.registers[0])
        except Exception as e:
            self.logger.error(f"读取地址异常: {e}")
        if invert:
            raw_bool = not raw_bool
        prev = self._prev_raw
        rising = (raw_bool and not prev)
        falling = ((not raw_bool) and prev)
        any_change = (raw_bool != prev)
        self._prev_raw = raw_bool
        mode = self.config.get("edge_mode", "rising")
        if mode == "rising":
            result_out = rising
        elif mode == "falling":
            result_out = falling
        elif mode == "any":
            result_out = any_change
        else:  # level 直接输出当前电平
            result_out = raw_bool
        return {"value": raw_bool, "result": result_out}
