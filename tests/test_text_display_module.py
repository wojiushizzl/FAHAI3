#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for TextDisplayModule registration and basic processing."""
import pytest
from app.pipeline.module_registry import get_module_class

def test_module_registered():
    cls = get_module_class("文本展示")
    assert cls is not None, "文本展示 模块未注册"

@pytest.mark.parametrize("append", [True, False])
def test_processing_append_modes(append):
    cls = get_module_class("文本展示")
    assert cls is not None
    m = cls()
    m.configure({"append": append, "max_lines": 3})
    # simulate 5 inputs
    for i in range(5):
        outs = m.process({"text_in": f"line{i}"})
        assert "text_out" in outs
    if append:
        # max_lines限制，应只保留最后3行
        assert m.display_text.splitlines() == ["line2","line3","line4"]
    else:
        # 覆盖模式始终只有最后一行
        assert m.display_text.splitlines() == ["line4"]
