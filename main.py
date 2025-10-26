#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FAHAI - 图形化流程设计器
程序入口，启动 GUI 应用程序
"""

import sys
import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.gui.main_window import MainWindow


def main():
    """主函数，启动应用程序"""
    # 创建 QApplication 实例
    app = QApplication(sys.argv)
    
    # 设置应用程序属性
    app.setApplicationName("FAHAI")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("FAHAI Project")
    
    # 启用高DPI支持
    # 高 DPI 属性在 Qt6 中可能默认启用，旧枚举可能不存在，安全尝试
    try:
        app.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    except AttributeError:
        pass
    try:
        app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    except AttributeError:
        pass
    
    # 创建主窗口
    main_window = MainWindow()
    main_window.show()
    
    # 运行应用程序
    sys.exit(app.exec())


if __name__ == "__main__":
    main()