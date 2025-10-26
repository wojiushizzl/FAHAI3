#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
标准化接口定义
提供端口、数据包与连接结构，供模块与执行器使用。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
import time

@dataclass
class PortDefinition:
    name: str
    port_type: str = "generic"
    desc: str = ""
    required: bool = False

@dataclass
class DataPacket:
    source_module: str
    source_port: str
    data: Any
    timestamp: float = field(default_factory=lambda: time.time())
    meta: Dict[str, Any] = field(default_factory=dict)

@dataclass
class Connection:
    source_module: str
    source_port: str
    target_module: str
    target_port: str
    active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_module": self.source_module,
            "source_port": self.source_port,
            "target_module": self.target_module,
            "target_port": self.target_port,
            "active": self.active
        }
