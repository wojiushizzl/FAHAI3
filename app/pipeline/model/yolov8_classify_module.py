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
        })
        self._model = None
        self._model_loaded = False
        self._names: Dict[int, str] = {}
        self._failed_reason: Optional[str] = None

    @property
    def module_type(self) -> ModuleType:
        return ModuleType.MODEL

    def _define_ports(self):
        if not self.input_ports:
            self.register_input_port("image", port_type="frame", desc="输入图像", required=True)
        if not self.output_ports:
            self.register_output_port("image", port_type="frame", desc="原图输出")
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
        path = self.config.get("model_path", "yolov8n-cls.pt")
        try:
            self._model = YOLO(path)
            # 分类模型 names 中是类别名称列表
            self._names = getattr(self._model, "names", {}) or {}
            self._model_loaded = True
        except Exception as e:
            self._failed_reason = f"模型加载失败: {e}"

    def _on_stop(self):
        self._model = None
        self._model_loaded = False

    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        img = inputs.get("image")
        if img is None or not isinstance(img, np.ndarray):
            return {"status": "no-image"}
        if not self._model_loaded or self._model is None:
            return {"status": f"model-unloaded: {self._failed_reason or 'unknown'}"}
        arr = img
        if arr.ndim == 2:
            arr = np.stack([arr]*3, axis=-1)
        elif arr.shape[2] == 4:
            arr = arr[:, :, :3]
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
        return {
            "image": img,  # 不修改原图
            "results": detections,
            "status": f"ok:{len(detections)}"
        }

    def get_status(self) -> Dict[str, Any]:
        base = super().get_status()
        base.update({
            "model_loaded": self._model_loaded,
            "failed_reason": self._failed_reason,
            "classes": list(self._names.values()),
        })
        return base
