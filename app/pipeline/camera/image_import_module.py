#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图片导入模块
从单文件、目录或文件列表依次读取图像作为帧输出，支持循环、间隔、颜色转换与可选缩放。
"""
from typing import Any, Dict, List, Optional
import os
import time
import glob
import cv2
import numpy as np
from app.pipeline.base_module import BaseModule, ModuleType, ModuleCapabilities
try:
    from pydantic import BaseModel, validator
except ImportError:  # 环境缺失 pydantic 时降级
    BaseModel = object  # type: ignore


class ImageImportModule(BaseModule):
    CAPABILITIES = ModuleCapabilities(
        supports_async=False,
        supports_batch=False,
        may_block=True,           # 文件 IO
        resource_tags=["image", "file"],
        throughput_hint=10.0,
    )

    class ConfigModel(BaseModel):  # type: ignore
        source_type: str = "file"          # file | directory | pattern | list
        path: str = ""                     # 单文件或目录路径
        pattern: str = "*.jpg"             # pattern 模式或目录过滤
        recursive: bool = False             # 目录/模式是否递归
        loop: bool = True                   # 是否循环播放
        interval_ms: int = 0                # 两帧之间的间隔 (ms)
        resize: List[int] = []              # [width, height] 可选
        color_format: str = "BGR"          # BGR | RGB | GRAY
        sort: bool = True                   # 是否排序文件列表
        max_files: int = 0                  # 限制最大文件数, 0 不限制
        file_list: List[str] = []           # source_type == list 时使用

        @validator("source_type")
        def _src_ok(cls, v):
            v2 = v.lower()
            if v2 not in {"file", "directory", "pattern", "list"}:
                raise ValueError("source_type 必须是 file|directory|pattern|list")
            return v2

        @validator("interval_ms")
        def _interval_ok(cls, v):
            if v < 0:
                raise ValueError("interval_ms 不能为负数")
            return v

        @validator("resize")
        def _resize_ok(cls, v):
            if v and (len(v) != 2 or v[0] <= 0 or v[1] <= 0):
                raise ValueError("resize 必须为空或 [w,h]")
            return v

        @validator("color_format")
        def _fmt_ok(cls, v):
            v2 = v.upper()
            if v2 not in {"BGR", "RGB", "GRAY"}:
                raise ValueError("color_format 必须是 BGR|RGB|GRAY")
            return v2

    def __init__(self, name: str = "图片导入模块"):
        super().__init__(name)
        self._files: List[str] = []
        self._idx: int = 0
        self._last_time: float = 0.0
        self.config.update({
            "source_type": "file",
            "path": "",
            "pattern": "*.jpg",
            "recursive": False,
            "loop": True,
            "interval_ms": 0,
            "resize": [],
            "color_format": "BGR",
            "sort": True,
            "max_files": 0,
            "file_list": [],
        })

    @property
    def module_type(self) -> ModuleType:
        return ModuleType.CAMERA  # 作为帧来源归类为 CAMERA

    def _define_ports(self):
        if not self.output_ports:
            self.register_output_port("image", port_type="frame", desc="当前图像帧")
            self.register_output_port("path", port_type="meta", desc="当前文件路径")
            self.register_output_port("index", port_type="meta", desc="当前索引")
            self.register_output_port("timestamp", port_type="meta", desc="时间戳")
        if not self.input_ports:
            self.register_input_port("control", port_type="control", desc="控制指令", required=False)

    def _on_start(self):
        self._rebuild_file_list()
        self._last_time = time.time()

    def _on_stop(self):
        # 无持久资源需释放
        pass

    def _on_configure(self, config: Dict[str, Any]):
        # 配置改变时重建文件列表
        self._rebuild_file_list()

    def _rebuild_file_list(self):
        src = self.config.get("source_type", "file")
        path = self.config.get("path", "")
        pattern = self.config.get("pattern", "*.jpg")
        recursive = bool(self.config.get("recursive", False))
        max_files = int(self.config.get("max_files", 0))
        file_list_cfg = self.config.get("file_list", [])
        files: List[str] = []
        try:
            if src == "file":
                if path and os.path.isfile(path):
                    files = [path]
            elif src == "directory":
                if path and os.path.isdir(path):
                    glob_pattern = os.path.join(path, "**", pattern) if recursive else os.path.join(path, pattern)
                    files = glob.glob(glob_pattern, recursive=recursive)
            elif src == "pattern":
                # pattern 可包含绝对/相对路径
                files = glob.glob(pattern, recursive=recursive)
            elif src == "list":
                files = [f for f in file_list_cfg if os.path.isfile(f)]
        except Exception as e:
            self.errors.append(f"枚举文件失败: {e}")
            files = []
        if self.config.get("sort", True):
            files.sort()
        if max_files > 0:
            files = files[:max_files]
        self._files = files
        self._idx = 0
        if not files:
            self.logger.warning("文件列表为空")
        else:
            self.logger.info(f"导入图像文件数: {len(files)}")

    def _load_image(self, path: str) -> Optional[np.ndarray]:
        try:
            img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
            if img is None:
                return None
            # 颜色转换
            fmt = self.config.get("color_format", "BGR").upper()
            if fmt == "RGB" and len(img.shape) >= 3:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            elif fmt == "GRAY" and len(img.shape) >= 3:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            # 缩放
            resize = self.config.get("resize", [])
            if resize and len(resize) == 2:
                w, h = int(resize[0]), int(resize[1])
                if w > 0 and h > 0:
                    img = cv2.resize(img, (w, h))
            return img
        except Exception as e:
            self.errors.append(f"加载图像失败 {path}: {e}")
            return None

    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        # 间隔控制
        interval_ms = int(self.config.get("interval_ms", 0))
        if interval_ms > 0:
            now = time.time()
            if (now - self._last_time) * 1000.0 < interval_ms:
                # 不输出新帧，保持上一次结果(可选择返回空)
                return {}
            self._last_time = now
        if not self._files:
            return {"error": "无文件"}
        if self._idx >= len(self._files):
            if self.config.get("loop", True):
                self._idx = 0
            else:
                return {"error": "播放结束"}
        path = self._files[self._idx]
        img = self._load_image(path)
        self._idx += 1
        if img is None:
            return {"error": f"读取失败: {os.path.basename(path)}"}
        ts = time.time()
        return {
            "image": img,
            "path": path,
            "index": self._idx - 1,
            "timestamp": ts,
        }

    def get_status(self) -> Dict[str, Any]:
        base = super().get_status()
        base.update({
            "total_files": len(self._files),
            "current_index": self._idx,
            "loop": self.config.get("loop", True),
        })
        return base
