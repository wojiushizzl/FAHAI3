#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Modbus 写入模块 / Modbus Writer Module
输入: connect (Modbus 客户端), value (任意可转布尔/整数的值)
根据 function 配置写入 coil 或 holding register。
支持值格式: True/False/0/1/"true"/"false"/"on"/"off"/数字字符串。

Outputs:
  success(bool): 写入是否成功 / Whether the write succeeded
  last_value(int): 最后写入的原始数值 (coil 时为 0/1) / Last raw value written (0/1 for coil)
"""
from typing import Any, Dict
from app.pipeline.base_module import BaseModule, ModuleType, ModuleCapabilities

try:
    from pydantic import BaseModel, validator
except ImportError:  # Fallback if pydantic not present at import time
    BaseModel = object  # type: ignore

class ModbusWriterModule(BaseModule):
    CAPABILITIES = ModuleCapabilities(may_block=True, resource_tags=["modbus"], throughput_hint=20.0)

    class ConfigModel(BaseModel):  # type: ignore
        address: int = 0
        unit_id: int = 1
        function: str = "coil"  # coil | holding
        invert: bool = False  # 写入前反转布尔意义 / invert boolean meaning before writing

        @validator("function")
        def _func_ok(cls, v):
            if v not in {"coil", "holding"}:
                raise ValueError("function 必须是 coil|holding 之一")
            return v

    def __init__(self, name: str = "modbus写入"):
        super().__init__(name)
        self._last_value = 0

    @property
    def module_type(self) -> ModuleType:
        return ModuleType.CUSTOM

    def _define_ports(self):
        self.register_input_port("connect", port_type="modbus", desc="Modbus连接 / Modbus connection", required=True)
        self.register_input_port("value", port_type="any", desc="写入值 (True/False/0/1/字符串) / Value to write", required=True)
        self.register_output_port("success", port_type="bool", desc="写入是否成功 / Write success")
        self.register_output_port("last_value", port_type="int", desc="最后写入原始值 / Last raw value written")

    def _coerce_value(self, v: Any, fn: str) -> int:
        """统一将输入值转成整数: coil 用 0/1, holding 直接取整数。"""
        if isinstance(v, bool):
            return 1 if v else 0
        if isinstance(v, (int, float)):
            return int(v)
        if isinstance(v, str):
            s = v.strip().lower()
            if s in {"true", "on", "yes", "1"}:
                return 1
            if s in {"false", "off", "no", "0"}:
                return 0
            # 尝试按数字
            try:
                return int(float(s))
            except ValueError:
                return 0
        # 其他类型尝试 bool() 再转
        try:
            return 1 if bool(v) else 0
        except Exception:
            return 0

    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        client = inputs.get("connect")
        if client is None:
            return {"success": False, "last_value": self._last_value}
        fn = self.config.get("function", "coil")
        addr = int(self.config.get("address", 0))
        unit = int(self.config.get("unit_id", 1))
        invert = bool(self.config.get("invert", False))
        raw_in = inputs.get("value")
        coerced = self._coerce_value(raw_in, fn)
        if fn == "coil":
            bool_val = bool(coerced)
            if invert:
                bool_val = not bool_val
            write_val = 1 if bool_val else 0
        else:  # holding
            write_val = coerced
            if invert:  # 对 holding invert 定义为若非零则写 0, 若零则写 1
                write_val = 0 if write_val else 1

        # 兼容不同 pymodbus 版本: write 方法可能不接受 unit 参数
        def _write_call(method_name: str, *m_args, **m_kwargs):
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

        success = False
        try:
            if fn == "coil":
                rr = _write_call('write_coil', addr, bool(write_val))
            else:
                rr = _write_call('write_register', addr, int(write_val))
            if rr is not None and hasattr(rr, 'isError') and rr.isError():
                self.logger.warning(f"写入失败: {rr}")
            else:
                # 如果返回对象没有 isError 或 isError False，我们认为成功
                success = rr is not None
        except Exception as e:
            self.logger.error(f"写入异常: {e}")
            success = False

        if success:
            self._last_value = int(write_val)
        return {"success": success, "last_value": self._last_value}