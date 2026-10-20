"""Prepare a reversible v18 sprite mirror output replication in a private directory."""
import argparse
import base64
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / 'build/timing_closure_20261011/reset_partition_v18_private-snapshot.json'
SNAPSHOT_SHA = 'd4f54c0fb3b6a076177fc2382105c664d740d82482a6ca612e0418c5282880d8'
FILES = ('rtl/spr_vram.sv', 'rtl/BT.sv')
LOCAL_BLOCK = ''' generate if (LOCAL_FG_Q) begin : local_foreground_q
  (* preserve, dont_merge *) reg [63:0] fg0_q = 64'b0;
  (* preserve, dont_merge *) reg [63:0] fg1_q = 64'b0;
  // Capture the original mirror's D on its original edge, never its old Q.
  always @(posedge CLK) begin
   fg0_q<=raw_q;
   fg1_q<=raw_q;
  end
  assign FG0_Q=fg0_q;
  assign FG1_Q=fg1_q;
 end else begin : shared_foreground_q
  assign FG0_Q=Q;
  assign FG1_Q=Q;
 end endgenerate
'''


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha(path):
    return sha_bytes(Path(path).read_bytes())


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def variants(text):
    raw = text.encode('ascii')
    return (raw, raw.replace(b'\n', b'\r\n')) if b'\n' in raw else (raw,)


def replacement(data, before, after):
    matches = [old for old in variants(before) if data.count(old)]
    assert len(matches) == 1 and data.count(matches[0]) == 1, ('Source anchor changed', before)
    old = matches[0]
    newline = b'\r\n' if b'\r\n' in old or (b'\n' not in old and b'\r\n' in data) else b'\n'
    new = after.encode('ascii').replace(b'\n', newline)
    return data.replace(old, new), dict(before=base64.b64encode(old).decode(),
                                        after=base64.b64encode(new).decode(), kind='unique_replacement')


def forward_spr(data):
    operations = []
    substitutions = [
        ('module SPR_VRAM (', 'module SPR_VRAM #(parameter LOCAL_FG_Q=0) ('),
        ('\toutput [3:0] BLIT_NONZERO\n);',
         '\toutput [3:0] BLIT_NONZERO,\n\toutput [63:0] FG0_SHIFT_Q,\n\toutput [63:0] FG1_SHIFT_Q\n);'),
        ('BT_SPR_POST_NONZERO_MIRROR #(10) read_mirror(',
         'BT_SPR_POST_NONZERO_MIRROR #(10,LOCAL_FG_Q) read_mirror('),
        ('.Q(mirror_q),.NZ(mirror_nz)',
         '.Q(mirror_q),.NZ(mirror_nz),.FG0_Q(FG0_SHIFT_Q),.FG1_Q(FG1_SHIFT_Q)'),
        ('module BT_SPR_POST_NONZERO_MIRROR #(parameter addr_width=10)(',
         'module BT_SPR_POST_NONZERO_MIRROR #(parameter addr_width=10,parameter LOCAL_FG_Q=0)('),
        (" output reg [63:0] Q=64'b0,output reg [15:0] NZ=16'b0\n);",
         " output reg [63:0] Q=64'b0,output reg [15:0] NZ=16'b0,\n output [63:0] FG0_Q,FG1_Q\n);"),
    ]
    for before, after in substitutions:
        data, op = replacement(data, before, after)
        operations.append(op)
    assert data.count(b'module BT_SPR_POST_NONZERO_MIRROR ') == 1
    pos = data.rfind(b'endmodule')
    assert pos >= 0 and not data[pos + len(b'endmodule'):].strip()
    newline = b'\r\n' if b'\r\n' in data[data.index(b'module BT_SPR_POST_NONZERO_MIRROR '):] else b'\n'
    block = LOCAL_BLOCK.encode().replace(b'\n', newline)
    assert block not in data
    data = data[:pos] + block + data[pos:]
    operations.append(dict(before='', after=base64.b64encode(block).decode(), kind='insert_final_module_block'))
    return data, operations


def forward_bt(data):
    operations = []
    substitutions = [
        ('\twire [63:0] FG0_COPY_DATA, FG1_COPY_DATA, CPU_SHIFT_Q;',
         '\twire [63:0] FG0_COPY_DATA, FG1_COPY_DATA, CPU_SHIFT_Q;\n\twire [63:0] FG0_SHIFT_Q, FG1_SHIFT_Q;'),
        ('\tSPR_VRAM SPR_VRAM (', '\tSPR_VRAM #(.LOCAL_FG_Q(1)) SPR_VRAM ('),
        ('\t\t.CPU_SHIFT_A(FG0_COPY_RD ? FG0_COPY_A : FG1_COPY_A),\n\t\t.CPU_SHIFT_Q(CPU_SHIFT_Q),',
         '\t\t.CPU_SHIFT_A(FG0_COPY_RD ? FG0_COPY_A : FG1_COPY_A),\n\t\t.CPU_SHIFT_Q(CPU_SHIFT_Q),\n\t\t.FG0_SHIFT_Q(FG0_SHIFT_Q), .FG1_SHIFT_Q(FG1_SHIFT_Q),'),
    ]
    for fg in (0, 1):
        substitutions.append((
            ".CPU_SHIFT(LA[3:0] == 4'b0101), .CPU_SHIFT_Q(CPU_SHIFT_Q),\n\t\t.MEM_CE(CE_R), .HOLE_A(FG%d_HOLE_A)" % fg,
            ".CPU_SHIFT(LA[3:0] == 4'b0101), .CPU_SHIFT_Q(FG%d_SHIFT_Q),\n\t\t.MEM_CE(CE_R), .HOLE_A(FG%d_HOLE_A)" % (fg, fg)))
    for before, after in substitutions:
        data, op = replacement(data, before, after)
        operations.append(op)
    return data, operations


def inverse(data, operations):
    for op in reversed(operations):
        before, after = (base64.b64decode(op[key]) for key in ('before', 'after'))
        assert after and data.count(after) == 1, ('Candidate edge changed', op['kind'])
        data = data.replace(after, before)
    return data


def verify_edge(directory):
    directory = Path(directory)
    manifest = read_json(directory / 'manifest.json')
    assert manifest['schema'] == 'bt-v18-sprite-local-mirror-q-edge-v1'
    assert sha(SNAPSHOT) == SNAPSHOT_SHA == manifest['parent_snapshot']['sha256']
    snapshot = read_json(SNAPSHOT)
    parent = Path(snapshot['project']).parent
    for name, record in manifest['sources'].items():
        original = (directory / 'oracle' / name).read_bytes()
        candidate = (directory / 'candidate' / name).read_bytes()
        assert sha_bytes(original) == record['parent_sha256'] == snapshot['sources'][name]
        assert sha(parent / name) == record['parent_sha256']
        assert sha_bytes(candidate) == record['candidate_sha256']
        assert inverse(candidate, record['operations']) == original
        regenerated, operations = (forward_spr if name == FILES[0] else forward_bt)(original)
        assert regenerated == candidate and operations == record['operations']
    assert set(manifest['sources']) == set(FILES)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    target = args.output.resolve()
    target.relative_to(ROOT)
    assert not target.exists()
    assert sha(SNAPSHOT) == SNAPSHOT_SHA
    snapshot = read_json(SNAPSHOT)
    parent = Path(snapshot['project']).parent
    records = {}
    for name in FILES:
        original = (parent / name).read_bytes()
        assert sha_bytes(original) == snapshot['sources'][name]
        candidate, operations = (forward_spr if name == FILES[0] else forward_bt)(original)
        assert inverse(candidate, operations) == original
        for folder, data in [('oracle', original), ('candidate', candidate)]:
            output = target / folder / name
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(data)
        records[name] = dict(parent_sha256=sha_bytes(original), candidate_sha256=sha_bytes(candidate),
                             operations=operations, full_raw_byte_inverse_passed=True)
    manifest = dict(schema='bt-v18-sprite-local-mirror-q-edge-v1',
        parent_snapshot=dict(path=str(SNAPSHOT), sha256=SNAPSHOT_SHA),
        sources=records, helper=dict(path=str(Path(__file__).resolve()), sha256=sha(__file__)),
        additional_soft_register_bits=128, additional_memory_bits=0,
        original_output_edge='Q<=raw_q on every posedge CLK, initialized0, no reset or enable',
        local_output_edges='fg0_q<=raw_q and fg1_q<=raw_q on identical posedge CLK, initialized0',
        original_Q_NZ_and_all_RAM_processes_unchanged=True,
        interface='Default-off LOCAL_FG_Q; original port order retained, two outputs appended',
        consumer_mapping={'FG0_VRAM.CPU_SHIFT_Q':'SPR_VRAM.FG0_SHIFT_Q',
                          'FG1_VRAM.CPU_SHIFT_Q':'SPR_VRAM.FG1_SHIFT_Q'},
        constraints_changed=False, root_modified=False, timing_accepted=False,
        mapped_replication_proven=False, qualified=False)
    (target / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    verify_edge(target)
    print(json.dumps(dict(candidate=str(target / 'candidate'), manifest=str(target / 'manifest.json'),
                          manifest_sha256=sha(target / 'manifest.json'),
                          sources={name: value['candidate_sha256'] for name, value in records.items()}),
                     separators=(',', ':')))


if __name__ == '__main__':
    main()
