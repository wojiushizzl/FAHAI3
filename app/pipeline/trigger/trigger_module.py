#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""触发模块 (完整版本) - 已迁移"""
import time
from typing import Any, Dict, List, Callable
from enum import Enum
from queue import Queue, Empty
import threading
from app.pipeline.base_module import BaseModule, ModuleType, ModuleCapabilities
try:
    from pydantic import BaseModel, validator
except ImportError:
    BaseModel = object  # type: ignore


class TriggerMode(Enum):
    MANUAL = "manual"
    TIMER = "timer"
    EXTERNAL = "external"
    MODBUS = "modbus"
    CONDITION = "condition"


class TriggerModule(BaseModule):
    CAPABILITIES = ModuleCapabilities(
        supports_async=True,
        supports_batch=False,
        may_block=True,
        resource_tags=["trigger"],
        throughput_hint=10.0,
    )

    class ConfigModel(BaseModel):  # type: ignore
        mode: str = TriggerMode.MANUAL.value
        interval: float = 1.0
        enabled: bool = True
        max_triggers: int = -1  # -1 表示无限
        delay: float = 0.0

        @validator("mode")
        def _mode_ok(cls, v):
            if v not in {m.value for m in TriggerMode}:
                raise ValueError("非法触发模式")
            return v

        @validator("interval", "delay")
        def _non_negative(cls, v):
            if v < 0:
                raise ValueError("时间参数必须 >= 0")
            return v

        @validator("max_triggers")
        def _max_ok(cls, v):
            if v == 0:
                raise ValueError("max_triggers 不能为 0，使用 -1 表示无限")
            return v

    def __init__(self, name: str = "触发模块"):
        super().__init__(name)
        self.is_triggered = False
        self.trigger_count = 0
        self.last_trigger_time = 0.0
        self.trigger_thread: threading.Thread | None = None
        self.is_running = False
        self.trigger_queue: Queue = Queue()
        self.trigger_callbacks: List[Callable] = []
        self.config.update({
            "mode": TriggerMode.MANUAL.value,
            "interval": 1.0,
            "enabled": True,
            "max_triggers": -1,
            "delay": 0.0
        })

    @property
    def module_type(self) -> ModuleType:
        return ModuleType.TRIGGER

    def _define_ports(self):
        if not self.output_ports:
            self.register_output_port("trigger_signal", port_type="control", desc="触发信号")
            self.register_output_port("trigger_info", port_type="meta", desc="触发信息")

    def _on_start(self):
        if not self.config.get("enabled", True):
            return
        self.is_running = True
        self.trigger_count = 0
        mode = TriggerMode(self.config["mode"])
        if mode == TriggerMode.TIMER:
            self._start_timer()
        # 其它模式占位，可扩展 EXTERNAL / MODBUS / CONDITION

    def _on_stop(self):
        self.is_running = False
        if self.trigger_thread and self.trigger_thread.is_alive():
            self.trigger_thread.join(timeout=2)

    def _start_timer(self):
        def loop():
            interval = self.config.get("interval", 1.0)
            while self.is_running:
                time.sleep(interval)
                if self.is_running:
                    self._fire("timer")
        self.trigger_thread = threading.Thread(target=loop, daemon=True)
        self.trigger_thread.start()

    def _fire(self, source: str):
        max_triggers = self.config.get("max_triggers", -1)
        if max_triggers > 0 and self.trigger_count >= max_triggers:
            return
        delay = self.config.get("delay", 0.0)
        if delay > 0:
            time.sleep(delay)
        self.trigger_count += 1
        self.last_trigger_time = time.time()
        info = {
            "source": source,
            "timestamp": self.last_trigger_time,
            "count": self.trigger_count
        }
        try:
            self.trigger_queue.put_nowait(info)
        except Exception:
            try:
                self.trigger_queue.get_nowait()
            except Empty:
                pass
            self.trigger_queue.put_nowait(info)
        for cb in self.trigger_callbacks:
            try:
                cb(info)
            except Exception as e:
                self.logger.error(f"触发回调错误: {e}")

    def manual_trigger(self):
        if self.config["mode"] == TriggerMode.MANUAL.value:
            self._fire("manual")

    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        try:
            info = self.trigger_queue.get_nowait()
            return {"trigger_signal": True, "trigger_info": info}
        except Empty:
            return {"trigger_signal": False, "trigger_info": None}

