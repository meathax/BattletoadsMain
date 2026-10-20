import json
import os
from pathlib import Path
import subprocess

d=Path(__file__).resolve().parent/'build'/'toolchain'
d.mkdir(parents=True,exist_ok=True)
cpp=d/'probe.cpp'
cpp.write_text('#include <string>\n#include <utility>\nstd::string f(std::string&& s){return std::move(s);}\nint main(){std::string a="check"; auto b=f(std::move(a));return b!="check";}\n')
cc='D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe'
results=[]
variants=[[],['-std=c++17'],['-static-libstdc++'],['-D_GLIBCXX_USE_CXX11_ABI=0']]
for i,options in enumerate(variants):
    exe=d/f'probe_{i}.exe'
    result=subprocess.run([cc,*options,str(cpp),'-o',str(exe)],capture_output=True,
        text=True,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    (d/f'probe_{i}.log').write_text(result.stdout+result.stderr)
    run_code=None
    if result.returncode==0:
        assert exe.read_bytes()[:2]==b'MZ'
        run_code=subprocess.run([str(exe)],creationflags=subprocess.CREATE_NO_WINDOW).returncode
    item={'options':options,'compile_exit':result.returncode,'run_exit':run_code}
    results.append(item)
    print(json.dumps(item))
(d/'receipt.json').write_text(json.dumps(results,indent=2))
