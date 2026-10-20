"""Guarded v20 edge: bank-local foreground mirrors using the existing hard Q.

Only isolated candidates are written. Operations are raw CRLF-preserving and
can be lifted onto disjoint foreground control edits; both full inverses must
still be checked against the immutable v20 parent.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PARENT = ROOT / "build/timing_closure_20261011/fg_sprite_controls_v20_private"
PARENT_SHAS = {
    "rtl/BT.sv": "e24c7e25743b00be2061d0767ba5785c745bc7def07deae3fc55c1f01384ff71",
    "rtl/spr_vram.sv": "9fff133ad84106b7b171134e4a09c6d01ffffc0bc2fc69be7b49e272b45822ef",
    "rtl/fg_vram.sv": "ddf9c579f24837042d1eb0e700f4e6f7f27896d0e93f4538525d66bfa1efbdd9",
}
MODE_PROOF = ROOT / "build/sprite_registered_q_v20_v1/mode-probe-r1/receipt.json"
MODE_PROOF_SHA = "e7761704cfd68c9a87d244db7f3b3c1311aacb6d004f1befb3227acf40787cfd"
MEM = PARENT / "rtl/BT_mem.sv"
MEM_SHA = "903aeedc272fd64409ebae8b8624befe82bc1f073d1545310dbeb070afaf6393"
REGISTERED = """ generate if (REGISTERED_FG_BANK_Q) begin : registered_foreground_banks
  // Same CLOCK0 address and output edges as raw_mirror followed by Q.
  // The hard output is never cleared, matching the original init-zero Q.
  for(genvar foreground=0;foreground<2;foreground=foreground+1) begin : foregrounds
   for(genvar bank=0;bank<4;bank=bank+1) begin : banks
    VRAM_SHIFTREG #(addr_width,1,1) mirror(
     .CLK(CLK),.ACLR(1'b0),.WADDR(WADDR),.RADDR(RADDR),
     .DATA(DATA),.WREN(WREN),.Q(FG_BANK_Q[foreground][bank]));
   end
  end
  assign FG0_Q=FG_BANK_Q[0][0];
  assign FG1_Q=FG_BANK_Q[1][0];
 end else if (LOCAL_FG_Q) begin : local_foreground_q
"""
DEFAULT_BANKS = """ generate if (!REGISTERED_FG_BANK_Q) begin : original_foreground_banks
  for(genvar foreground=0;foreground<2;foreground=foreground+1) begin : foregrounds
   for(genvar bank=0;bank<4;bank=bank+1) begin : banks
    assign FG_BANK_Q[foreground][bank] = foreground==0 ? FG0_Q : FG1_Q;
   end
  end
 end endgenerate
"""


def sha(data):
    return hashlib.sha256(data).hexdigest()


def replace(data, before, after, role, edits):
    # The immutable SPR parent is LF; BT/FG may retain their original CRLF.
    # Record exactly the matching raw anchor, without normalizing the source.
    newline = "\r\n" if b"\r\n" in data else "\n"
    choices = list(dict.fromkeys([before.replace("\n", newline).encode(), before.encode()]))
    matches = [value for value in choices if data.count(value) == 1]
    assert len(matches) == 1, (role, "raw anchor count", [data.count(value) for value in choices])
    matched = matches[0]
    if "\n" in before and b"\r\n" not in matched:
        newline = "\n"
    before = matched
    after = after.replace("\n", newline).encode()
    edits.append({"role": role, "before_b64": base64.b64encode(before).decode(),
                  "after_b64": base64.b64encode(after).decode()})
    return data.replace(before, after, 1)


def forward(data, edits):
    for edit in edits:
        before = base64.b64decode(edit["before_b64"])
        after = base64.b64decode(edit["after_b64"])
        assert data.count(before) == 1, (edit["role"], "forward anchor changed")
        data = data.replace(before, after, 1)
    return data


def inverse(data, edits):
    for edit in reversed(edits):
        before = base64.b64decode(edit["before_b64"])
        after = base64.b64decode(edit["after_b64"])
        assert data.count(after) == 1, (edit["role"], "inverse anchor changed")
        data = data.replace(after, before, 1)
    return data


def transform(rel, data):
    assert sha(data) == PARENT_SHAS[rel], (rel, "immutable v20 parent changed")
    edits = []
    if rel == "rtl/spr_vram.sv":
        data = replace(data, "module SPR_VRAM #(parameter LOCAL_FG_Q=0) (",
                       "module SPR_VRAM #(parameter LOCAL_FG_Q=0, parameter REGISTERED_FG_BANK_Q=0) (", "spr_parameter", edits)
        data = replace(data, "\toutput [63:0] FG1_SHIFT_Q\n);",
                       "\toutput [63:0] FG1_SHIFT_Q,\n\toutput [1:0][3:0][63:0] FG_BANK_SHIFT_Q\n);", "spr_appended_port", edits)
        data = replace(data, "BT_SPR_POST_NONZERO_MIRROR #(10,LOCAL_FG_Q) read_mirror(",
                       "BT_SPR_POST_NONZERO_MIRROR #(10,LOCAL_FG_Q,REGISTERED_FG_BANK_Q) read_mirror(", "mirror_parameter_binding", edits)
        data = replace(data, ".Q(mirror_q),.NZ(mirror_nz),.FG0_Q(FG0_SHIFT_Q),.FG1_Q(FG1_SHIFT_Q)",
                       ".Q(mirror_q),.NZ(mirror_nz),.FG0_Q(FG0_SHIFT_Q),.FG1_Q(FG1_SHIFT_Q),.FG_BANK_Q(FG_BANK_SHIFT_Q)", "mirror_bank_port_binding", edits)
        data = replace(data, "module BT_SPR_POST_NONZERO_MIRROR #(parameter addr_width=10,parameter LOCAL_FG_Q=0)(",
                       "module BT_SPR_POST_NONZERO_MIRROR #(parameter addr_width=10,parameter LOCAL_FG_Q=0,parameter REGISTERED_FG_BANK_Q=0)(", "mirror_appended_parameter", edits)
        data = replace(data, " output [63:0] FG0_Q,FG1_Q\n);",
                       " output [63:0] FG0_Q,FG1_Q,\n output [1:0][3:0][63:0] FG_BANK_Q\n);", "mirror_appended_port", edits)
        data = replace(data, " generate if (LOCAL_FG_Q) begin : local_foreground_q\n",
                       REGISTERED, "same_edge_registered_bank_producers", edits)
        data = replace(data, "  assign FG1_Q=Q;\n end endgenerate\nendmodule",
                       "  assign FG1_Q=Q;\n end endgenerate\n" + DEFAULT_BANKS + "endmodule", "default_off_bank_aliases", edits)
    elif rel == "rtl/BT.sv":
        data = replace(data, "\twire [63:0] FG0_SHIFT_Q, FG1_SHIFT_Q;",
                       "\twire [63:0] FG0_SHIFT_Q, FG1_SHIFT_Q;\n\twire [1:0][3:0][63:0] FG_BANK_SHIFT_Q;", "board_bank_bus", edits)
        data = replace(data, "SPR_VRAM #(.LOCAL_FG_Q(1)) SPR_VRAM (",
                       "SPR_VRAM #(.LOCAL_FG_Q(1), .REGISTERED_FG_BANK_Q(1)) SPR_VRAM (", "board_activate_registered_mirrors", edits)
        data = replace(data, ".FG0_SHIFT_Q(FG0_SHIFT_Q), .FG1_SHIFT_Q(FG1_SHIFT_Q),",
                       ".FG0_SHIFT_Q(FG0_SHIFT_Q), .FG1_SHIFT_Q(FG1_SHIFT_Q), .FG_BANK_SHIFT_Q(FG_BANK_SHIFT_Q),", "board_spr_bank_binding", edits)
        data = replace(data, "FG_VRAM FG0_VRAM (",
                       "FG_VRAM #(.REGISTERED_FG_BANK_Q(1)) FG0_VRAM (", "board_fg0_activate", edits)
        data = replace(data, "FG_VRAM FG1_VRAM(",
                       "FG_VRAM #(.REGISTERED_FG_BANK_Q(1)) FG1_VRAM(", "board_fg1_activate", edits)
        for bank in range(2):
            data = replace(data, f".CPU_SHIFT_Q(FG{bank}_SHIFT_Q),",
                           f".CPU_SHIFT_Q(FG{bank}_SHIFT_Q), .CPU_SHIFT_BANK_Q(FG_BANK_SHIFT_Q[{bank}]),", f"board_fg{bank}_bank_binding", edits)
    elif rel == "rtl/fg_vram.sv":
        data = replace(data, "module FG_VRAM (",
                       "module FG_VRAM #(parameter REGISTERED_FG_BANK_Q=0) (", "fg_default_off_parameter", edits)
        data = replace(data, "\toutput         CPU_SHIFT_WE\n);",
                       "\toutput         CPU_SHIFT_WE,\n\tinput [3:0][63:0] CPU_SHIFT_BANK_Q\n);", "fg_appended_bank_input", edits)
        lines = data.decode().splitlines()
        headers = [line for line in lines if "BT_FG_BANKED_VRAM #(" in line and line.endswith(") mem")]
        assert len(headers) == 1 and headers[0].endswith(")) mem"), "banked memory ABI changed"
        old_header = headers[0]
        new_header = old_header[:-6] + "), .REGISTERED_FG_BANK_Q(REGISTERED_FG_BANK_Q)) mem"
        data = replace(data, old_header, new_header, "banked_parameter_binding", edits)
        data = replace(data, ".SDATA_C(CPU_SHIFT_Q), .SDATA_S(SERIAL_WRITE_WORD)",
                       ".SDATA_C(CPU_SHIFT_Q), .SDATA_CB(CPU_SHIFT_BANK_Q), .SDATA_S(SERIAL_WRITE_WORD)", "fg_bank_data_binding", edits)
        data = replace(data, "module BT_FG_BANKED_VRAM #(parameter QA_REG = 0, parameter COPY_PREFETCH_LOCAL = 0, parameter BANK_WRITE_PREDECODED = 0, parameter SERIAL_SEGMENT_PRE = 0) (",
                       "module BT_FG_BANKED_VRAM #(parameter QA_REG = 0, parameter COPY_PREFETCH_LOCAL = 0, parameter BANK_WRITE_PREDECODED = 0, parameter SERIAL_SEGMENT_PRE = 0, parameter REGISTERED_FG_BANK_Q = 0) (", "banked_appended_parameter", edits)
        data = replace(data, "    input [3:0][3:0] SWREN_SEG_B\n);",
                       "    input [3:0][3:0] SWREN_SEG_B,\n    input [3:0][63:0] SDATA_CB\n);", "banked_appended_input", edits)
        data = replace(data, "    generate for (bank=0;bank<4;bank=bank+1) begin : banks\n",
                       "    generate for (bank=0;bank<4;bank=bank+1) begin : banks\n        wire [63:0] bank_cpu_data = REGISTERED_FG_BANK_Q ? SDATA_CB[bank] : SDATA_C;\n", "local_bank_data_selector", edits)
        old_mux = ".SDATA({SCSEL4[bank][3] ? SDATA_C[63:48] : SDATA_S[63:48], SCSEL4[bank][2] ? SDATA_C[47:32] : SDATA_S[47:32], SCSEL4[bank][1] ? SDATA_C[31:16] : SDATA_S[31:16], SCSEL4[bank][0] ? SDATA_C[15:0] : SDATA_S[15:0]})"
        data = replace(data, old_mux, old_mux.replace("SDATA_C[", "bank_cpu_data["), "per_bank_actual_ram_data_pins", edits)
    else:
        raise AssertionError("undeclared source")
    return data, edits


def verify_edge(directory):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_bytes())
    assert manifest["schema"] == "bt-v20-sprite-bank-registered-mirrors-source-edge-v1"
    assert sha(MODE_PROOF.read_bytes()) == MODE_PROOF_SHA
    assert sha(MEM.read_bytes()) == MEM_SHA
    assert json.loads(MODE_PROOF.read_bytes())["status"] == "PASS_EXACT_VENDOR_EDGE"
    parents, candidates = {}, {}
    for rel, expected in PARENT_SHAS.items():
        parent = (directory / "oracle" / rel).read_bytes()
        candidate = (directory / "candidate" / rel).read_bytes()
        assert sha(parent) == expected
        regenerated, edits = transform(rel, parent)
        assert manifest["files"][rel]["edits"] == edits
        assert candidate == regenerated
        assert inverse(candidate, edits) == parent
        assert forward(parent, edits) == candidate
        assert sha(candidate) == manifest["files"][rel]["candidate_sha256"]
        parents[rel], candidates[rel] = parent, candidate
    assert manifest["mode_proof_sha256"] == MODE_PROOF_SHA
    assert manifest["memory_sha256"] == MEM_SHA
    return parents, candidates, manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    assert output.is_relative_to(ROOT / "build") and not output.exists()
    assert sha(MODE_PROOF.read_bytes()) == MODE_PROOF_SHA
    assert json.loads(MODE_PROOF.read_bytes())["status"] == "PASS_EXACT_VENDOR_EDGE"
    assert sha(MEM.read_bytes()) == MEM_SHA
    files = {}
    pending = []
    for rel, expected in PARENT_SHAS.items():
        parent = (PARENT / rel).read_bytes()
        assert sha(parent) == expected
        candidate, edits = transform(rel, parent)
        assert inverse(candidate, edits) == parent
        files[rel] = {"parent_sha256": expected, "candidate_sha256": sha(candidate), "edits": edits}
        pending += [(output / "oracle" / rel, parent), (output / "candidate" / rel, candidate)]
    manifest = {"schema": "bt-v20-sprite-bank-registered-mirrors-source-edge-v1",
                "parent": str(PARENT), "files": files,
                "mode_proof": str(MODE_PROOF), "mode_proof_sha256": MODE_PROOF_SHA,
                "memory": str(MEM), "memory_sha256": MEM_SHA,
                "helper": str(Path(__file__).resolve()), "helper_sha256": sha(Path(__file__).read_bytes()),
                "replicas": {"foregrounds": 2, "banks_each": 4, "depth": 128, "width": 64,
                             "added_bits": 65536, "prior_fitted_mirror_m10ks": 2,
                             "projected_added_m10ks": 16, "prior_total": 458, "device_total": 553,
                             "projected_total": 474, "active_old_local_soft_Q_removed_bits": 128,
                             "mapped_replication_or_placement_proven": False},
                "contracts": ["default-off old behavior", "append-only port and parameter order",
                              "original Q/NZ/raw_mirror and asynchronous sprite ports unchanged",
                              "all eight new RAMs same write/read/clock input; hard ACLR constant0",
                              "FG0/FG1 old aliases from corresponding registered bank0, including DDR consumers",
                              "per-bank serial mux is otherwise identical", "no new edge or clock/SDC change"]}
    for path, data in pending:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    verify_edge(output)
    print(json.dumps({"output": str(output), "manifest_sha256": sha((output / "manifest.json").read_bytes()),
                      "candidates": {rel: row["candidate_sha256"] for rel, row in files.items()}}))


if __name__ == "__main__":
    main()
