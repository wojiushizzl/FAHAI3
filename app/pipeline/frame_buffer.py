#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""简单帧缓冲容器池
提供字典容器复用，减少频繁分配开销（图像 numpy 数组保持原始引用，不拷贝）。
后续可扩展为真正的预分配 numpy 内存或共享内存机制。
"""
from collections import deque
from typing import Deque, Dict, Any


class FrameBufferPool:
    def __init__(self, maxsize: int = 10):
        self._free: Deque[Dict[str, Any]] = deque()
        self._maxsize = maxsize

    def borrow(self) -> Dict[str, Any]:
        try:
            buf = self._free.popleft()
            buf.clear()  # 清空旧字段
            return buf
        except IndexError:
            return {}

    def release(self, buf: Dict[str, Any]):
        if len(self._free) < self._maxsize:
            # 仅保留关键字段占位，图像引用会由外部继续持有（或被 GC）
            buf.clear()
            self._free.append(buf)

    def stats(self) -> Dict[str, Any]:
        return {"free": len(self._free), "maxsize": self._maxsize}
