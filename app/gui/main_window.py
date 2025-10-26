#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主窗口模块
提供拖拽流程画布的主界面
"""

from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QMenuBar, QStatusBar, QToolBar, QSplitter, QFileDialog, QLabel, QProgressBar)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QIcon, QKeySequence, QAction
import os, json

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
        # 最近项目记录文件 (放在当前工作目录，可根据需要迁移到用户家目录)
        self._last_project_meta_path = os.path.join(os.getcwd(), "last_project.json")

        # 初始化UI组件
        self._init_ui()
        self._init_menu()
        self._init_toolbar()
        self._init_statusbar()
        self._connect_signals()
        # 延迟热加载上次项目，避免启动时卡顿（showEvent 中 singleShot 调用）
        self._auto_load_scheduled = False
        # 状态栏扩展：系统信息 & 性能信息
        self._sysinfo_timer = QTimer(self)
        self._sysinfo_timer.setInterval(1500)  # 1.5s 更新
        self._sysinfo_timer.timeout.connect(self._update_system_info)
        self._sysinfo_timer.start()
        self._metrics_timer = QTimer(self)
        self._metrics_timer.setInterval(1200)  # 1.2s 更新执行器性能（冗余防止与系统信息同时刷新卡顿）
        self._metrics_timer.timeout.connect(self._refresh_executor_metrics)
        self._metrics_timer.start()
        self._last_metrics_snapshot = {}
        # GPU 初始化 (pynvml)
        self._gpu_available = False
        self._pynvml = None
        self._gpu_handle = None
        self._gpu_handles = []
        try:
            import pynvml
            pynvml.nvmlInit()
            count = pynvml.nvmlDeviceGetCount()
            if count > 0:
                for i in range(count):
                    try:
                        h = pynvml.nvmlDeviceGetHandleByIndex(i)
                        self._gpu_handles.append(h)
                    except Exception:
                        pass
                if self._gpu_handles:
                    self._gpu_handle = self._gpu_handles[0]
                    self._pynvml = pynvml
                    self._gpu_available = True
        except Exception:
            self._gpu_available = False
        self._sysinfo_enabled = True
        
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
        # 监控菜单
        monitor_menu = menubar.addMenu('监控(&M)')
        reset_metrics_action = QAction('重置性能指标', self)
        reset_metrics_action.triggered.connect(self.reset_executor_metrics)
        monitor_menu.addAction(reset_metrics_action)
        toggle_sysinfo_action = QAction('系统信息轮询', self)
        toggle_sysinfo_action.setCheckable(True)
        toggle_sysinfo_action.setChecked(True)
        toggle_sysinfo_action.triggered.connect(self._toggle_system_info)
        monitor_menu.addAction(toggle_sysinfo_action)
        grid_toggle_action = QAction('切换网格显示', self)
        grid_toggle_action.triggered.connect(lambda: self.flow_canvas.toggle_grid())
        monitor_menu.addAction(grid_toggle_action)
        
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
        # 右侧系统信息标签 + 进度条
        self.cpu_bar = QProgressBar()
        self.cpu_bar.setRange(0,100)
        self.cpu_bar.setFixedWidth(80)
        self.cpu_bar.setTextVisible(False)
        self.cpu_bar.setStyleSheet("QProgressBar { border:1px solid #bbb; background:#eee; } QProgressBar::chunk { background:#4caf50; }")
        self.gpu_bar = QProgressBar()
        self.gpu_bar.setRange(0,100)
        self.gpu_bar.setFixedWidth(80)
        self.gpu_bar.setTextVisible(False)
        self.gpu_bar.setStyleSheet("QProgressBar { border:1px solid #bbb; background:#eee; } QProgressBar::chunk { background:#2196f3; }")
        self.disk_bar = QProgressBar()
        self.disk_bar.setRange(0,100)
        self.disk_bar.setFixedWidth(80)
        self.disk_bar.setTextVisible(False)
        self.disk_bar.setStyleSheet("QProgressBar { border:1px solid #bbb; background:#eee; } QProgressBar::chunk { background:#ff9800; }")
        self.sysinfo_label = QLabel("CPU: --% | GPU: -- | Disk: --")
        self.sysinfo_label.setStyleSheet("QLabel { color: #555; padding-left:6px; }")
        self.metrics_label = QLabel("Exec: 0 | Avg: 0ms | Slow: -")
        self.metrics_label.setStyleSheet("QLabel { color:#444; padding-left:12px; }")
        self.statusbar.addPermanentWidget(self.metrics_label)
        self.statusbar.addPermanentWidget(QLabel("CPU"))
        self.statusbar.addPermanentWidget(self.cpu_bar)
        self.statusbar.addPermanentWidget(QLabel("GPU"))
        self.statusbar.addPermanentWidget(self.gpu_bar)
        self.statusbar.addPermanentWidget(QLabel("Disk"))
        self.statusbar.addPermanentWidget(self.disk_bar)
        self.statusbar.addPermanentWidget(self.sysinfo_label)
        
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
            self._persist_last_project(path)
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
            self._persist_last_project(self._current_pipeline_path)
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
            self._persist_last_project(path)
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
        # 性能指标回调（冗余保障：即使定时器刷新，仍在有新数据时立即更新缓存）
        self.pipeline_executor.add_metrics_callback(self._on_executor_metrics)
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
        exec_once.add_metrics_callback(lambda nodes, agg: self._cache_metrics_snapshot(nodes, agg))
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

    def showEvent(self, event):
        super().showEvent(event)
        # 首次显示后延迟加载最近项目
        if not self._auto_load_scheduled:
            self._auto_load_scheduled = True
            from PyQt6.QtCore import QTimer
            self.statusbar.showMessage('正在准备热加载上次项目...')
            QTimer.singleShot(400, self._auto_load_last_project)

    # ---------- 系统信息更新 ----------
    def _update_system_info(self):
        cpu_percent = None
        gpu_mem_percent = None
        gpu_txt = 'None'
        cpu_txt = 'n/a'
        disk_percent = None
        disk_txt = 'n/a'
        # CPU
        try:
            import psutil
            cpu_percent = psutil.cpu_percent(interval=0)
            cpu_txt = f"{cpu_percent:.0f}%"
        except Exception:
            cpu_percent = None
        # GPU 多卡信息
        if self._gpu_available and self._pynvml and self._gpu_handles:
            segments = []
            try:
                for idx, h in enumerate(self._gpu_handles):
                    try:
                        mem_info = self._pynvml.nvmlDeviceGetMemoryInfo(h)
                        util_info = self._pynvml.nvmlDeviceGetUtilizationRates(h)
                        used_mb = mem_info.used / 1024**2
                        total_mb = mem_info.total / 1024**2
                        percent = (mem_info.used / mem_info.total) * 100.0 if mem_info.total else 0.0
                        if idx == 0:
                            gpu_mem_percent = percent
                        segments.append(f"GPU{idx}:{used_mb:.0f}/{total_mb:.0f}MB {util_info.gpu}%")
                    except Exception:
                        segments.append(f"GPU{idx}:n/a")
                gpu_txt = ' | '.join(segments)
            except Exception:
                gpu_mem_percent = None
        else:
            # 回退 torch (仅显示本进程分配，不是全局)
            try:
                import torch
                if torch.cuda.is_available():
                    props = torch.cuda.get_device_properties(0)
                    total_mb = props.total_memory / 1024**2
                    used_mb = torch.cuda.memory_allocated(0) / 1024**2
                    gpu_mem_percent = (used_mb/total_mb)*100.0 if total_mb else 0.0
                    name = torch.cuda.get_device_name(0)
                    gpu_txt = f"{name} {used_mb:.0f}/{total_mb:.0f}MB"
            except Exception:
                gpu_mem_percent = None
        # 磁盘 (使用当前工作目录所在分区)
        try:
            import psutil, pathlib
            root_drive = pathlib.Path(os.getcwd()).anchor or os.getcwd()
            usage = psutil.disk_usage(root_drive)
            disk_percent = usage.percent
            used_gb = usage.used / 1024**3
            total_gb = usage.total / 1024**3
            disk_txt = f"{used_gb:.1f}/{total_gb:.1f}GB {disk_percent:.0f}%"
        except Exception:
            disk_percent = None

        # 更新进度条
        if cpu_percent is not None:
            self.cpu_bar.setValue(int(cpu_percent))
        else:
            self.cpu_bar.setValue(0)
        if gpu_mem_percent is not None:
            self.gpu_bar.setValue(int(gpu_mem_percent))
            self.gpu_bar.setEnabled(True)
        else:
            self.gpu_bar.setValue(0)
            self.gpu_bar.setEnabled(False)
        if disk_percent is not None:
            self.disk_bar.setValue(int(disk_percent))
            self.disk_bar.setEnabled(True)
        else:
            self.disk_bar.setValue(0)
            self.disk_bar.setEnabled(False)
        self.sysinfo_label.setText(f"CPU: {cpu_txt} | GPU: {gpu_txt} | Disk: {disk_txt}")

    def _toggle_system_info(self, checked: bool):
        self._sysinfo_enabled = bool(checked)
        if self._sysinfo_enabled:
            self._sysinfo_timer.start(); self._metrics_timer.start()
            self.statusbar.showMessage('系统信息轮询已开启')
        else:
            self._sysinfo_timer.stop(); self._metrics_timer.stop()
            self.statusbar.showMessage('系统信息轮询已关闭')

    # ---------- 性能指标刷新 ----------
    def _on_executor_metrics(self, nodes: dict, aggregate: dict):
        self._cache_metrics_snapshot(nodes, aggregate)
        self._apply_metrics_display()

    def _cache_metrics_snapshot(self, nodes: dict, aggregate: dict):
        # 计算最慢模块（按 avg_time 或 last_time）
        slow_mod = '-'
        slow_time_ms = 0.0
        try:
            if nodes:
                # 优先使用 avg_time 判断整体慢；若 avg 相近使用 max
                sorted_nodes = sorted(nodes.items(), key=lambda kv: kv[1].get('avg_time', 0), reverse=True)
                nid, stat = sorted_nodes[0]
                slow_mod = nid
                slow_time_ms = stat.get('avg_time', 0.0) * 1000.0
        except Exception:
            pass
        snap = {
            'execs': aggregate.get('total_execs', 0),
            'total_time': aggregate.get('total_time', 0.0),
            'modules': aggregate.get('modules_profiled', 0),
            'slow_mod': slow_mod,
            'slow_ms': slow_time_ms
        }
        # 平均耗时（总时间 / 总执行次数）
        if snap['execs'] > 0:
            snap['avg_ms'] = (snap['total_time'] / snap['execs']) * 1000.0
        else:
            snap['avg_ms'] = 0.0
        self._last_metrics_snapshot = snap

    def _apply_metrics_display(self):
        if not self._last_metrics_snapshot:
            return
        s = self._last_metrics_snapshot
        self.metrics_label.setText(
            f"Exec: {s['execs']} | Avg: {s['avg_ms']:.1f}ms | Slow: {s['slow_mod']} {s['slow_ms']:.1f}ms"
        )

    def _refresh_executor_metrics(self):
        # 若执行器存在，主动抓取最新 metrics
        if self.pipeline_executor:
            try:
                data = self.pipeline_executor.get_metrics()
                self._cache_metrics_snapshot(data['nodes'], data['aggregate'])
            except Exception:
                pass
        self._apply_metrics_display()

    def reset_executor_metrics(self):
        if self.pipeline_executor:
            try:
                self.pipeline_executor.reset_metrics()
            except Exception:
                pass
        self._last_metrics_snapshot = {}
        self.metrics_label.setText("Exec: 0 | Avg: 0ms | Slow: -")

    # ---------- 最近项目自动加载/保存 ----------
    def _persist_last_project(self, path: str):
        """记录最近打开的项目路径到元数据文件"""
        try:
            data = {"pipeline_path": path, "ts": time.time()}
            with open(self._last_project_meta_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            # 非致命错误，仅状态栏提示
            self.statusbar.showMessage(f'记录最近项目失败: {e}')

    def _auto_load_last_project(self):
        """尝试自动加载最近记录的项目，如果存在且未显式指定新项目。"""
        if self._current_pipeline_path:  # 已有当前路径时不自动加载
            return
        if not os.path.exists(self._last_project_meta_path):
            return
        try:
            with open(self._last_project_meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            recent_path = meta.get('pipeline_path')
            if recent_path and os.path.exists(recent_path) and recent_path.lower().endswith('.json'):
                # 使用增量加载，缓解启动卡顿
                def _progress(done, total):
                    self.statusbar.showMessage(f'热加载进度: {done}/{total} 模块')
                def _finished(ok):
                    if ok:
                        self._current_pipeline_path = recent_path
                        self.statusbar.showMessage(f'热加载完成: {recent_path}')
                    else:
                        self.statusbar.showMessage('热加载失败')
                if hasattr(self.flow_canvas, 'load_from_file_incremental'):
                    self.flow_canvas.load_from_file_incremental(recent_path, batch_size=8, progress_cb=_progress, finished_cb=_finished)
                else:
                    ok = self.flow_canvas.load_from_file(recent_path)
                    _finished(ok)
        except Exception as e:
            self.statusbar.showMessage(f'自动加载异常: {e}')