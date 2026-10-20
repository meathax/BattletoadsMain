"""Run focused platform simulations and check source/MRA integration; no Quartus."""
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
import re
import os
import sys
import hashlib
import json
import uuid

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/platform_features'
OUT.mkdir(parents=True, exist_ok=True)

def simulation_command(arguments):
    # Native Icarus crashes on this known-good fixture on this host. Linux
    # tools/ELF execute only through their matching Ubuntu WSL environment.
    return ['wsl.exe','-d','Ubuntu','--cd',str(ROOT),'--exec',*arguments] if os.name=='nt' else arguments

def main():
    wrapper=(ROOT/'Arcade-Battletoads.sv').read_text()
    qip_text=(ROOT/'files.qip').read_text()
    mra=ET.parse(ROOT/'releases/Battletoads.mra').getroot()
    switches=mra.find('switches')
    # SW1 per MAME btoads: 0 = On; bit 1 low is Stereo On. Shown via CONF_STR DIP;
    assert switches.get('page_id') is None and '"DIP;",' in wrapper
    assert switches.get('default')=='f0'
    names=['Demo Sounds','Stereo','Common Coin Mech','Three Players',
           'Free Play','Blood Free Mode','Credit Retention','Unknown SW1:8']
    dips=switches.findall('dip')
    assert [d.get('name') for d in dips]==names
    assert [int(d.get('bits')) for d in dips]==list(range(8))
    assert all(d.get('ids')=='On,Off' for d in dips)
    assert all(len(d.get('name'))+len('Off')+2<=28 for d in dips)
    assert mra.find('nvram').attrib=={'index':'4','size':'8192'}
    controls='Attack,Jump,Coin,Start,Service Menu,Pause'
    assert mra.find('buttons').get('names')==controls
    assert f'J1,{controls};' in wrapper
    assert '.SERVICE(~(status[32] | joy0[8] | joy1[8] | joy2[8]))' in wrapper
    assert 'status[42:40]' in wrapper and 'HV-Integer;' in wrapper
    assert 'HDMI Rotation' not in wrapper and 'screen_rotate_two' not in wrapper
    assert 'bt_video_mixer #(.LINE_LENGTH(512+8), .HALF_DEPTH(0), .GAMMA(1))' in wrapper
    qip=(ROOT/'files.qip').read_text()
    assert 'rtl/bt_video_mixer.sv' in qip and 'rtl/bt_scandoubler.sv' in qip
    assert '.cpu_addr(BT_NVRAM_ADDR)' in wrapper
    assert re.search(r'sdram\s*#\(\.CONTROLLED_REFRESH\(1\)\)\s+sdram\s*\(.*?\.clk\(clk_sys\)', wrapper, re.S)
    assert '.ioctl_upload_index(8\'d4)' in wrapper
    compact=re.sub(r'\s+','',wrapper)
    assert '.CE_F(CE_F_CPU)' in wrapper and '.CE_R(CE_R_CPU)' in wrapper
    # The OSD pauses only when the OSD Pause option (status[43], default Off) is On.
    assert 'pause_cpu<=user_pause|nvram_pause|osd_pause;' in compact and 'osd_pause<=OSD_STATUS&status[43];' in compact and 'OSD_STATUS|' not in compact
    assert '.osd_open(OSD_STATUS&~status[44])' in compact
    assert "status_menumask={11'd0,!status[54],!crt_available,2'd0,direct_video}" in compact
    assert 'bt_crt_adjust' in wrapper and 'rtl/crt_adjust.sv' in qip_text and 'rtl/bt_crt_adjust.sv' in qip_text
    assert 'bt_pause_bridge' in qip
    assert re.search(r'bt_pause_bridge\s*#\(\.DISPLAY_SERVICE_PAUSE\(1\)\)\s+cpu_pause_bridge\s*\(.*?\.pause_req\(pause_cpu\).*?\.raw_ce_f\(CE_F\).*?\.raw_ce_r\(CE_R\).*?\.ce_f\(CE_F_CPU\).*?\.ce_r\(CE_R_CPU\).*?\.halted\(cpu_pause_halted\).*?\.pause_ready\(cpu_pause_ready\)',wrapper,re.S)
    assert '.cpu_we(BT_NVRAM_WE&&CE_R_CPU)' in compact
    assert '.cpu_halted(cpu_pause_halted)' in compact
    qsf=(ROOT/'Arcade-Battletoads.qsf').read_text()
    assert '"MISTER_FB=1"' in qsf
    assert 'MISTER_DISABLE_YC' in qsf and 'MISTER_DISABLE_ALSA' in qsf
    pll=(ROOT/'rtl/pll/pll_0002.v').read_text()
    assert '80.000000 MHz' in pll and '160.000000 MHz' in pll
    print('PASS controls, service polarity, all eight DIP mappings, OSD labels, scale/rotation, NVRAM host wiring, Y/C and ALSA disabled')
    retained=OUT/('platform-'+uuid.uuid4().hex)
    retained.mkdir()
    relative=retained.relative_to(ROOT).as_posix()
    sources=['tests/platform_features_tb.sv','rtl/bt_clock_enables.sv','rtl/bt_pause_bridge.sv','rtl/bt_nvram.sv']
    inputs=sources+['Arcade-Battletoads.sv','files.qip','Arcade-Battletoads.qsf','rtl/pll/pll_0002.v','releases/Battletoads.mra','src/btc0/btc0.asm','tests/verify_platform_features.py','tests/verify_bt_video_ddr_memory.py']
    original_hashes={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in inputs}
    commands=[simulation_command(['verilator','--binary','--assert','--timing','--top-module','platform_features_tb','-Wno-fatal','-j','2','--Mdir',relative+'/obj',*sources]),
              simulation_command(['./'+relative+'/obj/Vplatform_features_tb'])]
    logs=[]
    for number,command in enumerate(commands):
        result=subprocess.run(command,cwd=ROOT,text=True,encoding='utf-8',errors='replace',capture_output=True,timeout=300)
        (retained/f'phase_{number}.log').write_text(result.stdout+result.stderr,encoding='utf-8')
        logs.append({'command':command,'exit_code':result.returncode})
        if result.returncode:
            raise RuntimeError(f'Platform simulation failed ({result.returncode}); {retained}: '+(result.stdout+result.stderr)[-3000:])
    report=(retained/'phase_1.log').read_text(encoding='utf-8')
    assert 'PASS steady 10 MHz' in report and 'PASS all 8192 NVRAM bytes:' in report
    phase=re.search(r'PASS platform pause/NVRAM: (.+)',report)
    assert phase,'Missing actual board pause/NVRAM proof'
    print(report.strip())
    bridge=retained/'memory_bridge'
    command=simulation_command(['python3','tests/verify_bt_video_ddr_memory.py','--simulator','verilator','--output',bridge.relative_to(ROOT).as_posix()])
    subprocess.run(command,cwd=ROOT,check=True)
    # The program loads HTOTAL=639 and VTOTAL=256; raster totals are inclusive.
    asm=(ROOT/'src/btc0/btc0.asm').read_text()
    assert 'HTOTAL = 0x027F' in asm and 'VTOTAL = 0x0100' in asm
    print(f'PASS source timing: 10 MHz / (640 * 257) = {10000000/(640*257):.9f} Hz, horizontal 15625 Hz')
    assert original_hashes=={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in inputs},'A platform input changed during qualification'
    receipt={'status':'PASS','scope':'Existing platform clock, MRA/loader/input/source assertions plus actual board phase gate, settled final R NVRAM write, packed 8192-byte host image and memory-only bridge regression; no physical RAM/timing/RBF claim.',
             'inputs':original_hashes,
             'commands':logs,'phase_coverage':{key:int(value) for key,value in re.findall(r'(\w+)=(\d+)',phase.group(1))},
             'bridge_receipt':str(bridge/'receipt.json'),'bridge_receipt_sha256':hashlib.sha256((bridge/'receipt.json').read_bytes()).hexdigest()}
    (retained/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print('Platform evidence: '+str(retained/'receipt.json'))

if __name__=='__main__':
    main()
