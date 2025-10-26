#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模型推理模块 (完整版本)
原始实现迁移至分类目录，保留加载/预处理/后处理框架。
"""
import os
import time
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from app.pipeline.base_module import BaseModule, ModuleType, ModuleCapabilities
try:
    from pydantic import BaseModel as PydModel, validator
except ImportError:
    PydModel = object  # type: ignore
from app.models.base_model import BaseModel as InferenceBaseModel


class ModelModule(BaseModule):
    CAPABILITIES = ModuleCapabilities(
        supports_async=False,
        supports_batch=True,
        may_block=True,
        resource_tags=["model", "inference"],
        throughput_hint=15.0,
    )

    class ConfigModel(PydModel):  # type: ignore
        model_type: str = "detection"
        model_path: str = ""
        model_format: str = "onnx"
        input_size: List[int] = [640, 640]
        confidence_threshold: float = 0.5
        nms_threshold: float = 0.4
        max_detections: int = 100
        class_names: List[str] = []
        device: str = "auto"
        batch_size: int = 1
        preprocessing: Dict[str, Any] = {
            "normalize": True,
            "mean": [0.485, 0.456, 0.406],
            "std": [0.229, 0.224, 0.225],
            "letterbox": True,
            "bgr2rgb": True
        }
        postprocessing: Dict[str, Any] = {
            "filter_classes": [],
            "min_area": 100,
            "max_area": -1,
            "aspect_ratio_range": [0.1, 10.0]
        }

        @validator("input_size")
        def _size_ok(cls, v):
            if len(v) != 2 or v[0] <= 0 or v[1] <= 0:
                raise ValueError("input_size 必须为正的 [w,h]")
            return v

        @validator("confidence_threshold", "nms_threshold")
        def _prob_ok(cls, v):
            if not (0 <= v <= 1):
                raise ValueError("阈值需在 0~1 范围")
            return v

        @validator("batch_size")
        def _batch_ok(cls, v):
            if v <= 0:
                raise ValueError("batch_size 必须 > 0")
            return v

    def __init__(self, name: str = "模型模块"):
        super().__init__(name)
        self.model = None  # 实际推理模型实例
        self.model_loaded = False
        self.inference_count = 0
        self.total_inference_time = 0.0
        self.last_inference_time = 0.0
        self.config.update({
            "model_type": "detection",
            "model_path": "",
            "model_format": "onnx",
            "input_size": [640, 640],
            "confidence_threshold": 0.5,
            "nms_threshold": 0.4,
            "max_detections": 100,
            "class_names": [],
            "device": "auto",
            "batch_size": 1,
            "preprocessing": {
                "normalize": True,
                "mean": [0.485, 0.456, 0.406],
                "std": [0.229, 0.224, 0.225],
                "letterbox": True,
                "bgr2rgb": True
            },
            "postprocessing": {
                "filter_classes": [],
                "min_area": 100,
                "max_area": -1,
                "aspect_ratio_range": [0.1, 10.0]
            }
        })

    @property
    def module_type(self) -> ModuleType:
        return ModuleType.MODEL

    def _define_ports(self):
        if not self.input_ports:
            self.register_input_port("image", port_type="frame", desc="输入图像", required=True)
            self.register_input_port("roi", port_type="region", desc="兴趣区域ROI", required=False)
        if not self.output_ports:
            self.register_output_port("detections", port_type="result", desc="检测/推理结果")
            self.register_output_port("inference_info", port_type="meta", desc="推理信息")

    def _on_start(self):
        if not self.model_loaded:
            if not self._load_model():
                raise RuntimeError("模型加载失败")

    def _on_stop(self):
        pass

    def _on_configure(self, config: Dict[str, Any]):
        # pydantic 校验后模型路径变更需要重新加载
        if "model_path" in config and config["model_path"] != self.config.get("model_path"):
            self.model_loaded = False
            self._load_model()

    def _load_model(self) -> bool:
        path = self.config.get("model_path")
        if not path:
            self.logger.warning("未指定模型路径")
            return False
        if not os.path.exists(path):
            self.logger.error(f"模型文件不存在: {path}")
            return False
        try:
            self.logger.info(f"加载模型: {path}")
            # 使用基础推理模型占位（真实实现可替换）
            self.model = InferenceBaseModel()
            if self.model.load(path, self.config):
                self.model_loaded = True
                return True
            self.logger.error("模型初始化失败")
            return False
        except Exception as e:
            self.logger.error(f"模型加载异常: {e}")
            return False

    def _preprocess_image(self, image: np.ndarray, roi: Optional[Dict] = None) -> Optional[np.ndarray]:
        if image is None:
            return None
        if roi:
            x, y = roi.get("x", 0), roi.get("y", 0)
            w, h = roi.get("width", image.shape[1]), roi.get("height", image.shape[0])
            image = image[y:y+h, x:x+w]
        prep = self.config.get("preprocessing", {})
        if prep.get("bgr2rgb", True) and len(image.shape) == 3:
            image = image[:, :, ::-1]
        target = self.config.get("input_size", [640, 640])
        import cv2
        if prep.get("letterbox", True):
            image = self._letterbox_resize(image, target)
        else:
            image = cv2.resize(image, tuple(target))
        if prep.get("normalize", True):
            image = image.astype(np.float32) / 255.0
            mean = np.array(prep.get("mean", [0.485, 0.456, 0.406]))
            std = np.array(prep.get("std", [0.229, 0.224, 0.225]))
            image = (image - mean) / std
        if len(image.shape) == 3:
            image = image.transpose(2, 0, 1)
            image = np.expand_dims(image, 0)
        return image

    def _letterbox_resize(self, image: np.ndarray, target_size: List[int]) -> np.ndarray:
        import cv2
        h, w = image.shape[:2]
        tw, th = target_size
        scale = min(tw / w, th / h)
        nw, nh = int(w * scale), int(h * scale)
        resized = cv2.resize(image, (nw, nh))
        result = np.full((th, tw, 3), 114, dtype=np.uint8)
        top = (th - nh) // 2
        left = (tw - nw) // 2
        result[top:top+nh, left:left+nw] = resized
        return result

    def _postprocess_results(self, raw: Any, shape: Tuple[int, int]) -> Dict[str, Any]:
        # 占位后处理，根据模型类型扩展
        return {"detections": [], "count": 0}

    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not self.model_loaded or not self.model:
            return {"error": "模型未加载"}
        image = inputs.get("image")
        if image is None:
            return {"error": "缺少输入图像"}
        roi = inputs.get("roi")
        start = time.time()
        processed = self._preprocess_image(image, roi)
        if processed is None:
            return {"error": "预处理失败"}
        raw = self.model.inference(processed)
        results = self._postprocess_results(raw, image.shape[:2])
        infer_time = time.time() - start
        self.inference_count += 1
        self.total_inference_time += infer_time
        self.last_inference_time = infer_time
        results["inference_info"] = {
            "inference_time": infer_time,
            "inference_count": self.inference_count,
            "average_time": self.total_inference_time / self.inference_count,
            "timestamp": time.time()
        }
        return results

    def get_inference_statistics(self) -> Dict[str, Any]:
        avg = self.total_inference_time / self.inference_count if self.inference_count else 0
        return {
            "total_inferences": self.inference_count,
            "total_time": self.total_inference_time,
            "average_time": avg,
            "last_inference_time": self.last_inference_time,
            "fps": 1.0 / avg if avg > 0 else 0
        }
