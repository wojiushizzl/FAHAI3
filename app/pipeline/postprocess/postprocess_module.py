#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""后处理模块 (完整版本) - 已迁移"""
import os
import json
import time
from typing import Any, Dict, List
from app.pipeline.base_module import BaseModule, ModuleType, ModuleCapabilities
try:
    from pydantic import BaseModel, validator
except ImportError:
    BaseModel = object  # type: ignore


class PostprocessModule(BaseModule):
    CAPABILITIES = ModuleCapabilities(
        supports_async=False,
        supports_batch=True,
        may_block=False,
        resource_tags=["postprocess"],
        throughput_hint=200.0,
    )

    class ConfigModel(BaseModel):  # type: ignore
        output_format: str = "json"  # json | raw
        save_results: bool = False
        output_path: str = "./outputs"
        max_cache_size: int = 500

        @validator("output_format")
        def _fmt_ok(cls, v):
            if v not in {"json", "raw"}:
                raise ValueError("output_format 必须是 json/raw")
            return v

        @validator("max_cache_size")
        def _cache_ok(cls, v):
            if v <= 0:
                raise ValueError("max_cache_size 必须 > 0")
            return v

    def __init__(self, name: str = "后处理模块"):
        super().__init__(name)
        self.process_count = 0
        self.total_process_time = 0.0
        self.last_process_time = 0.0
        self.results_cache: List[Dict[str, Any]] = []
        self.max_cache_size = 500
        self.config.update({
            "output_format": "json",
            "save_results": False,
            "output_path": "./outputs",
            "max_cache_size": 500,
        })

    @property
    def module_type(self) -> ModuleType:
        return ModuleType.POSTPROCESS

    def _define_ports(self):
        if not self.input_ports:
            self.register_input_port("results", port_type="result", desc="推理/检测结果", required=True)
            self.register_input_port("metadata", port_type="meta", desc="元数据", required=False)
        if not self.output_ports:
            self.register_output_port("processed_results", port_type="result", desc="后处理结果")
            self.register_output_port("statistics", port_type="meta", desc="统计信息")

    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start = time.time()
        results = inputs.get("results")
        if results is None:
            return {"error": "缺少输入结果"}
        formatted = self._format_output(results)
        proc_time = time.time() - start
        self.process_count += 1
        self.total_process_time += proc_time
        self.last_process_time = proc_time
        stats = self._stats()
        if self.config.get("save_results", False):
            self._save(formatted)
        self._cache(results)
        return {"processed_results": formatted, "statistics": stats}

    def _format_output(self, results: Any) -> Any:
        fmt = self.config.get("output_format", "json")
        if fmt == "json":
            try:
                return json.dumps(results, ensure_ascii=False)
            except Exception:
                return str(results)
        return results

    def _save(self, data: Any):
        try:
            out = self.config.get("output_path", "./outputs")
            os.makedirs(out, exist_ok=True)
            fname = f"post_{int(time.time())}_{self.process_count}.txt"
            with open(os.path.join(out, fname), "w", encoding="utf-8") as f:
                if isinstance(data, str):
                    f.write(data)
                else:
                    f.write(str(data))
        except Exception as e:
            self.logger.error(f"保存结果失败: {e}")

    def _cache(self, results: Any):
        if isinstance(results, dict):
            self.results_cache.append(results.copy())
        # 根据配置动态调整缓存限制
        limit = int(self.config.get("max_cache_size", self.max_cache_size))
        self.max_cache_size = limit
        if len(self.results_cache) > limit:
            self.results_cache = self.results_cache[-limit:]

    def _stats(self) -> Dict[str, Any]:
        avg = self.total_process_time / self.process_count if self.process_count else 0
        return {
            "total_processed": self.process_count,
            "average_time": avg,
            "last_process_time": self.last_process_time,
            "cache_size": len(self.results_cache)
        }
