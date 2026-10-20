"""Exact v9 address-class edge and additive, source-bound stage checks."""
import hashlib
from pathlib import Path
import re

from prepare_bt_address_class import BASE, address_class_transform
from prepare_bt_en0_snapshot_candidate import canonical_lf, en0_snapshot_transform


def sha(data):
    return hashlib.sha256(data).hexdigest()


def verify_edge(root, candidate_read, original_mc, source_root=None):
    baseline = root / 'build/timing_closure_20261011/integrated_v9_private'
    result = {}
    combined = b'BT_PARALLEL_DDR_DATA_BEGIN' in candidate_read('rtl/BT.sv')
    if combined:
        from bt_combined_stage_fixture import verify_combined_edge
        combined_expected, combined_provenance = verify_combined_edge(root, source_root, candidate_read)
        result['parallel_ddr_composition'] = combined_provenance
    result['edge_type'] = 'bt-class-parallel-ddr-v1' if combined else 'bt-address-class-v1'
    for name, expected in BASE.items():
        before = (en0_snapshot_transform(original_mc) if name.endswith('_MC.sv')
                  else (baseline / name).read_bytes())
        assert sha(before) == expected, 'Pinned complete v9 input changed: ' + name
        after = candidate_read(name)
        transformed = address_class_transform(name, before)
        if combined and name == 'rtl/BT.sv':
            transformed = combined_expected[name]
        assert canonical_lf(after) == canonical_lf(transformed), \
            'Address-class candidate changed outside its exact v9 edge: ' + name
        result[name] = {'before_sha256': sha(before), 'after_sha256': sha(after),
                        'before_canonical_lf_sha256': sha(canonical_lf(before)),
                        'after_canonical_lf_sha256': sha(canonical_lf(after)),
                        'explicit_transform_matches': True}
    helper = Path(__file__).with_name('prepare_bt_address_class.py')
    result['transform_helper'] = {'path': str(helper), 'sha256': sha(helper.read_bytes())}
    result['fixture_helper'] = {'path': str(Path(__file__)),
                                'sha256': sha(Path(__file__).read_bytes())}
    return result, (baseline / 'rtl/BT.sv').read_text(), candidate_read('rtl/BT.sv').decode()


def function_from_source(mc):
    matches = re.findall(r'\tfunction automatic \[3:0\] AddressClass\(.*?\tendfunction', mc, re.S)
    assert len(matches) == 1, 'Expected one exact published address-class function'
    return matches[0].replace('AddressClass', 'class_from_source')


def port_expression(text, instance, port):
    start = re.search(r'\bFG_VRAM\s+' + instance + r'\s*\(', text)
    assert start, instance
    scope = text[start.end():text.index('\t);', start.end())]
    anchor = re.search(r'\.' + port + r'\s*\(', scope)
    assert anchor, (instance, port)
    first = anchor.end()
    depth = 1
    for at in range(first, len(scope)):
        if scope[at] == '(':
            depth += 1
        elif scope[at] == ')':
            depth -= 1
            if depth == 0:
                return scope[first:at]
    raise AssertionError('Unterminated actual instance expression')


def declarations(text):
    names = ['BG0_SEL', 'BG1_SEL', 'FG_CPU_ADDR_MATCH', 'FG_DISP_SEL', 'FG_DRAW_SEL',
             'FG0_SEL', 'FG0_SCRN', 'FG1_SEL', 'FG1_SCRN']
    result = {}
    for name in names:
        matches = re.findall(r'\bwire\s+' + name + r'\s*=\s*(.*?);', text, re.S)
        assert len(matches) == 1, name
        result[name] = matches[0]
    for bank in range(2):
        for port in ('TRANSFER', 'RAS_N'):
            result[f'FG{bank}_{port}_PIN'] = port_expression(text, f'FG{bank}_VRAM', port)
    return result


def decoder_checks(old_bt, current_bt, mc):
    old, new = declarations(old_bt), declarations(current_bt)
    assert list(old) == list(new)
    lines = [function_from_source(mc), '''
 integer address_decode_cases=0;
 task automatic check_address_decode(input [9:0] high_bits,input [3:0] code_bits,input bit display,input bit ras);
  logic [31:0] LA;
  logic [15:0] DISP_CONTROL;
  logic [3:0] CPU_ADDR_CLASS;
  logic RAS_N;''']
    for side in ('old', 'new'):
        lines += ['  logic class_' + side + '_' + name + ';' for name in old]
    lines += ["  LA={high_bits,18'h2a55a,code_bits};DISP_CONTROL={display,15'b0};RAS_N=ras;",
              '  CPU_ADDR_CLASS=class_from_source(LA);']
    for side, expressions in [('old', old), ('new', new)]:
        for name, expression in expressions.items():
            rhs = re.sub(r'\b(?:' + '|'.join(old) + r')\b',
                         lambda m: 'class_' + side + '_' + m.group(0), expression)
            lines.append('  class_' + side + '_' + name + '=' + rhs + ';')
    vector = lambda side: '{' + ','.join('class_' + side + '_' + name for name in old) + '}'
    lines += ['  assert(' + vector('old') + ' === ' + vector('new') + ')',
              '   else $fatal(1,"published FG/BG/display/draw/transfer/screen/RAS decoder differs high=%h code=%h display=%b RAS=%b",high_bits,code_bits,display,ras);',
              '  address_decode_cases++;', ' endtask', '''
 initial begin
  for(integer hi=0;hi<1024;hi++)for(integer code=0;code<16;code++)
   for(integer display=0;display<2;display++)for(integer ras=0;ras<2;ras++)
    check_address_decode(10'(hi),4'(code),1'(display),1'(ras));
 end
''']
    return '\n'.join(lines), {'scope': 'All 1024 relevant high address values x all16 live bus codes x both display maps x both RAS levels. Exact source expressions copied for BG0/BG1/commonFG/display/draw/bank/screen, both TRANSFER pins and both final foreground RAS pins.',
                              'old_expressions': old, 'current_expressions': new,
                              'class_function_sha256': sha(function_from_source(mc).encode())}


def augment(replace_once, mc, old_bt, current_bt):
    replace_once(' output WRITE_ANY_ALL,WRITE_ANY_FG\n',
                 ' output WRITE_ANY_ALL,WRITE_ANY_FG,\n output [3:0] ADDR_CLASS\n')
    replace_once('.DBUS_A(ba),.DBUS_DI(MC_RETURN_WORD)',
                 '.DBUS_A(ba),.DBUS_ADDR_CLASS(ADDR_CLASS),.DBUS_DI(MC_RETURN_WORD)')
    monitor = function_from_source(mc) + '''
 integer address_class_cycles=0,address_class_en0_cycles=0,address_class_hold_cycles=0;
 integer address_class_launch_read=0,address_class_launch_write=0,address_class_launch_cache=0;
 integer address_class_launch_refresh=0,address_class_launch_read_ext=0,address_class_launch_write_ext=0;
 bit address_refresh_active=0;
 always @(posedge CLK) if(RST_N) begin
  assert(ADDR_CLASS === {(ba[31:22]=={8'hB4,2'b00}),(ba[31:22]=={8'hB0,2'b00}),
                        ((ba[31:27]&5'b10111)==5'b10100),(ba[31:27]==5'b10100&&ba[25:22]==0)})
   else $fatal(1,"published four address hints are not the live MC address at SYS edge");
  address_class_cycles++;
  if(!EN)address_class_en0_cycles++;
  if(EN&&CE_F&&!MC.MC_STATE&&(MC.MC_READ_EXT||MC.MC_WRITE_EXT||ddr_be_bridge_tb.req_read||ddr_be_bridge_tb.req_write||ddr_be_bridge_tb.req_cache))begin
   if(MC.MC_READ_EXT)address_class_launch_read_ext++;
   else if(MC.MC_WRITE_EXT)address_class_launch_write_ext++;
   else if(ddr_be_bridge_tb.req_read&&!ddr_be_bridge_tb.req_cache)address_class_launch_read++;
   else if(ddr_be_bridge_tb.req_write&&!ddr_be_bridge_tb.req_cache)address_class_launch_write++;
   else address_class_launch_cache++;
  end else address_class_hold_cycles++;
 end
 always @(negedge CLK) begin
  #0.002;
  if(RST_N)assert(ADDR_CLASS === class_from_source(ba))
   else $fatal(1,"address hints lost their corresponding address after SYS edge");
  else assert(ADDR_CLASS===0&&ba===0)
   else $fatal(1,"address hint/address asynchronous reset identity differs");
  if(!RST_N)address_refresh_active=0;
  else begin
   // SCRREF_PEND is block-local in the actual MC. Count the real published
   // refresh transaction, rather than relying on a simulator's local name.
   if(ras&&code==4'b0100&&!address_refresh_active)address_class_launch_refresh++;
   address_refresh_active=ras&&code==4'b0100;
  end
 end
'''
    replace_once(' assign LA={ba[31:4],code};', monitor + ' assign LA={ba[31:4],code};')
    exhaustive, coverage = decoder_checks(old_bt, current_bt, mc)
    replace_once(' bit scan_hblank=1,scan_vblank=1;', exhaustive + '\n bit scan_hblank=1,scan_vblank=1;')
    probe = '''
 bit class_probe_reset_n=0,class_probe_enabled=1,class_probe_write_pre=0,class_probe_done=0;
 bit [31:0] class_probe_addr=0;
 wire [31:0] class_probe_bus,class_probe_original_bus;
 wire [3:0] class_probe_hints;
 wire class_probe_ras,class_probe_we,class_probe_rd;
 integer class_probe_skips=0,class_probe_en0_holds=0,class_probe_idle_holds=0,class_probe_async_resets=0,class_probe_edges=0;
 TMS34020_MC CLASS_PROBE(.CLK(clk),.RST_N(class_probe_reset_n),.EN(class_probe_enabled),
  .CE_F(raw_phase_f),.CE_R(raw_phase_r),.RES_N(1'b1),.ADDR(class_probe_addr),.DOUT(32'b0),
  .FS(6'd32),.FS0(6'd32),.FS1(6'd32),.FIELD_SELECT(1'b0),.READ(1'b0),.WRITE(1'b0),
  .WRITE_PRE(class_probe_write_pre),.PIX(1'b1),.PC(32'b0),.CACHE(1'b0),.VECT(1'b0),
  .PIX_WMASK(32'hffffffff),.SCRREF_ADDR(32'b0),.SCRREF_RUN(1'b0),.CST(1'b0),
  .DBUS_A(class_probe_bus),.DBUS_ADDR_CLASS(class_probe_hints),.DBUS_RAS(class_probe_ras),
  .DBUS_WE(class_probe_we),.DBUS_RD(class_probe_rd),.DBUS_DI(32'b0),.DBUS_DI_E(32'b0),.DBUS_RDY(1'b1));
 TMS34020_MC_FINAL_ORACLE CLASS_PROBE_ORIGINAL(.CLK(clk),.RST_N(class_probe_reset_n),.EN(class_probe_enabled),
  .CE_F(raw_phase_f),.CE_R(raw_phase_r),.RES_N(1'b1),.ADDR(class_probe_addr),.DOUT(32'b0),
  .FS(6'd32),.FS0(6'd32),.FS1(6'd32),.FIELD_SELECT(1'b0),.READ(1'b0),.WRITE(1'b0),
  .WRITE_PRE(class_probe_write_pre),.PIX(1'b1),.PC(32'b0),.CACHE(1'b0),.VECT(1'b0),
  .PIX_WMASK(32'hffffffff),.SCRREF_ADDR(32'b0),.SCRREF_RUN(1'b0),.CST(1'b0),
  .DBUS_A(class_probe_original_bus),.DBUS_DI(32'b0),.DBUS_DI_E(32'b0),.DBUS_RDY(1'b1));
 always @(negedge clk)begin
  #0.002;
  assert(class_probe_bus===class_probe_original_bus)
   else $fatal(1,"pixel-skipped address/hold differs from immutable full MC");
  if(class_probe_reset_n)assert(class_probe_hints===class_from_source(class_probe_bus))
   else $fatal(1,"pixel-skipped/EN0-held address class differs");
  else assert(class_probe_hints===0&&class_probe_bus===0)
   else $fatal(1,"independent MC address-class reset differs");
  class_probe_edges++;
 end
 task automatic class_probe_wait_f;
  while(!raw_phase_f)begin @(negedge clk);#0.01;end
 endtask
 initial begin
  wait(reset_n);@(negedge clk);#0.01;class_probe_reset_n=1;
  for(integer target=0;target<16;target++)begin
   class_probe_wait_f();
   case(target%8)
    0:class_probe_addr=32'ha0000010;
    1:class_probe_addr=32'ha4000010;
    2:class_probe_addr=32'ha8000010;
    3:class_probe_addr=32'hac000010;
    4:class_probe_addr=32'hb0000010;
    5:class_probe_addr=32'hb4000010;
    6:class_probe_addr=32'h00000010;
    7:class_probe_addr=32'hfc000010;
   endcase
   class_probe_write_pre=1;
   @(posedge clk);@(negedge clk);#0.01;class_probe_write_pre=0;
   assert(class_probe_bus===class_probe_addr&&!class_probe_ras&&!class_probe_we&&!class_probe_rd)
    else $fatal(1,"skipped transparent pixel prewrite failed exact address update without a bus transaction");
   class_probe_skips++;
   class_probe_enabled=0;class_probe_write_pre=1;class_probe_addr=~class_probe_addr;
   repeat(6)begin @(negedge clk);#0.01;
    assert(class_probe_bus!==class_probe_addr)else $fatal(1,"EN0 launched a preparatory pixel address");
    class_probe_en0_holds++;
   end
   class_probe_write_pre=0;class_probe_enabled=1;
   repeat(4)begin @(negedge clk);#0.01;
    assert(class_probe_bus!==class_probe_addr)else $fatal(1,"idle request changed the published address");
    class_probe_idle_holds++;
   end
   class_probe_reset_n=0;#0.02;
   assert(class_probe_bus===0&&class_probe_hints===0)else $fatal(1,"address/class did not clear on asynchronous reset");
   class_probe_async_resets++;repeat(2)@(negedge clk);#0.01;class_probe_reset_n=1;
  end
  class_probe_done=1;
 end
'''
    replace_once(' task automatic wait_f;', probe + ' task automatic wait_f;')
    summary = '''
  assert(address_decode_cases==65536&&class_probe_done&&class_probe_skips==16&&class_probe_async_resets==16&&class_probe_en0_holds==96&&class_probe_idle_holds==64)
   else $fatal(1,"missing exhaustive decoder or directed pixel-skip/reset/EN0/idle coverage");
  assert(dut.CPU.address_class_cycles>1000&&dut.CPU.address_class_en0_cycles>100&&dut.CPU.address_class_hold_cycles>1000&&
         dut.CPU.address_class_launch_read>0&&dut.CPU.address_class_launch_write>0&&dut.CPU.address_class_launch_cache>0&&
         dut.CPU.address_class_launch_refresh>0&&dut.CPU.address_class_launch_read_ext>0&&dut.CPU.address_class_launch_write_ext>0)
   else $fatal(1,"missing actual full-MC ordinary/cache/refresh/extended launch and held class coverage");
  $display("ADDRESS_CLASS checks=%0d EN0=%0d holds=%0d read=%0d write=%0d cache=%0d refresh=%0d read_ext=%0d write_ext=%0d",dut.CPU.address_class_cycles,dut.CPU.address_class_en0_cycles,dut.CPU.address_class_hold_cycles,dut.CPU.address_class_launch_read,dut.CPU.address_class_launch_write,dut.CPU.address_class_launch_cache,dut.CPU.address_class_launch_refresh,dut.CPU.address_class_launch_read_ext,dut.CPU.address_class_launch_write_ext);
  $display("ADDRESS_DECODER cases=%0d pixel_skips=%0d EN0_holds=%0d idle_holds=%0d async_resets=%0d oracle_edges=%0d",address_decode_cases,class_probe_skips,class_probe_en0_holds,class_probe_idle_holds,class_probe_async_resets,class_probe_edges);
'''
    replace_once('  $finish;', summary + '  $finish;')
    return coverage
