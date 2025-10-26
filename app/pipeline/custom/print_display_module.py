#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
打印显示模块 (PrintDisplayModule)
接收任意输入数据(默认 data 端口)并在画布内模块区域实时显示文本内容。
支持行缓冲、前缀、最大长度截断等。
"""
from typing import Any, Dict, Optional, List
import time
from app.pipeline.base_module import BaseModule, ModuleType, ModuleCapabilities
try:
    from pydantic import BaseModel, validator
except ImportError:
    BaseModel = object  # type: ignore

class PrintDisplayModule(BaseModule):
    CAPABILITIES = ModuleCapabilities(
        supports_async=False,
        supports_batch=False,
        may_block=False,
        resource_tags=["viewer", "text", "print"],
        throughput_hint=120.0,
    )

    class ConfigModel(BaseModel):  # type: ignore
        max_lines: int = 10          # 保持的行数
        truncate: int = 200          # 单行最大长度（超出截断）
        prefix: str = ""             # 每行前缀
        update_mode: str = "every"  # every|interval|on_change
        interval_ms: int = 0         # interval 模式刷新最小间隔
        merge_dict: bool = True      # dict 自动格式化为 key=value 拼接
        show_timestamp: bool = True  # 是否显示时间戳

        @validator("max_lines")
        def _ml(cls, v):
            if v <= 0: raise ValueError("max_lines > 0")
            return v
        @validator("truncate")
        def _tr(cls, v):
            if v <= 10: raise ValueError("truncate > 10")
            return v
        @validator("update_mode")
        def _um(cls, v):
            if v not in {"every", "interval", "on_change"}:
                raise ValueError("update_mode 必须是 every|interval|on_change")
            return v
        @validator("interval_ms")
        def _im(cls, v):
            if v < 0: raise ValueError("interval_ms >= 0")
            return v

    def __init__(self, name: str = "打印显示模块"):
        super().__init__(name)
        self.config.update({
            "max_lines": 10,
            "truncate": 200,
            "prefix": "",
            "update_mode": "every",
            "interval_ms": 0,
            "merge_dict": True,
            "show_timestamp": True,
        })
        self._lines: List[str] = []
        self._last_text: Optional[str] = None
        self._last_update_ts: float = 0.0
        self._change_counter = 0

    @property
    def module_type(self) -> ModuleType:
        return ModuleType.CUSTOM

    def _define_ports(self):
        if not self.input_ports:
            self.register_input_port("data", port_type="meta", desc="输入数据")
        if not self.output_ports:
            self.register_output_port("text", port_type="meta", desc="当前文本")
            self.register_output_port("changes", port_type="meta", desc="更新次数")

    def _should_update(self, text: Optional[str]) -> bool:
        mode = self.config.get("update_mode", "every")
        if mode == "every":
            return True
        if mode == "on_change":
            if text is None:
                return False
            if self._last_text is None or text != self._last_text:
                return True
            return False
        if mode == "interval":
            interval_ms = int(self.config.get("interval_ms", 0))
            if interval_ms <= 0:
                return True
            now = time.time()
            if (now - self._last_update_ts) * 1000.0 >= interval_ms:
                self._last_update_ts = now
                return True
            return False
        return True

    def _format_input(self, value: Any) -> str:
        if value is None:
            return "<None>"
        if isinstance(value, dict) and self.config.get("merge_dict", True):
            parts = []
            for k, v in value.items():
                parts.append(f"{k}={v}")
            return ", ".join(parts)
        if isinstance(value, (list, tuple, set)):
            return f"{type(value).__name__}[{len(value)}] {list(value)[:5]}"  # 简要
        text = str(value)
        return text

    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        raw = inputs.get("data")
        text = self._format_input(raw)
        # 截断
        max_len = int(self.config.get("truncate", 200))
        if len(text) > max_len:
            text = text[:max_len] + "..."
        if self.config.get("show_timestamp", True):
            ts_str = time.strftime("%H:%M:%S")
            text = f"[{ts_str}] {text}"
        prefix = self.config.get("prefix", "")
        if prefix:
            text = prefix + text
        if not self._should_update(text):
            return {"text": self._last_text or "", "changes": self._change_counter}
        self._last_text = text
        self._change_counter += 1
        # 维护缓冲
        self._lines.append(text)
        max_lines = int(self.config.get("max_lines", 10))
        if len(self._lines) > max_lines:
            self._lines = self._lines[-max_lines:]
        return {"text": text, "changes": self._change_counter}

    def get_status(self) -> Dict[str, Any]:
        base = super().get_status()
        base.update({
            "lines": self._lines.copy(),
            "last_text": self._last_text,
            "change_counter": self._change_counter
        })
        return base

    # 供画布访问的显示文本（多行合并）
    @property
    def display_text(self) -> str:
        return "\n".join(self._lines)
