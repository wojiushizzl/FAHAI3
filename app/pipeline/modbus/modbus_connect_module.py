#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Modbus 连接模块
支持:
1. TCP 单主机 (host/port)
2. TCP 多主机 (hosts 列表) -> 输出 connections 列表
3. RTU 串口 (protocol=rtu, port/baudrate/parity/stopbits/bytesize)
增强: 错误计数与熔断 (fuse) 避免频繁重连刷日志。
输出:
    connect: 单客户端或第一个客户端 (兼容现有模块)
    connections: 多客户端列表 (multi host 时)
    status: 是否全部连接成功
    fused: 是否处于熔断冷却期
"""
from typing import Any, Dict, List
import time
from app.pipeline.base_module import BaseModule, ModuleType, ModuleCapabilities

try:
    from pydantic import BaseModel, validator
except ImportError:
    BaseModel = object  # type: ignore

# pymodbus 2.x / 3.x 结构兼容处理
_TcpClient = None
try:  # pymodbus >=3.0
    from pymodbus.client import ModbusTcpClient as _TcpClient  # type: ignore
except Exception:
    try:  # pymodbus 2.x fallback
        from pymodbus.client.sync import ModbusTcpClient as _TcpClient  # type: ignore
    except Exception:
        _TcpClient = None  # noqa: F401

class ModbusConnectModule(BaseModule):
    CAPABILITIES = ModuleCapabilities(may_block=True, resource_tags=["modbus"], throughput_hint=5.0)

    class ConfigModel(BaseModel):  # type: ignore
        protocol: str = "tcp"            # tcp | rtu
        host: str = "127.0.0.1"           # 单主机
        hosts: List[str] = []             # 多主机列表（优先于 host）
        port: int = 502                   # TCP 端口
        timeout: float = 3.0
        unit_id: int = 1
        auto_reconnect: bool = True
        fuse_fail_count: int = 5          # 超过该连续失败次数触发熔断
        fuse_cooldown_s: float = 10.0     # 熔断持续时间
        reconnect_backoff_s: float = 0.0  # 重连前等待时间
        # RTU 参数
        serial_port: str = "COM3"
        baudrate: int = 9600
        parity: str = "N"                 # N/E/O
        stopbits: int = 1
        bytesize: int = 8

        @validator("protocol")
        def _proto_ok(cls, v):
            if v not in {"tcp", "rtu"}:
                raise ValueError("protocol 必须是 tcp 或 rtu")
            return v

        @validator("port")
        def _port_ok(cls, v):
            if not (0 < v < 65536):
                raise ValueError("端口必须在 1-65535")
            return v

        @validator("timeout", "fuse_cooldown_s", "reconnect_backoff_s")
        def _positive(cls, v):
            if v < 0:
                raise ValueError("时间参数需 >= 0")
            return v

    def __init__(self, name: str = "modbus连接"):
        super().__init__(name)
        self._client = None          # 单连接（兼容）
        self._clients: List[Any] = []  # 多连接
        self._fail_count = 0
        self._fuse_until = 0.0
        self._last_attempt_ts = 0.0

    @property
    def module_type(self) -> ModuleType:
        return ModuleType.CUSTOM

    def _define_ports(self):
        self.register_output_port("connect", port_type="modbus", desc="单连接或第一个连接")
        self.register_output_port("connections", port_type="list", desc="多连接列表")
        self.register_output_port("status", port_type="bool", desc="总体连接状态")
        self.register_output_port("fused", port_type="bool", desc="熔断状态")

    def _on_start(self):
        self._clients.clear()
        self._client = None
        if self._is_fused():
            return
        protocol = self.config.get("protocol", "tcp")
        timeout = self.config.get("timeout", 3.0)
        if protocol == "tcp":
            if _TcpClient is None:
                self.logger.error("未找到 pymodbus TCP 客户端类")
                return
            hosts: List[str] = self.config.get("hosts", []) or []
            host_single = self.config.get("host", "127.0.0.1")
            targets = hosts if hosts else [host_single]
            for h in targets:
                try:
                    cli = _TcpClient(host=h, port=self.config.get("port", 502), timeout=timeout)
                    if cli.connect():  # type: ignore
                        self._clients.append(cli)
                    else:
                        self.logger.error(f"TCP 连接失败: {h}")
                        cli.close()
                except Exception as e:
                    self.logger.error(f"TCP 创建异常 {h}: {e}")
            if self._clients:
                self._client = self._clients[0]
        else:  # RTU
            # 导入串口客户端
            SerialClient = None
            try:
                from pymodbus.client import ModbusSerialClient as SerialClient  # type: ignore
            except Exception:
                try:
                    from pymodbus.client.sync import ModbusSerialClient as SerialClient  # type: ignore
                except Exception:
                    SerialClient = None
            if SerialClient is None:
                self.logger.error("未找到 pymodbus 串口客户端类")
                return
            try:
                cli = SerialClient(method="rtu",
                                   port=self.config.get("serial_port", "COM3"),
                                   baudrate=self.config.get("baudrate", 9600),
                                   parity=self.config.get("parity", "N"),
                                   stopbits=self.config.get("stopbits", 1),
                                   bytesize=self.config.get("bytesize", 8),
                                   timeout=timeout)
                if cli.connect():  # type: ignore
                    self._client = cli
                    self._clients = [cli]
                else:
                    self.logger.error("RTU 连接失败")
                    cli.close()
            except Exception as e:
                self.logger.error(f"RTU 创建异常: {e}")

        # 成功则重置失败计数
        if self._clients:
            self._fail_count = 0
        else:
            self._fail_count += 1
            self._check_fuse()

    def _on_stop(self):
        for c in self._clients:
            try:
                c.close()
            except Exception:
                pass
        self._clients.clear()
        self._client = None

    def _is_fused(self) -> bool:
        return time.time() < self._fuse_until

    def _check_fuse(self):
        fuse_fail_count = int(self.config.get("fuse_fail_count", 5))
        if self._fail_count >= fuse_fail_count and not self._is_fused():
            cooldown = float(self.config.get("fuse_cooldown_s", 10.0))
            self._fuse_until = time.time() + cooldown
            self.logger.error(f"触发熔断: 连续失败 {self._fail_count} 次, 冷却 {cooldown}s")

    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        fused = self._is_fused()
        all_ok = bool(self._clients) and all(bool(c) for c in self._clients)
        if (not all_ok) and self.config.get("auto_reconnect", True) and (not fused):
            backoff = float(self.config.get("reconnect_backoff_s", 0.0))
            now = time.time()
            if backoff > 0 and (now - self._last_attempt_ts) < backoff:
                # 等待下一个周期
                pass
            else:
                self._last_attempt_ts = now
                self._on_start()
                all_ok = bool(self._clients)
        return {
            "connect": self._client,
            "connections": self._clients,
            "status": all_ok,
            "fused": fused
        }
