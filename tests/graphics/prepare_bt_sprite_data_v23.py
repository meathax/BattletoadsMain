"""Guarded, default-off v23 sprite data localization and RAM row rewiring.

No production file is written.  The parent is the frozen 144-file v23 image.
The separate BT connection edits are a composition recipe, not an executed
change.  Physical RAM retention/placement is explicitly outside this proof.
"""
import argparse
import base64
import hashlib
import itertools
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "build/timing_closure_20261011/pixel_cpu_fg_v23_private-snapshot.json"
SNAPSHOT_SHA = "627f642c9490ce2ffeb532313e33e750a1b67997b2d99a46f3a2cc564d6f6e67"
PARENT = ROOT / "build/timing_closure_20261011/pixel_cpu_fg_v23_private"
FG_SHA = "46d75cb9a4a058535d671991410ef316cb4c0b113811038c73aba15075880b18"
BT_SHA = "49896ce904746ef65d03c63f38333e18dcdcf48550f092c35682073aaa956891"
SOURCE_FILES = ("rtl/spr_vram.sv", "rtl/fg_vram.sv")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def checked(path, expected):
    raw = Path(path).read_bytes()
    assert sha(raw) == expected, ("source digest changed", str(path))
    return raw


def encoded(before, after):
    return {"before_b64": base64.b64encode(before).decode(),
            "after_b64": base64.b64encode(after).decode()}


def forward(raw, edits):
    for edit in edits:
        before, after = (base64.b64decode(edit[key]) for key in ("before_b64", "after_b64"))
        assert before != after and raw.count(before) == 1, "forward anchor changed"
        raw = raw.replace(before, after, 1)
    return raw


def inverse(raw, edits):
    for edit in reversed(edits):
        before, after = (base64.b64decode(edit[key]) for key in ("before_b64", "after_b64"))
        assert raw.count(after) == 1, "inverse anchor changed"
        raw = raw.replace(after, before, 1)
    return raw


def replace(raw, old, new, edits):
    # The frozen SPR/BT parents are LF; FG is CRLF.  Match the existing
    # anchor's newline bytes and preserve all untouched raw bytes.
    if raw.count(old) == 0 and b"\r\n" in old:
        old = old.replace(b"\r\n", b"\n")
        new = new.replace(b"\r\n", b"\n")
    assert raw.count(old) == 1, ("unique source anchor changed", old)
    edits.append(encoded(old, new))
    return raw.replace(old, new, 1)


def transform_sprite(parent):
    assert b"\n" in parent
    out = parent
    edits = []
    out = replace(out,
        b"module SPR_VRAM #(parameter LOCAL_FG_Q=0, parameter REGISTERED_FG_BANK_Q=0) (",
        b"module SPR_VRAM #(parameter LOCAL_FG_Q=0, parameter REGISTERED_FG_BANK_Q=0, parameter FG_BANK_ADDR_PERMUTE=0, parameter LOCAL_FG_PACKET_D=0) (", edits)
    out = replace(out,
        b"output [1:0][3:0][63:0] FG_BANK_SHIFT_Q\r\n",
        b"output [1:0][3:0][63:0] FG_BANK_SHIFT_Q,\r\n\tinput [1:0][63:0] FG_PACKET_D,\r\n\tinput FG_PACKET_SELECT\r\n", edits)
    insert = b"""\t// Optional local replicas sample each foreground's original packet D on
\t// its original MEM edge.  The live owner selector and the following
\t// CPU_PACKET_DATA capture retain the original priority and latency.
\twire [63:0] CPU_PACKET_SOURCE_DATA;
\tgenerate if (LOCAL_FG_PACKET_D) begin : local_foreground_packet
\t\t(* preserve, dont_merge *) bit [1:0][63:0] fg_packet_data_q;
\t\talways @(posedge CLK) fg_packet_data_q <= FG_PACKET_D;
\t\tassign CPU_PACKET_SOURCE_DATA = FG_PACKET_SELECT ? fg_packet_data_q[0] : fg_packet_data_q[1];
\tend else begin : original_foreground_packet
\t\tassign CPU_PACKET_SOURCE_DATA = CPU_SHIFT_DATA;
\tend endgenerate
""".replace(b"\n", b"\r\n")
    anchor = b"\tbit CPU_PACKET_WE;\r\n"
    out = replace(out, anchor, insert + anchor, edits)
    out = replace(out, b"CPU_PACKET_DATA <= CPU_SHIFT_DATA;", b"CPU_PACKET_DATA <= CPU_PACKET_SOURCE_DATA;", edits)
    out = replace(out, b"BT_SPR_POST_NONZERO_MIRROR #(10,LOCAL_FG_Q,REGISTERED_FG_BANK_Q) read_mirror(",
        b"BT_SPR_POST_NONZERO_MIRROR #(10,LOCAL_FG_Q,REGISTERED_FG_BANK_Q,FG_BANK_ADDR_PERMUTE) read_mirror(", edits)
    out = replace(out,
        b"module BT_SPR_POST_NONZERO_MIRROR #(parameter addr_width=10,parameter LOCAL_FG_Q=0,parameter REGISTERED_FG_BANK_Q=0)(",
        b"module BT_SPR_POST_NONZERO_MIRROR #(parameter addr_width=10,parameter LOCAL_FG_Q=0,parameter REGISTERED_FG_BANK_Q=0,parameter FG_BANK_ADDR_PERMUTE=0)(", edits)
    out = replace(out, b"genvar foreground,bank;", b"genvar foreground,bank,address_bit;", edits)
    old = b"""    VRAM_SHIFTREG #(addr_width,1,1) mirror(
     .CLK(CLK),.ACLR(1'b0),.WADDR(WADDR),.RADDR(RADDR),
     .DATA(DATA),.WREN(WREN),.Q(FG_BANK_Q[foreground][bank]));""".replace(b"\n", b"\r\n")
    new = b"""    wire [addr_width-1:3] mirror_waddr,mirror_raddr;
    if (FG_BANK_ADDR_PERMUTE) begin : permuted_row_bits
     // Rewire both row addresses by the same bijection.  This changes no
     // data/mask/clock/output edge, and preserves X/Z without a data XOR.
     for(address_bit=0;address_bit<addr_width-3;address_bit=address_bit+1) begin : bits
      localparam integer variant=foreground*4+bank;
      localparam integer source_bit=variant<6 ? (address_bit+variant+1)%(addr_width-3) :
       variant==6 ? addr_width-4-address_bit : address_bit==0 ? 1 : address_bit==1 ? 0 : address_bit;
      assign mirror_waddr[address_bit+3]=WADDR[source_bit+3];
      assign mirror_raddr[address_bit+3]=RADDR[source_bit+3];
     end
    end else begin : original_row_bits
     assign mirror_waddr=WADDR;
     assign mirror_raddr=RADDR;
    end
    VRAM_SHIFTREG #(addr_width,1,1) mirror(
     .CLK(CLK),.ACLR(1'b0),.WADDR(mirror_waddr),.RADDR(mirror_raddr),
     .DATA(DATA),.WREN(WREN),.Q(FG_BANK_Q[foreground][bank]));""".replace(b"\n", b"\r\n")
    out = replace(out, old, new, edits)
    return out, edits


def transform_foreground(parent):
    out = parent
    edits = []
    # The existing ports keep their positional indices; the new output is last.
    out = replace(out, b"input [3:0][63:0] CPU_SHIFT_BANK_Q\r\n",
        b"input [3:0][63:0] CPU_SHIFT_BANK_Q,\r\n\toutput [63:0] CPU_SHIFT_SOURCE_D\r\n", edits)
    old = b"\tassign CPU_SHIFT_DATA = CPU_SHIFT_DATA_Q;\r\n"
    new = old + b"\tassign CPU_SHIFT_SOURCE_D = SQ_D | (COPY_WORD & {64{COPY_WE}});\r\n"
    out = replace(out, old, new, edits)
    return out, edits


def connection_edits(parent):
    out = parent
    edits = []
    out = replace(out, b"\twire [63:0] FG0_COPY_DATA, FG1_COPY_DATA, CPU_SHIFT_Q;\r\n",
        b"\twire [63:0] FG0_COPY_DATA, FG1_COPY_DATA, CPU_SHIFT_Q;\r\n\twire [1:0][63:0] FG_PACKET_D;\r\n", edits)
    out = replace(out, b"SPR_VRAM #(.LOCAL_FG_Q(1), .REGISTERED_FG_BANK_Q(1)) SPR_VRAM (",
        b"SPR_VRAM #(.LOCAL_FG_Q(1), .REGISTERED_FG_BANK_Q(1), .FG_BANK_ADDR_PERMUTE(1), .LOCAL_FG_PACKET_D(1)) SPR_VRAM (", edits)
    out = replace(out,
        b"\t\t.CPU_SHIFT_DATA(FG0_COPY_WE ? FG0_COPY_DATA : FG1_COPY_DATA),\r\n",
        b"\t\t.CPU_SHIFT_DATA(FG0_COPY_WE ? FG0_COPY_DATA : FG1_COPY_DATA),\r\n\t\t.FG_PACKET_D(FG_PACKET_D), .FG_PACKET_SELECT(FG0_COPY_WE),\r\n", edits)
    for fg in range(2):
        needle = re.compile(rb"(?m)^([^\r\n]*\.CPU_SHIFT_DATA\(FG" + str(fg).encode() + rb"_COPY_DATA\)[^\r\n]*)\r?\n")
        matches = list(needle.finditer(out))
        assert len(matches) == 1, ("FG packet output binding changed", fg)
        old = matches[0].group(0)
        eol = "\r\n" if b"\r\n" in old else "\n"
        new = old + ("\t\t.CPU_SHIFT_SOURCE_D(FG_PACKET_D[%d])," % fg + eol).encode()
        out = replace(out, old, new, edits)
    assert inverse(out, edits) == parent
    return edits


def permutations(width=7):
    assert width >= 4
    return [tuple((bit + variant + 1) % width if variant < 6 else
                  width - 1 - bit if variant == 6 else
                  1 if bit == 0 else 0 if bit == 1 else bit
                  for bit in range(width)) for variant in range(8)]


def source_proof(parents, candidates, edits, bt, binding_edits):
    for rel in SOURCE_FILES:
        assert forward(parents[rel], edits[rel]) == candidates[rel]
        assert inverse(candidates[rel], edits[rel]) == parents[rel]
    assert inverse(forward(bt, binding_edits), binding_edits) == bt
    mapping = permutations()
    assert len(set(mapping)) == 8 and all(sorted(p) == list(range(7)) for p in mapping)
    rows = 0
    for symbols in itertools.product("01xz", repeat=7):
        for p in mapping:
            remapped = tuple(symbols[index] for index in p)
            recovered = tuple(remapped[p.index(index)] for index in range(7))
            assert recovered == symbols
            rows += 1
    fg = candidates["rtl/fg_vram.sv"]
    assert fg.count(b"CPU_SHIFT_DATA_Q <= SQ_D | (COPY_WORD & {64{COPY_WE}});") == 1
    assert fg.count(b"assign CPU_SHIFT_SOURCE_D = SQ_D | (COPY_WORD & {64{COPY_WE}});") == 1
    # All existing FG data capture/body bytes, including LCELL, are recovered.
    assert b"bit [63: 0]  CPU_SHIFT_DATA_Q;" in fg
    spr = candidates["rtl/spr_vram.sv"]
    assert spr.count(b"(* preserve, dont_merge *) bit [1:0][63:0] fg_packet_data_q;") == 1
    assert b"always @(posedge CLK) fg_packet_data_q <= FG_PACKET_D;" in spr
    assert b"FG_PACKET_SELECT ? fg_packet_data_q[0] : fg_packet_data_q[1]" in spr
    assert b"CPU_PACKET_DATA <= CPU_PACKET_SOURCE_DATA;" in spr
    rejected = []
    mutants = [
        ("default_on", b"parameter FG_BANK_ADDR_PERMUTE=0", b"parameter FG_BANK_ADDR_PERMUTE=1"),
        ("packet_default_on", b"parameter LOCAL_FG_PACKET_D=0", b"parameter LOCAL_FG_PACKET_D=1"),
        ("one_port_permutation", b".RADDR(mirror_raddr)", b".RADDR(RADDR)"),
        ("data_changed", b".DATA(DATA),.WREN(WREN),.Q(FG_BANK_Q", b".DATA(~DATA),.WREN(WREN),.Q(FG_BANK_Q"),
        ("extra_edge", b"fg_packet_data_q <= FG_PACKET_D", b"fg_packet_data_q <= CPU_SHIFT_DATA"),
        ("four_state_storage", b"bit [1:0][63:0] fg_packet_data_q", b"reg [1:0][63:0] fg_packet_data_q"),
        ("priority_changed", b"FG_PACKET_SELECT ? fg_packet_data_q[0] : fg_packet_data_q[1]", b"FG_PACKET_SELECT ? fg_packet_data_q[1] : fg_packet_data_q[0]"),
        ("new_reset", b"always @(posedge CLK) fg_packet_data_q", b"always @(posedge CLK or negedge RST_N) fg_packet_data_q"),
    ]
    for name, old, new in mutants:
        assert spr.count(old) >= 1, ("negative-control anchor absent", name)
        wrong = spr.replace(old, new, 1)
        try:
            assert wrong == forward(parents["rtl/spr_vram.sv"], edits["rtl/spr_vram.sv"])
        except AssertionError:
            rejected.append(name)
    assert len(rejected) == 8
    return {"status": "PASS_REVERSIBLE_SOURCE_AND_4STATE_ROW_BIJECTION",
            "four_state_row_inverse_checks": rows,
            "bijective_row_maps": [list(p) for p in mapping],
            "negative_controls_rejected": rejected,
            "packet_identity": "Two 2-state zero-initialized local Qs capture the exact original FG D expressions on the same MEM edge, then use the unchanged live FG0-priority selector before the existing packet edge.",
            "collision_identity": "The same bijection on both RAM ports preserves every matching address and byte-lane overlap; no data bit/X/Z is transformed.",
            "unchanged_leaf_geometry_modes_masks_and_output_edges": True,
            "actual_Intel_simulation_complete": False,
            "physical_RAM_independence_proven": False,
            "timing_accepted": False, "rbf_generated": False}


def verify_edge(edge):
    edge = Path(edge).resolve()
    manifest = json.loads((edge / "manifest.json").read_bytes())
    assert manifest["schema"] == "bt-sprite-data-v23-source-edge-v1"
    assert manifest["preparer_sha256"] == sha(Path(__file__).read_bytes())
    checked(SNAPSHOT, SNAPSHOT_SHA)
    parents = {rel: checked(edge / "oracle" / rel, manifest["files"][rel]["parent_sha256"]) for rel in SOURCE_FILES}
    candidates = {rel: checked(edge / "candidate" / rel, manifest["files"][rel]["candidate_sha256"]) for rel in SOURCE_FILES}
    edits = {rel: manifest["files"][rel]["edits"] for rel in SOURCE_FILES}
    bt = checked(edge / "binding_parent" / "rtl/BT.sv", BT_SHA)
    proof = source_proof(parents, candidates, edits, bt, manifest["BT_connection_edits"])
    assert proof == manifest["source_proof"]
    return parents, candidates, manifest


def prepare(output):
    output = Path(output).resolve()
    assert output.is_relative_to(ROOT / "build") and not output.exists()
    snapshot = json.loads(checked(SNAPSHOT, SNAPSHOT_SHA))
    assert snapshot["rbf_generation"] is False and len(snapshot["sources"]) == 144
    parents = {rel: checked(PARENT / rel, snapshot["sources"][rel]) for rel in SOURCE_FILES}
    assert sha(parents["rtl/fg_vram.sv"]) == FG_SHA
    bt = checked(PARENT / "rtl/BT.sv", BT_SHA)
    spr, se = transform_sprite(parents["rtl/spr_vram.sv"])
    fg, fe = transform_foreground(parents["rtl/fg_vram.sv"])
    candidates = dict(zip(SOURCE_FILES, (spr, fg)))
    edits = dict(zip(SOURCE_FILES, (se, fe)))
    bindings = connection_edits(bt)
    proof = source_proof(parents, candidates, edits, bt, bindings)
    for rel, raw in parents.items():
        for scope, contents in (("oracle", raw), ("candidate", candidates[rel])):
            path = output / scope / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(contents)
    path = output / "binding_parent/rtl/BT.sv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bt)
    manifest = {"schema": "bt-sprite-data-v23-source-edge-v1", "status": proof["status"],
        "parent_snapshot": str(SNAPSHOT), "parent_snapshot_sha256": SNAPSHOT_SHA,
        "preparer": str(Path(__file__).resolve()), "preparer_sha256": sha(Path(__file__).read_bytes()),
        "files": {rel: {"parent_sha256": sha(parents[rel]), "candidate_sha256": sha(candidates[rel]), "edits": edits[rel]} for rel in SOURCE_FILES},
        "BT_connection_parent_sha256": BT_SHA, "BT_connection_edits": bindings,
        "BT_connections_applied": False, "source_proof": proof,
        "source_changes": "Only private SPR/FG files; BT edits are a separate reversible binding recipe.",
        "root_modified": False, "rbf_generated": False}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    verify_edge(output)
    print(json.dumps({"manifest": str(output / "manifest.json"), "manifest_sha256": sha((output / "manifest.json").read_bytes()),
                      "candidate_sha256": {rel: sha(raw) for rel, raw in candidates.items()}, "source_proof": proof}, separators=(",", ":")))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.output)
