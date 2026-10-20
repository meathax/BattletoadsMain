"""Strict v11 request edge and additive complete-MC/VRAM-pin stage observers.

The old bus, stage fixture and its assertions are retained. The new request
output is driven by the actual candidate MC, never by an oracle proxy.
"""
import hashlib
from pathlib import Path
import re

from prepare_bt_vram_request import BASE, BASE_ROOT, transform
from qualify_bt_address_class_r2 import instance_ports

sha = lambda data: hashlib.sha256(data).hexdigest()
VISIBILITY_BEFORE = '''    if name.endswith('TMS34020_MC.sv'):
        text = data.decode()
        marker = '\\t\\tbit         READ_LATCH;'
        assert text.count(marker) == 1
        text = text.replace(marker, '')
        text = text.replace('\\talways @(posedge CLK or negedge RST_N) begin',
                            '\\tbit READ_LATCH;\\n\\talways @(posedge CLK or negedge RST_N) begin', 1)
        data = text.encode()
        transforms[name] = 'Move READ_LATCH declaration to module scope only; unchanged state logic.'
'''
VISIBILITY_AFTER = '''    if name.endswith('TMS34020_MC.sv') or name.endswith('TMS34020_MC_V11_REQUEST_ORACLE.sv'):
        text = data.decode()
        markers = ['\\t\\tbit         SCRREF_PEND;', '\\t\\tbit         READ_LATCH;',
                   '\\t\\tbit         WRITE_LATCH;', '\\t\\tbit [ 1: 0] FETCH_LSB;']
        for marker in markers:
            assert text.count(marker) == 1, ('Exact persistent-state visibility declaration changed', name, marker)
            text = text.replace(marker, '', 1)
        anchor = '\\talways @(posedge CLK or negedge RST_N) begin'
        assert text.count(anchor) == 1
        declarations = ''.join('\\t' + marker.strip() + '\\n' for marker in markers)
        text = text.replace(anchor, declarations + anchor, 1)
        data = text.encode()
        transforms[name] = 'Declaration-only visibility of four original static persistent clock-block bit states, uniformly in exact before/candidate MC; all logic, reset, update edges and assertions unchanged.'
'''


def visible_complete_state(execution):
    assert execution.count(VISIBILITY_BEFORE) == 1, 'Retained visibility transform changed'
    result = execution.replace(VISIBILITY_BEFORE, VISIBILITY_AFTER, 1)
    assert result.replace(VISIBILITY_AFTER, VISIBILITY_BEFORE, 1) == execution
    return result


def lf(data):
    result = data.replace(b'\r\n', b'\n')
    assert b'\r' not in result, 'Only LF/CRLF normalization is permitted'
    return result


def verify_edge(root, source_root, candidate_read):
    """Return a pinned v11 parent reader for the existing, strict v11 gate."""
    parents, provenance = {}, {}
    for name, digest in BASE.items():
        before = (BASE_ROOT / name).read_bytes()
        assert sha(before) == digest, 'Immutable full v11 input changed: ' + name
        expected, edits, assignments = transform(name, before)
        actual = candidate_read(name)
        assert lf(actual) == lf(expected), 'Undeclared request source change: ' + name
        inverse = lf(actual).decode()
        for edit in reversed(edits):
            assert edit['after'] in inverse
            inverse = inverse.replace(edit['after'], edit['before'], 1)
        assert inverse.encode() == lf(before), 'Request inverse did not recover v11'
        parents[name] = before
        provenance[name] = {
            'before_path': str(BASE_ROOT / name), 'before_sha256': sha(before),
            'before_lf_sha256': sha(lf(before)), 'actual_sha256': sha(actual),
            'actual_lf_sha256': sha(lf(actual)), 'expected_sha256': sha(expected),
            'reversible_exact_parent': True, 'projected_assignments': assignments,
        }
    def parent_read(name):
        return parents[name] if name in parents else candidate_read(name)
    for name in ('prepare_bt_vram_request.py', 'bt_vram_request_fixture.py'):
        helper = Path(__file__).with_name(name)
        provenance[name] = {'path': str(helper), 'sha256': sha(helper.read_bytes())}
    provenance['scope'] = 'Typed exact full-v11 source inverse, not a new simulator, mapped, timing or hardware result.'
    provenance['legacy_ras_reset_added'] = False
    return parent_read, provenance


def function_from_source(mc):
    matches = re.findall(r'\tfunction automatic \[3:0\] VramRequests\(.*?\tendfunction', mc, re.S)
    assert len(matches) == 1
    return matches[0].replace('VramRequests', 'request_from_candidate_source').replace('AddressClass', 'class_from_source')


SELECTORS = ('BG0_SEL', 'BG1_SEL', 'FG_CPU_ADDR_MATCH', 'FG_DISP_SEL',
             'FG_DRAW_SEL', 'FG0_SEL', 'FG0_SCRN', 'FG1_SEL', 'FG1_SCRN')
INSTANCES = (('FG_VRAM', 'FG0_VRAM'), ('FG_VRAM', 'FG1_VRAM'),
             ('BG_VRAM', 'BG0_VRAM_0'), ('BG_VRAM', 'BG0_VRAM_1'),
             ('BG_VRAM', 'BG1_VRAM_0'), ('BG_VRAM', 'BG1_VRAM_1'))


def old_pin_function(old_bt):
    """Copy original v11 selectors and original six RAS ports verbatim."""
    lines = [' function automatic [5:0] vram_ras_before(input [31:0] address,',
             '   input [3:0] bus_code,input bit ras_active,input bit display_page);',
             '  logic [31:0] LA;logic [15:0] DISP_CONTROL;logic [3:0] CPU_ADDR_CLASS;logic RAS_N;']
    lines += ['  logic ' + name + ';' for name in SELECTORS]
    lines += ["  LA={address[31:4],bus_code};DISP_CONTROL={display_page,15'b0};",
              '  CPU_ADDR_CLASS=class_from_source(address);RAS_N=~ras_active;']
    for name in SELECTORS:
        expressions = re.findall(r'\bwire\s+' + name + r'\s*=\s*(.*?);', old_bt, re.S)
        assert len(expressions) == 1, name
        lines.append('  ' + name + '=' + expressions[0] + ';')
    pins = [instance_ports(old_bt, module, instance)['RAS_N'] for module, instance in INSTANCES]
    lines += ['  vram_ras_before={' + ','.join(pins) + '};', ' endfunction']
    return '\n'.join(lines)


def state_names(mc):
    """All original module registers and original persistent clock-block state."""
    text = re.sub(r'\tfunction\b.*?\tendfunction', '', mc, flags=re.S)
    names = []
    for match in re.finditer(r'^\t(?:bit|logic|reg)\s+(?:\[[^\]\n]+\]\s*)?([^;\n]+);', text, re.M):
        for item in match[1].split(','):
            name = item.strip().split('=')[0].strip()
            assert re.fullmatch(r'\w+', name), ('Unsupported state declaration', name)
            names.append(name)
    first = re.search(r'\talways @\(posedge CLK or negedge RST_N\) begin(.*?)\n\t\tif', mc, re.S)
    assert first
    for group in re.findall(r'\bbit\s+(?:\[[^\]]+\]\s*)?([^;]+);', first[1]):
        for name in group.split(','):
            name = name.strip()
            assert re.fullmatch(r'\w+', name)
            names.append(name)
    assert len(names) == len(set(names)) and {'READ_LATCH', 'WRITE_LATCH'} <= set(names)
    return names


def directed_probe(outputs, states):
    declarations = '\n'.join(' wire [' + str(width - 1) + ':0] request_probe_' + side + '_' + signal + ';'
                             for side in ('new', 'old') for signal, width in outputs.values())
    common = '''.CLK(clk),.RST_N(request_probe_reset),.EN(request_probe_en),
 .CE_F(request_probe_f),.CE_R(request_probe_r),.RES_N(1'b1),
 .ADDR(request_probe_address),.DOUT(32'hfedc9876),.FS(request_probe_size),
 .FS0(request_probe_size),.FS1(request_probe_size),.FIELD_SELECT(1'b0),
 .READ(request_probe_read),.WRITE(request_probe_write),.WRITE_PRE(request_probe_pre),
 .PIX(request_probe_pixel),.PC(request_probe_address),.CACHE(request_probe_cache),
 .VECT(request_probe_vector),.PIX_WMASK(32'hffffffff),
 .SCRREF_ADDR(request_probe_address),.SCRREF_RUN(request_probe_screen),.CST(request_probe_cst),
 .DBUS_DI(32'b0),.DBUS_DI_E(32'b0),.DBUS_RDY(1'b1)'''
    instances = []
    for side, module, instance in (('new', 'TMS34020_MC', 'REQUEST_DIRECTED'),
                                    ('old', 'TMS34020_MC_V11_REQUEST_ORACLE', 'REQUEST_DIRECTED_BEFORE')):
        pins = ','.join('.' + port + '(request_probe_' + side + '_' + signal + ')' for port, (signal, width) in outputs.items())
        if side == 'new':
            pins += ',.VRAM_REQUEST(request_probe_bits)'
        instances.append(' ' + module + ' ' + instance + '(' + common + ',' + pins + ');')
    vector = lambda side, instance: '{' + ','.join('request_probe_' + side + '_' + signal for signal, width in outputs.values()) + ',' + ','.join(instance + '.' + name for name in states) + '}'
    body = '''
 bit request_probe_reset=0,request_probe_en=1,request_probe_f=0,request_probe_r=0;
 bit request_probe_read=0,request_probe_write=0,request_probe_pre=0,request_probe_pixel=0;
 bit request_probe_cache=0,request_probe_screen=0,request_probe_cst=0,request_probe_vector=0;
 bit request_probe_done=0;bit [31:0] request_probe_address=0;bit [5:0] request_probe_size=32;
 wire [3:0] request_probe_bits;
 integer request_probe_edges=0,request_probe_overlaps=0,request_probe_en0=0;
 integer request_probe_reset_held_ras=0,request_probe_launches=0,request_probe_transparent=0;
 PROBE_DECLARATIONS
 PROBE_INSTANCES
 always @(negedge clk)begin
  #0.005;
  assert(PROBE_NEW===PROBE_OLD)else $fatal(1,"directed request edge changed original v11 MC state/output");
  assert(request_probe_bits===dut.CPU.requests_from_original(request_probe_new_ba,request_probe_new_code,request_probe_new_ras))
   else $fatal(1,"directed overlapping F/R, reset or EN0 request projection differs");
  request_probe_edges++;
 end
 task automatic request_probe_step(input bit phase_f,input bit phase_r,input bit enable);
  @(negedge clk);#0.01;request_probe_f=phase_f;request_probe_r=phase_r;request_probe_en=enable;
  @(posedge clk);#0.02;
  if(phase_f&&phase_r&&enable)request_probe_overlaps++;
  if(!enable)request_probe_en0++;
 endtask
 task automatic request_probe_drain;
  request_probe_read=0;request_probe_write=0;request_probe_pre=0;request_probe_cache=0;request_probe_screen=0;
  for(integer i=0;i<8;i++)begin
   // Keep an admitted F immediately before every admitted R, as required
   // by the unchanged early-read age assertion. Idle may follow R.
   request_probe_step(1,0,1);request_probe_step(0,1,1);
   request_probe_step(0,0,1);
  end
 endtask
 initial begin
  repeat(3)@(negedge clk);#0.01;request_probe_reset=1;
  for(integer target=0;target<32;target++)begin
   // First finish a real transaction so transparent-prewrite cases begin
   // with the original RAS close event, including after an unreset RAS.
   request_probe_address=0;request_probe_size=32;request_probe_read=1;
   request_probe_pixel=0;request_probe_cst=0;request_probe_vector=0;
   request_probe_step(1,0,1);request_probe_drain();
   assert(!request_probe_new_ras)else $fatal(1,"directed MC did not close priming read");
   case(target%8)
    0:request_probe_address=32'ha000001f;
    1:request_probe_address=32'ha400001f;
    2:request_probe_address=32'ha800001f;
    3:request_probe_address=32'hac00001f;
    4:request_probe_address=32'hb000001f;
    5:request_probe_address=32'hb400001f;
    6:request_probe_address=32'h0000001f;
    7:request_probe_address=32'hc000001f;
   endcase
   request_probe_size=6'(1+(target%63));request_probe_pixel=target[0];request_probe_cst=target[1];
   request_probe_vector=target[2];
   case(target%6)
    0:request_probe_read=1;
    1:begin request_probe_write=1;request_probe_pre=1;end
    2:request_probe_cache=1;
    3:request_probe_screen=1;
    4:begin request_probe_pixel=1;request_probe_pre=1;request_probe_transparent++;end
    5:begin request_probe_read=1;request_probe_size=63;end
   endcase
   // The source contract gives F priority for overlapping phase inputs.
   request_probe_step(1,1,1);request_probe_launches++;
   request_probe_read=0;request_probe_write=0;request_probe_pre=0;request_probe_cache=0;
   request_probe_step(0,0,0);request_probe_step(1,1,0);request_probe_step(0,1,0);
   request_probe_drain();
   // First close a real address-zero read. The retained verification-only
   // DBUS_A_REF is also intentionally unreset, so keep that old invariant
   // valid across the reset-with-held-RAS case rather than changing it.
   request_probe_address=0;request_probe_size=32;request_probe_read=1;
   request_probe_pixel=0;request_probe_cst=0;request_probe_vector=0;
   request_probe_step(1,0,1);request_probe_drain();
   // A real refresh at A0 activates FG and both BG requests (code4), so
   // reset must clear an active request while legacy RAS still stays high.
   request_probe_screen=1;
   request_probe_step(1,0,1);request_probe_step(0,1,1);request_probe_step(1,0,1);
   request_probe_screen=0;
   assert(request_probe_new_ras&&request_probe_old_ras&&request_probe_new_ba===0&&
          request_probe_new_code===4'h4&&request_probe_bits===4'b1101)
    else $fatal(1,"missing active code4 request and held-RAS reset stimulus");
   @(negedge clk);#0.01;request_probe_reset=0;request_probe_read=0;
   #0.01;
   assert(request_probe_new_ras&&request_probe_old_ras&&request_probe_bits===0&&
          request_probe_new_ba===0&&request_probe_new_code===4'hf)
    else $fatal(1,"asynchronous reset changed legacy unreset RAS or failed request clearing");
   request_probe_reset_held_ras++;
   request_probe_step(0,0,0);
   @(negedge clk);#0.01;request_probe_reset=1;
   request_probe_step(0,0,0);
  end
  request_probe_done=1;
 end
'''
    return body.replace('PROBE_DECLARATIONS', declarations).replace('PROBE_INSTANCES', '\n'.join(instances)).replace(
        'PROBE_NEW', vector('new', 'REQUEST_DIRECTED')).replace('PROBE_OLD', vector('old', 'REQUEST_DIRECTED_BEFORE'))


def full_v11_oracle(directory):
    name = 'rtl/TMS34020/TMS34020_MC.sv'
    raw = (BASE_ROOT / name).read_bytes()
    assert sha(raw) == BASE[name] and raw.count(b'module TMS34020_MC') == 1
    compiled = raw.replace(b'module TMS34020_MC', b'module TMS34020_MC_V11_REQUEST_ORACLE', 1)
    path = directory / 'TMS34020_MC_V11_REQUEST_ORACLE.sv'
    path.write_bytes(compiled)
    return path, {'path': str(path), 'sha256': sha(compiled), 'immutable_v11_sha256': sha(raw),
                  'transform': 'Complete v11 MC; module rename only; all original assertions enabled.'}


def augment(replace_once, fixture_text, mc, old_bt, current_bt):
    replace_once(' output [3:0] ADDR_CLASS\n', ' output [3:0] ADDR_CLASS,\n output [3:0] VRAM_REQUEST\n')
    replace_once('.DBUS_ADDR_CLASS(ADDR_CLASS),.DBUS_DI(MC_RETURN_WORD)',
                 '.DBUS_ADDR_CLASS(ADDR_CLASS),.VRAM_REQUEST(VRAM_REQUEST),.DBUS_DI(MC_RETURN_WORD)')
    outputs = {'DIN': ('din', 32), 'DIN_F': ('din_f', 32), 'CACHE_WR': ('cache_wr', 1),
               'WAIT': ('wait_mc', 1), 'DBUS_A': ('ba', 32), 'DBUS_DO': ('bd', 32),
               'DBUS_RAS': ('ras', 1), 'DBUS_WE': ('we', 1), 'DBUS_RD': ('rd', 1),
               'DBUS_RD_EXT': ('RD_EXT', 1), 'DBUS_BE': ('be', 4), 'DBUS_CODE': ('code', 4),
               'DBUS_ANY_BE': ('any_be', 1), 'DBUS_ANY_BE_FG': ('any_be_fg', 1),
               'DBUS_ADDR_CLASS': ('ADDR_CLASS', 4)}
    # Use the actual complete MC binding after existing stage/class adaptations.
    actual = re.findall(r'\bTMS34020_MC MC\(.*?\);', fixture_text, re.S)
    assert len(actual) == 1
    oracle = actual[0].replace('TMS34020_MC MC(', 'TMS34020_MC_V11_REQUEST_ORACLE REQUEST_BEFORE(', 1)
    for port, (signal, width) in outputs.items():
        old = '.' + port + '(' + signal + ')'
        assert oracle.count(old) == 1, port
        oracle = oracle.replace(old, '.' + port + '(request_before_' + signal + ')', 1)
    # The input slice predates this adapter's request-port insertion.
    assert '.VRAM_REQUEST' not in oracle
    declarations = '\n'.join(' wire [' + str(width - 1) + ':0] request_before_' + signal + ';'
                             for signal, width in outputs.values())
    parent_mc = lf((BASE_ROOT / 'rtl/TMS34020/TMS34020_MC.sv').read_bytes()).decode()
    states = state_names(parent_mc)
    actual_vector = '{' + ','.join(signal for signal, width in outputs.values()) + ',' + ','.join('MC.' + n for n in states) + '}'
    before_vector = '{' + ','.join('request_before_' + signal for signal, width in outputs.values()) + ',' + ','.join('REQUEST_BEFORE.' + n for n in states) + '}'
    monitor = function_from_source(mc) + '\n' + old_pin_function(old_bt) + '\n' + declarations + '\n' + oracle + '''
 integer vram_request_pre=0,vram_request_post=0,vram_request_reset=0,vram_request_en0=0;
 integer vram_request_f=0,vram_request_r=0,vram_request_idle=0,vram_before_state_checks=0;
 function automatic [3:0] requests_from_original(input [31:0] address,input [3:0] bus_code,input bit ras_active);
  logic [5:0] pins;
  pins=vram_ras_before(address,bus_code,ras_active,1'b1);
  requests_from_original={~pins[0],~pins[2],~pins[4],~pins[5]};
 endfunction
 always @(posedge CLK)begin
  if(RST_N)begin
   assert(VRAM_REQUEST===requests_from_original(ba,code,ras)&&VRAM_REQUEST===request_from_candidate_source(ba,code,ras))
    else $fatal(1,"actual MC request differs from original v11 bus selectors before SYS edge");
   vram_request_pre++;
  end
 end
 always @(negedge CLK)begin
  #0.004;
  assert(ACTUAL_STATE===BEFORE_STATE)
   else $fatal(1,"request edge changed an original complete v11 MC state/output");
  vram_before_state_checks++;
  if(RST_N)begin
   assert(VRAM_REQUEST===requests_from_original(ba,code,ras)&&VRAM_REQUEST===request_from_candidate_source(ba,code,ras))
    else $fatal(1,"actual MC request lost its same-edge bus projection after SYS edge");
   vram_request_post++;
   if(!EN)vram_request_en0++;
   if(CE_F)vram_request_f++;else if(CE_R)vram_request_r++;else vram_request_idle++;
  end else begin
   assert(VRAM_REQUEST===0&&ba===0&&code===4'hf)
    else $fatal(1,"request reset did not preserve original reset address/code");
   vram_request_reset++;
  end
 end
'''.replace('ACTUAL_STATE', actual_vector).replace('BEFORE_STATE', before_vector)
    replace_once(' assign LA={ba[31:4],code};', monitor + ' assign LA={ba[31:4],code};')
    pins = '{' + ','.join('dut.' + instance + '.RAS_N' for module, instance in INSTANCES) + '}'
    pin_monitor = '''
 integer vram_mem_pre=0,vram_mem_post=0,vram_live_page_changes=0;
 bit [1:0] vram_pages_seen=0;bit vram_previous_page=0;
 always @(posedge mem_clk)begin
  if(reset_n)begin
   assert(ACTUAL_PINS===dut.CPU.vram_ras_before(dut.CPU.ba,dut.CPU.code,dut.CPU.ras,dut.DISP_CONTROL[15]))
    else $fatal(1,"actual six VRAM RAS pins differ from original selectors at consuming MEM edge");
   vram_mem_pre++;
   vram_pages_seen[dut.DISP_CONTROL[15]]=1;
   if(dut.DISP_CONTROL[15]!=vram_previous_page)vram_live_page_changes++;
   vram_previous_page=dut.DISP_CONTROL[15];
  end
  #0.004;
  if(reset_n)begin
   assert(ACTUAL_PINS===dut.CPU.vram_ras_before(dut.CPU.ba,dut.CPU.code,dut.CPU.ras,dut.DISP_CONTROL[15]))
    else $fatal(1,"live display/bus update changed a VRAM RAS pin after MEM/SYS edge");
   vram_mem_post++;
  end
 end
'''.replace('ACTUAL_PINS', pins)
    replace_once(' bit scan_hblank=1,scan_vblank=1;', pin_monitor + directed_probe(outputs, states) + ' bit scan_hblank=1,scan_vblank=1;')
    summary = '''
  assert(dut.CPU.vram_request_pre>1000&&dut.CPU.vram_request_post>1000&&dut.CPU.vram_request_en0>100&&
         dut.CPU.vram_request_reset>0&&dut.CPU.vram_request_f>100&&dut.CPU.vram_request_r>100&&
         dut.CPU.vram_before_state_checks>1000&&vram_mem_pre>1000&&vram_mem_post>1000&&
         (&vram_pages_seen)&&vram_live_page_changes>=2)
   else $fatal(1,"missing actual MC, complete v11 state, both live pages, EN0 or MEM-pin request coverage");
  $display("VRAM_REQUEST pre=%0d post=%0d reset=%0d EN0=%0d F=%0d R=%0d idle=%0d before_state=%0d MEM_pre=%0d MEM_post=%0d page_changes=%0d",
   dut.CPU.vram_request_pre,dut.CPU.vram_request_post,dut.CPU.vram_request_reset,dut.CPU.vram_request_en0,
   dut.CPU.vram_request_f,dut.CPU.vram_request_r,dut.CPU.vram_request_idle,dut.CPU.vram_before_state_checks,
   vram_mem_pre,vram_mem_post,vram_live_page_changes);
  assert(request_probe_done&&request_probe_launches==32&&request_probe_overlaps==32&&
         request_probe_reset_held_ras==32&&request_probe_en0==160&&request_probe_transparent==5)
   else $fatal(1,"missing directed overlap, EN0, held-RAS reset or transparent prewrite request cases");
  $display("VRAM_REQUEST_PROBE edges=%0d launches=%0d overlaps=%0d reset_held_ras=%0d EN0=%0d transparent=%0d",
   request_probe_edges,request_probe_launches,request_probe_overlaps,request_probe_reset_held_ras,request_probe_en0,request_probe_transparent);
'''
    replace_once('  $finish;', summary + '  $finish;')
    force_lines = [line.strip() for line in fixture_text.splitlines() if re.search(r'\b(force|release)\b', line) and not line.lstrip().startswith('//')]
    return {'scope': 'Actual complete candidate MC drives the appended CPU/BT request pin. Compare every original v11 MC output and source-listed state on every SYS cycle, and all six original/candidate RAS pins before/after each consuming MEM edge with live display transitions. The retained request-driven wrapper copies the actual complete CPU return-stage block; full instruction CPU/board feedback remains native128 scope.',
            'old_mc_state_names': states, 'old_mc_outputs': outputs,
            'original_v11_selector_function': old_pin_function(old_bt),
            'candidate_request_function': function_from_source(mc),
            'compiled_visibility_transform': VISIBILITY_AFTER,
            'retained_fixture_force_release_statements': force_lines,
            'directed_probe': '32 true MC launches including overlapping F/R priority, 160 EN0 edges, 32 asynchronous reset-with-held-RAS cases, five transparent prewrites and normal/extended/vector/cache/refresh address/code paths; no bus/output forces.',
            'new_bus_or_request_force_statements': [], 'new_request_driver': 'actual TMS34020_MC.VRAM_REQUEST',
            'all_original_stage_assertions_retained': True, 'defined_undefined_ram_masks_changed': False}
