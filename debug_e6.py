import sys; sys.path.insert(0, '.')
from datetime import datetime, timedelta

def make_rows(cmd, hour, count=8, span=35, day_type="weekday"):
    rows = []; base = datetime.now() - timedelta(days=span); added=0; day=0
    while added < count:
        dt = base + timedelta(days=day)
        is_weekend = dt.weekday() >= 5
        if (day_type=="weekday" and not is_weekend) or (day_type=="weekend" and is_weekend):
            ts = dt.replace(hour=hour, minute=5, second=0)
            rows.append([ts.strftime("%Y-%m-%d %H:%M:%S"), "voice", cmd, "ok", "0.5", "success"])
            added += 1
        day += 1
    return rows

cutoff = datetime.now() - timedelta(days=30)
print(f"cutoff: {cutoff.date()}")

for day_type in ["weekday","weekend"]:
    rows = make_rows("search youtube", 11, day_type=day_type)
    included = [r for r in rows if datetime.strptime(r[0],"%Y-%m-%d %H:%M:%S") >= cutoff]
    dates = sorted(set(datetime.strptime(r[0],"%Y-%m-%d %H:%M:%S").date() for r in included))
    span = (dates[-1]-dates[0]).days if len(dates)>1 else 0
    print(f"{day_type}: total={len(rows)} included={len(included)} span={span}d dates={dates[:3]}...{dates[-1:]}")
