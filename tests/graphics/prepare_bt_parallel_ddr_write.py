#!/usr/bin/env python3
"""Prepare a reversible, hash-bound private DDR source-capture candidate."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = {
    'rtl/BT.sv': '69e8eef01824c66356c4e1427f5bab3509534aba39c23df01a3dce713be2672b',
    'rtl/ddram.sv': 'a29089154fbcdca55ac9b68f17d9a60b188750782724031613c93c2bc24274a3',
    'Arcade-Battletoads.sv': 'b1a1b77918f8c9a883f349a221db7830c0a3126dcc144d0bcd80c7a0359580da',
}
PARALLEL = '''\t// BT_PARALLEL_DDR_DATA_BEGIN
\t// Raw data and the exact existing owner are sampled together by ddram.
\t// Source order: sprite, foreground zero, foreground one, CPU bus.
\tassign EDATA_CANDIDATES[0] = {8'b0,SPR_DRAW_DATA,8'b0,SPR_DRAW_DATA};
\tassign EDATA_CANDIDATES[1] = FG0_HOLE_DATA;
\tassign EDATA_CANDIDATES[2] = FG1_HOLE_DATA;
\tassign EDATA_CANDIDATES[3] = LDO;
\tassign EDATA_SELECT[0] = SPR_DDR_REQ;
\tassign EDATA_SELECT[1] = !SPR_DDR_REQ && FG_HOLE_COPY && FG0_HOLE_SEL;
\tassign EDATA_SELECT[2] = !SPR_DDR_REQ && FG_HOLE_COPY && !FG0_HOLE_SEL;
\tassign EDATA_SELECT[3] = !SPR_DDR_REQ && !FG_HOLE_COPY;
\t// BT_PARALLEL_DDR_DATA_END
'''
CAPTURE = '''\t// BT_PARALLEL_DDR_CAPTURE_BEGIN
\t// Preserve the acceptance edge. The owner no longer gates wide raw-data
\t// register inputs; selection happens after the four words are captured.
\t// Module-scope write_data* names retain the existing qualified endpoint
\t// family. Owner registers are separate, ordinary single-cycle targets.
\t(* preserve, dont_merge *) reg [3:0][31:0] write_data_parallel;
\t(* preserve, dont_merge *) reg [3:0][31:0] write_data_o_parallel;
\treg [31:0] write_data_serial;
\t(* preserve, dont_merge *) reg [31:0] write_data_o_serial;
\tgenerate if (USE_PARALLEL_DIN) begin : parallel_write_capture
\t\t(* preserve, dont_merge *) reg [3:0] cache_owner, beat_owner;
\t\talways @(posedge clk) if (!rst && write_prepend && sclk) begin
\t\t\twrite_data_parallel <= parallel_din;
\t\t\twrite_data_o_parallel <= parallel_din;
\t\t\tcache_owner <= parallel_din_sel;
\t\t\tbeat_owner <= parallel_din_sel;
\t\tend
\t\tassign write_data =
\t\t\t(write_data_parallel[0] & {32{cache_owner[0]}}) |
\t\t\t(write_data_parallel[1] & {32{cache_owner[1]}}) |
\t\t\t(write_data_parallel[2] & {32{cache_owner[2]}}) |
\t\t\t(write_data_parallel[3] & {32{cache_owner[3]}});
\t\tassign write_data_o =
\t\t\t(write_data_o_parallel[0] & {32{beat_owner[0]}}) |
\t\t\t(write_data_o_parallel[1] & {32{beat_owner[1]}}) |
\t\t\t(write_data_o_parallel[2] & {32{beat_owner[2]}}) |
\t\t\t(write_data_o_parallel[3] & {32{beat_owner[3]}});
`ifndef SYNTHESIS
\t\talways @(posedge clk) if (!rst && write_prepend && sclk)
\t\t\tassert ($onehot(parallel_din_sel) && din ==
\t\t\t\t((parallel_din[0] & {32{parallel_din_sel[0]}}) |
\t\t\t\t (parallel_din[1] & {32{parallel_din_sel[1]}}) |
\t\t\t\t (parallel_din[2] & {32{parallel_din_sel[2]}}) |
\t\t\t\t (parallel_din[3] & {32{parallel_din_sel[3]}})))
\t\t\telse $fatal(1,"DDR parallel source/owner changed accepted input word");
`endif
\tend else begin : serial_write_capture
\t\talways @(posedge clk) if (!rst && write_prepend && sclk) begin
\t\t\twrite_data_serial <= din;
\t\t\twrite_data_o_serial <= din;
\t\tend
\t\tassign write_data = write_data_serial;
\t\tassign write_data_o = write_data_o_serial;
\tend endgenerate
\t// BT_PARALLEL_DDR_CAPTURE_END

'''

def sha(data):
    return hashlib.sha256(data).hexdigest()

def prepare(base, output):
    assert not output.exists(), 'Candidate directory already exists'
    assert output.is_relative_to(ROOT / 'build'), 'Private build directory required'
    raw = {name: (base / name).read_bytes() for name in BASE}
    assert {name: sha(data) for name, data in raw.items()} == BASE, 'Frozen v9 source changed'
    edits = {name: [] for name in BASE}
    current = {name: data.decode().replace('\r\n', '\n') for name, data in raw.items()}

    def change(name, before, after):
        assert current[name].count(before) == 1, 'Transform anchor changed: ' + name
        current[name] = current[name].replace(before, after, 1)
        edits[name].append({'before': before, 'after': after})

    change('rtl/BT.sv', '`endif\n);\n\n\tbit [31: 0] LA;',
           '`endif\n\t, output [3:0][31:0] EDATA_CANDIDATES\n\t, output [3:0] EDATA_SELECT\n);\n\n\tbit [31: 0] LA;')
    anchor = "\tassign EDATA = SPR_DDR_REQ ? {8'b0,SPR_DRAW_DATA,8'b0,SPR_DRAW_DATA} :"
    change('rtl/BT.sv', anchor, PARALLEL + anchor)
    change('rtl/ddram.sv', 'parameter USE_PREDECODED_MISS=0)', 'parameter USE_PREDECODED_MISS=0, parameter USE_PARALLEL_DIN=0)')
    change('rtl/ddram.sv', '\toutput reg [31: 0] dbg_din\n);',
           '\toutput reg [31: 0] dbg_din,\n\tinput [3:0][31:0] parallel_din,\n\tinput [3:0] parallel_din_sel\n);')
    change('rtl/ddram.sv', '\treg  [ 31:  0] write_data;', '\twire [31:0] write_data;')
    change('rtl/ddram.sv', '\t(* preserve, dont_merge *) reg [ 31:  0] write_data_o;', '\twire [31:0] write_data_o;')
    change('rtl/ddram.sv', '\t\t\twrite_data <= din;\n\t\t\twrite_data_o <= din;\n', '')
    change('rtl/ddram.sv', '\talways @(posedge clk) begin\n\t\tbit old_io_rd, old_io_we;',
           CAPTURE + '\talways @(posedge clk) begin\n\t\tbit old_io_rd, old_io_we;')
    change('Arcade-Battletoads.sv', '\t\t.EDATA(BT_EDATA),',
           '\t\t.EDATA(BT_EDATA),\n\t\t.EDATA_CANDIDATES(bt_edata_candidates), .EDATA_SELECT(bt_edata_select),')
    change('Arcade-Battletoads.sv', '\twire [31: 0] ddr_do;',
           '\twire [3:0][31:0] bt_edata_candidates;\n\twire [3:0] bt_edata_select;\n\twire [31: 0] ddr_do;')
    change('Arcade-Battletoads.sv', '.USE_PREDECODED_MISS(1)) ddram', '.USE_PREDECODED_MISS(1), .USE_PARALLEL_DIN(1)) ddram')
    change('Arcade-Battletoads.sv', '\t\t.din (BT_EDATA),',
           '\t\t.din (BT_EDATA),\n\t\t.parallel_din(bt_edata_candidates), .parallel_din_sel(bt_edata_select),')
    sources = {}
    for name, body in current.items():
        reverse = body
        for edit in reversed(edits[name]):
            assert reverse.count(edit['after']) == 1 if edit['after'] else True
            # Empty removal is reversed at its surviving neighboring anchor.
            if not edit['after']:
                reverse = reverse.replace('\t\t\twrite_addr <= addr;\n', '\t\t\twrite_addr <= addr;\n' + edit['before'], 1)
            else:
                reverse = reverse.replace(edit['after'], edit['before'], 1)
        assert reverse == raw[name].decode().replace('\r\n', '\n'), 'Changed body beyond declared edge: ' + name
        target = output / 'candidate' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body.replace('\n', '\r\n').encode())
        original = output / 'immutable_oracle' / name
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_bytes(raw[name])
        sources[name] = sha(target.read_bytes())
    receipt = {'schema': 'bt-parallel-ddr-private-transform-v1', 'status': 'PASS',
        'base_sources': BASE, 'candidate_sources': sources, 'edits': edits,
        'transform_source': sha(Path(__file__).read_bytes()),
        'scope': 'Reversible source preparation only; same acceptance edge and source priority require complete controller/beat simulation.',
        'generic_default': 0, 'source_order': ['sprite', 'foreground0', 'foreground1', 'cpu']}
    (output / 'manifest.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'candidate': str(output / 'candidate'), 'sources': sources}))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', type=Path, default=ROOT / 'build/timing_closure_20261011/integrated_v9_private')
    parser.add_argument('--out', type=Path, default=ROOT / 'build/ddr_parallel_sources_v9_v2')
    args = parser.parse_args()
    prepare(args.base.resolve(), args.out.resolve())
