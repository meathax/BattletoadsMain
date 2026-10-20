"""Expose existing MC state and software-only assignment probes in private copies."""
import hashlib
import re
from pathlib import Path


def validate_runtime_edge(root):
    baseline=root/'build/ddr_parallel_sources_v9_v2/native_runtime_scope_v1/original_native_run.py'
    current=root/'tests/graphics/native_run.py'
    text=current.read_text();original=baseline.read_text()
    before="mc.write_text(mc_text.replace(local_latch,'').replace(module_latch,\n              module_latch+'\\n\\tbit          READ_LATCH;'))"
    after="mc_visible=mc_text.replace(local_latch,'').replace(module_latch,\n              module_latch+'\\n\\tbit          READ_LATCH;')\nmc_visible,mc_launch_scope=expose_launch_scope(mc_visible)\nmc.write_text(mc_visible)\n(target/'mc_launch_scope.json').write_text(json.dumps(mc_launch_scope,indent=2))\nsources['tests/graphics/bt_native_mc_scope.py']=hashlib.sha256((root/'tests/graphics/bt_native_mc_scope.py').read_bytes()).hexdigest()"
    edits=[('', 'from bt_native_mc_scope import expose_launch_scope\n'),(before,after),
           ('', "    shutil.copyfile(target/'mc_launch_scope.json',retained/'mc_launch_scope.json')\n")]
    reverse=text
    for old,new in reversed(edits):
        assert reverse.count(new)==1
        reverse=reverse.replace(new,old,1)
    assert reverse==original,'Native runner change exceeds the private MC scope adapter'
    return {'schema':'bt-native-runtime-scope-edge-v1','status':'PASS',
        'baseline_path':str(baseline),'baseline_sha256':hashlib.sha256(baseline.read_bytes()).hexdigest(),
        'candidate_path':str(current),'candidate_sha256':hashlib.sha256(current.read_bytes()).hexdigest(),
        'helper_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'exact_reversal_verified':True,'edits':edits}


def expose_launch_scope(text):
    if '\tbit SCRREF_PEND, READ_LATCH, WRITE_LATCH;' in text:
        return _expose_merged_scope(text)
    original=text
    local='\t\tbit         SCRREF_PEND;'
    module='\tbit          FETCH_LATCH;'
    assert text.count(local)==1 and text.count(module)==1
    declarations=module+'\n\tbit          SCRREF_PEND;\n'+''.join(
        '\tbit bt_probe_'+name+'=0;\n' for name in ('ext','fs','ba','buf'))
    text=text.replace(local,'').replace(module,declarations,1)
    last_local='\t\tbit [ 1: 0] FETCH_LSB;'
    assert text.count(last_local)==1
    clears='\n'+''.join('\t\tbt_probe_'+name+' <= 0;\n' for name in ('ext','fs','ba','buf'))
    text=text.replace(last_local,last_local+clears,1)
    names={'MC_EXT_WORD':'ext','DOUT_FS':'fs','DOUT_BA_OLD':'ba','DOUT_BUF':'buf'}
    counts=dict.fromkeys(names,0)
    pattern=r'(?m)^([ \t]*)(MC_EXT_WORD|DOUT_FS|DOUT_BA_OLD|DOUT_BUF)(\s*<=.*?;)'
    def probe(match):
        counts[match[2]]+=1
        return match[0]+'\n'+match[1]+'bt_probe_'+names[match[2]]+' <= 1;'
    text=re.sub(pattern,probe,text)
    assert counts=={'MC_EXT_WORD':4,'DOUT_FS':2,'DOUT_BA_OLD':1,'DOUT_BUF':2}
    # Every actual assignment, including identical values and reset writes,
    # produces an NBA probe. Strip the probes/declarations to recover all
    # original functional code exactly.
    reverse=re.sub(r'(?m)^([ \t]*)(MC_EXT_WORD|DOUT_FS|DOUT_BA_OLD|DOUT_BUF)(\s*<=.*?;)\n\1bt_probe_\w+ <= 1;',
                   lambda match:match[1]+match[2]+match[3],text)
    reverse=reverse.replace(last_local+clears,last_local,1).replace(declarations,module,1)
    reverse=reverse.replace('\talways @(posedge CLK or negedge RST_N) begin\t\t\n',
                            '\talways @(posedge CLK or negedge RST_N) begin\t\t\n'+local,1)
    # Removal leaves the original declaration's newline in its old position.
    reverse=reverse.replace(local+'\n\n\t\tbit         READ_LATCH;',local+'\n\t\tbit         READ_LATCH;',1)
    # Native_run already lifted READ_LATCH, so recover its former empty line.
    if reverse!=original:
        reverse=reverse.replace(local+'\n\n\n\t\tbit         WRITE_LATCH;',local+'\n\n\t\tbit         WRITE_LATCH;',1)
    assert reverse==original,'MC probe transformation changed functional code'
    return text,{'schema':'bt-native-mc-launch-scope-v1','status':'PASS',
        'input_sha256_lf':hashlib.sha256(original.encode()).hexdigest(),
        'output_sha256_lf':hashlib.sha256(text.encode()).hexdigest(),
        'assignment_sites':counts,'functional_body_reversal_verified':True,
        'scope':'Only private simulation declaration exposure and NBA assignment probes; production MC untouched.'}


def _expose_merged_scope(text):
    """Merged MC layout: SCRREF_PEND/READ_LATCH/FETCH_LSB already live at module
    scope. Add only the software probes, then prove exact functional reversal."""
    original=text
    module='\tbit          FETCH_LATCH;'
    assert text.count(module)==1
    declarations=module+'\n'+''.join('\tbit bt_probe_'+name+'=0;\n' for name in ('ext','fs','ba','buf'))
    text=text.replace(module,declarations,1)
    head='\talways @(posedge CLK or negedge RST_N) begin\t\t\n'
    assert text.count(head)==1
    clears=''.join('\t\tbt_probe_'+name+' <= 0;\n' for name in ('ext','fs','ba','buf'))
    text=text.replace(head,head+clears,1)
    names={'MC_EXT_WORD':'ext','DOUT_FS':'fs','DOUT_BA_OLD':'ba','DOUT_BUF':'buf'}
    counts=dict.fromkeys(names,0)
    pattern=r'(?m)^([ \t]*)(MC_EXT_WORD|DOUT_FS|DOUT_BA_OLD|DOUT_BUF)(\s*<=.*?;)'
    def probe(match):
        counts[match[2]]+=1
        return match[0]+'\n'+match[1]+'bt_probe_'+names[match[2]]+' <= 1;'
    text=re.sub(pattern,probe,text)
    assert counts=={'MC_EXT_WORD':4,'DOUT_FS':2,'DOUT_BA_OLD':1,'DOUT_BUF':2},counts
    reverse=re.sub(r'(?m)^([ \t]*)(MC_EXT_WORD|DOUT_FS|DOUT_BA_OLD|DOUT_BUF)(\s*<=.*?;)\n\1bt_probe_\w+ <= 1;',
                   lambda match:match[1]+match[2]+match[3],text)
    reverse=reverse.replace(head+clears,head,1).replace(declarations,module,1)
    assert reverse==original,'MC probe transformation changed functional code'
    return text,{'schema':'bt-native-mc-launch-scope-v1','status':'PASS','layout':'merged-module-scope',
        'input_sha256_lf':hashlib.sha256(original.encode()).hexdigest(),
        'output_sha256_lf':hashlib.sha256(text.encode()).hexdigest(),
        'assignment_sites':counts,'functional_body_reversal_verified':True,
        'scope':'Only private simulation probes; production MC untouched.'}
