#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主窗口模块
提供拖拽流程画布的主界面
"""

from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QMenuBar, QStatusBar, QToolBar, QSplitter, QFileDialog)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QKeySequence, QAction

from .enhanced_flow_canvas import EnhancedFlowCanvas
from app.pipeline.pipeline_executor import PipelineExecutor, ExecutionMode, PipelineStatus
import threading, time
from typing import Dict, Any
from .dock_panel import DockPanel, PropertyPanel


class MainWindow(QMainWindow):
    # 跨线程模块执行步骤事件：在执行器工作线程中发射，主线程接收
    module_step_event = pyqtSignal(str, str)
    """主窗口类，管理整个应用程序界面"""
    
    # 信号定义
    project_opened = pyqtSignal(str)  # 项目打开信号
    project_saved = pyqtSignal(str)   # 项目保存信号
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FAHAI - 图形化流程设计器")
        self.setGeometry(100, 100, 1200, 800)
        self.pipeline_executor: PipelineExecutor | None = None
        self._feeder_thread: threading.Thread | None = None
        self._feeder_stop = threading.Event()
        self._current_pipeline_path: str | None = None  # 当前项目文件路径（用于 Ctrl+S 直接保存）
        self._last_save_ts: float = 0.0  # 保存节流时间戳
        self._save_min_interval_ms: int = 500  # 最小间隔
        
        # 初始化UI组件
        self._init_ui()
        self._init_menu()
        self._init_toolbar()
        self._init_statusbar()
        self._connect_signals()
        
    def _init_ui(self):
        """初始化用户界面"""
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建主布局
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建分割器
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)
        # 创建增强版流程画布（支持端口拖拽连线）
        self.flow_canvas = EnhancedFlowCanvas()
        # 左侧模块工具箱面板
        self.dock_panel = DockPanel()
        splitter.addWidget(self.dock_panel)
        splitter.addWidget(self.flow_canvas)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 900])
        # 右侧属性面板 Dock
        from PyQt6.QtWidgets import QDockWidget
        self.property_panel = PropertyPanel()
        self.property_dock = QDockWidget("属性", self)
        self.property_dock.setObjectName("RightPropertyDock")
        self.property_dock.setWidget(self.property_panel)
        self.property_dock.setMinimumWidth(280)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.property_dock)
        self.property_dock.raise_()
        # 跨线程信号连接（模块执行高亮）
        self.module_step_event.connect(self.flow_canvas.highlight_execution)
        # 全局快捷键（确保在焦点位于画布或其它控件时仍可触发）
        from PyQt6.QtGui import QShortcut, QKeySequence
        self._sc_new = QShortcut(QKeySequence("Ctrl+N"), self, activated=self._new_project)
        self._sc_open = QShortcut(QKeySequence("Ctrl+O"), self, activated=self._open_project)
        # 移除 Ctrl+S 快捷键定义，仅使用菜单/工具栏 QAction (避免 Ambiguous shortcut overload)
        self._sc_save_as = QShortcut(QKeySequence("Ctrl+Shift+S"), self, activated=self._save_project_as)
        self._sc_inject = QShortcut(QKeySequence("Ctrl+I"), self, activated=self._inject_data)
        self._sc_apply = QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._apply_properties)
        
    def _init_menu(self):
        """初始化菜单栏"""
        menubar = self.menuBar()
        
        # 文件菜单
        file_menu = menubar.addMenu('文件(&F)')
        
        # 新建项目
        new_action = QAction('新建项目(&N)', self)
        new_action.setShortcut(QKeySequence(QKeySequence.StandardKey.New))
        new_action.triggered.connect(self._new_project)
        file_menu.addAction(new_action)
        
        # 打开项目
        open_action = QAction('打开项目(&O)', self)
        open_action.setShortcut(QKeySequence(QKeySequence.StandardKey.Open))
        open_action.triggered.connect(self._open_project)
        file_menu.addAction(open_action)
        
        file_menu.addSeparator()

        # 保存流程
        save_action = QAction('保存流程(&S)', self)
        save_action.setShortcut(QKeySequence(QKeySequence.StandardKey.Save))
        save_action.triggered.connect(self._save_project)
        file_menu.addAction(save_action)

        # 加载流程
        load_action = QAction('加载流程(&L)', self)
        load_action.setShortcut(QKeySequence('Ctrl+Shift+O'))
        load_action.triggered.connect(self._open_project)
        file_menu.addAction(load_action)

        file_menu.addSeparator()

        # 退出
        exit_action = QAction('退出(&X)', self)
        exit_action.setShortcut(QKeySequence(QKeySequence.StandardKey.Quit))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # 编辑菜单
        edit_menu = menubar.addMenu('编辑(&E)')

        # 撤销
        undo_action = QAction('撤销(&U)', self)
        undo_action.setShortcut(QKeySequence(QKeySequence.StandardKey.Undo))
        undo_action.triggered.connect(self._undo)
        edit_menu.addAction(undo_action)

        # 重做
        redo_action = QAction('重做(&R)', self)
        redo_action.setShortcut(QKeySequence(QKeySequence.StandardKey.Redo))
        redo_action.triggered.connect(self._redo)
        edit_menu.addAction(redo_action)

        edit_menu.addSeparator()

        # 复制
        copy_action = QAction('复制(&C)', self)
        copy_action.setShortcut(QKeySequence(QKeySequence.StandardKey.Copy))
        copy_action.triggered.connect(self._copy)
        edit_menu.addAction(copy_action)

        # 粘贴
        paste_action = QAction('粘贴(&V)', self)
        paste_action.setShortcut(QKeySequence(QKeySequence.StandardKey.Paste))
        paste_action.triggered.connect(self._paste)
        edit_menu.addAction(paste_action)

        # 删除
        delete_action = QAction('删除(&D)', self)
        delete_action.setShortcut(QKeySequence('Delete'))
        delete_action.triggered.connect(self._delete)
        edit_menu.addAction(delete_action)
        # 复制并偏移 (Duplicate)
        duplicate_action = QAction('复制并偏移(&D)', self)
        duplicate_action.setShortcut(QKeySequence('Ctrl+D'))
        duplicate_action.triggered.connect(self._duplicate_selection)
        edit_menu.addAction(duplicate_action)

        # 运行菜单
        run_menu = menubar.addMenu('运行(&R)')

        # 运行流程
        run_action = QAction('运行流程(&R)', self)
        run_action.setShortcut(QKeySequence('F5'))
        run_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        run_action.triggered.connect(self._run_pipeline)
        run_menu.addAction(run_action)

        # 暂停
        pause_action = QAction('暂停(&P)', self)
        pause_action.setShortcut(QKeySequence('F6'))
        pause_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        pause_action.triggered.connect(self._pause_pipeline)
        run_menu.addAction(pause_action)

        # 恢复
        resume_action = QAction('恢复(&E)', self)
        resume_action.setShortcut(QKeySequence('F7'))
        resume_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        resume_action.triggered.connect(self._resume_pipeline)
        run_menu.addAction(resume_action)

        # 停止运行
        stop_action = QAction('停止运行(&S)', self)
        stop_action.setShortcut(QKeySequence('F8'))
        stop_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        stop_action.triggered.connect(self._stop_pipeline)
        run_menu.addAction(stop_action)

        # 单次执行
        run_once_action = QAction('运行一次(&O)', self)
        run_once_action.setShortcut(QKeySequence('F9'))
        run_once_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        run_once_action.triggered.connect(self._run_pipeline_once)
        run_menu.addAction(run_once_action)

        # 帮助菜单
        help_menu = menubar.addMenu('帮助(&H)')

        # 关于
        about_action = QAction('关于(&A)', self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)
        
    def _init_toolbar(self):
        """初始化工具栏"""
        toolbar = self.addToolBar('主工具栏')
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        
        run_act = QAction('运行 F5', self); run_act.triggered.connect(self._run_pipeline)
        pause_act = QAction('暂停 F6', self); pause_act.triggered.connect(self._pause_pipeline)
        resume_act = QAction('恢复 F7', self); resume_act.triggered.connect(self._resume_pipeline)
        stop_act = QAction('停止 F8', self); stop_act.triggered.connect(self._stop_pipeline)
        run_once_act = QAction('单次 F9', self); run_once_act.triggered.connect(self._run_pipeline_once)
        inject_act = QAction('注入数据', self); inject_act.triggered.connect(self._inject_data)
        edit_act = QAction('编辑模块', self); edit_act.triggered.connect(self._edit_selected_module)
        toolbar.addActions([run_act, pause_act, resume_act, stop_act, run_once_act, inject_act, edit_act])
        
    def _init_statusbar(self):
        """初始化状态栏"""
        self.statusbar = self.statusBar()
        self.statusbar.showMessage('就绪')
        
    def _connect_signals(self):
        """连接信号和槽"""
        # 连接画布和停靠面板的信号
        self.dock_panel.module_selected.connect(self.flow_canvas.add_module)
        self.flow_canvas.module_selected.connect(self._on_canvas_module_selected)
        
    # 菜单动作槽函数
    def _new_project(self):
        """新建项目"""
        self.flow_canvas.clear()
        self.statusbar.showMessage('新建项目')
        
    def _open_project(self):
        """加载流程文件"""
        path, _ = QFileDialog.getOpenFileName(self, '加载流程', '', 'Pipeline (*.json);;All (*)')
        if not path:
            return
        ok = self.flow_canvas.load_from_file(path)
        if ok:
            self.statusbar.showMessage(f'加载成功: {path}')
            self._current_pipeline_path = path
        else:
            self.statusbar.showMessage('加载失败')
        
    def _save_project(self):
        """保存流程到当前文件；若无当前路径则提示另存为。"""
        # 节流: 避免短时间重复触发 Ctrl+S 导致磁盘频繁写入
        now = time.time()*1000.0
        if (now - self._last_save_ts) < self._save_min_interval_ms:
            self.statusbar.showMessage('保存过于频繁，已忽略')
            return
        self._last_save_ts = now
        if not self._current_pipeline_path:
            self._save_project_as()
            return
        ok = self.flow_canvas.save_to_file(self._current_pipeline_path)
        if ok:
            self.statusbar.showMessage(f'保存成功: {self._current_pipeline_path}')
        else:
            self.statusbar.showMessage('保存失败')
        
    def _save_project_as(self):
        path, _ = QFileDialog.getSaveFileName(self, '另存为流程', self._current_pipeline_path or '', 'Pipeline (*.json);;All (*)')
        if not path:
            return
        ok = self.flow_canvas.save_to_file(path)
        if ok:
            self._current_pipeline_path = path
            self._last_save_ts = time.time()*1000.0  # 更新节流时间戳
        self.statusbar.showMessage('另存为成功' if ok else '另存为失败')
        
    def _undo(self):
        self.flow_canvas.undo()
        self.statusbar.showMessage('撤销完成')
        
    def _redo(self):
        self.flow_canvas.redo()
        self.statusbar.showMessage('重做完成')
        
    def _copy(self):
        self.flow_canvas.copy_selection()
        self.statusbar.showMessage('已复制')
        
    def _paste(self):
        self.flow_canvas.paste_selection()
        self.statusbar.showMessage('已粘贴')
        
    def _delete(self):
        self.flow_canvas.delete_selection()
        self.statusbar.showMessage('已删除')
    
    def _duplicate_selection(self):
        self.flow_canvas.duplicate_selection()
        self.statusbar.showMessage('已复制并粘贴')

    def _apply_properties(self):
        if hasattr(self.property_panel, 'apply_current'):
            self.property_panel.apply_current()
            self.statusbar.showMessage('属性已应用')
    
    def _on_canvas_module_selected(self, module_item):
        """当画布选中模块时刷新右侧属性面板"""
        if self.property_panel:
            self.property_panel.show_module_properties(module_item)
        
    def _run_pipeline(self):
        """运行流程"""
        # 若已有执行器在跑，忽略
        if self.pipeline_executor and self.pipeline_executor.status == PipelineStatus.RUNNING:
            self.statusbar.showMessage('流程已在运行中')
            return
        # 构建执行器
        self.pipeline_executor = PipelineExecutor()
        self.flow_canvas.build_executor(self.pipeline_executor)
        # 设为顺序执行
        self.pipeline_executor.set_execution_mode(ExecutionMode.SEQUENTIAL)
        # 注册回调
        self.pipeline_executor.add_progress_callback(self._on_executor_progress)
        self.pipeline_executor.add_result_callback(self._on_executor_result)
        self.pipeline_executor.add_error_callback(self._on_executor_error)
        # 模块执行步骤回调（用于画布高亮）
        self.pipeline_executor.add_module_step_callback(self._on_executor_module_step)
        # 启动执行器，传入初始空输入
        started = self.pipeline_executor.start(input_data={})
        if not started:
            self.statusbar.showMessage('流程启动失败')
            return
        # 启动馈送线程：周期推送空输入触发循环
        self._feeder_stop.clear()
        self._feeder_thread = threading.Thread(target=self._feeder_loop, daemon=True)
        self._feeder_thread.start()
        self.statusbar.showMessage('流程已启动')

    def _run_pipeline_once(self):
        """构建并执行单次流程，不进入持续馈送线程。"""
        if self.pipeline_executor and self.pipeline_executor.status in (PipelineStatus.RUNNING, PipelineStatus.PAUSED):
            self.statusbar.showMessage('持续运行中，无法单次执行')
            return
        # 新建执行器并构建流程
        exec_once = PipelineExecutor()
        self.flow_canvas.build_executor(exec_once)
        exec_once.set_execution_mode(ExecutionMode.SEQUENTIAL)  # 强制顺序
        # 注册高亮与结果回调（临时）
        exec_once.add_module_step_callback(self._on_executor_module_step)
        exec_once.add_result_callback(lambda r: self.statusbar.showMessage(f'单次结果: {list(r.keys())[:5]}'))
        exec_once.add_error_callback(lambda e: self.statusbar.showMessage(f'单次执行错误: {e}'))
        result = exec_once.run_once(input_data={})
        if result is None:
            if exec_once.status == PipelineStatus.ERROR:
                self.statusbar.showMessage('单次执行失败')
            else:
                self.statusbar.showMessage('单次执行未产出结果')
        else:
            self.statusbar.showMessage('单次执行完成')
        
    def _stop_pipeline(self):
        """停止流程"""
        if not self.pipeline_executor:
            self.statusbar.showMessage('无执行器实例')
            return
        self._feeder_stop.set()
        if self._feeder_thread and self._feeder_thread.is_alive():
            self._feeder_thread.join(timeout=2)
        self.pipeline_executor.stop()
        self.statusbar.showMessage('流程已停止')

    def _pause_pipeline(self):
        if not self.pipeline_executor or self.pipeline_executor.status != PipelineStatus.RUNNING:
            self.statusbar.showMessage('不可暂停')
            return
        self.pipeline_executor.pause()
        self.statusbar.showMessage('流程已暂停')

    def _resume_pipeline(self):
        if not self.pipeline_executor or self.pipeline_executor.status != PipelineStatus.PAUSED:
            self.statusbar.showMessage('不可恢复')
            return
        self.pipeline_executor.resume()
        self.statusbar.showMessage('流程已恢复')

    def _inject_data(self):
        """手动注入数据包到执行器输入队列"""
        if not self.pipeline_executor or self.pipeline_executor.status != PipelineStatus.RUNNING:
            self.statusbar.showMessage('流程未运行，无法注入')
            return
        from PyQt6.QtWidgets import QInputDialog
        key, ok = QInputDialog.getText(self, '注入数据', '键名:')
        if not ok or not key:
            return
        value, ok2 = QInputDialog.getText(self, '注入数据', f'值 ({key}):')
        if not ok2:
            return
        packet = {key: value}
        self.pipeline_executor.input_queue.put(packet)
        self.statusbar.showMessage(f'已注入: {key}={value}')

    def _edit_selected_module(self):
        """针对选中文本输入模块快速编辑文本"""
        sel = self.flow_canvas.scene.selectedItems()
        if not sel:
            self.statusbar.showMessage('未选中模块')
            return
        item = sel[0]
        from PyQt6.QtWidgets import QInputDialog
        if hasattr(item, 'module_type') and item.module_type == '文本输入' and item.module_ref:
            current = getattr(item.module_ref, 'text_value', '')
            new_text, ok = QInputDialog.getText(self, '编辑文本', '文本内容:', text=current)
            if ok:
                item.module_ref.set_text(new_text)
                self.statusbar.showMessage('文本已更新')
        else:
            self.statusbar.showMessage('该模块不支持快速编辑')

    # ---------- 执行器辅助 ----------
    def _feeder_loop(self):
        # 定期投递空输入，触发一次顺序执行
        while not self._feeder_stop.is_set():
            try:
                if self.pipeline_executor and self.pipeline_executor.status == PipelineStatus.RUNNING:
                    self.pipeline_executor.input_queue.put({})
            except Exception:
                pass
            time.sleep(0.5)

    def _on_executor_progress(self, count: int, exec_time: float):
        self.statusbar.showMessage(f'执行次数: {count} | 最近耗时: {exec_time:.3f}s')

    def _on_executor_result(self, result: Dict[str, Any]):
        # 简化展示：显示已有键
        keys = ','.join(list(result.keys())[:5])
        self.statusbar.showMessage(f'最新结果键: {keys}')

    def _on_executor_error(self, error: Exception):
        self.statusbar.showMessage(f'执行错误: {error}')
    
    def _on_executor_module_step(self, node_id: str, phase: str):
        """执行器线程触发的模块执行步骤事件→转发为主线程信号。"""
        # 使用 Qt 信号队列到主线程，避免直接跨线程操作 GUI / QTimer
        self.module_step_event.emit(node_id, phase)
        
    def _show_about(self):
        """显示关于对话框"""
        # TODO: 实现关于对话框
        self.statusbar.showMessage('关于 FAHAI')
        
    def closeEvent(self, event):
        """窗口关闭事件"""
        # TODO: 在关闭前询问是否保存项目
        event.accept()