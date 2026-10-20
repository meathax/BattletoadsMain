"""Prove the frozen r2 decode edge and compose unchanged Intel RAM evidence.

This parses the actual Boolean SV expressions. It starts no simulator or
Quartus job and does not rewrite any retained receipt or release validator.
"""
import argparse
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
V9 = ROOT / 'build/timing_closure_20261011/integrated_v9_private'
R1 = ROOT / 'build/timing_closure_20261011/address_classes_v10/candidate_r1'
R2 = ROOT / 'build/timing_closure_20261011/address_classes_v10/candidate_r2'
BASE = {
    'rtl/BT.sv': '69e8eef01824c66356c4e1427f5bab3509534aba39c23df01a3dce713be2672b',
    'rtl/TMS34020/TMS34020.sv': 'b559dd361d02705cc19088d9b09389b1f978645b7c7f3cb8cb761877226de1a9',
    'rtl/TMS34020/TMS34020_MC.sv': '01bc6d0da7355616fa615b3c75132e85ab30810f68c5474620fb045b8be25531',
}
FIRST = {
    'rtl/BT.sv': '4d6b3a1ad122539d72ccbdbde08e86ee8910c26c6dd0620eed17c88730ac8245',
    'rtl/TMS34020/TMS34020.sv': '46f0743c4b3186796c19d6fe1a2d1a3a5fa4750763f5890ff95e87789a057d1c',
    'rtl/TMS34020/TMS34020_MC.sv': '165a7d5a0265c8c98822b3771fcdf62b9a51d2bcd85cc45abbf1fb6bdd8d650a',
}
FINAL = dict(FIRST, **{'rtl/BT.sv': '2560e301b61e8fb56285df0d4f57752cc985820991542031dae9df17e508c6fe'})
PHYSICAL = {
    'rtl/fg_vram.sv': '233061bcfdcb986e250a204ce488f2171372250baac073a28086065529d64fec',
    'rtl/BT_mem.sv': '903aeedc272fd64409ebae8b8624befe82bc1f073d1545310dbeb070afaf6393',
    'rtl/bg_vram.sv': 'ba42376b22889cf0dc0f1b55203e21e1cf121daa7b4ab690ad24eb8586ba31d1',
    'tests/graphics/ram_models.sv': '039f6ead2da5edfeaa0bf4aeb45eb7795ccf3e57e6193ea3e7763a41ae2cdafc',
}
VENDOR_RECEIPT = ROOT / 'tests/graphics/evidence/vram-physical/vram-current-c37fbfc0d0cb409dae7e0692f8f4598f/receipt.json'
PIN_RECEIPT = ROOT / 'build/item4-equivalence-2745c075f1784ba8808e3feca78b512c/receipt.json'
ORACLE = 'b53726397822b9dbebb02d36411294056fd08649'
sha = lambda data: hashlib.sha256(data).hexdigest()
normalize = lambda text: re.sub(r'\s+', '', text)


class SVExpression:
    """Small unsigned SV expression parser for the exact decode vocabulary."""
    TOKEN = re.compile(r"\s*(\d+'[bhdo][0-9a-fA-F_]+|\d+|[A-Za-z_]\w*|==|&&|\|\||[!~&|^?:(){}\[\],])")
    PRECEDENCE = {'||': 2, '&&': 3, '|': 4, '^': 5, '&': 6, '==': 7}

    def __init__(self, expression):
        self.tokens, pos = [], 0
        expression = expression.strip()
        while pos < len(expression):
            match = self.TOKEN.match(expression, pos)
            assert match, ('Unsupported SV token', expression[pos:])
            self.tokens.append(match[1])
            pos = match.end()
        self.index = 0
        self.tree = self.parse(0)
        assert self.index == len(self.tokens), ('Trailing SV tokens', self.tokens[self.index:])

    def peek(self):
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def take(self, expected=None):
        value = self.peek()
        assert value is not None and (expected is None or value == expected), (expected, value)
        self.index += 1
        return value

    def primary(self):
        token = self.take()
        if token in ('!', '~'):
            tree = ('unary', token, self.primary())
        elif token == '(':
            tree = self.parse(0)
            self.take(')')
        elif token == '{':
            children = [self.parse(0)]
            while self.peek() == ',':
                self.take(',')
                children.append(self.parse(0))
            self.take('}')
            tree = ('concat', children)
        elif token[0].isdigit():
            if "'" in token:
                width, value = token.split("'", 1)
                base = {'b': 2, 'h': 16, 'd': 10, 'o': 8}[value[0]]
                tree = ('constant', int(width), int(value[1:].replace('_', ''), base))
            else:
                tree = ('constant', 32, int(token))
        else:
            tree = ('variable', token)
        while self.peek() == '[':
            self.take('[')
            hi = int(self.take())
            lo = hi
            if self.peek() == ':':
                self.take(':')
                lo = int(self.take())
            self.take(']')
            tree = ('slice', tree, hi, lo)
        return tree

    def parse(self, priority):
        tree = self.primary()
        while self.peek() in self.PRECEDENCE and self.PRECEDENCE[self.peek()] >= priority:
            operation = self.take()
            right = self.parse(self.PRECEDENCE[operation] + 1)
            tree = ('binary', operation, tree, right)
        if priority <= 1 and self.peek() == '?':
            self.take('?')
            yes = self.parse(0)
            self.take(':')
            tree = ('ternary', tree, yes, self.parse(1))
        return tree


def evaluate(tree, variable):
    kind = tree[0]
    if kind == 'constant':
        return tree[1], tree[2] & ((1 << tree[1]) - 1)
    if kind == 'variable':
        return variable(tree[1])
    if kind == 'slice':
        width, value = evaluate(tree[1], variable)
        hi, lo = tree[2:]
        assert 0 <= lo <= hi < width
        return hi - lo + 1, (value >> lo) & ((1 << (hi - lo + 1)) - 1)
    if kind == 'concat':
        width = value = 0
        for child in tree[1]:
            child_width, child_value = evaluate(child, variable)
            width += child_width
            value = (value << child_width) | child_value
        return width, value
    if kind == 'unary':
        width, value = evaluate(tree[2], variable)
        return (1, int(not value)) if tree[1] == '!' else (width, (~value) & ((1 << width) - 1))
    if kind == 'ternary':
        condition = evaluate(tree[1], variable)[1]
        yes, no = evaluate(tree[2], variable), evaluate(tree[3], variable)
        return max(yes[0], no[0]), (yes if condition else no)[1]
    assert kind == 'binary'
    op = tree[1]
    aw, av = evaluate(tree[2], variable)
    bw, bv = evaluate(tree[3], variable)
    if op == '==':
        return 1, int(av == bv)
    if op == '&&':
        return 1, int(bool(av) and bool(bv))
    if op == '||':
        return 1, int(bool(av) or bool(bv))
    return max(aw, bw), {'&': lambda: av & bv, '|': lambda: av | bv, '^': lambda: av ^ bv}[op]()


def wire_expression(text, name):
    matches = re.findall(r'\bwire(?:\s*\[[^\]]+\])?\s+' + re.escape(name) + r'\s*=\s*(.*?);', text, re.S)
    assert len(matches) == 1, (name, 'unique wire expression')
    return SVExpression(matches[0]).tree


def balanced_end(text, start):
    assert text[start] == '('
    depth = 1
    for pos in range(start + 1, len(text)):
        depth += (text[pos] == '(') - (text[pos] == ')')
        if not depth:
            return pos
    raise AssertionError('Unclosed source instance/port')


def instance_ports(text, module, instance):
    matches = list(re.finditer(r'\b' + module + r'\s+' + instance + r'\s*\(', text))
    assert len(matches) == 1, (module, instance)
    start = matches[0].end() - 1
    body = text[start + 1:balanced_end(text, start)]
    ports = {}
    for match in re.finditer(r'\.(\w+)\s*\(', body):
        begin = match.end() - 1
        assert match[1] not in ports
        ports[match[1]] = body[begin + 1:balanced_end(body, begin)]
    return ports


def file_pin(path, expected):
    data = path.read_bytes()
    assert sha(data) == expected, ('Source identity differs', str(path), expected, sha(data))
    return data


def native_path(value):
    return Path(value.replace('\\\\', '\\'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-root', type=Path, default=R2)
    parser.add_argument('--module-root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.resolve().relative_to(ROOT)
    assert not args.output.exists(), 'Keep retained receipts immutable'
    sources, texts = {}, [{}, {}, {}]
    for name in BASE:
        for index, (directory, identities) in enumerate([(V9, BASE), (R1, FIRST), (args.candidate_root, FINAL)]):
            data = file_pin(directory / name, identities[name])
            texts[index][name] = data.decode().replace('\r\n', '\n')
        sources[name] = {'v9_sha256': BASE[name], 'r1_sha256': FIRST[name], 'r2_sha256': FINAL[name]}
    preparer_path = ROOT / 'tests/graphics/prepare_bt_address_class.py'
    spec = importlib.util.spec_from_file_location('bt_address_classes_preparer', preparer_path)
    preparer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(preparer)
    assert preparer.BASE == BASE
    for name in BASE:
        assert preparer.address_class_transform(name, (V9 / name).read_bytes()) == (args.candidate_root / name).read_bytes()
    mc, cpu = texts[2]['rtl/TMS34020/TMS34020_MC.sv'], texts[2]['rtl/TMS34020/TMS34020.sv']
    assert len(re.findall(r'(?<![\w])DBUS_A\s*<=', mc)) == 2
    assert len(re.findall(r'(?<![\w])DBUS_ADDR_CLASS\s*<=', mc)) == 2
    assert "DBUS_ADDR_CLASS <= 4'b0000;" in mc and preparer.NEW_ADDRESS_LOAD in mc
    assert re.search(r'\bLA\s*(?:=|<=)\s*\{\s*DBUS_A\[31:\s*4\]\s*,\s*DBUS_CODE\s*\}', cpu)
    assert cpu.count('.DBUS_ADDR_CLASS(ADDR_CLASS)') == 1
    assert texts[2]['rtl/BT.sv'].count('.ADDR_CLASS(CPU_ADDR_CLASS)') == 1
    class_returns = re.findall(r'AddressClass\s*=\s*(.*?);', mc, re.S)
    assert len(class_returns) == 1
    class_tree = SVExpression(class_returns[0]).tree
    assert evaluate(class_tree, lambda name: (32, 0) if name == 'address' else (_ for _ in ()).throw(AssertionError(name))) == (4, 0)
    class_values = [evaluate(class_tree, lambda name, high=high: (32, high << 22) if name == 'address' else (_ for _ in ()).throw(AssertionError(name)))[1] for high in range(1024)]
    selectors = ['FG_CPU_ADDR_MATCH', 'FG_DISP_SEL', 'FG_DRAW_SEL', 'FG0_SEL', 'FG1_SEL', 'FG0_SCRN', 'FG1_SCRN', 'BG0_SEL', 'BG1_SEL']
    bt_trees = [{name: wire_expression(texts[index]['rtl/BT.sv'], name) for name in selectors} for index in (0, 2)]
    instances = [(module, instance) for module, instance in [('FG_VRAM', 'FG0_VRAM'), ('FG_VRAM', 'FG1_VRAM'), ('BG_VRAM', 'BG0_VRAM_0'), ('BG_VRAM', 'BG0_VRAM_1'), ('BG_VRAM', 'BG1_VRAM_0'), ('BG_VRAM', 'BG1_VRAM_1')]]
    pin_trees, bindings = [[], []], {}
    for module, instance in instances:
        before = instance_ports(texts[0]['rtl/BT.sv'], module, instance)
        after = instance_ports(texts[2]['rtl/BT.sv'], module, instance)
        assert before.keys() == after.keys()
        differing = [port for port in before if normalize(before[port]) != normalize(after[port])]
        assert differing == (['TRANSFER'] if module == 'FG_VRAM' else []), (instance, differing)
        bindings[instance] = {'module': module, 'identical_bound_ports': sorted(set(before) - set(differing)), 'equivalent_bound_ports': differing}
        for port in (['RAS_N', 'TRANSFER'] if module == 'FG_VRAM' else ['RAS_N']):
            pin_trees[0].append((instance + '.' + port, SVExpression(before[port]).tree))
            pin_trees[1].append((instance + '.' + port, SVExpression(after[port]).tree))
    counts, selector_counts, cases = {name: 0 for name, tree in pin_trees[0]}, {name: 0 for name in selectors}, 0
    for high, code, display, ras in itertools.product(range(1024), range(16), range(2), range(2)):
        environment = {'LA': (32, (high << 22) | code), 'CPU_ADDR_CLASS': (4, class_values[high]), 'DISP_CONTROL': (16, display << 15), 'RAS_N': (1, ras)}
        values = []
        for trees in bt_trees:
            memo = dict(environment)
            def variable(name):
                if name not in memo:
                    memo[name] = evaluate(trees[name], variable)
                return memo[name]
            selector_values = {name: variable(name) for name in selectors}
            pins = {name: evaluate(tree, variable) for name, tree in pin_trees[len(values)]}
            values.append((selector_values, pins))
        assert values[0] == values[1], (high, code, display, ras, values)
        for name, value in values[1][0].items():
            selector_counts[name] += bool(value[1])
        for name, value in values[1][1].items():
            counts[name] += bool(value[1])
        cases += 1
    assert cases == 65536 and all(0 < value < cases for value in selector_counts.values())

    # New evidence is a typed composition edge, never a retagged simulator run.
    vendor_data, pin_data = VENDOR_RECEIPT.read_bytes(), PIN_RECEIPT.read_bytes()
    vendor, controller = json.loads(vendor_data), json.loads(pin_data)
    assert vendor['schema'] == 'bt-current-vram-intel-model-v1' and vendor['oracle_ref'] == ORACLE
    assert vendor['source_stability_passed'] and vendor['exit_code'] == 0 and vendor['intel_model_equivalence_passed']
    assert vendor['mapped_atoms_verified'] is False
    assert controller['baseline_ref'] == ORACLE and controller['all_passed']
    assert all(result['exit_code'] == 0 for result in controller['results'])
    actual_sources = {}
    for name, expected in PHYSICAL.items():
        # The frozen fit snapshot contains production inputs, not test adapters.
        # Adapter identity is independently pinned by both retained receipts.
        directories = (V9, args.module_root) if name.startswith('rtl/') else (args.module_root,)
        for directory in directories:
            file_pin(directory / name, expected)
        assert vendor['sources'][name] == expected
        if name != 'rtl/bg_vram.sv':
            assert controller['sources'][name] == expected
        actual_sources[name] = {'path': str((args.module_root / name).resolve()), 'sha256': expected}
    for name, expected in vendor['sources'].items():
        file_pin(ROOT / name, expected)
    for name, expected in vendor['fixtures'].items():
        file_pin(ROOT / name, expected)
    for path, expected in vendor['external_sources'].items():
        file_pin(native_path(path), expected)
    job = native_path(vendor['workspace'])
    log_index = {}
    # Read only this receipt's private workspace, at most one directory level.
    log_paths = list(job.glob('*.log')) + list(job.glob('*/*.log'))
    assert 0 < len(log_paths) <= 32, 'Bounded expected vendor logs'
    for path in log_paths:
        data = path.read_bytes()
        log_index[sha(data)] = (str(path), data.decode(errors='replace'))
    verified_logs = []
    for result in vendor['results']:
        assert result['compile_exit_code'] == 0 and result['simulator'] == 'modelsim'
        compile_path, compile_log = log_index[result['compile_log_sha256']]
        assert not re.search(r'\b(?:fatal|fail|error)\b', compile_log, re.I)
        verified_logs.append({'path': compile_path, 'sha256': result['compile_log_sha256']})
        for run in result['runs']:
            assert run['exit_code'] == 0 and run['passed']
            path, transcript = log_index[run['log_sha256']]
            assert not re.search(r'\b(?:fatal|fail|error)\b', transcript, re.I)
            assert all(marker in transcript for marker in run['markers'])
            verified_logs.append({'path': path, 'sha256': run['log_sha256']})
    for name in ('rtl/fg_vram.sv', 'rtl/BT_mem.sv', 'rtl/bg_vram.sv'):
        original = subprocess.run(['git', '-C', str(ROOT), 'show', ORACLE + ':' + name], check=True, stdout=subprocess.PIPE).stdout
        retained = job / 'oracle' / name
        assert original == retained.read_bytes(), (name, 'immutable full-file Git oracle')
    contract = vendor['canonical_comparison_contract']
    assert contract['mixed_port_mode'] == 'DONT_CARE' and contract['same_port_mode'] == 'NEW_DATA_NO_NBE_READ'
    assert 'without exclusions' in contract['before_candidate_physical_comparison']
    assert 'Only the16 bits' in contract['canonical_sq_exclusions'] and 'Other48' in contract['canonical_sq_exclusions']
    receipt = {
        'schema': 'bt-address-class-r2-vram-composition-v1',
        'passed': True, 'exit_code': 0,
        'scope': 'Fresh source-parsed binary r2 decode truth table and strict unchanged-module/vendor-evidence composition. No simulator executed; original receipts, masks and release validators are unchanged.',
        'source_edge': sources,
        'oracle_root': str(V9), 'candidate_root': str(args.candidate_root.resolve()),
        'helper_sha256': sha(Path(__file__).read_bytes()),
        'preparer_sha256': sha(preparer_path.read_bytes()),
        'truth_table_cases': cases, 'selector_comparisons': cases * len(selectors),
        'actual_pin_comparisons': cases * len(pin_trees[0]),
        'selector_true_counts': selector_counts, 'pin_true_counts': counts,
        'mc_temporal_induction': {
            'base': 'Architected reset sets both DBUS_A and its AddressClass to zero.',
            'step': 'On every original DBUS_A load, the class is captured from the identical address_next RHS in the same nonblocking edge under the unchanged EN/CE_F/!MC_STATE gate and original extension/refresh/read/fetch priority. Otherwise both registers hold. These are their only assignments.',
            'published_binding': 'LA upper bits are DBUS_A upper bits; its low nibble is independently published DBUS_CODE. The class function reads only address[31:22].',
            'domain': 'Reachable binary bus state after architected reset; no new restrictions on RAM collision data or X/Z comparisons.',
        },
        'all_six_vram_instance_bindings': bindings,
        'unchanged_current_module_sources': actual_sources,
        'retained_vendor_receipt': {'path': str(VENDOR_RECEIPT), 'sha256': sha(vendor_data), 'simulator': 'modelsim', 'intel_model_equivalence_passed': True, 'fixtures_and_actual_vendor_rehashed': True, 'original_logs_rehashed': verified_logs, 'oracle_ref': ORACLE},
        'retained_fg_capture_receipt': {'path': str(PIN_RECEIPT), 'sha256': sha(pin_data), 'all_passed': True, 'scope': controller['scope']},
        'collision_contract_unchanged': contract,
        'collision_contract_sha256': sha(json.dumps(contract, sort_keys=True).encode()),
        'composition': 'Equal unchanged input bindings and proved equal request/transfer selectors on every edge feed byte-identical FG/BG state machines and RAM bodies. Thus every RAM capture tuple, collision predicate and output-register edge is identical to the qualified v9 inputs. Retained strict physical before/candidate data and X/Z comparisons and narrow canonical-only exclusions apply without alteration.',
        'new_vendor_simulation_performed': False,
        'mapped_atoms_verified': False, 'routed_timing_qualified': False, 'mister_hardware_qualified': False,
        'complete_mc_phase_simulation_checked_by_this_helper': False,
        'limits': 'Root/rotation owns current full MC/class/stage simulation and actual fitted/release gates. This composition covers the address-class edge and unchanged physical FG/BG modules only; it does not qualify another changed DDR/CPU edge or promote an old receipt to a fresh simulator run.',
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'passed': True, 'receipt': str(args.output.resolve()), 'cases': cases, 'selectors': receipt['selector_comparisons'], 'actual_pins': receipt['actual_pin_comparisons'], 'vendor_simulations_started': 0}))


if __name__ == '__main__':
    main()
