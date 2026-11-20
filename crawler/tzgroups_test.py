#!/usr/bin/env python3
"""python3 crawler/tzgroups_test.py: every site has a group, the crons are unique, the workflow lists them all."""
import glob, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from tzgroups import GROUPS, group_of, plan  # noqa: E402

ROOT = os.path.dirname(HERE)
cases = [
    ("FR", "Île-de-France", 48.85, 2.35, "eu-af"), ("MG", "", -18.9, 47.5, "eu-af"), ("BR", "São Paulo", -23.5, -46.6, "br"),
    ("US", "New York", 40.7, -74.0, "na-e"), ("US", "Texas", 31.8, -106.4, "na-m"), ("US", "Texas", 29.7, -95.4, "na-c"),
    ("US", "Florida", 30.4, -87.2, "na-c"), ("US", "Colorado", 38.98, -105.08, "na-m"), ("US", "Arizona", 33.4, -112.0, "na-m"),
    ("US", "Hawaii", 21.3, -157.8, "na-p"), ("US", "Alaska", 61.2, -149.9, "na-p"), ("CA", "Ontario", 43.7, -79.4, "na-e"),
    ("CA", "Manitoba", 49.9, -97.1, "na-c"), ("CA", "Alberta", 51.0, -114.0, "na-m"), ("CA", "British Columbia", 49.3, -123.1, "na-p"),
    ("AU", "Victoria", -37.8, 145.0, "au-e"), ("AU", "Western Australia", -31.9, 115.9, "au-w"),
]
for cc, region, lat, lng, want in cases:
    assert group_of(cc, region, lat, lng) == want, (cc, region, group_of(cc, region, lat, lng), want)
assert len({g["cron"] for g in GROUPS.values()}) == len(GROUPS)
text = open(os.path.join(ROOT, "ci", "nightly-crawl.yml"), encoding="utf-8").read()
for gid, meta in GROUPS.items():
    minute, hour = meta["cron"].split()
    assert f'cron: "{minute} {hour} * * *"' in text, gid
    assert plan(f"{minute} {hour} * * *")["groups"] == [gid]
assert len(re.findall(r'- cron: "', text)) == len(GROUPS)
for path in glob.glob(os.path.join(ROOT, "sites", "*.json")):
    if path.endswith("optout.json"):
        continue
    for rec in json.load(open(path, encoding="utf-8")):
        assert group_of(rec.get("cc"), rec.get("region"), rec.get("lat"), rec.get("lng")) in GROUPS, rec["id"]
print("ok")
