#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Basic tests for EnhancedFlowCanvas -> PipelineExecutor bridge."""
import os
import sys
import pytest
from PyQt6.QtWidgets import QApplication

# Ensure root path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.gui.enhanced_flow_canvas import EnhancedFlowCanvas
from app.gui.connection_graphics import BetterConnectionLine
from app.pipeline.pipeline_executor import PipelineExecutor

@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app

def _connect(canvas, source_type, source_port, target_type, target_port):
    s_item = next(m for m in canvas.modules if m.module_type == source_type)
    t_item = next(m for m in canvas.modules if m.module_type == target_type)
    sp = next(p for p in s_item.output_points if p.port_name == source_port)
    tp = next(p for p in t_item.input_points if p.port_name == target_port)
    line = BetterConnectionLine(sp, tp, canvas=canvas, temp=False)
    canvas.scene.addItem(line)
    sp.connections.append(line)
    tp.connections.append(line)
    canvas.connections.append((line, sp, tp))

def test_build_executor_basic(qapp):
    canvas = EnhancedFlowCanvas()
    canvas.add_module("文本输入")
    canvas.add_module("打印")
    _connect(canvas, "文本输入", "text", "打印", "text")
    executor = PipelineExecutor()
    canvas.build_executor(executor)
    assert len(executor.nodes) == 2, "Should have 2 nodes"
    assert any(c.source_port == "text" and c.target_port == "text" for c in executor.connections), "Connection mapping failed"

def test_unique_ids(qapp):
    canvas = EnhancedFlowCanvas()
    canvas.add_module("文本输入")
    canvas.add_module("文本输入")  # second instance
    executor = PipelineExecutor()
    canvas.build_executor(executor)
    ids = list(executor.nodes.keys())
    assert len(ids) == 2 and ids[0] != ids[1], "IDs should be unique"

def test_connection_export_round_trip(qapp, tmp_path):
    canvas = EnhancedFlowCanvas()
    canvas.add_module("文本输入")
    canvas.add_module("打印")
    _connect(canvas, "文本输入", "text", "打印", "text")
    path = tmp_path / "pipeline.json"
    assert canvas.save_to_file(str(path))
    # New canvas load
    new_canvas = EnhancedFlowCanvas()
    assert new_canvas.load_from_file(str(path))
    struct = new_canvas.export_structure()
    assert len(struct['modules']) == 2
    assert len(struct['connections']) == 1
    conn = struct['connections'][0]
    assert conn['source_port'] == 'text' and conn['target_port'] == 'text'
