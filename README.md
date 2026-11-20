# Nexus events crawler

Nightly reader of public church event pages for the Nexus directory
([nexuschurches.com](https://nexuschurches.com)). It covers France, the United Kingdom,
Canada, Switzerland and the United States, about 24,000 church websites a night.

## What it does

- `sites/<CC>.json`: the church websites to read (id, slug, name, website, city, region,
  coordinates). Everything here is already public on nexuschurches.com. Built with
  `crawler/build_sites.py` from the directory data, with the evangelical policy and
  opt-outs (`sites/optout.json`) already applied.
- `crawler/tzgroups.py` puts every site in a time-zone group, so each country is read in its own
  night (roughly 2-4 AM local). `.github/workflows/nightly-crawl.yml` has one cron per group
  and runs it with parallel jobs. Each job owns the sites of its group whose host hashes to it
  (`crawler/shard.py`), so one host is never read by two jobs at once.

  | Group | Countries | UTC cron | Local time (winter / summer) |
  |---|---|---|---|
  | `eu-af` | FR GB DE BE CH, CI CM CD SN BJ TG BF MG | 01:07 | Paris 2:07 / 3:07, London 1:07 / 2:07, Abidjan 1:07 |
  | `br` | BR | 05:07 | Brasília 2:07 |
  | `na-e` | US + CA Eastern, Atlantic | 07:07 | New York 2:07 / 3:07 |
  | `na-c` | US + CA Central | 08:07 | Chicago 2:07 / 3:07 |
  | `na-m` | US + CA Mountain | 09:07 | Denver 2:07 / 3:07 |
  | `na-p` | US + CA Pacific, Alaska, Hawaii | 10:07 | Los Angeles 2:07 / 3:07 |
  | `au-e` | AU east + centre | 16:07 | Sydney 3:07 (AEDT) / 2:07 (AEST) |
  | `au-w` | AU Western Australia | 18:07 | Perth 2:07 |

- Politeness (`crawler/import_events.py`): an identifiable User-Agent
  (`NexusEventsBot`, see https://nexuschurches.com/annuaire/evenements/robot). It honours robots.txt,
  TDM reservation and `noai`. It waits 3 s between requests to the same host, caps each site at
  22 s, and sends conditional GETs (ETag / Last-Modified) that are kept per shard with `actions/cache`.
- The `publish` job merges the shards of a group (`crawler/merge_shards.py --group`) and uploads
  `nexus-events.tar.gz` (one `<CC>.json` per country of the group plus `summary.json`) and `summary.json`
  to the group's own release, `nightly-<group>`, replacing that group's files. Groups never touch each other's release.
- The Nexus site downloads that asset and merges it (`crawler/merge_into_site.py`). Only churches
  read successfully that night replace their rows, and a country is skipped if its results are stale,
  incomplete, or would lose more than 30 % of the group's events. Each group is merged on its own and
  never wipes another group's events.

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
