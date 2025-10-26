#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Registry smoke test
验证：
1. 基础模块均已注册。
2. capabilities 字段存在。
3. configure() 对有 ConfigModel 的模块返回 True。
运行方式：pytest -k registry_smoke 或直接 python 执行查看输出。
"""
from app.pipeline.module_registry import list_registered_modules, get_module_class

__all__ = [
    'test_registry_contains_expected',
    'test_configure_valid_camera',
    'test_configure_invalid_camera',
    'test_logic_config'
]

EXPECTED = {"相机","模型","触发","后处理","文本输入","打印","延时","逻辑"}


def _instantiate(display_name: str):
    cls = get_module_class(display_name)
    assert cls is not None, f"{display_name} 未注册"
    inst = cls()
    st = inst.get_status()
    assert "capabilities" in st, f"{display_name} 缺少 capabilities"
    return inst


def test_registry_contains_expected():
    regs = set(list_registered_modules())
    missing = EXPECTED - regs
    assert not missing, f"缺少注册模块: {missing}"


def test_configure_valid_camera():
    cam = _instantiate("相机")
    ok = cam.configure({"fps": 25})
    assert ok is True, "相机配置失败";
    assert cam.config.get("fps") == 25


def test_configure_invalid_camera():
    cam = _instantiate("相机")
    ok = cam.configure({"fps": -10})
    assert ok is False, "负 fps 应该失败"


def test_logic_config():
    logic = _instantiate("逻辑")
    ok = logic.configure({"op": "OR", "inputs_count": 3})
    assert ok is True
    assert logic.config.get("op") == "OR"
    assert logic.config.get("inputs_count") == 3

if __name__ == "__main__":
    # 简单运行输出
    for name in EXPECTED:
        cls = get_module_class(name)
        print(name, "->", cls)
    # Quick instantiate
    m = _instantiate("逻辑")
    print("Logic status capabilities:", m.get_status()["capabilities"])