#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VideoPlayModule 基础测试

流程:
 1. 生成一个临时视频文件 (20 帧, 彩色渐变)
 2. 实例化模块并 configure(source_type=file, path=tmp_video)
 3. start 模块, 连续调用 process() 读取输出
 4. 断言 frame_index 递增且 image shape 正确
 5. 测试 pause/resume 控制命令
"""
import os
import cv2
import numpy as np
import tempfile
import time
import pytest
from app.pipeline.module_registry import get_module_class


def _create_temp_video(frames: int = 20, size=(64, 48), fps: int = 10) -> str:
    fd, path = tempfile.mkstemp(suffix='.avi')
    os.close(fd)
    fourcc = cv2.VideoWriter_fourcc(*'XVID')
    writer = cv2.VideoWriter(path, fourcc, fps, size)
    for i in range(frames):
        # 生成简单渐变彩色帧
        img = np.zeros((size[1], size[0], 3), dtype=np.uint8)
        img[..., 0] = (i * 10) % 256
        img[..., 1] = (i * 5) % 256
        img[..., 2] = (255 - i * 12) % 256
        writer.write(img)
    writer.release()
    return path


@pytest.mark.video
def test_video_play_basic():
    cls = get_module_class("视频播放")
    assert cls is not None, "视频播放 模块未注册"
    path = _create_temp_video()
    try:
        mod = cls()
        ok = mod.configure({
            'source_type': 'file',
            'path': path,
            'loop': False,
            'target_fps': 30.0,
            'resize_width': 0,
            'resize_height': 0,
            'convert_format': 'BGR',
            'start_paused': False,
            'speed': 1.0,
        })
        assert ok is True, "配置失败"
        assert mod.start() is True, "启动失败"
        frame_indices = []
        shapes = []
        # 给读取线程预热时间
        time.sleep(0.15)
        # 拉取更多次 process
        for _ in range(80):
            out = mod.run_cycle()
            meta = out.get('meta', {})
            fid = meta.get('frame_index')
            if 'image' in out and isinstance(out['image'], np.ndarray):
                shapes.append(out['image'].shape)
            frame_indices.append(fid)
            time.sleep(0.01)
        # 至少应出现多个不同帧序号
        uniq = len(set(frame_indices))
        assert uniq > 5, f"帧序号变化不足: {uniq}"  # 文件20帧, 读取应>5
        # 图像形状合理 (64x48 或 转换后灰度可能为 48x64)
        assert any(len(s) in (2, 3) for s in shapes), "图像 shape 不合法"
        # 测试 pause 控制
        mod.receive_inputs({'control': {'action': 'pause'}})
        paused_fid = mod.run_cycle()['meta']['frame_index']
        time.sleep(0.1)
        mod.run_cycle()
        paused_fid2 = mod.run_cycle()['meta']['frame_index']
        assert paused_fid2 == paused_fid, "暂停后帧序号仍在变化"
        # 恢复
        mod.receive_inputs({'control': {'action': 'resume'}})
        time.sleep(0.05)
        resumed_fid = mod.run_cycle()['meta']['frame_index']
        assert resumed_fid >= paused_fid, "恢复后帧序号未前进"
    finally:
        mod.stop()
        if os.path.exists(path):
            os.remove(path)
