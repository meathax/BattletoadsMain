"""Assemble only a current, fitted snapshot accepted by the all-corner gate."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

p=argparse.ArgumentParser()
p.add_argument('snapshot',type=Path)
a=p.parse_args()
root=Path(__file__).resolve().parents[2]
snapshot=a.snapshot.resolve()
retained=root/'tests/graphics/evidence/quartus'/snapshot.name
retained.mkdir(parents=True,exist_ok=True)
flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
receipt={'snapshot':str(snapshot),'assembled':False,'commands':[]}
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

try:
    gate_command=[sys.executable,'-X','utf8',str(root/'tests/graphics/verify_timing.py'),str(snapshot)]
    result=subprocess.run(gate_command,cwd=root,stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT,text=True,creationflags=flags)
    (retained/'assembly_gate.log').write_text(result.stdout)
    if result.returncode:
        print(result.stdout[-2000:])
        raise RuntimeError('RBF assembly refused: the source-bound all-corner timing gate did not pass')
    gate=json.loads((snapshot/'rbf_gate.json').read_text())
    if not gate['eligible_for_rbf']:raise RuntimeError('RBF gate is not eligible')
    from resource_audit import audit
    resources = audit(snapshot)
    if not resources['meets_all_hard_limits']:
        raise RuntimeError('RBF assembly refused: resource hard limits: ' + '; '.join(resources['failures']))
    receipt['resource_audit_sha256'] = sha(snapshot/'resource_audit.json')
    receipt['gate_sha256']=sha(snapshot/'rbf_gate.json')
    receipt['worst_slack_ns']=gate['worst_slack_ns']
    tool='D:/vibes/fpga/bin/quartus-safe.cmd'
    command=[tool,'quartus_asm','Arcade-Battletoads']
    receipt['commands'].append(command)
    with (retained/'assembly.log').open('w') as log:
        result=subprocess.run(command,cwd=snapshot,stdout=log,stderr=subprocess.STDOUT,
                              creationflags=flags)
    if result.returncode:raise RuntimeError('quartus_asm failed; see '+str(retained/'assembly.log'))
    sofs=list((snapshot/'output_files').glob('*.sof'))
    if len(sofs)!=1:raise RuntimeError('expected one assembled SOF')
    sof=sofs[0];rbf=sof.with_suffix('.rbf')
    if not rbf.exists():
        command=[tool,'quartus_cpf','-c',str(sof),str(rbf)]
        receipt['commands'].append(command)
        with (retained/'conversion.log').open('w') as log:
            result=subprocess.run(command,cwd=snapshot,stdout=log,stderr=subprocess.STDOUT,
                                  creationflags=flags)
        if result.returncode:raise RuntimeError('SOF to RBF conversion failed')
    if not rbf.exists() or not rbf.stat().st_size:raise RuntimeError('RBF missing or empty')
    destination=root/'releases'/('Battletoads_'+datetime.now().strftime('%Y%m%d')+'_'+snapshot.name[-8:]+'.rbf')
    shutil.copyfile(rbf,destination)
    receipt.update({'assembled':True,'rbf':str(destination),'rbf_sha256':sha(destination),
                    'rbf_bytes':destination.stat().st_size,'sof_sha256':sha(sof),'exit_code':0})
    print('rbf='+str(destination))
    print(json.dumps({'worst_slack_ns':gate['worst_slack_ns'],'rbf_bytes':destination.stat().st_size},indent=2))
except (OSError,RuntimeError,json.JSONDecodeError) as error:
    receipt.update({'exit_code':1,'error':str(error)})
    print(str(error))
finally:
    (retained/'rbf_receipt.json').write_text(json.dumps(receipt,indent=2))
sys.exit(receipt['exit_code'])
