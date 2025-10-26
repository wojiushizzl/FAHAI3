#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import unittest
from app.pipeline.module_registry import list_registered_modules, get_module_class

EXPECTED = {"相机","模型","触发","后处理","文本输入","打印","延时","逻辑"}

class TestRegistrySmoke(unittest.TestCase):
    def _instantiate(self, name: str):
        cls = get_module_class(name)
        self.assertIsNotNone(cls, f"{name} 未注册")
        inst = cls()
        st = inst.get_status()
        self.assertIn("capabilities", st)
        return inst

    def test_registry_contains_expected(self):
        regs = set(list_registered_modules())
        missing = EXPECTED - regs
        self.assertFalse(missing, f"缺少注册模块: {missing}")

    def test_configure_valid_camera(self):
        cam = self._instantiate("相机")
        ok = cam.configure({"fps": 25})
        self.assertTrue(ok)
        self.assertEqual(cam.config.get("fps"), 25)

    def test_configure_invalid_camera(self):
        cam = self._instantiate("相机")
        ok = cam.configure({"fps": -10})
        self.assertFalse(ok)

    def test_logic_config(self):
        logic = self._instantiate("逻辑")
        ok = logic.configure({"op": "OR", "inputs_count": 3})
        self.assertTrue(ok)
        self.assertEqual(logic.config.get("op"), "OR")
        self.assertEqual(logic.config.get("inputs_count"), 3)

if __name__ == '__main__':
    unittest.main()