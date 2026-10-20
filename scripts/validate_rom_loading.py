"""Validate the MRA against MAME and materialize an ignored simulation image."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]


def build_image(mra, archive):
    """MiSTer Main reads map nibbles from right to left (low byte first)."""
    image = bytearray()
    for section in mra.find("rom[@index='0']"):
        parts = section.findall('part') if section.tag == 'interleave' else [section]
        contents = []
        for part in parts:
            crc = int(part.get('crc'), 16)
            info = next(i for i in archive.infolist() if i.CRC == crc)
            content = archive.read(info)
            assert zlib.crc32(content) == crc, part.get('name')
            contents.append(content)
        if section.tag == 'part':
            image.extend(contents[0])
            continue
        width = int(section.get('output')) // 8
        sizes = [len(c) // sum(d != '0' for d in p.get('map'))
                 for p, c in zip(parts, contents)]
        assert len(set(sizes)) == 1
        interleaved = bytearray(sizes[0] * width)
        lanes = set()
        for part, content in zip(parts, contents):
            mapping = list(reversed(part.get('map')))
            assert len(mapping) == width
            stride = sum(d != '0' for d in mapping)
            for lane, digit in enumerate(mapping):
                if digit != '0':
                    assert lane not in lanes
                    lanes.add(lane)
                    interleaved[lane::width] = content[int(digit) - 1::stride]
        assert lanes == set(range(width))
        image.extend(interleaved)
    return bytes(image)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('zip', type=Path)
    ap.add_argument('--mame', type=Path, required=True)
    ap.add_argument('--out', type=Path, default=ROOT / 'build' / 'roms' / 'download.bin')
    args = ap.parse_args()
    xml = ET.fromstring(subprocess.run([str(args.mame), '-listxml', 'btoads'],
                                      capture_output=True, check=True).stdout)
    version = xml.get('build').split()[0].replace('.', '').zfill(4)
    mra = ET.parse(ROOT / 'releases' / 'Battletoads.mra').getroot()
    assert mra.findtext('mameversion') == version
    assert mra.find("rom[@index='0']").get('zip') == 'btoads.zip'
    buttons = mra.find('buttons')
    assert buttons.get('names') == 'Attack,Jump,Coin,Start,Service Menu,Pause'
    assert buttons.get('default') == 'A,B,Select,Start,R,L'
    switches = mra.find('switches')
    if switches is not None:
        dips = xml.find("machine[@name='btoads']").findall('dipswitch')
        defaults = sum(int(v.get('value')) for d in dips for v in d.findall('dipvalue')
                       if v.get('default') == 'yes')
        # Preserve this core's three-player default; all other defaults are MAME's.
        assert int(switches.get('default'), 16) == defaults & ~0x08
        assert len(switches.findall('dip')) == len(dips) == 8
        for dip in switches.findall('dip'):
            reference = next(d for d in dips if d.get('name') == dip.get('name'))
            bit = int(dip.get('bits'))
            assert int(reference.get('mask')) == 1 << bit
            ids = dip.get('ids').split(',')
            for value in reference.findall('dipvalue'):
                assert ids[int(value.get('value')) >> bit] == value.get('name')
    roms = {r.get('name'): r for r in xml.find("machine[@name='btoads']").findall('rom')}
    with zipfile.ZipFile(args.zip) as archive:
        for part in mra.findall('.//part'):
            reference = roms[part.get('name')]
            content = archive.read(part.get('name'))
            assert len(content) == int(reference.get('size'))
            assert part.get('crc') == reference.get('crc')
            assert hashlib.sha1(content).hexdigest() == reference.get('sha1')
        p0, p1 = (archive.read(n) for n in ['btc0-p0.u120', 'btc0-p1.u121'])
        # Independent ROM_LOAD32_WORD oracle; no MRA map digits are used here.
        maincpu = bytearray(0x800000)
        maincpu[0::4], maincpu[1::4] = p0[0::2], p0[1::2]
        maincpu[2::4], maincpu[3::4] = p1[0::2], p1[1::2]
        expected = maincpu + archive.read('btc0-s.u109') + archive.read('bt.u102')
        image = build_image(mra, archive)
        assert image == expected
    assert len(image) == 0xA08000
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(image)
    print(f'PASS MAME {version}: all 4 ROM sizes, CRCs, SHA1s; MRA equals ROM_LOAD32_WORD')
    print('PASS controls: Attack=A, Jump=B, Coin=Select, Start=Start')
    if switches is not None:
        print('PASS DIP defaults/settings')
    print(f'PASS payload {len(image):#x} bytes, sha256={hashlib.sha256(image).hexdigest()}')
    print(f'Simulation input: {args.out.resolve()} (ROM data stays out of git)')


if __name__ == '__main__':
    main()
