#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
流程执行器
负责管理和执行整个处理流程，支持顺序和并行执行
"""

import threading
import time
import queue
from typing import Any, Dict, List, Optional, Callable
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, Future
import logging

from .base_module import BaseModule, ModuleStatus
from .interfaces import Connection


class ExecutionMode(Enum):
    """执行模式枚举"""
    SEQUENTIAL = "sequential"   # 顺序执行
    PARALLEL = "parallel"       # 并行执行
    PIPELINE = "pipeline"       # 流水线执行


class PipelineStatus(Enum):
    """流程状态枚举"""
    IDLE = "idle"               # 空闲状态
    RUNNING = "running"         # 运行状态
    PAUSED = "paused"          # 暂停状态
    STOPPING = "stopping"      # 停止中
    STOPPED = "stopped"        # 已停止
    ERROR = "error"            # 错误状态


class PipelineNode:
    """流程节点"""
    
    def __init__(self, module: BaseModule, node_id: str = None):
        self.module = module
        self.node_id = node_id or module.module_id
        self.inputs = {}           # 输入连接
        self.outputs = {}          # 输出连接
        self.predecessors = []     # 前驱节点
        self.successors = []       # 后继节点
        self.execution_time = 0.0  # 执行时间
        self.last_result = None    # 最后执行结果
        
    def add_input(self, input_name: str, source_node: 'PipelineNode', output_name: str):
        """添加输入连接"""
        self.inputs[input_name] = (source_node, output_name)
        if source_node not in self.predecessors:
            self.predecessors.append(source_node)
            
    def add_output(self, output_name: str, target_node: 'PipelineNode', input_name: str):
        """添加输出连接"""
        if output_name not in self.outputs:
            self.outputs[output_name] = []
        self.outputs[output_name].append((target_node, input_name))
        if target_node not in self.successors:
            self.successors.append(target_node)


class PipelineExecutor:
    """
    流程执行器，管理整个处理流程的执行
    支持多种执行模式和复杂的数据流控制
    """
    
    def __init__(self, name: str = "流程执行器"):
        """
        初始化流程执行器
        
        Args:
            name: 执行器名称
        """
        self.name = name
        self.nodes: Dict[str, PipelineNode] = {}
        self.connections: List[Connection] = []  # 规范化连接列表
        self.execution_order: List[str] = []
        
        # 执行状态
        self.status = PipelineStatus.IDLE
        self.execution_mode = ExecutionMode.SEQUENTIAL
        
        # 执行控制
        self.executor_thread = None
        self.thread_pool = None
        self.max_workers = 4
        self.is_running = False
        self.pause_event = threading.Event()
        self.stop_event = threading.Event()
        
        # 数据队列
        self.input_queue = queue.Queue()
        self.output_queue = queue.Queue()
        
        # 回调函数
        self.progress_callbacks: List[Callable] = []
        self.result_callbacks: List[Callable] = []
        self.error_callbacks: List[Callable] = []
        # 模块步骤回调（用于 GUI 高亮：phase = 'start' | 'end'）
        self.module_step_callbacks: List[Callable] = []
        
        # 统计信息
        self.execution_count = 0
        self.total_execution_time = 0.0
        self.error_count = 0
        # 性能指标：{node_id: {'exec_count':int,'total_time':float,'max_time':float,'last_time':float,'avg_time':float}}
        self._perf_stats: Dict[str, Dict[str, float]] = {}
        self._perf_lock = threading.Lock()
        self._metrics_callbacks: List[Callable] = []  # 周期指标回调 (stats_dict, aggregate_dict)
        self._metrics_interval_s = 1.0
        self._metrics_timer_thread = None
        self._metrics_stop = threading.Event()
        
        # 配置
        self.config = {
            "execution_mode": ExecutionMode.SEQUENTIAL.value,
            "max_workers": 4,
            "timeout": 30.0,            # 执行超时时间
            "retry_count": 3,           # 重试次数
            "retry_delay": 1.0,         # 重试延迟
            "enable_monitoring": True,   # 启用监控
            "log_level": "INFO"
        }
        
        # 设置日志
        self.logger = logging.getLogger(f"PipelineExecutor.{id(self)}")
        
    def add_module(self, module: BaseModule, node_id: str = None) -> str:
        """
        添加模块到流程中
        
        Args:
            module: 要添加的模块
            node_id: 节点ID，如果不指定则使用模块ID
            
        Returns:
            节点ID
        """
        node_id = node_id or module.module_id
        
        if node_id in self.nodes:
            raise ValueError(f"节点ID已存在: {node_id}")
            
        node = PipelineNode(module, node_id)
        self.nodes[node_id] = node
        
        self.logger.info(f"添加模块到流程: {module.name} ({node_id})")
        return node_id
        
    def remove_module(self, node_id: str):
        """从流程中移除模块"""
        if node_id not in self.nodes:
            raise ValueError(f"节点不存在: {node_id}")
            
        node = self.nodes[node_id]
        
        # 移除所有连接
        for pred in node.predecessors:
            for outputs in pred.outputs.values():
                outputs[:] = [(target, input_name) for target, input_name in outputs 
                             if target.node_id != node_id]
                             
        for succ in node.successors:
            succ.predecessors[:] = [pred for pred in succ.predecessors 
                                   if pred.node_id != node_id]
            for input_name in list(succ.inputs.keys()):
                source_node, _ = succ.inputs[input_name]
                if source_node.node_id == node_id:
                    del succ.inputs[input_name]
                    
        del self.nodes[node_id]
        self.logger.info(f"从流程中移除模块: {node_id}")
        
    def connect_modules(self, source_id: str, output_name: str, 
                       target_id: str, input_name: str):
        """
        连接两个模块
        
        Args:
            source_id: 源模块ID
            output_name: 输出端口名称
            target_id: 目标模块ID
            input_name: 输入端口名称
        """
        if source_id not in self.nodes:
            raise ValueError(f"源节点不存在: {source_id}")
        if target_id not in self.nodes:
            raise ValueError(f"目标节点不存在: {target_id}")
            
        source_node = self.nodes[source_id]
        target_node = self.nodes[target_id]
        
        source_node.add_output(output_name, target_node, input_name)
        target_node.add_input(input_name, source_node, output_name)
        
        self.logger.info(f"连接模块: {source_id}.{output_name} -> {target_id}.{input_name}")
        self.connections.append(Connection(source_module=source_id,
                                           source_port=output_name,
                                           target_module=target_id,
                                           target_port=input_name))
        
    def disconnect_modules(self, source_id: str, output_name: str,
                          target_id: str, input_name: str):
        """断开模块连接"""
        if source_id not in self.nodes or target_id not in self.nodes:
            return
            
        source_node = self.nodes[source_id]
        target_node = self.nodes[target_id]
        
        # 移除连接
        if output_name in source_node.outputs:
            source_node.outputs[output_name][:] = [
                (target, inp) for target, inp in source_node.outputs[output_name]
                if target.node_id != target_id or inp != input_name
            ]
            
        if input_name in target_node.inputs:
            source, output = target_node.inputs[input_name]
            if source.node_id == source_id and output == output_name:
                del target_node.inputs[input_name]
                
        self.logger.info(f"断开连接: {source_id}.{output_name} -> {target_id}.{input_name}")
        self.connections = [c for c in self.connections if not (
            c.source_module == source_id and c.source_port == output_name and
            c.target_module == target_id and c.target_port == input_name
        )]
        
    def set_execution_mode(self, mode: ExecutionMode):
        """设置执行模式"""
        self.execution_mode = mode
        self.config["execution_mode"] = mode.value
        self.logger.info(f"设置执行模式: {mode.value}")
        
    def start(self, input_data: Dict[str, Any] = None) -> bool:
        """
        启动流程执行
        
        Args:
            input_data: 输入数据
            
        Returns:
            启动成功返回True
        """
        if self.status != PipelineStatus.IDLE:
            self.logger.warning("流程已在运行中")
            return False
            
        try:
            # 验证流程
            if not self._validate_pipeline():
                return False
                
            # 计算执行顺序
            self.execution_order = self._calculate_execution_order()
            if not self.execution_order:
                self.logger.error("无法计算执行顺序，可能存在循环依赖")
                return False
                
            # 初始化所有模块
            for node_id in self.nodes:
                node = self.nodes[node_id]
                if not node.module.start():
                    self.logger.error(f"模块启动失败: {node_id}")
                    return False
                    
            # 设置初始输入数据
            if input_data:
                self.input_queue.put(input_data)
                
            # 启动执行
            self.status = PipelineStatus.RUNNING
            self.is_running = True
            self.pause_event.set()
            self.stop_event.clear()
            
            # 创建线程池
            if self.execution_mode in [ExecutionMode.PARALLEL, ExecutionMode.PIPELINE]:
                self.thread_pool = ThreadPoolExecutor(max_workers=self.max_workers)

            # 启动性能指标定时线程
            if self.config.get("enable_monitoring", True):
                self._start_metrics_loop()
                
            # 启动执行线程
            self.executor_thread = threading.Thread(target=self._execution_loop)
            self.executor_thread.daemon = True
            self.executor_thread.start()
            
            self.logger.info("流程执行已启动")
            return True
            
        except Exception as e:
            self.status = PipelineStatus.ERROR
            self.logger.error(f"启动流程失败: {e}")
            return False
            
    def stop(self) -> bool:
        """停止流程执行"""
        if self.status not in [PipelineStatus.RUNNING, PipelineStatus.PAUSED]:
            return False
            
        try:
            self.status = PipelineStatus.STOPPING
            self.is_running = False
            self.stop_event.set()
            
            # 等待执行线程结束
            if self.executor_thread and self.executor_thread.is_alive():
                self.executor_thread.join(timeout=5)
                
            # 关闭线程池
            if self.thread_pool:
                self.thread_pool.shutdown(wait=True)
                self.thread_pool = None
                
            # 停止所有模块
            for node in self.nodes.values():
                node.module.stop()
                
            self.status = PipelineStatus.STOPPED
            self.logger.info("流程执行已停止")
            # 停止性能指标线程
            self._stop_metrics_loop()
            return True
            
        except Exception as e:
            self.status = PipelineStatus.ERROR
            self.logger.error(f"停止流程失败: {e}")
            return False
            
    def pause(self) -> bool:
        """暂停流程执行"""
        if self.status != PipelineStatus.RUNNING:
            return False
            
        self.status = PipelineStatus.PAUSED
        self.pause_event.clear()
        self.logger.info("流程执行已暂停")
        return True
        
    def resume(self) -> bool:
        """恢复流程执行"""
        if self.status != PipelineStatus.PAUSED:
            return False
            
        self.status = PipelineStatus.RUNNING
        self.pause_event.set()
        self.logger.info("流程执行已恢复")
        return True
        
    def _validate_pipeline(self) -> bool:
        """验证流程合法性"""
        if not self.nodes:
            self.logger.error("流程中没有模块")
            return False
            
        # 检查循环依赖
        if self._has_cycle():
            self.logger.error("流程中存在循环依赖")
            return False
            
        # 检查模块状态
        for node in self.nodes.values():
            if node.module.status == ModuleStatus.ERROR:
                self.logger.error(f"模块处于错误状态: {node.node_id}")
                return False
                
        return True
        
    def _has_cycle(self) -> bool:
        """检查是否存在循环依赖"""
        visited = set()
        rec_stack = set()
        
        def dfs(node_id):
            visited.add(node_id)
            rec_stack.add(node_id)
            
            node = self.nodes[node_id]
            for successor in node.successors:
                if successor.node_id not in visited:
                    if dfs(successor.node_id):
                        return True
                elif successor.node_id in rec_stack:
                    return True
                    
            rec_stack.remove(node_id)
            return False
            
        for node_id in self.nodes:
            if node_id not in visited:
                if dfs(node_id):
                    return True
                    
        return False

    # ----- 单次执行支持 -----
    def run_once(self, input_data: Dict[str, Any] | None = None) -> Dict[str, Any] | None:
        """执行单次顺序流程，不启动后台循环线程。
        典型用途：用户触发“运行一次”快捷键，只跑一轮并得到结果。

        行为:
        1. 仅在 IDLE 状态可执行，避免与持续运行冲突。
        2. 验证拓扑与模块状态；初始化(start)→执行→停止(stop)。
        3. 使用顺序模式拓扑排序，忽略设置的 parallel/pipeline 模式（保持确定性）。
        4. 触发模块步骤回调 (start/end) 与结果/进度回调。
        5. 结束后状态回到 IDLE。
        返回: 最终数据上下文 (含各模块输出路由后的聚合)；失败返回 None。
        """
        if self.status != PipelineStatus.IDLE:
            self.logger.warning("run_once: 当前执行器非 IDLE 状态，拒绝执行")
            return None
        try:
            if not self._validate_pipeline():
                return None
            order = self._calculate_execution_order()
            if not order:
                self.logger.error("run_once: 拓扑排序失败")
                return None
            # 初始化模块
            for node in self.nodes.values():
                if not node.module.start():
                    self.logger.error(f"run_once: 模块启动失败 {node.node_id}")
                    # 尝试停止已启动模块
                    for n2 in self.nodes.values():
                        try: n2.module.stop()
                        except Exception: pass
                    return None
            self.status = PipelineStatus.RUNNING
            data_context: Dict[str, Any] = input_data.copy() if input_data else {}
            start_t = time.time()
            # 顺序执行
            for node_id in order:
                node = self.nodes[node_id]
                node_inputs = self._prepare_node_inputs(node, data_context)
                node.module.receive_inputs(node_inputs)
                self._notify_module_step(node_id, 'start')
                mod_t0 = time.time()
                result = node.module.run_cycle()
                node.execution_time = time.time() - mod_t0
                node.last_result = result
                self._route_outputs(node, result, data_context)
                self._notify_module_step(node_id, 'end')
                # 中断检测 (布尔闸门等设置 request_abort)
                if getattr(node.module, 'request_abort', False) or (isinstance(result, dict) and result.get('abort') is True):
                    self.logger.info(f"run_once: 中断于节点 {node_id}")
                    break
            exec_time = time.time() - start_t
            self.execution_count += 1
            self.total_execution_time += exec_time
            # 回调通知
            if data_context:
                self._notify_result(data_context)
            self._notify_progress(self.execution_count, exec_time)
            # 停止模块
            for node in self.nodes.values():
                try:
                    node.module.stop()
                except Exception:
                    pass
            self.status = PipelineStatus.IDLE
            self.logger.info(f"run_once: 单次执行完成 耗时 {exec_time:.3f}s")
            return data_context
        except Exception as e:
            self.status = PipelineStatus.ERROR
            self.logger.error(f"run_once: 执行异常 {e}")
            self._notify_error(e)
            return None
        
    def _calculate_execution_order(self) -> List[str]:
        """计算执行顺序（拓扑排序）"""
        in_degree = {node_id: 0 for node_id in self.nodes}
        
        # 计算入度
        for node in self.nodes.values():
            for successor in node.successors:
                in_degree[successor.node_id] += 1
                
        # 拓扑排序
        queue_list = [node_id for node_id, degree in in_degree.items() if degree == 0]
        result = []
        
        while queue_list:
            node_id = queue_list.pop(0)
            result.append(node_id)
            
            node = self.nodes[node_id]
            for successor in node.successors:
                in_degree[successor.node_id] -= 1
                if in_degree[successor.node_id] == 0:
                    queue_list.append(successor.node_id)
                    
        return result if len(result) == len(self.nodes) else []
        
    def _execution_loop(self):
        """执行循环"""
        self.logger.info("开始流程执行循环")
        
        try:
            while self.is_running:
                # 等待暂停状态解除
                self.pause_event.wait()
                
                if self.stop_event.is_set():
                    break
                    
                # 获取输入数据
                try:
                    input_data = self.input_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                    
                # 执行流程
                start_time = time.time()
                
                if self.execution_mode == ExecutionMode.SEQUENTIAL:
                    result = self._execute_sequential(input_data)
                elif self.execution_mode == ExecutionMode.PARALLEL:
                    result = self._execute_parallel(input_data)
                else:  # PIPELINE
                    result = self._execute_pipeline(input_data)
                    
                execution_time = time.time() - start_time
                
                # 更新统计信息
                self.execution_count += 1
                self.total_execution_time += execution_time
                
                # 输出结果
                if result:
                    self.output_queue.put(result)
                    self._notify_result(result)
                    
                # 通知进度
                self._notify_progress(self.execution_count, execution_time)
                
        except Exception as e:
            self.status = PipelineStatus.ERROR
            self.error_count += 1
            self.logger.error(f"执行循环错误: {e}")
            self._notify_error(e)
            
        finally:
            self.logger.info("执行循环结束")
            
    def _execute_sequential(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """顺序执行（端口驱动路由版本）
        增强: adaptive 并发 (配置 adaptive_parallel=True 时)
        同一层级的可阻塞模块 (may_block=True) 使用临时线程池并行执行；
        其它保持顺序，避免破坏依赖与界面高亮节奏。
        """
        current_data = input_data.copy()
        adaptive = bool(self.config.get('adaptive_parallel', False))
        if not adaptive:
            # 原始逻辑
            for node_id in self.execution_order:
                node = self.nodes[node_id]
                node_inputs = self._prepare_node_inputs(node, current_data)
                node.module.receive_inputs(node_inputs)
                self._notify_module_step(node_id, 'start')
                start_time = time.time()
                result = node.module.run_cycle()
                node.execution_time = time.time() - start_time
                self._record_perf(node.node_id, node.execution_time)
                node.last_result = result
                self._route_outputs(node, result, current_data)
                self._notify_module_step(node.node_id, 'end')
                if getattr(node.module, 'request_abort', False) or (isinstance(result, dict) and result.get('abort') is True):
                    self.logger.info(f"顺序执行中断于节点 {node_id}")
                    break
            return current_data
        # 自适应层级并发
        levels = self._calculate_execution_levels()
        for level in levels:
            # 拆分 may_block 与普通
            block_nodes = [nid for nid in level if getattr(self.nodes[nid].module.capabilities, 'may_block', False)]
            normal_nodes = [nid for nid in level if nid not in block_nodes]
            # 先并行执行 block_nodes
            if block_nodes and len(block_nodes) > 1:
                temp_pool = ThreadPoolExecutor(max_workers=min(len(block_nodes), self.config.get('max_workers', 4)))
                futures: List[Future] = []
                for nid in block_nodes:
                    node = self.nodes[nid]
                    node_inputs = self._prepare_node_inputs(node, current_data)
                    node.module.receive_inputs(node_inputs)
                    futures.append(temp_pool.submit(self._execute_node_return_route, node, current_data))
                for f in futures:
                    try:
                        f.result(timeout=self.config.get('timeout', 30))
                    except Exception as e:
                        self.logger.error(f"自适应并发节点失败: {e}")
                temp_pool.shutdown(wait=True)
            else:
                # 单个或无并发节点
                for nid in block_nodes:
                    node = self.nodes[nid]
                    node_inputs = self._prepare_node_inputs(node, current_data)
                    node.module.receive_inputs(node_inputs)
                    self._notify_module_step(nid, 'start')
                    t0 = time.time()
                    result = node.module.run_cycle()
                    node.execution_time = time.time() - t0
                    self._record_perf(node.node_id, node.execution_time)
                    node.last_result = result
                    self._route_outputs(node, result, current_data)
                    self._notify_module_step(nid, 'end')
                    if getattr(node.module, 'request_abort', False) or (isinstance(result, dict) and result.get('abort') is True):
                        self.logger.info(f"自适应并发层中断于节点 {nid}")
                        return current_data
            # 顺序执行普通节点
            for nid in normal_nodes:
                node = self.nodes[nid]
                node_inputs = self._prepare_node_inputs(node, current_data)
                node.module.receive_inputs(node_inputs)
                self._notify_module_step(nid, 'start')
                t0 = time.time()
                result = node.module.run_cycle()
                node.execution_time = time.time() - t0
                self._record_perf(node.node_id, node.execution_time)
                node.last_result = result
                self._route_outputs(node, result, current_data)
                self._notify_module_step(nid, 'end')
                if getattr(node.module, 'request_abort', False) or (isinstance(result, dict) and result.get('abort') is True):
                    self.logger.info(f"自适应并发普通层中断于节点 {nid}")
                    return current_data
        return current_data

    def _execute_node_return_route(self, node: PipelineNode, current_data: Dict[str, Any]) -> None:
        """辅助：在线程中执行节点并路由结果 (用于 adaptive 并发)。"""
        self._notify_module_step(node.node_id, 'start')
        t0 = time.time()
        result = node.module.run_cycle()
        node.execution_time = time.time() - t0
        self._record_perf(node.node_id, node.execution_time)
        node.last_result = result
        self._route_outputs(node, result, current_data)
        self._notify_module_step(node.node_id, 'end')
        
    def _execute_parallel(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """并行执行（端口驱动路由版本）"""
        # 按层级并行执行
        levels = self._calculate_execution_levels()
        current_data = input_data.copy()
        
        for level_nodes in levels:
            if len(level_nodes) == 1:
                # 单个节点直接执行
                node = self.nodes[level_nodes[0]]
                node_inputs = self._prepare_node_inputs(node, current_data)
                node.module.receive_inputs(node_inputs)
                self._notify_module_step(node.node_id, 'start')
                start_time = time.time()
                result = node.module.run_cycle()
                node.execution_time = time.time() - start_time
                self._record_perf(node.node_id, node.execution_time)
                node.last_result = result
                self._route_outputs(node, result, current_data)
                self._notify_module_step(node.node_id, 'end')
            else:
                # 多个节点并行执行
                futures = []
                for node_id in level_nodes:
                    node = self.nodes[node_id]
                    node_inputs = self._prepare_node_inputs(node, current_data)
                    future = self.thread_pool.submit(self._execute_node, node, node_inputs)
                    futures.append((node, future))
                    
                # 等待所有任务完成
                for node, future in futures:
                    try:
                        result = future.result(timeout=self.config.get("timeout", 30))
                        node.last_result = result
                        self._route_outputs(node, result, current_data)
                    except Exception as e:
                        self.logger.error(f"节点执行失败: {node.node_id}, {e}")
                        
        return current_data
        
    def _execute_pipeline(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """流水线执行"""
        # 实现流水线执行逻辑
        # 这里需要更复杂的数据流管理
        return self._execute_sequential(input_data)
        
    def _execute_node(self, node: PipelineNode, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """执行单个节点 (并行模式内部使用)"""
        node.module.receive_inputs(inputs)
        self._notify_module_step(node.node_id, 'start')
        start_time = time.time()
        result = node.module.run_cycle()
        node.execution_time = time.time() - start_time
        self._record_perf(node.node_id, node.execution_time)
        self._notify_module_step(node.node_id, 'end')
        return result
        
    def _calculate_execution_levels(self) -> List[List[str]]:
        """计算执行层级"""
        levels = []
        processed = set()
        
        while len(processed) < len(self.nodes):
            current_level = []
            
            for node_id in self.nodes:
                if node_id in processed:
                    continue
                    
                node = self.nodes[node_id]
                # 检查所有前驱节点是否已处理
                if all(pred.node_id in processed for pred in node.predecessors):
                    current_level.append(node_id)
                    
            if not current_level:
                break  # 防止死循环
                
            levels.append(current_level)
            processed.update(current_level)
            
        return levels
        
    def _prepare_node_inputs(self, node: PipelineNode, data_context: Dict[str, Any]) -> Dict[str, Any]:
        """准备节点输入数据"""
        node_inputs = {}
        
        for input_name, (source_node, output_name) in node.inputs.items():
            if source_node.last_result and output_name in source_node.last_result:
                node_inputs[input_name] = source_node.last_result[output_name]
            elif input_name in data_context:
                node_inputs[input_name] = data_context[input_name]
                
        return node_inputs

    def _route_outputs(self, node: PipelineNode, outputs: Dict[str, Any], data_context: Dict[str, Any]):
        """根据连接关系路由输出数据到全局上下文与目标节点输入缓存。"""
        if not outputs:
            return
        # 更新全局数据上下文（共享输出）
        for k, v in outputs.items():
            data_context[k] = v
        # 按显式连接分发
        for output_name, connections in node.outputs.items():
            if output_name in outputs:
                value = outputs[output_name]
                for target_node, target_input_name in connections:
                    target_node.module.receive_inputs({target_input_name: value})
        
    def add_progress_callback(self, callback: Callable):
        """添加进度回调"""
        self.progress_callbacks.append(callback)
        
    def add_result_callback(self, callback: Callable):
        """添加结果回调"""
        self.result_callbacks.append(callback)
        
    def add_error_callback(self, callback: Callable):
        """添加错误回调"""
        self.error_callbacks.append(callback)

    def add_module_step_callback(self, callback: Callable):
        """添加模块步骤回调。
        回调签名: callback(node_id: str, phase: str)
        phase 取值: 'start' | 'end'
        """
        self.module_step_callbacks.append(callback)
        
    def _notify_progress(self, count: int, execution_time: float):
        """通知进度更新"""
        for callback in self.progress_callbacks:
            try:
                callback(count, execution_time)
            except Exception as e:
                self.logger.error(f"进度回调错误: {e}")
                
    def _notify_result(self, result: Dict[str, Any]):
        """通知结果"""
        for callback in self.result_callbacks:
            try:
                callback(result)
            except Exception as e:
                self.logger.error(f"结果回调错误: {e}")
                
    def _notify_error(self, error: Exception):
        """通知错误"""
        for callback in self.error_callbacks:
            try:
                callback(error)
            except Exception as e:
                self.logger.error(f"错误回调错误: {e}")

    def _notify_module_step(self, node_id: str, phase: str):
        """通知模块执行步骤（开始/结束）。
        注意：在并行模式下可能由多个线程调用，GUI 层需考虑线程安全。
        """
        for callback in self.module_step_callbacks:
            try:
                callback(node_id, phase)
            except Exception as e:
                self.logger.error(f"模块步骤回调错误: {e}")
                
    def get_status(self) -> Dict[str, Any]:
        """获取执行器状态"""
        avg_time = (self.total_execution_time / self.execution_count 
                   if self.execution_count > 0 else 0)
        
        return {
            "status": self.status.value,
            "execution_mode": self.execution_mode.value,
            "node_count": len(self.nodes),
            "execution_count": self.execution_count,
            "total_execution_time": self.total_execution_time,
            "average_execution_time": avg_time,
            "error_count": self.error_count,
            "throughput": 1.0 / avg_time if avg_time > 0 else 0
        }

    # ---------- 性能监控扩展 ----------
    def _record_perf(self, node_id: str, duration: float):
        with self._perf_lock:
            stat = self._perf_stats.get(node_id)
            if not stat:
                stat = {'exec_count': 0, 'total_time': 0.0, 'max_time': 0.0, 'last_time': 0.0, 'avg_time': 0.0}
                self._perf_stats[node_id] = stat
            stat['exec_count'] += 1
            stat['total_time'] += duration
            stat['last_time'] = duration
            if duration > stat['max_time']:
                stat['max_time'] = duration
            stat['avg_time'] = stat['total_time'] / stat['exec_count']

    def get_metrics(self) -> Dict[str, Any]:
        with self._perf_lock:
            per_node = {nid: stats.copy() for nid, stats in self._perf_stats.items()}
        aggregate = {
            'modules_profiled': len(per_node),
            'total_execs': sum(s['exec_count'] for s in per_node.values()),
            'total_time': sum(s['total_time'] for s in per_node.values()),
        }
        return {'nodes': per_node, 'aggregate': aggregate}

    def reset_metrics(self):
        with self._perf_lock:
            self._perf_stats.clear()

    def add_metrics_callback(self, callback: Callable):
        """注册性能指标回调: callback(stats_dict, aggregate_dict)"""
        self._metrics_callbacks.append(callback)

    def _start_metrics_loop(self):
        if self._metrics_timer_thread and self._metrics_timer_thread.is_alive():
            return
        self._metrics_stop.clear()
        def _loop():
            while not self._metrics_stop.is_set():
                time.sleep(self._metrics_interval_s)
                try:
                    data = self.get_metrics()
                    for cb in self._metrics_callbacks:
                        try:
                            cb(data['nodes'], data['aggregate'])
                        except Exception:
                            pass
                except Exception:
                    pass
        self._metrics_timer_thread = threading.Thread(target=_loop, daemon=True)
        self._metrics_timer_thread.start()

    def _stop_metrics_loop(self):
        self._metrics_stop.set()
        if self._metrics_timer_thread and self._metrics_timer_thread.is_alive():
            self._metrics_timer_thread.join(timeout=1.5)
        self._metrics_timer_thread = None
        
    def get_pipeline_graph(self) -> Dict[str, Any]:
        """获取流程图信息"""
        nodes = {}
        edges = []
        
        for node_id, node in self.nodes.items():
            nodes[node_id] = {
                "module_name": node.module.name,
                "module_type": node.module.module_type.value,
                "status": node.module.status.value,
                "execution_time": node.execution_time
            }
            
            for output_name, connections in node.outputs.items():
                for target_node, input_name in connections:
                    edges.append({
                        "source": node_id,
                        "target": target_node.node_id,
                        "source_port": output_name,
                        "target_port": input_name
                    })
                    
        return {
            "nodes": nodes,
            "edges": edges,
            "execution_order": self.execution_order,
            "connections": [
                {
                    "source_module": c.source_module,
                    "source_port": c.source_port,
                    "target_module": c.target_module,
                    "target_port": c.target_port,
                    "active": c.active
                } for c in self.connections
            ]
        }