#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YOLOv8 检测模块 (yolov8检测)
输入: image (numpy ndarray BGR/RGB/GRAY)
输出: image (带标注的图), results (检测结果列表)

依赖: ultralytics (自动拉取 torch)。请在环境中安装:
  pip install ultralytics

配置字段 (pydantic 验证):
  model_path: 模型权重文件或内置名称 (默认 yolov8n.pt)
  confidence: 置信度阈值 (0~1)
  device: auto|cpu|cuda|cuda:0 等 (auto 根据 torch.cuda.is_available)
  max_det: 最大检测数
  agnostic_nms: 是否类别无关 NMS
  show_labels: 结果可视化时是否绘制标签
  show_conf: 是否在标注中显示置信度
  half: FP16 推理 (仅在 CUDA 可用时生效)

results 输出示例 (list[dict]):
  [{"box": [x1,y1,x2,y2], "confidence": 0.87, "class_id": 0, "class_name": "person"}, ...]

错误处理: 若模型未加载或输入异常则返回 {"status": "error: ..."} 仅在 results 端口写入。
"""
from typing import Any, Dict, List, Optional
import numpy as np
from app.pipeline.base_module import BaseModule, ModuleType, ModuleCapabilities

try:
    from pydantic import BaseModel, validator
except ImportError:
    BaseModel = object  # type: ignore
    def validator(*args, **kwargs):  # type: ignore
        def _wrap(fn):
            return fn
        return _wrap

class YoloV8DetectModule(BaseModule):
    CAPABILITIES = ModuleCapabilities(
        supports_async=False,
        supports_batch=False,
        may_block=True,
        resource_tags=["model", "yolo", "detect"],
        throughput_hint=60.0,
    )

    class ConfigModel(BaseModel):  # type: ignore
        model_path: str = "yolov8n.pt"
        confidence: float = 0.25
        device: str = "auto"
        max_det: int = 100
        agnostic_nms: bool = False
        show_labels: bool = True
        show_conf: bool = True
        half: bool = False

        @validator("confidence")
        def _conf(cls, v):
            if not (0 <= v <= 1):
                raise ValueError("confidence 必须在 [0,1]")
            return v
        @validator("max_det")
        def _md(cls, v):
            if v <= 0:
                raise ValueError("max_det > 0")
            return v

    def __init__(self, name: str = "yolov8检测"):
        super().__init__(name)
        # 默认配置初始写入（避免未调用 configure 时缺省）
        self.config.update({
            "model_path": "yolov8n.pt",
            "confidence": 0.25,
            "device": "auto",
            "max_det": 100,
            "agnostic_nms": False,
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
            self.register_output_port("results", port_type="meta", desc="检测结果列表")
            self.register_output_port("status", port_type="meta", desc="运行状态")

    def _select_device(self) -> str:
        device_cfg = self.config.get("device", "auto")
        if device_cfg == "auto":
            try:
                import torch
                return "cuda" if torch.cuda.is_available() else "cpu"
            except Exception:
                return "cpu"
        return device_cfg

    def _on_start(self):
        if self._model_loaded:
            return
        try:
            from ultralytics import YOLO  # type: ignore
        except Exception as e:
            self._failed_reason = f"未安装 ultralytics: {e}"
            return
        model_path = self.config.get("model_path", "yolov8n.pt")
        try:
            self._model = YOLO(model_path)
            # 取类别名称
            self._names = getattr(self._model, "names", {}) or {}
            self._model_loaded = True
        except Exception as e:
            self._failed_reason = f"模型加载失败: {e}"

    def _on_stop(self):
        # 释放模型引用（便于显式 GC）
        self._model = None
        self._model_loaded = False

    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        img = inputs.get("image")
        if img is None or not isinstance(img, np.ndarray):
            return {"status": "no-image"}
        if not self._model_loaded or self._model is None:
            return {"status": f"model-unloaded: {self._failed_reason or 'unknown'}"}
        # 规范图像: 保证 3 通道
        arr = img
        if arr.ndim == 2:
            arr = np.stack([arr]*3, axis=-1)
        elif arr.shape[2] == 4:
            arr = arr[:, :, :3]
        # YOLO 输入通常为 BGR; 若后续需要可加颜色转换配置
        conf = float(self.config.get("confidence", 0.25))
        max_det = int(self.config.get("max_det", 100))
        agnostic = bool(self.config.get("agnostic_nms", False))
        device = self._select_device()
        half = bool(self.config.get("half", False)) and device.startswith("cuda")
        try:
            # ultralytics YOLO 调用
            results = self._model.predict(source=arr, conf=conf, verbose=False, max_det=max_det,
                                           agnostic_nms=agnostic, device=device, half=half)
        except Exception as e:
            return {"status": f"infer-error: {e}"}
        if not results:
            return {"status": "no-results"}
        r0 = results[0]
        # 构造结果列表
        detections: List[Dict[str, Any]] = []
        try:
            if hasattr(r0, "boxes") and r0.boxes is not None:
                # boxes.xyxy, boxes.cls, boxes.conf
                xyxy = getattr(r0.boxes, "xyxy", None)
                cls = getattr(r0.boxes, "cls", None)
                confs = getattr(r0.boxes, "conf", None)
                if xyxy is not None and cls is not None and confs is not None:
                    for i in range(len(xyxy)):
                        bb = xyxy[i].tolist()
                        cid = int(cls[i].item()) if hasattr(cls[i], 'item') else int(cls[i])
                        score = float(confs[i].item()) if hasattr(confs[i], 'item') else float(confs[i])
                        detections.append({
                            "box": [round(b,2) for b in bb],
                            "confidence": round(score,4),
                            "class_id": cid,
                            "class_name": self._names.get(cid, str(cid))
                        })
        except Exception as e:
            return {"status": f"parse-error: {e}"}
        # 可视化标注
        try:
            annotated = r0.plot(conf=self.config.get("show_conf", True), labels=self.config.get("show_labels", True))
        except Exception:
            annotated = arr
        return {
            "image": annotated,
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
