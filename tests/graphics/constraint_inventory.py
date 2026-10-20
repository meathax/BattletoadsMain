"""Bounded inventory of TimeQuest coverage; no constraints are changed."""
from collections import Counter
from pathlib import Path
import json
import sys

directory=Path(sys.argv[1])
rows=[line.split(';')[1:-1] for line in (directory/'constraints.rpt').read_text(errors='replace').splitlines()
      if line.startswith(';')]
no_clock=[row[0].strip() for row in rows if len(row)>1 and "No clock feeds" in row[1]]
groups=Counter(name.split('|')[0].split('~')[0] for name in no_clock)
ucp=(directory/'unconstrained.rpt').read_text(errors='replace').splitlines()
ports={}
for label in ('Input','Output'):
    # Headings are padded to their table width.
    start=next(i for i,line in enumerate(ucp) if line.startswith(';') and
               len(line.split(';')[1:-1])==1 and
               line.split(';')[1].strip()==f'Unconstrained {label} Ports')
    entries=[]
    for line in ucp[start+4:]:
        if not line.startswith(';'): break
        fields=[value.strip() for value in line.split(';')[1:-1]]
        if fields and fields[0] not in ('Port','Name','Node Name'):
            entries.append(fields[:3])
    ports[label.lower()]=entries
output={'no_clock_count':len(no_clock),'no_clock_roots':dict(groups),
        'unconstrained_ports':ports,
        'note':'Coverage inventory only; intentional I/O boundaries still require explicit review.'}
(directory/'constraint_inventory.json').write_text(json.dumps(output,indent=2))
print(json.dumps({'no_clock_count':len(no_clock),'no_clock_roots':dict(groups),
                  'unconstrained_ports':{name:[row[0] for row in entries]
                                         for name,entries in ports.items()}},indent=2))
