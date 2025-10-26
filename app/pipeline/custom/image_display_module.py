#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图片展示模块
接收输入端口 image (numpy ndarray)，将其原样输出，并提供用于 GUI 画布缩略显示的尺寸/格式配置。
由 GUI 层检测该模块类型后在 ModuleItem 内嵌显示缩略图。
"""
from typing import Any, Dict, Optional, List
import time
import numpy as np
from app.pipeline.base_module import BaseModule, ModuleType, ModuleCapabilities
try:
    from pydantic import BaseModel, validator
except ImportError:  # 环境无 pydantic 时降级
    BaseModel = object  # type: ignore

class ImageDisplayModule(BaseModule):
    CAPABILITIES = ModuleCapabilities(
        supports_async=False,
        supports_batch=False,
        may_block=False,
        resource_tags=["viewer", "image"],
        throughput_hint=60.0,
    )

    class ConfigModel(BaseModel):  # type: ignore
        width: int = 160             # 缩略显示宽度
        height: int = 120            # 缩略显示高度
        maintain_aspect: bool = True # 保持原图比例
        downscale_only: bool = True  # 只缩小不放大
        update_mode: str = "on_change"  # on_change | interval
        interval_ms: int = 0         # update_mode=interval 时的最小间隔
        channel_format: str = "BGR"  # BGR|RGB|GRAY （如需要内部转换）
        autoskip_error: bool = True  # 遇到非图像输入是否静默跳过

        @validator("width", "height")
        def _positive(cls, v):
            if v <= 0:
                raise ValueError("width/height 必须 > 0")
            return v

        @validator("update_mode")
        def _mode_ok(cls, v):
            if v not in {"on_change", "interval"}:
                raise ValueError("update_mode 必须是 on_change|interval")
            return v

        @validator("interval_ms")
        def _interval_ok(cls, v):
            if v < 0:
                raise ValueError("interval_ms 不能为负")
            return v

        @validator("channel_format")
        def _fmt_ok(cls, v):
            v2 = v.upper()
            if v2 not in {"BGR", "RGB", "GRAY"}:
                raise ValueError("channel_format 必须是 BGR|RGB|GRAY")
            return v2

    def __init__(self, name: str = "图片展示模块"):
        super().__init__(name)
        self.last_image: Optional[np.ndarray] = None
        self.last_update_ts: float = 0.0
        self._change_counter: int = 0
        # 默认配置（若未调用 configure）
        self.config.update({
            "width": 160,
            "height": 120,
            "maintain_aspect": True,
            "downscale_only": True,
            "update_mode": "on_change",
            "interval_ms": 0,
            "channel_format": "BGR",
            "autoskip_error": True,
        })

    @property
    def module_type(self) -> ModuleType:
        return ModuleType.CUSTOM

    def _define_ports(self):
        if not self.input_ports:
            self.register_input_port("image", port_type="frame", desc="输入图像", required=True)
        if not self.output_ports:
            # 输出同一张图像，便于串接其他模块（例如后处理）
            self.register_output_port("image", port_type="frame", desc="原样输出图像")
            self.register_output_port("meta", port_type="meta", desc="显示信息")

    def _should_update(self, img: Optional[np.ndarray]) -> bool:
        mode = self.config.get("update_mode", "on_change")
        if mode == "interval":
            interval_ms = int(self.config.get("interval_ms", 0))
            if interval_ms <= 0:
                return True
            now = time.time()
            if (now - self.last_update_ts) * 1000.0 >= interval_ms:
                self.last_update_ts = now
                return True
            return False
        # on_change 模式
        if img is None:
            return False
        # 通过数组引用变化计数来判定更新（简单策略：对象 id 不同即变化）
        if self.last_image is None or id(img) != id(self.last_image):
            return True
        return False

    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        img = inputs.get("image")
        if img is None or not isinstance(img, np.ndarray):
            if self.config.get("autoskip_error", True):
                return {"meta": {"status": "no-image"}}
            return {"error": "缺少图像输入"}
        # 是否更新缩略图
        if self._should_update(img):
            self.last_image = img
            self._change_counter += 1
        return {
            "image": img,
            "meta": {
                "updated": self.last_image is img,
                "changes": self._change_counter,
                "shape": list(img.shape),
                "timestamp": time.time()
            }
        }

    def get_status(self) -> Dict[str, Any]:
        base = super().get_status()
        base.update({
            "has_image": self.last_image is not None,
            "last_shape": list(self.last_image.shape) if isinstance(self.last_image, np.ndarray) else None,
            "change_counter": self._change_counter
        })
        return base
