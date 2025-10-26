#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模型基类
定义AI模型的通用接口和基础功能
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple, Union
import os
import time
import logging
import numpy as np


class ModelFormat:
    """模型格式常量"""
    ONNX = "onnx"
    TENSORRT = "tensorrt"
    PYTORCH = "pytorch"
    TENSORFLOW = "tensorflow"
    OPENVINO = "openvino"
    PADDLE = "paddle"


class ModelType:
    """模型类型常量"""
    DETECTION = "detection"
    CLASSIFICATION = "classification"
    SEGMENTATION = "segmentation"
    REGRESSION = "regression"
    CUSTOM = "custom"


class BaseModel(ABC):
    """
    AI模型基类，定义所有模型的通用接口
    支持多种模型格式和推理引擎
    """
    
    def __init__(self, model_path: str = "", config: Dict[str, Any] = None):
        """
        初始化模型
        
        Args:
            model_path: 模型文件路径
            config: 模型配置参数
        """
        self.model_path = model_path
        self.config = config or {}
        
        # 模型信息
        self.model_name = os.path.basename(model_path) if model_path else "BaseModel"
        self.model_format = self.config.get("model_format", ModelFormat.ONNX)
        self.model_type = self.config.get("model_type", ModelType.DETECTION)
        
        # 模型状态
        self.is_loaded = False
        self.device = self.config.get("device", "auto")
        self.batch_size = self.config.get("batch_size", 1)
        
        # 输入输出信息
        self.input_shape = None
        self.output_shape = None
        self.input_names = []
        self.output_names = []
        
        # 性能统计
        self.inference_count = 0
        self.total_inference_time = 0.0
        self.last_inference_time = 0.0
        
        # 预处理和后处理配置
        self.preprocessing_config = self.config.get("preprocessing", {})
        self.postprocessing_config = self.config.get("postprocessing", {})
        
        # 类别信息
        self.class_names = self.config.get("class_names", [])
        self.num_classes = len(self.class_names)
        
        # 日志
        self.logger = logging.getLogger(f"{self.__class__.__name__}.{id(self)}")
        
        # 模型实例（由子类实现）
        self.model = None
        self.session = None
        
    @property
    @abstractmethod
    def supported_formats(self) -> List[str]:
        """返回支持的模型格式列表"""
        pass
        
    @abstractmethod
    def load(self, model_path: str, config: Dict[str, Any] = None) -> bool:
        """
        加载模型
        
        Args:
            model_path: 模型文件路径
            config: 加载配置
            
        Returns:
            加载成功返回True
        """
        pass
        
    @abstractmethod
    def inference(self, inputs: Union[np.ndarray, Dict[str, np.ndarray]]) -> Any:
        """
        执行推理
        
        Args:
            inputs: 输入数据
            
        Returns:
            推理结果
        """
        pass
        
    def unload(self):
        """卸载模型"""
        if self.is_loaded:
            self.model = None
            self.session = None
            self.is_loaded = False
            self.logger.info("模型已卸载")
            
    def preprocess(self, inputs: Any) -> Union[np.ndarray, Dict[str, np.ndarray]]:
        """
        预处理输入数据
        
        Args:
            inputs: 原始输入数据
            
        Returns:
            预处理后的数据
        """
        # 默认实现，子类可以重写
        if isinstance(inputs, np.ndarray):
            return self._preprocess_array(inputs)
        else:
            return inputs
            
    def postprocess(self, outputs: Any) -> Any:
        """
        后处理模型输出
        
        Args:
            outputs: 模型原始输出
            
        Returns:
            后处理后的结果
        """
        # 默认实现，子类可以重写
        return outputs
        
    def _preprocess_array(self, array: np.ndarray) -> np.ndarray:
        """预处理数组数据"""
        # 数据类型转换
        if array.dtype != np.float32:
            array = array.astype(np.float32)
            
        # 归一化
        if self.preprocessing_config.get("normalize", False):
            if array.max() > 1.0:
                array = array / 255.0
                
        # 标准化
        if "mean" in self.preprocessing_config and "std" in self.preprocessing_config:
            mean = np.array(self.preprocessing_config["mean"])
            std = np.array(self.preprocessing_config["std"])
            array = (array - mean) / std
            
        # 调整维度
        if len(array.shape) == 3 and self.preprocessing_config.get("add_batch_dim", True):
            array = np.expand_dims(array, axis=0)
            
        return array
        
    def validate_input(self, inputs: Any) -> bool:
        """
        验证输入数据格式
        
        Args:
            inputs: 输入数据
            
        Returns:
            验证通过返回True
        """
        if not self.is_loaded:
            self.logger.error("模型未加载")
            return False
            
        if isinstance(inputs, np.ndarray):
            # 验证数组维度
            if self.input_shape and inputs.shape != self.input_shape:
                self.logger.warning(f"输入形状不匹配，期望: {self.input_shape}, 实际: {inputs.shape}")
                
        elif isinstance(inputs, dict):
            # 验证字典输入
            for name in self.input_names:
                if name not in inputs:
                    self.logger.error(f"缺少输入: {name}")
                    return False
                    
        return True
        
    def benchmark(self, inputs: Any, iterations: int = 100) -> Dict[str, float]:
        """
        性能测试
        
        Args:
            inputs: 测试输入数据
            iterations: 测试迭代次数
            
        Returns:
            性能统计结果
        """
        if not self.is_loaded:
            raise RuntimeError("模型未加载")
            
        self.logger.info(f"开始性能测试，迭代次数: {iterations}")
        
        times = []
        
        # 预热
        for _ in range(5):
            self.inference(inputs)
            
        # 正式测试
        for i in range(iterations):
            start_time = time.time()
            self.inference(inputs)
            end_time = time.time()
            
            times.append(end_time - start_time)
            
            if (i + 1) % 10 == 0:
                self.logger.debug(f"完成 {i + 1}/{iterations} 次测试")
                
        # 计算统计信息
        times = np.array(times)
        
        result = {
            "iterations": iterations,
            "total_time": float(np.sum(times)),
            "average_time": float(np.mean(times)),
            "min_time": float(np.min(times)),
            "max_time": float(np.max(times)),
            "std_time": float(np.std(times)),
            "throughput": iterations / np.sum(times),  # 吞吐量 (推理/秒)
            "fps": 1.0 / np.mean(times)  # 帧率
        }
        
        self.logger.info(f"性能测试完成: 平均耗时 {result['average_time']*1000:.2f}ms, "
                        f"FPS: {result['fps']:.2f}")
        
        return result
        
    def warm_up(self, inputs: Any = None, iterations: int = 5):
        """
        模型预热
        
        Args:
            inputs: 预热输入数据，如果为空则生成随机数据
            iterations: 预热迭代次数
        """
        if not self.is_loaded:
            self.logger.warning("模型未加载，跳过预热")
            return
            
        self.logger.info(f"开始模型预热，迭代次数: {iterations}")
        
        # 生成随机输入数据
        if inputs is None:
            inputs = self._generate_dummy_input()
            
        for i in range(iterations):
            try:
                self.inference(inputs)
                self.logger.debug(f"预热迭代 {i+1}/{iterations} 完成")
            except Exception as e:
                self.logger.error(f"预热迭代 {i+1} 失败: {e}")
                
        self.logger.info("模型预热完成")
        
    def _generate_dummy_input(self) -> Any:
        """生成虚拟输入数据"""
        if self.input_shape:
            return np.random.randn(*self.input_shape).astype(np.float32)
        else:
            # 默认生成常见的图像输入
            return np.random.randn(1, 3, 224, 224).astype(np.float32)
            
    def get_model_info(self) -> Dict[str, Any]:
        """获取模型信息"""
        return {
            "model_name": self.model_name,
            "model_path": self.model_path,
            "model_format": self.model_format,
            "model_type": self.model_type,
            "is_loaded": self.is_loaded,
            "device": self.device,
            "batch_size": self.batch_size,
            "input_shape": self.input_shape,
            "output_shape": self.output_shape,
            "input_names": self.input_names,
            "output_names": self.output_names,
            "num_classes": self.num_classes,
            "class_names": self.class_names[:10] if len(self.class_names) > 10 else self.class_names
        }
        
    def get_statistics(self) -> Dict[str, Any]:
        """获取推理统计信息"""
        avg_time = (self.total_inference_time / self.inference_count 
                   if self.inference_count > 0 else 0)
        
        return {
            "inference_count": self.inference_count,
            "total_inference_time": self.total_inference_time,
            "average_inference_time": avg_time,
            "last_inference_time": self.last_inference_time,
            "throughput": 1.0 / avg_time if avg_time > 0 else 0,
            "fps": 1.0 / avg_time if avg_time > 0 else 0
        }
        
    def reset_statistics(self):
        """重置统计信息"""
        self.inference_count = 0
        self.total_inference_time = 0.0
        self.last_inference_time = 0.0
        self.logger.info("统计信息已重置")
        
    def _update_statistics(self, inference_time: float):
        """更新统计信息"""
        self.inference_count += 1
        self.total_inference_time += inference_time
        self.last_inference_time = inference_time
        
    def save_config(self, config_path: str):
        """保存模型配置"""
        import json
        
        config_data = {
            "model_path": self.model_path,
            "model_format": self.model_format,
            "model_type": self.model_type,
            "device": self.device,
            "batch_size": self.batch_size,
            "class_names": self.class_names,
            "preprocessing": self.preprocessing_config,
            "postprocessing": self.postprocessing_config,
            "config": self.config
        }
        
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
            self.logger.info(f"配置已保存到: {config_path}")
        except Exception as e:
            self.logger.error(f"保存配置失败: {e}")
            
    @classmethod
    def load_config(cls, config_path: str) -> Dict[str, Any]:
        """加载模型配置"""
        import json
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            return config_data
        except Exception as e:
            logging.error(f"加载配置失败: {e}")
            return {}
            
    def __str__(self) -> str:
        return f"{self.__class__.__name__}({self.model_name}, {self.model_format})"
        
    def __repr__(self) -> str:
        return self.__str__()
        
    def __enter__(self):
        """上下文管理器入口"""
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.unload()


class DummyModel(BaseModel):
    """
    虚拟模型实现，用于测试和演示
    """
    
    def __init__(self, model_path: str = "", config: Dict[str, Any] = None):
        super().__init__(model_path, config)
        self.model_name = "DummyModel"
        
    @property
    def supported_formats(self) -> List[str]:
        return [ModelFormat.ONNX, ModelFormat.PYTORCH]
        
    def load(self, model_path: str, config: Dict[str, Any] = None) -> bool:
        """加载虚拟模型"""
        self.model_path = model_path
        if config:
            self.config.update(config)
            
        # 模拟加载过程
        self.input_shape = (1, 3, 224, 224)
        self.output_shape = (1, 1000)
        self.input_names = ["input"]
        self.output_names = ["output"]
        
        self.is_loaded = True
        self.logger.info(f"虚拟模型加载成功: {model_path}")
        return True
        
    def inference(self, inputs: Union[np.ndarray, Dict[str, np.ndarray]]) -> np.ndarray:
        """执行虚拟推理"""
        if not self.is_loaded:
            raise RuntimeError("模型未加载")
            
        start_time = time.time()
        
        # 模拟推理过程
        time.sleep(0.001)  # 模拟1ms的推理时间
        
        # 生成虚拟结果
        if isinstance(inputs, np.ndarray):
            batch_size = inputs.shape[0]
            result = np.random.randn(batch_size, 1000).astype(np.float32)
        else:
            result = np.random.randn(1, 1000).astype(np.float32)
            
        # 更新统计信息
        inference_time = time.time() - start_time
        self._update_statistics(inference_time)
        
        return result