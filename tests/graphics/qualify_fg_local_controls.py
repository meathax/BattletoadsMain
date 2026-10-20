"""Compare item-4 memory RTL with an immutable pre-edit git reference.

The foreground oracle uses the current two-clock cache contract on both sides.
The existing full-map workload is retained, with CPU pause during copy, directed
restart/abort/reset collisions, and cycle-by-cycle interface/copy-word comparison.
The DDR oracle keeps the original branch
priority and exercises the candidate's externally predecoded word/WE inputs.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid


ROOT = next(p for p in Path(__file__).resolve().parents if (p/'.git').exists() and (p/'rtl/fg_vram.sv').is_file())
BASELINE_REF = '8f048ee518f3062506e80d5f5a64585450d062f5'
VERILATOR = Path('D:/vibes/fpga/bin/verilator.exe')
COMPILER = Path('D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', type=Path,
        help='optional frozen snapshot, verified against the immutable baseline commit')
    parser.add_argument('--tests', nargs='+', choices=('ddr', 'fg', 'fg-ddr'), default=['ddr', 'fg', 'fg-ddr'])
    parser.add_argument('--candidate-dir', type=Path, default=ROOT, help='isolated candidate source root; default current project')
    args = parser.parse_args()
    name = 'item4-equivalence-'+uuid.uuid4().hex
    workspace = Path('R:/Verilator/BT')/name
    workspace.mkdir(parents=True)
    retained = ROOT/'build'/name
    retained.mkdir(parents=True)
    hashes = {'helper:'+Path(__file__).name: hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}

    def reference_bytes(name):
        data = subprocess.check_output(['git', 'show', f'{BASELINE_REF}:{name}'], cwd=ROOT)
        if args.baseline:
            frozen = (args.baseline/name).read_bytes()
            if frozen.replace(b'\r\n', b'\n') != data.replace(b'\r\n', b'\n'):
                raise ValueError(f'baseline snapshot differs from {BASELINE_REF}:{name}')
            return frozen
        return data

    def freeze(name, reference=False):
        data = reference_bytes(name) if reference else ((args.candidate_dir if name.startswith('rtl/') else ROOT)/name).read_bytes()
        hashes[('baseline:' if reference else '')+name] = hashlib.sha256(data).hexdigest()
        path = workspace/(('reference-' if reference else '')+Path(name).name)
        if reference and name == 'rtl/ddram.sv':
            data = data.replace(b'module ddram', b'module ddram_baseline', 1)
        if reference and name == 'rtl/fg_vram.sv':
            data = data.replace(b'module FG_VRAM', b'module FG_VRAM_REFERENCE', 1)
            data = data.replace(b'BT_FG_VIDEO_ADDR_TRACK', b'BT_FG_VIDEO_ADDR_TRACK_REFERENCE')
        path.write_bytes(data)
        return path

    ddr = freeze('rtl/ddram.sv')
    ddr_ref = freeze('rtl/ddram.sv', True)
    fg = freeze('rtl/fg_vram.sv')
    fg_ref = freeze('rtl/fg_vram.sv', True)
    ram = freeze('tests/graphics/ram_models.sv')
    clear = freeze('rtl/bt_fg_ddr_clear.sv')
    checks = []
    if 'ddr' in args.tests:
        original = freeze('tests/ddram_cache_tb.sv').read_text()
        assert 'ddram candidate(' in original
        original = original.replace('module ddram_cache_tb;', 'module item4_ddram_equivalence_tb;', 1)
        original = original.replace('ddram candidate(',
            'ddram #(.USE_PREDECODED_WORD(1), .USE_PREDECODED_WE(1)) candidate(\n'
            '    .external_read_word(4\'b0001 << address[3:2]), .external_we_any(|write_be),', 1)
        tb = workspace/'item4_ddram_equivalence_tb.sv'
        tb.write_text(original)
        checks.append(('ddr', 'item4_ddram_equivalence_tb', [ddr, ddr_ref, tb]))
    if 'fg' in args.tests:
        original = freeze('tests/foreground_read_equivalence_tb.sv').read_text()
        original = original.replace('module foreground_read_equivalence_tb;',
            'module item4_foreground_equivalence_tb;\n'
            '  logic [63:0] item4_reference_word = 0;\n'
            '  bit item4_cpu_pause = 0;\n'
            '  integer item4_collect_cycles=0, item4_restart_collisions=0, item4_abort_collisions=0, item4_reset_collects=0;', 1)
        sentinel = 'reference_CPU_SHIFT_Q<=cache_word(reference_CPU_SHIFT_A);'
        assert sentinel in original
        original = original.replace(sentinel,
            'item4_reference_word<=cache_word(reference_CPU_SHIFT_A);\n'
            '    reference_CPU_SHIFT_Q<=item4_reference_word;', 1)
        sentinel = '.SQ(reference_SQ),\n    .DRAW_WE(DRAW_WE),'
        assert sentinel in original
        original = original.replace(sentinel, sentinel+'\n'
            '    .DRAW_BANK_WE(DRAW_BANK_WE), .DRAW_RAM_BANK_WE(DRAW_RAM_BANK_WE),', 1)
        original, count = re.subn(r'always\s+#([\d.]+)\s+CPU_CLK\s*=\s*~CPU_CLK\s*;',
            r'always #\1 if (!item4_cpu_pause) CPU_CLK=~CPU_CLK;', original)
        assert count == 1, 'CPU clock fixture changed'
        sentinel = 'for(integer elapsed=0;elapsed<16000;elapsed++) begin'
        assert sentinel in original
        original = original.replace(sentinel,
            'if(cpu_copy && write_copy) begin item4_cpu_pause=1;tick(64);item4_cpu_pause=0;end\n'
            '    '+sentinel, 1)
        closing = original.index('\n  initial begin')
        original = original[:closing]+'''\n  always @(negedge CLK) begin
    #0.1;
    assert(candidate.HOLE_A_FF === reference.HOLE_A_FF)
      else $fatal(1,"item4 changed registered hole address: %h/%h",candidate.HOLE_A_FF,reference.HOLE_A_FF);
    assert(candidate.COPY_ADDR_N === reference.COPY_ADDR_N)
      else $fatal(1,"item4 changed next-copy address capture/advance/hold: %h/%h",candidate.COPY_ADDR_N,reference.COPY_ADDR_N);
    assert(candidate.COPY_WORD === reference.COPY_WORD)
      else $fatal(1,"item4 changed the copy-word capture/clear cycle: %h/%h",candidate.COPY_WORD,reference.COPY_WORD);
    if(RST_N) begin
      assert(candidate.COPY_STATE === reference.COPY_STATE && candidate.UNALIGNED_EXEC === reference.UNALIGNED_EXEC)
        else $fatal(1,"item4 changed copy-state progression");
      assert({candidate_RDY,candidate_HOLE_A,candidate_HOLE_SEL,candidate_HOLE_RD,
              candidate_HOLE_WE,candidate_HOLE_DATA,candidate_CPU_SHIFT_A,candidate_CPU_SHIFT_RD,
              candidate_CPU_SHIFT_WE,candidate_CPU_SHIFT_WA,candidate_CPU_SHIFT_DATA,candidate_Q,candidate_SQ}
          ==={reference_RDY,reference_HOLE_A,reference_HOLE_SEL,reference_HOLE_RD,
              reference_HOLE_WE,reference_HOLE_DATA,reference_CPU_SHIFT_A,reference_CPU_SHIFT_RD,
              reference_CPU_SHIFT_WE,reference_CPU_SHIFT_WA,reference_CPU_SHIFT_DATA,reference_Q,reference_SQ})
        else $fatal(1,"item4 changed a foreground interface cycle: ready=%b/%b Q=%h/%h SQ=%h/%h DDRctrl=%h/%h DDRdata=%h/%h shiftctrl=%h/%h shiftdata=%h/%h",
          candidate_RDY,reference_RDY,candidate_Q,reference_Q,candidate_SQ,reference_SQ,
          {candidate_HOLE_A,candidate_HOLE_SEL,candidate_HOLE_RD,candidate_HOLE_WE},
          {reference_HOLE_A,reference_HOLE_SEL,reference_HOLE_RD,reference_HOLE_WE},
          candidate_HOLE_DATA,reference_HOLE_DATA,
          {candidate_CPU_SHIFT_A,candidate_CPU_SHIFT_RD,candidate_CPU_SHIFT_WE,candidate_CPU_SHIFT_WA},
          {reference_CPU_SHIFT_A,reference_CPU_SHIFT_RD,reference_CPU_SHIFT_WE,reference_CPU_SHIFT_WA},
          candidate_CPU_SHIFT_DATA,reference_CPU_SHIFT_DATA);
    end
  end
  always @(posedge CLK) if(RST_N && candidate.UNALIGNED_EXEC && candidate.COPY_STATE==3) begin
    item4_collect_cycles++;
    if(!candidate.RAS_N_M && candidate.RDY_RAS_N_OLD) begin
      if(!candidate.OE_N_M && candidate.WE_N_M && candidate.TRANSFER_M) item4_restart_collisions++;
      else item4_abort_collisions++;
    end
  end
  task automatic item4_copy_control_corner(input integer lane,input integer mode);
    logic [63:0] before_abort;
    // DDR state 4, RAM state 5, or a prefetched RAM state 1 enters collect on
    // the next edge. A DDR collect abort violates the original shadow invariant
    // (its later READ_DDR_R write wins over abort), so abort RAM at collect and
    // DDR while waiting, retaining every original RTL assertion in both DUTs.
    A=(mode==1 ? 18'd0 : 18'h00100);RAS_N=1;WE_N=1;OE_N=1;SC=0;TRANSFER=1;CPU_SHIFT=1;SE_N=0;
    tick(8);OE_N=0;RAS_N=0;tick(6);RAS_N=1;OE_N=1;
    for(integer elapsed=0;elapsed<16000;elapsed++) begin
      tick(1);
      if(candidate.UNALIGNED_EXEC && candidate.COPY_POS[2:0]==3'(lane) &&
         ((mode==3 || mode==4) ? candidate.COPY_STATE==0 :
          mode==1 ? (candidate.COPY_STATE==5 || (candidate.COPY_STATE==1 && candidate.COPY_PRE)) :
          candidate.COPY_STATE==4)) break;
      if(elapsed==15999) $fatal(1,"item4 collision setup timed out lane=%0d mode=%0d",lane,mode);
    end
    before_abort=candidate.COPY_WORD;
    A=18'h20302;OE_N=(mode==1 || mode==4);WE_N=1;TRANSFER=(mode!=1 && mode!=4);RAS_N=0;tick(1);
    if(mode==3) begin
      assert(candidate.COPY_STATE!=3) else $fatal(1,"item4 clear-only setup reached collect");
      tick(1);
      assert(candidate.COPY_WORD==0 && reference.COPY_WORD==0) else $fatal(1,"copy restart failed to clear every byte");
    end else if(mode==4) begin
      assert(candidate.COPY_STATE!=3) else $fatal(1,"item4 DDR wait-abort setup reached collect");
      tick(1);
      assert(candidate.COPY_WORD==before_abort && reference.COPY_WORD==before_abort)
        else $fatal(1,"DDR wait abort changed the held copy word");
    end else begin
      assert(candidate.COPY_STATE==3 && reference.COPY_STATE==3) else $fatal(1,"item4 collision did not reach collect");
      if(mode==2) begin
        item4_reset_collects++;RST_N=0;tick(2);
        assert(candidate.COPY_WORD==0 && reference.COPY_WORD==0) else $fatal(1,"copy reset failed to clear every byte");
      end else tick(1);
    end
    RAS_N=1;OE_N=1;TRANSFER=0;CPU_SHIFT=0;tick(4);
    RST_N=0;tick(4);RST_N=1;tick(12);
    compare_transactions();transactions++;
  endtask
'''+original[closing:]
        sentinel = 'RST_N=0;tick(8);RST_N=1;tick(12);A=0;tick(8);'
        assert sentinel in original
        original = original.replace(sentinel,
            'for(integer lane=0;lane<8;lane++) begin\n'
            '      item4_copy_control_corner(lane,0);item4_copy_control_corner(lane,1);\n'
            '    end\n'
            '    item4_copy_control_corner(4,2);item4_copy_control_corner(7,2);item4_copy_control_corner(3,3);item4_copy_control_corner(3,4);\n'
            '    assert(item4_restart_collisions==8 && item4_abort_collisions==8 && item4_reset_collects==2)\n'
            '      else $fatal(1,"missing copy collision coverage: restart=%0d abort=%0d reset=%0d",item4_restart_collisions,item4_abort_collisions,item4_reset_collects);\n'
            '    $display("PASS item4 copy control corners: collect_cycles=%0d restart_collisions=%0d abort_collisions=%0d reset_collects=%0d; complete 64-bit copy-word equality every clock",item4_collect_cycles,item4_restart_collisions,item4_abort_collisions,item4_reset_collects);\n'
            '    '+sentinel, 1)
        original = original.replace('  initial begin\n', '  integer item4_rmt_ram_cycles=0,item4_rmt_ddr_cycles=0;\n  integer item4_rmt_ram_finish_restart=0,item4_rmt_ddr_finish_restart=0;\n  integer item4_rmt_mode_changes=0,item4_rmt_aborts=0,item4_rmt_resets=0;\n  integer item4_history_falls=0,item4_history_rises=0,item4_hole_changes=0;\n  logic item4_previous_hole_sel=0;\n  always @(posedge CLK) begin\n    if(RST_N) begin\n      if(reference.RMT_EXEC && (!reference.CPU_COPY_MODE || !reference.SREG_POS[8])) item4_rmt_ram_cycles++;\n      if(reference.RMT_EXEC && reference.CPU_COPY_MODE && reference.SREG_POS[8]) item4_rmt_ddr_cycles++;\n      if(reference.RAS_N_M && !reference.RDY_RAS_N_OLD) item4_history_rises++;\n      if(!reference.RAS_N_M && reference.RDY_RAS_N_OLD) begin\n        item4_history_falls++;\n        if(reference.RMT_EXEC) begin\n          if(!reference.OE_N_M && reference.TRANSFER_M && reference.CPU_SHIFT_M != reference.CPU_COPY_MODE)\n            item4_rmt_mode_changes++;\n          if(reference.OE_N_M || !reference.TRANSFER_M) item4_rmt_aborts++;\n          if((reference.MRT_EXEC || !reference.CPU_COPY_MODE || !reference.SREG_POS[8]) && reference.SREG_POS == 9\'h1f8)\n            item4_rmt_ram_finish_restart++;\n          if(reference.CPU_COPY_MODE && reference.SREG_POS[8] && reference.RMT_DDR_STATE == 2 && reference.SREG_POS == 9\'h1fe)\n            item4_rmt_ddr_finish_restart++;\n        end\n      end\n      if(reference_HOLE_SEL != item4_previous_hole_sel) item4_hole_changes++;\n      item4_previous_hole_sel <= reference_HOLE_SEL;\n    end else item4_previous_hole_sel <= 0;\n  end\n  task automatic item4_rmt_reset;\n    if(RST_N && reference.RMT_EXEC) item4_rmt_resets++;\n    RAS_N=1;WE_N=1;OE_N=1;TRANSFER=0;CPU_SHIFT=0;SC=0;\n    RST_N=0;tick(8);RST_N=1;tick(12);\n  endtask\n  task automatic item4_rmt_begin(input bit copy_mode,input logic [17:0] address);\n    A=address;RAS_N=1;WE_N=1;OE_N=1;TRANSFER=1;CPU_SHIFT=copy_mode;SE_N=0;SC=0;\n    tick(8);OE_N=0;WE_N=0;RAS_N=0;tick(6);\n    assert(reference.RMT_EXEC && candidate.RMT_EXEC) else $fatal(1,"RMT fixture did not start");\n    RAS_N=1;WE_N=1;OE_N=1;tick(6);\n  endtask\n  task automatic item4_rmt_restarts;\n    // Complete both copy modes, then vary restart phase through every RAM\n    // terminal slot and the delayed DDR terminal response window.\n    transfer(18\'h3fc00,1,0);\n    transfer(18\'h1fc00,1,1);\n    for(integer mode=0;mode<2;mode++) begin\n      for(integer phase=0;phase<(mode ? 192 : 12);phase++) begin\n        item4_rmt_reset();\n        item4_rmt_begin(1\'(mode),18\'h2a000);\n        for(integer timeout=0;timeout<16000;timeout++) begin\n          if(reference.SREG_POS >= (mode ? 9\'h1f0 : 9\'h1c0)) break;\n          tick(1);\n          if(timeout==15999) $fatal(1,"RMT fixture position timeout mode=%0d",mode);\n        end\n        tick(phase);\n        A=18\'h15400;CPU_SHIFT=1\'(~mode);TRANSFER=1;OE_N=0;WE_N=0;RAS_N=0;\n        tick(6);RAS_N=1;WE_N=1;OE_N=1;tick(24);\n        compare_transactions();\n      end\n    end\n    // An unqualified RAS edge aborts the current transfer; keep both history\n    // values and a registered DDR hole active before asserting that edge.\n    for(integer mode=0;mode<2;mode++) begin\n      item4_rmt_reset();item4_rmt_begin(1\'(mode),18\'h06000);\n      if(mode) begin\n        for(integer timeout=0;timeout<16000;timeout++) begin\n          if(reference.SREG_POS[8]) break;\n          tick(1);\n          if(timeout==15999) $fatal(1,"RMT fixture DDR entry timeout");\n        end\n      end\n      TRANSFER=0;OE_N=1;RAS_N=0;tick(6);RAS_N=1;tick(12);\n      compare_transactions();\n    end\n    item4_rmt_reset();item4_rmt_begin(1,18\'h0a000);\n    for(integer timeout=0;timeout<16000;timeout++) begin\n      if(reference.RMT_DDR_STATE==1 && reference.SREG_POS[8]) break;\n      tick(1);\n      if(timeout==15999) $fatal(1,"RMT fixture reset window timeout");\n    end\n    item4_rmt_reset();compare_transactions();\n    assert(item4_rmt_ram_cycles>0 && item4_rmt_ddr_cycles>0 &&\n           item4_rmt_ram_finish_restart>0 && item4_rmt_ddr_finish_restart>0 &&\n           item4_rmt_mode_changes>0 && item4_rmt_aborts>0 && item4_rmt_resets>0 &&\n           item4_history_falls>0 && item4_history_rises>0 && item4_hole_changes>0)\n      else $fatal(1,"RMT coverage incomplete ram=%0d ddr=%0d ram_terminal=%0d ddr_terminal=%0d mode=%0d abort=%0d reset=%0d history=%0d/%0d hole=%0d",\n        item4_rmt_ram_cycles,item4_rmt_ddr_cycles,item4_rmt_ram_finish_restart,item4_rmt_ddr_finish_restart,\n        item4_rmt_mode_changes,item4_rmt_aborts,item4_rmt_resets,item4_history_falls,item4_history_rises,item4_hole_changes);\n    $display("PASS item4 RMT/control corners: ram_cycles=%0d ddr_cycles=%0d ram_finish_restart=%0d ddr_finish_restart=%0d mode_changes=%0d aborts=%0d active_resets=%0d history_falls=%0d history_rises=%0d hole_changes=%0d; all18bit HOLE_A_FF/COPY_ADDR_N equality every clock",\n      item4_rmt_ram_cycles,item4_rmt_ddr_cycles,item4_rmt_ram_finish_restart,item4_rmt_ddr_finish_restart,\n      item4_rmt_mode_changes,item4_rmt_aborts,item4_rmt_resets,item4_history_falls,item4_history_rises,item4_hole_changes);\n  endtask\n' + '  initial begin\n', 1)
        original = original.replace('    $display("PASS foreground transaction equivalence', '    item4_rmt_restarts();\n    $display("PASS foreground transaction equivalence', 1)
        tb = workspace/'item4_foreground_equivalence_tb.sv'
        tb.write_text(original)
        checks.append(('fg', 'item4_foreground_equivalence_tb', [fg, fg_ref, ram, tb]))
    if 'fg-ddr' in args.tests:
        tb = freeze('tests/foreground_ddr_tb.sv')
        checks.append(('fg-ddr', 'foreground_ddr_tb', [fg, ddr, clear, ram, tb]))
    results = []
    env = dict(os.environ, MISTER_DIFF_HEADLESS='1', VERILATOR_PROJECT='BT',
        VERILATOR_WORKSPACE=str(workspace), VERILATOR_RAM_WORKSPACE=str(workspace))
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    for label, top, files in checks:
        target = workspace/label
        target.mkdir()
        command = [str(VERILATOR), '--binary', '--assert', '--timing', '-j', '4', '--threads', '1',
            '--x-initial', 'unique', '--x-assign', 'unique', '--top-module', top,
            '--Mdir', str(target/'obj'), '-Wno-fatal',
            '-MAKEFLAGS', f'CXX={COMPILER.as_posix()} LINK={COMPILER.as_posix()}',
            '-CFLAGS', '-DVL_TIME_CONTEXT -std=c++17', '-LDFLAGS', '-static-libstdc++ -static-libgcc',
            *map(str, files)]
        with (target/'build.log').open('w') as log:
            result = subprocess.run(command, cwd=workspace, env=env, stdout=log,
                stderr=subprocess.STDOUT, creationflags=flags)
        if result.returncode == 0:
            with (target/'run.log').open('w') as log:
                result = subprocess.run([str(target/'obj'/('V'+top+'.exe'))], cwd=workspace,
                    env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
        path = target/('run.log' if (target/'run.log').exists() else 'build.log')
        print(label+': '+path.read_text(errors='replace')[-2200:])
        results.append({'test': label, 'exit_code': result.returncode, 'command': command, 'log': str(path)})
        if result.returncode:
            break
    receipt = {'baseline': str(args.baseline) if args.baseline else 'git:'+BASELINE_REF,
        'baseline_ref': BASELINE_REF, 'candidate_dir': str(args.candidate_dir.resolve()), 'snapshot': str(workspace), 'retained': str(retained), 'sources': hashes,
        'scope': 'exact existing memory interface and complete 64-bit copy-word cycles, original DDR controller priority, all foreground banks/lanes and transfer boundaries, CPU pause, eight byte-lane DDR restart/capture and RAM abort/capture collisions, reset at DDR collect, clear-only restart and DDR wait abort, retained memory reset and actual DDR backpressure protocol; no physical timing or full-core/frame/hardware qualification',
        'results': results, 'all_passed': len(results) == len(checks) and all(x['exit_code'] == 0 for x in results)}
    (workspace/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    shutil.copyfile(workspace/'receipt.json', retained/'receipt.json')
    for label, _, _ in checks:
        for filename in ('build.log', 'run.log'):
            source = workspace/label/filename
            if source.exists():
                (retained/label).mkdir(exist_ok=True)
                shutil.copyfile(source, retained/label/filename)
    print('receipt='+str(retained/'receipt.json'))
    return 0 if receipt['all_passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
