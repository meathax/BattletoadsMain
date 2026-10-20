"""Private monitor-only CPU change, with exact input and synthesis preservation."""
from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'build/en0_snapshot_b537_20261011/candidate'
OUT = ROOT / 'build/final_cpu_checker_b537_v1'
PINS = {
    'Arcade-Battletoads.sv': 'b1a1b77918f8c9a883f349a221db7830c0a3126dcc144d0bcd80c7a0359580da',
    'files.qip': '461a5b38500e876ef060fe3ffdd378b96a3eb0622d2cd71060741b5f446a0fd9',
    'rtl/BT.sv': '69e8eef01824c66356c4e1427f5bab3509534aba39c23df01a3dce713be2672b',
    'rtl/TMS34020/TMS34020.sv': 'd658300d7d8fd58845b299b1c92d1e62488f66f878b337d6716df991c151e05e',
    'rtl/TMS34020/TMS34020_MC.sv': '01bc6d0da7355616fa615b3c75132e85ab30810f68c5474620fb045b8be25531',
    'rtl/bt_pause_bridge.sv': '050593e64fe70cfb8fb3331a1d5fed87a4d28cd3eb0793e673a37ddb3114ad96',
    'rtl/bt_clock_enables.sv': 'ac4777d7e89fab97fc11eb7b22ca241c708531641fff8e9d7ce449cbf6ac8dfd',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def no_simulation(text):
    # This checker is excluded by the release preprocessor macro, rather than
    # translate_off. Pin the complete, unnested guard before excluding it.
    pattern = r'(?m)^\s*`ifdef MISTER_CPU_PHASE_CHECK\s*\n(.*?)^\s*`endif[^\n]*\n'
    matches = list(re.finditer(pattern, text, flags=re.S))
    assert len(matches) == 3, 'expected three phase-check macro regions'
    for match in matches:
        assert not re.search(r'(?m)^\s*`(?:if|else|endif)', match.group(1)), 'nested guard changed'
    text = re.sub(pattern, '', text, flags=re.S)
    return re.sub(r'// synthesis translate_off.*?// synthesis translate_on', '', text, flags=re.S)


def main():
    files = {}
    for name, pin in PINS.items():
        data = (BASE / name).read_bytes()
        assert sha(data) == pin, 'frozen base changed: ' + name
        files[name] = data
    path = 'rtl/TMS34020/TMS34020.sv'
    old = files[path].decode()
    original = 'if (RST_N && CE_R) assert (MC_DIN === MC_DIN_F)'
    corrected = 'if (RST_N && EN && CE_R) assert (MC_DIN === MC_DIN_F)'
    assert old.count(original) == 1
    new = old.replace(original, corrected)
    old_comment = '// R-phase consumers read the early capture; it equals the CE_F capture at every CE_R.'
    new_comment = '// Enabled R-phase consumers read the early capture; it equals the CE_F capture.'
    assert new.count(old_comment) == 1
    new = new.replace(old_comment, new_comment)
    assert new.replace(corrected, original).replace(new_comment, old_comment) == old
    assert no_simulation(old) == no_simulation(new), 'synthesized source changed'
    assert old.index('`ifdef MISTER_CPU_PHASE_CHECK') < old.index(original) < old.index('`endif', old.index('`ifdef MISTER_CPU_PHASE_CHECK'))
    files[path] = new.encode()
    nvram_path = ROOT / 'build/pause_nvram_b537_v2/candidate/rtl/bt_nvram.sv'
    nvram = nvram_path.read_bytes()
    assert sha(nvram) == '665fd23ada6bf9fd0377baf5412ce0c8525bd8f9cb4f67f82b81aae03183f4dc'
    old_nvram = (BASE / 'rtl/bt_nvram.sv').read_bytes()
    assert old_nvram[old_nvram.index(b');') + 2:] == nvram[nvram.index(b');') + 2:], 'NVRAM body changed'
    files['rtl/bt_nvram.sv'] = nvram
    for name, data in files.items():
        target = OUT / 'candidate' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            assert target.read_bytes() == data, 'private candidate changed: ' + str(target)
        else:
            target.write_bytes(data)
    cases = []
    for rst in (0, 1):
        for en in (0, 1):
            for r in (0, 1):
                active = bool(rst and en and r)
                cases.append({'RST_N': rst, 'EN': en, 'CE_R': r,
                              'original_checker_active': bool(rst and r),
                              'architectural_consumer_active': active,
                              'new_checker_active': active})
    receipt = {'schema': 'bt-cpu-return-checker-preservation-v1', 'status': 'PASS',
               'candidate_root': str(OUT / 'candidate'),
               'base_root': str(BASE), 'base_sources': PINS,
               'sources': {n: sha(d) for n, d in files.items()},
               'original_checker_predicate': 'RST_N && CE_R',
               'new_checker_predicate': 'RST_N && EN && CE_R',
               'checker_values_and_failure_unchanged': True,
               'synthesis_source_identical': True,
                'checker_exclusion': 'MISTER_CPU_PHASE_CHECK undefined in release',
               'synthesis_source_sha256': sha(no_simulation(old).encode()),
               'enable_cases': cases,
               'nonconsumer_differences_retained_in_full_stage_receipts': {
                   'production': 3301, 'alternating': 4328},
               'full_stage_receipts': [
                   'tests/graphics/evidence/ddr-be-bridge/ddr-be-bridge-f4e18e10168a4800b872975fa30ab146/receipt.json',
                   'tests/graphics/evidence/ddr-be-bridge/ddr-be-bridge-24a218137fd0458e9ebdbd8b7035fe96/receipt.json'],
               'scope': 'monitor enable and byte-identical synthesized CPU; full CPU replay remains required',
               'helper_sha256': sha(Path(__file__).read_bytes())}
    (OUT / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'receipt': str(OUT / 'receipt.json'), **receipt}, sort_keys=True))


if __name__ == '__main__':
    main()
