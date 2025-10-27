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
        export_raw: bool = True  # 是否输出原始图像（image_raw）
        enable_target_filter: bool = False  # 是否只输出指定目标类别
        target_classes: List[str] = []       # 目标类别名称(与模型 names 对应, 留空表示不过滤)
        annotate_filtered_only: bool = False  # 标注图是否仅显示过滤后结果

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
            "export_raw": True,
            "enable_target_filter": False,
            "target_classes": [],
            "annotate_filtered_only": False,
        })
        self._model = None
        self._model_loaded = False
        self._names: Dict[int, str] = {}
        self._failed_reason: Optional[str] = None
        # 最近一次推理的尺寸 (H,W,C)
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
        # PyTorch 2.6 weights_only 兼容补丁
        try:
            from app.utils.torch_patch import ensure_torch_load_legacy
            ensure_torch_load_legacy()
        except Exception:
            pass
        model_path = self.config.get("model_path", "yolov8n.pt")
        try:
            self._model = YOLO(model_path)
            # 取类别名称
            self._names = getattr(self._model, "names", {}) or {}
            self._model_loaded = True
        except Exception as e:
            # 若报错与 weights_only 相关，提示可能的兼容问题
            msg = str(e)
            if "weights_only" in msg.lower():
                self._failed_reason = f"模型加载失败(weights_only兼容): {msg}"
            else:
                self._failed_reason = f"模型加载失败: {msg}"

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
        # 更新原始尺寸（使用原始传入图像的 shape）
        try:
            self._last_raw_shape = tuple(img.shape)
        except Exception:
            self._last_raw_shape = None
        # YOLO 输入通常为 BGR; 若后续需要可加颜色转换配置
        conf = float(self.config.get("confidence", 0.25))
        max_det = int(self.config.get("max_det", 100))
        agnostic = bool(self.config.get("agnostic_nms", False))
        device = self._select_device()
        half = bool(self.config.get("half", False)) and device.startswith("cuda")
        try:
            # ultralytics YOLO 调用
            predict_kwargs: Dict[str, Any] = dict(source=arr, conf=conf, verbose=False, max_det=max_det,
                                                 agnostic_nms=agnostic, device=device, half=half)
            # 名称过滤映射：启用 enable_target_filter 时根据 target_classes 名称映射 indices（若提供）
            if bool(self.config.get("enable_target_filter", False)):
                tnames = self.config.get("target_classes", []) or []
                if tnames and self._names:
                    name_to_idx = {str(v).lower(): k for k, v in self._names.items()}
                    mapped = []
                    for nm in tnames:
                        key = str(nm).strip().lower()
                        # 支持数字索引 (字符串或整数)
                        if key.isdigit():
                            try:
                                mapped.append(int(key))
                                continue
                            except ValueError:
                                pass
                        if key in name_to_idx:
                            mapped.append(int(name_to_idx[key]))
                    if mapped:
                        predict_kwargs["classes"] = mapped
                print(mapped)
            results = self._model.predict(**predict_kwargs)
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
                for d in detections:
                    cid = d.get("class_id")
                    cname = d.get("class_name", "").lower()
                    if (cid in index_set) or (cname in norm_name_set):
                        filtered.append(d)
                detections = filtered
        # 可视化标注
        annotated = arr
        try:
            if bool(self.config.get("annotate_filtered_only", False)) and bool(self.config.get("enable_target_filter", False)):
                # 构造一个仿 results 的临时对象，替换 boxes 为过滤后的集合
                # ultralytics Results 对象不可直接简单修改, 这里采用重新绘制策略:
                from copy import deepcopy
                # 若 detections 空则直接返回原图
                if detections:
                    # 创建 mask 图层: 依据 YOLO plot 实现，需要原始 r0.boxes 张量子集
                    try:
                        # 获取原 box/cls/conf 张量并根据 filtered indices 重组
                        all_indices = []
                        id_map = []
                        if hasattr(r0, 'boxes') and r0.boxes is not None:
                            xyxy = getattr(r0.boxes, 'xyxy', None)
                            cls_tensor = getattr(r0.boxes, 'cls', None)
                            conf_tensor = getattr(r0.boxes, 'conf', None)
                            if xyxy is not None and cls_tensor is not None and conf_tensor is not None:
                                # 通过匹配坐标近似确定索引 (简单策略：首个匹配)
                                for d in detections:
                                    bb = d['box']
                                    # 在 xyxy 中寻找完全相同四元组
                                    match_idx = None
                                    for i in range(len(xyxy)):
                                        arr_bb = xyxy[i].tolist()
                                        arr_bb_r = [round(x,2) for x in arr_bb]
                                        if arr_bb_r == bb:
                                            match_idx = i
                                            break
                                    if match_idx is not None:
                                        all_indices.append(match_idx)
                        if all_indices:
                            import torch
                            # 构造子 boxes 对象
                            sub_boxes = deepcopy(r0.boxes)
                            sub_boxes.xyxy = r0.boxes.xyxy[all_indices]
                            sub_boxes.cls = r0.boxes.cls[all_indices]
                            sub_boxes.conf = r0.boxes.conf[all_indices]
                            # 临时替换 plot 时使用的 boxes
                            original_boxes = r0.boxes
                            r0.boxes = sub_boxes
                            try:
                                annotated = r0.plot(conf=self.config.get("show_conf", True), labels=self.config.get("show_labels", True))
                            finally:
                                r0.boxes = original_boxes
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
        })
        return base
