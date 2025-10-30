#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
相机模块 (完整版本)
负责图像采集和处理，支持USB/网络/工业相机占位。
此文件为原始全功能实现，已从根目录迁移到分类子目录。
"""
from typing import Any, Dict, Optional
import cv2
import numpy as np
import threading
import time
from queue import Queue, Empty
from app.pipeline.base_module import BaseModule, ModuleType, ModuleCapabilities
try:
    from pydantic import BaseModel, validator
except ImportError:
    BaseModel = object  # type: ignore
from app.pipeline.frame_buffer import FrameBufferPool


class CameraModule(BaseModule):
    """相机模块，负责图像采集。支持 pydantic 配置与能力声明。"""

    # 能力声明
    CAPABILITIES = ModuleCapabilities(
        supports_async=True,
        supports_batch=False,
        may_block=True,
        resource_tags=["camera"],
        throughput_hint=30.0,
    )

    # 配置模型
    class ConfigModel(BaseModel):  # type: ignore
        camera_type: str = "usb"  # usb | network | industrial
        camera_id: int = 0
        width: int = 1280
        height: int = 720
        fps: int = 30
        exposure: int = -1  # -1 表示自动
        gain: int = -1      # -1 表示自动
        auto_focus: bool = True
        format: str = "BGR"  # BGR | RGB | GRAY

        @validator("camera_type")
        def _camera_type_ok(cls, v):
            if v not in {"usb", "network", "industrial"}:
                raise ValueError("camera_type 必须是 usb/network/industrial")
            return v

        @validator("width", "height")
        def _positive(cls, v):
            if v <= 0:
                raise ValueError("width/height 必须为正整数")
            return v

        @validator("fps")
        def _fps_ok(cls, v):
            if not (1 <= v <= 240):
                raise ValueError("fps 必须在 1~240 范围")
            return v

        @validator("format")
        def _fmt_ok(cls, v):
            if v not in {"BGR", "RGB", "GRAY"}:
                raise ValueError("format 必须是 BGR/RGB/GRAY")
            return v

    def __init__(self, name: str = "相机模块", camera_id: int = 0):
        super().__init__(name)
        self.camera_id = camera_id
        self.camera: Optional[cv2.VideoCapture] = None
        self.capture_thread: Optional[threading.Thread] = None
        self.is_capturing = False
        self.frame_queue: Queue = Queue(maxsize=10)
        self.buffer_pool = FrameBufferPool(maxsize=10)
        # 默认配置（会被 configure 校验覆盖）
        self.config.update({
            "camera_type": "usb",
            "camera_id": camera_id,
            "width": 1280,
            "height": 720,
            "fps": 30,
            "exposure": -1,
            "gain": -1,
            "auto_focus": True,
            "format": "BGR",
            "target_fps": 30.0,
            "drop_if_slow": True
        })
        self._last_frame: Optional[np.ndarray] = None
        self._last_ts: float = 0.0
        self._frame_counter: int = 0
        self._last_output_ts: float = 0.0
        self._start_time: float = time.time()

    @property
    def module_type(self) -> ModuleType:
        return ModuleType.CAMERA

    def _define_ports(self):
        if not self.input_ports:
            self.register_input_port("trigger", port_type="control", desc="触发信号", required=False)
            self.register_input_port("config", port_type="control", desc="动态配置", required=False)
        if not self.output_ports:
            self.register_output_port("image", port_type="frame", desc="采集到的图像帧")
            self.register_output_port("meta", port_type="meta", desc="采集状态与时间戳")

    def _on_start(self):
        if not self._open_camera():
            raise RuntimeError("无法打开相机")
        self._configure_camera()
        self.is_capturing = True
        self.capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.capture_thread.start()

    def _on_stop(self):
        self.is_capturing = False
        if self.capture_thread and self.capture_thread.is_alive():
            self.capture_thread.join(timeout=2)
        self._close_camera()

    def _on_configure(self, config: Dict[str, Any]):
        if self.camera and self.camera.isOpened():
            self._configure_camera()

    def _open_camera(self) -> bool:
        try:
            camera_type = self.config.get("camera_type", "usb")
            if camera_type == "usb":
                self.camera = cv2.VideoCapture(self.config["camera_id"])
            elif camera_type == "network":
                url = self.config.get("url", "rtsp://192.168.1.100/stream")
                self.camera = cv2.VideoCapture(url)
            else:
                self.logger.warning("工业相机支持占位实现")
                self.camera = cv2.VideoCapture(self.config["camera_id"])
            if not self.camera.isOpened():
                self.logger.error("无法打开相机")
                return False
            return True
        except Exception as e:
            self.logger.error(f"打开相机失败: {e}")
            return False

    def _close_camera(self):
        if self.camera:
            self.camera.release()
            self.camera = None

    def _configure_camera(self):
        if not self.camera or not self.camera.isOpened():
            return
        try:
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.config["width"])
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config["height"])
            self.camera.set(cv2.CAP_PROP_FPS, self.config["fps"])
            if self.config["exposure"] > 0:
                self.camera.set(cv2.CAP_PROP_EXPOSURE, self.config["exposure"])
            else:
                try:
                    self.camera.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)
                except Exception:
                    pass
            if self.config["gain"] > 0:
                self.camera.set(cv2.CAP_PROP_GAIN, self.config["gain"])
        except Exception as e:
            self.logger.error(f"配置相机参数失败: {e}")

    def _capture_loop(self):
        frame_count = 0
        start = time.time()
        while self.is_capturing and self.camera and self.camera.isOpened():
            ret, frame = self.camera.read()
            if not ret:
                time.sleep(0.01)
                continue
            ts = time.time()
            processed = self._process_frame(frame)
            self._last_frame = processed
            self._last_ts = ts
            if self.frame_queue.full():
                try:
                    self.frame_queue.get_nowait()
                except Empty:
                    pass
            # 使用缓冲池容器减少字典对象频繁分配
            container = self.buffer_pool.borrow()
            container["image"] = processed
            container["timestamp"] = ts
            container["frame_id"] = frame_count
            try:
                self.frame_queue.put_nowait(container)
            except Exception:
                # 放回缓冲池
                self.buffer_pool.release(container)
            frame_count += 1
            if frame_count % 60 == 0:
                elapsed = time.time() - start
                fps = frame_count / max(elapsed, 1e-3)
                self.logger.debug(f"Camera FPS ~ {fps:.2f}")

    def _process_frame(self, frame: np.ndarray) -> np.ndarray:
        fmt = self.config.get("format", "BGR")
        if fmt == "RGB":
            return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        if fmt == "GRAY":
            return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return frame

    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not self.is_capturing:
            return {"meta": {"error": "not-started", "camera_id": self.camera_id}}
        target_fps = float(self.config.get("target_fps", self.config.get("fps", 30)))
        now = time.time()
        min_interval = 1.0 / target_fps if target_fps > 0 else 0.0
        allow_new = (now - self._last_output_ts) >= min_interval - 1e-4
        image = None; ts_out = None; fid = None
        if allow_new:
            try:
                data = self.frame_queue.get_nowait()
                image = data.get("image")
                ts_out = data.get("timestamp")
                fid = data.get("frame_id")
                self.buffer_pool.release(data)
                self._last_output_ts = now
                self._frame_counter += 1
            except Empty:
                image = self._last_frame
                ts_out = self._last_ts
        else:
            # 节流周期内不输出新图像, 仅返回 meta (image 保留 None)
            image = None
            ts_out = self._last_ts
        meta = {
            "timestamp": ts_out,
            "frame_id": fid,
            "camera_id": self.camera_id,
            "width": self.config.get("width"),
            "height": self.config.get("height"),
            "format": self.config.get("format"),
            "fps_capture": self.config.get("fps"),
            "target_fps": target_fps,
            "output_fps_est": (self._frame_counter / max(now - self._start_time, 1e-3)),
            "throttled": not allow_new,
            "queue_size": self.frame_queue.qsize(),
        }
        if image is None:
            return {"meta": meta}
        return {"image": image, "meta": meta}

    def get_camera_info(self) -> Dict[str, Any]:
        if not self.camera or not self.camera.isOpened():
            return {}
        return {
            "width": int(self.camera.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "height": int(self.camera.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "fps": float(self.camera.get(cv2.CAP_PROP_FPS)),
            "exposure": self.camera.get(cv2.CAP_PROP_EXPOSURE),
            "gain": self.camera.get(cv2.CAP_PROP_GAIN)
        }

    def capture_single_frame(self) -> Optional[np.ndarray]:
        if not self.camera or not self.camera.isOpened():
            return None
        ret, frame = self.camera.read()
        if ret:
            return self._process_frame(frame)
        return None
