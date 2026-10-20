"""Compact diagnostic view of bounded TimeQuest path reports."""
import argparse
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument("reports",nargs="+",type=Path)
p.add_argument("--paths",type=int,default=3)
a=p.parse_args()
for report in a.reports:
    print("REPORT",report)
    path=0; data=False; past_clock=False
    with report.open(errors="replace") as stream:
        for index,line in enumerate(stream):
            if index>=12000: break
            if line.startswith("Path #"):
                path+=1; data=False; past_clock=False
                if path>a.paths: break
                print(line.strip())
            fields=[v.strip() for v in line.split(";")[1:-1]]
            if not path or not fields: continue
            if fields[0] in ("From Node","To Node","Setup Relationship","Clock Skew","Data Delay","Number of Logic Levels"):
                print(" | ".join(fields).rstrip(" |"))
            if fields==["Data Arrival Path"]: data=True
            if fields==["Data Required Path"]: data=False
            if data and len(fields)==7:
                if fields[-1]=="data path": past_clock=True; continue
                if past_clock and fields[3] in ("CELL","IC","uTco"):
                    print(" | ".join(fields))
