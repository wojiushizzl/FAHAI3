#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BoolGateModule 与 OK/NOK 字符串输入的兼容性测试

运行: pytest -k bool_gate_oknok 或 python tests/test_bool_gate_oknok.py
"""
from app.pipeline.utility.bool_gate_module import BoolGateModule


def _run(val, invert=False):
    m = BoolGateModule()
    m._define_ports()  # ensure ports
    out = m.process({'flag': val, 'invert': invert})
    return out['passed'], out['flag_out'], out['gate_trigger']


def test_oknok_true_strings():
    for v in ['OK', 'ok', 'True', 'true', 'Yes', '1', 'pass', 'SUCCESS']:
        passed, flag_out, gate_trigger = _run(v)
        assert passed is True and flag_out is True and gate_trigger is False, f"{v} 解析异常"


def test_oknok_false_strings():
    for v in ['NOK', 'nok', 'False', 'false', 'No', '0', 'ng', 'fail', 'ERROR']:
        passed, flag_out, gate_trigger = _run(v)
        assert passed is False and flag_out is False and gate_trigger is True, f"{v} 解析异常"


def test_numeric_values():
    assert _run(0)[0] is False
    assert _run(5)[0] is True
    assert _run(-3)[0] is True


def test_invert_flag():
    assert _run('OK', invert=True)[0] is False
    assert _run('NOK', invert=True)[0] is True


if __name__ == '__main__':
    # 简单直接运行
    print('OK set ->', _run('OK'))
    print('NOK set ->', _run('NOK'))
    print('Invert OK ->', _run('OK', invert=True))
    print('Invert NOK ->', _run('NOK', invert=True))
    print('数字 0 ->', _run(0))
    print('数字 2 ->', _run(2))
    print('全部测试通过')
