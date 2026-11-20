"""Time-zone groups for the nightly crawl.

Every church site belongs to one group. A group is crawled once a day, at its own cron time
(UTC), which falls at roughly 2-4 AM local time for its churches, so pages are read while
their website is quiet. The Nexus site shows the same schedule on church and organisation
pages (src/nexus/lib/nightlySchedule.ts must stay in step with this file; the site repo
checks both against every church of the directory).

group_of(cc, region, lat, lng) -> group id.
"""
from __future__ import annotations

# id -> UTC cron "minute hour" (7 minutes past: GitHub delays runs at the top of the hour), matrix shards, label
GROUPS: dict[str, dict] = {
    "eu-af": {"cron": "7 1", "shards": 7, "label": "Europe + Africa"},
    "br": {"cron": "7 5", "shards": 1, "label": "Brazil"},
    "na-e": {"cron": "7 7", "shards": 15, "label": "US/Canada Eastern + Atlantic"},
    "na-c": {"cron": "7 8", "shards": 8, "label": "US/Canada Central"},
    "na-m": {"cron": "7 9", "shards": 3, "label": "US/Canada Mountain"},
    "na-p": {"cron": "7 10", "shards": 5, "label": "US/Canada Pacific, Alaska, Hawaii"},
    "au-e": {"cron": "7 16", "shards": 1, "label": "Australia east + centre"},
    "au-w": {"cron": "7 18", "shards": 1, "label": "Western Australia"},
}
GROUP_ORDER = list(GROUPS)

EU_AF = {"FR", "GB", "DE", "BE", "CH", "CI", "CM", "CD", "SN", "BJ", "TG", "BF", "MG"}  # Madagascar (UTC+3) is read at 4 AM: only a few sites

US_EASTERN = {
    "Connecticut", "Delaware", "District of Columbia", "Georgia", "Maine", "Maryland", "Massachusetts",
    "Michigan", "New Hampshire", "New Jersey", "New York", "North Carolina", "Ohio", "Pennsylvania",
    "Puerto Rico", "Rhode Island", "South Carolina", "Vermont", "Virginia", "West Virginia",
}
US_CENTRAL = {
    "Alabama", "Arkansas", "Illinois", "Iowa", "Louisiana", "Minnesota", "Mississippi", "Missouri",
    "Oklahoma", "Wisconsin",
}
US_MOUNTAIN = {"Arizona", "Colorado", "Montana", "New Mexico", "Utah", "Wyoming"}
US_PACIFIC = {"California", "Nevada", "Washington"}

CA_EASTERN = {"Ontario", "Québec", "Quebec", "Nova Scotia", "New Brunswick / Nouveau-Brunswick", "Prince Edward Island",
              "Newfoundland and Labrador"}
CA_CENTRAL = {"Manitoba", "Saskatchewan"}
CA_MOUNTAIN = {"Alberta", "Northwest Territories"}
CA_PACIFIC = {"British Columbia", "Yukon"}


def _by_longitude(lng: float) -> str:
    """Contiguous North America fallback when the region is unknown or split across zones."""
    if lng >= -85.0:
        return "na-e"
    if lng >= -102.0:
        return "na-c"
    if lng >= -114.5:
        return "na-m"
    return "na-p"


def _us(region: str, lat: float, lng: float) -> str:
    if region == "Hawaii" or (lat and lng and lat < 23.5 and lng < -154):
        return "na-p"
    if region == "Alaska" or (lat > 51 and lng < -130):
        return "na-p"
    if region in US_EASTERN:
        return "na-e"
    if region == "Florida":  # the panhandle west of the Apalachicola river is Central
        return "na-c" if lng and lng < -85.0 and lat and lat > 29.6 else "na-e"
    if region == "Indiana":  # the north-west and south-west corners are Central
        return "na-c" if lng and lng < -86.9 else "na-e"
    if region == "Kentucky":
        return "na-c" if lng and lng < -85.9 else "na-e"
    if region == "Tennessee":
        return "na-e" if lng and lng > -85.4 else "na-c"
    if region in US_CENTRAL:
        return "na-c"
    if region == "Texas":
        return "na-m" if lng and lng < -104.9 else "na-c"
    if region == "Kansas":
        return "na-m" if lng and lng < -101.7 else "na-c"
    if region == "Nebraska":
        return "na-m" if lng and lng < -101.0 else "na-c"
    if region == "South Dakota":
        return "na-m" if lng and lng < -100.4 else "na-c"
    if region == "North Dakota":
        return "na-m" if lng and lng < -101.8 else "na-c"
    if region in US_MOUNTAIN:
        return "na-m"
    if region == "Idaho":  # the northern panhandle is Pacific
        return "na-p" if lat and lng and lat > 45.9 and lng < -115.5 else "na-m"
    if region == "Oregon":  # Malheur county is Mountain
        return "na-m" if lat and lng and lat < 44.3 and lng > -117.7 else "na-p"
    if region in US_PACIFIC:
        return "na-p"
    return _by_longitude(lng or -90.0)


def _ca(region: str, lat: float, lng: float) -> str:
    if region == "Ontario":
        return "na-c" if lng and lng < -90.5 else "na-e"
    if region == "British Columbia":
        return "na-m" if lat and lng and lng > -116.5 and lat < 51.5 else "na-p"
    if region in CA_EASTERN:
        return "na-e"
    if region in CA_CENTRAL:
        return "na-c"
    if region in CA_MOUNTAIN:
        return "na-m"
    if region in CA_PACIFIC:
        return "na-p"
    return _by_longitude(lng or -90.0)


def group_of(cc: str, region: str | None = "", lat: float | None = 0.0, lng: float | None = 0.0) -> str:
    cc = (cc or "").upper()
    region = (region or "").strip()
    lat, lng = float(lat or 0.0), float(lng or 0.0)
    if cc in EU_AF:
        return "eu-af"
    if cc == "BR":
        return "br"
    if cc == "AU":
        return "au-w" if region == "Western Australia" or (not region and lng and lng < 129) else "au-e"
    if cc == "CA":
        return _ca(region, lat, lng)
    if cc == "US":
        return _us(region, lat, lng)
    return "eu-af"


def countries_of(group: str) -> list[str]:
    return {
        "eu-af": sorted(EU_AF),
        "br": ["BR"],
        "na-e": ["US", "CA"], "na-c": ["US", "CA"], "na-m": ["US", "CA"], "na-p": ["US", "CA"],
        "au-e": ["AU"], "au-w": ["AU"],
    }[group]


def plan(selector: str) -> dict:
    """Which groups a workflow run crawls. selector: a group id, "all", or the cron expression that fired
    (github.event.schedule, e.g. "7 7 * * *")."""
    selector = (selector or "").strip()
    if selector in ("", "all"):
        groups = GROUP_ORDER
    elif selector in GROUPS:
        groups = [selector]
    else:
        stamp = " ".join(selector.split()[:2])
        groups = [g for g in GROUP_ORDER if GROUPS[g]["cron"] == stamp]
    if not groups:
        raise SystemExit(f"no time-zone group is scheduled at {selector!r}")
    matrix = [{"group": g, "shard": n, "shards": GROUPS[g]["shards"]} for g in groups for n in range(GROUPS[g]["shards"])]
    return {"groups": groups, "matrix": matrix}


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) >= 2 and sys.argv[1] == "plan":
        result = plan(sys.argv[2] if len(sys.argv) > 2 else "all")
        # key=value lines for $GITHUB_OUTPUT
        print("groups=" + json.dumps(result["groups"], separators=(",", ":")))
        print("matrix=" + json.dumps(result["matrix"], separators=(",", ":")))
    else:
        for g in GROUP_ORDER:
            print(g, GROUPS[g]["cron"], GROUPS[g]["shards"], GROUPS[g]["label"])
