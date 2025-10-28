#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YOLOv8 分类模块 (yolov8分类)
输入: image
输出: image(可选同输入), results(分类 Top-N 列表)

results: [{"class_id": int, "class_name": str, "confidence": float}, ...]
"""
from typing import Any, Dict, List, Optional
import numpy as np
from app.pipeline.base_module import BaseModule, ModuleType, ModuleCapabilities
try:
    from pydantic import BaseModel, validator
except ImportError:
    BaseModel = object  # type: ignore
    def validator(*args, **kwargs):
        def _wrap(fn): return fn
        return _wrap

class YoloV8ClassifyModule(BaseModule):
    CAPABILITIES = ModuleCapabilities(
        supports_async=False,
        supports_batch=False,
        may_block=True,
        resource_tags=["model", "yolo", "classify"],
        throughput_hint=120.0,
    )

    class ConfigModel(BaseModel):  # type: ignore
        model_path: str = "yolov8n-cls.pt"
        device: str = "auto"
        top_n: int = 5
        half: bool = False
        export_raw: bool = True  # 是否输出原始图像端口
        background_warmup: bool = True  # 后台预热
        warmup_iterations: int = 2      # 预热次数
        warmup_image_size: int = 224    # 分类模型默认输入尺寸（可根据权重自适应）
        deferred_first_infer: bool = True  # 预热期间延迟真实推理

        @validator("top_n")
        def _tn(cls, v):
            if v <= 0: raise ValueError("top_n > 0")
            return v

    def __init__(self, name: str = "yolov8分类"):
        super().__init__(name)
        self.config.update({
            "model_path": "yolov8n-cls.pt",
            "device": "auto",
            "top_n": 5,
            "half": False,
            "export_raw": True,
            "background_warmup": True,
            "warmup_iterations": 2,
            "warmup_image_size": 224,
            "deferred_first_infer": True,
        })
        self._model = None
        self._model_loaded = False
        self._names: Dict[int, str] = {}
        self._failed_reason: Optional[str] = None
        self._last_raw_shape: Optional[tuple] = None
        self._last_annotated_shape: Optional[tuple] = None  # 分类不修改图像, 等同 raw
        # 预热状态
        self._warming: bool = False
        self._warmup_done: bool = False
        self._warmup_error: Optional[str] = None
        self._warmup_iters_completed: int = 0
        self._warmup_thread = None

    @property
    def module_type(self) -> ModuleType:
        return ModuleType.MODEL

    def _define_ports(self):
        if not self.input_ports:
            self.register_input_port("image", port_type="frame", desc="输入图像", required=True)
            self.register_input_port("control", port_type="bool", desc="推理控制: False 跳过", required=False)
        if not self.output_ports:
            self.register_output_port("image_raw", port_type="frame", desc="原始输入图像")
            self.register_output_port("image", port_type="frame", desc="(分类)保持原图")
            self.register_output_port("results", port_type="meta", desc="分类结果")
            self.register_output_port("status", port_type="meta", desc="状态")

    def _select_device(self) -> str:
        dev = self.config.get("device", "auto")
        if dev == "auto":
            try:
                import torch
                return "cuda" if torch.cuda.is_available() else "cpu"
            except Exception:
                return "cpu"
        return dev

    def _on_start(self):
        if self._model_loaded:
            return
        try:
            from ultralytics import YOLO  # type: ignore
        except Exception as e:
            self._failed_reason = f"未安装 ultralytics: {e}"
            return
        # PyTorch 2.6 weights_only 兼容补丁
        try:
            from app.utils.torch_patch import ensure_torch_load_legacy
            ensure_torch_load_legacy()
        except Exception:
            pass
        path = self.config.get("model_path", "yolov8n-cls.pt")
        try:
            self._model = YOLO(path)
            # 分类模型 names 中是类别名称列表
            self._names = getattr(self._model, "names", {}) or {}
            self._model_loaded = True
            if bool(self.config.get("background_warmup", True)):
                self._start_warmup_thread()
        except Exception as e:
            msg = str(e)
            if "weights_only" in msg.lower():
                self._failed_reason = f"模型加载失败(weights_only兼容): {msg}"
            else:
                self._failed_reason = f"模型加载失败: {msg}"

    def _on_stop(self):
        self._model = None
        self._model_loaded = False
        try:
            if self._warming and self._warmup_thread is not None:
                import threading
                if isinstance(self._warmup_thread, threading.Thread):
                    self._warmup_thread.join(timeout=0.5)
        except Exception:
            pass

    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        ctrl = inputs.get("control")
        if ctrl is not None:
            if isinstance(ctrl, (int, float)):
                ctrl_val = (ctrl != 0)
            elif isinstance(ctrl, str):
                v = ctrl.strip().lower()
                ctrl_val = v in {"true","1","yes","y","run","start"}
                if v in {"false","0","no","n","stop","pause"}:
                    ctrl_val = False
            else:
                ctrl_val = bool(ctrl)
            if not ctrl_val:
                return {"status": "skipped"}
        img = inputs.get("image")
        if img is None or not isinstance(img, np.ndarray):
            return {"status": "no-image"}
        if not self._model_loaded or self._model is None:
            return {"status": f"model-unloaded: {self._failed_reason or 'unknown'}"}
        if bool(self.config.get("deferred_first_infer", True)) and self._warming and not self._warmup_done:
            return {"status": f"warming:{self._warmup_iters_completed}/{self.config.get('warmup_iterations',0)}"}
        arr = img
        if arr.ndim == 2:
            arr = np.stack([arr]*3, axis=-1)
        elif arr.shape[2] == 4:
            arr = arr[:, :, :3]
        try:
            self._last_raw_shape = tuple(img.shape)
        except Exception:
            self._last_raw_shape = None
        device = self._select_device()
        half = bool(self.config.get("half", False)) and device.startswith("cuda")
        try:
            results = self._model.predict(source=arr, verbose=False, device=device, half=half)
        except Exception as e:
            return {"status": f"infer-error: {e}"}
        if not results:
            return {"status": "no-results"}
        r0 = results[0]
        detections: List[Dict[str, Any]] = []
        try:
            probs = getattr(r0, "probs", None)
            if probs is not None and hasattr(probs, "top1"):
                # probs.data 是向量
                data = getattr(probs, "data", None)
                if data is not None:
                    arr_probs = data.cpu().numpy() if hasattr(data, "cpu") else data
                    top_n = int(self.config.get("top_n", 5))
                    idx_sorted = arr_probs.argsort()[::-1][:top_n]
                    for i in idx_sorted:
                        detections.append({
                            "class_id": int(i),
                            "class_name": self._names.get(int(i), str(i)),
                            "confidence": round(float(arr_probs[i]), 5)
                        })
        except Exception as e:
            return {"status": f"parse-error: {e}"}
        self._last_annotated_shape = self._last_raw_shape
        return {
            "image_raw": img if bool(self.config.get("export_raw", True)) else None,
            "image": img,
            "results": detections,
            "status": f"ok:{len(detections)}"
        }

    def get_status(self) -> Dict[str, Any]:
        base = super().get_status()
        base.update({
            "model_loaded": self._model_loaded,
            "failed_reason": self._failed_reason,
            "classes": list(self._names.values()),
            "last_raw_shape": self._last_raw_shape,
            "last_annotated_shape": self._last_annotated_shape,
            "warming": self._warming,
            "warmup_done": self._warmup_done,
            "warmup_error": self._warmup_error,
            "warmup_iters_completed": self._warmup_iters_completed,
        })
        return base

    def warmup_async(self):
        """公开预热接口: 若未加载则加载, 然后启动后台预热."""
        try:
            if not self._model_loaded:
                self._on_start()
            if self._model_loaded and not self._warmup_done and not self._warming:
                self._start_warmup_thread()
        except Exception as e:
            self._warmup_error = f"warmup-async-error: {e}"

    # ---------------- 预热实现 -----------------
    def _start_warmup_thread(self):
        if self._warming or self._warmup_done or not self._model_loaded or self._model is None:
            return
        import threading
        self._warming = True
        self._warmup_error = None
        self._warmup_iters_completed = 0
        iters = max(0, int(self.config.get("warmup_iterations", 0)))
        img_size = int(self.config.get("warmup_image_size", 224))
        device = self._select_device()
        half = bool(self.config.get("half", False)) and device.startswith("cuda")

        def _run_warmup():
            try:
                if iters <= 0:
                    return
                import numpy as _np
                dummy = (_np.random.rand(img_size, img_size, 3) * 255).astype(_np.uint8)
                for i in range(iters):
                    try:
                        self._model.predict(source=dummy, verbose=False, device=device, half=half)
                    except Exception as _ie:
                        self._warmup_error = f"warmup-infer-error: {_ie}"
                        break
                    self._warmup_iters_completed = i + 1
            except Exception as e:
                self._warmup_error = f"warmup-error: {e}"
            finally:
                self._warming = False
                self._warmup_done = True if self._warmup_error is None else False
        th = threading.Thread(target=_run_warmup, name=f"yolo8-cls-warmup-{self.name}", daemon=True)
        self._warmup_thread = th
        th.start()
