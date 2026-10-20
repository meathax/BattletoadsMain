"""Source-parsed ROBDD proof and compiled immutable-oracle locator regression.

The ROBDD interpreter accepts only the unsigned 2-state straight-line subset
actually used by these functions.  Every expression is parsed from retained SV;
unsupported syntax fails.  Equality covers all 2**33 val/direction inputs.
"""
import argparse
from functools import reduce
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
sha = lambda value: hashlib.sha256(value).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BDD:
    def __init__(self):
        self.variables = ['dir'] + [f'val[{i}]' for i in range(31, -1, -1)]
        self.nodes = [(-1, 0, 0), (-1, 1, 1)]
        self.unique, self.cache, self.neg_cache = {}, {}, {0: 1, 1: 0}

    def node(self, var, lo, hi):
        if lo == hi:
            return lo
        key = (var, lo, hi)
        if key not in self.unique:
            assert len(self.nodes) < 2_000_000, 'Bounded BDD node budget exceeded'
            self.unique[key] = len(self.nodes)
            self.nodes.append(key)
        return self.unique[key]

    def neg(self, value):
        if value not in self.neg_cache:
            var, lo, hi = self.nodes[value]
            result = self.node(var, self.neg(lo), self.neg(hi))
            self.neg_cache[value] = result
            self.neg_cache[result] = value
        return self.neg_cache[value]

    def apply(self, op, left, right):
        if left > right:
            left, right = right, left
        if op == '&':
            if left == 0 or right == 0:
                return 0
            if left == 1:
                return right
            if left == right:
                return left
        elif op == '|':
            if left == 1 or right == 1:
                return 1
            if left == 0:
                return right
            if left == right:
                return left
        elif op == '^':
            if left == 0:
                return right
            if left == 1:
                return self.neg(right)
            if left == right:
                return 0
        else:
            raise AssertionError(('Unsupported BDD operator', op))
        key = (op, left, right)
        if key not in self.cache:
            lv = self.nodes[left][0] if left > 1 else 33
            rv = self.nodes[right][0] if right > 1 else 33
            var = min(lv, rv)
            assert var < 33
            _, ll, lh = self.nodes[left] if lv == var else (var, left, left)
            _, rl, rh = self.nodes[right] if rv == var else (var, right, right)
            self.cache[key] = self.node(var, self.apply(op, ll, rl), self.apply(op, lh, rh))
        return self.cache[key]

    def any(self, bits):
        return reduce(lambda a, b: self.apply('|', a, b), bits, 0)

    def mux(self, cond, yes, no):
        return self.apply('|', self.apply('&', cond, yes), self.apply('&', self.neg(cond), no))

    def evaluate(self, value, val, direction):
        while value > 1:
            var, lo, hi = self.nodes[value]
            selected = direction if var == 0 else ((val >> (32-var)) & 1)
            value = hi if selected else lo
        return value

    def witness(self, value):
        assert value != 0
        val, direction = 0, 0
        while value > 1:
            var, lo, hi = self.nodes[value]
            selected = hi != 0
            if selected:
                if var == 0:
                    direction = 1
                else:
                    val |= 1 << (32-var)
            value = hi if selected else lo
        return {'val': val, 'dir': direction}

    def certificate(self, old_bits, new_bits):
        assert old_bits == new_bits
        for index, (var, lo, hi) in enumerate(self.nodes[2:], 2):
            assert lo != hi and lo < index and hi < index
            assert self.unique[(var, lo, hi)] == index
            assert all(child <= 1 or self.nodes[child][0] > var for child in (lo, hi))
        return {'variable_order': self.variables, 'nodes': self.nodes,
                'old_outputs_lsb_first': old_bits, 'new_outputs_lsb_first': new_bits,
                'universal_input_count': 2**33}


class Expression:
    TOKEN = re.compile(r"\s*(?:(\d+'[bBdDhH][0-9a-fA-F_]+)|([A-Za-z_]\w*)|(\d+)|([\[\]{}():?!~&|^,]))")

    def __init__(self, text, env, bdd):
        self.tokens, position = [], 0
        while position < len(text):
            match = self.TOKEN.match(text, position)
            if not match:
                assert not text[position:].strip(), ('Unsupported SV expression', text[position:])
                break
            self.tokens.append(next(group for group in match.groups() if group is not None))
            position = match.end()
        self.i, self.env, self.bdd = 0, env, bdd

    def take(self, expected=None):
        assert self.i < len(self.tokens), ('Truncated expression', expected)
        value = self.tokens[self.i]
        if expected is not None:
            assert value == expected, (expected, value)
        self.i += 1
        return value

    def peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    @staticmethod
    def width(bits, size):
        assert size >= len(bits)
        return bits + (0,) * (size-len(bits))

    def parse(self):
        result = self.ternary()
        assert self.i == len(self.tokens), ('Trailing expression tokens', self.tokens[self.i:])
        return result

    def ternary(self):
        result = self.binary(0)
        if self.peek() == '?':
            self.take('?')
            yes = self.ternary()
            self.take(':')
            no = self.ternary()
            size = max(len(yes), len(no))
            cond = self.bdd.any(result)
            result = tuple(self.bdd.mux(cond, a, b) for a, b in
                           zip(self.width(yes, size), self.width(no, size)))
        return result

    def binary(self, level):
        operators = ['|', '^', '&']
        if level == len(operators):
            return self.unary()
        result = self.binary(level+1)
        while self.peek() == operators[level]:
            op = self.take()
            right = self.binary(level+1)
            size = max(len(result), len(right))
            result = tuple(self.bdd.apply(op, a, b) for a, b in
                           zip(self.width(result, size), self.width(right, size)))
        return result

    def unary(self):
        token = self.peek()
        if token in {'!', '~', '|', '&', '^'}:
            self.take()
            value = self.unary()
            if token == '!':
                return (self.bdd.neg(self.bdd.any(value)),)
            if token == '~':
                return tuple(self.bdd.neg(bit) for bit in value)
            if token == '|':
                return (self.bdd.any(value),)
            if token == '&':
                return (reduce(lambda a, b: self.bdd.apply('&', a, b), value, 1),)
            return (reduce(lambda a, b: self.bdd.apply('^', a, b), value, 0),)
        return self.primary()

    def primary(self):
        token = self.take()
        if token == '(':
            result = self.ternary()
            self.take(')')
            return result
        if token == '{':
            if self.peek() and self.peek().isdigit() and self.tokens[self.i+1] == '{':
                count = int(self.take())
                self.take('{')
                value = self.ternary()
                self.take('}')
                self.take('}')
                return value * count
            groups = [self.ternary()]
            while self.peek() == ',':
                self.take(',')
                groups.append(self.ternary())
            self.take('}')
            return tuple(bit for group in reversed(groups) for bit in group)
        literal = re.fullmatch(r"(\d+)'([bBdDhH])([0-9a-fA-F_]+)", token)
        if literal:
            size, base, digits = literal.groups()
            size = int(size)
            number = int(digits.replace('_', ''), {'b': 2, 'd': 10, 'h': 16}[base.lower()])
            assert size > 0 and number < 2**size
            return tuple((number >> i) & 1 for i in range(size))
        assert token in self.env, ('Undeclared expression input', token)
        result = self.env[token]
        if self.peek() == '[':
            self.take('[')
            high = int(self.take())
            low = high
            if self.peek() == ':':
                self.take(':')
                low = int(self.take())
            self.take(']')
            assert 0 <= low <= high < len(result)
            result = result[low:high+1]
        return result


def interpret(function, bdd):
    function = re.sub(r'//[^\n]*|/\*.*?\*/', '', function, flags=re.S)
    header, body = function.split(';', 1)
    assert re.fullmatch(r'\s*function\s+bit\s*\[\s*4\s*:\s*0\s*\]\s+\w+\s*\(\s*input\s+bit\s*\[\s*31\s*:\s*0\s*\]\s+val\s*,\s*input\s+bit\s+dir\s*\)', header)
    assert body.rstrip().endswith('endfunction')
    body = body.rstrip()[:-len('endfunction')]
    env = {'dir': (bdd.node(0, 0, 1),),
           'val': tuple(bdd.node(32-i, 0, 1) for i in range(32))}
    assigned = {'val': (True,)*32, 'dir': (True,)}
    returned = None
    count = 0
    for statement in body.split(';'):
        statement = statement.strip()
        if not statement:
            continue
        assert returned is None, 'Statement after function return'
        declaration = re.fullmatch(r'bit\s*\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*(\w+(?:\s*,\s*\w+)*)', statement)
        if declaration:
            high, low, names = declaration.groups()
            assert int(low) == 0
            for name in re.split(r'\s*,\s*', names):
                assert name not in env
                env[name] = (0,) * (int(high)+1)
                assigned[name] = (False,) * (int(high)+1)
            continue
        if statement.startswith('return '):
            expression = statement[len('return '):]
            # All locals in these functions are fully assigned, not stateful.
            assert all(all(bits) for bits in assigned.values()), 'Unassigned static function local'
            returned = Expression(expression, env, bdd).parse()
            assert len(returned) == 5
            continue
        assignment = re.fullmatch(r'(\w+)(?:\[\s*(\d+)\s*(?::\s*(\d+)\s*)?\])?\s*=\s*(.*)', statement, re.S)
        assert assignment, ('Unsupported function statement', statement)
        name, high, low, expression = assignment.groups()
        assert name in env and name not in {'val', 'dir'}
        # Reject reads of not-yet-assigned local bits.  Declarations never act
        # as implicit storage or as invented zero constants in this proof.
        for used in re.findall(r'\b[A-Za-z_]\w*\b', expression):
            if used in assigned and used not in {'val', 'dir'}:
                uses = list(re.finditer(r'\b' + re.escape(used) + r'\b(?:\[\s*(\d+)\s*(?::\s*(\d+)\s*)?\])?', expression))
                for use in uses:
                    hi, lo = use.groups()
                    valid = assigned[used] if hi is None else assigned[used][int(lo or hi):int(hi)+1]
                    assert valid and all(valid), ('Read before assignment', used, expression)
        value = Expression(expression, env, bdd).parse()
        high = len(env[name])-1 if high is None else int(high)
        low = 0 if low is None and high == len(env[name])-1 and '[' not in statement.split('=')[0] else int(low or high)
        assert 0 <= low <= high < len(env[name]) and len(value) == high-low+1
        bits = list(env[name])
        marks = list(assigned[name])
        bits[low:high+1] = value
        marks[low:high+1] = (True,) * len(value)
        env[name], assigned[name] = tuple(bits), tuple(marks)
        count += 1
    assert returned is not None
    return returned, count


def reject(name, operation, controls):
    try:
        operation()
    except (AssertionError, ValueError):
        controls.append({'name': name, 'rejected': True})
        return
    raise AssertionError('Negative control accepted: ' + name)


def compare_functions(old, new):
    bdd = BDD()
    old_bits, old_count = interpret(old, bdd)
    new_bits, new_count = interpret(new, bdd)
    if old_bits != new_bits:
        mismatch = bdd.any(tuple(bdd.apply('^', a, b) for a, b in zip(old_bits, new_bits)))
        raise AssertionError(('Locator differs', bdd.witness(mismatch)))
    return bdd, old_bits, new_bits, old_count, new_count


def testbench(old_function, new_function, bdd, bits):
    original = old_function.replace(' OneLocate(', ' OneLocateOracle(', 1)
    seed = random.Random(0x414c55424c4f43)
    vectors = [(0, 0), (0, 1), (0xffffffff, 0), (0xffffffff, 1)]
    vectors += [(1 << i, d) for i in range(32) for d in range(2)]
    vectors += [(seed.getrandbits(32), seed.getrandbits(1)) for _ in range(1980)]
    assert len(vectors) == 2048
    expected = []
    for val, direction in vectors:
        result = sum(bdd.evaluate(bit, val, direction) << i for i, bit in enumerate(bits))
        expected.append(f"    check_bdd(32'h{val:08x}, 1'b{direction}, 5'd{result});")
    return '''`timescale 1ns/1ps
module cpu_onelocate_tb;
''' + original + '\n' + new_function + '''
  longint unsigned checks = 0;
  longint unsigned bdd_checks = 0;
  bit [31:0] rng = 32'h73a1bc29;
  integer i, j, n, offset;
  task automatic check(input bit [31:0] val, input bit dir);
    bit [4:0] oracle, candidate;
    oracle = OneLocateOracle(val, dir);
    candidate = BtOneLocate(val, dir);
    if (oracle !== candidate)
      $fatal(1,"OneLocate val=%h dir=%b oracle=%d candidate=%d",val,dir,oracle,candidate);
    checks++;
  endtask
  task automatic check_bdd(input bit [31:0] val, input bit dir, input bit [4:0] expected);
    if (OneLocateOracle(val, dir) !== expected || BtOneLocate(val, dir) !== expected)
      $fatal(1,"BDD/source disagreement val=%h dir=%b expected=%d",val,dir,expected);
    bdd_checks++;
  endtask
  initial begin
''' + '\n'.join(expected) + '''
    check(0,0); check(0,1); check(32'hffffffff,0); check(32'hffffffff,1);
    for(i=0;i<32;i++) begin
      check(32'h1<<i,0); check(32'h1<<i,1);
      check(~(32'h1<<i),0); check(~(32'h1<<i),1);
      for(j=i+1;j<32;j++) begin
        check((32'h1<<i)|(32'h1<<j),0); check((32'h1<<i)|(32'h1<<j),1);
        check(~((32'h1<<i)|(32'h1<<j)),0); check(~((32'h1<<i)|(32'h1<<j)),1);
      end
    end
    for(n=0;n<65536;n++) begin
      for(offset=0;offset<=16;offset+=4) begin
        check(32'(n)<<offset,0); check(32'(n)<<offset,1);
      end
    end
    for(n=0;n<1048576;n++) begin
      rng ^= rng << 13; rng ^= rng >> 17; rng ^= rng << 5;
      check(rng,0); check(rng,1);
    end
    if(checks != 2754628 || bdd_checks != 2048) $fatal(1,"Coverage count changed %d/%d",checks,bdd_checks);
    $display("PASS CPU_ONELOCATE checks=%0d bdd_checks=%0d random_words=1048576 windows=327680 zero_cases=4",checks,bdd_checks);
    $finish;
  end
endmodule
'''


def file_record(path):
    return {'path': str(path.resolve()), 'sha256': sha(path.read_bytes())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edge', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    edge, output = args.edge.resolve(), args.output.resolve()
    edge.relative_to(ROOT / 'build')
    output.relative_to(ROOT / 'build')
    assert not output.exists(), 'Never overwrite a proof'
    output.mkdir(parents=True)
    preparer = load(ROOT / 'tests/graphics/prepare_bt_parallel_onelocate.py', 'parallel_onelocate_edge')
    manifest_path = edge / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    assert manifest['helper_sha256'] == sha(Path(preparer.__file__).read_bytes())
    old_cpu_path, package_path = edge / ('oracle/' + preparer.CPU_PATH), edge / ('oracle/' + preparer.PACKAGE_PATH)
    candidate_path = edge / ('candidate/' + preparer.CPU_PATH)
    old_cpu, package, candidate = old_cpu_path.read_bytes(), package_path.read_bytes(), candidate_path.read_bytes()
    assert sha(old_cpu) == preparer.CPU_SHA and sha(package) == preparer.PACKAGE_SHA
    assert manifest['candidate_sha256'][preparer.CPU_PATH] == sha(candidate)
    assert preparer.reverse(candidate) == old_cpu and preparer.transform(old_cpu) == candidate
    old_function = preparer.extract_function(package.decode(), 'OneLocate')
    new_function = preparer.extract_function(candidate.decode(), 'BtOneLocate')
    assert sha(old_function.encode()) == manifest['old_function_sha256']
    assert sha(new_function.encode()) == manifest['new_function_sha256']
    started = time.monotonic()
    bdd, old_bits, new_bits, old_count, new_count = compare_functions(old_function, new_function)
    certificate_path = output / 'bdd-certificate.json'
    certificate_path.write_text(json.dumps(bdd.certificate(old_bits, new_bits), separators=(',', ':')) + '\n')
    proof_seconds = time.monotonic()-started
    controls = []
    reject('foreign_parent_raw_hash', lambda: preparer.transform(old_cpu + b'\n'), controls)
    reject('missing_call', lambda: preparer.reverse(candidate.replace(preparer.NEW_CALL.encode(), b'LOC_RES = 0;', 1)), controls)
    reject('duplicate_call', lambda: preparer.reverse(candidate + preparer.NEW_CALL.encode()), controls)
    reject('foreign_cpu_body_change', lambda: preparer.reverse(candidate + b'// unrelated change\n'), controls)
    reject('wrong_zero_direction_case', lambda: compare_functions(old_function, new_function.replace('~dir | (|val)', 'dir | (|val)', 1)), controls)
    reject('dropped_highest_nibble', lambda: compare_functions(old_function, new_function.replace('high_group[7] = present[7];', "high_group[7] = 1'b0;", 1)), controls)
    reject('swapped_direction', lambda: compare_functions(old_function, new_function.replace('dir ? low_index : high_index', 'dir ? high_index : low_index', 1)), controls)
    reject('modified_immutable_oracle', lambda: compare_functions(old_function.replace('res ^ {5{~dir}}', 'res ^ {5{dir}}', 1), new_function), controls)
    reject('unsupported_signed_arithmetic', lambda: interpret(new_function.replace('index = dir ? low_index : high_index;', 'index = low_index + high_index;', 1), BDD()), controls)
    bench_path = output / 'cpu_onelocate_tb.sv'
    bench_path.write_text(testbench(old_function, new_function, bdd, old_bits))
    command = ['wsl.exe', '-d', 'Ubuntu', '--cd', str(ROOT), '--exec', 'verilator',
               '--binary', '--timing', '--top-module', 'cpu_onelocate_tb', '-Wno-fatal',
               '-j', '2', '--Mdir', str(output.relative_to(ROOT)).replace('\\', '/') + '/obj',
               str(bench_path.relative_to(ROOT)).replace('\\', '/')]
    version_command = ['wsl.exe', '-d', 'Ubuntu', '--cd', str(ROOT), '--exec', 'verilator', '--version']
    version = subprocess.run(version_command, capture_output=True, text=True)
    (output / 'version.log').write_text(version.stdout + version.stderr)
    assert version.returncode == 0
    compile_result = subprocess.run(command, capture_output=True, text=True)
    compile_log = output / 'compile.log'
    compile_log.write_text(compile_result.stdout + compile_result.stderr)
    assert compile_result.returncode == 0, ('Compilation failed', str(compile_log))
    run_command = ['wsl.exe', '-d', 'Ubuntu', '--cd', str(ROOT), '--exec',
                   './' + str(output.relative_to(ROOT)).replace('\\', '/') + '/obj/Vcpu_onelocate_tb']
    run_result = subprocess.run(run_command, capture_output=True, text=True)
    run_log = output / 'run.log'
    run_log.write_text(run_result.stdout + run_result.stderr)
    assert run_result.returncode == 0, ('Simulation failed', str(run_log))
    marker = re.search(r'PASS CPU_ONELOCATE checks=(\d+) bdd_checks=(\d+) random_words=(\d+) windows=(\d+) zero_cases=(\d+)', run_result.stdout)
    assert marker and tuple(map(int, marker.groups())) == (2754628, 2048, 1048576, 327680, 4)
    artifacts = [manifest_path, old_cpu_path, package_path, candidate_path, certificate_path,
                 bench_path, compile_log, run_log, output / 'version.log',
                 ROOT / 'tests/graphics/prepare_bt_parallel_onelocate.py', Path(__file__)]
    receipt = {
        'schema': 'bt-cpu-parallel-onelocate-qualification-v1',
        'status': 'PASS', 'edge': str(edge),
        'source_sha256': manifest['source_sha256'],
        'candidate_sha256': manifest['candidate_sha256'],
        'full_cpu_raw_inverse_identical': True,
        'proof': {'kind': 'source-parsed canonical reduced ordered binary decision diagram',
                  'inputs': 33, 'universal_input_count': 2**33, 'outputs': 5,
                  'old_assignment_count': old_count, 'new_assignment_count': new_count,
                  'bdd_nodes': len(bdd.nodes), 'seconds': proof_seconds,
                  'old_output_node_ids': old_bits, 'new_output_node_ids': new_bits,
                  'compositional_scope': 'Exact pure locator equality plus full-CPU inverse byte identity proves every old CPU output/state transition unchanged for all 2-state locator inputs; no register or latency change'},
        'compiled_checks': {'oracle_vs_candidate': 2754628, 'source_vs_bdd': 2048,
                            'random_words': 1048576, 'exhaustive_16_bit_windows': 327680,
                            'both_directions': True, 'walking_bits': True, 'all_two_bit_pairs': True},
        'negative_controls': controls,
        'commands': {'version': version_command, 'compile': command, 'run': run_command},
        'return_codes': {'version': version.returncode, 'compile': compile_result.returncode, 'run': run_result.returncode},
        'version': version.stdout.strip(),
        'artifacts': [file_record(path) for path in artifacts],
        'timing_accepted': False,
        'limitations': ['No new fitted timing, board native replay or hardware claim.',
                        'Functions retain original bit input/local/result types and therefore the same 4-state-to-2-state coercion; ROBDD domain is the resulting 2-state inputs.',
                        'Parallel nibble structure is a timing hypothesis until exact-source fitting; the reported path is dominated by routing.'],
    }
    receipt_path = output / 'receipt.json'
    receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'status': 'PASS', 'receipt': str(receipt_path), 'receipt_sha256': sha(receipt_path.read_bytes()),
                      'candidate_sha256': sha(candidate), 'bdd_inputs': 33, 'bdd_nodes': len(bdd.nodes),
                      'compiled_checks': receipt['compiled_checks'], 'negative_controls': len(controls)}, indent=2))


if __name__ == '__main__':
    main()
