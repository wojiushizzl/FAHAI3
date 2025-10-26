#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unittest-based tests for EnhancedFlowCanvas -> PipelineExecutor bridge."""
import os
import sys
import unittest
from PyQt6.QtWidgets import QApplication

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.gui.enhanced_flow_canvas import EnhancedFlowCanvas
from app.gui.connection_graphics import BetterConnectionLine
from app.pipeline.pipeline_executor import PipelineExecutor

_app = QApplication.instance() or QApplication([])

class TestBuildExecutor(unittest.TestCase):
    def _connect(self, canvas, source_type, source_port, target_type, target_port):
        s_item = next(m for m in canvas.modules if m.module_type == source_type)
        t_item = next(m for m in canvas.modules if m.module_type == target_type)
        sp = next(p for p in s_item.output_points if p.port_name == source_port)
        tp = next(p for p in t_item.input_points if p.port_name == target_port)
        line = BetterConnectionLine(sp, tp, canvas=canvas, temp=False)
        canvas.scene.addItem(line)
        sp.connections.append(line)
        tp.connections.append(line)
        canvas.connections.append((line, sp, tp))

    def test_basic_mapping(self):
        canvas = EnhancedFlowCanvas()
        canvas.add_module("文本输入")
        canvas.add_module("打印")
        self._connect(canvas, "文本输入", "text", "打印", "text")
        executor = PipelineExecutor()
        canvas.build_executor(executor)
        self.assertEqual(len(executor.nodes), 2)
        self.assertTrue(any(c.source_port == 'text' and c.target_port == 'text' for c in executor.connections))

    def test_unique_ids(self):
        canvas = EnhancedFlowCanvas()
        canvas.add_module("文本输入")
        canvas.add_module("文本输入")
        executor = PipelineExecutor()
        canvas.build_executor(executor)
        ids = list(executor.nodes.keys())
        self.assertEqual(len(ids), 2)
        self.assertNotEqual(ids[0], ids[1])

    def test_round_trip_serialization(self):
        canvas = EnhancedFlowCanvas()
        canvas.add_module("文本输入")
        canvas.add_module("打印")
        self._connect(canvas, "文本输入", "text", "打印", "text")
        path = os.path.join(ROOT, 'outputs', 'test_pipeline.json')
        if not os.path.isdir(os.path.dirname(path)):
            os.makedirs(os.path.dirname(path), exist_ok=True)
        self.assertTrue(canvas.save_to_file(path))
        new_canvas = EnhancedFlowCanvas()
        self.assertTrue(new_canvas.load_from_file(path))
        struct = new_canvas.export_structure()
        self.assertEqual(len(struct['modules']), 2)
        self.assertEqual(len(struct['connections']), 1)
        conn = struct['connections'][0]
        self.assertEqual(conn['source_port'], 'text')
        self.assertEqual(conn['target_port'], 'text')

if __name__ == '__main__':
    unittest.main()
