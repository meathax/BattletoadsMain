"""Compare complete RGB rasters directly, without registration or offsets."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

from PIL import Image

p=argparse.ArgumentParser()
p.add_argument('reference',type=Path)
p.add_argument('native',type=Path)
p.add_argument('--evidence',type=Path)
a=p.parse_args()
ref=Image.open(a.reference).convert('RGB')
actual=Image.open(a.native).convert('RGB')
receipt={'reference':str(a.reference.resolve()),'native':str(a.native.resolve()),
         'reference_sha256':hashlib.sha256(a.reference.read_bytes()).hexdigest(),
         'native_sha256':hashlib.sha256(a.native.read_bytes()).hexdigest(),
         'reference_size':ref.size,'native_size':actual.size,'offset':[0,0]}
if ref.size==actual.size:
    reference_rgb=ref.tobytes();native_rgb=actual.tobytes()
    difference=bytes(255 if reference_rgb[i:i+3]!=native_rgb[i:i+3] else 0
                     for i in range(0,len(reference_rgb),3))
    receipt['different_pixels']=difference.count(255)
    receipt['total_pixels']=len(difference)
    receipt['passed']=receipt['different_pixels']==0
else:
    receipt['passed']=False
if a.evidence:
    a.evidence.mkdir(parents=True,exist_ok=True)
    (a.evidence/'receipt.json').write_text(json.dumps(receipt,indent=2))
    actual.save(a.evidence/'native.png')
    if ref.size==actual.size:
        Image.frombytes('L',ref.size,difference).save(a.evidence/'difference.png')
print(json.dumps(receipt,indent=2))
sys.exit(0 if receipt['passed'] else 1)
