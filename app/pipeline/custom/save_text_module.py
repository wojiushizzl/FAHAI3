#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
保存文本模块 (SaveTextModule)
输入: text (string)
输出: status (meta), saved_path (meta 可选)

功能: 将输入文本保存到指定文件 (默认 outputs/text_log.txt)。支持追加/覆盖、可选时间戳、编码选择。
"""
from typing import Any, Dict, Optional
import os
import datetime
from app.pipeline.base_module import BaseModule, ModuleCapabilities, ModuleType

try:
    from pydantic import BaseModel, validator
except ImportError:  # 容错运行
    BaseModel = object  # type: ignore
    def validator(*args, **kwargs):
        def _wrap(fn): return fn
        return _wrap

class SaveTextModule(BaseModule):
    CAPABILITIES = ModuleCapabilities(
        supports_async=False,
        supports_batch=False,
        may_block=True,
        resource_tags=["io", "text"],
        throughput_hint=200.0,
    )

    class ConfigModel(BaseModel):  # type: ignore
        file_path: str = "outputs/text_log.txt"  # 目标文件
        append: bool = True                      # True 追加, False 覆盖
        add_timestamp: bool = True               # 每行前添加时间戳
        encoding: str = "utf-8"                 # 文件编码
        ensure_parent: bool = True               # 自动创建父目录
        empty_placeholder: str = "(empty)"      # 空文本替换内容

        @validator("encoding")
        def _enc(cls, v):
            if not v: return "utf-8"
            return v

    def __init__(self, name: str = "保存文本"):
        super().__init__(name)
        self.config.update({
            "file_path": "outputs/text_log.txt",
            "append": True,
            "add_timestamp": True,
            "encoding": "utf-8",
            "ensure_parent": True,
            "empty_placeholder": "(empty)",
        })
        self._last_saved_path: Optional[str] = None
        self._last_error: Optional[str] = None
        self._write_count: int = 0

    @property
    def module_type(self) -> ModuleType:
        return ModuleType.CUSTOM

    def _define_ports(self):
        if not self.input_ports:
            self.register_input_port("text", port_type="string", desc="要保存的文本", required=True)
        if not self.output_ports:
            self.register_output_port("status", port_type="meta", desc="执行状态")
            self.register_output_port("saved_path", port_type="meta", desc="保存文件路径")

    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        txt = inputs.get("text")
        if txt is None:
            txt = ""
        if not isinstance(txt, str):
            try:
                txt = str(txt)
            except Exception:
                txt = "(unstringifiable)"
        if txt == "":
            txt = str(self.config.get("empty_placeholder", "(empty)"))
        path = str(self.config.get("file_path", "outputs/text_log.txt"))
        append = bool(self.config.get("append", True))
        add_ts = bool(self.config.get("add_timestamp", True))
        enc = str(self.config.get("encoding", "utf-8"))
        ensure_parent = bool(self.config.get("ensure_parent", True))

        line = txt
        if add_ts:
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            line = f"[{ts}] {line}"
        line += "\n"

        try:
            parent = os.path.dirname(path)
            if ensure_parent and parent and not os.path.exists(parent):
                os.makedirs(parent, exist_ok=True)
            mode = "a" if append else "w"
            with open(path, mode, encoding=enc, errors="ignore") as f:
                f.write(line)
            self._last_saved_path = path
            self._last_error = None
            self._write_count += 1
            return {"status": f"ok:{self._write_count}", "saved_path": path}
        except Exception as e:
            self._last_error = str(e)
            return {"status": f"error:{e}", "saved_path": None}

    def get_status(self) -> Dict[str, Any]:
        base = super().get_status()
        base.update({
            "last_saved_path": self._last_saved_path,
            "last_error": self._last_error,
            "write_count": self._write_count,
        })
        return base

# 允许直接脚本测试
if __name__ == "__main__":
    m = SaveTextModule()
    m.start()
    out = m.process({"text": "Hello World"})
    print(out)
