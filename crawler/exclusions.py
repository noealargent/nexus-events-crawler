"""Nexus inclusion rule: only churches confessing the historic Christian faith (Trinity; Jesus fully God and fully man).

Shared by scripts/osm/build.py (OpenStreetMap import), scripts/rna/merge_into_osm.py (RNA / Sirene import) and
scripts/osm/prune_excluded.py (removal from an existing public/osm), so a future import drops the same places.

Excluded groups:
  jehovahs_witnesses   Jehovah's Witnesses (Kingdom Hall, Salle du Royaume, Témoins de Jéhovah, Salón del Reino…)
  latter_day_saints    The Church of Jesus Christ of Latter-day Saints / Mormon, incl. FLDS and Strangite
  christian_science    Church of Christ, Scientist / Christian Science (Reading Room, Society, Église du Christ scientiste)
  unitarian_universalist  Unitarian / Unitarian Universalist / Universalist (incl. historic "First Parish" tagged UU)
  unity                Unity (Unity Church of X, Unity of X, Christ Unity, Practical Christianity) — not the word "unity"
                       in other churches' names (Unity Baptist, Church of God in Unity, Love and Unity…), and a bare
                       "Unity Church / Chapel" (mostly rural GNIS congregations) only with a Unity website or tag
  la_luz_del_mundo     La Luz del Mundo (Iglesia del Dios Vivo, Columna y Apoyo de la Verdad)
  iglesia_ni_cristo    Iglesia ni Cristo
  spiritist            Spiritist (Kardec, centre spirite, espírita) / Spiritualist (NSAC, "Spiritual Science") — not the
                       "Spiritual Church" / "Spiritual Baptist" congregations
  swedenborgian        Swedenborgian / New Church (Church of the New Jerusalem, Lord's New Church) — not the many
                       "New Jerusalem Baptist / COGIC" churches nor evangelical "New Church" plants
  moorish_science      Moorish Science Temple of America
  new_thought          Religious Science / Divine Science / Science of Mind / Centers for Spiritual Living / Mental Science

Kept on purpose: Oneness Pentecostals and the New Apostolic Church (outside this rule).

Also excluded (evangelical directory only, Nov 2026):
  Community of Christ / RLDS / "Reorganized", Restoration Branches, Remnant Church, Bickertonite "The Church of Jesus Christ".
Reviewed ids: exclusion_keep.json "keep" (stray tags) and "drop" (ambiguous name, outside evidence).

Signals, in order:
  1. the name names one of the groups (specific phrases only: "Jehovah Jireh", "Ward Chapel", "Saint …",
     "Latter Rain" do not match);
  2. the OSM denomination tag (denomination=jehovahs_witness / mormon / lds / latter_day_saints / christian_science…),
     the stated network/operator, or the official website (jw.org, churchofjesuschrist.org, christianscience.com…).
A tag, network or website signal is ignored when the name clearly states another church tradition
("Broken Arrow Seventh Adventist Church" tagged jehovahs_witness), and a name signal is ignored when the name also
states another tradition and the place is tagged with it (a node named "… Methodist Church;Jehovah's Witness …").
"""
import json
import os
import re
import unicodedata

GROUPS = ("jehovahs_witnesses", "latter_day_saints", "christian_science", "unitarian_universalist", "unity",
          "la_luz_del_mundo", "iglesia_ni_cristo", "spiritist", "swedenborgian", "moorish_science", "new_thought")


def _fold(s):
    s = unicodedata.normalize("NFD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[_’`]", lambda m: " " if m.group(0) == "_" else "'", s)


NAME = {
    "jehovahs_witnesses": re.compile(
        r"kingdom hall|knights hall of jehovah|salle du royaume|salles? d.assemblees? (?:des |de )?temoins|salon(?:es)? del reino"
        r"|testigos de jehova|temoins de j[eh]?h?ovah?|jehovah'?s? witness|jehovahs? witness|jehovah wittness|jehovah'?s'? wittness"
        r"|congregation[- ]jehovah|assembly hall of jehovah|convention center of jehovah|\bjw\.org\b|^jw$|watchtower"
        r"|jehovas zeugen|zeugen jehovas|konigreichssaal"),
    "latter_day_saints": re.compile(
        r"latter[- ]?day saints?|saints?[- ](?:des[- ])?derniers[- ]jours|\bsts[- ]derniers[- ]jours|\bmormon|\blds\b|\bflds\b"
        r"|community of christ|\brlds\b|reorgani[sz]ed latter|restoration branch"
        r"|^(?:the |sharing the )?church of jesus christ(?:$|,| \()"
        r"|thechurchofjesuschrist\.org"),
    "christian_science": re.compile(
        r"church(?: of |[- ])christ,?[- ]+scien(?:tist|ce)\b|christian scien(?:ce|tist)|christ scientiste|science chretienne"
        r"|church of christian scientist"),
    "unitarian_universalist": re.compile(
        r"\bunitari(?:an|en|enne|os?|as?)s?\b|universalist(?:as?|s)?\b(?! (?:baptist|missionary))|\buu fellowship|\buu congregation"),
    # Unity (Unity School of Christianity / Unity Worldwide Ministries): "Unity of X", "Unity Church of X", "Unity in X",
    # "X Unity", "Christ Church Unity", "Unity Spiritual Center"… — never the word inside another church's name
    # ("Unity Baptist", "Church of God in Unity", "Love and Unity", "Christian Unity Church", "Greater Unity…").
    "unity": re.compile(
        r"^unity$|^unity (?:church|center|centre|temple|spiritual|society|of |in |on the |at the |fellowship of |worship center$|[a-z]+$)"
        r"|^(?:christ|first|the|garden park|grand strand|christ light|christ-love|independent|wayfarers)"
        r" (?:church )?unity(?: church| temple| cathedral| spiritual| of| at|$)"
        r"|christ church unity|unity (?:school|society) of practical christianity|practical christianity|\\bunity truth|\\bunity spiritual"),
    "la_luz_del_mundo": re.compile(r"luz del mundo|columna y apoyo de la verdad"),
    "iglesia_ni_cristo": re.compile(r"\bni cristo\b"),
    "spiritist": re.compile(
        r"spiritis[tm]|\bspirites?\b|spiritisme|\bespirit[ae]s?\b|espirita|kardec|spiritualis[tm]|spiritual science|leon denis"),
    "swedenborgian": re.compile(
        r"swedenborg|church of the new jerusalem|society of the new church|nova hierosolyma|nouvelle jerusalem \(swedenborg"
        r"|^(?:almont|fryeburg|kempton|glenview|laporte|washington|bryn athyn|pittsburgh|boston|cambridge) new church\b"),
    "moorish_science": re.compile(r"moorish science"),
    "new_thought": re.compile(
        r"religious science|divine science|science of mind|spiritual living|mental science|new thought|mind science"
        r"|science des religions"),
}
# Unity: a bare "Unity Church / Chapel / Tabernacle / Worship Center" is mostly a rural congregation named after its
# community (GNIS), so the name alone does not decide; a Unity website or denomination tag still does.
UNITY_GENERIC = re.compile(r"^unity (?:church|chapel|tabernacle|temple tabernacle|worship center)$")
# Unity: generic uses of the word in other churches' names.
UNITY_NOT = re.compile(
    r"baptist|missionary|church of god|god in christ|methodist|adventist|holiness|holy|cogic|in god|of faith|of love|love and unity"
    r"|christian unity|greater|brethren|apostolic|gospel|bible|jesus|unity and charity|crc|covenant|outreach|pentecost|ministries international")
# Other branches of the Latter Day Saint movement kept by judgment (see module docstring).
LDS_KEEP = re.compile(r"community of christ|\brlds\b|reorgani[sz]ed|restoration|restored|remnant|bickerton|cofchrist")
DENOM = {
    "jehovahs_witnesses": re.compile(r"jehovah|witness|temoins de jehovah"),
    "latter_day_saints": re.compile(r"latter.?day|mormon|^lds$|\bflds\b|strangite"),
    "christian_science": re.compile(r"christian scien|christ,? scientist|^scientist$|^christ scientist$|science chretienne"),
    "unitarian_universalist": re.compile(r"unitarian|universalist|unitarien"),
    "unity": re.compile(r"^unity$|^unity church|^unity school|^new thought$"),
    "la_luz_del_mundo": re.compile(r"luz del mundo|light of the world"),
    "iglesia_ni_cristo": re.compile(r"ni cristo"),
    "spiritist": re.compile(r"spiritis|spiritualis|\bspirites?\b|espirita|spiritual science"),
    "swedenborgian": re.compile(r"swedenborg|new jerusalem|^new church$"),
    "moorish_science": re.compile(r"moorish"),
    "new_thought": re.compile(r"science of mind|religious science|divine science|centers? for spiritual living|new thought"),
}
WEBSITE = {
    "jehovahs_witnesses": re.compile(r"(?:^|[/.])(?:jw\.org|watchtower\.org)(?:/|$)"),
    "latter_day_saints": re.compile(r"(?:^|[/.])(?:churchofjesuschrist\.org|thechurchofjesuschrist\.org|cofchrist\.org|lds\.org|ldschurch\.org|ldsstrangite\.com)(?:/|$)"),
    "christian_science": re.compile(r"(?:^|[/.])(?:christianscience\.com|marybakereddylibrary\.org|csmonitor\.com|cs-[a-z]+\.org)(?:/|$)"),
    "unitarian_universalist": re.compile(r"(?:^|[/.])uua\.org(?:/|$)"),
    "unity": re.compile(r"(?:^|[/.])(?:unity\.org|unityworldwideministries\.org|unity(?!.*(?:baptist|methodist|bible|gospel))[a-z-]*\.(?:org|com|net))(?:/|$)"),
    "la_luz_del_mundo": re.compile(r"(?:^|[/.])lldm\.org(?:/|$)"),
    "iglesia_ni_cristo": re.compile(r"(?:^|[/.])(?:iglesianicristo\.net|incmedia\.org)(?:/|$)"),
    "spiritist": re.compile(r"(?:^|[/.])(?:spiritist\.us|nsac\.org)(?:/|$)"),
    "swedenborgian": re.compile(r"(?:^|[/.])(?:swedenborg\.org|newchurch\.org)(?:/|$)"),
    "moorish_science": re.compile(r"(?:^|[/.])moorishsciencetempleofamerica"),
    "new_thought": re.compile(r"(?:^|[/.])(?:csl\.org|divinescience\.org)(?:/|$)"),
}
# Another church tradition stated in the name.
OTHER_TRADITION = re.compile(
    r"baptist|catholi|methodist|lutheran|presbyterian|episcopal|anglican|pentecost|assembl(?:y|ies) of god|nazarene|adventist"
    r"|church of god|evangeli|bapti|protestant|reformed|mennonite|brethren|bretheren|orthodox|wesleyan|apostolic|full gospel|bible church"
    r"|congregational|moravian|disciples of christ")


# Places whose only signal is a stray denomination tag on a plainly different church, kept after review (Oct 2026).
# Key: directory id ("n…" node, "w…" way, "r…" relation). Also read by src/nexus/osm/exclusions.test.ts.
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "exclusion_keep.json"), encoding="utf-8") as _f:
    _REVIEWED = json.load(_f)
KEEP_IDS = _REVIEWED["keep"]
DROP_IDS = _REVIEWED.get("drop", {})  # {"id": {"group": …, "why": …}}: excluded on outside evidence, name alone is ambiguous


def _host(url):
    return re.sub(r"^https?://", "", (url or "").strip().lower()).split("?")[0]


def excluded(name, denomination="", network="", website="", tagged="", rec_id=""):
    """Group name when the place belongs to an excluded group, else "".

    name          display name
    denomination  OSM denomination tag (raw, e.g. "jehovahs_witness") or the directory's denOther ("Jehovah's Witnesses")
    network       network / operator / brand
    website       official website
    tagged        the directory's mapped denomination ("baptist", "methodist", "", "other"…), for the conflict rule
    rec_id        directory id ("n123", "w456"…), for the reviewed KEEP_IDS
    """
    if rec_id and rec_id in KEEP_IDS:
        return ""
    if rec_id and rec_id in DROP_IDS:
        return DROP_IDS[rec_id]["group"]
    n, d, net, web = _fold(name), _fold(denomination).strip(), _fold(network), _host(website)
    other_in_name = bool(OTHER_TRADITION.search(n))
    skip = set()
    if UNITY_NOT.search(n):
        skip.add("unity")
    groups = [g for g in GROUPS if g not in skip]
    for group in groups:
        if group == "unity" and UNITY_GENERIC.search(n):
            continue
        if NAME[group].search(n):
            if other_in_name and tagged not in ("", "other"):
                return ""
            return group
    if other_in_name:
        return ""
    for group in groups:
        if d and DENOM[group].search(d):
            return group
        if WEBSITE[group].search(web):
            return group
        if tagged in ("", "other") and NAME[group].search(net):
            return group
    return ""


def clean_network(network):
    """A kept place must not expose an excluded body as its network (it would become a directory filter option):
    SouthLake Church, Assemblies of God, carries network="The Church of Jesus Christ of Latter-day Saints"."""
    n = _fold(network)
    unity_ok = not (UNITY_NOT.search(n) or UNITY_GENERIC.search(n))
    return "" if any(NAME[g].search(n) for g in GROUPS if g != "unity" or unity_ok) else network
