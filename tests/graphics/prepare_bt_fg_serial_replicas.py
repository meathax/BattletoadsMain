"""Prepare the private bank-local FG serial RAM candidate from frozen f3.

Preserves the original shiftreg and its complete output/consumer path. Three
new instances have identical old inputs and parameters, with only Q redirected.
"""
import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FG_SOURCE = ROOT / 'build/fg_serial_controls_v12_v2/candidate/rtl/fg_vram.sv'
FG_SHA = 'f3b4c19de2f64d018860a7c3480b0393f4ec9a6f39f004160c1a2c696f84750b'
SPR_SHA = 'c876714b5432df11b8a3e14ab9847ba9ad2a05a96f31a4a3548c57e321c7fb4c'
LEAVES = {
    'rtl/BT_mem.sv': '903aeedc272fd64409ebae8b8624befe82bc1f073d1545310dbeb070afaf6393',
    'tests/graphics/ram_models.sv': '039f6ead2da5edfeaa0bf4aeb45eb7795ccf3e57e6193ea3e7763a41ae2cdafc',
}
ORIGINAL_SHIFTREG = '''\tVRAM_SHIFTREG #(9,1,1) shiftreg
\t(
\t\t.CLK(CLK),
\t\t.ACLR(~RST_N),
\t\t.WADDR(SRW_A),
\t\t.DATA(SRW_D),
\t\t.WREN(SRW_E),
\t\t.RADDR(RMT_EXEC && !CPU_COPY_MODE ? SREG_POS[8:3] : SR_RA[8:3]),
\t\t.Q(SR_Q)
\t);'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def check(condition, message):
    if not condition:
        raise ValueError(message)


def prepare(fg_source, output):
    check(not output.exists() and output.is_relative_to(ROOT/'build'), 'Fresh private build directory required')
    raw = {'rtl/fg_vram.sv': fg_source.read_bytes(), 'rtl/spr_vram.sv': (ROOT/'rtl/spr_vram.sv').read_bytes()}
    expected = {'rtl/fg_vram.sv': FG_SHA, 'rtl/spr_vram.sv': SPR_SHA}
    check({name: sha(data) for name, data in raw.items()} == expected, 'Frozen source changed')
    check({name: sha((ROOT/name).read_bytes()) for name in LEAVES} == LEAVES, 'RAM leaf/model changed')
    original = {name: data.decode().replace('\r\n', '\n') for name, data in raw.items()}
    candidate = dict(original)
    edits = {name: [] for name in raw}

    def change(name, before, after):
        check(candidate[name].count(before) == 1, 'Transform anchor changed: '+name)
        candidate[name] = candidate[name].replace(before, after, 1)
        edits[name].append({'before': before, 'after': after})

    fg = 'rtl/fg_vram.sv'
    change(fg, '\twire [63:0] SERIAL_WRITE_WORD = SR_Q;',
        '\twire [63:0] SERIAL_WRITE_WORD = SR_Q;\n'
        '\t// Bank zero retains the original RAM; three identical RAMs serve the other banks.\n'
        '\t(* keep *) wire [3:0][63:0] SERIAL_WRITE_WORD_B;\n'
        '\tassign SERIAL_WRITE_WORD_B[0] = SERIAL_WRITE_WORD;')
    change(fg, '.SERIAL_SEGMENT_PRE(1)) mem', '.SERIAL_SEGMENT_PRE(1), .SERIAL_DATA_LOCAL(1)) mem')
    change(fg, '.SDATA_S(SERIAL_WRITE_WORD),', '.SDATA_S(SERIAL_WRITE_WORD), .SDATA_SB(SERIAL_WRITE_WORD_B),')
    replica = ORIGINAL_SHIFTREG.replace('.Q(SR_Q)', '.Q(SERIAL_WRITE_WORD_B[serial_replica])')
    check(replica.replace('.Q(SERIAL_WRITE_WORD_B[serial_replica])', '.Q(SR_Q)') == ORIGINAL_SHIFTREG,
          'Replica has a changed non-Q pin')
    replica = '\n'.join('\t'+line for line in replica.splitlines())
    block = '''

\t// Identical old write/read edges, byte enables, clear, initialization and OLD_DATA
\t// collision behavior. The original named shiftreg still supplies video and SR_Q.
\tgenerate for (genvar serial_replica=1; serial_replica<4; serial_replica=serial_replica+1) begin : serial_write_replicas
REPLICA
`ifndef SYNTHESIS
\t\talways @(negedge CLK)
\t\t\tassert (SERIAL_WRITE_WORD_B[serial_replica] === SR_Q)
\t\t\t\telse $fatal(1,"FG bank serial RAM replica differs in data or X state");
`endif
\tend endgenerate'''.replace('REPLICA', replica)
    change(fg, ORIGINAL_SHIFTREG, ORIGINAL_SHIFTREG+block)
    change(fg, 'parameter SERIAL_SEGMENT_PRE = 0) (',
        'parameter SERIAL_SEGMENT_PRE = 0, parameter SERIAL_DATA_LOCAL = 0) (')
    change(fg, '    input [3:0][3:0] SWREN_SEG_B\n);',
        '    input [3:0][3:0] SWREN_SEG_B,\n'
        '    // Appended optional input: legacy/default instances retain shared SDATA_S.\n'
        '    input [3:0][63:0] SDATA_SB\n);')
    bank_anchor = '    generate for (bank=0;bank<4;bank=bank+1) begin : banks\n'
    change(fg, bank_anchor, bank_anchor+'        wire [63:0] bank_serial_word = SERIAL_DATA_LOCAL ? SDATA_SB[bank] : SDATA_S;\n')
    serial_mux = '{SCSEL4[bank][3] ? SDATA_C[63:48] : SDATA_S[63:48], SCSEL4[bank][2] ? SDATA_C[47:32] : SDATA_S[47:32], SCSEL4[bank][1] ? SDATA_C[31:16] : SDATA_S[31:16], SCSEL4[bank][0] ? SDATA_C[15:0] : SDATA_S[15:0]}'
    change(fg, serial_mux, serial_mux.replace('SDATA_S[', 'bank_serial_word['))
    change('rtl/spr_vram.sv', ' output reg [63:0] Q=64\'b0,output reg [15:0] NZ=16\'b0',
        ' (* preserve, maxfan = 4 *) output reg [63:0] Q=64\'b0,output reg [15:0] NZ=16\'b0')

    for name, changes in edits.items():
        restored = candidate[name]
        for edit in reversed(changes):
            check(restored.count(edit['after']) == 1, 'Reverse anchor changed')
            restored = restored.replace(edit['after'], edit['before'], 1)
        check(restored == original[name], 'Whole source reversal failed')
    check(candidate[fg].count(ORIGINAL_SHIFTREG) == 1, 'Original shiftreg instance/output changed')
    check('SERIAL_DATA_LOCAL = 0' in candidate[fg] and 'SDATA_SB\n);' in candidate[fg], 'Optional interface not appended/default-off')
    check(candidate['rtl/spr_vram.sv'].replace('(* preserve, maxfan = 4 *) ', '') == original['rtl/spr_vram.sv'],
          'Sprite producer changed beyond attributes')
    sources = {}
    for name, text in candidate.items():
        path = output/'candidate'/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode())
        parent = output/'immutable_parent'/name
        parent.parent.mkdir(parents=True, exist_ok=True)
        parent.write_bytes(raw[name])
        sources[name] = sha(path.read_bytes())
    leaf = (ROOT/'rtl/BT_mem.sv').read_text()
    signature = leaf[leaf.index('module VRAM_SHIFTREG'):]
    signature = signature[:signature.index('endmodule')+len('endmodule')]
    result = {'schema': 'bt-fg-serial-ram-replicas-transform-v1', 'status': 'PASS',
        'qualification': 'Source transform and identical-pin RAM induction only; focused behavioral and Intel collision simulation and physical fit remain required.',
        'parent_sources': expected, 'candidate_sources': sources, 'parent_source_paths': {'rtl/fg_vram.sv': str(fg_source), 'rtl/spr_vram.sv': str(ROOT/'rtl/spr_vram.sv')},
        'unchanged_leaf_sources': LEAVES, 'transform_source_sha256': sha(Path(__file__).read_bytes()),
        'edits': edits, 'exact_source_reversal_lf': True, 'serialization': 'Parent raw bytes retained; CRLF-to-LF canonical transform; candidate written as LF.',
        'original_shiftreg_preserved': True, 'replica_count_per_fg': 3, 'total_shiftreg_instances_per_fg': 4,
        'identical_original_replica_signature': {'module': 'VRAM_SHIFTREG', 'parameters': [9, 1, 1],
            'CLK': 'CLK', 'ACLR': '~RST_N', 'WADDR': 'SRW_A', 'DATA': 'SRW_D', 'WREN': 'SRW_E',
            'RADDR': 'RMT_EXEC && !CPU_COPY_MODE ? SREG_POS[8:3] : SR_RA[8:3]',
            'only_changed_pin': 'Q', 'leaf_module_lf_sha256': sha(signature.encode())},
        'ram_contract': {'rows': 64, 'word_bits': 64, 'byte_enables': 8, 'mixed_port_read_during_write': 'OLD_DATA',
            'registered_read_address': True, 'registered_output': True, 'output_async_clear': True, 'power_up_uninitialized': False},
        'banked_parameter_default': 0, 'banked_new_port_appended': 'SDATA_SB', 'new_data_capture_edges': 0,
        'sprite_attribute_only': {'preserve': True, 'maxfan': 4, 'original_producer_reset_init_and_assignment_body_identical': True,
            'quartus17_reference': 'https://resources.altera.com/quartushelp/17.0/hdl/vlog/vlog_file_dir.htm'},
        'additional_storage_bits_two_fg_instances': 24576, 'physical_m10k_count': 'Pending native map; no inference/resource claim'}
    (output/'manifest.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'status': 'PASS', 'candidate': str(output/'candidate'), 'sources': sources,
                      'manifest_sha256': sha((output/'manifest.json').read_bytes())}, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fg-source', type=Path, default=FG_SOURCE)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.fg_source.resolve(), args.output.resolve())


if __name__ == '__main__':
    main()
