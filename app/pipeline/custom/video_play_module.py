#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视频播放/展示模块
=================
负责从视频文件或摄像头源读取帧, 并向下游输出当前帧及播放状态 meta。
相比 CameraModule(纯采集) 与 ImageDisplayModule(纯展示) 的组合, 本模块打包了
"读源 + 播放控制 + 展示" 的功能, 适合回放演示与简单视频驱动流程。

端口:
  输入:
    control (control, 可选)    播放控制命令: {"action":"pause"|"resume"|...}
    config  (control, 可选)    动态配置更新
  输出:
    image   (frame)            当前帧 (numpy ndarray)
    meta    (meta)             播放状态信息

播放控制命令示例:
  {"action": "pause"}
  {"action": "resume"}
  {"action": "stop"}
  {"seek": 120}              # 跳转到第120帧(文件源)
  {"speed": 0.5}             # 播放速度倍率, 影响输出节流
  {"action": "reload", "path": "new.mp4"}

注意: 摄像头源时 seek/reload(path) 仅在切换路径到新文件时生效, seek 对摄像头无效。
"""
from __future__ import annotations
from typing import Any, Dict, Optional
import time
import threading
from queue import Queue, Empty
import cv2
import numpy as np
from app.pipeline.base_module import BaseModule, ModuleType, ModuleCapabilities

try:
    from pydantic import BaseModel, validator
except ImportError:  # 兼容无 pydantic 环境
    BaseModel = object  # type: ignore


class VideoPlayModule(BaseModule):
    CAPABILITIES = ModuleCapabilities(
        supports_async=True,
        supports_batch=False,
        may_block=True,
        resource_tags=["video", "player"],
        throughput_hint=30.0,
    )

    class ConfigModel(BaseModel):  # type: ignore
        source_type: str = "file"      # file | camera
        path: str = ""                 # 当 source=file 时
        camera_id: int = 0              # 当 source=camera 时
        loop: bool = True
        target_fps: float = 30.0        # 输出节流FPS (<= 原始)
        resize_width: int = 0
        resize_height: int = 0
        maintain_aspect: bool = True
        convert_format: str = "BGR"    # BGR|RGB|GRAY
        drop_if_slow: bool = True
        autoskip_error: bool = True
        start_paused: bool = False
        max_queue: int = 5
        read_ahead: bool = True
        seek_on_start: int = 0          # 仅文件源有效
        speed: float = 1.0              # 播放速度倍率, 影响节流间隔

        @validator("source_type")
        def _src_type_ok(cls, v):
            if v not in {"file", "camera"}:
                raise ValueError("source_type 必须是 file|camera")
            return v

        @validator("target_fps")
        def _fps_ok(cls, v):
            if v <= 0 or v > 240:
                raise ValueError("target_fps 必须在 (0,240]")
            return v

        @validator("resize_width", "resize_height")
        def _size_nonneg(cls, v):
            if v < 0:
                raise ValueError("resize 尺寸不能为负")
            return v

        @validator("convert_format")
        def _fmt_ok(cls, v):
            v2 = v.upper()
            if v2 not in {"BGR", "RGB", "GRAY"}:
                raise ValueError("convert_format 必须是 BGR|RGB|GRAY")
            return v2

        @validator("speed")
        def _speed_ok(cls, v):
            if v <= 0 or v > 10:
                raise ValueError("speed 必须在 (0,10]")
            return v

    def __init__(self, name: str = "视频播放模块"):
        super().__init__(name)
        # 默认配置, 如未调用 configure
        self.config.update({
            "source_type": "file",
            "path": "",
            "camera_id": 0,
            "loop": True,
            "target_fps": 30.0,
            "resize_width": 0,
            "resize_height": 0,
            "maintain_aspect": True,
            "convert_format": "BGR",
            "drop_if_slow": True,
            "autoskip_error": True,
            "start_paused": False,
            "max_queue": 5,
            "read_ahead": True,
            "seek_on_start": 0,
            "speed": 1.0,
        })
        # 播放状态
        self.capture: Optional[cv2.VideoCapture] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._paused = False
        self._queue: Queue = Queue(maxsize=self.config.get("max_queue", 5))
        self._capture_lock = threading.Lock()  # 避免并发 read 触发底层 ffmpeg 断言
        # 使用 -1 初始值, 读取首帧后变为 0 以便更直观
        self._frame_index: int = -1
        self._last_output_ts: float = 0.0
        self._output_count: int = 0
        self._start_time: float = 0.0
        self._orig_fps: Optional[float] = None
        self._total_frames: Optional[int] = None
        self._last_frame_shape: Optional[tuple] = None
        self._speed_factor: float = 1.0

    @property
    def module_type(self) -> ModuleType:
        return ModuleType.CUSTOM

    def _define_ports(self):
        if not self.input_ports:
            self.register_input_port("control", port_type="control", desc="播放控制", required=False)
            self.register_input_port("config", port_type="control", desc="动态配置", required=False)
        if not self.output_ports:
            self.register_output_port("image", port_type="frame", desc="当前帧")
            self.register_output_port("meta", port_type="meta", desc="播放状态")

    # ---------------- 生命周期 -----------------
    def _on_start(self):
        if not self._open_source():
            raise RuntimeError("无法打开视频/摄像头源")
        self._apply_seek_on_start()
        self._speed_factor = float(self.config.get("speed", 1.0))
        self._paused = bool(self.config.get("start_paused", False))
        self._running = True
        self._start_time = time.time()
        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()

    def _on_stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._close_source()
        while not self._queue.empty():  # 清空队列
            try:
                self._queue.get_nowait()
            except Empty:
                break

    def _on_configure(self, config: Dict[str, Any]):
        # 如果修改了关键源参数需要重载
        need_reload = False
        for k in ["source_type", "path", "camera_id"]:
            if k in config:
                need_reload = True
                break
        if need_reload:
            self.logger.info("检测到源参数修改, 重载视频源")
            self._reload_source()
        if "speed" in config:
            self._speed_factor = float(config.get("speed", 1.0))
        # 更新队列大小(不强制缩放已存在容量, 简化处理)
        if "max_queue" in config:
            # 无法直接改变 Queue 大小, 可在未来重建, 暂保留
            pass

    # ---------------- 源管理 -----------------
    def _open_source(self) -> bool:
        try:
            stype = self.config.get("source_type", "file")
            if stype == "file":
                path = self.config.get("path", "")
                self.capture = cv2.VideoCapture(path)
            else:
                cam_id = int(self.config.get("camera_id", 0))
                self.capture = cv2.VideoCapture(cam_id)
            if not self.capture or not self.capture.isOpened():
                self.logger.error("视频源打开失败")
                return False
            # 取原始 FPS 和总帧数(摄像头可能不可用)
            fps = self.capture.get(cv2.CAP_PROP_FPS)
            self._orig_fps = fps if fps and fps > 0 else None
            frames = int(self.capture.get(cv2.CAP_PROP_FRAME_COUNT))
            self._total_frames = frames if frames > 0 else None
            # 对文件源: POS_FRAMES 指向下一帧索引, 我们保持 -1 起始, 读取后自增
            if self.config.get("source_type") == "file":
                self._frame_index = -1
            else:
                self._frame_index = 0
            return True
        except Exception as e:
            self.logger.error(f"打开源异常: {e}")
            return False

    def _close_source(self):
        if self.capture:
            try:
                self.capture.release()
            except Exception:
                pass
        self.capture = None

    def _reload_source(self):
        self._close_source()
        ok = self._open_source()
        if not ok:
            self.logger.error("重载视频源失败")

    def _apply_seek_on_start(self):
        if self.capture and self.capture.isOpened() and self.config.get("source_type") == "file":
            seek = int(self.config.get("seek_on_start", 0))
            if seek > 0 and self._total_frames and seek < self._total_frames:
                self.capture.set(cv2.CAP_PROP_POS_FRAMES, seek)
                self._frame_index = seek

    # ---------------- 读取线程 -----------------
    def _reader_loop(self):
        target_fps = float(self.config.get("target_fps", 30.0))
        read_ahead = bool(self.config.get("read_ahead", True))
        loop_enabled = bool(self.config.get("loop", True))
        while self._running and self.capture and self.capture.isOpened():
            if self._paused:
                time.sleep(0.05)
                continue
            # 控制读取速率: 不严格锁定, 简单 sleep 限制
            eff_fps = target_fps * self._speed_factor
            interval = 1.0 / eff_fps if eff_fps > 0 else 0.0
            # 如果队列已满并且配置 drop_if_slow, 丢弃读取等待
            if self._queue.full() and self.config.get("drop_if_slow", True):
                time.sleep(min(interval, 0.02))
                continue
            ret, frame = self.capture.read()
            if not ret:
                # 文件末尾处理
                if self.config.get("source_type") == "file":
                    if loop_enabled:
                        self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        self._frame_index = 0
                        continue
                    else:
                        # 停止播放但保持模块运行, 输出 meta playing=False
                        self._paused = True
                        self.logger.info("已到达文件末尾, 自动暂停")
                        time.sleep(0.1)
                        continue
                else:
                    # 摄像头暂时无帧, 短暂等待
                    time.sleep(0.01)
                    continue
            # 更新帧序号
            if self._frame_index < 0:
                self._frame_index = 0
            else:
                self._frame_index += 1
            # 入队最新帧(不做前处理, 在 process 中转换)
            try:
                self._queue.put(frame, timeout=0.01)
                if (self._frame_index % 5) == 0:
                    self.logger.debug(f"reader frame_index={self._frame_index}")
            except Exception:
                pass
            # 读前瞻: 若 read_ahead=False 则主动 sleep 匹配间隔
            if not read_ahead and interval > 0:
                time.sleep(interval)

    # ---------------- 播放控制解析 -----------------
    def _apply_control(self, ctrl: Dict[str, Any]):
        if not ctrl:
            return
        if "action" in ctrl:
            act = ctrl.get("action")
            if act == "pause":
                self._paused = True
            elif act == "resume":
                self._paused = False
            elif act == "stop":
                # seek 回 0 并暂停
                if self.capture and self.capture.isOpened() and self.config.get("source_type") == "file":
                    self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    self._frame_index = 0
                self._paused = True
            elif act == "reload":
                # 可选 path 参数
                new_path = ctrl.get("path")
                if new_path:
                    self.config["path"] = new_path
                self._reload_source()
        if "seek" in ctrl:
            seek = int(ctrl.get("seek"))
            if self.capture and self.capture.isOpened() and self.config.get("source_type") == "file" and self._total_frames:
                if 0 <= seek < self._total_frames:
                    self.capture.set(cv2.CAP_PROP_POS_FRAMES, seek)
                    self._frame_index = seek
        if "speed" in ctrl:
            sp = float(ctrl.get("speed"))
            if 0 < sp <= 10:
                self._speed_factor = sp
                self.config["speed"] = sp

    # ---------------- 帧处理 -----------------
    def _transform_frame(self, frame: np.ndarray) -> np.ndarray:
        # 尺寸调整
        rw = int(self.config.get("resize_width", 0))
        rh = int(self.config.get("resize_height", 0))
        if rw > 0 and rh > 0:
            if self.config.get("maintain_aspect", True):
                h, w = frame.shape[:2]
                scale = min(rw / w, rh / h)
                nw, nh = int(w * scale), int(h * scale)
                frame = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
            else:
                frame = cv2.resize(frame, (rw, rh), interpolation=cv2.INTER_AREA)
        # 格式转换
        fmt = self.config.get("convert_format", "BGR").upper()
        if fmt == "RGB":
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        elif fmt == "GRAY":
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return frame

    # ---------------- 主处理入口 -----------------
    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        # 解析控制命令
        ctrl = inputs.get("control")
        if isinstance(ctrl, dict):
            self._apply_control(ctrl)
        dyn_cfg = inputs.get("config")
        if isinstance(dyn_cfg, dict) and dyn_cfg:
            # 允许运行期 configure (宽松)
            self.configure(dyn_cfg)  # 注意: configure 内部会调用 _on_configure
        frame: Optional[np.ndarray] = None
        # 从队列取最新帧 (丢弃旧帧)
        while True:
            try:
                item = self._queue.get_nowait()
                frame = item
            except Empty:
                break
        # 不再进行同步直接读取: 若队列为空则让 GUI 使用上一帧 (或空占位), 防止并发 capture.read
        if frame is not None and isinstance(frame, np.ndarray):
            frame = self._transform_frame(frame)
            self._last_frame_shape = frame.shape
        else:
            if not self.config.get("autoskip_error", True):
                # 提供更丰富的 meta 状态
                meta_err = {
                    "frame_index": self._frame_index,
                    "playing": not self._paused,
                    "error": "no-frame"
                }
                return {"error": "无帧", "meta": meta_err}
        # 输出节流 (按 target_fps & speed 控制 meta 更新频率)
        now = time.time()
        target_fps = float(self.config.get("target_fps", 30.0)) * self._speed_factor
        min_interval = 1.0 / target_fps if target_fps > 0 else 0.0
        # 简化: 始终更新输出统计, 不严格节流 (GUI 层可自行节流)
        self._last_output_ts = now
        self._output_count += 1
        # 计算输出 FPS 估计
        elapsed = max(now - self._start_time, 1e-6)
        fps_out = self._output_count / elapsed
        progress = None
        if self._total_frames and self._total_frames > 0:
            progress = self._frame_index / self._total_frames
        # 构建状态描述
        status: str = "ok"
        if frame is None:
            status = "no-frame"
        if self.capture and not self.capture.isOpened():
            status = "not-open"
        if self.config.get("source_type") == "file" and not self.config.get("path"):
            status = "empty-path"
        meta = {
            "frame_index": self._frame_index,
            "total_frames": self._total_frames,
            "progress": progress,
            "source": (self.config.get("path") if self.config.get("source_type") == "file" else f"camera:{self.config.get('camera_id')}") ,
            "playing": not self._paused,
            "paused": self._paused,
            "loop": bool(self.config.get("loop", True)),
            "fps_out": fps_out,
            "original_fps": self._orig_fps,
            "shape": list(self._last_frame_shape) if self._last_frame_shape else None,
            "speed": self._speed_factor,
            "timestamp": now,
            "status": status,
        }
        if frame is None:
            return {"meta": meta}
        return {"image": frame, "meta": meta}

    def get_status(self) -> Dict[str, Any]:
        base = super().get_status()
        base.update({
            "frame_index": self._frame_index,
            "total_frames": self._total_frames,
            "original_fps": self._orig_fps,
            "paused": self._paused,
            "speed": self._speed_factor,
        })
        return base
