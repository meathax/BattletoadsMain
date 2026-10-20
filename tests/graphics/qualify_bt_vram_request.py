"""Source-bound exhaustive original/request pin proof for the private v11 edge."""
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import re

from prepare_bt_vram_request import BASE, BASE_ROOT, transform
from bt_vram_request_fixture import INSTANCES, SELECTORS, lf, verify_edge
from qualify_bt_address_class_r2 import SVExpression, evaluate, instance_ports, wire_expression

ROOT = Path(__file__).resolve().parents[2]
sha = lambda data: hashlib.sha256(data).hexdigest()


def function_assignment(source, name):
    body = re.findall(r'function automatic \[3:0\] ' + name + r'\(.*?endfunction', source, re.S)
    assert len(body) == 1
    returned = re.findall(r'\b' + name + r'\s*=\s*(.*?);', body[0], re.S)
    assert len(returned) == 1
    return body[0], SVExpression(returned[0]).tree


def ports(header, debug):
    header = re.sub(r'`ifdef DEBUG(.*?)`endif', lambda m: m[1] if debug else '', header, flags=re.S)
    header = re.sub(r'//[^\n]*', '', header)
    header = header[header.index('(') + 1:header.rindex(');')]
    return [re.findall(r'\b\w+\b', part)[-1] for part in header.split(',') if part.strip()]


def prove(candidate_read):
    parent_read, edge = verify_edge(ROOT, BASE_ROOT, candidate_read)
    before = lf(parent_read('rtl/BT.sv')).decode()
    after = lf(candidate_read('rtl/BT.sv')).decode()
    mc = lf(candidate_read('rtl/TMS34020/TMS34020_MC.sv')).decode()
    original_mc = lf(parent_read('rtl/TMS34020/TMS34020_MC.sv')).decode()
    for name in ('rtl/TMS34020/TMS34020_MC.sv', 'rtl/TMS34020/TMS34020.sv'):
        old = lf(parent_read(name)).decode().split(');', 1)[0] + ');'
        new = lf(candidate_read(name)).decode().split(');', 1)[0] + ');'
        for debug in (False, True):
            assert ports(new, debug) == ports(old, debug) + ['VRAM_REQUEST'], (name, debug)
    class_body, class_tree = function_assignment(mc, 'AddressClass')
    assert class_body == function_assignment(original_mc, 'AddressClass')[0]
    request_body, request_tree = function_assignment(mc, 'VramRequests')
    match = re.findall(r'fg_match\s*=\s*(.*?);', request_body, re.S)
    assert len(match) == 1
    match_tree = SVExpression(match[0]).tree
    old_wires = {name: wire_expression(before, name) for name in SELECTORS}
    assert all(wire_expression(after, name) == tree for name, tree in old_wires.items())
    old_ports, new_ports = [], []
    for module, instance in INSTANCES:
        a, b = instance_ports(before, module, instance), instance_ports(after, module, instance)
        assert a.keys() == b.keys()
        assert {k: v for k, v in a.items() if k != 'RAS_N'} == {k: v for k, v in b.items() if k != 'RAS_N'}
        old_ports.append(SVExpression(a['RAS_N']).tree)
        new_ports.append(SVExpression(b['RAS_N']).tree)
    cases = pin_checks = request_checks = 0
    for high, code, page, ras_active in itertools.product(range(1024), range(16), range(2), range(2)):
        address = (high << 22) | 0x2a55a0
        values = {'address': (32, address), 'code': (4, code), 'ras_active': (1, ras_active),
                  'LA': (32, (address & ~15) | code), 'DISP_CONTROL': (16, page << 15),
                  'RAS_N': (1, 1 - ras_active)}
        values['classes'] = evaluate(class_tree, values.__getitem__)
        values['CPU_ADDR_CLASS'] = values['classes']
        values['fg_match'] = evaluate(match_tree, values.__getitem__)
        values['CPU_VRAM_REQUEST'] = evaluate(request_tree, values.__getitem__)
        def resolve(name):
            if name not in values:
                assert name in old_wires, name
                values[name] = evaluate(old_wires[name], resolve)
            return values[name]
        original = [evaluate(tree, resolve)[1] for tree in old_ports]
        current = [evaluate(tree, resolve)[1] for tree in new_ports]
        assert original == current, (high, code, page, ras_active, original, current)
        requests = values['CPU_VRAM_REQUEST'][1]
        expected = ((ras_active and ((high == (0xb4 << 2)) or code == 4)) << 3) | \
                   ((ras_active and ((high == (0xb0 << 2)) or code == 4)) << 2) | \
                   ((ras_active and bool(values['fg_match'][1]) and bool(address & (1 << 26))) << 1) | \
                   (ras_active and ((bool(values['fg_match'][1]) and not bool(address & (1 << 26))) or code == 4))
        assert requests == expected
        cases += 1; pin_checks += len(original); request_checks += 4
    # Legacy RAS is intentionally unreset. Reset A0/CODEf alone make all requests zero.
    for ras_active in (0, 1):
        values = {'address': (32, 0), 'code': (4, 15), 'ras_active': (1, ras_active)}
        values['classes'] = evaluate(class_tree, values.__getitem__)
        values['fg_match'] = evaluate(match_tree, values.__getitem__)
        assert evaluate(request_tree, values.__getitem__) == (4, 0)
    reset = original_mc[original_mc.index('if (!RST_N) begin'):original_mc.index('\t\telse begin', original_mc.index('if (!RST_N) begin'))]
    assert not re.search(r'\bDBUS_RAS\s*<=', reset)
    projections = edge['rtl/TMS34020/TMS34020_MC.sv']['projected_assignments']
    assert len(projections) == 16
    actual_assignments = re.findall(r'^\s*(DBUS_A|DBUS_CODE|DBUS_RAS)\s*<=\s*(.+);\s*$', mc, re.M)
    old_assignments = re.findall(r'^\s*(DBUS_A|DBUS_CODE|DBUS_RAS)\s*<=\s*(.+);\s*$', original_mc, re.M)
    assert actual_assignments == old_assignments, 'An original NBA or its priority/order changed'
    return {'status': 'PASS', 'exhaustive_cases': cases, 'six_ras_pin_comparisons': pin_checks,
            'request_bit_comparisons': request_checks, 'all_original_nbas_retained': True,
            'same_edge_projection_assignments': len(projections), 'debug_and_release_abi_preserved': True,
            'reset_with_held_ras_zero_requests': True, 'selectors_and_transfer_pins_unchanged': True,
            'display_page_remains_live': True, 'source_edge': edge,
            'scope': 'Exact Boolean/source and induction premise proof; no simulator/elaboration/fit/timing/hardware claim.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    candidate = args.candidate.resolve()
    output = args.output.resolve()
    output.relative_to(ROOT / 'build')
    assert not output.exists(), 'Keep accepted receipts immutable'
    inputs = {}
    def read(name):
        raw = (candidate / name).read_bytes()
        inputs[name] = {'path': str(candidate / name), 'sha256': sha(raw), 'lf_sha256': sha(lf(raw))}
        return raw
    result = prove(read)
    controls = []
    for name, old, new, label in [
        ('rtl/BT.sv', b'CPU_VRAM_REQUEST[0]', b'CPU_VRAM_REQUEST[1]', 'changed RAS pin'),
        ('rtl/BT.sv', b'.TRANSFER(', b'.BROKEN_TRANSFER(', 'changed transfer binding'),
        ('rtl/TMS34020/TMS34020_MC.sv', b'vram_ras_next = 0;', b'vram_ras_next = 1;', 'changed R-phase projection priority'),
        ('rtl/TMS34020/TMS34020_MC.sv', b'VRAM_REQUEST <= 4\'b0000;', b'VRAM_REQUEST <= 4\'b0001;', 'changed reset'),
        ('rtl/TMS34020/TMS34020.sv', b'.VRAM_REQUEST(VRAM_REQUEST)', b'.VRAM_REQUEST(4\'b0)', 'combinatorial/proxy CPU binding'),
    ]:
        actual = read(name)
        assert old in actual, label
        corrupted = actual.replace(old, new, 1)
        def corrupted_read(path):
            return corrupted if path == name else read(path)
        try:
            verify_edge(ROOT, BASE_ROOT, corrupted_read)
        except AssertionError:
            controls.append({'name': label, 'rejected': True})
        else:
            raise AssertionError('Negative control was accepted: ' + label)
    result['negative_controls'] = controls
    result['inputs'] = inputs
    result['helper_sha256'] = sha(Path(__file__).read_bytes())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'receipt': str(output), 'status': result['status'], 'cases': result['exhaustive_cases'],
                      'pin_checks': result['six_ras_pin_comparisons'], 'negative_controls': len(controls)}))


if __name__ == '__main__':
    main()
