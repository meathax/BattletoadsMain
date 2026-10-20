"""Audit an actually routed fit against the user's Cyclone V resource limits."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


LIMITS = {
    'alms': (75, 80), 'labs': (85, 90),
    'peak_interconnect': (80, 85), 'average_interconnect': (50, 60),
    'm10k': (85, 90), 'block_bits': (80, 85), 'dsp': (80, 90),
}


def audit(snapshot):
    output = snapshot / 'output_files'
    summary = output / 'Arcade-Battletoads.fit.summary'
    report = output / 'Arcade-Battletoads.fit.rpt'
    failures = []
    if not summary.exists() or 'Fitter Status : Successful' not in summary.read_text():
        failures.append('a successful fitted snapshot is required')
    if not report.exists():
        failures.append('detailed fitter report is required; summary cannot establish routing/LAB use')
    body = report.read_text(errors='replace') if report.exists() else ''
    table = []
    for line in body.splitlines():
        if line.startswith(';'):
            cells = [v.strip() for v in line.split(';')[1:-1]]
            if len(cells) >= 2:
                table.append(cells)
    metrics = {}

    def count(name, pattern, fallback=None):
        candidates = [r for r in table if re.fullmatch(pattern, ' '.join(r[0].split()), re.I)]
        if not candidates and fallback:
            candidates = [r for r in table if re.fullmatch(fallback, ' '.join(r[0].split()), re.I)]
        if not candidates:
            return
        parsed = []
        for row in candidates:
            match = re.match(r'([\d,]+)\s*/\s*([\d,]+)', row[1])
            if not match:
                # Partition tables also repeat labels with raw counts only.
                # Only device-wide used/capacity rows establish utilization.
                continue
            used, capacity = [int(v.replace(',', '')) for v in match.groups()]
            if capacity <= 0:
                failures.append('invalid resource capacity: ' + row[0])
                continue
            parsed.append({'used': used, 'capacity': capacity,
                           'percent': 100 * used / capacity,
                           'report_label': row[0]})
        if parsed:
            if len({v['capacity'] for v in parsed}) != 1:
                failures.append('inconsistent resource capacities: ' + name)
            # Repeated summaries must never hide a higher detailed count.
            metrics[name] = max(parsed, key=lambda v: v['percent'])

    count('alms', r'Logic utilization \(in ALMs\)')
    count('labs', r'(?:Total )?LABs: partially or completely used')
    # Failed fits may report zero generic RAM blocks before nonzero M10Ks.
    count('m10k', r'M10K blocks', fallback=r'Total RAM Blocks')
    count('block_bits', r'Total block memory bits')
    count('dsp', r'(?:Total DSP Blocks|DSP blocks)')
    routing = []
    for row in table:
        if 'interconnect' in row[0].lower() and ('peak' in row[0].lower() or 'average' in row[0].lower()):
            values = [float(v) for v in re.findall(r'(\d+(?:\.\d+)?)\s*%', ' '.join(row[1:]))]
            if values:
                routing.append({'label': row[0], 'percentages': values})
    for name, word in (('peak_interconnect', 'peak'), ('average_interconnect', 'average')):
        values = [v for row in routing if word in row['label'].lower() for v in row['percentages']]
        if values:
            # Conservative if a report presents total, horizontal and vertical.
            metrics[name] = {'percent': max(values), 'reported_percentages': values}
    for name, (target, hard) in LIMITS.items():
        if name not in metrics:
            failures.append('missing actual routed resource: ' + name)
            continue
        metric = metrics[name]
        metric.update({'target_percent': target, 'hard_limit_percent': hard,
                       'meets_target': metric['percent'] <= target,
                       'meets_hard_limit': metric['percent'] <= hard})
        if not metric['meets_hard_limit']:
            failures.append(f"{name}: {metric['percent']:.3f}% exceeds {hard}%")
    hierarchy = []
    active = False
    columns = None
    for row in table:
        if len(row) == 1:
            continue
        if row[0] == 'Compilation Hierarchy Node':
            columns = row
            active = True
            continue
        if active and columns and len(row) == len(columns):
            hierarchy.append(dict(zip(columns, row)))
            if len(hierarchy) >= 60:
                break
    receipt = {'snapshot': str(snapshot), 'metrics': metrics,
               'routing_rows': routing, 'hierarchy': hierarchy,
               'source_manifest_sha256': hashlib.sha256((snapshot / 'snapshot.json').read_bytes()).hexdigest()
               if (snapshot / 'snapshot.json').exists() else None,
               'fit_report_sha256': hashlib.sha256(report.read_bytes()).hexdigest() if report.exists() else None,
               'meets_all_hard_limits': not failures, 'failures': failures,
               'clock_domains': '80 MHz master with enables; related 160 MHz memory and phase-shifted SDRAM receive; MiSTer HDMI/platform clocks retained',
               'scope': 'resource limits are separate from the source-bound eight-corner timing and functional gates'}
    (snapshot / 'resource_audit.json').write_text(json.dumps(receipt, indent=2))
    retained = Path(__file__).resolve().parents[2] / 'tests/graphics/evidence/quartus' / snapshot.name
    retained.mkdir(parents=True, exist_ok=True)
    (retained / 'resource_audit.json').write_text(json.dumps(receipt, indent=2))
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', type=Path)
    result = audit(parser.parse_args().snapshot.resolve())
    print(json.dumps({'metrics': result['metrics'], 'meets_all_hard_limits': result['meets_all_hard_limits'],
                      'failures': result['failures']}, indent=2))
    sys.exit(not result['meets_all_hard_limits'])
