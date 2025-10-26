#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模块基类
定义所有处理模块的基础接口和通用功能
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Callable, Type
from enum import Enum
import uuid
import logging
try:
    from pydantic import BaseModel, ValidationError
except ImportError:  # 运行环境未安装时保持兼容（配置校验会跳过）
    BaseModel = object  # type: ignore
    ValidationError = Exception  # type: ignore


class ModuleCapabilities:
    """模块能力描述 (轻量结构，避免额外依赖)
    可由子类覆盖 CAPABILITIES 属性来自定义。

    Attributes:
        supports_async: 是否支持异步执行（内部线程或协程）。
        supports_batch: 是否支持批量输入处理。
        may_block: 是否可能进行阻塞操作（IO/CPU密集）。
        resource_tags: 资源标签 (例如: ['camera','gpu']).
        throughput_hint: 吞吐提示（预估每秒处理次数 / 帧数）。
    """
    def __init__(self,
                 supports_async: bool = False,
                 supports_batch: bool = False,
                 may_block: bool = False,
                 resource_tags: Optional[List[str]] = None,
                 throughput_hint: Optional[float] = None):
        self.supports_async = supports_async
        self.supports_batch = supports_batch
        self.may_block = may_block
        self.resource_tags = resource_tags or []
        self.throughput_hint = throughput_hint if throughput_hint is not None else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "supports_async": self.supports_async,
            "supports_batch": self.supports_batch,
            "may_block": self.may_block,
            "resource_tags": list(self.resource_tags),
            "throughput_hint": self.throughput_hint,
        }


class ModuleStatus(Enum):
    """模块状态枚举"""
    IDLE = "idle"           # 空闲状态
    RUNNING = "running"     # 运行状态
    PAUSED = "paused"       # 暂停状态
    ERROR = "error"         # 错误状态
    STOPPED = "stopped"     # 停止状态


class ModuleType(Enum):
    """模块类型枚举"""
    CAMERA = "camera"               # 相机模块
    TRIGGER = "trigger"             # 触发模块
    MODEL = "model"                 # 模型推理模块
    POSTPROCESS = "postprocess"     # 后处理模块
    CUSTOM = "custom"               # 自定义模块


class BaseModule(ABC):
    """
    模块基类，所有处理模块都应该继承此类
    提供通用的模块管理功能和接口定义
    """
    
    def __init__(self, name: str = None, module_id: str = None):
        """
        初始化模块
        
        Args:
            name: 模块名称
            module_id: 模块ID，如果不指定则自动生成
        """
        self.name = name or self.__class__.__name__
        self.module_id = module_id or str(uuid.uuid4())
        self.status = ModuleStatus.IDLE
        self.config = {}
        self._config_model = None  # pydantic 模型实例（若存在）
        # 运行期缓存（可选使用）
        self.inputs = {}
        self.outputs = {}
        self.errors = []
        
        # 设置日志
        self.logger = logging.getLogger(f"{self.__class__.__name__}.{self.module_id}")
        
        # 输入输出端口定义（标准化）: {port_name: {"type": str, "desc": str, "required": bool}}
        self.input_ports = {}
        self.output_ports = {}

        # 注册标准端口（子类可覆盖 _define_ports）
        self._define_ports()
        
        # 模块属性
        self.properties = {}
        
        # 初始化模块
        self._initialize()
        
    def _initialize(self):
        """模块初始化，子类可以重写此方法"""
        pass

    # -------- 能力与配置模型 --------
    # 子类可覆盖： CAPABILITIES = ModuleCapabilities(...)
    CAPABILITIES = ModuleCapabilities()
    # 子类可定义： class ConfigModel(BaseModel): ...

    @property
    def capabilities(self) -> ModuleCapabilities:
        """返回模块能力描述"""
        caps = getattr(self.__class__, 'CAPABILITIES', None)
        if isinstance(caps, ModuleCapabilities):
            return caps
        return self.CAPABILITIES

    def _define_ports(self):
        """定义模块的输入输出端口，子类可重写添加端口。
        默认实现：如果未重写则添加一个通用输入与输出。
        """
        if not self.input_ports and not self.output_ports:
            self.register_input_port("in", port_type="generic", desc="通用输入")
            self.register_output_port("out", port_type="generic", desc="通用输出")

    # ------------------- 端口注册与访问 -------------------
    def register_input_port(self, name: str, port_type: str = "generic", desc: str = "", required: bool = False):
        if name in self.input_ports:
            raise ValueError(f"输入端口已存在: {name}")
        self.input_ports[name] = {"type": port_type, "desc": desc, "required": required}

    def register_output_port(self, name: str, port_type: str = "generic", desc: str = ""):
        if name in self.output_ports:
            raise ValueError(f"输出端口已存在: {name}")
        self.output_ports[name] = {"type": port_type, "desc": desc}

    def receive_inputs(self, data: Dict[str, Any]):
        """接收上一模块输出的数据并缓存在 inputs"""
        for k, v in data.items():
            if k in self.input_ports:  # 只存已定义的端口
                self.inputs[k] = v

    def produce_outputs(self, data: Dict[str, Any]):
        """将本模块处理结果写入 outputs (仅写已定义端口)"""
        for k, v in data.items():
            if k in self.output_ports:
                self.outputs[k] = v

    def clear_io(self):
        self.inputs.clear()
        self.outputs.clear()
        
    @property
    @abstractmethod
    def module_type(self) -> ModuleType:
        """返回模块类型"""
        pass
        
    @abstractmethod
    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理输入数据并返回输出结果
        
        Args:
            inputs: 输入数据字典
            
        Returns:
            输出结果字典
        """
        pass

    def run_cycle(self) -> Dict[str, Any]:
        """执行一次处理循环：使用 self.inputs 作为输入，调用 process，写入 outputs 并返回结果。"""
        result = self.process(self.inputs.copy())
        if not isinstance(result, dict):
            result = {"out": result}
        self.produce_outputs(result)
        return result
        
    def start(self) -> bool:
        """
        启动模块
        
        Returns:
            启动成功返回True，否则返回False
        """
        try:
            if self.status in [ModuleStatus.IDLE, ModuleStatus.STOPPED]:
                self._on_start()
                self.status = ModuleStatus.RUNNING
                self.logger.info(f"模块 {self.name} 启动成功")
                return True
            else:
                self.logger.warning(f"模块 {self.name} 已经在运行中")
                return False
        except Exception as e:
            self.status = ModuleStatus.ERROR
            self.errors.append(str(e))
            self.logger.error(f"模块 {self.name} 启动失败: {e}")
            return False
            
    def stop(self) -> bool:
        """
        停止模块
        
        Returns:
            停止成功返回True，否则返回False
        """
        try:
            if self.status in [ModuleStatus.RUNNING, ModuleStatus.PAUSED]:
                self._on_stop()
                self.status = ModuleStatus.STOPPED
                self.logger.info(f"模块 {self.name} 停止成功")
                return True
            else:
                self.logger.warning(f"模块 {self.name} 未在运行中")
                return False
        except Exception as e:
            self.status = ModuleStatus.ERROR
            self.errors.append(str(e))
            self.logger.error(f"模块 {self.name} 停止失败: {e}")
            return False
            
    def pause(self) -> bool:
        """
        暂停模块
        
        Returns:
            暂停成功返回True，否则返回False
        """
        try:
            if self.status == ModuleStatus.RUNNING:
                self._on_pause()
                self.status = ModuleStatus.PAUSED
                self.logger.info(f"模块 {self.name} 暂停成功")
                return True
            else:
                self.logger.warning(f"模块 {self.name} 未在运行中")
                return False
        except Exception as e:
            self.status = ModuleStatus.ERROR
            self.errors.append(str(e))
            self.logger.error(f"模块 {self.name} 暂停失败: {e}")
            return False
            
    def resume(self) -> bool:
        """
        恢复模块
        
        Returns:
            恢复成功返回True，否则返回False
        """
        try:
            if self.status == ModuleStatus.PAUSED:
                self._on_resume()
                self.status = ModuleStatus.RUNNING
                self.logger.info(f"模块 {self.name} 恢复成功")
                return True
            else:
                self.logger.warning(f"模块 {self.name} 未处于暂停状态")
                return False
        except Exception as e:
            self.status = ModuleStatus.ERROR
            self.errors.append(str(e))
            self.logger.error(f"模块 {self.name} 恢复失败: {e}")
            return False
            
    def reset(self) -> bool:
        """
        重置模块
        
        Returns:
            重置成功返回True，否则返回False
        """
        try:
            self.stop()
            self._on_reset()
            self.status = ModuleStatus.IDLE
            self.errors.clear()
            self.logger.info(f"模块 {self.name} 重置成功")
            return True
        except Exception as e:
            self.status = ModuleStatus.ERROR
            self.errors.append(str(e))
            self.logger.error(f"模块 {self.name} 重置失败: {e}")
            return False
            
    def configure(self, config: Dict[str, Any]) -> bool:
        """
        配置模块参数
        
        Args:
            config: 配置参数字典
            
        Returns:
            配置成功返回True，否则返回False
        """
        try:
            parsed_config = config
            # 若子类定义了 pydantic ConfigModel 则使用严格验证
            ConfigModel = getattr(self.__class__, 'ConfigModel', None)
            if ConfigModel and issubclass(ConfigModel, BaseModel):
                try:
                    self._config_model = ConfigModel(**config)  # type: ignore
                    parsed_config = self._config_model.dict()
                except ValidationError as ve:  # type: ignore
                    self.errors.append(str(ve))
                    self.logger.error(f"模块 {self.name} 配置验证失败: {ve}")
                    return False
                except Exception as e:
                    self.errors.append(str(e))
                    self.logger.error(f"模块 {self.name} 配置模型错误: {e}")
                    return False
            # 额外的自定义验证
            if self._validate_config(parsed_config):
                self.config.update(parsed_config)
                self._on_configure(parsed_config)
                self.logger.info(f"模块 {self.name} 配置成功")
                return True
            else:
                self.logger.error(f"模块 {self.name} 自定义验证失败")
                return False
        except Exception as e:
            self.errors.append(str(e))
            self.logger.error(f"模块 {self.name} 配置失败: {e}")
            return False
            
    def get_status(self) -> Dict[str, Any]:
        """
        获取模块状态信息
        
        Returns:
            状态信息字典
        """
        return {
            "module_id": self.module_id,
            "name": self.name,
            "type": self.module_type.value,
            "status": self.status.value,
            "config": self.config.copy(),
            "errors": self.errors.copy(),
            "input_ports": self.input_ports.copy(),
            "output_ports": self.output_ports.copy(),
            "current_inputs": list(self.inputs.keys()),
            "current_outputs": list(self.outputs.keys()),
            "capabilities": self.capabilities.to_dict(),
        }
        
    def set_property(self, key: str, value: Any):
        """设置模块属性"""
        self.properties[key] = value
        
    def get_property(self, key: str, default: Any = None) -> Any:
        """获取模块属性"""
        return self.properties.get(key, default)
        
    # 生命周期回调方法，子类可以重写
    def _on_start(self):
        """启动时的回调"""
        pass
        
    def _on_stop(self):
        """停止时的回调"""
        pass
        
    def _on_pause(self):
        """暂停时的回调"""
        pass
        
    def _on_resume(self):
        """恢复时的回调"""
        pass
        
    def _on_reset(self):
        """重置时的回调"""
        pass
        
    def _on_configure(self, config: Dict[str, Any]):
        """配置时的回调"""
        pass
        
    def _validate_config(self, config: Dict[str, Any]) -> bool:
        """
        验证配置参数
        
        Args:
            config: 配置参数字典
            
        Returns:
            验证通过返回True，否则返回False
        """
        # 默认实现，子类可以重写
        return True
        
    def __str__(self) -> str:
        return f"{self.__class__.__name__}({self.name}, {self.module_id})"
        
    def __repr__(self) -> str:
        return self.__str__()