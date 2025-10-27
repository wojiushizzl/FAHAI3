#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模块注册表
提供模块类的集中注册与查找，支持GUI动态端口反射。
"""
from typing import Dict, Type, Optional, List
from .base_module import BaseModule
import logging
try:
    from importlib.metadata import entry_points
except ImportError:  # Python <3.8 回退（此环境为3.10通常不会触发）
    entry_points = None  # type: ignore

# 内部注册映射: display_name -> class
_module_registry: Dict[str, Type[BaseModule]] = {}
_logger = logging.getLogger("module_registry")

def register_module(display_name: str, cls: Type[BaseModule]):
    """注册模块类
    Args:
        display_name: 在GUI中显示的名称（可为中文）
        cls: 模块类，继承自 BaseModule
    """
    if not issubclass(cls, BaseModule):
        raise TypeError("模块类必须继承 BaseModule")
    _module_registry[display_name] = cls

def get_module_class(display_name: str) -> Optional[Type[BaseModule]]:
    return _module_registry.get(display_name)

def list_registered_modules() -> List[str]:
    return list(_module_registry.keys())

def load_plugin_modules(group: str = "fahai.modules") -> List[str]:
    """通过 entry points 加载外部插件模块。
    约定：每个 entry point 的对象是一个 BaseModule 子类；名称使用 entry point 的 name。
    Returns: 成功注册的显示名列表。
    """
    loaded: List[str] = []
    if not entry_points:
        return loaded
    try:
        eps = entry_points()
        # 兼容不同 Python 版本: 3.10 返回 dict-like, 新版本返回 Selection
        candidates = []
        if isinstance(eps, dict):  # old style
            candidates = eps.get(group, [])
        else:
            for ep in eps:
                if ep.group == group:
                    candidates.append(ep)
        for ep in candidates:
            try:
                obj = ep.load()
                if isinstance(obj, type) and issubclass(obj, BaseModule):
                    display_name = ep.name
                    if display_name in _module_registry:
                        _logger.warning(f"插件名称已存在，跳过: {display_name}")
                        continue
                    register_module(display_name, obj)
                    loaded.append(display_name)
                else:
                    _logger.error(f"Entry point {ep.name} 不是有效的 BaseModule 子类")
            except Exception as e:
                _logger.error(f"加载插件 {ep.name} 失败: {e}")
    except Exception as e:
        _logger.error(f"枚举插件失败: {e}")
    return loaded

# 可选：预先导入常用模块进行注册（也可以在各模块文件中自注册）
try:
    from .camera.camera_module import CameraModule
    register_module("相机", CameraModule)
except Exception as e:
    pass

try:
    from .camera.image_import_module import ImageImportModule
    register_module("图片导入", ImageImportModule)
except Exception as e:
    pass

try:
    from .model.model_module import ModelModule
    register_module("模型", ModelModule)
except Exception as e:
    pass

try:
    from .trigger.trigger_module import TriggerModule
    register_module("触发", TriggerModule)
except Exception as e:
    pass

try:
    from .postprocess.postprocess_module import PostprocessModule
    register_module("后处理", PostprocessModule)
except Exception as e:
    pass
try:
    from .postprocess.yolo_result_bool_module import YoloResultBoolModule
    register_module("检测结果布尔判断", YoloResultBoolModule)
except Exception:
    pass

# 新增: 文本输入与打印模块
############################################################
# 新的分类结构: input / display / storage / script / utility
# 旧 custom 模块仍保留以兼容外部直接导入路径；这里统一从新路径注册。
############################################################
try:
    from .utility.text_input_module import TextInputModule
    register_module("文本输入", TextInputModule)
except Exception:
    pass
try:
    from .utility.print_module import PrintModule
    register_module("打印", PrintModule)
except Exception:
    pass
try:
    from .utility.delay_module import DelayModule
    register_module("延时", DelayModule)
except Exception:
    pass
try:
    from .utility.logic_module import LogicModule
    register_module("逻辑", LogicModule)
except Exception:
    pass
try:
    from .utility.bool_gate_module import BoolGateModule
    register_module("布尔闸门", BoolGateModule)
except Exception:
    pass
try:
    from .utility.path_selector_module import PathSelectorModule
    register_module("路径选择器", PathSelectorModule)
except Exception:
    pass
try:
    from .utility.sample_dev_module import SampleDevModule
    register_module("示例模块", SampleDevModule)
except Exception:
    pass
try:
    from .display.image_display_module import ImageDisplayModule
    register_module("图片展示", ImageDisplayModule)
except Exception:
    pass
try:
    from .display.print_display_module import PrintDisplayModule
    register_module("打印显示", PrintDisplayModule)
except Exception:
    pass
try:
    from .display.text_display_module import TextDisplayModule
    register_module("文本展示", TextDisplayModule)
except Exception:
    pass
try:
    from .display.ok_nok_display_module import OkNokDisplayModule
    register_module("OK/NOK展示", OkNokDisplayModule)
except Exception:
    pass
try:
    from .storage.save_image_module import SaveImageModule
    register_module("保存图片", SaveImageModule)
except Exception:
    pass
try:
    from .storage.save_text_module import SaveTextModule
    register_module("保存文本", SaveTextModule)
except Exception:
    pass
try:
    from .script.script_module import ScriptModule
    register_module("脚本模块", ScriptModule)
except Exception:
    pass

# YOLOv8 模型系列模块 (检测/分类/分割)
try:
    from .model.yolov8_detect_module import YoloV8DetectModule
    register_module("yolov8检测", YoloV8DetectModule)
except Exception as e:
    pass
try:
    from .model.yolov8_classify_module import YoloV8ClassifyModule
    register_module("yolov8分类", YoloV8ClassifyModule)
except Exception as e:
    pass
try:
    from .model.yolov8_segment_module import YoloV8SegmentModule
    register_module("yolov8分割", YoloV8SegmentModule)
except Exception as e:
    pass

# Modbus 系列模块
try:
    from .modbus.modbus_connect_module import ModbusConnectModule
    register_module("modbus连接", ModbusConnectModule)
except Exception:
    pass
try:
    from .modbus.modbus_server_module import ModbusServerModule
    register_module("modbus模拟服务器", ModbusServerModule)
except Exception:
    pass
try:
    from .modbus.modbus_listener_module import ModbusListenerModule
    register_module("modbus监听", ModbusListenerModule)
except Exception:
    pass
try:
    from .modbus.modbus_write_module import ModbusWriteModule
    register_module("modbus输出", ModbusWriteModule)
except Exception:
    pass

# 自动加载外部插件
_loaded_plugins = load_plugin_modules()
if _loaded_plugins:
    _logger.info(f"已加载插件模块: {_loaded_plugins}")
