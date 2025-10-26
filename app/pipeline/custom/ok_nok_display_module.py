#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OK/NOK 展示模块
输入: flag (bool) - 判定状态
输出: flag (bool), text (str), status (str)

显示逻辑由画布 (EnhancedFlowCanvas.ModuleItem) 识别模块名称 "OK/NOK展示" 后渲染：
  - flag 为真: 绿色背景 + 白字 "OK"
  - flag 为假: 红色背景 + 白字 "NOK"

配置 (pydantic 验证):
  true_label: 默认 "OK"
  false_label: 默认 "NOK"
  auto_inverse: 尝试从输入中自动解析真值 (例如字符串 'false','0' 视为 False)
  remember_last: 是否记忆最后一次状态 (无输入时继续显示最后值)
"""
from typing import Any, Dict, Optional
from app.pipeline.base_module import BaseModule, ModuleType, ModuleCapabilities
try:
    from pydantic import BaseModel, validator
except ImportError:  # pydantic 缺失降级
    BaseModel = object  # type: ignore
    def validator(*args, **kwargs):  # type: ignore
        def _wrap(fn): return fn
        return _wrap

class OkNokDisplayModule(BaseModule):
    CAPABILITIES = ModuleCapabilities(
        supports_async=False,
        supports_batch=False,
        may_block=False,
        resource_tags=["viewer", "status"],
        throughput_hint=500.0,
    )

    class ConfigModel(BaseModel):  # type: ignore
        true_label: str = "OK"
        false_label: str = "NOK"
        auto_inverse: bool = True
        remember_last: bool = True
        font_size: int = 12

        @validator("true_label", "false_label")
        def _non_empty(cls, v):
            if not v.strip():
                raise ValueError("标签不能为空")
            return v.strip()

    def __init__(self, name: str = "OK/NOK展示"):
        super().__init__(name)
        self.config.update({
            "true_label": "OK",
            "false_label": "NOK",
            "auto_inverse": True,
            "remember_last": True,
            "font_size": 12,
        })
        self._last_flag: Optional[bool] = None
        self._last_text: str = ""  # 供画布读取

    @property
    def module_type(self) -> ModuleType:
        return ModuleType.CUSTOM

    def _define_ports(self):
        if not self.input_ports:
            self.register_input_port("flag", port_type="bool", desc="布尔状态", required=False)
        if not self.output_ports:
            self.register_output_port("flag", port_type="bool", desc="当前状态")
            self.register_output_port("text", port_type="string", desc="显示文本")
            self.register_output_port("status", port_type="meta", desc="模块状态")

    def _coerce_flag(self, value: Any) -> Optional[bool]:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            v = value.strip().lower()
            if v in {"true", "1", "yes", "ok", "y"}:
                return True
            if v in {"false", "0", "no", "n", "nok"}:
                return False
        return bool(value)  # 兜底转换

    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        raw = inputs.get("flag")
        flag = self._coerce_flag(raw)
        if flag is None and self.config.get("remember_last", True):
            flag = self._last_flag
        if flag is None:
            # 初始无状态
            self._last_text = "?"
            return {"flag": None, "text": "?", "status": "no-input"}
        self._last_flag = flag
        label_true = self.config.get("true_label", "OK")
        label_false = self.config.get("false_label", "NOK")
        text = label_true if flag else label_false
        self._last_text = text
        return {
            "flag": flag,
            "text": text,
            "status": "ok"
        }

    # 供画布访问的显示文本
    @property
    def display_text(self) -> str:
        return self._last_text

    def get_status(self) -> Dict[str, Any]:
        base = super().get_status()
        base.update({
            "last_flag": self._last_flag,
            "last_text": self._last_text,
        })
        return base
