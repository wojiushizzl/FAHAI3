#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for SaveTextModule."""
import os
import tempfile
from app.pipeline.custom.save_text_module import SaveTextModule

def test_save_text_basic(tmp_path):
    m = SaveTextModule()
    # 禁用时间戳确保内容可预测
    m.configure({"file_path": str(tmp_path / "log.txt"), "append": True, "add_timestamp": False})
    m.start()
    out1 = m.process({"text": "Hello"})
    out2 = m.process({"text": "World"})
    assert out1["status"].startswith("ok:")
    assert out2["status"].startswith("ok:")
    with open(tmp_path / "log.txt", "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    assert lines == ["Hello", "World"]

def test_save_text_override(tmp_path):
    m = SaveTextModule()
    m.configure({"file_path": str(tmp_path / "log2.txt"), "append": True, "add_timestamp": False})
    m.start()
    m.process({"text": "A"})
    # 改为覆盖
    m.configure({"append": False})
    m.process({"text": "B"})
    with open(tmp_path / "log2.txt", "r", encoding="utf-8") as f:
        data = f.read().strip().splitlines()
    assert data == ["B"]

def test_empty_placeholder(tmp_path):
    m = SaveTextModule()
    m.configure({"file_path": str(tmp_path / "log3.txt"), "append": False, "add_timestamp": False, "empty_placeholder": "(none)"})
    m.start()
    m.process({"text": ""})
    with open(tmp_path / "log3.txt", "r", encoding="utf-8") as f:
        data = f.read().strip()
    assert data == "(none)"
