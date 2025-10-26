#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Modbus 通信辅助工具
提供Modbus TCP/RTU通信功能，用于与PLC和其他设备通信
"""

import logging
import time
import threading
from typing import Any, Dict, List, Optional, Union, Callable
from enum import Enum
import struct

try:
    from pymodbus.client.sync import ModbusTcpClient, ModbusSerialClient
    from pymodbus.constants import Endian
    from pymodbus.payload import BinaryPayloadDecoder, BinaryPayloadBuilder
    from pymodbus.exceptions import ModbusException, ConnectionException
    PYMODBUS_AVAILABLE = True
except ImportError:
    PYMODBUS_AVAILABLE = False
    ModbusTcpClient = None
    ModbusSerialClient = None


class ModbusDataType(Enum):
    """Modbus数据类型枚举"""
    BOOL = "bool"           # 布尔值 (1位)
    INT16 = "int16"         # 16位有符号整数
    UINT16 = "uint16"       # 16位无符号整数
    INT32 = "int32"         # 32位有符号整数
    UINT32 = "uint32"       # 32位无符号整数
    FLOAT32 = "float32"     # 32位浮点数
    STRING = "string"       # 字符串


class ModbusRegisterType(Enum):
    """Modbus寄存器类型枚举"""
    COIL = "coil"                           # 线圈 (01功能码)
    DISCRETE_INPUT = "discrete_input"       # 离散输入 (02功能码)
    HOLDING_REGISTER = "holding_register"   # 保持寄存器 (03功能码)
    INPUT_REGISTER = "input_register"       # 输入寄存器 (04功能码)


class ModbusHelper:
    """
    Modbus通信辅助类
    支持TCP和RTU通信方式，提供高级读写接口
    """
    
    def __init__(self, connection_type: str = "tcp", **kwargs):
        """
        初始化Modbus客户端
        
        Args:
            connection_type: 连接类型 ("tcp" 或 "rtu")
            **kwargs: 连接参数
        """
        if not PYMODBUS_AVAILABLE:
            raise ImportError("pymodbus库未安装，请运行: pip install pymodbus")
            
        self.connection_type = connection_type.lower()
        self.client = None
        self.is_connected = False
        
        # 连接参数
        self.connection_params = kwargs
        
        # 默认参数
        if self.connection_type == "tcp":
            self.host = kwargs.get("host", "127.0.0.1")
            self.port = kwargs.get("port", 502)
            self.timeout = kwargs.get("timeout", 3)
        elif self.connection_type == "rtu":
            self.port = kwargs.get("port", "/dev/ttyUSB0")
            self.baudrate = kwargs.get("baudrate", 9600)
            self.bytesize = kwargs.get("bytesize", 8)
            self.parity = kwargs.get("parity", "N")
            self.stopbits = kwargs.get("stopbits", 1)
            self.timeout = kwargs.get("timeout", 3)
        
        self.unit_id = kwargs.get("unit_id", 1)
        
        # 监控线程
        self.monitor_thread = None
        self.monitor_running = False
        self.monitor_callbacks: List[Callable] = []
        self.monitor_registers: List[Dict] = []
        
        # 日志
        self.logger = logging.getLogger(f"ModbusHelper.{id(self)}")
        
        # 创建客户端
        self._create_client()
        
    def _create_client(self):
        """创建Modbus客户端"""
        try:
            if self.connection_type == "tcp":
                self.client = ModbusTcpClient(
                    host=self.host,
                    port=self.port,
                    timeout=self.timeout
                )
            elif self.connection_type == "rtu":
                self.client = ModbusSerialClient(
                    method='rtu',
                    port=self.port,
                    baudrate=self.baudrate,
                    bytesize=self.bytesize,
                    parity=self.parity,
                    stopbits=self.stopbits,
                    timeout=self.timeout
                )
            else:
                raise ValueError(f"不支持的连接类型: {self.connection_type}")
                
            self.logger.info(f"创建Modbus客户端成功: {self.connection_type}")
            
        except Exception as e:
            self.logger.error(f"创建Modbus客户端失败: {e}")
            raise
            
    def connect(self) -> bool:
        """
        连接Modbus设备
        
        Returns:
            连接成功返回True
        """
        try:
            if self.client is None:
                self._create_client()
                
            result = self.client.connect()
            self.is_connected = result
            
            if result:
                self.logger.info(f"Modbus连接成功: {self.connection_type}")
            else:
                self.logger.error("Modbus连接失败")
                
            return result
            
        except Exception as e:
            self.logger.error(f"Modbus连接异常: {e}")
            self.is_connected = False
            return False
            
    def disconnect(self):
        """断开Modbus连接"""
        try:
            if self.client and self.is_connected:
                self.client.close()
                self.is_connected = False
                self.logger.info("Modbus连接已断开")
                
            # 停止监控
            self.stop_monitoring()
            
        except Exception as e:
            self.logger.error(f"断开Modbus连接异常: {e}")
            
    def read_coils(self, address: int, count: int = 1, unit_id: int = None) -> Optional[List[bool]]:
        """
        读取线圈状态
        
        Args:
            address: 起始地址
            count: 读取数量
            unit_id: 单元ID
            
        Returns:
            线圈状态列表
        """
        if not self.is_connected:
            self.logger.error("Modbus未连接")
            return None
            
        try:
            unit_id = unit_id or self.unit_id
            result = self.client.read_coils(address, count, unit=unit_id)
            
            if result.isError():
                self.logger.error(f"读取线圈失败: {result}")
                return None
                
            return result.bits[:count]
            
        except Exception as e:
            self.logger.error(f"读取线圈异常: {e}")
            return None
            
    def write_coil(self, address: int, value: bool, unit_id: int = None) -> bool:
        """
        写入单个线圈
        
        Args:
            address: 地址
            value: 值
            unit_id: 单元ID
            
        Returns:
            写入成功返回True
        """
        if not self.is_connected:
            self.logger.error("Modbus未连接")
            return False
            
        try:
            unit_id = unit_id or self.unit_id
            result = self.client.write_coil(address, value, unit=unit_id)
            
            if result.isError():
                self.logger.error(f"写入线圈失败: {result}")
                return False
                
            return True
            
        except Exception as e:
            self.logger.error(f"写入线圈异常: {e}")
            return False
            
    def write_coils(self, address: int, values: List[bool], unit_id: int = None) -> bool:
        """
        写入多个线圈
        
        Args:
            address: 起始地址
            values: 值列表
            unit_id: 单元ID
            
        Returns:
            写入成功返回True
        """
        if not self.is_connected:
            self.logger.error("Modbus未连接")
            return False
            
        try:
            unit_id = unit_id or self.unit_id
            result = self.client.write_coils(address, values, unit=unit_id)
            
            if result.isError():
                self.logger.error(f"写入多个线圈失败: {result}")
                return False
                
            return True
            
        except Exception as e:
            self.logger.error(f"写入多个线圈异常: {e}")
            return False
            
    def read_discrete_inputs(self, address: int, count: int = 1, unit_id: int = None) -> Optional[List[bool]]:
        """读取离散输入"""
        if not self.is_connected:
            self.logger.error("Modbus未连接")
            return None
            
        try:
            unit_id = unit_id or self.unit_id
            result = self.client.read_discrete_inputs(address, count, unit=unit_id)
            
            if result.isError():
                self.logger.error(f"读取离散输入失败: {result}")
                return None
                
            return result.bits[:count]
            
        except Exception as e:
            self.logger.error(f"读取离散输入异常: {e}")
            return None
            
    def read_holding_registers(self, address: int, count: int = 1, unit_id: int = None) -> Optional[List[int]]:
        """读取保持寄存器"""
        if not self.is_connected:
            self.logger.error("Modbus未连接")
            return None
            
        try:
            unit_id = unit_id or self.unit_id
            result = self.client.read_holding_registers(address, count, unit=unit_id)
            
            if result.isError():
                self.logger.error(f"读取保持寄存器失败: {result}")
                return None
                
            return result.registers
            
        except Exception as e:
            self.logger.error(f"读取保持寄存器异常: {e}")
            return None
            
    def write_register(self, address: int, value: int, unit_id: int = None) -> bool:
        """写入单个保持寄存器"""
        if not self.is_connected:
            self.logger.error("Modbus未连接")
            return False
            
        try:
            unit_id = unit_id or self.unit_id
            result = self.client.write_register(address, value, unit=unit_id)
            
            if result.isError():
                self.logger.error(f"写入寄存器失败: {result}")
                return False
                
            return True
            
        except Exception as e:
            self.logger.error(f"写入寄存器异常: {e}")
            return False
            
    def write_registers(self, address: int, values: List[int], unit_id: int = None) -> bool:
        """写入多个保持寄存器"""
        if not self.is_connected:
            self.logger.error("Modbus未连接")
            return False
            
        try:
            unit_id = unit_id or self.unit_id
            result = self.client.write_registers(address, values, unit=unit_id)
            
            if result.isError():
                self.logger.error(f"写入多个寄存器失败: {result}")
                return False
                
            return True
            
        except Exception as e:
            self.logger.error(f"写入多个寄存器异常: {e}")
            return False
            
    def read_input_registers(self, address: int, count: int = 1, unit_id: int = None) -> Optional[List[int]]:
        """读取输入寄存器"""
        if not self.is_connected:
            self.logger.error("Modbus未连接")
            return None
            
        try:
            unit_id = unit_id or self.unit_id
            result = self.client.read_input_registers(address, count, unit=unit_id)
            
            if result.isError():
                self.logger.error(f"读取输入寄存器失败: {result}")
                return None
                
            return result.registers
            
        except Exception as e:
            self.logger.error(f"读取输入寄存器异常: {e}")
            return None
            
    def read_data(self, address: int, data_type: ModbusDataType, 
                  register_type: ModbusRegisterType = ModbusRegisterType.HOLDING_REGISTER,
                  unit_id: int = None) -> Optional[Any]:
        """
        读取指定数据类型的数据
        
        Args:
            address: 地址
            data_type: 数据类型
            register_type: 寄存器类型
            unit_id: 单元ID
            
        Returns:
            解析后的数据
        """
        try:
            if data_type == ModbusDataType.BOOL:
                if register_type == ModbusRegisterType.COIL:
                    result = self.read_coils(address, 1, unit_id)
                else:
                    result = self.read_discrete_inputs(address, 1, unit_id)
                return result[0] if result else None
                
            # 计算需要读取的寄存器数量
            if data_type in [ModbusDataType.INT16, ModbusDataType.UINT16]:
                count = 1
            elif data_type in [ModbusDataType.INT32, ModbusDataType.UINT32, ModbusDataType.FLOAT32]:
                count = 2
            else:
                count = 1
                
            # 读取寄存器
            if register_type == ModbusRegisterType.HOLDING_REGISTER:
                registers = self.read_holding_registers(address, count, unit_id)
            else:
                registers = self.read_input_registers(address, count, unit_id)
                
            if not registers:
                return None
                
            # 解析数据
            return self._decode_registers(registers, data_type)
            
        except Exception as e:
            self.logger.error(f"读取数据异常: {e}")
            return None
            
    def write_data(self, address: int, value: Any, data_type: ModbusDataType,
                   unit_id: int = None) -> bool:
        """
        写入指定数据类型的数据
        
        Args:
            address: 地址
            value: 值
            data_type: 数据类型
            unit_id: 单元ID
            
        Returns:
            写入成功返回True
        """
        try:
            if data_type == ModbusDataType.BOOL:
                return self.write_coil(address, bool(value), unit_id)
                
            # 编码数据
            registers = self._encode_data(value, data_type)
            if not registers:
                return False
                
            # 写入寄存器
            if len(registers) == 1:
                return self.write_register(address, registers[0], unit_id)
            else:
                return self.write_registers(address, registers, unit_id)
                
        except Exception as e:
            self.logger.error(f"写入数据异常: {e}")
            return False
            
    def _decode_registers(self, registers: List[int], data_type: ModbusDataType) -> Any:
        """解码寄存器数据"""
        try:
            decoder = BinaryPayloadDecoder.fromRegisters(registers, byteorder=Endian.Big)
            
            if data_type == ModbusDataType.INT16:
                return decoder.decode_16bit_int()
            elif data_type == ModbusDataType.UINT16:
                return decoder.decode_16bit_uint()
            elif data_type == ModbusDataType.INT32:
                return decoder.decode_32bit_int()
            elif data_type == ModbusDataType.UINT32:
                return decoder.decode_32bit_uint()
            elif data_type == ModbusDataType.FLOAT32:
                return decoder.decode_32bit_float()
            elif data_type == ModbusDataType.STRING:
                return decoder.decode_string(len(registers) * 2).decode('ascii').rstrip('\x00')
            else:
                return registers[0]
                
        except Exception as e:
            self.logger.error(f"解码寄存器数据失败: {e}")
            return None
            
    def _encode_data(self, value: Any, data_type: ModbusDataType) -> Optional[List[int]]:
        """编码数据为寄存器格式"""
        try:
            builder = BinaryPayloadBuilder(byteorder=Endian.Big)
            
            if data_type == ModbusDataType.INT16:
                builder.add_16bit_int(int(value))
            elif data_type == ModbusDataType.UINT16:
                builder.add_16bit_uint(int(value))
            elif data_type == ModbusDataType.INT32:
                builder.add_32bit_int(int(value))
            elif data_type == ModbusDataType.UINT32:
                builder.add_32bit_uint(int(value))
            elif data_type == ModbusDataType.FLOAT32:
                builder.add_32bit_float(float(value))
            elif data_type == ModbusDataType.STRING:
                builder.add_string(str(value))
            else:
                return [int(value)]
                
            return builder.to_registers()
            
        except Exception as e:
            self.logger.error(f"编码数据失败: {e}")
            return None
            
    def start_monitoring(self, registers: List[Dict], callback: Callable, interval: float = 1.0):
        """
        开始寄存器监控
        
        Args:
            registers: 要监控的寄存器列表
            callback: 回调函数
            interval: 监控间隔（秒）
        """
        self.monitor_registers = registers
        self.monitor_callbacks.append(callback)
        
        if not self.monitor_running:
            self.monitor_running = True
            self.monitor_thread = threading.Thread(
                target=self._monitoring_loop, 
                args=(interval,)
            )
            self.monitor_thread.daemon = True
            self.monitor_thread.start()
            
            self.logger.info(f"开始Modbus监控，间隔: {interval}秒")
            
    def stop_monitoring(self):
        """停止寄存器监控"""
        self.monitor_running = False
        
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=2)
            
        self.monitor_callbacks.clear()
        self.monitor_registers.clear()
        self.logger.info("Modbus监控已停止")
        
    def _monitoring_loop(self, interval: float):
        """监控循环"""
        last_values = {}
        
        while self.monitor_running and self.is_connected:
            try:
                for register_info in self.monitor_registers:
                    address = register_info["address"]
                    data_type = ModbusDataType(register_info.get("data_type", "uint16"))
                    register_type = ModbusRegisterType(register_info.get("register_type", "holding_register"))
                    name = register_info.get("name", f"reg_{address}")
                    
                    # 读取当前值
                    current_value = self.read_data(address, data_type, register_type)
                    
                    # 检查值是否变化
                    if name not in last_values or last_values[name] != current_value:
                        last_values[name] = current_value
                        
                        # 通知回调函数
                        for callback in self.monitor_callbacks:
                            try:
                                callback(name, current_value, register_info)
                            except Exception as e:
                                self.logger.error(f"监控回调异常: {e}")
                                
                time.sleep(interval)
                
            except Exception as e:
                self.logger.error(f"监控循环异常: {e}")
                time.sleep(interval)
                
    def test_connection(self) -> bool:
        """测试连接"""
        if not self.is_connected:
            return False
            
        try:
            # 尝试读取一个寄存器来测试连接
            result = self.read_holding_registers(0, 1)
            return result is not None
        except:
            return False
            
    def get_connection_info(self) -> Dict[str, Any]:
        """获取连接信息"""
        info = {
            "connection_type": self.connection_type,
            "is_connected": self.is_connected,
            "unit_id": self.unit_id,
            "monitor_running": self.monitor_running,
            "monitor_register_count": len(self.monitor_registers)
        }
        
        if self.connection_type == "tcp":
            info.update({
                "host": self.host,
                "port": self.port,
                "timeout": self.timeout
            })
        else:
            info.update({
                "port": self.port,
                "baudrate": self.baudrate,
                "timeout": self.timeout
            })
            
        return info
        
    def __enter__(self):
        """上下文管理器入口"""
        self.connect()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.disconnect()


# 便捷函数
def create_tcp_client(host: str = "127.0.0.1", port: int = 502, unit_id: int = 1, **kwargs) -> ModbusHelper:
    """创建TCP客户端"""
    return ModbusHelper("tcp", host=host, port=port, unit_id=unit_id, **kwargs)


def create_rtu_client(port: str = "/dev/ttyUSB0", baudrate: int = 9600, unit_id: int = 1, **kwargs) -> ModbusHelper:
    """创建RTU客户端"""
    return ModbusHelper("rtu", port=port, baudrate=baudrate, unit_id=unit_id, **kwargs)


# 示例用法
if __name__ == "__main__":
    # TCP连接示例
    try:
        with create_tcp_client("192.168.1.100", 502) as client:
            # 读取保持寄存器
            registers = client.read_holding_registers(0, 10)
            print(f"寄存器值: {registers}")
            
            # 读取浮点数
            float_value = client.read_data(0, ModbusDataType.FLOAT32)
            print(f"浮点数值: {float_value}")
            
            # 写入数据
            success = client.write_data(0, 123.45, ModbusDataType.FLOAT32)
            print(f"写入结果: {success}")
            
    except Exception as e:
        print(f"Modbus操作失败: {e}")