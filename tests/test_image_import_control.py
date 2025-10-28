#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ImageImportModule control 输入测试
运行: 手动添加 sys.path 或集成到现有 pytest 后执行
"""
import sys, os, time
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.pipeline.camera.image_import_module import ImageImportModule  # type: ignore


def fake_files(mod: ImageImportModule, n=3):
    mod._files = [f"f{i}.jpg" for i in range(n)]
    mod._idx = 0

class _FakeImg:
    shape=(10,10,3)

# Monkey patch _load_image to avoid disk IO
ImageImportModule._load_image = lambda self, p: _FakeImg()

def test_control_hold():
    m = ImageImportModule()
    m._define_ports()
    fake_files(m, 3)
    # first frame normal
    out1 = m.process({})
    assert out1.get('index') == 0
    # control False, should not advance
    out2 = m.process({'control': False})
    assert out2.get('status') == 'skipped-hold'
    assert out2.get('index') == 0
    # control string pause
    out3 = m.process({'control': 'pause'})
    assert out3.get('status').startswith('skipped')
    # resume
    out4 = m.process({'control': True})
    assert out4.get('index') == 1


def test_control_empty():
    m = ImageImportModule()
    m.config['skip_behavior'] = 'empty'
    m._define_ports()
    fake_files(m, 2)
    out1 = m.process({})
    assert out1.get('index') == 0
    out2 = m.process({'control': 0})  # numeric false
    assert out2.get('status') == 'skipped'
    # ensure index not advanced
    out3 = m.process({})
    assert out3.get('index') == 1

if __name__ == '__main__':
    test_control_hold(); test_control_empty(); print('image import control tests passed')
