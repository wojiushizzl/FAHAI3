# Modbus 模块使用说明

## 模块列表
- `modbus模拟服务器`: 在本地 127.0.0.1 启动一个可配置端口的 Modbus TCP 服务器 (默认 1502)。支持批量写入线圈与保持寄存器并周期输出状态快照。
- `modbus连接`: 建立与设备的连接。支持 TCP 单主机 / 多主机 / RTU 串口；带熔断(fuse)与重连回退(backoff)。
- `modbus监听`: 轮询读取指定地址（coil / discrete / holding / input），支持边沿模式: `rising` / `falling` / `any` / `level`。
- `modbus输出`: 根据输入布尔/数值条件写入 coil 或 holding register，可选择仅在变化时写入。

## 典型调试流程
1. 在画布添加 `modbus模拟服务器` 模块 (可保持默认端口 1502)。
2. 添加 `modbus连接` 模块，配置 host=127.0.0.1, port=1502。
3. 添加 `modbus监听` 模块，地址类型选择 `holding`，address=0，周期即可读取初始值 0。
4. 给 `modbus模拟服务器` 模块的输入端口 `holding_values` 传入列表，例如 `[5,10,15]`，监听模块应输出 5 (地址0)。
5. 使用 `edge_mode=any` 或 `rising` 可获得变化脉冲。

## 配置说明
### modbus模拟服务器
| 参数 | 说明 | 默认 |
|------|------|------|
| port | 服务器监听端口 | 1502 |
| coil_count | 线圈数量 | 64 |
| holding_count | 保持寄存器数量 | 64 |
| unit_id | 站号 | 1 |
| update_snapshot | 是否周期输出快照 | True |

### modbus连接
| 参数 | 说明 | 默认 |
|------|------|------|
| protocol | `tcp` 或 `rtu` | tcp |
| host | 单主机地址 | 127.0.0.1 |
| hosts | 多主机列表 (优先于 host) | [] |
| port | TCP 端口 | 502 |
| timeout | 超时秒 | 3.0 |
| auto_reconnect | 自动重连 | True |
| fuse_fail_count | 连续失败次数触发熔断 | 5 |
| fuse_cooldown_s | 熔断冷却秒 | 10.0 |
| reconnect_backoff_s | 重连前等待秒 | 0.0 |
| serial_port | RTU 串口 | COM3 |
| baudrate | 波特率 | 9600 |
| parity | N/E/O | N |
| stopbits | 停止位 | 1 |
| bytesize | 数据位 | 8 |

输出端口:
- `connect`: 单连接或第一连接句柄
- `connections`: 多主机连接列表
- `status`: 全部连接是否成功
- `fused`: 是否处于熔断期

### modbus监听
| 参数 | 说明 | 默认 |
|------|------|------|
| address_type | coil/discrete/holding/input | coil |
| address | 读取地址 | 0 |
| unit_id | 站号 | 1 |
| edge_mode | rising/falling/any/level | rising |
| invert | 反转值（布尔） | False |

输出:
- `value`: 当前值
- `edge`: 边沿触发标志 (当 edge_mode != level)

### modbus输出
| 参数 | 说明 | 默认 |
|------|------|------|
| write_type | coil 或 holding | coil |
| address | 写入地址 | 0 |
| unit_id | 站号 | 1 |
| write_on_change | 仅变化时写入 | True |
| safe_mode | 抑制写入异常 | True |

输入端口: `trigger` (bool 或数值)、可选 `value` (holding写入数值)
输出: `written` (是否写入), `result` (库返回结果或错误)

## 熔断机制说明
`modbus连接` 在连续失败次数达到 `fuse_fail_count` 后进入熔断，`fused` 输出为 True，在 `fuse_cooldown_s` 时间内不再尝试重连，以避免日志刷屏与资源浪费。冷却结束后自动再次尝试连接并清除失败计数。

## 边沿模式
- rising: 0 -> 1 时输出 edge=True
- falling: 1 -> 0 时输出 edge=True
- any: 任意变化输出 edge=True
- level: 始终输出当前值，不产生 edge 脉冲

## 常见问题
1. 端口被占用: 修改 `modbus模拟服务器` 的端口，并同步调整 `modbus连接` 的 port。
2. RTU 无法连接: 确认 pymodbus 版本支持串口，串口号、权限与波特率正确。
3. 多主机连接部分成功: `status` 为 False，但 `connections` 列表里仍含已成功的客户端，可在下游模块中挑选使用。
4. 熔断后不再恢复: 检查是否仍有新的错误导致失败计数未清零；可临时降低 `fuse_fail_count` 进行验证。

## 自适应并发 (Adaptive)
执行器配置 `adaptive_parallel=True` 时，拓扑同层的 `may_block=True` 模块会被并行执行，提高 IO 场景吞吐；依赖顺序保持不变。

## 示例管线 JSON 片段
```json
{
  "modules": [
    {"module_type": "modbus模拟服务器", "x": 40, "y": 40},
    {"module_type": "modbus连接", "x": 300, "y": 40, "config": {"host": "127.0.0.1", "port": 1502}},
    {"module_type": "modbus监听", "x": 560, "y": 40, "config": {"address_type": "holding", "address": 0, "edge_mode": "any"}}
  ]
}
```

## 后续可拓展
- 多协议统一连接池
- 单点写入接口 (index/value) 替代批量覆盖
- 服务器随机波动模式用于高频边沿测试
- 写入结果指标统计 (成功率/失败率)

---
最后更新: 2025-10-26
