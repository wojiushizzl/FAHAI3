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
        export_raw: bool = True  # 是否输出原始图像端口
        enable_target_filter: bool = False  # 是否启用目标类别过滤
        target_classes: List[str] = []       # 要保留的类别名称列表
        annotate_filtered_only: bool = False  # 标注图仅显示过滤后结果

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
            "export_raw": True,
            "enable_target_filter": False,
            "target_classes": [],
            "annotate_filtered_only": False,
        })
        self._model = None
        self._model_loaded = False
        self._names: Dict[int, str] = {}
        self._failed_reason: Optional[str] = None
        self._last_raw_shape: Optional[tuple] = None
        self._last_annotated_shape: Optional[tuple] = None

    @property
    def module_type(self) -> ModuleType:
        return ModuleType.MODEL

    def _define_ports(self):
        if not self.input_ports:
            self.register_input_port("image", port_type="frame", desc="输入图像", required=True)
        if not self.output_ports:
            self.register_output_port("image_raw", port_type="frame", desc="原始输入图像")
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
        # PyTorch 2.6 weights_only 兼容补丁
        try:
            from app.utils.torch_patch import ensure_torch_load_legacy
            ensure_torch_load_legacy()
        except Exception:
            pass
        path = self.config.get("model_path", "yolov8n-seg.pt")
        try:
            self._model = YOLO(path)
            self._names = getattr(self._model, "names", {}) or {}
            self._model_loaded = True
        except Exception as e:
            msg = str(e)
            if "weights_only" in msg.lower():
                self._failed_reason = f"模型加载失败(weights_only兼容): {msg}"
            else:
                self._failed_reason = f"模型加载失败: {msg}"

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
        try:
            self._last_raw_shape = tuple(img.shape)
        except Exception:
            self._last_raw_shape = None
        conf = float(self.config.get("confidence", 0.25))
        max_det = int(self.config.get("max_det", 100))
        device = self._select_device()
        half = bool(self.config.get("half", False)) and device.startswith("cuda")
        try:
            predict_kwargs: Dict[str, Any] = dict(source=arr, conf=conf, verbose=False, max_det=max_det,
                                                 device=device, half=half)
            if bool(self.config.get("enable_target_filter", False)):
                tnames = self.config.get("target_classes", []) or []
                if tnames and self._names:
                    name_to_idx = {str(v).lower(): k for k, v in self._names.items()}
                    mapped = []
                    for nm in tnames:
                        key = str(nm).strip().lower()
                        if key in name_to_idx:
                            mapped.append(int(name_to_idx[key]))
                    if mapped:
                        predict_kwargs["classes"] = mapped
            results = self._model.predict(**predict_kwargs)
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
        # 目标过滤逻辑
        if bool(self.config.get("enable_target_filter", False)):
            target_list = self.config.get("target_classes", []) or []
            norm_name_set = set()
            index_set = set()
            for t in target_list:
                s = str(t).strip()
                if not s:
                    continue
                if s.isdigit():
                    try:
                        index_set.add(int(s))
                    except ValueError:
                        pass
                else:
                    norm_name_set.add(s.lower())
            if norm_name_set or index_set:
                filtered = []
                for d in segs:
                    cid = d.get("class_id")
                    cname = d.get("class_name", "").lower()
                    if (cid in index_set) or (cname in norm_name_set):
                        filtered.append(d)
                segs = filtered
        # 标注图绘制（支持 annotate_filtered_only 仅绘制过滤后目标）
        annotated = arr
        try:
            if bool(self.config.get("annotate_filtered_only", False)) and bool(self.config.get("enable_target_filter", False)):
                # 当启用并存在过滤结果时裁剪 boxes + masks
                if segs:
                    from copy import deepcopy
                    try:
                        # 建立匹配索引集合：通过 box 坐标匹配 (与检测模块策略一致)
                        match_indices = []
                        orig_boxes = getattr(r0, 'boxes', None)
                        boxes_xyxy = getattr(orig_boxes, 'xyxy', None)
                        if orig_boxes is not None and boxes_xyxy is not None:
                            for d in segs:
                                bb = d.get('box')
                                # 在原 boxes 中寻找坐标完全相同的四元组（四舍五入至2位与构造时一致）
                                found = None
                                for i in range(len(boxes_xyxy)):
                                    arr_bb = boxes_xyxy[i].tolist()
                                    arr_bb_r = [round(x,2) for x in arr_bb]
                                    if arr_bb_r == bb:
                                        found = i
                                        break
                                if found is not None:
                                    match_indices.append(found)
                        if match_indices:
                            # 构造子集 boxes
                            sub_boxes = deepcopy(orig_boxes)
                            sub_boxes.xyxy = orig_boxes.xyxy[match_indices]
                            sub_boxes.cls = orig_boxes.cls[match_indices]
                            sub_boxes.conf = orig_boxes.conf[match_indices]
                            # 构造子集 masks (若存在)
                            orig_masks = getattr(r0, 'masks', None)
                            sub_masks = None
                            if orig_masks is not None and hasattr(orig_masks, 'data'):
                                sub_masks = deepcopy(orig_masks)
                                sub_masks.data = orig_masks.data[match_indices]
                            # 临时替换 r0 的 boxes/masks 用于 plot
                            original_boxes = r0.boxes
                            original_masks = getattr(r0, 'masks', None)
                            r0.boxes = sub_boxes
                            if sub_masks is not None:
                                r0.masks = sub_masks
                            try:
                                annotated = r0.plot(conf=self.config.get("show_conf", True), labels=self.config.get("show_labels", True))
                            finally:
                                r0.boxes = original_boxes
                                if sub_masks is not None and original_masks is not None:
                                    r0.masks = original_masks
                        else:
                            annotated = arr
                    except Exception:
                        annotated = r0.plot(conf=self.config.get("show_conf", True), labels=self.config.get("show_labels", True))
                else:
                    annotated = arr
            else:
                annotated = r0.plot(conf=self.config.get("show_conf", True), labels=self.config.get("show_labels", True))
        except Exception:
            annotated = arr
        try:
            self._last_annotated_shape = tuple(annotated.shape)
        except Exception:
            self._last_annotated_shape = None
        return {
            "image_raw": img if bool(self.config.get("export_raw", True)) else None,
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
            "last_raw_shape": self._last_raw_shape,
            "last_annotated_shape": self._last_annotated_shape,
        })
        return base
