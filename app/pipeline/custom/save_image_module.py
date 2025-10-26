#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
保存图片模块
接收上游图像 ndarray 并按配置保存到指定目录，支持命名模式、更新策略与格式选项。
"""
from typing import Any, Dict, Optional
import os, time
import cv2
import numpy as np
from app.pipeline.base_module import BaseModule, ModuleType, ModuleCapabilities
try:
    from pydantic import BaseModel, validator
except ImportError:  # 环境缺失 pydantic 时降级
    BaseModel = object  # type: ignore

class SaveImageModule(BaseModule):
    CAPABILITIES = ModuleCapabilities(
        supports_async=False,
        supports_batch=False,
        may_block=True,  # 文件 IO
        resource_tags=["image", "io", "save"],
        throughput_hint=30.0,
    )

    class ConfigModel(BaseModel):  # type: ignore
        output_dir: str = "outputs/images"       # 保存目录
        filename_pattern: str = "frame_{index:05d}.png"  # 格式化命名 index 变量可用
        create_dir: bool = True                  # 若目录不存在自动创建
        overwrite: bool = False                  # 若文件已存在是否覆盖
        image_format: str = "PNG"               # PNG|JPG
        quality: int = 95                        # JPG 质量 (1-100)
        update_mode: str = "every"              # every|on_change|interval|once
        interval_ms: int = 0                     # interval 模式最小间隔
        downscale_max: int = 0                   # >0 时若任一边超过该值则缩小保持比例

        @validator("image_format")
        def _fmt(cls, v):
            v2 = v.upper()
            if v2 not in {"PNG", "JPG"}:
                raise ValueError("image_format 必须是 PNG|JPG")
            return v2

        @validator("quality")
        def _quality(cls, v):
            if v < 1 or v > 100:
                raise ValueError("quality 必须 1-100")
            return v

        @validator("update_mode")
        def _umode(cls, v):
            if v not in {"every", "on_change", "interval", "once"}:
                raise ValueError("update_mode 必须是 every|on_change|interval|once")
            return v

        @validator("interval_ms")
        def _interval(cls, v):
            if v < 0:
                raise ValueError("interval_ms 不能为负")
            return v

    def __init__(self, name: str = "保存图片模块"):
        super().__init__(name)
        self.config.update({
            "output_dir": "outputs/images",
            "filename_pattern": "frame_{index:05d}.png",
            "create_dir": True,
            "overwrite": False,
            "image_format": "PNG",
            "quality": 95,
            "update_mode": "every",
            "interval_ms": 0,
            "downscale_max": 0,
        })
        self._index = 0
        self._last_image_id: Optional[int] = None
        self._last_save_ts = 0.0
        self._has_run_once = False  # once 模式标识

    @property
    def module_type(self) -> ModuleType:
        return ModuleType.POSTPROCESS

    def _define_ports(self):
        if not self.input_ports:
            self.register_input_port("image", port_type="frame", desc="图像输入", required=True)
            self.register_input_port("path", port_type="meta", desc="动态保存路径或目录 (可选)")
        if not self.output_ports:
            self.register_output_port("path", port_type="meta", desc="保存路径")
            self.register_output_port("index", port_type="meta", desc="保存序号")
            self.register_output_port("timestamp", port_type="meta", desc="保存时间戳")
            self.register_output_port("status", port_type="meta", desc="状态信息")

    def _should_save(self, img: np.ndarray) -> bool:
        mode = self.config.get("update_mode", "every")
        if mode == "every":
            return True
        if mode == "once":
            if self._has_run_once:
                return False
            return True
        if mode == "on_change":
            img_id = id(img)
            if img_id != self._last_image_id:
                self._last_image_id = img_id
                return True
            return False
        if mode == "interval":
            interval_ms = int(self.config.get("interval_ms", 0))
            if interval_ms <= 0:
                return True
            now = time.time()
            if (now - self._last_save_ts) * 1000.0 >= interval_ms:
                self._last_save_ts = now
                return True
            return False
        return True

    def _downscale_if_needed(self, img: np.ndarray) -> np.ndarray:
        limit = int(self.config.get("downscale_max", 0))
        if limit <= 0:
            return img
        h, w = img.shape[:2]
        if max(h, w) <= limit:
            return img
        # 按最大边缩放
        scale = limit / float(max(h, w))
        new_w = int(w * scale); new_h = int(h * scale)
        return cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        img = inputs.get("image")
        if img is None or not isinstance(img, np.ndarray):
            return {"status": "no-image"}
        if not self._should_save(img):
            return {"status": "skipped"}
        # 动态路径处理：如果提供 path 输入，可能是目录或完整文件名
        dynamic_path = inputs.get("path")
        out_dir = self.config.get("output_dir", "outputs/images")
        img_fmt = self.config.get("image_format", "PNG").upper()
        pattern = self.config.get("filename_pattern", "frame_{index:05d}.png")
        # 判定动态路径：
        final_path: Optional[str] = None
        if isinstance(dynamic_path, str) and dynamic_path.strip():
            dp = dynamic_path.strip()
            # 若包含扩展名 (png/jpg/jpeg) 则视作完整文件路径
            lower = dp.lower()
            if lower.endswith('.png') or lower.endswith('.jpg') or lower.endswith('.jpeg'):
                final_path = dp
                out_dir = os.path.dirname(dp) or '.'
            else:
                # 作为目录覆盖 output_dir
                out_dir = dp
        # 创建目录
        if self.config.get("create_dir", True):
            try:
                os.makedirs(out_dir, exist_ok=True)
            except Exception as e:
                return {"status": f"mkdir-fail: {e}"}
        # 文件名生成（若未提供完整路径）
        if final_path is None:
            filename = pattern.format(index=self._index)
            final_path = os.path.join(out_dir, filename)
        # 索引自增（无论是否覆盖）
        cur_index = self._index
        self._index += 1
        if (not self.config.get("overwrite", False)) and os.path.exists(final_path):
            return {"status": "exists", "path": final_path, "index": cur_index}
        to_save = self._downscale_if_needed(img)
        try:
            if img_fmt == "PNG":
                ok = cv2.imwrite(final_path, to_save)
            else:  # JPG
                q = int(self.config.get("quality", 95))
                ok = cv2.imwrite(final_path, to_save, [int(cv2.IMWRITE_JPEG_QUALITY), q])
            if not ok:
                return {"status": "write-fail", "path": final_path, "index": cur_index}
        except Exception as e:
            return {"status": f"error: {e}"}
        ts = time.time()
        # once 模式标记
        if self.config.get("update_mode") == "once":
            self._has_run_once = True
        return {
            "path": final_path,
            "index": cur_index,
            "timestamp": ts,
            "status": "saved"
        }

    def get_status(self) -> Dict[str, Any]:
        base = super().get_status()
        base.update({
            "saved_count": self._index,
            "last_image_id": self._last_image_id,
            "has_run_once": self._has_run_once,
        })
        return base
