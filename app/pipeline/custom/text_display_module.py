#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文本展示模块 (TextDisplayModule)
与 OK/NOK 展示视觉方式一致：在画布内部矩形中居中显示一段文本。
不处理上游输入，不追加缓冲，仅显示配置中的 text_content。
可调整：字体大小、文字颜色、背景色、text_content。
"""
from typing import Any, Dict
from app.pipeline.base_module import BaseModule, ModuleType, ModuleCapabilities
try:
    from pydantic import BaseModel, validator
except ImportError:
    BaseModel = object  # type: ignore

class TextDisplayModule(BaseModule):
    CAPABILITIES = ModuleCapabilities(
        supports_async=False,
        supports_batch=False,
        may_block=False,
        resource_tags=["viewer","text"],
        throughput_hint=200.0,
    )

    class ConfigModel(BaseModel):  # type: ignore
        font_size: int = 12
        text_color: str = "#222222"
        background_color: str = "#ffffff"
        text_content: str = ""

        @validator("font_size")
        def _fs(cls, v):
            if v < 6 or v > 72:
                raise ValueError("font_size 范围 6-72")
            return v
        @validator("text_color")
        def _tc(cls, v):
            if not isinstance(v, str) or len(v) < 3:
                raise ValueError("text_color 必须是字符串，如 #RRGGBB")
            return v
        @validator("background_color")
        def _bc(cls, v):
            if not isinstance(v, str) or len(v) < 3:
                raise ValueError("background_color 必须是字符串，如 #RRGGBB")
            return v
        @validator("text_content")
        def _tcnt(cls, v):
            return v if isinstance(v, str) else str(v)

    def __init__(self, name: str = "文本展示"):
        super().__init__(name)
        # 默认配置写入 config 便于直接编辑
        self.config.update({
            "font_size": 12,
            "text_color": "#222222",
            "background_color": "#ffffff",
            "text_content": "",
        })

    @property
    def module_type(self) -> ModuleType:
        return ModuleType.CUSTOM

    def _define_ports(self):
        # 无输入端口，仅输出当前文本（便于下游引用）
        if not self.output_ports:
            self.register_output_port("text", port_type="text", desc="展示文本")

    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        # 直接输出配置文本，不依赖输入
        text = self.config.get("text_content", "")
        return {"text": text}

    @property
    def display_text(self) -> str:
        return str(self.config.get("text_content", ""))

    def get_status(self) -> Dict[str, Any]:
        base = super().get_status()
        base.update({
            "text": self.config.get("text_content", ""),
            "config": dict(self.config),
        })
        return base
