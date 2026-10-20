"""Source-interpreted ROBDD proof for the two-state shift function subset.

This deliberately small interpreter accepts only the function syntax used here.
The same parsed expressions are evaluated over canonical Boolean decision
diagrams, with controls ordered before data. No HDL oracle is reimplemented.
"""
from __future__ import annotations
import re


class BDD:
    def __init__(self, names):
        self.names = tuple(names)
        self.nodes = {0: None, 1: None}
        self.unique = {}
        self.cache = {}
        self.neg_cache = {0: 1, 1: 0}

    def node(self, var, lo, hi):
        if lo == hi:
            return lo
        key = (var, lo, hi)
        if key not in self.unique:
            n = len(self.nodes)
            self.unique[key] = n
            self.nodes[n] = key
        return self.unique[key]

    def var(self, name):
        return self.node(self.names.index(name), 0, 1)

    def neg(self, n):
        if n not in self.neg_cache:
            var, lo, hi = self.nodes[n]
            self.neg_cache[n] = self.node(var, self.neg(lo), self.neg(hi))
        return self.neg_cache[n]

    def op(self, op, a, b):
        a, b = sorted((a, b))
        if op == '&':
            if not a: return 0
            if a == 1: return b
            if a == b: return a
        elif op == '|':
            if a == 1 or b == 1: return 1
            if not a: return b
            if a == b: return a
        elif op == '^':
            if a == b: return 0
            if not a: return b
            if a == 1: return self.neg(b)
        key = (op, a, b)
        if key in self.cache:
            return self.cache[key]
        av = self.nodes[a][0] if a > 1 else 10**9
        bv = self.nodes[b][0] if b > 1 else 10**9
        var = min(av, bv)
        al, ah = self.nodes[a][1:] if av == var else (a, a)
        bl, bh = self.nodes[b][1:] if bv == var else (b, b)
        out = self.node(var, self.op(op, al, bl), self.op(op, ah, bh))
        self.cache[key] = out
        return out

    def ite(self, c, yes, no):
        return self.op('|', self.op('&', c, yes), self.op('&', self.neg(c), no))

    def evaluate(self, node, assignment):
        while node > 1:
            var, lo, hi = self.nodes[node]
            node = hi if assignment[self.names[var]] else lo
        return node


def const(n, width):
    return [(n >> i) & 1 for i in range(width)]


class Expr:
    token = re.compile(r"\s*(\d+'[bBdDhH][0-9a-fA-F_]+|[A-Za-z_]\w*|\d+|~&|~\||>=|<=|==|!=|[{}()\[\],?:!~&|^+\-])")
    precedence = {'|': 2, '^': 3, '&': 4, '>=': 5, '==': 5, '+': 7}

    def __init__(self, text, env, bdd):
        self.tokens, pos = [], 0
        while pos < len(text):
            m = self.token.match(text, pos)
            assert m, ('unsupported HDL expression', text[pos:])
            self.tokens.append(m[1]); pos = m.end()
        self.i, self.env, self.bdd = 0, env, bdd

    def peek(self): return self.tokens[self.i] if self.i < len(self.tokens) else None
    def take(self, expected=None):
        t = self.peek()
        assert t is not None and (expected is None or t == expected), (t, expected)
        self.i += 1
        return t

    def reduce(self, op, value):
        n = 1 if op == '&' else 0
        for bit in value: n = self.bdd.op(op, n, bit)
        return n

    def align(self, a, b):
        size = max(len(a), len(b))
        return a + [0]*(size-len(a)), b + [0]*(size-len(b))

    def binary(self, op, a, b):
        a, b = self.align(a, b)
        if op in ('&', '|', '^'):
            return [self.bdd.op(op, x, y) for x, y in zip(a, b)]
        if op == '+':
            out, carry = [], 0
            for x, y in zip(a, b):
                xy = self.bdd.op('^', x, y)
                out.append(self.bdd.op('^', xy, carry))
                carry = self.bdd.op('|', self.bdd.op('&', x, y), self.bdd.op('&', xy, carry))
            return out
        if op == '==':
            return [self.bdd.neg(self.reduce('|', self.binary('^', a, b)))]
        if op == '>=':
            greater, equal = 0, 1
            for x, y in zip(reversed(a), reversed(b)):
                greater = self.bdd.op('|', greater, self.bdd.op('&', equal, self.bdd.op('&', x, self.bdd.neg(y))))
                equal = self.bdd.op('&', equal, self.bdd.neg(self.bdd.op('^', x, y)))
            return [self.bdd.op('|', greater, equal)]
        raise AssertionError(op)

    def primary(self):
        t = self.take()
        if t in ('!', '~', '|', '&', '~&', '~|'):
            value = self.primary()
            if t == '~': result = [self.bdd.neg(x) for x in value]
            elif t == '!': result = [self.bdd.neg(self.reduce('|', value))]
            else:
                result = [self.reduce(t[-1], value)]
                if t.startswith('~'): result = [self.bdd.neg(result[0])]
        elif t == '(':
            result = self.expression(); self.take(')')
        elif t == '{':
            if self.peek().isdigit() and self.i+1 < len(self.tokens) and self.tokens[self.i+1] == '{':
                count = int(self.take()); self.take('{')
                value = self.expression(); self.take('}'); self.take('}')
                result = value * count
            else:
                parts = [self.expression()]
                while self.peek() == ',': self.take(); parts.append(self.expression())
                self.take('}')
                result = [x for part in reversed(parts) for x in part]
        elif "'" in t:
            width, digits = t.split("'", 1)
            result = const(int(digits[1:].replace('_', ''), {'b': 2, 'd': 10, 'h': 16}[digits[0].lower()]), int(width))
        elif t.isdigit(): result = const(int(t), 32)
        else:
            assert t in self.env, ('unknown HDL variable', t)
            result = self.env[t][:]
        while self.peek() == '[':
            self.take(); high = int(self.take())
            if self.peek() == ':': self.take(); low = int(self.take())
            else: low = high
            self.take(']')
            assert 0 <= low <= high < len(result)
            result = result[low:high+1]
        return result

    def expression(self, minimum=0):
        out = self.primary()
        while self.peek() in self.precedence and self.precedence[self.peek()] >= minimum:
            op = self.take(); out = self.binary(op, out, self.expression(self.precedence[op]+1))
        if minimum == 0 and self.peek() == '?':
            self.take(); yes = self.expression(); self.take(':'); no = self.expression()
            yes, no = self.align(yes, no)
            c = self.reduce('|', out)
            out = [self.bdd.ite(c, x, y) for x, y in zip(yes, no)]
        return out

    def parse(self):
        out = self.expression()
        assert self.i == len(self.tokens), ('unparsed HDL tokens', self.tokens[self.i:])
        return out


def execute(function_text, inputs, bdd):
    text = re.sub(r'//[^\n]*', '', function_text)
    text = text[text.index(';')+1:text.rindex('endfunction')]
    # A constant-bound synthesis loop is expanded without changing arithmetic
    # widths: each 5'(32-n) value is in [2,31] and fits exactly in five bits.
    loop = ("for (int n = 1; n < 31; n = n + 1)\n"
            "\t\t\tterms[n - 1] = (val[n] ^ val[31]) & (sa >= 5'(32 - n));")
    if 'for (' in text:
        assert text.count(loop) == 1, 'unexpected synthesis loop'
        text = text.replace(loop, '\n'.join(f"terms[{n-1}] = (val[{n}] ^ val[31]) & (sa >= 5'd{32-n});" for n in range(1,31)))
    env = {name: value[:] for name, value in inputs.items()}
    returned = None
    for statement in text.split(';'):
        statement = statement.strip()
        if not statement: continue
        if statement.startswith('bit '):
            m = re.fullmatch(r'bit\s+(?:\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*)?(.+)', statement, re.S)
            assert m, statement
            width = int(m[1])-int(m[2])+1 if m[1] else 1
            for name in m[3].split(','): env[name.strip()] = [0]*width
            continue
        if statement.startswith('return '):
            assert returned is None
            returned = Expr(statement[7:], env, bdd).parse(); continue
        lhs, rhs = statement.split('=', 1)
        lhs = lhs.strip(); value = Expr(rhs.strip(), env, bdd).parse()
        if lhs.startswith('{'):
            names = [name.strip() for name in lhs[1:-1].split(',')]
            width = sum(len(env[name]) for name in names)
            value = (value+[0]*width)[:width]
            offset = 0
            for name in reversed(names):
                size = len(env[name]); env[name] = value[offset:offset+size]; offset += size
        elif '[' in lhs:
            m = re.fullmatch(r'(\w+)\[(\d+)\]', lhs); assert m, lhs
            env[m[1]][int(m[2])] = value[0]
        else:
            assert lhs in env, lhs
            env[lhs] = (value+[0]*len(env[lhs]))[:len(env[lhs])]
    assert returned is not None
    return returned


def prove(old_carry, new_carry, old_overflow, new_overflow):
    names = [f'code[{i}]' for i in reversed(range(4))] + [f'sa[{i}]' for i in reversed(range(5))] + [f'val[{i}]' for i in reversed(range(32))]
    bdd = BDD(names)
    inputs = {name: [bdd.var(f'{name}[{i}]') for i in range(size)] for name, size in (('val',32),('sa',5),('code',4))}
    oc, nc = execute(old_carry, inputs, bdd), execute(new_carry, inputs, bdd)
    ov, nv = execute(old_overflow, inputs, bdd), execute(new_overflow, inputs, bdd)
    assert len(oc) == len(nc) == 33 and len(ov) == len(nv) == 1
    assert oc == nc and ov == nv, 'source-interpreted universal function equivalence failed'
    return {'method': 'Canonical ROBDD over parsed actual two-state SystemVerilog function expressions',
            'carry_input_bits': 41, 'carry_input_assignments': 2**41, 'carry_equal_output_bits': 33,
            'overflow_input_bits': 37, 'overflow_input_assignments': 2**37, 'overflow_equal_output_bits': 1,
            'bdd_nodes': len(bdd.nodes), 'all_miter_bits_identically_zero': True,
            'compatibility': 'Unroll fixed n=1..30 loop and evaluate representable five-bit constant casts; preserve unsigned widths, truncation, concatenation, reductions and ordered function assignments.'}
