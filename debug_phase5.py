import sys; sys.path.insert(0, '.')
import csv, os, json
from datetime import datetime, timedelta
from modules.pattern_learner import _load_csv_rows, _normalize_command, analyze, MIN_OCCURRENCES, MIN_DAY_SPAN

def write_fake(rows):
    with open('command_log.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['timestamp','input_type','command','response','time_taken_s','status'])
        for r in rows:
            w.writerow(r)

base = datetime.now() - timedelta(days=21)
rows = []
added = 0; day = 0
while added < 8:
    dt = base + timedelta(days=day)
    if dt.weekday() < 5:
        ts = dt.replace(hour=9, minute=10, second=0)
        rows.append([ts.strftime('%Y-%m-%d %H:%M:%S'), 'voice', 'play coding playlist on spotify', 'ok', '0.5', 'success'])
        added += 1
    day += 1

write_fake(rows)
loaded = _load_csv_rows(days=30)
print(f"Loaded rows: {len(loaded)}")

if loaded:
    r0 = loaded[0]
    print(f"First row keys: {list(r0.keys())}")
    print(f"First row: {r0}")
    cmd = r0.get('command', '').lower()
    norm = _normalize_command(cmd)
    print(f"Normalized: {repr(norm)}")
    ts = datetime.strptime(r0['timestamp'], '%Y-%m-%d %H:%M:%S')
    h = ts.hour
    bucket = (h // 2) * 2
    day_type = 'weekend' if ts.weekday() >= 5 else 'weekday'
    print(f"Hour={h} bucket={bucket} day_type={day_type}")

print(f"\nMIN_OCCURRENCES={MIN_OCCURRENCES}, MIN_DAY_SPAN={MIN_DAY_SPAN}")

# manually simulate bucketing
from collections import defaultdict
buckets = defaultdict(list)
for row in loaded:
    try:
        ts = datetime.strptime(row['timestamp'], '%Y-%m-%d %H:%M:%S')
        cmd = row.get('command', '').lower().strip()
        norm = _normalize_command(cmd)
        if not norm:
            print(f"  SKIPPED (no norm): {cmd!r}")
            continue
        hb = (ts.hour // 2) * 2
        dt2 = 'weekend' if ts.weekday() >= 5 else 'weekday'
        buckets[(norm, hb, dt2)].append(ts)
    except Exception as e:
        print(f"  Error: {e}")

print(f"\nBuckets ({len(buckets)}):")
for key, tss in buckets.items():
    dates = sorted(set(t.date() for t in tss))
    span = (dates[-1] - dates[0]).days if len(dates) > 1 else 0
    print(f"  {key}: count={len(tss)}, span={span}d, dates={[str(d) for d in dates]}")
    print(f"  -> passes? count>={MIN_OCCURRENCES}: {len(tss) >= MIN_OCCURRENCES}, span>={MIN_DAY_SPAN}: {span >= MIN_DAY_SPAN}")

# now try full analyze
if os.path.exists('patterns.json'): os.remove('patterns.json')
if os.path.exists('pattern_last_run.json'): os.remove('pattern_last_run.json')
print("\nRunning analyze()...")
result = analyze()
print(f"analyze() returned {len(result)} patterns")
for p in result:
    print(f"  {p}")
