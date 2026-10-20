"""Check production LMO/RMO (BtOneLocate) against MAME 0.289 34010ops.hxx.

MAME: LMO = leading-zero count, RMO = trailing-zero count, both 0 for Rs=0.
Battletoads selects its per-frame object Y-sort pass with RMO; an inverted
RMO (31 - bit) skips the sort, so sprites draw in list order.
"""
import random
import re
import subprocess
import sys
import uuid
from pathlib import Path

root = Path(__file__).resolve().parents[1]
# Optional argument: alternate CPU source (negative control against old RTL).
src = Path(sys.argv[1] if len(sys.argv) > 1 else root / 'rtl/TMS34020/TMS34020.sv').read_text()
m = re.search(r'\tfunction bit \[4:0\] BtOneLocate\(.*?endfunction', src, re.S)
assert m, 'BtOneLocate not found'


def ref(val, rmo):
    if val == 0:
        return 0
    if rmo:
        return (val & -val).bit_length() - 1
    return 31 - (val.bit_length() - 1)


rng = random.Random(0xB7)
values = [0, 1, 2, 3, 0x80000000, 0xffffffff, 0x7fffffff, 0xfffffffe, 0x00010000, 0x0000ffff]
values += [1 << i for i in range(32)] + [((1 << 32) - 1) ^ ((1 << i) - 1) for i in range(32)]
values += [rng.getrandbits(32) >> rng.randrange(32) for _ in range(4000)]
vectors = ''.join(f'{v:08x} {d} {ref(v, d):02x}\n' for v in values for d in (0, 1))

def wsl_path(p):
    p = Path(p).resolve()
    return '/mnt/' + p.drive[0].lower() + p.as_posix()[2:]


work = root / 'build' / ('one_locate-' + uuid.uuid4().hex[:8])
work.mkdir(parents=True)
(work / 'vectors.hex').write_text(vectors)
(work / 'tb.sv').write_text(f'''module tb;
{m.group(0)}
    integer f, n, errors = 0, checks = 0;
    bit [31:0] v; bit d; bit [4:0] e;
    initial begin
        f = $fopen("{wsl_path(work / 'vectors.hex')}", "r");
        while (!$feof(f)) begin
            n = $fscanf(f, "%h %h %h\\n", v, d, e);
            if (n == 3) begin
                checks++;
                if (BtOneLocate(v, d) !== e) begin
                    errors++;
                    if (errors < 10) $display("MISMATCH %s val=%08h got=%0d exp=%0d", d ? "RMO" : "LMO", v, BtOneLocate(v, d), e);
                end
            end
        end
        if (errors) $fatal(1, "FAIL one-locate: %0d/%0d mismatches", errors, checks);
        $display("PASS one-locate: %0d LMO/RMO vectors match MAME", checks);
        $finish;
    end
endmodule
''')
wsl = ['wsl.exe', '-d', 'Ubuntu', '--cd', str(root), '--exec']
cmd = wsl + ['/usr/bin/verilator', '--binary', '--assert', '-Wno-fatal', '--top-module', 'tb',
             '--Mdir', wsl_path(work / 'obj'), wsl_path(work / 'tb.sv')]
r = subprocess.run(cmd, capture_output=True, text=True)
if r.returncode:
    sys.exit(r.stdout[-3000:] + r.stderr[-3000:])
r = subprocess.run(wsl + [wsl_path(work / 'obj' / 'Vtb')], capture_output=True, text=True)
out = r.stdout + r.stderr
(work / 'run.log').write_text(out)
print(out.strip())
sys.exit(0 if r.returncode == 0 and 'PASS one-locate' in out and 'FAIL' not in out else 1)
