#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地 Modbus 模拟服务器模块
在 127.0.0.1 上启动一个可调寄存器的 Modbus TCP 服务器，供连接/监听模块调试。
可配置端口与初始寄存器数量；支持在流程中通过输入端口动态写入线圈与保持寄存器值。
输出:
  host: 服务器主机 (始终 127.0.0.1)
  port: 端口
  context: pymodbus 的服务器上下文 (可被其他模块直接访问)
  status: 是否运行
  coils: 当前线圈列表快照
  holdings: 当前保持寄存器列表快照
"""
from typing import Any, Dict, List
import threading, time
from .modbus_connect_module import ModuleCapabilities  # reuse capability class
from ..base_module import BaseModule, ModuleType
import logging

try:
    from pydantic import BaseModel, validator
except Exception:
    BaseModel = object  # type: ignore
    validator = lambda *a, **kw: (lambda f: f)  # type: ignore

# 尝试导入服务器相关组件 (兼容不同版本 pymodbus)
TcpServerClass = None
ServerContextClass = None
SlaveContextClass = None
SeqDataBlockClass = None
try:
    from pymodbus.server import ModbusTcpServer as TcpServerClass  # type: ignore
    from pymodbus.datastore import ModbusServerContext as ServerContextClass  # type: ignore
    from pymodbus.datastore import ModbusSlaveContext as SlaveContextClass  # type: ignore
    from pymodbus.datastore import ModbusSequentialDataBlock as SeqDataBlockClass  # type: ignore
except Exception:
    # 旧版本 fallback
    try:
        from pymodbus.server.sync import ModbusTcpServer as TcpServerClass  # type: ignore
        from pymodbus.datastore import ModbusServerContext as ServerContextClass  # type: ignore
        from pymodbus.datastore import ModbusSlaveContext as SlaveContextClass  # type: ignore
        from pymodbus.datastore import ModbusSequentialDataBlock as SeqDataBlockClass  # type: ignore
    except Exception:
        pass


class ModbusServerModule(BaseModule):
    CAPABILITIES = ModuleCapabilities(may_block=True, resource_tags=["modbus","server"], throughput_hint=2.0)

    class ConfigModel(BaseModel):  # type: ignore
        port: int = 1502
        coil_count: int = 64
        holding_count: int = 64
        unit_id: int = 1
        auto_start: bool = True
        update_snapshot: bool = True  # 是否每个周期输出快照

        @validator("port")
        def _port_ok(cls, v):
            if not (0 < v < 65536):
                raise ValueError("端口必须在 1-65535")
            return v

        @validator("coil_count", "holding_count")
        def _size_ok(cls, v):
            if v <= 0 or v > 2000:
                raise ValueError("寄存器数量需在 1-2000 内")
            return v

    def __init__(self, name: str = "modbus模拟服务器"):
        super().__init__(name)
        self._server = None
        self._thread: threading.Thread | None = None
        self._context = None
        self._stop_evt = threading.Event()
        self._coils_cache: List[int] = []
        self._holdings_cache: List[int] = []

    @property
    def module_type(self) -> ModuleType:
        return ModuleType.CUSTOM

    def _define_ports(self):
        # 输入: 可选写入线圈/保持寄存器
        self.register_input_port("coil_values", port_type="list", desc="覆盖写入全部线圈值")
        self.register_input_port("holding_values", port_type="list", desc="覆盖写入全部保持寄存器值")
        # 新增启停控制：True=启动(若未启动) / False=关闭(若已启动)。未连接时由 auto_start 控制
        self.register_input_port("enable", port_type="bool", desc="启用/关闭服务器 (未连接则使用 auto_start)")
        # 输出
        self.register_output_port("host", port_type="str", desc="服务器地址")
        self.register_output_port("port", port_type="int", desc="服务器端口")
        self.register_output_port("context", port_type="modbus_ctx", desc="服务器上下文")
        self.register_output_port("status", port_type="bool", desc="运行状态")
        self.register_output_port("coils", port_type="list", desc="线圈快照")
        self.register_output_port("holdings", port_type="list", desc="保持寄存器快照")
        self.register_output_port("started_once", port_type="bool", desc="是否曾成功启动过")

    def _make_context(self):
        coil_count = int(self.config.get("coil_count", 64))
        holding_count = int(self.config.get("holding_count", 64))
        # 初始化所有寄存器为 0
        di = SeqDataBlockClass(0, [0]*coil_count) if SeqDataBlockClass else None
        co = SeqDataBlockClass(0, [0]*coil_count) if SeqDataBlockClass else None
        hr = SeqDataBlockClass(0, [0]*holding_count) if SeqDataBlockClass else None
        ir = SeqDataBlockClass(0, [0]*holding_count) if SeqDataBlockClass else None
        slave = SlaveContextClass(di=di, co=co, hr=hr, ir=ir) if SlaveContextClass else None
        if slave and ServerContextClass:
            return ServerContextClass(slaves=slave, single=True)
        return None

    def _serve_loop(self):
        try:
            while not self._stop_evt.is_set() and self._server:
                # 旧版服务器可能需要自定义循环; 新版 ModbusTcpServer 有 serve_forever()
                if hasattr(self._server, 'serve_forever'):
                    self._server.serve_forever()
                    break
                else:
                    time.sleep(0.5)
        except Exception as e:
            self.logger.error(f"服务器线程异常: {e}")

    def _on_start(self):
        if TcpServerClass is None:
            self.logger.error("pymodbus 未提供服务器类，无法启动模拟服务器")
            return
        self._context = self._make_context()
        if not self._context:
            self.logger.error("创建服务器上下文失败")
            return
        port = int(self.config.get("port", 1502))
        try:
            self._stop_evt.clear()
            self._server = TcpServerClass(self._context, address=("127.0.0.1", port))
            self._thread = threading.Thread(target=self._serve_loop, daemon=True)
            self._thread.start()
            self.logger.info(f"模拟 Modbus TCP 服务器启动: 127.0.0.1:{port}")
        except Exception as e:
            self.logger.error(f"服务器启动失败: {e}")
            self._server = None

    def _on_stop(self):
        self._stop_evt.set()
        try:
            if self._server:
                if hasattr(self._server, 'server_close'):
                    self._server.server_close()
                if hasattr(self._server, 'shutdown'):
                    try:
                        self._server.shutdown()
                    except Exception:
                        pass
        except Exception:
            pass
        self._server = None
        self._context = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None

    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        # 启停控制：优先输入端口 enable，其次配置 auto_start
        want_enable = inputs.get('enable')
        if want_enable is None:
            want_enable = bool(self.config.get('auto_start', True))
        else:
            # 允许字符串/数字转换
            if isinstance(want_enable, str):
                want_enable = want_enable.strip().lower() in ('1','true','yes','on','start','enable')
            else:
                want_enable = bool(want_enable)
        running = bool(self._server)
        # 根据期望状态执行一次启停（不重复重启）
        if want_enable and not running:
            self._on_start()
            running = bool(self._server)
        elif (not want_enable) and running:
            self._on_stop()
            running = False
        if running and self._context:
            try:
                slave = self._context[0] if hasattr(self._context, '__getitem__') else None
                if slave:
                    # 覆盖写入 coil_values
                    coil_vals = inputs.get('coil_values')
                    if isinstance(coil_vals, list):
                        for i, v in enumerate(coil_vals):
                            try:
                                slave.setValues(1, i, [int(bool(v))])  # 1 = coil
                            except Exception:
                                break
                    hold_vals = inputs.get('holding_values')
                    if isinstance(hold_vals, list):
                        for i, v in enumerate(hold_vals):
                            try:
                                slave.setValues(3, i, [int(v)])  # 3 = holding register
                            except Exception:
                                break
                    # 快照
                    if self.config.get('update_snapshot', True):
                        coil_count = int(self.config.get('coil_count', 64))
                        holding_count = int(self.config.get('holding_count', 64))
                        self._coils_cache = []
                        self._holdings_cache = []
                        for i in range(coil_count):
                            try:
                                val = slave.getValues(1, i, count=1)[0]
                            except Exception:
                                val = 0
                            self._coils_cache.append(val)
                        for i in range(holding_count):
                            try:
                                val = slave.getValues(3, i, count=1)[0]
                            except Exception:
                                val = 0
                            self._holdings_cache.append(val)
            except Exception as e:
                self.logger.error(f"快照更新错误: {e}")
        return {
            'host': '127.0.0.1',
            'port': int(self.config.get('port', 1502)),
            'context': self._context,
            'status': running,
            'coils': list(self._coils_cache),
            'holdings': list(self._holdings_cache),
            'started_once': bool(self._thread)  # 若线程曾创建则表示启动过
        }

    def configure(self, config: Dict[str, Any]) -> bool:
        ok = super().configure(config)
        # 若已运行且调整了寄存器数量，需提示重启
        if ok and self.status == self.status.RUNNING:
            self.logger.info("配置已更新（寄存器数量变更需要重启服务器才生效）")
        return ok

# 允许直接使用 import 时注册
try:
    from ..module_registry import register_module
    register_module("modbus模拟服务器", ModbusServerModule)
except Exception:
    logging.getLogger(__name__).warning("modbus模拟服务器自动注册失败")
