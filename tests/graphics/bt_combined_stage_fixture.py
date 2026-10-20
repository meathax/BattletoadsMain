"""Explicit class/parallel-DDR composition and additive complete-controller observers."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

from prepare_bt_address_class import BASE as CLASS_BASE, address_class_transform
from prepare_bt_parallel_ddr_write import BASE as DDR_BASE, CAPTURE, PARALLEL
from prepare_bt_en0_snapshot_candidate import BASE_MC_GIT_COMMIT, canonical_lf

PARALLEL_SHA = {
    'rtl/ddram.sv': 'ea8b8738afeca05c2dc214cb9a30c946ddb9d3010900ada185d0e180f6987dc9',
    'rtl/BT.sv': '575060dae2abf4deb5713589c172d82331d63dab19ef2df4c6f125e09a8283a9',
    'Arcade-Battletoads.sv': 'ba4977deb04e399143800f81a7354280e2fe4180775c53bc816825844e43e5cf',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def parallel_transform(name, data):
    """Only the independently reviewed parallel-source changes, reversible."""
    text = canonical_lf(data).decode()
    changes = {
        'rtl/BT.sv': [
            ('`endif\n);\n\n\tbit [31: 0] LA;', '`endif\n\t, output [3:0][31:0] EDATA_CANDIDATES\n\t, output [3:0] EDATA_SELECT\n);\n\n\tbit [31: 0] LA;'),
            ("\tassign EDATA = SPR_DDR_REQ ? {8'b0,SPR_DRAW_DATA,8'b0,SPR_DRAW_DATA} :", PARALLEL + "\tassign EDATA = SPR_DDR_REQ ? {8'b0,SPR_DRAW_DATA,8'b0,SPR_DRAW_DATA} :"),
        ],
        'rtl/ddram.sv': [
            ('parameter USE_PREDECODED_MISS=0)', 'parameter USE_PREDECODED_MISS=0, parameter USE_PARALLEL_DIN=0)'),
            ('\toutput reg [31: 0] dbg_din\n);', '\toutput reg [31: 0] dbg_din,\n\tinput [3:0][31:0] parallel_din,\n\tinput [3:0] parallel_din_sel\n);'),
            ('\treg  [ 31:  0] write_data;', '\twire [31:0] write_data;'),
            ('\t(* preserve, dont_merge *) reg [ 31:  0] write_data_o;', '\twire [31:0] write_data_o;'),
            ('\t\t\twrite_addr <= addr;\n\t\t\twrite_data <= din;\n\t\t\twrite_data_o <= din;\n', '\t\t\twrite_addr <= addr;\n'),
            ('\talways @(posedge clk) begin\n\t\tbit old_io_rd, old_io_we;', CAPTURE + '\talways @(posedge clk) begin\n\t\tbit old_io_rd, old_io_we;'),
        ],
        'Arcade-Battletoads.sv': [
            ('\t\t.EDATA(BT_EDATA),', '\t\t.EDATA(BT_EDATA),\n\t\t.EDATA_CANDIDATES(bt_edata_candidates), .EDATA_SELECT(bt_edata_select),'),
            ('\twire [31: 0] ddr_do;', '\twire [3:0][31:0] bt_edata_candidates;\n\twire [3:0] bt_edata_select;\n\twire [31: 0] ddr_do;'),
            ('.USE_PREDECODED_MISS(1)) ddram', '.USE_PREDECODED_MISS(1), .USE_PARALLEL_DIN(1)) ddram'),
            ('\t\t.din (BT_EDATA),', '\t\t.din (BT_EDATA),\n\t\t.parallel_din(bt_edata_candidates), .parallel_din_sel(bt_edata_select),'),
        ],
    }
    assert name in changes
    before = text
    for old, new in changes[name]:
        assert text.count(old) == 1, 'Parallel composition anchor changed: ' + name
        text = text.replace(old, new, 1)
    restored = text
    for old, new in reversed(changes[name]):
        assert restored.count(new) == 1
        restored = restored.replace(new, old, 1)
    assert restored == before, 'Parallel composition is not reversible'
    return text.encode()


def verify_combined_edge(root, source_root, candidate_read):
    baseline = root / 'build/timing_closure_20261011/integrated_v9_private'
    parent = root / 'build/ddr_parallel_sources_v9_v2/candidate'
    expected, provenance = {}, {}
    for name, digest in DDR_BASE.items():
        before = (baseline / name).read_bytes()
        assert sha(before) == digest, 'Exact complete v9 parent changed: ' + name
        parallel_parent = (parent / name).read_bytes()
        assert sha(parallel_parent) == PARALLEL_SHA[name]
        assert canonical_lf(parallel_parent) == parallel_transform(name, before)
        if name == 'rtl/BT.sv':
            intermediate = address_class_transform(name, before)
            expected[name] = parallel_transform(name, intermediate)
        else:
            expected[name] = parallel_transform(name, before)
        actual = candidate_read(name)
        assert canonical_lf(actual) == expected[name], 'Combined source has an undeclared change: ' + name
        if name != 'rtl/BT.sv':
            assert actual == parallel_parent, 'Non-BT parent bytes must remain exact'
        provenance[name] = {'before_sha256': sha(before), 'after_sha256': sha(actual),
                            'after_canonical_lf_sha256': sha(expected[name]),
                            'parallel_parent_sha256': sha(parallel_parent),
                            'explicit_transform_matches': True}
    composition_path = source_root.parent / (source_root.name + '-composition.json')
    composition = json.loads(composition_path.read_text())
    assert composition['schema'] == 'bt-address-ddr-composition-v1'
    assert set(composition['files']) == set(DDR_BASE) | set(CLASS_BASE)
    for name, record in composition['files'].items():
        actual = candidate_read(name)
        assert record['sha256'] == sha(actual)
        assert record['baseline_sha256'] == (DDR_BASE.get(name) or CLASS_BASE[name])
        for item in record['parents']:
            path = Path(item['path']).resolve()
            assert path.is_relative_to(root / 'build')
            raw = path.read_bytes()
            assert sha(raw) == item['sha256'] and sha(canonical_lf(raw)) == item['lf_sha256']
    provenance['composition'] = {'path': str(composition_path), 'sha256': sha(composition_path.read_bytes())}
    provenance['edge_type'] = 'bt-class-parallel-ddr-v1'
    for name in ('bt_combined_stage_fixture.py', 'prepare_bt_parallel_ddr_write.py'):
        path = Path(__file__).with_name(name)
        provenance[name] = {'path': str(path), 'sha256': sha(path.read_bytes())}
    return expected, provenance


def full_ddr_oracle(root, directory):
    result = subprocess.run(['D:/vibes/fpga/bin/git.EXE', '-C', str(root), 'show',
                             BASE_MC_GIT_COMMIT + ':rtl/ddram.sv'], capture_output=True)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    raw = result.stdout
    parent = (root / 'build/timing_closure_20261011/integrated_v9_private/rtl/ddram.sv').read_bytes()
    assert sha(parent) == DDR_BASE['rtl/ddram.sv'] and canonical_lf(raw) == canonical_lf(parent)
    assert raw.count(b'module ddram') == 1
    path = directory / 'ddram_full_immutable_oracle.sv'
    compiled = raw.replace(b'module ddram', b'module ddram_full_immutable_oracle', 1)
    path.write_bytes(compiled)
    return {'path': path.relative_to(root).as_posix(), 'sha256': sha(compiled),
            'git_commit': BASE_MC_GIT_COMMIT, 'git_file': 'rtl/ddram.sv', 'git_raw_sha256': sha(raw),
            'transform': 'Full immutable controller; module rename only; every assertion stays enabled.'}


def augment(replace_once, top):
    assert '.sclk(CE_R)' in top and '.USE_PARALLEL_DIN(1)' in top
    bank_map = re.search(r'\t// BEGIN DDR_BANK_MAP.*?\t// END DDR_BANK_MAP', top, re.S).group()
    def rename_bus(text):
        names = {'BT_EADDR': 'eaddr', 'BT_ERAM': 'eram', 'BT_EFG': 'efg',
                 'BT_ENVRAM': 'envram', 'BT_ESPR': 'espr', 'BT_EROM': 'erom'}
        return re.sub(r'\b(?:' + '|'.join(names) + r')\b', lambda m: names[m.group()], text)
    bank_map = rename_bus(bank_map)
    for name in ('ddr_wren', 'ddr_rden'):
        declaration = re.search(r'\twire ' + name + r' = .*?;', top).group()
        bank_map += '\n' + rename_bus(declaration)
    replace_once(' wire [31:0] edata;', ' wire [3:0][31:0] actual_parallel_data;\n wire [3:0] actual_parallel_owner;\n wire [31:0] edata;')
    replace_once('.EDATA(edata),', '.EDATA(edata),.EDATA_CANDIDATES(actual_parallel_data),.EDATA_SELECT(actual_parallel_owner),')
    controller = '''
 // These complete controllers observe actual compiled BT source/owner outputs.
 // Preserve the original consuming-stage response model and every stimulus;
 // native128 separately qualifies the complete board DDR feedback loop.
 BOARD_BANK_MAP
 wire parallel_memory_busy=(ticks%13)==5||(ticks%13)==6;
 reg [63:0] parallel_memory_dout=0;
 reg parallel_memory_ready=0;
 integer parallel_memory_remaining=0,parallel_memory_beat=0;
 wire [31:0] parallel_q,parallel_old_q;
 wire parallel_busy,parallel_old_busy,parallel_rd,parallel_old_rd,parallel_we,parallel_old_we;
 wire [63:0] parallel_din,parallel_old_din;
 wire [28:0] parallel_addr,parallel_old_addr;
 wire [7:0] parallel_be,parallel_old_be,parallel_len,parallel_old_len;
 ddram #(.USE_PARALLEL_DIN(1)) parallel_controller(CONTROLLER_INPUTS,
  .parallel_din(actual_parallel_data),.parallel_din_sel(actual_parallel_owner),
  .dout(parallel_q),.busy(parallel_busy),.DDRAM_RD(parallel_rd),.DDRAM_WE(parallel_we),
  .DDRAM_ADDR(parallel_addr),.DDRAM_DIN(parallel_din),.DDRAM_BE(parallel_be),.DDRAM_BURSTCNT(parallel_len));
 ddram_full_immutable_oracle immutable_controller(CONTROLLER_INPUTS,
  .dout(parallel_old_q),.busy(parallel_old_busy),.DDRAM_RD(parallel_old_rd),.DDRAM_WE(parallel_old_we),
  .DDRAM_ADDR(parallel_old_addr),.DDRAM_DIN(parallel_old_din),.DDRAM_BE(parallel_old_be),.DDRAM_BURSTCNT(parallel_old_len));
 always @(posedge mem_clk)begin
  parallel_memory_ready<=0;
  if(!reset_n)begin parallel_memory_remaining<=0;parallel_memory_beat<=0;end
  else if(parallel_memory_remaining>0)begin
   parallel_memory_ready<=1;
   parallel_memory_dout<=64'h7e1f293b5a3c4d6f^{2{parallel_addr,3'(parallel_memory_beat)}};
   parallel_memory_beat<=parallel_memory_beat+1;
   parallel_memory_remaining<=parallel_memory_remaining-1;
  end else if(parallel_rd&&!parallel_memory_busy)begin
   parallel_memory_remaining<=integer'(parallel_len);parallel_memory_beat<=0;
  end
 end
 bit parallel_word_valid=0;
 reg [31:0] parallel_expected_word=0;
 reg [3:0] parallel_expected_owner=0;
 reg [3:0][31:0] parallel_expected_raw='0;
 integer parallel_acceptance=0,parallel_hold_checks=0,parallel_reset_edges=0;
 integer parallel_pre_views=0,parallel_post_views=0,parallel_ddr_beats=0,parallel_cache_checks=0;
 integer parallel_owners[4]='{default:0};
 always @(posedge mem_clk)begin
  if(!reset_n)parallel_reset_edges++;
  else begin
   assert(parallel_controller.write_prepend===immutable_controller.write_prepend)
    else $fatal(1,"actual BT parallel DDR acceptance enable differs from immutable controller");
   if(parallel_word_valid)begin
    assert(parallel_controller.write_data===immutable_controller.write_data&&parallel_controller.write_data_o===immutable_controller.write_data_o)
     else $fatal(1,"actual BT parallel DDR preedge cache/beat view differs");
    parallel_pre_views++;
   end
   if(parallel_controller.write_prepend&&raw_phase_r)begin
    assert($onehot(actual_parallel_owner)&&edata===
      ((actual_parallel_data[0]&{32{actual_parallel_owner[0]}})|
       (actual_parallel_data[1]&{32{actual_parallel_owner[1]}})|
       (actual_parallel_data[2]&{32{actual_parallel_owner[2]}})|
       (actual_parallel_data[3]&{32{actual_parallel_owner[3]}})))
     else $fatal(1,"actual compiled BT raw owner does not reproduce its accepted legacy EDATA");
    parallel_expected_word<=edata;parallel_expected_owner<=actual_parallel_owner;parallel_expected_raw<=actual_parallel_data;
    parallel_word_valid<=1;parallel_acceptance++;
    for(integer owner=0;owner<4;owner++)if(actual_parallel_owner[owner])parallel_owners[owner]++;
   end else if(parallel_word_valid)parallel_hold_checks++;
  end
 end
 always @(negedge mem_clk)begin
  #0.002;
  if(reset_n)begin
   assert({parallel_q,parallel_busy,parallel_rd,parallel_we}===
          {parallel_old_q,parallel_old_busy,parallel_old_rd,parallel_old_we})
    else $fatal(1,"actual BT DDR current/immutable controller outputs differ");
   if(parallel_rd)assert({parallel_addr,parallel_len}==={parallel_old_addr,parallel_old_len})
    else $fatal(1,"actual BT DDR read command differs");
   if(parallel_we)begin
    assert({parallel_addr,parallel_din,parallel_be,parallel_len}===
           {parallel_old_addr,parallel_old_din,parallel_old_be,parallel_old_len})
     else $fatal(1,"actual BT DDR accepted write beat differs from immutable controller");
    parallel_ddr_beats++;
   end
   for(integer bank=0;bank<4;bank++)for(integer word_index=0;word_index<4;word_index++)begin
    assert(parallel_controller.rbuf[bank][word_index]===immutable_controller.rbuf[bank][word_index])
     else $fatal(1,"actual BT DDR physical cache-word view differs");
    parallel_cache_checks++;
   end
   if(parallel_word_valid)begin
    assert(parallel_controller.write_data===parallel_expected_word&&parallel_controller.write_data_o===parallel_expected_word&&
           parallel_controller.write_data===immutable_controller.write_data&&parallel_controller.write_data_o===immutable_controller.write_data_o&&
           parallel_controller.write_data_parallel===parallel_expected_raw&&parallel_controller.write_data_o_parallel===parallel_expected_raw&&
           parallel_controller.parallel_write_capture.cache_owner===parallel_expected_owner&&parallel_controller.parallel_write_capture.beat_owner===parallel_expected_owner)
     else $fatal(1,"actual BT DDR post-capture owner/raw/cache/beat words differ");
    parallel_post_views++;
   end
  end
 end
'''
    common = ".clk(mem_clk),.rst(!reset_n),.sclk(raw_phase_r),.addr(ddr_addr[27:1]),.din(edata),.we(ewe&{4{ddr_wren}}),.rd(erd&&ddr_rden),.cache(ddr_addr[24:23]),.io_addr(27'b0),.io_din(32'b0),.io_rd(1'b0),.io_we(4'b0),.baddr(27'b0),.bin(64'b0),.brd(1'b0),.bwr(1'b0),.DDRAM_BUSY(parallel_memory_busy),.DDRAM_DOUT(parallel_memory_dout),.DDRAM_DOUT_READY(parallel_memory_ready)"
    controller = controller.replace('BOARD_BANK_MAP', bank_map).replace('CONTROLLER_INPUTS', common)
    replace_once(' task automatic wait_f;', controller + ' task automatic wait_f;')
    # Keep the old page-1 sequence intact. Exercise its identical page-0
    # transaction through real MC commands so the physical FG1 owner is captured.
    # The display control is restored before the original screen/field stimuli.
    original_screen_comment = '  // Real screen-refresh codes exercise both serial ports and partner FG copy.'
    extra_owner_stimulus = '''  // Additive physical FG1 serial-copy owner, without forcing any DUT signal.
  access(1,32'h20000180,0,16,0);
  req_pixel=1;req_cst=1;
  access(0,32'ha0000080,0,32,0);
  access(0,32'ha0001000,0,32,0);
  access(1,32'ha0000080,32'hfedc_9876,32,0);
  req_pixel=0;req_cst=0;
  access(1,32'h20000180,32'h8000,16,0);
'''
    extra_cpu_stimulus = '''  // Additive external RAM writes qualify CPU ownership on both phase profiles.
  access(1,32'h00000800,32'hcafe_beef,32,0);
  access(1,32'h00000803,32'h1357_9bdf,13,0);
'''
    replace_once(original_screen_comment, extra_owner_stimulus + extra_cpu_stimulus + original_screen_comment)
    summary = '''
  assert(parallel_acceptance>0&&parallel_pre_views>100&&parallel_post_views>100&&parallel_hold_checks>100&&parallel_reset_edges>0&&parallel_ddr_beats>0&&parallel_cache_checks>1000)
   else $fatal(1,"missing activated actual-BT full-DDR accepted/held/reset/cache/beat coverage");
  foreach(parallel_owners[owner])assert(parallel_owners[owner]>0)
   else $fatal(1,"actual BT DDR owner not captured: %0d",owner);
  $display("COMBINED_DDR acceptance=%0d holds=%0d reset_edges=%0d pre_views=%0d post_views=%0d ddr_beats=%0d cache_words=%0d sprite=%0d foreground0=%0d foreground1=%0d cpu=%0d",parallel_acceptance,parallel_hold_checks,parallel_reset_edges,parallel_pre_views,parallel_post_views,parallel_ddr_beats,parallel_cache_checks,parallel_owners[0],parallel_owners[1],parallel_owners[2],parallel_owners[3]);
'''
    replace_once('  $finish;', summary + '  $finish;')
    return {'scope': 'Actual complete BT raw-source/onehot-owner outputs drive activated complete parallel DDR and immutable full-controller observers. Compare accepted words, held pre/post cache/beat views,16 cache words and native DDR commands/data. Preserve existing modeled consuming-stage responses; complete board feedback, launch-age timing and physical Intel qualification remain separate.',
            'parameter': 'USE_PARALLEL_DIN=1', 'memory_phase': 'raw_phase_r (actual board CE_R, separate from admitted CPU phases)',
            'actual_board_bank_map': bank_map, 'controller_binding': common,
            'candidate_instance': 'parallel_controller', 'oracle_instance': 'immutable_controller',
            'additive_fg1_stimulus': extra_owner_stimulus,
            'additive_cpu_stimulus': extra_cpu_stimulus}
