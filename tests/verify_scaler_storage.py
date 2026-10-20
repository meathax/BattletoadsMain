"""Prove scalar scaler storage preserves its record representation and timing."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/scaler_storage'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', type=Path, required=True)
    args = parser.parse_args()
    source = (ROOT / 'sys/ascal.vhd').read_text()
    before = args.baseline.read_text()
    # Apart from storage encoding and RAM placement, the complete scaler must
    # match the original source, including clocks, addresses and write guards.
    normalized = re.sub(
        r'\t-- Keep RAM words scalar.*?(?=\tTYPE arr_pixq)', '', source, flags=re.S)
    normalized = normalized.replace('arr_pix_ram(', 'arr_pix(')
    normalized = normalized.replace('pack_pix(i_ldw)', 'i_ldw')
    normalized = normalized.replace('pack_pix(o_ldw)', 'o_ldw')
    normalized = re.sub(
        r'unpack_pix\(((?:i_mem|o_line[0-3]|o_linf[0-3])\([^)]*\))\)',
        r'\1', normalized)
    for placement in ('MLAB', 'M10K'):
        normalized = normalized.replace(f'"{placement}, no_rw_check"', '"no_rw_check"')
        before = before.replace(f'"{placement}, no_rw_check"', '"no_rw_check"')
    assert ([line.rstrip() for line in normalized.splitlines()] ==
            [line.rstrip() for line in before.splitlines()]), \
        'Scaler control/timing changed beyond RAM encoding'

    declarations = source[source.index('\tTYPE type_pix IS RECORD'):
                          source.index('\tTYPE arr_pixq')]
    bench = '''library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
entity scaler_storage_tb is end;
architecture test of scaler_storage_tb is
''' + declarations + '''
begin
    process
        variable p, q : type_pix;
        variable packed : unsigned(23 downto 0);
    begin
        for i in 0 to 16777215 loop
            p := (r => to_unsigned(i / 65536, 8),
                  g => to_unsigned((i / 256) mod 256, 8),
                  b => to_unsigned(i mod 256, 8));
            packed := pack_pix(p);
            assert packed = to_unsigned(i, 24)
                report "RGB lane mismatch" severity failure;
            q := unpack_pix(packed);
            assert q = p report "RGB round-trip mismatch" severity failure;
        end loop;
        report "PASS all 16777216 RGB values through production VHDL codec";
        std.env.stop;
        wait;
    end process;
end;
'''
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'scaler_storage_tb.vhd').write_text(bench)
    commands = [['ghdl', '-a', '--std=08', 'scaler_storage_tb.vhd'],
                ['ghdl', '-e', '--std=08', 'scaler_storage_tb'],
                ['ghdl', '-r', '--std=08', 'scaler_storage_tb', '--assert-level=error']]
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    logs = []
    for command in commands:
        result = subprocess.run(command, cwd=OUT, check=True, creationflags=flags,
                                capture_output=True, text=True)
        logs.append(result.stdout + result.stderr)
    log = '\n'.join(logs)
    (OUT / 'ghdl.log').write_text(log)
    assert 'PASS all 16777216 RGB values' in log, 'Simulator completion marker missing'
    print(log.strip())
    receipt = {'baseline': str(args.baseline.resolve()),
               'baseline_sha256': hashlib.sha256(args.baseline.read_bytes()).hexdigest(),
               'source_sha256': hashlib.sha256((ROOT / 'sys/ascal.vhd').read_bytes()).hexdigest(),
               'commands': commands, 'rgb_cases': 16777216,
               'control_and_timing_unchanged': True}
    (OUT / 'receipt.json').write_text(json.dumps(receipt, indent=2))
    print('PASS entire scaler control/address/timing source preserved')


if __name__ == '__main__':
    main()
