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
import os
from app.utils.i18n import set_language_mode, get_language_mode, translate, L


class MainWindow(QMainWindow):
    # 跨线程模块执行步骤事件：在执行器工作线程中发射，主线程接收
    module_step_event = pyqtSignal(str, str)
    """主窗口类，管理整个应用程序界面"""
    
    # 信号定义
    project_opened = pyqtSignal(str)  # 项目打开信号
    project_saved = pyqtSignal(str)   # 项目保存信号
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FAHAI - AOI @ HzP")
        self.setGeometry(100, 100, 1200, 800)
        self.pipeline_executor: PipelineExecutor | None = None
        self._feeder_thread: threading.Thread | None = None
        self._feeder_stop = threading.Event()
        self._feeder_interval_sec: float = 0.5  # F5 运行循环投递间隔(秒)，可配置
        self._current_pipeline_path: str | None = None  # 当前项目文件路径（用于 Ctrl+S 直接保存）
        self._last_save_ts: float = 0.0  # 保存节流时间戳
        self._save_min_interval_ms: int = 500  # 最小间隔
        # user_data 目录用于存放用户持久化数据（不纳入版本控制）
        self._user_data_dir = os.path.join(os.getcwd(), 'user_data')
        try:
            os.makedirs(self._user_data_dir, exist_ok=True)
        except Exception:
            pass
        # 通用用户设置文件路径（扩展后可加入其它偏好）
        self._settings_path = os.path.join(self._user_data_dir, 'settings.json')
        # 定义持久化文件路径
        self._last_project_meta_path = os.path.join(self._user_data_dir, "last_project.json")
        self._view_state_path = os.path.join(self._user_data_dir, 'last_view.json')
        self._window_state_path = os.path.join(self._user_data_dir, 'last_window_state.bin')
        # 迁移旧版根目录文件（兼容之前版本）
        self._migrate_legacy_state_files()
        # 用户项目存放目录 (pipeline json)
        self._projects_dir = os.path.join(self._user_data_dir, 'projects')
        try:
            os.makedirs(self._projects_dir, exist_ok=True)
        except Exception:
            pass
        # 编辑相关动作集合（用于锁定时禁用）在菜单初始化时填充
        self._edit_related_actions: list[QAction] = []

        # 先加载用户设置(语言/运行间隔)以便后续 UI 初始化直接使用正确语言
        self._load_user_settings()
        # 初始化UI组件 & 菜单/工具栏/状态栏（此时语言模式已就位）
        self._init_ui()
        self._init_menu()
        self._init_toolbar()
        self._init_statusbar()
        self._connect_signals()
        # 延迟热加载上次项目，避免启动时卡顿（showEvent 中 singleShot 调用）
        self._auto_load_scheduled = False
        # 状态栏扩展：系统信息 & 性能信息
        self._sysinfo_timer = QTimer(self)
        self._metrics_timer = QTimer(self)
        self._sysinfo_timer.setInterval(1000)
        self._metrics_timer.setInterval(1500)
        self._sysinfo_timer.timeout.connect(self._update_system_info)
        self._metrics_timer.timeout.connect(self._refresh_executor_metrics)
        self._gpu_handle = None
        self._gpu_handles = []
        self._gpu_available = False
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
        # GPU 初始化完成后恢复窗口状态
        self._restore_window_state()
        self._sysinfo_enabled = True
        self._last_metrics_snapshot = {}
        # 启动定时器（可通过菜单关闭）
        self._sysinfo_timer.start(); self._metrics_timer.start()
        # 预热进度条持久化状态：达到 100% 后保持绿色直到项目切换
        self._warmup_completed_persist: bool = False
        self._warmup_bar_last_style: str = 'inactive'
    # （语言与运行间隔已在构造早期加载）

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
        # 让左侧面板可调节但保持较小初始占比
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        # 初始尺寸: 使用当前主窗口宽度比估算, 避免硬编码
        try:
            total_w = self.width()
            left_w = max(240, int(total_w * 0.22))
            splitter.setSizes([left_w, total_w - left_w])
        except Exception:
            splitter.setSizes([280, 920])
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
        # 菜单在 _init_menu 中创建
        
    def _init_menu(self):
        """初始化菜单栏 (首次) -> 调用重建逻辑"""
        self._rebuild_menus()

    def _rebuild_menus(self):
        """根据当前语言模式重建整套菜单。"""
        menubar = self.menuBar()
        menubar.clear()
        self._edit_related_actions = []

        def L(cn: str, en: str):
            mode = get_language_mode()
            if mode == 'zh':
                return cn
            if mode == 'en':
                return en
            return f"{cn} {en}"

        # 文件菜单
        file_menu = menubar.addMenu(L('文件','File'))
        new_action = QAction(L('新建项目','New Project'), self)
        new_action.setShortcut(QKeySequence(QKeySequence.StandardKey.New))
        new_action.triggered.connect(self._new_project); file_menu.addAction(new_action)
        open_action = QAction(L('打开项目','Open Project'), self)
        open_action.setShortcut(QKeySequence(QKeySequence.StandardKey.Open))
        open_action.triggered.connect(self._open_project); file_menu.addAction(open_action)
        file_menu.addSeparator()
        save_action = QAction(L('保存流程','Save Pipeline'), self)
        save_action.setShortcut(QKeySequence(QKeySequence.StandardKey.Save))
        save_action.triggered.connect(self._save_project); file_menu.addAction(save_action)
        save_as_action = QAction(L('另存为','Save As'), self)
        save_as_action.setShortcut(QKeySequence('Ctrl+Shift+S'))
        save_as_action.triggered.connect(self._save_project_as); file_menu.addAction(save_as_action)
        load_action = QAction(L('加载流程','Load Pipeline'), self)
        load_action.setShortcut(QKeySequence('Ctrl+Shift+O'))
        load_action.triggered.connect(self._open_project); file_menu.addAction(load_action)
        file_menu.addSeparator()
        exit_action = QAction(L('退出','Exit'), self)
        exit_action.setShortcut(QKeySequence(QKeySequence.StandardKey.Quit))
        exit_action.triggered.connect(self.close); file_menu.addAction(exit_action)

        # 编辑菜单
        edit_menu = menubar.addMenu(L('编辑','Edit'))
        undo_action = QAction(L('撤销','Undo'), self); undo_action.setShortcut(QKeySequence(QKeySequence.StandardKey.Undo)); undo_action.triggered.connect(self._undo); edit_menu.addAction(undo_action)
        redo_action = QAction(L('重做','Redo'), self); redo_action.setShortcut(QKeySequence(QKeySequence.StandardKey.Redo)); redo_action.triggered.connect(self._redo); edit_menu.addAction(redo_action)
        edit_menu.addSeparator()
        copy_action = QAction(L('复制','Copy'), self); copy_action.setShortcut(QKeySequence(QKeySequence.StandardKey.Copy)); copy_action.triggered.connect(self._copy); edit_menu.addAction(copy_action)
        paste_action = QAction(L('粘贴','Paste'), self); paste_action.setShortcut(QKeySequence(QKeySequence.StandardKey.Paste)); paste_action.triggered.connect(self._paste); edit_menu.addAction(paste_action)
        delete_action = QAction(L('删除','Delete'), self); delete_action.setShortcut(QKeySequence('Delete')); delete_action.triggered.connect(self._delete); edit_menu.addAction(delete_action)
        duplicate_action = QAction(L('复制并偏移','Duplicate Offset'), self); duplicate_action.setShortcut(QKeySequence('Ctrl+D')); duplicate_action.triggered.connect(self._duplicate_selection); edit_menu.addAction(duplicate_action)

        # 运行菜单
        run_menu = menubar.addMenu(L('运行','Run'))
        run_action = QAction(L('运行流程','Run Pipeline'), self); run_action.setShortcut(QKeySequence('F5')); run_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut); run_action.triggered.connect(self._run_pipeline); run_menu.addAction(run_action)
        pause_action = QAction(L('暂停','Pause'), self); pause_action.setShortcut(QKeySequence('F6')); pause_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut); pause_action.triggered.connect(self._pause_pipeline); run_menu.addAction(pause_action)
        resume_action = QAction(L('恢复','Resume'), self); resume_action.setShortcut(QKeySequence('F7')); resume_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut); resume_action.triggered.connect(self._resume_pipeline); run_menu.addAction(resume_action)
        stop_action = QAction(L('停止运行','Stop'), self); stop_action.setShortcut(QKeySequence('F8')); stop_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut); stop_action.triggered.connect(self._stop_pipeline); run_menu.addAction(stop_action)
        run_once_action = QAction(L('运行一次','Run Once'), self); run_once_action.setShortcut(QKeySequence('F9')); run_once_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut); run_once_action.triggered.connect(self._run_pipeline_once); run_menu.addAction(run_once_action)

        # 监控菜单
        monitor_menu = menubar.addMenu(L('监控','Monitor'))
        reset_metrics_action = QAction(L('重置性能指标','Reset Metrics'), self); reset_metrics_action.triggered.connect(self.reset_executor_metrics); monitor_menu.addAction(reset_metrics_action)
        toggle_sysinfo_action = QAction(L('系统信息轮询','System Info Poll'), self); toggle_sysinfo_action.setCheckable(True); toggle_sysinfo_action.setChecked(getattr(self, '_sysinfo_enabled', True)); toggle_sysinfo_action.triggered.connect(self._toggle_system_info); monitor_menu.addAction(toggle_sysinfo_action)
        grid_toggle_action = QAction(L('切换网格显示','Toggle Grid'), self); grid_toggle_action.triggered.connect(lambda: self.flow_canvas.toggle_grid()); monitor_menu.addAction(grid_toggle_action)
        # 自动预热
        if not hasattr(self, '_auto_preheat_enabled'):
            self._auto_preheat_enabled = True
        auto_preheat_action = QAction(L('自动YOLO预热','Auto YOLO Warmup'), self)
        auto_preheat_action.setCheckable(True)
        auto_preheat_action.setChecked(self._auto_preheat_enabled)
        def _toggle_preheat(checked: bool):
            self._auto_preheat_enabled = bool(checked)
            if hasattr(self, 'statusbar'):
                msg = L('自动YOLO预热','Auto YOLO Warmup') + (L('已启用',' Enabled') if checked else L('已关闭',' Disabled'))
                self.statusbar.showMessage(msg, 3000)
        auto_preheat_action.toggled.connect(_toggle_preheat)
        monitor_menu.addAction(auto_preheat_action)
        # 设置运行间隔
        set_interval_action = QAction(L('设置运行间隔(ms)','Set Interval (ms)'), self)
        def _set_interval():
            from PyQt6.QtWidgets import QInputDialog
            cur_ms = int(self._feeder_interval_sec * 1000)
            val, ok = QInputDialog.getInt(self, L('运行间隔','Run Interval'), L('循环投递空输入触发执行的间隔 (毫秒):','Interval for pushing empty input (ms):'), cur_ms, 50, 10000, 50)
            if not ok:
                return
            self._feeder_interval_sec = max(0.05, val/1000.0)
            self._post_status(L('已设置运行间隔:','Set interval:')+f' {val}ms', 3000)
            self._persist_user_settings()
        set_interval_action.triggered.connect(_set_interval)
        monitor_menu.addAction(set_interval_action)
        # 刷新视觉
        refresh_view_act = QAction(L('刷新所有模块视觉','Refresh Module Visuals'), self)
        def _do_refresh_all():
            try:
                for m in getattr(self.flow_canvas, 'modules', []):
                    if hasattr(m, 'refresh_visual'):
                        m.refresh_visual()
                self.statusbar.showMessage(L('已刷新所有模块视觉','All module visuals refreshed'), 3000)
            except Exception as e:
                self.statusbar.showMessage(L('刷新失败:','Refresh failed:')+f'{e}', 5000)
        refresh_view_act.triggered.connect(_do_refresh_all)
        monitor_menu.addAction(refresh_view_act)

        # 视图菜单
        view_menu = menubar.addMenu(L('视图','View'))
        theme_toggle_action = QAction(L('黑白反转主题','Invert Theme'), self); theme_toggle_action.setCheckable(True); theme_toggle_action.setChecked(getattr(self, '_theme_inverted', False)); theme_toggle_action.triggered.connect(lambda checked: self._toggle_invert_theme(checked)); view_menu.addAction(theme_toggle_action)
        if hasattr(self, 'property_dock'):
            toggle_prop_act = QAction(L('属性面板','Property Panel'), self)
            toggle_prop_act.setCheckable(True)
            toggle_prop_act.setChecked(self.property_dock.isVisible())
            def _sync_prop_vis(checked: bool):
                try:
                    if checked:
                        self.property_dock.show(); self.property_dock.raise_()
                    else:
                        self.property_dock.hide()
                    if hasattr(self, 'statusbar'):
                        self.statusbar.showMessage(L('属性面板已','Property panel ')+(L('显示','shown') if checked else L('隐藏','hidden')), 2500)
                except Exception as e:
                    if hasattr(self, 'statusbar'):
                        self.statusbar.showMessage(L('属性面板切换失败:','Property panel toggle failed:')+f'{e}', 4000)
            toggle_prop_act.toggled.connect(_sync_prop_vis)
            def _on_dock_visibility_changed(vis: bool):
                try:
                    if toggle_prop_act.isChecked() != vis:
                        toggle_prop_act.setChecked(vis)
                except Exception:
                    pass
            try:
                self.property_dock.visibilityChanged.connect(_on_dock_visibility_changed)
            except Exception:
                pass
            view_menu.addAction(toggle_prop_act)

        # 帮助菜单
        help_menu = menubar.addMenu(L('帮助','Help'))
        about_action = QAction(L('关于','About'), self); about_action.triggered.connect(self._show_about); help_menu.addAction(about_action)

        # 语言菜单（简单显示，当前菜单本身已在 rebuild 前建立, 这里仅提供切换入口）
        lang_menu = menubar.addMenu(L('语言','Language'))
        def _lang_act(text_cn, text_en, mode):
            act = QAction(L(text_cn, text_en), self)
            act.setCheckable(True)
            if get_language_mode() == mode:
                act.setChecked(True)
            def _apply():
                if act.isChecked():
                    set_language_mode(mode)
                    # 递归重建
                    self._rebuild_menus()
                    # 重建工具栏
                    try:
                        self._build_toolbar()
                    except Exception:
                        pass
                    # 刷新工具箱与模块标题
                    try:
                        self.dock_panel.module_toolbox.refresh_modules()  # type: ignore
                    except Exception:
                        pass
                    try:
                        if hasattr(self.flow_canvas, 'modules'):
                            for m in getattr(self.flow_canvas, 'modules', []):
                                # 使用新的标题刷新方法以保证居中与翻译一致
                                if hasattr(m, 'refresh_title_language'):
                                    m.refresh_title_language()
                                elif hasattr(m,'text_item') and hasattr(m,'module_type'):
                                    # 回退逻辑
                                    m.text_item.setPlainText(self._translate_module_type(m.module_type))
                                    if hasattr(m,'_center_title'):
                                        m._center_title()
                    except Exception:
                        pass
                    self._persist_user_settings()
            act.triggered.connect(_apply)
            lang_menu.addAction(act)
        _lang_act('中文','Chinese','zh')
        _lang_act('英文','English','en')
        _lang_act('中英','Both','both')

        # 收集编辑相关动作
        self._edit_related_actions.extend([
            undo_action, redo_action, copy_action, paste_action, delete_action, duplicate_action,
        ])

        # （已移除旧的重复语言菜单块，使用上方统一的 lang_menu 逻辑）

    def _init_toolbar(self):
        """初始化工具栏 (首次) 并存引用; 后续语言切换可重建"""
        self._build_toolbar()

    def _build_toolbar(self):
        # 若已存在旧 toolbar(s) 移除重建，避免重复按钮累计
        try:
            # findChildren 以确保全部清理（极端情况下可能出现多个残留）
            for tb in self.findChildren(QToolBar):
                if tb.objectName() == 'MainToolBar':
                    self.removeToolBar(tb)
        except Exception:
            pass
        # 重置编辑相关动作集合（仅保留语言菜单重建之前填充的基础编辑动作）
        base_actions = []
        for act in getattr(self, '_edit_related_actions', []):
            base_actions.append(act)
        self._edit_related_actions = base_actions
        from app.utils.i18n import get_language_mode
        def L(cn: str, en: str):
            mode = get_language_mode()
            if mode == 'zh': return cn
            if mode == 'en': return en
            return f"{cn} {en}"
        toolbar = self.addToolBar(L('主工具栏','Main Toolbar'))
        toolbar.setObjectName('MainToolBar')
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        run_act = QAction(L('运行','Run')+' F5', self); run_act.triggered.connect(self._run_pipeline)
        pause_act = QAction(L('暂停','Pause')+' F6', self); pause_act.triggered.connect(self._pause_pipeline)
        resume_act = QAction(L('恢复','Resume')+' F7', self); resume_act.triggered.connect(self._resume_pipeline)
        stop_act = QAction(L('停止','Stop')+' F8', self); stop_act.triggered.connect(self._stop_pipeline)
        run_once_act = QAction(L('单次','Once')+' F9', self); run_once_act.triggered.connect(self._run_pipeline_once)
        inject_act = QAction(L('注入数据','Inject Data'), self); inject_act.triggered.connect(self._inject_data)
        edit_act = QAction(L('编辑模块','Edit Module'), self); edit_act.triggered.connect(self._edit_selected_module)
        toolbar.addActions([run_act, pause_act, resume_act, stop_act, run_once_act, inject_act, edit_act])
        # 画布锁定切换：锁定后禁止任何编辑（添加/删除/拖动/连线），仍可运行流程。
        self._lock_act = QAction(L('锁定画布','Lock Canvas'), self)
        self._lock_act.setCheckable(True)
        self._lock_act.setToolTip(L('锁定后禁止编辑，只能查看和运行','When locked: view/run only, no editing'))
        def _toggle_lock(checked: bool):
            if hasattr(self, 'flow_canvas'):
                self.flow_canvas.set_locked(checked)
            for act in getattr(self, '_edit_related_actions', []):
                act.setEnabled(not checked)
            if hasattr(self, 'dock_panel'):
                self.dock_panel.setEnabled(not checked)
            if hasattr(self, 'property_panel'):
                self.property_panel.setEnabled(not checked)
            if hasattr(self, 'statusbar'):
                self.statusbar.showMessage(L('画布已锁定','Canvas locked') if checked else L('画布已解锁','Canvas unlocked'))
        self._lock_act.toggled.connect(_toggle_lock)
        toolbar.addAction(self._lock_act)
        # 工具栏中的编辑相关动作加入集合
        self._edit_related_actions.extend([inject_act, edit_act])
        
    def _init_statusbar(self):
        """初始化状态栏"""
        self.statusbar = self.statusBar()
        self.statusbar.showMessage(L('就绪','Ready'))
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
        self.sysinfo_label = QLabel(L("CPU: --% | GPU: -- | 磁盘: --","CPU: --% | GPU: -- | Disk: --"))
        self.sysinfo_label.setStyleSheet("QLabel { color: #555; padding-left:6px; }")
        self.metrics_label = QLabel(L("执行:0 | 平均:0ms | 最慢:-","Exec:0 | Avg:0ms | Slow:-"))
        self.metrics_label.setStyleSheet("QLabel { color:#444; padding-left:12px; }")
        # YOLO 预热进度条（持久化完成）
        self.warmup_bar = QProgressBar()
        self.warmup_bar.setRange(0,100)
        self.warmup_bar.setFixedWidth(100)
        self.warmup_bar.setTextVisible(False)
        self._apply_warmup_bar_style('inactive')
        self.warmup_bar.setToolTip("YOLO 模型预热进度 (全部模块平均百分比) | 绿色=完成 | 紫色=进行中 | 灰色=未开始")
        # 添加到状态栏
        self.statusbar.addPermanentWidget(self.metrics_label)
        self.statusbar.addPermanentWidget(QLabel(L("CPU","CPU")))
        self.statusbar.addPermanentWidget(self.cpu_bar)
        self.statusbar.addPermanentWidget(QLabel(L("GPU","GPU")))
        self.statusbar.addPermanentWidget(self.gpu_bar)
        self.statusbar.addPermanentWidget(QLabel(L("磁盘","Disk")))
        self.statusbar.addPermanentWidget(self.disk_bar)
        self.statusbar.addPermanentWidget(QLabel(L("预热","Warmup")))
        self.statusbar.addPermanentWidget(self.warmup_bar)
        self.statusbar.addPermanentWidget(self.sysinfo_label)
        
    def _connect_signals(self):
        """连接信号和槽"""
        # 连接画布和停靠面板的信号
        self.dock_panel.module_selected.connect(self.flow_canvas.add_module)
        self.flow_canvas.module_selected.connect(self._on_canvas_module_selected)
        # 初始化主题状态
        self._theme_inverted = False
        self._apply_stylesheet(False)
        # 尝试恢复之前的画布视图状态
        self._restore_view_state_if_exists()

    def _restore_view_state_if_exists(self):
        """延迟恢复画布视图，避免自动加载流程前场景尺寸不稳定导致偏移"""
        if not hasattr(self, 'flow_canvas'):
            return
        path = getattr(self, '_view_state_path', None)
        if not path or not os.path.isfile(path):
            return
        from PyQt6.QtCore import QTimer
        try:
            with open(path, 'r', encoding='utf-8') as f:
                state = json.load(f)
        except Exception as e:
            print(f"读取视图状态失败: {e}")
            return
        delay = 650 if getattr(self, '_auto_load_scheduled', False) else 250
        def _do_restore():
            try:
                if hasattr(self.flow_canvas, 'import_view_state'):
                    self.flow_canvas.import_view_state(state)
                dark_flag = state.get('dark_theme')
                if isinstance(dark_flag, bool) and dark_flag != self._theme_inverted:
                    self._toggle_invert_theme(dark_flag)
            except Exception as ie:
                print(f"视图状态导入异常: {ie}")
        QTimer.singleShot(delay, _do_restore)

    # ---------- 主题样式支持 ----------
    def _apply_stylesheet(self, invert: bool):
        base_path = os.path.join(os.getcwd(), 'resources', 'styles')
        fname = 'invert.qss' if invert else 'main.qss'
        path = os.path.join(base_path, fname)
        if not os.path.isfile(path):
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                self.setStyleSheet(f.read())
        except Exception:
            pass

    def _toggle_invert_theme(self, checked: bool):
        self._theme_inverted = checked
        self._apply_stylesheet(checked)
        # 通知画布更新网格配色
        if hasattr(self, 'flow_canvas') and hasattr(self.flow_canvas, 'set_dark_theme'):
            self.flow_canvas.set_dark_theme(checked)
        if hasattr(self, 'statusbar'):
            self.statusbar.showMessage(L('已启用反转主题','Inverted theme on') if checked else L('已恢复默认主题','Theme restored'))
        
    # 菜单动作槽函数
    def _new_project(self):
        """新建项目"""
        self.flow_canvas.clear()
        self.statusbar.showMessage(L('新建项目','New project'))
        self._reset_warmup_state()
        
    def _open_project(self):
        """加载流程文件"""
        start_dir = self._projects_dir if os.path.isdir(self._projects_dir) else os.getcwd()
        path, _ = QFileDialog.getOpenFileName(self, '加载流程', start_dir, 'Pipeline (*.json);;All (*)')
        if not path:
            return
        # 打开项目前重置预热状态
        self._reset_warmup_state()
        ok = self.flow_canvas.load_from_file(path)
        if ok:
            self.statusbar.showMessage(L('加载成功:','Loaded:')+f' {path}')
            if os.path.basename(path).lower() == 'sample.json':
                self._current_pipeline_path = None
                self.statusbar.showMessage(L('加载模板 sample.json，保存将提示新文件名','Template sample.json loaded, Save will ask new name'))
            else:
                self._current_pipeline_path = path
            self._persist_last_project(path)
        else:
            self.statusbar.showMessage(L('加载失败','Load failed'))
        
    def _save_project(self):
        """保存流程到当前文件；若无当前路径则提示另存为。"""
        # 节流: 避免短时间重复触发 Ctrl+S 导致磁盘频繁写入
        now = time.time()*1000.0
        if (now - self._last_save_ts) < self._save_min_interval_ms:
            self.statusbar.showMessage(L('保存过于频繁，已忽略','Save too frequent, ignored'))
            return
        self._last_save_ts = now
        if (not self._current_pipeline_path) or (os.path.basename(self._current_pipeline_path).lower() == 'sample.json'):
            self._save_project_as()
            return
        ok = self.flow_canvas.save_to_file(self._current_pipeline_path)
        if ok:
            self.statusbar.showMessage(L('保存成功:','Saved:')+f' {self._current_pipeline_path}')
            self._persist_last_project(self._current_pipeline_path)
        else:
            self.statusbar.showMessage(L('保存失败','Save failed'))
        
    def _save_project_as(self):
        # 为首次保存提供一个默认建议文件名而不是 sample.json
        import time as _time
        base_dir = self._projects_dir if os.path.isdir(self._projects_dir) else os.getcwd()
        if self._current_pipeline_path and os.path.isfile(self._current_pipeline_path):
            suggested = self._current_pipeline_path
        else:
            ts = _time.strftime('%Y%m%d_%H%M%S')
            suggested = os.path.join(base_dir, f'pipeline_{ts}.json')
        path, _ = QFileDialog.getSaveFileName(self, '另存为流程', suggested, 'Pipeline (*.json);;All (*)')
        if not path:
            return
        ok = self.flow_canvas.save_to_file(path)
        if ok:
            self._current_pipeline_path = path
            self._last_save_ts = time.time()*1000.0  # 更新节流时间戳
            self._persist_last_project(path)
        self.statusbar.showMessage(L('另存为成功','Save As success') if ok else L('另存为失败','Save As failed'))
        
    def _undo(self):
        self.flow_canvas.undo()
        self.statusbar.showMessage(L('撤销完成','Undo done'))
        
    def _redo(self):
        self.flow_canvas.redo()
        self.statusbar.showMessage(L('重做完成','Redo done'))
        
    def _copy(self):
        self.flow_canvas.copy_selection()
        self.statusbar.showMessage(L('已复制','Copied'))
        
    def _paste(self):
        self.flow_canvas.paste_selection()
        self.statusbar.showMessage(L('已粘贴','Pasted'))
        
    def _delete(self):
        self.flow_canvas.delete_selection()
        self.statusbar.showMessage(L('已删除','Deleted'))
    
    def _duplicate_selection(self):
        self.flow_canvas.duplicate_selection()
        self.statusbar.showMessage('已复制并粘贴')

    def _apply_properties(self):
        if hasattr(self.property_panel, 'apply_current'):
            self.property_panel.apply_current()
            self.statusbar.showMessage(L('属性已应用','Properties applied'))
    
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
            time.sleep(self._feeder_interval_sec if self._feeder_interval_sec > 0 else 0.01)

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
        """窗口关闭事件：保存视图状态与项目路径"""
        try:
            # 保存当前项目路径 (已有持久化逻辑)
            if self._current_pipeline_path:
                self._persist_last_project(self._current_pipeline_path)
            # 保存画布视图状态
            if hasattr(self, 'flow_canvas'):
                state = self.flow_canvas.export_view_state()
                with open(self._view_state_path, 'w', encoding='utf-8') as vf:
                    json.dump(state, vf, ensure_ascii=False, indent=2)
            # 保存窗口几何与布局
            try:
                geo = self.saveGeometry()
                st = self.saveState()
                with open(self._window_state_path, 'wb') as wf:
                    wf.write(len(geo).to_bytes(4, 'little'))
                    wf.write(geo)
                    wf.write(len(st).to_bytes(4, 'little'))
                    wf.write(st)
            except Exception as e2:
                print(f"保存窗口状态失败: {e2}")
        except Exception as e:
            print(f"关闭时保存视图状态失败: {e}")
        event.accept()

    def _migrate_legacy_state_files(self):
        """将旧版本根目录下的状态文件移动到 user_data 目录"""
        legacy_files = [
            ('last_project.json', self._last_project_meta_path),
            ('last_view.json', self._view_state_path),
            ('last_window_state.bin', self._window_state_path)
        ]
        for fname, new_path in legacy_files:
            old_path = os.path.join(os.getcwd(), fname)
            try:
                if os.path.isfile(old_path) and not os.path.isfile(new_path):
                    # 尝试迁移
                    with open(old_path, 'rb') as rf:
                        data = rf.read()
                    with open(new_path, 'wb') as wf:
                        wf.write(data)
                    os.remove(old_path)
            except Exception as e:
                print(f"迁移文件 {fname} 失败: {e}")

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
        # GPU 多卡信息 / NVML 或 torch 回退
        if self._gpu_available and getattr(self, '_pynvml', None) and self._gpu_handles:
            segments = []
            gpu_util_values = []
            try:
                for idx, h in enumerate(self._gpu_handles):
                    try:
                        mem_info = self._pynvml.nvmlDeviceGetMemoryInfo(h)
                        util_info = self._pynvml.nvmlDeviceGetUtilizationRates(h)
                        used_mb = mem_info.used / 1024**2
                        total_mb = mem_info.total / 1024**2
                        mem_percent = (mem_info.used / mem_info.total) * 100.0 if mem_info.total else 0.0
                        gpu_util_values.append(util_info.gpu)
                        segments.append(f"GPU{idx}:{used_mb:.0f}/{total_mb:.0f}MB {mem_percent:.0f}% util {util_info.gpu}%")
                    except Exception:
                        segments.append(f"GPU{idx}:n/a")
                gpu_txt = ' | '.join(segments)
                if gpu_util_values:
                    gpu_bar_percent = sum(gpu_util_values) / len(gpu_util_values)  # 平均核心利用率
                else:
                    gpu_bar_percent = 0.0
            except Exception:
                gpu_bar_percent = None
        else:
            try:
                import torch
                if torch.cuda.is_available():
                    props = torch.cuda.get_device_properties(0)
                    total_mb = props.total_memory / 1024**2
                    # 优先 reserved (更接近实际占用)，否则 allocated
                    reserved = torch.cuda.memory_reserved(0) / 1024**2 if hasattr(torch.cuda, 'memory_reserved') else 0.0
                    allocated = torch.cuda.memory_allocated(0) / 1024**2
                    used_mb = reserved if reserved > 0 else allocated
                    mem_percent = (used_mb/total_mb)*100.0 if total_mb else 0.0
                    name = torch.cuda.get_device_name(0)
                    gpu_txt = f"{name} {used_mb:.0f}/{total_mb:.0f}MB {mem_percent:.0f}%"
                    gpu_bar_percent = mem_percent  # 回退时用显存百分比
                else:
                    gpu_bar_percent = None
            except Exception:
                gpu_bar_percent = None
        # 磁盘
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
        # 更新显示
        if cpu_percent is not None:
            self.cpu_bar.setValue(int(cpu_percent))
        else:
            self.cpu_bar.setValue(0)
        if gpu_bar_percent is not None:
            show_val = int(gpu_bar_percent if gpu_bar_percent >= 1 else (1 if gpu_bar_percent > 0 else 0))
            self.gpu_bar.setValue(show_val); self.gpu_bar.setEnabled(True)
        else:
            self.gpu_bar.setValue(0); self.gpu_bar.setEnabled(False)
        if disk_percent is not None:
            self.disk_bar.setValue(int(disk_percent)); self.disk_bar.setEnabled(True)
        else:
            self.disk_bar.setValue(0); self.disk_bar.setEnabled(False)
        self.sysinfo_label.setText(f"CPU: {cpu_txt} | GPU: {gpu_txt} | Disk: {disk_txt}")
        # 更新 YOLO 预热进度条
        self._update_warmup_bar()

    def _update_warmup_bar(self):
        """更新 YOLO 预热进度条: 紫色=进行中, 绿色=全部完成(持久化), 灰色=未开始或无 YOLO."""
        # 若已持久化完成：保持绿色，除非画布不再有 YOLO 模块
        if self._warmup_completed_persist:
            try:
                modules = getattr(self.flow_canvas, 'modules', [])
            except Exception:
                modules = []
            has_yolo = False
            for m in modules:
                ref = getattr(m, 'module_ref', None)
                if not ref:
                    continue
                try:
                    caps = getattr(ref, 'CAPABILITIES', None)
                    if caps and 'yolo' in getattr(caps, 'resource_tags', []):
                        has_yolo = True; break
                except Exception:
                    pass
            if has_yolo:
                if self._warmup_bar_last_style != 'completed':
                    self._apply_warmup_bar_style('completed')
                self.warmup_bar.setEnabled(True)
                self.warmup_bar.setValue(100)
                return
            else:
                # 无 YOLO 模块 → 重置
                self._reset_warmup_state()
        # 实时统计
        try:
            modules = getattr(self.flow_canvas, 'modules', [])
        except Exception:
            modules = []
        total_yolo = 0
        active_count = 0
        progresses = []
        all_done = True
        for m in modules:
            ref = getattr(m, 'module_ref', None)
            if not ref:
                continue
            try:
                caps = getattr(ref, 'CAPABILITIES', None)
                if not (caps and 'yolo' in getattr(caps, 'resource_tags', [])):
                    continue
                total_yolo += 1
                warming = getattr(ref, '_warming', False)
                done = getattr(ref, '_warmup_done', False)
                cfg = getattr(ref, 'config', {}) if isinstance(getattr(ref, 'config', {}), dict) else {}
                total_iter = int(cfg.get('warmup_iterations', 0))
                completed_iter = int(getattr(ref, '_warmup_iters_completed', 0))
                mod_complete = bool(done or (total_iter == 0 and not warming))
                if not mod_complete:
                    all_done = False
                if warming and not done and total_iter > 0:
                    active_count += 1
                    pct = max(0.0, min(100.0, (completed_iter / total_iter) * 100.0))
                    progresses.append(pct)
            except Exception:
                pass
        if total_yolo == 0:
            self.warmup_bar.setValue(0)
            self.warmup_bar.setEnabled(False)
            if self._warmup_bar_last_style != 'inactive':
                self._apply_warmup_bar_style('inactive')
            return
        if active_count > 0 and progresses:
            avg_pct = sum(progresses)/len(progresses)
            self.warmup_bar.setEnabled(True)
            self.warmup_bar.setValue(int(avg_pct))
            if self._warmup_bar_last_style != 'active':
                self._apply_warmup_bar_style('active')
            detail = ', '.join(f"{int(p)}%" for p in progresses)
            self.warmup_bar.setToolTip(f"YOLO 预热进行中: {active_count}/{total_yolo} | 平均 {avg_pct:.1f}% | 详情 [{detail}]")
        else:
            if all_done:
                self._warmup_completed_persist = True
                self.warmup_bar.setEnabled(True)
                self.warmup_bar.setValue(100)
                if self._warmup_bar_last_style != 'completed':
                    self._apply_warmup_bar_style('completed')
                self.warmup_bar.setToolTip(f"YOLO 预热已完成: {total_yolo} 个模块")
            else:
                self.warmup_bar.setEnabled(False)
                self.warmup_bar.setValue(0)
                if self._warmup_bar_last_style != 'inactive':
                    self._apply_warmup_bar_style('inactive')
                self.warmup_bar.setToolTip("YOLO 预热未开始或等待首次推理触发")

    def _apply_warmup_bar_style(self, mode: str):
        """设置预热进度条样式: inactive(灰), active(紫), completed(绿)."""
        styles = {
            'inactive': "QProgressBar { border:1px solid #bbb; background:#eee; } QProgressBar::chunk { background:#bdbdbd; }",
            'active': "QProgressBar { border:1px solid #bbb; background:#eee; } QProgressBar::chunk { background:#9c27b0; }",
            'completed': "QProgressBar { border:1px solid #bbb; background:#eee; } QProgressBar::chunk { background:#4caf50; }",
        }
        self.warmup_bar.setStyleSheet(styles.get(mode, styles['inactive']))
        self._warmup_bar_last_style = mode

    def _reset_warmup_state(self):
        """项目切换时重置预热持久化状态."""
        self._warmup_completed_persist = False
        if hasattr(self, 'warmup_bar'):
            self.warmup_bar.setValue(0)
            self.warmup_bar.setEnabled(False)
            self._apply_warmup_bar_style('inactive')
            self.warmup_bar.setToolTip("YOLO 模型预热进度 (全部模块平均百分比) | 绿色=完成 | 紫色=进行中 | 灰色=未开始")

    # ---------- 用户设置持久化 ----------
    def _load_user_settings(self):
        """加载用户设置 (运行间隔等); 若文件不存在或格式错误则使用默认。"""
        try:
            if not os.path.isfile(self._settings_path):
                return
            with open(self._settings_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                run_ms = data.get('run_interval_ms')
                if isinstance(run_ms, (int, float)) and 50 <= run_ms <= 10000:
                    self._feeder_interval_sec = max(0.05, run_ms/1000.0)
                lang = data.get('language_mode')
                if isinstance(lang, str) and lang in ('zh','en','both'):
                    set_language_mode(lang)
        except Exception as e:
            # 读取失败忽略，保持默认
            print(f"加载用户设置失败: {e}")

    def _persist_user_settings(self):
        """保存当前运行间隔等设置到 settings.json。"""
        try:
            data = {
                'run_interval_ms': int(self._feeder_interval_sec * 1000),
                'language_mode': get_language_mode(),
                'ts': time.time()
            }
            with open(self._settings_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            if hasattr(self, 'statusbar'):
                self.statusbar.showMessage(f'保存设置失败: {e}', 3000)

    def _translate_module_type(self, module_type: str) -> str:
        # 当前简单使用 translate; 将来可针对模块别名单独表
        try:
            from app.utils.i18n import translate as _t
            return _t(module_type)
        except Exception:
            return module_type

    def _restore_window_state(self):
        """恢复窗口几何和停靠布局 (若之前保存)."""
        try:
            if not os.path.isfile(self._window_state_path):
                return
            with open(self._window_state_path, 'rb') as rf:
                geo_len = int.from_bytes(rf.read(4), 'little')
                geo = rf.read(geo_len)
                st_len = int.from_bytes(rf.read(4), 'little')
                st = rf.read(st_len)
            self.restoreGeometry(geo)
            self.restoreState(st)
        except Exception as e:
            print(f"恢复窗口状态失败: {e}")

    def _toggle_system_info(self, checked: bool):
        """开启/关闭系统信息与性能指标定时刷新。"""
        self._sysinfo_enabled = bool(checked)
        if self._sysinfo_enabled:
            try:
                self._sysinfo_timer.start(); self._metrics_timer.start()
            except Exception:
                pass
            if hasattr(self, 'statusbar'):
                self.statusbar.showMessage('系统信息轮询已开启', 2500)
        else:
            try:
                self._sysinfo_timer.stop(); self._metrics_timer.stop()
            except Exception:
                pass
            if hasattr(self, 'statusbar'):
                self.statusbar.showMessage('系统信息轮询已关闭', 2500)

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
        if self._current_pipeline_path:
            return
        if not os.path.exists(self._last_project_meta_path):
            return
        try:
            with open(self._last_project_meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            recent_path = meta.get('pipeline_path')
            if recent_path and os.path.exists(recent_path) and recent_path.lower().endswith('.json'):
                # 项目切换时重置预热持久化状态
                self._reset_warmup_state()
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
                from PyQt6.QtCore import QTimer as _QT
                _QT.singleShot(1200, self._auto_preheat_models)
        except Exception as e:
            self.statusbar.showMessage(f'自动加载异常: {e}')

    def _auto_preheat_models(self):
        """遍历画布中模块, 对 YOLO 类型模块执行 warmup_async 降低首帧卡顿."""
        if not getattr(self, '_auto_preheat_enabled', True):
            return
        try:
            modules = getattr(self.flow_canvas, 'modules', [])
        except Exception:
            modules = []
        targets = []
        for m in modules:
            ref = getattr(m, 'module_ref', None)
            if not ref:
                continue
            try:
                caps = getattr(ref, 'CAPABILITIES', None)
                if caps and 'yolo' in getattr(caps, 'resource_tags', []):
                    targets.append(ref)
            except Exception:
                pass
        if not targets:
            return
        def _worker(refs):
            for r in refs:
                try:
                    if hasattr(r, 'warmup_async'):
                        r.warmup_async()
                except Exception:
                    pass
            # 使用线程安全的异步状态更新
            self._post_status(f'YOLO预热已触发: {len(refs)} 个', 4000)
        import threading
        threading.Thread(target=_worker, args=(targets,), daemon=True, name='yolo-preheat-thread').start()

    def _post_status(self, message: str, timeout_ms: int = 3000):
        """线程安全地在主线程更新状态栏消息。"""
        try:
            from PyQt6.QtCore import QTimer, QObject
            # 若当前就在主线程直接调用
            if hasattr(self, 'statusbar'):
                # 使用 singleShot 保证在主事件循环执行（避免子线程直接操作）
                QTimer.singleShot(0, lambda: self.statusbar.showMessage(message, timeout_ms))
        except Exception:
            pass