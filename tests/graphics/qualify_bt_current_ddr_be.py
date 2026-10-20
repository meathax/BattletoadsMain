"""Qualify the complete current CPU consuming stage using retained owner tests.

The production files and historical fixtures remain untouched. The generated
wrapper contains the actual CPU stage byte for byte and preserves the old tests.
"""
import hashlib
import json
from pathlib import Path
import re
import uuid
import argparse
from prepare_bt_en0_snapshot_candidate import (BASE_MC_GIT_COMMIT, BASE_MC_CANONICAL_SHA256,
    MC_ORACLE_NAME, canonical_lf, git_mc_oracle, en0_snapshot_transform)
from bt_address_class_fixture import verify_edge as verify_address_class_edge, augment as augment_address_class_fixture
from bt_combined_stage_fixture import full_ddr_oracle, augment as augment_combined_ddr_fixture

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-root', type=Path, help='Explicit production-source overlay; absent files are bound to the unchanged repository inputs.')
parser.add_argument('--phase', choices=('alternating', 'production'), default='alternating')
args = parser.parse_args()

ROOT = Path(__file__).resolve().parents[2]
LEGACY = ROOT / 'build/resource_audit/qualify_ddr_be_bridge.py'
OLD_TB = ROOT / 'build/resource_audit/ddr_be_bridge_tb.sv'
OLD_STAGE = ROOT / 'build/resource_audit/ddr_return_split/MC_MEM_RETURN_STAGE.svh'
CPU = ROOT / 'rtl/TMS34020/TMS34020.sv'
sha = lambda data: hashlib.sha256(data).hexdigest()
source_root = args.source_root.resolve() if args.source_root else ROOT
bound_sources = {}


def candidate_read(name):
    source = ROOT / name
    overlay = source_root / name
    if overlay.is_file():
        source = overlay
    data = source.read_bytes()
    entry = {'path': str(source.resolve()), 'sha256': sha(data)}
    assert name not in bound_sources or bound_sources[name] == entry, 'An input changed during qualification: ' + name
    bound_sources[name] = entry
    return data


directory = ROOT / 'build/current_ddr_be_stage' / uuid.uuid4().hex
directory.mkdir(parents=True, exist_ok=False)


def relative(path):
    return path.relative_to(ROOT).as_posix()


def stage(source):
    start = '\t// BEGIN MC_MEM_RETURN_STAGE:'
    end = '\t// END MC_MEM_RETURN_STAGE'
    assert source.count(start) == source.count(end) == 1
    first = source.index(start)
    last = source.index(end, first) + len(end)
    return source[first:last]


cpu_bytes = candidate_read('rtl/TMS34020/TMS34020.sv')
cpu_text = cpu_bytes.decode()
assert '\r' not in cpu_text, 'Stage copy must preserve the current LF source exactly'
current_stage = stage(cpu_text)
pause_source = candidate_read('rtl/bt_pause_bridge.sv')
top_source = candidate_read('Arcade-Battletoads.sv').decode()


def port_map(module, text):
    matches = list(re.finditer(r'\b' + re.escape(module) + r'\s+\w+\s*\((.*?)\);', text, re.S))
    assert len(matches) == 1, 'Expected one actual board instance of ' + module
    return {port: value.strip() for port, value in re.findall(r'\.(\w+)\s*\(\s*([^()]*)\)', matches[0].group(1))}


pause_ports = port_map('bt_pause_bridge', top_source)
clock_ports = port_map('bt_clock_enables', top_source)
bt_ports = port_map('BT', top_source)
assert pause_ports['pause_req'] == 'pause_cpu', 'Proof requires the actual registered board pause request'
assert pause_ports['clk'] == clock_ports['clk'] and pause_ports['reset'] == clock_ports['reset']
assert pause_ports['raw_ce_f'] == clock_ports['ce_f'] and pause_ports['raw_ce_r'] == clock_ports['ce_r']
assert pause_ports['ce_f'] == bt_ports['CE_F'] and pause_ports['ce_r'] == bt_ports['CE_R']
if pause_ports.get('halted'):
    nvram_ports = port_map('bt_nvram', top_source)
    assert pause_ports['halted'] == nvram_ports['cpu_halted'] == 'cpu_pause_halted'
    assert re.sub(r'\s+', '', nvram_ports['cpu_we']) == 'BT_NVRAM_WE&&CE_R_CPU'
    candidate_read('rtl/bt_nvram.sv')
else:
    nvram_ports = {}
original_mc = candidate_read(MC_ORACLE_NAME)
git_original_mc = git_mc_oracle()
assert canonical_lf(original_mc) == canonical_lf(git_original_mc)
assert sha(canonical_lf(original_mc)) == BASE_MC_CANONICAL_SHA256, 'Immutable original full-MC source changed'
current_mc = candidate_read('rtl/TMS34020/TMS34020_MC.sv')
address_class_sideband = b'DBUS_ADDR_CLASS' in current_mc
address_class_edge = {}
address_class_decoder = {}
combined_ddr_scope = {}
combined_ddr_oracle = {}
if address_class_sideband:
    address_class_edge, address_class_old_bt, address_class_current_bt = verify_address_class_edge(ROOT, candidate_read, original_mc, source_root)
    if address_class_edge['edge_type'] == 'bt-class-parallel-ddr-v1':
        combined_ddr_oracle = full_ddr_oracle(ROOT, directory)
    guarded_mc = en0_snapshot_transform(original_mc)
else:
    guarded_mc = current_mc
en0_snapshot_fix = canonical_lf(guarded_mc) != canonical_lf(original_mc)
if en0_snapshot_fix:
    assert canonical_lf(guarded_mc) == canonical_lf(en0_snapshot_transform(original_mc)), 'MC differs outside the authorized preparatory snapshot/age change'
oracle_file = directory / 'TMS34020_MC_FINAL_ORACLE.sv'
assert original_mc.count(b'module TMS34020_MC') == 1
oracle_file.write_bytes(b'`define SYNTHESIS\n' + original_mc.replace(
    b'module TMS34020_MC', b'module TMS34020_MC_FINAL_ORACLE', 1) + b'\n`undef SYNTHESIS\n')
old_fixture = OLD_TB.read_text()
old_stage = stage(old_fixture)
assert old_stage.strip() == OLD_STAGE.read_text().strip()
early_addition = '''\t// The same word as the MC's CE_R early capture sees it, one clock before
\t// the CE_F capture: the held memory words are already final there, the IO
\t// register mux is taken before its output register (DO_NEXT).
\twire [31:0] MC_RETURN_WORD_E = MC_MEM_SELECTED ?
\t    (MC_DDR_SELECTED ? MC_DDR_RETURN_WORD : MC_MEM_WORD) :
\t    IO_SEL ? IO_DO_NEXT : LDI_CACHE_LATE;
'''
late_e_interface = 'IO_SEL ? IO_DO_NEXT : LDI_CACHE_LATE_E;' in current_stage
if late_e_interface:
    early_addition = early_addition.replace('IO_SEL ? IO_DO_NEXT : LDI_CACHE_LATE;', 'IO_SEL ? IO_DO_NEXT : LDI_CACHE_LATE_E;')
    assert '.LDI_CACHE_LATE_E' in candidate_read('rtl/BT.sv').decode(), 'Candidate BT does not drive the actual early late-owner port'
assert current_stage.count(early_addition) == 1
assert current_stage.replace(early_addition, '', 1) == old_stage, \
    'The retained original capture, mask, reset or assertions have changed'
stage_file = directory / 'MC_MEM_RETURN_STAGE_CURRENT.svh'
stage_file.write_bytes(current_stage.encode())

transforms = []
fixture = old_fixture


def replace_once(before, after):
    global fixture
    assert fixture.count(before) == 1, repr(before)
    fixture = fixture.replace(before, after, 1)
    transforms.append((before, after))


replace_once(old_stage, current_stage)
if late_e_interface:
    replace_once('input [31:0] LDI_CACHE_DDR_DATA,LDI_CACHE_RAM_DATA,LDI_CACHE_LATE,',
                 'input [31:0] LDI_CACHE_DDR_DATA,LDI_CACHE_RAM_DATA,LDI_CACHE_LATE,LDI_CACHE_LATE_E,')
replace_once(' wire [31:0] ba,bd,di,din;',
             ' wire [31:0] ba,bd,di,din;\n wire [31:0] di_e,din_f,din_f_ref;')
replace_once(' wire [31:0] IO_DO=ddr_be_bridge_tb.io_q;',
             ' wire [31:0] IO_DO=ddr_be_bridge_tb.io_q;\n'
             ' wire [31:0] IO_DO_NEXT=ddr_be_bridge_tb.io_next;')
replace_once('.DOUT(ddr_be_bridge_tb.req_data),.DIN(din),',
             '.DOUT(ddr_be_bridge_tb.req_data),.DIN(din),.DIN_F(din_f),')
replace_once('.DOUT(ddr_be_bridge_tb.req_data),.DIN(din_ref),',
             '.DOUT(ddr_be_bridge_tb.req_data),.DIN(din_ref),.DIN_F(din_f_ref),')
assert fixture.count('.WRITE(ddr_be_bridge_tb.req_write),') == 2
for old, new in [
    ('.WRITE(ddr_be_bridge_tb.req_write),', '.WRITE(ddr_be_bridge_tb.req_write),.WRITE_PRE(ddr_be_bridge_tb.req_write),'),
]:
    count = fixture.count(old)
    fixture = fixture.replace(old, new)
    transforms.append((old, new, count))
replace_once('.DBUS_DI(MC_RETURN_WORD),',
             '.DBUS_DI(MC_RETURN_WORD),.DBUS_DI_E(MC_RETURN_WORD_E),')
replace_once('.DBUS_DI(di),', '.DBUS_DI(di),.DBUS_DI_E(di_e),')
replace_once(' assign di=IO_SEL?IO_DO:LDI;',
             ''' // Independent raw-bus next-state oracle. Final di remains the
 // original raw owner mux. The palette D is derived from its unchanged
 // registered owner/update contract, without using the candidate E mux.
 wire raw_palette_read = CE_R && ddr_be_bridge_tb.dut.MISC_SEL && !QE_N &&
                         !ddr_be_bridge_tb.dut.PAL_ACCESSED &&
                         {LA[11:5],5'b0} == 12'h320;
 reg [7:0] raw_palette_next;
 reg [31:0] raw_late_next;
 always_comb begin
  raw_palette_next=ddr_be_bridge_tb.dut.PAL_READ_DATA;
  if(!RST_N) raw_palette_next=0;
  else if(raw_palette_read) case(ddr_be_bridge_tb.dut.PAL_RBYTE)
   0:raw_palette_next=ddr_be_bridge_tb.dut.IO_PAL_Q[23:16];
   1:raw_palette_next=ddr_be_bridge_tb.dut.PAL_WDATA[15:8];
   2:raw_palette_next=ddr_be_bridge_tb.dut.PAL_WDATA[7:0];
   default:begin end
  endcase
  raw_late_next=LDI;
  if(ddr_be_bridge_tb.dut.MISC_SEL && {LA[11:5],5'b0} == 12'h320)
   raw_late_next={24'b0,raw_palette_next};
 end
 assign di=IO_SEL?IO_DO:LDI;
 assign di_e=IO_SEL?IO_DO_NEXT:raw_late_next;''')
replace_once('fg0_post_bank<=dut.FG0_VRAM.mem.read_bank;fg1_post_bank<=dut.FG1_VRAM.mem.read_bank;',
             'fg0_post_bank<={dut.FG0_VRAM.mem.banks[3].ram.qg,dut.FG0_VRAM.mem.banks[2].ram.qg,dut.FG0_VRAM.mem.banks[1].ram.qg,dut.FG0_VRAM.mem.banks[0].ram.qg};'
             'fg1_post_bank<={dut.FG1_VRAM.mem.banks[3].ram.qg,dut.FG1_VRAM.mem.banks[2].ram.qg,dut.FG1_VRAM.mem.banks[1].ram.qg,dut.FG1_VRAM.mem.banks[0].ram.qg};')
replace_once(' always @(posedge clk)if(reset_n&&r&&dut.CPU.IO_SEL&&!dut.QE_N)begin io_q<=io_q^32\'h00ff_a55a;io_late++;end',
             '  wire [31:0] io_next=(reset_n&&r&&dut.CPU.IO_SEL&&!dut.QE_N) ? io_q^32\'h00ff_a55a : io_q;\n'
             '  always @(posedge clk)if(reset_n&&r&&dut.CPU.IO_SEL&&!dut.QE_N)begin io_q<=io_q^32\'h00ff_a55a;io_late++;end')

early_checks = '''
  integer early_checks=0,early_mem_checks=0,early_late_checks=0,early_io_checks=0,early_io_next_changes=0;
  integer early_palette_checks=0,early_palette_changes=0,early_r_checks=0,early_idle_checks=0;
  integer early_palette_byte[3]='{default:0};
  always @(posedge CLK) if(RST_N && EN && !CE_F && MC.READ_LATCH) begin
   assert(MC_RETURN_WORD_E == di_e)
    else $fatal(1,"actual CPU early stage differs from independent raw owner word");
   early_checks++;
   if(CE_R) early_r_checks++; else early_idle_checks++;
   if(MC_MEM_SELECTED) early_mem_checks++;
   else if(IO_SEL) begin
    early_io_checks++;
    if(IO_DO_NEXT != IO_DO) early_io_next_changes++;
   end else begin
    early_late_checks++;
    if(raw_palette_read) begin
     early_palette_checks++;
     if(raw_palette_next != ddr_be_bridge_tb.dut.PAL_READ_DATA) early_palette_changes++;
     if(ddr_be_bridge_tb.dut.PAL_RBYTE < 3) early_palette_byte[ddr_be_bridge_tb.dut.PAL_RBYTE]++;
    end
   end
  end
  always @(negedge CLK) if(RST_N) begin
   assert(din_f == din_f_ref)
    else $fatal(1,"actual F-phase MC return differs from raw owner reference");
   assert({MC.READ_WORD_E,MC.READ_PREVIOUS_E,MC.READ_ALIGN_E,MC.READ_SIZE_E,MC.READ_OLD_SIZE_E,MC.READ_EXTENDED_E} ==
          {REF.READ_WORD_E,REF.READ_PREVIOUS_E,REF.READ_ALIGN_E,REF.READ_SIZE_E,REF.READ_OLD_SIZE_E,REF.READ_EXTENDED_E})
    else $fatal(1,"actual early capture words differ from raw owner reference");
  end
'''
if en0_snapshot_fix:
    early_checks = early_checks.replace('RST_N && EN && !CE_F && MC.READ_LATCH',
                                        'RST_N && !CE_F && MC.READ_LATCH', 1)
replace_once(' assign di=IO_SEL?IO_DO:LDI;', early_checks + ' assign di=IO_SEL?IO_DO:LDI;')

reference_match = re.search(r' TMS34020_MC REF\(.*?\);', fixture, re.S)
assert reference_match
reference_instance = reference_match.group(0)
original_instance = reference_instance.replace('TMS34020_MC REF(', 'TMS34020_MC_FINAL_ORACLE ORIGINAL_F(', 1)
output_widths = {'DIN': 32, 'DIN_F': 32, 'CACHE_WR': 1, 'WAIT': 1,
                 'DBUS_A': 32, 'DBUS_DO': 32, 'DBUS_RAS': 1, 'DBUS_WE': 1,
                 'DBUS_RD': 1, 'DBUS_RD_EXT': 1, 'DBUS_BE': 4, 'DBUS_CODE': 4,
                 'DBUS_ANY_BE': 1, 'DBUS_ANY_BE_FG': 1}
original_wires, original_comparisons = [], []
for port, width in output_widths.items():
    pattern = r'\.' + port + r'\([^()]*\)'
    found = list(re.finditer(pattern, original_instance))
    assert len(found) <= 1
    if not found:
        continue
    wire = 'original_F_' + port
    original_wires.append(' wire ' + (f'[{width-1}:0] ' if width > 1 else '') + wire + ';')
    original_instance = re.sub(pattern, '.' + port + '(' + wire + ')', original_instance, count=1)
    if port != 'DIN':
        original_comparisons.append('MC.' + port + ' === ' + wire)
original_proof = '\n'.join(original_wires) + original_instance + '''
 integer original_final_checks=0,original_final_en0_checks=0;
 always @(negedge CLK) if(RST_N) begin
  assert(ORIGINAL_FINAL_COMPARISONS)
   else $fatal(1,"current MC final F result or architectural bus output differs from immutable original full MC");
  original_final_checks++;
  if(!EN) original_final_en0_checks++;
 end
'''.replace('ORIGINAL_FINAL_COMPARISONS', ' && '.join(original_comparisons))
replace_once(reference_instance, reference_instance + '\n' + original_proof)
replace_once('bit clk=0,mem_clk=0,reset_n=0,enabled=1,paused=0,phase=0;',
             'bit clk=0,mem_clk=0,reset_n=0,enabled=1,paused=0,manual_phase=0;')
clock_model = ''' always @(negedge clk) manual_phase=~manual_phase;
 localparam bit use_real_phase=REAL_PHASE_VALUE;
 wire real_f,real_r,real_v;
 bt_clock_enables phase_contract(.clk(clk),.reset(!reset_n),.ce_f(real_f),.ce_r(real_r),.vce(real_v));
 wire phase=use_real_phase?real_f:manual_phase;
 wire raw_phase_f=use_real_phase?real_f:manual_phase;
 wire raw_phase_r=use_real_phase?real_r:!manual_phase;
 wire f,r,pause_halted;
 // The original stimulus variable is the pause request at the same
 // interface as the board's registered pause_cpu. It no longer raw-masks
 // phases: compile and consume the exact board bridge instead.
 bt_pause_bridge pause_contract(.clk(clk),.reset(!reset_n),.pause_req(paused),
  .raw_ce_f(raw_phase_f),.raw_ce_r(raw_phase_r),.ce_f(f),.ce_r(r),.halted(pause_halted));
 integer phase_f_cycles=0,phase_r_cycles=0,phase_idle_cycles=0;
 always @(posedge clk) if(reset_n && enabled && !paused) begin
  if(f) phase_f_cycles++;
  else if(r) phase_r_cycles++;
  else phase_idle_cycles++;
 end
 task automatic align_real_request_release(input bit to_r);
  // Preserve each fixture's intended raw F/R request release while the
  // real controller can insert an idle slot. The actual bridge decides
  // when an effective phase resumes; every original minimum hold applies.
  if(use_real_phase) while(!(to_r?real_r:real_f)) begin @(negedge clk);#0.01;end
 endtask
 bit halt_previous=0,await_resume=0,saw_resumed_f=0;
 integer halt_acknowledgments=0,resumed_f_cycles=0,resumed_r_cycles=0,halt_sys_cycles=0;
 integer halted_memory_cycles=0,halted_live_memory_cycles=0;
 always @(posedge clk) begin
  if(!reset_n) begin halt_previous=0;await_resume=0;saw_resumed_f=0;end
  else begin
   if(pause_halted && !halt_previous) halt_acknowledgments++;
   if(pause_halted && paused) begin
    assert(!f && !r) else $fatal(1,"acknowledged board halt emitted a CPU phase");
    halt_sys_cycles++;
    await_resume=1;
    saw_resumed_f=0;
   end
   if(await_resume && !paused && f) begin saw_resumed_f=1;resumed_f_cycles++;end
   if(await_resume && r) begin
    assert(saw_resumed_f) else $fatal(1,"effective resumed R preceded included F after acknowledged halt");
    resumed_r_cycles++;await_resume=0;saw_resumed_f=0;
   end
   halt_previous=pause_halted;
  end
 end
 always @(posedge mem_clk) if(reset_n && pause_halted && paused) begin
  halted_memory_cycles++;
  if(dut.CPU.MC.MC_STATE || dut.CPU.MC.CACHE_WR || dut.SPR_BUSY || dut.FG_HOLE_COPY)
   halted_live_memory_cycles++;
 end
'''.replace('REAL_PHASE_VALUE', "1'b1" if args.phase == 'production' else "1'b0")
replace_once(' always @(negedge clk) phase=~phase;\n wire f=phase&&!paused,r=!phase&&!paused;', clock_model)
replace_once('repeat(hold_cycles)@(negedge clk);#0.01;pause_ack++;paused=0;',
             'repeat(hold_cycles)@(negedge clk);#0.01;align_real_request_release((hold_cycles%2)==0);pause_ack++;paused=0;')
replace_once('repeat(9)@(negedge clk);#0.01;pause_ack++;paused=0;',
             'repeat(9)@(negedge clk);#0.01;align_real_request_release(freeze_mode==3);pause_ack++;paused=0;')
trace = '''
  // Bounded diagnostic only: record the first command preparation/capture
  // phases before any preserved MC assertion can stop the simulation.
  realtime last_early_capture=0;
  realtime last_en_change=0;
  bit previous_enabled=1;
  always @(posedge clk) if(reset_n && enabled && !f && dut.CPU.MC.READ_LATCH)
   last_early_capture<=$realtime;
  always @(negedge clk) begin
   #0.03;
   if(enabled != previous_enabled) begin
    last_en_change=$realtime;
    $display("STAGE_EN_EDGE t=%0t EN=%b F=%b R=%b paused=%b halted=%b req=%h bus=%h latch=%b",$time,enabled,f,r,paused,pause_halted,req_addr,dut.LA,dut.CPU.MC.READ_LATCH);
    previous_enabled=enabled;
   end
   if(reset_n && enabled && f && dut.CPU.MC.READ_LATCH &&
      (dut.CPU.MC.READ_WORD_E !== dut.CPU.MC_RETURN_WORD ||
       dut.CPU.MC.READ_EXTENDED_E !== dut.CPU.MC.MC_EXT_WORD))
    $display("STAGE_FAIL_PREP t=%0t EN=%b F=%b R=%b req=%h reqsize=%h bus=%h state=%b pend=%b latch=%b io=%b misc=%b mem=%b ddr=%b paused=%b halted=%b actualE=%h rawE=%h finalF=%h refE=%h extE=%b extF=%b last_early=%0.3f last_EN_change=%0.3f",$time,enabled,f,r,req_addr,req_size,dut.LA,dut.CPU.MC.MC_STATE,dut.CPU.MC.MC_READ_PEND,dut.CPU.MC.READ_LATCH,dut.CPU.IO_SEL,dut.MISC_SEL,dut.CPU.MC_MEM_SELECTED,dut.CPU.MC_DDR_SELECTED,paused,pause_halted,dut.CPU.MC.READ_WORD_E,dut.CPU.di_e,dut.CPU.MC_RETURN_WORD,dut.CPU.REF.READ_WORD_E,dut.CPU.MC.READ_EXTENDED_E,dut.CPU.MC.MC_EXT_WORD,last_early_capture,last_en_change);
  end
  always @(negedge clk) if(reset_n && ($realtime < 1500 || (dut.CPU.MC.READ_LATCH && $realtime < 3000))) begin
   #0.02;
   $display("STAGE_TRACE t=%0t F=%b R=%b EN=%b paused=%b rawF=%b rawR=%b req=%h r=%b w=%b bus=%h state=%b pend=%b latch=%b io=%b misc=%b pal_accessed=%b pal_data=%h dut_early=%h ref_early=%h rawE=%h rawFword=%h heldE=%h heldF=%h last_early=%0.3f age_now=%0.3f",$time,f,r,enabled,paused,real_f,real_r,req_addr,req_read,req_write,dut.LA,dut.CPU.MC.MC_STATE,dut.CPU.MC.MC_READ_PEND,dut.CPU.MC.READ_LATCH,dut.CPU.IO_SEL,dut.MISC_SEL,dut.PAL_ACCESSED,dut.PAL_READ_DATA,dut.CPU.MC.READ_WORD_E,dut.CPU.REF.READ_WORD_E,dut.CPU.di_e,dut.CPU.di,dut.CPU.MC_RETURN_WORD_E,dut.CPU.MC_RETURN_WORD,last_early_capture,$realtime-last_early_capture);
  end
'''
if en0_snapshot_fix:
    trace = trace.replace('reset_n && enabled && !f && dut.CPU.MC.READ_LATCH',
                          'reset_n && !f && dut.CPU.MC.READ_LATCH', 1)
replace_once(' task automatic wait_f;', trace + ' task automatic wait_f;')

native64 = '''
 integer native64_read_cases=0,native64_en0_cases=0,en0_snapshot_loads=0,en0_r_consumer_exclusions=0;
 bit [63:0] native64_sizes=0,native64_en0_sizes=0;
 bit [31:0] native64_alignments=0;
 always @(posedge clk) if(reset_n) begin
  if(enabled && f && dut.CPU.MC.READ_LATCH) begin
   native64_sizes[dut.CPU.MC.DIN_FS]=1;
   native64_alignments[dut.CPU.MC.DIN_BA]=1;
  end
  if(!enabled && !f && dut.CPU.MC.READ_LATCH) en0_snapshot_loads++;
  if(!enabled && r && dut.CPU.din !== dut.CPU.din_f) en0_r_consumer_exclusions++;
 end
 task automatic native64_access(input [31:0] address,input [5:0] size,input bit suspend_en);
  if(!suspend_en) access(0,address,0,size,0);
  else begin
   settle();wait_f();req_addr=address;req_size=size;req_read=1;
   @(posedge clk);@(negedge clk);#0.01;req_read=0;
   wait(dut.CPU.MC.READ_LATCH);@(negedge clk);#0.01;enabled=0;
   repeat(6+integer'(size%7))@(negedge clk);#0.01;
   while(!f)begin @(negedge clk);#0.01;end
   assert(dut.CPU.MC.READ_LATCH)else $fatal(1,"encoded-size EN pause dropped an acknowledged read");
   enabled=1;native64_en0_cases++;native64_en0_sizes[size]=1;settle();
  end
  native64_read_cases++;
 endtask
'''
replace_once(' task automatic acknowledged_en0(', native64 + ' task automatic acknowledged_en0(')
native64_stimulus = '''
  // Add every six-bit encoded size without altering the original legal
  // 1..32 read/write matrix or its assertions. EN suspension resumes F.
  for(integer bank=0;bank<2;bank++)for(integer size=0;size<64;size++)for(integer align=0;align<32;align++)
   native64_access(32'hb0000400+bank*32'h04000000+align,6'(size),((size+align)%4)==0);
'''
replace_once("  access(0,32'hc0000100,0,32,0);", native64_stimulus + "  access(0,32'hc0000100,0,32,0);")
summary = '''
  assert(dut.CPU.early_checks>1000 && dut.CPU.early_mem_checks>0 && dut.CPU.early_late_checks>0 && dut.CPU.early_io_checks>0 && dut.CPU.early_io_next_changes>0)
   else $fatal(1,"missing exact current early-stage owner/late-IO coverage");
  $display("EARLY_CPU_STAGE checks=%0d memory=%0d live_late=%0d io=%0d io_next_changes=%0d",dut.CPU.early_checks,dut.CPU.early_mem_checks,dut.CPU.early_late_checks,dut.CPU.early_io_checks,dut.CPU.early_io_next_changes);
  assert(dut.CPU.early_palette_checks>0 && dut.CPU.early_palette_changes>0)
   else $fatal(1,"missing changed palette next-state early capture");
  foreach(dut.CPU.early_palette_byte[b]) assert(dut.CPU.early_palette_byte[b]>0)
   else $fatal(1,"missing palette byte lane %0d",b);
  assert(phase_f_cycles>1000 && phase_r_cycles>1000 && (!use_real_phase || (phase_idle_cycles>1000 && dut.CPU.early_idle_checks>0)))
   else $fatal(1,"missing real F/R/idle phase or idle early-load coverage");
  $display("EARLY_PALETTE checks=%0d changes=%0d byte0=%0d byte1=%0d byte2=%0d",dut.CPU.early_palette_checks,dut.CPU.early_palette_changes,dut.CPU.early_palette_byte[0],dut.CPU.early_palette_byte[1],dut.CPU.early_palette_byte[2]);
  $display("EARLY_PHASE real=%0d F=%0d R=%0d idle=%0d captures_R=%0d captures_idle=%0d",use_real_phase,phase_f_cycles,phase_r_cycles,phase_idle_cycles,dut.CPU.early_r_checks,dut.CPU.early_idle_checks);
  assert(halt_acknowledgments>=4 && resumed_f_cycles>=4 && resumed_r_cycles>=4 && halt_sys_cycles>20 && halted_memory_cycles>50 && halted_live_memory_cycles>0)
   else $fatal(1,"missing acknowledged halt, legal F/R resume, or live memory-clock progress coverage");
  $display("BOARD_PAUSE halt_ack=%0d resumed_F=%0d resumed_R=%0d halt_SYS=%0d halted_MEM=%0d live_halted_MEM=%0d request_release_F=%0d request_release_R=%0d",halt_acknowledgments,resumed_f_cycles,resumed_r_cycles,halt_sys_cycles,halted_memory_cycles,halted_live_memory_cycles,pause_resume_f,pause_resume_r);
  assert(dut.CPU.original_final_checks>1000 && dut.CPU.original_final_en0_checks>100)
   else $fatal(1,"missing immutable original F/EN0 comparison coverage");
  assert(native64_read_cases==4096 && native64_en0_cases==1024 && (&native64_sizes) && (&native64_en0_sizes) && (&native64_alignments) && en0_snapshot_loads>100)
   else $fatal(1,"missing complete encoded field size/alignment or preparatory EN0 capture coverage");
  $display("ORIGINAL_MC_FINAL checks=%0d EN0_checks=%0d",dut.CPU.original_final_checks,dut.CPU.original_final_en0_checks);
  $display("NATIVE64_MC read_cases=%0d EN0_cases=%0d EN0_snapshot_loads=%0d EN0_nonconsumer_R_differences=%0d sizes=%h EN0_sizes=%h alignments=%h",native64_read_cases,native64_en0_cases,en0_snapshot_loads,en0_r_consumer_exclusions,native64_sizes,native64_en0_sizes,native64_alignments);
'''
replace_once('  $finish;', summary + '  $finish;')
if address_class_sideband:
    address_class_decoder = augment_address_class_fixture(replace_once, current_mc.decode().replace('\r\n', '\n'), address_class_old_bt, address_class_current_bt)
if combined_ddr_oracle:
    combined_ddr_scope = augment_combined_ddr_fixture(replace_once, top_source)
restored = fixture
for transform in reversed(transforms):
    before, after, *count = transform
    expected = count[0] if count else 1
    assert restored.count(after) == expected
    restored = restored.replace(after, before, expected)
assert restored == old_fixture, 'An old assertion or stimulus was altered outside the declared replacements'
assert stage(fixture) == stage_file.read_bytes().decode() == stage(cpu_text)
fixture_file = directory / 'ddr_be_bridge_tb.sv'
fixture_file.write_bytes(fixture.encode())
manifest = {
    'schema': 'bt-current-ddr-be-stage-adapter-v2',
    'cpu_sha256': sha(cpu_bytes),
    'production_source_overlay': str(source_root),
    'phase_mode': args.phase,
    'board_pause_source_sha256': sha(pause_source),
    'actual_top_pause_ports': pause_ports,
    'actual_top_clock_ports': clock_ports,
    'actual_top_bt_phase_ports': {key: bt_ports[key] for key in ('CE_F', 'CE_R')},
    'actual_top_nvram_pause_ports': nvram_ports,
    'immutable_original_full_mc_sha256': sha(original_mc),
    'immutable_original_full_mc_canonical_lf_sha256': sha(canonical_lf(original_mc)),
    'immutable_original_mc_git_commit': BASE_MC_GIT_COMMIT,
    'immutable_original_mc_git_blob_raw_sha256': sha(git_original_mc),
    'current_full_mc_sha256': sha(current_mc),
    'current_full_mc_canonical_lf_sha256': sha(canonical_lf(current_mc)),
    'en0_preparatory_snapshot_fix': en0_snapshot_fix,
    'address_class_sideband': address_class_sideband,
    'address_class_v9_edge': address_class_edge,
    'address_class_decoder_scope': address_class_decoder,
    'combined_ddr_scope': combined_ddr_scope,
    'combined_ddr_oracle': combined_ddr_oracle,
    'immutable_final_oracle': {'path': relative(oracle_file), 'sha256': sha(oracle_file.read_bytes()), 'transform': 'Full immutable MC, module rename only, temporarily SYNTHESIS for historical nonproduction assertions. Candidate MC and REF assertions stay enabled. Compare DIN_F and every architectural bus/output except the intentionally preparatory DIN on every SYS cycle, including EN0.'},
    'native64_scope': '4096 additive read cases: all 64 encoded FS values x 32 alignments x two BG owners, including 1024 acknowledged EN0 cases with F-first resume. Original 2048 legal field read/write cases and both original EN0 stimuli remain unchanged.',
    'legacy_runner': relative(LEGACY), 'legacy_runner_sha256': sha(LEGACY.read_bytes()),
    'legacy_fixture': relative(OLD_TB), 'legacy_fixture_sha256': sha(OLD_TB.read_bytes()),
    'legacy_stage': relative(OLD_STAGE), 'legacy_stage_sha256': sha(OLD_STAGE.read_bytes()),
    'runner': relative(Path(__file__)), 'runner_sha256': sha(Path(__file__).read_bytes()),
    'stage': relative(stage_file), 'stage_sha256': sha(stage_file.read_bytes()),
    'fixture': relative(fixture_file), 'fixture_sha256': sha(fixture_file.read_bytes()),
    'exact_full_cpu_stage_copied': True,
    'original_assertions_preserved': True,
    'original_commands_and_minimum_pause_durations_preserved': True,
    'old_capture_block_unchanged_except_early_return_wire': True,
    'io_next_model': 'Exact next value of the existing R-phase IO register update; raw reference uses IO_NEXT for early capture and IO_Q for F capture.',
    'palette_next_model': 'Independent raw owner D: reset or CE_R/MISC/read/not-accessed/320 and PAL_RBYTE-selected actual palette bytes. No EN guard because the unchanged BT palette register has none. Final raw bus reference is unchanged.',
    'phase_model': 'Exact board bt_pause_bridge consumes the original pause request stimuli. Unchanged bt_clock_enables F,R,F,R,idle for production, original alternating F/R adversarial timing otherwise. Raw request release aligns to each intended phase after at least its original hold; the compiled bridge must include F before effective resumed R. Existing pause_resume counters refer to request release, not effective phase.',
    'postmux_bank_observation': 'The removed common read_bank selector is observed as the four current registered per-bank QGATE bits (ram_models.qg); the original owner equality remains unchanged. Physical primitives require separate vendor qualification.',
    'transforms': [list(item) for item in transforms],
}
(directory / 'fixture_manifest.json').write_text(json.dumps(manifest, indent=2))

execution = LEGACY.read_text()
assert execution.count("'rtl/TMS34020/TMS34020_MC.sv',") == 1
execution = execution.replace("'rtl/TMS34020/TMS34020_MC.sv',", repr(relative(oracle_file)) + ", 'rtl/TMS34020/TMS34020_MC.sv',", 1)
assert execution.count("'rtl/BT.sv',") == 1
execution = execution.replace("'rtl/BT.sv',", "'rtl/BT.sv', 'rtl/bt_clock_enables.sv', 'rtl/bt_pause_bridge.sv',", 1)
if combined_ddr_oracle:
    execution = execution.replace("'rtl/BT.sv',", repr(combined_ddr_oracle['path']) + ", 'rtl/ddram.sv', 'rtl/BT.sv',", 1)
execution = execution.replace('build/resource_audit/ddr_be_bridge_tb.sv', relative(fixture_file))
execution = execution.replace('build/resource_audit/ddr_return_split/MC_MEM_RETURN_STAGE.svh', relative(stage_file))
execution, reads_replaced = re.subn(r'\(root\s*/\s*([^\n\)]+)\)\.read_bytes\(\)', lambda match: '_candidate_read(' + match.group(1) + ')', execution)
assert reads_replaced == 6, 'Unexpected source-reading contract in retained qualifier'
assert "assert _stage_data.decode().strip() in _cpu_data.decode()" in execution
anchor = "(workspace / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\\n')"
assert execution.count(anchor) == 1
receipt_audit = "receipt['current_stage_adapter'] = " + repr(manifest) + "\n"
receipt_audit += "receipt['sources'][" + repr(relative(OLD_TB)) + "] = " + repr(sha(OLD_TB.read_bytes())) + "\n"
receipt_audit += "receipt['sources'][" + repr(relative(OLD_STAGE)) + "] = " + repr(sha(OLD_STAGE.read_bytes())) + "\n"
receipt_audit += "receipt['sources'][" + repr(relative(Path(__file__))) + "] = " + repr(sha(Path(__file__).read_bytes())) + "\n"
receipt_audit += "assert hashlib.sha256(_candidate_read('rtl/TMS34020/TMS34020.sv')).hexdigest() == " + repr(sha(cpu_bytes)) + ", 'CPU changed during proof'\n"
receipt_audit += "receipt['bound_production_inputs']=dict(_bound_sources)\n"
receipt_audit += "report=(workspace/'run.log').read_text(errors='replace') if run_exit == 0 else ''\n"
receipt_audit += "marker=re.search(r'^EARLY_CPU_STAGE (.+)$',report,re.MULTILINE)\n"
receipt_audit += "assert marker if run_exit == 0 else True, 'Required early-stage coverage absent'\n"
receipt_audit += "receipt['early_stage_coverage']={k:int(v) for k,v in re.findall(r'(\\w+)=(\\d+)',marker.group(1))} if marker else {}\n"
coverage_labels = [('EARLY_PALETTE','palette_early_coverage'),('EARLY_PHASE','phase_coverage'),('BOARD_PAUSE','board_pause_coverage'),('ORIGINAL_MC_FINAL','original_final_coverage'),('NATIVE64_MC','native64_coverage')]
if address_class_sideband:
    coverage_labels += [('ADDRESS_CLASS', 'address_class_coverage'), ('ADDRESS_DECODER', 'address_decoder_coverage')]
if combined_ddr_oracle:
    coverage_labels += [('COMBINED_DDR', 'combined_ddr_coverage')]
receipt_audit += 'for label,key in ' + repr(coverage_labels) + ':\n'
receipt_audit += "    match=re.search(r'^'+label+r' (.+)$',report,re.MULTILINE)\n"
receipt_audit += "    assert match if run_exit == 0 else True, 'Missing '+label\n"
receipt_audit += "    receipt[key]={k:int(v) for k,v in re.findall(r'(\\w+)=(\\d+)',match.group(1))} if match else {}\n"
execution = execution.replace(anchor, receipt_audit + anchor, 1)
body_file = directory / 'executed_qualifier.py'
body_file.write_bytes(execution.encode())
print('current_fixture=' + str(fixture_file), flush=True)
print('fixture_manifest=' + str(directory / 'fixture_manifest.json'), flush=True)
exec(compile(execution, str(body_file), 'exec'), {'__name__': '__main__', '__file__': str(LEGACY), '_candidate_read': candidate_read, '_bound_sources': bound_sources})
