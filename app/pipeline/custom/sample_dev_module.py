#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SampleDevModule
开发者示例模块：演示如何创建自定义处理模块并注册到系统。

特点:
- 明确定义输入/输出端口
- 使用配置模型验证参数
- 在 process 中读取输入并返回转换结果

将此文件复制并修改，可快速创建新模块。
"""
from typing import Dict, Any
from pydantic import BaseModel, Field
from app.pipeline.base_module import BaseModule, ModuleType, ModuleCapabilities

class SampleConfig(BaseModel):
    multiplier: float = Field(1.0, description="数值乘法系数")
    enabled: bool = Field(True, description="是否启用计算")
    note: str | None = Field(None, description="备注")

class SampleDevModule(BaseModule):
    CAPABILITIES = ModuleCapabilities(supports_async=False, supports_batch=False, may_block=False, resource_tags=["cpu"], throughput_hint=200.0)

    def _define_ports(self):
        # 定义输入输出端口 (避免使用默认 in/out 以示例自定义)
        self.register_input_port("value", port_type="number", desc="输入数值", required=True)
        self.register_input_port("flag", port_type="bool", desc="开关标志")
        self.register_output_port("result", port_type="number", desc="计算结果")
        self.register_output_port("echo", port_type="any", desc="原始输入回显")

    @property
    def module_type(self) -> ModuleType:
        return ModuleType.CUSTOM

    def _initialize(self):
        # 初始化配置模型实例
        try:
            self._config_model = SampleConfig()
        except Exception:
            self._config_model = None

    def configure(self, cfg: Dict[str, Any]):
        """应用外部传入配置。"""
        if not cfg:
            return
        if self._config_model:
            try:
                self._config_model = SampleConfig(**cfg)
                self.config = self._config_model.model_dump()  # pydantic v2
            except Exception as e:
                self.errors.append(f"配置无效: {e}")
        else:
            self.config.update(cfg)

    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        # 读取输入端口
        val = inputs.get("value", 0)
        flag = inputs.get("flag", True)
        multiplier = self.config.get("multiplier", 1.0)
        enabled = self.config.get("enabled", True)
        if not enabled:
            return {"result": 0, "echo": inputs}
        try:
            base = float(val) if isinstance(val, (int,float,str)) else 0.0
        except Exception:
            base = 0.0
        out_val = base * multiplier if flag else base
        return {"result": out_val, "echo": inputs}

# 注册到模块注册表（也可在 module_registry 中集中注册）
try:
    from app.pipeline.module_registry import register_module
    register_module("示例模块", SampleDevModule)
except Exception:
    pass
