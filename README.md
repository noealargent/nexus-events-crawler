# Nexus events crawler

Nightly reader of public church event pages for the Nexus directory
([nexuschurches.com](https://nexuschurches.com)). It covers France, the United Kingdom,
Canada, Switzerland and the United States, about 24,000 church websites a night.

## What it does

- `sites/<CC>.json`: the church websites to read (id, slug, name, website, city, region,
  coordinates). Everything here is already public on nexuschurches.com. Built with
  `crawler/build_sites.py` from the directory data, with the evangelical policy and
  opt-outs (`sites/optout.json`) already applied.
- `.github/workflows/nightly-crawl.yml` (source copy in `ci/nightly-crawl.yml`) runs every
  night at 08:30 UTC. It uses 20 parallel jobs. Each job owns the sites whose host hashes to it
  (`crawler/shard.py`), so one host is never read by two jobs at once.
- Politeness (`crawler/import_events.py`): an identifiable User-Agent
  (`NexusEventsBot`, see https://nexuschurches.com/annuaire/evenements/robot). It honours robots.txt,
  TDM reservation and `noai`. It waits 3 s between requests to the same host, caps each site at
  22 s, and sends conditional GETs (ETag / Last-Modified) that are kept per shard with `actions/cache`.
- The `publish` job merges the shards (`crawler/merge_shards.py`) and uploads
  `nexus-events.tar.gz` (one `<CC>.json` per country plus `summary.json`) and `summary.json`
  to the `nightly` release, replacing last night's files.
- The Nexus site downloads that asset and merges it (`crawler/merge_into_site.py`). Only churches
  read successfully that night replace their rows, and a country is skipped if its results are stale,
  incomplete, or would lose more than 30 % of its events.

No secrets are used. The only token is the automatic `GITHUB_TOKEN`.

## Opt out

A church can ask to be left out through « Retirer mes événements » on its Nexus page, or by
writing to contact@nexuschurches.com.

## Refresh the site list

```
python3 crawler/build_sites.py /path/to/nexus/public/osm/c
```

## License

All rights reserved. See [LICENSE](LICENSE). OpenStreetMap-derived data is under ODbL.
