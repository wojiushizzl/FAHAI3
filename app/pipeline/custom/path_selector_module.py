#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
路径选择器模块 (PathSelectorModule)
允许用户选择目录或文件路径并在流程中输出该路径。
双击模块或调用 configure 变更路径；无输入，仅输出当前路径。
"""
from typing import Dict, Any
import os
from app.pipeline.base_module import BaseModule, ModuleType, ModuleCapabilities

try:
    from pydantic import BaseModel, validator
except ImportError:
    BaseModel = object  # type: ignore

class PathSelectorModule(BaseModule):
    CAPABILITIES = ModuleCapabilities(
        supports_async=False,
        supports_batch=False,
        may_block=False,
        resource_tags=["path", "selector"],
        throughput_hint=5.0,
    )

    class ConfigModel(BaseModel):  # type: ignore
        selection_mode: str = "directory"  # directory|file
        dialog_title: str = "选择路径"
        default_path: str = ""            # 初始目录或文件
        remember_last: bool = True

        @validator("selection_mode")
        def _mode(cls, v):
            if v not in {"directory", "file"}:
                raise ValueError("selection_mode 必须为 directory|file")
            return v

    def __init__(self, name: str = "路径选择器"):
        super().__init__(name)
        self.config.update({
            "selection_mode": "directory",
            "dialog_title": "选择路径",
            "default_path": "",
            "remember_last": True,
        })
        self._current_path: str = ""

    @property
    def module_type(self) -> ModuleType:
        return ModuleType.CUSTOM

    def _define_ports(self):
        if not self.output_ports:
            self.register_output_port("path", port_type="meta", desc="当前选择路径")

    # 无输入驱动，直接输出当前路径
    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:  # type: ignore
        return {"path": self._current_path}

    def set_path(self, path: str):
        """外部调用设置路径，并可根据配置记忆。"""
        self._current_path = path.strip()
        if self.config.get("remember_last", True):
            self.config["default_path"] = self._current_path

    def get_status(self) -> Dict[str, Any]:
        base = super().get_status()
        base.update({"current_path": self._current_path})
        return base

    @property
    def selected_path(self) -> str:
        return self._current_path

__all__ = ["PathSelectorModule"]