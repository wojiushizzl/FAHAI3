#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CameraModule frequency/throttle test
验证 process 调用远高于 target_fps 时输出帧计数不会超过 target_fps 近似范围。
由于真实摄像头不可用，使用 OpenCV 提供的空白帧模拟 (通过 monkeypatch cv2.VideoCapture.read)。
"""
import time
import types
import cv2
import numpy as np
import pytest
from app.pipeline.camera.camera_module import CameraModule

class DummyCapture:
    def __init__(self):
        self.opened = True
        self.counter = 0
    def isOpened(self):
        return self.opened
    def read(self):
        # 返回简单黑帧
        self.counter += 1
        frame = np.zeros((480,640,3), dtype=np.uint8)
        return True, frame
    def release(self):
        self.opened = False

@pytest.fixture
def patched_camera(monkeypatch):
    monkeypatch.setattr(cv2, 'VideoCapture', lambda *a, **kw: DummyCapture())
    m = CameraModule(name="相机")
    assert m.start() is True
    # 将捕获 FPS 设高一些，但 target_fps 设低以测试节流
    m.configure({'fps':60, 'target_fps':10})
    return m

def test_camera_throttle_basic(patched_camera):
    m = patched_camera
    start = time.time()
    produced = 0
    # 快速调用 process 200 次
    for _ in range(200):
        out = m.run_cycle()
        if 'image' in out:
            produced += 1
        # 极短 sleep 模拟忙循环
        time.sleep(0.002)
    elapsed = time.time() - start
    # 理论最大 ~ target_fps * elapsed * 1.3 (允许少量抖动) 
    limit = m.config.get('target_fps',10) * elapsed * 1.3
    assert produced <= limit + 2, f"Produced {produced} frames > limit {limit:.2f}"
    assert produced > 0, "Should produce some frames"
    # meta 检查
    meta = m.outputs.get('meta')
    assert meta and 'output_fps_est' in meta


def test_camera_returns_meta_when_throttled(patched_camera):
    m = patched_camera
    # 连续快速调用, 部分次数应该被标记 throttled True
    throttled_flags = []
    for _ in range(50):
        out = m.run_cycle()
        meta = out.get('meta')
        if meta:
            throttled_flags.append(meta.get('throttled'))
        time.sleep(0.001)
    # 应出现至少一次 True
    assert any(throttled_flags), "Expected some throttled cycles"


def test_camera_stop(patched_camera):
    m = patched_camera
    assert m.stop() is True
    out = m.run_cycle()
    meta = out.get('meta')
    assert meta and meta.get('error') == 'not-started'
