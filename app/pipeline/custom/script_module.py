#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""脚本模块 (ScriptModule)
允许用户在配置中直接编辑并运行自定义 Python 代码，对输入端口数据进行处理并输出结果。

安全与限制：
- 代码在受限命名空间执行，不直接暴露内置模块写文件/网络能力（仍可通过导入进行扩展，需自行负责安全）。
- 运行异常捕获后写入 last_error 并输出状态。错误不会中断整体流水线。

用法：
config 示例：
{
  "script": "# inputs: dict\n# outputs: dict\nvalue = inputs.get('data');\noutputs['result'] = value if value is not None else 'no-data'",
  "repeat_cache_threshold": 5
}

端口：
输入: data (任意) image (可选)
输出: result  status  error
"""
from __future__ import annotations
from typing import Any, Dict
import time, traceback, hashlib

from app.pipeline.base_module import BaseModule, ModuleType

class ScriptModule(BaseModule):
    module_type = ModuleType.CUSTOM

    def __init__(self, name: str = "脚本模块"):
        super().__init__(name=name)
        # 端口定义
        self.register_input_port("data", port_type="meta", required=False, desc="任意输入数据")
        self.register_input_port("image", port_type="frame", required=False, desc="图像数据")
        self.register_output_port("result", port_type="meta", desc="脚本输出结果")
        self.register_output_port("status", port_type="meta", desc="运行状态 ok/error/empty")
        self.register_output_port("error", port_type="text", desc="错误消息")
        # 配置
        self.config.update({
            "script": "# 在此编写脚本\n# 可用变量: inputs (dict), outputs (dict), config (dict)\n# 示例:\nvalue = inputs.get('data')\nif value is not None:\n    outputs['result'] = value\nelse:\n    outputs['result'] = 'no-data'",
            "repeat_cache_threshold": 5
        })
        self.last_error: str | None = None
        self._prev_output_hash: str | None = None
        self._repeat_outputs_count: int = 0

    def _hash_outputs(self, data: Dict[str, Any]) -> str:
        try:
            # 尽量稳定哈希（仅基本类型）
            simplified = {}
            for k, v in data.items():
                if isinstance(v, (int, float, str)):
                    simplified[k] = v
                elif v is None:
                    simplified[k] = None
                else:
                    simplified[k] = type(v).__name__
            raw = repr(sorted(simplified.items())).encode('utf-8')
            return hashlib.sha256(raw).hexdigest()
        except Exception:
            return ''

    def process(self):
        script = self.config.get("script", "")
        inputs = {
            'data': self.get_input('data'),
            'image': self.get_input('image')
        }
        outputs: Dict[str, Any] = {}
        local_env = {
            'inputs': inputs,
            'outputs': outputs,
            'config': self.config,
            'time': time,
        }
        status = 'ok'
        self.last_error = None
        try:
            exec(script, {'__builtins__': __builtins__}, local_env)
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            status = 'error'
            outputs.setdefault('result', None)
        # 空数据判定
        if outputs.get('result') is None:
            status = 'empty' if status == 'ok' else status
        # 输出哈希与缓存标记
        h = self._hash_outputs(outputs)
        if h and self._prev_output_hash == h:
            self._repeat_outputs_count += 1
        else:
            self._repeat_outputs_count = 0
        self._prev_output_hash = h
        # 写出端口
        self.outputs['result'] = outputs.get('result')
        self.outputs['status'] = status
        if self.last_error:
            self.outputs['error'] = self.last_error
        else:
            self.outputs['error'] = ''

    def configure(self, new_config: Dict[str, Any]):
        super().configure(new_config)
        # 可选：热更新脚本时重置重复计数
        if 'script' in new_config:
            self._prev_output_hash = None
            self._repeat_outputs_count = 0

__all__ = ["ScriptModule"]