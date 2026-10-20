"""Run the unchanged complete-stage gate with a typed v11 request adapter.

The retained runner is hash pinned and only explicit additive adaptations are
permitted. All of its old stimulus, assertions and identity guards survive.
"""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = Path(__file__).with_name('qualify_bt_current_ddr_be.py')
PIN = 'e2671b083ae908fcdca5df51f83007d1b349b7c48ed971b8641ce19b46d6f0c4'
raw = ORIGINAL.read_bytes()
assert hashlib.sha256(raw).hexdigest() == PIN, 'Retained strict stage runner changed'
text = raw.decode()
edits = []


def replace(before, after):
    global text
    assert text.count(before) == 1, ('Unexpected retained runner contract', before[:120])
    edits.append((before, after))
    text = text.replace(before, after, 1)


replace('from bt_combined_stage_fixture import full_ddr_oracle, augment as augment_combined_ddr_fixture',
        'from bt_combined_stage_fixture import full_ddr_oracle, augment as augment_combined_ddr_fixture\n'
        'from bt_vram_request_fixture import verify_edge as verify_request_edge, augment as augment_request_fixture, full_v11_oracle, visible_complete_state\n'
        'from prepare_bt_vram_request import BASE_ROOT as REQUEST_PARENT_ROOT')
replace('combined_ddr_oracle = {}\n', 'combined_ddr_oracle = {}\n'
        'request_parent_read, request_edge = verify_request_edge(ROOT, source_root, candidate_read)\n'
        'request_oracle_file, request_oracle = full_v11_oracle(directory)\nrequest_scope = {}\n')
replace('verify_address_class_edge(ROOT, candidate_read, original_mc, source_root)',
        'verify_address_class_edge(ROOT, request_parent_read, original_mc, REQUEST_PARENT_ROOT)')
replace('if combined_ddr_oracle:\n    combined_ddr_scope = augment_combined_ddr_fixture(replace_once, top_source)',
        'request_scope = augment_request_fixture(replace_once, fixture, current_mc.decode().replace("\\r\\n", "\\n"),\n'
        '    request_parent_read("rtl/BT.sv").decode(), candidate_read("rtl/BT.sv").decode())\n'
        'if combined_ddr_oracle:\n    combined_ddr_scope = augment_combined_ddr_fixture(replace_once, top_source)')
replace("    'combined_ddr_oracle': combined_ddr_oracle,", "    'combined_ddr_oracle': combined_ddr_oracle,\n"
        "    'vram_request_edge': request_edge, 'vram_request_scope': request_scope, 'vram_request_full_v11_oracle': request_oracle,\n"
        "    'retained_strict_runner': {'path': str(ORIGINAL_RUNNER), 'sha256': ORIGINAL_RUNNER_SHA256},")
replace("assert execution.count(\"'rtl/BT.sv',\") == 1", "execution = execution.replace(\"'rtl/TMS34020/TMS34020_MC.sv',\", repr(relative(request_oracle_file)) + \", 'rtl/TMS34020/TMS34020_MC.sv',\", 1)\n"
        "assert execution.count(\"'rtl/BT.sv',\") == 1")
replace('execution = LEGACY.read_text()', 'execution = visible_complete_state(LEGACY.read_text())')
replace("coverage_labels = [('EARLY_PALETTE'", "coverage_labels = [('VRAM_REQUEST','vram_request_coverage'),('VRAM_REQUEST_PROBE','vram_request_probe_coverage'),('EARLY_PALETTE'")
restored = text
for before, after in reversed(edits):
    assert restored.count(after) == 1
    restored = restored.replace(after, before, 1)
assert restored.encode() == raw, 'Retained stage runner could not be recovered exactly'
exec(compile(text, str(Path(__file__)), 'exec'), {'__name__': '__main__', '__file__': str(Path(__file__)),
     'ORIGINAL_RUNNER': ORIGINAL, 'ORIGINAL_RUNNER_SHA256': PIN})
