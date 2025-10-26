#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""(moved) 逻辑模块"""
from typing import Dict, Any, List
from app.pipeline.base_module import BaseModule, ModuleType, ModuleCapabilities
try:
    from pydantic import BaseModel, validator
except ImportError:
    BaseModel = object  # type: ignore
import ast

class LogicModule(BaseModule):
    # 能力声明
    CAPABILITIES = ModuleCapabilities(
        supports_async=False,
        supports_batch=False,
        may_block=False,
        resource_tags=["logic"],
        throughput_hint=1000.0,
    )

    class ConfigModel(BaseModel):  # type: ignore
        op: str = "AND"
        invert: bool = False
        expr: str = ""
        inputs_count: int = 2
        history_size: int = 20

        @validator("op")
        def _op_ok(cls, v):
            v2 = v.upper()
            if v2 not in {"AND","OR","XOR","NAND","NOR","NOT"}:
                raise ValueError("非法逻辑操作类型")
            return v2

        @validator("inputs_count")
        def _inputs_ok(cls, v):
            if not (1 <= v <= 26):
                raise ValueError("inputs_count 必须在 1~26 范围")
            return v

        @validator("history_size")
        def _hist_ok(cls, v):
            if v <= 0:
                raise ValueError("history_size 必须 > 0")
            return v

    def __init__(self, name: str = "逻辑模块"):
        self.op = "AND"; self.invert = False; self.expr = ""; self.inputs_count = 2
        self.history_size = 20; self.exec_count = 0; self.history_results: List[bool] = []
        super().__init__(name)
    @property
    def module_type(self) -> ModuleType:
        return ModuleType.CUSTOM
    def _define_ports(self):
        if not self.output_ports:
            self.register_output_port("result", port_type="bool", desc="逻辑结果")
        if not self.input_ports:
            for i in range(self.inputs_count):
                name = chr(ord('a') + i)
                self.register_input_port(name, port_type="bool", desc=f"输入 {name}", required=(i==0))
    def _rebuild_input_ports(self, count:int):
        if count < 1: count = 1
        for k in list(self.input_ports.keys()): del self.input_ports[k]
        self.inputs.clear(); self.inputs_count = count
        for i in range(count):
            name = chr(ord('a') + i)
            self.register_input_port(name, port_type="bool", desc=f"输入 {name}", required=(i==0))
    def _coerce_bool(self, v: Any) -> bool:
        if isinstance(v, bool): return v
        if isinstance(v, (int,float)): return v!=0
        if isinstance(v,str):
            t=v.strip().lower();
            if t in ["1","true","t","yes","y","on"]: return True
            if t in ["0","false","f","no","n","off",""]: return False
        return bool(v)
    def process(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        bmap={n:self._coerce_bool(inputs.get(n)) for n in self.input_ports.keys()}
        if self.expr.strip():
            result=self._eval_expr(bmap)
        else:
            a=bmap.get('a',False); b=bmap.get('b',False); op=self.op.upper()
            try:
                if op=="AND": result=a and b
                elif op=="OR": result=a or b
                elif op=="XOR": result=(a and not b) or (not a and b)
                elif op=="NAND": result=not (a and b)
                elif op=="NOR": result=not (a or b)
                elif op=="NOT": result=not a
                else: self.errors.append(f"未知逻辑操作: {op}"); result=False
            except Exception as e:
                self.errors.append(str(e)); result=False
        if self.invert: result=not result
        return {"result": result}
    _ALLOWED_NODES=(ast.Expression,ast.BoolOp,ast.UnaryOp,ast.Name,ast.Load,ast.And,ast.Or,ast.Not,ast.Constant)
    def _eval_expr(self, env: Dict[str,bool]) -> bool:
        expr=self.expr.strip()
        try: tree=ast.parse(expr,mode='eval')
        except Exception as e: self.errors.append(f"表达式解析失败: {e}"); return False
        for node in ast.walk(tree):
            if not isinstance(node,self._ALLOWED_NODES): self.errors.append(f"不允许的语法: {type(node).__name__}"); return False
        code=compile(tree,'<logic-expr>','eval')
        try: val=eval(code,{"__builtins__":{}},env)
        except Exception as e: self.errors.append(f"表达式求值错误: {e}"); return False
        return bool(val)
    def _on_configure(self, config: Dict[str,Any]):
        # 配置在 pydantic 校验后转入，因此值可信
        self.op = config.get('op', self.op).upper()
        self.invert = bool(config.get('invert', self.invert))
        self.expr = str(config.get('expr', self.expr))
        ic = int(config.get('inputs_count', self.inputs_count))
        if ic != self.inputs_count:
            self._rebuild_input_ports(ic)
        self.history_size = int(config.get('history_size', self.history_size))
    def run_cycle(self) -> Dict[str,Any]:
        result=super().run_cycle(); self.exec_count+=1; val=result.get('result')
        if isinstance(val,bool):
            self.history_results.append(val)
            if len(self.history_results)>self.history_size:
                self.history_results=self.history_results[-self.history_size:]
        return result
    def get_status(self) -> Dict[str,Any]:
        base=super().get_status(); base.update({"op":self.op,"invert":self.invert,"expr":self.expr,
            "inputs_count":self.inputs_count,"history_size":self.history_size,
            "exec_count":self.exec_count,"history_results":list(self.history_results)})
        return base
