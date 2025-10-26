#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YOLOv8 分割模块 (yolov8分割)
输入: image
输出: image(标注图), results(包含 box / class / confidence / mask_info)

mask_info: {"index": i, "box": [...], "class_id": int, "class_name": str, "confidence": float, "mask_shape": [h,w]}
（为避免数据庞大暂不直接输出整张mask矩阵，可在后续扩展增加开关）
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

class YoloV8SegmentModule(BaseModule):
    CAPABILITIES = ModuleCapabilities(
        supports_async=False,
        supports_batch=False,
        may_block=True,
        resource_tags=["model", "yolo", "segment"],
        throughput_hint=30.0,
    )

    class ConfigModel(BaseModel):  # type: ignore
        model_path: str = "yolov8n-seg.pt"
        confidence: float = 0.25
        device: str = "auto"
        max_det: int = 100
        show_labels: bool = True
        show_conf: bool = True
        half: bool = False

        @validator("confidence")
        def _conf(cls, v):
            if not (0 <= v <= 1): raise ValueError("confidence 在 [0,1]")
            return v
        @validator("max_det")
        def _md(cls, v):
            if v <= 0: raise ValueError("max_det > 0")
            return v

    def __init__(self, name: str = "yolov8分割"):
        super().__init__(name)
        self.config.update({
            "model_path": "yolov8n-seg.pt",
            "confidence": 0.25,
            "device": "auto",
            "max_det": 100,
            "show_labels": True,
            "show_conf": True,
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
            self.register_output_port("image", port_type="frame", desc="标注后图像")
            self.register_output_port("results", port_type="meta", desc="分割结果列表")
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
        path = self.config.get("model_path", "yolov8n-seg.pt")
        try:
            self._model = YOLO(path)
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
        conf = float(self.config.get("confidence", 0.25))
        max_det = int(self.config.get("max_det", 100))
        device = self._select_device()
        half = bool(self.config.get("half", False)) and device.startswith("cuda")
        try:
            results = self._model.predict(source=arr, conf=conf, verbose=False, max_det=max_det,
                                           device=device, half=half)
        except Exception as e:
            return {"status": f"infer-error: {e}"}
        if not results:
            return {"status": "no-results"}
        r0 = results[0]
        segs: List[Dict[str, Any]] = []
        try:
            boxes = getattr(r0, "boxes", None)
            masks = getattr(r0, "masks", None)
            if boxes is not None and masks is not None:
                xyxy = getattr(boxes, "xyxy", None)
                cls = getattr(boxes, "cls", None)
                confs = getattr(boxes, "conf", None)
                mdata = getattr(masks, "data", None)  # (n,h,w)
                if xyxy is not None and cls is not None and confs is not None:
                    for i in range(len(xyxy)):
                        bb = xyxy[i].tolist()
                        cid = int(cls[i].item()) if hasattr(cls[i], 'item') else int(cls[i])
                        score = float(confs[i].item()) if hasattr(confs[i], 'item') else float(confs[i])
                        mask_shape = []
                        if mdata is not None:
                            ms = mdata[i]
                            mask_shape = list(ms.shape)
                        segs.append({
                            "index": i,
                            "box": [round(b,2) for b in bb],
                            "class_id": cid,
                            "class_name": self._names.get(cid, str(cid)),
                            "confidence": round(score,4),
                            "mask_shape": mask_shape
                        })
        except Exception as e:
            return {"status": f"parse-error: {e}"}
        try:
            annotated = r0.plot(conf=self.config.get("show_conf", True), labels=self.config.get("show_labels", True))
        except Exception:
            annotated = arr
        return {
            "image": annotated,
            "results": segs,
            "status": f"ok:{len(segs)}"
        }

    def get_status(self) -> Dict[str, Any]:
        base = super().get_status()
        base.update({
            "model_loaded": self._model_loaded,
            "failed_reason": self._failed_reason,
            "classes": list(self._names.values()),
        })
        return base
