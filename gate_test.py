from app.pipeline.utility.bool_gate_module import BoolGateModule
from app.pipeline.base_module import BaseModule, ModuleType
from app.pipeline.pipeline_executor import PipelineExecutor, ExecutionMode
import time

class CounterModule(BaseModule):
    def __init__(self,name='counter'): super().__init__(name); self.n=0
    @property
    def module_type(self): return ModuleType.CUSTOM
    def _define_ports(self): self.register_output_port('val','int','value')
    def process(self,inputs): self.n+=1; return {'val':self.n}

class ReceiveModule(BaseModule):
    def __init__(self,name='recv'): super().__init__(name); self.last=None
    @property
    def module_type(self): return ModuleType.CUSTOM
    def _define_ports(self): self.register_input_port('val','int','value',required=False); self.register_output_port('ok','bool','done')
    def process(self,inputs): self.last=inputs.get('val'); return {'ok':True}

# Build pipeline: counter1 -> gate (flag) and counter1 -> recv1; independent counter2 -> recv2
cnt=CounterModule('counter1')
gate=BoolGateModule()
recv=ReceiveModule('recv1')
cnt2=CounterModule('counter2')
recv2=ReceiveModule('recv2')

ex=PipelineExecutor()
ex.add_module(cnt,'c1')
ex.add_module(gate,'g1')
ex.add_module(recv,'r1')
ex.add_module(cnt2,'c2')
ex.add_module(recv2,'r2')
# Connections
ex.connect_modules('c1','val','g1','flag')
ex.connect_modules('c1','val','r1','val')
ex.connect_modules('c2','val','r2','val')

# Force gate flag False by modifying gate process? We'll let counter1 output start at 1 (True) then manually set flag False by intercepting.
# Simpler: run one cycle (flag True) then patch gate to always False.
ex.set_execution_mode(ExecutionMode.SEQUENTIAL)
ex.start({})
ex.input_queue.put({})  # first tick
# Patch gate
orig_process = gate.process

def always_false(inputs):
    inputs['flag'] = False
    return orig_process(inputs)

gate.process = always_false  # type: ignore
for _ in range(3):
    ex.input_queue.put({})

time.sleep(1.0)
ex.stop()
print('recv1.last', recv.last, 'recv2.last', recv2.last)
