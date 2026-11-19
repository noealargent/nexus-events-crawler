"""Nexus evangelical focus (owner decision, Nov 1 2026): the directory lists evangelical churches only.

Faith basis: the declaration of faith of the CNEF (Conseil national des évangéliques de France, adopted 15 June 2010,
itself the World Evangelical Alliance basis of 1951): Scripture as the Word of God and supreme authority; one God,
Father, Son and Holy Spirit; Jesus Christ, God made flesh, his atoning death, bodily resurrection and return;
salvation by grace through faith alone; the Holy Spirit; the unity of all believers; the resurrection.

A church is accepted when it adheres to that basis, whatever its name or family: evangelical, Baptist, Pentecostal,
charismatic, Brethren, Mennonite, free and independent churches, and Reformed / Lutheran / Methodist / Anglican
congregations that adhere. Open data (OpenStreetMap, RNA) cannot tell us what each congregation confesses, so this
module sorts every record with the signals we have (denomination tag, network, name) into:

  remove  Roman Catholic (incl. Eastern Catholic, Old Catholic, traditionalist), Orthodox (Eastern and Oriental),
          other non-evangelical creeds still in the data (Christadelphian, gnostic, masonic…). A Catholic or Orthodox
          tag or an unambiguous name (paroisse, diocèse, Notre-Dame, basilique, abbaye, Our Lady, Sacred Heart…).
          In France, an untagged "Église Saint-…", chapelle, cathédrale… is a Catholic parish building (except in
          Alsace-Moselle and the Pays de Montbéliard, where Lutheran churches bear saints' names: review).
  review  kept for now, decision pending: a name that may be Catholic / Orthodox but is not certain ("St. John's
          Church" with no tag), conflicting signals (tagged Catholic but named "évangélique"), historic mainline bodies
          that may not adhere (Église protestante unie, UEPAL, PC(USA), ELCA, Episcopal Church, United Methodist, UCC,
          Disciples, Quakers…), Adventists, Oneness / New Apostolic, Community of Christ…
  keep    evangelical families, and untagged places with no non-evangelical signal.

Strict pass (owner, Nov 3 2026: « que évangéliques »): every "keep" then goes through _evidence_pass(). Mainline
families (Reformed / Presbyterian, Lutheran, Methodist, Anglican / Episcopal, Congregational, EPUdF / UEPAL, also
recognised from the website domain: epudf.org, eglise-protestante-unie.fr, uepal…) are hidden unless the record names
an evangelical body inside the family (Église réformée évangélique / UNEPREF, EREI, Église évangélique méthodiste,
Free Methodist, Wesleyan, AME / CME, PCA, OPC, EPC, ACNA, Free Lutheran, Lutheran Brethren…). In France, "temple" or
"protestant" is no longer evidence by itself: a record needs a union, network, CNEF-member website, or an evangelical
word (évangélique, pentecôtiste, baptiste, Assemblée de Dieu, libre, mennonite…) in its name or website; otherwise it
is hidden as "uncertain". Hidden records stay in h/ and come back when the church claims its page and signs the charter.

Used by scripts/osm/prune_evangelical.py (static data), scripts/osm/build.py and scripts/rna/merge_into_osm.py
(future imports) and mirrored by src/nexus/evangelical.ts (code-side guard). classify() returns (action, reason).
"""
import json
import os
import re
import unicodedata

try:
    from exclusions import excluded as _excluded
except ImportError:  # imported as scripts.osm.evangelical
    from .exclusions import excluded as _excluded


def fold(s):
    s = unicodedata.normalize("NFD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[’`]", "'", s)
    return re.sub(r"[\s_]+", " ", s).strip()


REMOVE_DEN = {"catholic": "catholic", "orthodox": "orthodox"}
EVANGELICAL_DEN = {"evangelical", "baptist", "pentecostal", "charismatic", "assemblies", "nondenominational", "brethren",
                   "mennonite"}
PROTESTANT_DEN = {"methodist", "lutheran", "reformed", "anglican"}

CATHOLIC_TEXT = re.compile(
    r"catholi|\bparoiss|\bdioces|\bdiocese|\barchdioces|\beveche\b|\bparish\b|\bbasilic|\babba?ye\b|\babbatiale|\bprieure\b|\bpriory\b"
    r"|\bcouvent\b|\bconvent\b|\bcarmelit|\bcarmel (?:de|du|des|saint|notre)|\bnotre[- ]dame\b|\bour lady\b|\bnuestra senora|\bnossa senhora"
    r"|\bvirgen\b|\bvierge\b|guadalupe|sacre[- ]c(?:oe|œ)ur|sacred heart|sagrado corazon|immacul|blessed sacrament|saint[- ]sacrement"
    r"|\brosaire\b|\brosary\b|precious blood|corpus christi|\bfsspx?\b|pius x|pie x\b|\bshrine\b|\bsanctuaire\b|\bsantuario\b"
    r"|\bermitage\b|\bhermitage chapel|\bcollegiale\b|\bmonast|\bjesuit|\bbenedictin|\bfranciscan|\bfrancisca|\bdominicain|\bdominican"
    r"|\bcapucin|\bcapuchin|\bclarisses?\b|\bursulin|\bvisitation\b|\bsisters of\b|\bsoeurs\b|\bfilles de la\b|\bpetites soeurs"
    r"|\bpontif|\bmaronit|\bmelkit|\bchalde|\bsyro[- ]malabar|\bruthenian|\bmission (?:san|santa|nuestra)|\bnewman center"
    r"|\bknights of columbus|\bholy rosary|\bassumption\b|\bassomption\b|\bannonciation\b|\bdes saints[- ]anges")
ORTHODOX_TEXT = re.compile(
    r"\borthodo(?:x|xe|xa|xo)\b(?! presbyterian)|\bcopt(?:e|ic|o)\b|\bapostolique armenienne|\barmenian apostolic|\bantiochian\b|\bbyzantin|\btheotokos\b|\bpanagia\b|\bdormition\b|\bassyrian church|\bchurch of the east\b|\bmalankara\b"
    r"|\bjacobite\b|\bsyriac\b|\bmetropole grecque|\bpatriarca")
# Ethnic names of Orthodox churches: a signal only for untagged places without any Protestant word (Russian Baptist…).
ETHNIC_ORTHODOX_TEXT = re.compile(
    r"\b(?:greek|grecque|russian|russe|serbian|serbe|romanian|roumaine|armenian|armenienne|ethiopian|ethiopienne|eritrean|georgian"
    r"|bulgarian|macedonian|ukrainian|carpatho)\b")
NONCREEDAL_TEXT = re.compile(
    r"christadelph|ecclesia gnostica|\bgnostic|johannite|\bmasonic\b|\bmetaphysical\b|liberal catholic|\btheosoph|\brosicruc"
    r"|\bunification|\bthe way international|\bchurch of satan|\beckankar|\buniversal life church|\bhebrew israelite|\bindian shaker"
    r"|\bmariavit|\bcarthusian|\biglesia filipina independiente|\bpolish national|\bni cristo\b|\buua\b|\btemple lot\b")
# Names that may be Catholic / Orthodox / Episcopal / Lutheran without a tag (review, never remove on their own).
WEAK_TEXT = re.compile(
    r"^(?:the )?(?:saint|sainte|saints|st|ste|sts|san|santa|santo|sao|sankt)\b|\b(?:saint|st|ste|sts)\.? [a-z]|\bsan [a-z]|\bsanta [a-z]"
    r"|\bholy (?:family|cross|name|trinity|spirit|redeemer|angels|innocents|apostles|ghost|communion|nativity)\b|\btransfiguration\b"
    r"|\bannunciation\b|\bepiphany\b|\bresurrection church|\bascension\b|\bchrist the king\b|\bchrist roi\b|\bcapilla\b|\bmission\b$"
    r"|\bcathedral\b|\bcathedrale\b|\bcalvaire\b|\bgrotte\b|\boratoire\b|\boratory\b|\bchapelle\b|\bchapel of (?:our|the holy|st)")
EVANGELICAL_TEXT = re.compile(
    r"evangeli|\bbapti|\bbautista|pentec|\bassembl(?:y|ies|ee|ees|ea|eia)\b|\bchurch of god\b|\bnazarene|\bwesleyan|\bfree methodist"
    r"|\bcalvary\b|\bvineyard\b|\bfoursquare|\balliance\b|\bbible\b|\bbiblique|\bbiblica|\bgospel\b|\bbrethren\b|\bfreres\b|\bmennonit"
    r"|\bapostoli|\btabernacle|\bchristian (?:center|centre|fellowship|church|assembly)\b|\bcentre chretien|\bfellowship\b|\bministr"
    r"|\bministere|\bministerio|\bchurch of christ\b|\bchurches of christ\b|\bprotestant|\breformee?s?\b|\breformed\b|\blutheri|\blutheran"
    r"|\bmethodist|\bpresbyter|\bcongregational|\bholiness\b|\bcogic\b|\bnon[- ]?denominational|\bnondenominational|\bcristiana?\b"
    r"|\bchretienne?\b|\biglesia de dios\b|\bigreja\b|\bredeemed\b|\brccg\b|\bhillsong\b|\bcaef\b|\baeeblf\b|\bfeebf\b|\bepudf\b"
    r"|\bmessianic|\bmessianique|\bsalvation army|\barmee du salut|\btemple\b|\btemplo\b|\bcommunity church\b|\bchristian and missionary"
    r"|\bmissionary\b|\bquadrangulaire|\bvie et lumiere|\bportes ouvertes\b|\bmission evangel|\bcharismati|\breveil\b|\brevival\b"
    r"|\belim\b|\bfiec\b|\bnewfrontiers\b|\bgospel hall\b")
# Saints' names and feasts that contain Protestant-looking words (Saint-Jean-Baptiste, John the Evangelist, Pentecôte).
SAINT_WORDS = re.compile(
    r"\b(?:saint|sainte|st|ste|san|sao|santo|john|jean|juan|joao|johannes|giovanni|mark|marc|luke|luc|matthew|mathieu|matthieu)\.?"
    r"[ .'-]+(?:the |l'|l |le |el |de |de la |o )?(?:baptist[ae]?|bautista|battista|evangeli[a-z]*)\b|\bbaptistere|\bde la pentecote\b"
    r"|\bles reformes\b|\bnativite de saint|\bmartyre de saint")
# Explicit Protestant words, enough to doubt a Catholic / Orthodox tag.
STRONG_PROTESTANT_TEXT = re.compile(
    r"evangelique|evangelical|evangelica|evangelisch|\bbaptist church|\beglise baptiste|\bbaptiste\b|\bbaptist\b|\bbautista\b"
    r"|protestant|pentecotiste|pentecostal|assemblee de dieu|assembl(?:y|ies) of god|asambleas? de dios|eglise reformee|reformed church"
    r"|lutheri|lutheran|methodist|presbyterian|nazarene|church of god\b|iglesia de dios|\bcalvary chapel|\bvineyard")
# Historic mainline bodies that may not adhere to the evangelical basis (review: kept until the owner decides).
MAINLINE_TEXT = re.compile(
    r"\beglise protestante unie\b|\bepudf\b|\buepal\b|\bunion des eglises protestantes d.alsace|\bconfession d.augsbourg"
    r"|\beglise reformee de france\b|\b(?:erf|efr)\b|\bpresbyterian church \(?u\.?s\.?a\.?\)?|\bpc\s?\(?usa\)?|\bpcusa\b"
    r"|\bevangelical lutheran church (?:in|of) america\b|\belca\b|\bunited church of christ\b|\bucc\b|\bunited methodist\b|\bumc\b"
    r"|\bdisciples of christ\b|\bchristian church \(disciples|\bmetropolitan community church|\bquaker|\bsociety of friends\b"
    r"|\bfriends meeting|\bmeeting house of friends|\bepiscopal\b|\bepiscopale\b"
    r"|\bmoravian\b|\breformed church in america\b|\bamerican baptist churches usa\b|\bunited church\b|\buniting\b|\becumenical\b"
    r"|\boecumen"
    # United Kingdom (Nov 17 2026): established / historic mainline bodies.
    r"|(?<!free )\bchurch of england\b|\bchurch in wales\b|(?<!free )\bchurch of scotland\b|\bscottish episcopal\b|\bchurch of ireland\b"
    r"|\bunited reformed church\b|\burc\b|\bmethodist church of (?:great britain|ireland)\b"
    # Canada / Switzerland (Nov 18 2026)
    r"|\bunited church of canada\b|\banglican church of canada\b|\bpresbyterian church in canada\b"
    r"|\bevangelical lutheran church in canada\b|\belcic\b"
    r"|\bevangeli(?:sch[- ])?reformiert|\bkirchgemeinde\b|\blandeskirche\b"
    r"|\bfederation des eglises protestantes de suisse\b|\bfeps\b|\bschweizerischer evangelischer kirchenbund"
    r"|\bchristkathol|\baltkathol")
ADVENTIST_TEXT = re.compile(r"adventist|adventiste|seventh[- ]day|septieme jour|\bsda\b|adventistchurch\.org")
LDS_MOVEMENT_NAME = re.compile(
    r"^(?:the |sharing the )?church of jesus christ(?:$|,| \()"
    r"|restoration branch")
ONENESS_TEXT = re.compile(
    r"united pentecostal|\bupci\b|\boneness\b|jesus only|in jesus'? name|apostolic assembly of the faith in christ jesus"
    r"|pentecostal assemblies of the world|\bpaw\b")
OTHER_REVIEW_TEXT = re.compile(
    r"new apostolic|neo[- ]?apostolique|community of christ|latter|reorgani[sz]ed|\brlds\b|restoration branch"
    r"|(?:^|(?<=, ))(?:the |sharing the )?church of jesus christ(?:$|,| \()"
    r"|united church of god|simultan|\bunitarian"
    r"|\bchristian scien|swedenborg|\bnew church\b|\binterfaith|\binterreligi|\bmulti[- ]?faith")
# Regions where Lutheran churches bear saints' names (Alsace-Moselle, Pays de Montbéliard): a saint's name is not enough.
LUTHERAN_SAINT_POSTCODES = re.compile(r"^(?:67|68|57|90|25[2-4])")
FR_BUILDING = re.compile(
    r"^(?:ancienne |vieille |petite |grande )?(?:eglise|chapelle|cathedrale|basilique|abbaye|abbatiale|collegiale|prieure|ermitage"
    r"|oratoire|sanctuaire|calvaire|grotte|couvent|monastere|carmel|crypte|capella|cappella|chjesa|gleisa|glisa|iliz|chapel)\b"
    r"|^(?:notre[- ]dame|saint|sainte|saints|st|ste)\b|\bsaint[- ]|\bsainte[- ]")


def _first_pass(rec):
    """(remove | review | keep, reason): the Nov 1 audit pass; classify() settles every review case."""
    name = fold(rec.get("name", ""))
    den = rec.get("den", "") or ""
    other = fold(rec.get("denOther", ""))
    net = fold(rec.get("network", ""))
    text = f"{name} | {other} | {net}"
    # African Methodist Episcopal (AME, AME Zion, CME): Methodist, not the Episcopal Church.
    mtext = re.sub(r"methodist episcopal|\bame\b", "methodist", text)
    plain = SAINT_WORDS.sub(" ", name)
    evangelical_name = bool(EVANGELICAL_TEXT.search(plain))
    strong_protestant = bool(STRONG_PROTESTANT_TEXT.search(plain))
    cat = bool(CATHOLIC_TEXT.search(text))
    orth = bool(ORTHODOX_TEXT.search(text))
    group = _excluded(rec.get("name", ""), rec.get("denOther", ""), rec.get("network", ""), rec.get("website", ""), den,
                      rec.get("id", ""))
    if group:
        return "remove", "non-evangelical creed: " + group
    if LDS_MOVEMENT_NAME.search(name):
        return "remove", "non-evangelical creed: latter_day_saints"
    if NONCREEDAL_TEXT.search(text):
        return "remove", "non-evangelical creed: " + NONCREEDAL_TEXT.search(text).group(0)
    if den in REMOVE_DEN:
        if strong_protestant and not CATHOLIC_TEXT.search(name) and not ORTHODOX_TEXT.search(name):
            return "review", f"tagged {den} but the name says otherwise"
        return "remove", f"tagged {den}"
    if den == "other" and (cat or orth):
        hits = {m.group(0) for m in CATHOLIC_TEXT.finditer(text)} | {m.group(0) for m in ORTHODOX_TEXT.finditer(text)}
        if hits <= {"paroiss", "parish", "sanctuaire", "sanctuary"}:
            return "review", f"denomination '{rec.get('denOther', '')}', name reads '{sorted(hits)[0]}'"
        if strong_protestant and not CATHOLIC_TEXT.search(name) and not ORTHODOX_TEXT.search(name):
            return "review", f"denomination '{rec.get('denOther', '')}' with a Protestant name"
        return "remove", ("catholic" if cat else "orthodox") + f" (denomination '{rec.get('denOther', '')}')"
    if OTHER_REVIEW_TEXT.search(text):
        return "review", "other tradition: " + OTHER_REVIEW_TEXT.search(text).group(0)
    if ONENESS_TEXT.search(text):
        return "review", "oneness pentecostal (non-Trinitarian)"
    if den == "adventist" or ADVENTIST_TEXT.search(text):
        return "review", "adventist"
    if den in EVANGELICAL_DEN or den in PROTESTANT_DEN or den == "other" or evangelical_name or rec.get("src") == "rna":
        if cat or orth:
            hits = {m.group(0) for m in CATHOLIC_TEXT.finditer(text)} | {m.group(0) for m in ORTHODOX_TEXT.finditer(text)}
            # "Paroisse protestante", "St. Paul's Lutheran Parish", "Sanctuaire de Dieu": soft words next to a Protestant name.
            soft = hits <= {"paroiss", "parish", "sanctuaire", "sanctuary"}
            if not (soft and (strong_protestant or den in EVANGELICAL_DEN | PROTESTANT_DEN)):
                if not den:
                    return "review", "mixed signals: " + ("catholic" if cat else "orthodox") + " words in a Protestant name"
                return "review", f"tagged {den} but the name reads '{sorted(hits)[0]}'"
        m = MAINLINE_TEXT.search(mtext)
        if m:
            return "review", "mainline body: " + m.group(0)
        if den == "other" and other in ("quaker", "friends", "society of friends"):
            return "review", "mainline body: quaker"
        if den in EVANGELICAL_DEN:
            return "keep", f"tagged {den}"
        if den in PROTESTANT_DEN:
            return "keep", f"tagged {den} (historic Protestant, adherence asked at claim)"
        if rec.get("src") == "rna":
            if RNA_CATHOLIC_CONGREGATION.search(name):
                return "remove", "catholic religious congregation (RNA): " + RNA_CATHOLIC_CONGREGATION.search(name).group(0)
            if RNA_NONTRINITARIAN.search(f"{name} {fold(rec.get('website', ''))}"):
                return "remove", "non-Trinitarian body (RNA): " + RNA_NONTRINITARIAN.search(f"{name} {fold(rec.get('website', ''))}").group(0)
            return "keep", "RNA Protestant/evangelical association"
        if den == "other":
            if evangelical_name or EVANGELICAL_TEXT.search(other) or other in ("", "none", "no", "n/a", "unknown", "other", "others", "christian", "christianity"):
                return "keep", f"denomination '{rec.get('denOther', '')}'"
            return "review", f"unlisted denomination '{rec.get('denOther', '')}'"
        return "keep", "evangelical/Protestant name"
    # Untagged, no Protestant word in the name.
    if cat:
        return "remove", "catholic name: " + CATHOLIC_TEXT.search(text).group(0)
    if orth:
        return "remove", "orthodox name: " + ORTHODOX_TEXT.search(text).group(0)
    if MAINLINE_TEXT.search(mtext):
        return "review", "mainline body: " + MAINLINE_TEXT.search(mtext).group(0)
    if ETHNIC_ORTHODOX_TEXT.search(name):
        return "review", "untagged ethnic name (Orthodox?): " + ETHNIC_ORTHODOX_TEXT.search(name).group(0)
    if rec.get("cc") == "FR":
        if FR_BUILDING.search(name):
            if LUTHERAN_SAINT_POSTCODES.search(rec.get("postcode", "") or ""):
                return "review", "untagged church building in a Lutheran region (Alsace-Moselle / Montbéliard)"
            return "remove", "untagged French parish building (église/chapelle Saint-…, Notre-Dame…)"
        return "review", "untagged, no evangelical signal"
    if WEAK_TEXT.search(name):
        return "review", "untagged saint / liturgical name (Catholic, Episcopal, Lutheran or Orthodox?)"
    return "keep", "untagged, no non-evangelical signal"


# RNA associations filed as Protestant whose name is a Catholic religious congregation, or a body outside the Trinitarian
# basis (World Mission Society Church of God, Branham "Message" churches), found in the Paris check (Nov 4 2026).
RNA_CATHOLIC_CONGREGATION = re.compile(r"\boratoire de jesus\b|\bfreres (?:de la )?doctrine chretienne\b|\bfilles de jesus\b")
RNA_NONTRINITARIAN = re.compile(r"\beglise de dieu association mondiale\b|\bedam[- ]france\b|vieespoiretverite|\bbranham"
                                r"|\beglise du septieme age\b|\bparole de l'heure\b")


# Settling the review group (owner decision, Nov 1 2026, preview first): outside the Trinitarian basis -> remove;
# mainline / Adventist / uncertain -> hidden until a leader claims the page and accepts the charter.
NONTRINITARIAN_OTHER = re.compile(
    r"new apostolic|neo[- ]?apostolique|community of christ|latter[- ]day|reorgani[sz]ed|\brlds\b|restoration branch"
    r"|(?:^|(?<=, ))(?:the |sharing the )?church of jesus christ(?:$|,| \()"
    r"|\bunitarian|\bchristian scien|swedenborg")
NONTRINITARIAN_DEN_OTHER = {"branhamism", "cutlerite", "united pentacostal", "united pentecostal", "jewish", "konkokyo", "acim",
                            "unitarian", "christadelphian", "bickertonite"}
# OSM free-text denominations that name evangelical families the first pass did not know (misspellings included).
EVANGELICAL_DEN_OTHER = {
    "covenant", "efca", "acts 29", "converge", "pca", "sbc", "aog", "cowboy", "cowboy church", "nazerene", "batpist", "ame",
    "a.m.e. zion", "romanian penecostal", "romanian pentacostal", "missonary", "soma communities", "christian mission",
    "christian union", "united brethern", "anglican church in north america", "christian congregation in the united states",
    "jews for jesus", "hispanic church", "free",
    # United Kingdom OSM denomination values (build.py keeps them as free text)
    "free church of scotland", "free presbyterian", "fiec", "independent evangelical", "elim", "elim pentecostal",
    "new testament church of god", "redeemed christian church of god", "grace baptist", "strict baptist",
    "newfrontiers", "assemblies of god", "apostolic church", "gospel hall"}
# Untagged US "… Cathedral of Faith / Praise / Deliverance": Pentecostal and charismatic naming, not a Catholic cathedral.
CATHEDRAL_EVANGELICAL = re.compile(
    r"\bcathedral\b.*\b(?:faith|praise|deliverance|hope|abundant|life|light|miracles?|prayer|worship|blessings?|adoracion|outreach"
    r"|glory|victory|power|harvest|kingdom|body of christ|ancient of days)\b|\b(?:abundant|faith|praise|deliverance|life|worship)\b.*\bcathedral\b")
# Not a place of worship any more (owner feedback, Nov 1 2026): "Ruine de l'église", "… Church (ruins)", "abandoned church".
# Place names such as "Beaver Ruin Church" or "Big Ruin Creek Baptist" stay.
RUIN_NAME = re.compile(
    r"^ruines?\b|\bruines? d|\bvestiges? d|\(ruins?\)|\bchurch ruins?\b|\bruins?$|\bruins? of\b|\babandoned\b|\bvacant\b")
# UEPAL (Union des Églises protestantes d'Alsace et de Lorraine): the RNA "Conseil presbytéral Église luthérienne /
# réformée - Paroisse de …" parish councils and EPAL / EPRAL names, the Alsace-Moselle equivalent of the EPUdF -> hidden.
UEPAL_NAME = re.compile(r"^conseil presbyteral (?:de l )?eglise (?:lutherienne|reformee)\b|\b(?:uepal|epal|epcaal|epral)\b")
HIDDEN_GROUPS = ("mainline", "adventist", "us-saint-name", "fr-untagged", "lutheran-region", "catholic-tag-protestant-name",
                 "uncertain")


def hidden_group(reason):
    """The hidden-until-claimed group of a 'hidden' reason (meta.json keeps a count per group)."""
    if reason.startswith("mainline body"):
        return "mainline"
    if reason == "adventist":
        return "adventist"
    if reason.startswith("untagged saint"):
        return "us-saint-name"
    if reason.startswith("untagged, no evangelical"):
        return "fr-untagged"
    if reason.startswith("untagged church building in a Lutheran"):
        return "lutheran-region"
    if reason.startswith("tagged catholic") or reason.startswith("tagged orthodox"):
        return "catholic-tag-protestant-name"
    return "uncertain"


# Evangelical focus, strict pass (owner decision, Nov 3 2026: "que évangéliques"): a historic Protestant word ("temple",
# "protestant", "réformée", "luthérienne"…), a Lutheran / Reformed / Methodist / Anglican tag or an RNA association with
# no denomination is not evangelical evidence on its own. A kept record also needs positive evidence; otherwise it is
# hidden until a leader claims the page and accepts the charter (mainline family -> "mainline", else "uncertain").
# Mainline bodies recognised from the website domain (the name and tags often say only "Temple protestant").
MAINLINE_WEB = re.compile(
    r"epudf|eglise-?protestante-?unie|protestants?-?unis|\buepal\b|\bepal\b|protestants?-?(?:strasbourg|alsace|mulhouse|colmar)"
    r"|lutherien|lutheran|luther\b|reformee?s?\b|\berf\b|\belca\b|pcusa|presbyterian|\bumc\b|umc\.|methodist|episcopal|anglican"
    r"|\bucc\b|disciples|\bcofe\b|churchofengland|europe\.anglican|evangelisch|protestantisch|ekd\.")
# Mainline families in a name or a free-text denomination (Lutheran, Reformed, Presbyterian, Methodist, Anglican, UEPAL…).
MAINLINE_FAMILY_TEXT = re.compile(
    r"lutheri|lutheran|\breformee?s?\b|\breformed\b|\breformiert|\bpresbyter|\bmethodist|\bepiscopal|\banglican|\bevangelisch"
    r"|protestantisch|\bprotestante? unie|\bconsistoire|\bconseil presbyteral|\bcongregational\b|\bwaldensian|\bvaudois")
# Positive evangelical evidence (name, free-text denomination, network): evangelical unions and networks (CNEF members:
# AdD, FEEBF, AEEBLF, UEEL, CAEF, EPE, UNEPREF, Église apostolique, Armée du Salut, Vie et Lumière…) and evangelical
# vocabulary. "évangélique luthérienne" (EELF) and the German "evangelisch" (Protestant) are not evidence.
EVIDENCE_TEXT = re.compile(
    r"evangeli(?!sch)|\bbapti|\bbautista|pentec|\bassembl(?:y|ies|ee|ees|ea|eia)\b(?! cultuelle)|\brhema\b|\badd\b|\bchurch of god\b|\beglise de dieu\b"
    r"|\bnazar(?:en|ene|een)|\bwesleyan|\bfree methodist|\bglobal methodist|\bcalvary\b|\bevangile\b|\bpour (?:le )?christ\b|\bjesus\b|\bvineyard\b|\bfoursquare|\bquadrangulaire|\balliance\b"
    r"|\bbible\b|\bbibli(?:que|ca|cal)\b|\bgospel\b|\bbrethren\b|\bfreres\b|\bmennonit|\banabapt|\bapostoli|\btabernacle"
    r"|\bchristian (?:center|centre|fellowship|church|assembly)\b|\bcentre chretien|\bfellowship\b|\bministr|\bministere"
    r"|\bministerio|\bministeriel|\bchurch(?:es)? of christ\b|\beglise du christ\b|\bholiness\b|\bcogic\b|\bnon[- ]?denominational"
    r"|\bcristiana?\b|\bchretien(?:ne)?s?\b|\biglesia de dios\b|\bigreja\b|\bredeemed\b|\brccg\b|\bhillsong\b|\bcaef\b"
    r"|\baeeblf\b|\bfeebf\b|\bueel\b|\beel\b|\beglises? (?:evangeliques? |protestantes? )?libres?\b|\bprotestants? libres?\b|\bcnef\b|\bunepref\b|\berei\b|\bcepee\b"
    r"|\bmessianic|\bmessianique|\bsalvation army|\barmee du salut|\bcommunity church\b|\bmissionary\b|\bvie et lumiere"
    r"|\blife and light\b|\bportes? ouvertes?\b|\bcharismati|\breveil\b|\brevival\b|\btzigane|\bplein evangile|\bfull gospel"
    r"|\bimpact centre|\bicc\b|\bfree church\b|\bfree evangelical|\bsaintete de dieu")
# Evangelical bodies inside the mainline families: they keep a Reformed / Methodist / Anglican / Lutheran word.
MAINLINE_EVANGELICAL_TEXT = re.compile(
    r"reforme?e? evangelique|evangelique reformee?|protestante reformee evangelique|\berei\b|\bunepref\b|evangelique methodiste"
    r"|methodiste evangelique|\bfree methodist|\bglobal methodist|\bevangelical methodist|\bcongregational methodist|\bwesleyan"
    r"|african methodist episcopal|christian methodist episcopal|colored methodist episcopal|\bame\b|\bame zion|\bcme\b|presbyterian church in america|\bpca\b|evangelical presbyterian"
    r"|orthodox presbyterian|\bopc\b|bible presbyterian|reformed presbyterian|associate reformed|reformed baptist|united reformed churches"
    r"|free reformed|protestant reformed|heritage reformed|netherlands reformed|canadian reformed|anglican church in north america|\bacna\b"
    r"|reformed episcopal|lutheran brethren|free lutheran|\baflc\b|conservative congregational|evangelical covenant|baptist")
# United Kingdom only (cc GB, Nov 17 2026): evangelical bodies inside the Presbyterian / Anglican / Congregational /
# Methodist families. Kept apart so French and US records keep their reviewed outcome.
UK_MAINLINE_EVANGELICAL_TEXT = re.compile(
    r"free church of scotland|free presbyterian|international presbyterian|associated presbyterian|free church of england"
    r"|evangelical congregational|\befcc\b|wesleyan reform|\bfiec\b")
# Website domains of evangelical unions and churches (no word boundaries: "eglisebaptiste.fr", "add-lyon.fr").
EVIDENCE_WEB = re.compile(
    r"evangel(?!isch)|baptist|pentec|assemblee|assembleede?dieu|(?:^|[./-])add(?:[0-9./-]|france|lyon|paris)|eglise-?libre|protestants?-?libres?"
    r"|(?:^|[./-])u?eel|(?:^|[./-])epe[.-]|caef|feebf|aeeblf|cnef|vieetlumiere|chretien|bibli|gospel|reveil|hillsong|(?:^|[./-])icc"
    r"|impactcentre|unepref|tabernacle|messian|mennonit|-menno|freres|armeedusalut|salvationarmy|nazarene|wesleyan|freemethodist|globalmethodist"
    r"|(?:^|[./-])(?:pca|opc|epc|acna)(?:[./-]|$)|[a-z]pca\.|calvarychapel|vineyard|foursquare|assemblyofgod|\bag\.org"
    r"|paoc|cmacan|alliancecanada|fellowship\.ca|thefellowship|associatedgospel|\bagc\.(?:ca|org)|emcc\.|mennonitebrethren"
    r"|efccanada|theefc|egliseevangeli|aeq\.|chrischona|vivakirche|bewegungplus|feg\.ch|sea-res|each\.ch|icf\.ch")
# Websites read on Nov 3 2026 that state the church is evangelical ("Église protestante évangélique", CNEF member) while
# the record says only "Temple" / "Église …".
WEBSITE_CHECKED_EVANGELICAL = {"lecep.org", "eglisecbni.org", "egliseconfluence.fr"}
# OSM denomination=evangelical in Alsace-Moselle / Montbéliard is often the German sense (Lutheran / Protestant).
FR_GENERIC_PROTESTANT = re.compile(
    r"^(?:(?:temple|eglise|kirche|evangelische kirche)(?: protestante?)?|paroisse protestante|protestant)"
    r"(?: (?:de|du|des|d|de la|saint|sainte|st|ste)\b.*| [a-z-]+)?$|^(?:eglise|temple) (?:saint|sainte|st|ste)\b")


def _web(rec):
    w = fold(rec.get("website", "") or "")
    m = re.match(r"^(?:https?://)?(?:www\.)?([^/?#]+)(.*)$", w)
    return (m.group(1), m.group(1) + m.group(2)) if m else ("", "")


NOT_EVANGELICAL_FR = re.compile(r"assemblee du desert|\bharris|communaute des chretiens|renouveau religieux")


def _evidence_pass(rec, reason):
    """Strict pass on a kept record: (keep | hidden, reason)."""
    name = fold(rec.get("name", ""))
    den = rec.get("den", "") or ""
    other = fold(rec.get("denOther", ""))
    net = fold(rec.get("network", ""))
    plain = SAINT_WORDS.sub(" ", name)
    text = f"{plain} | {other} | {net}"
    domain, url = _web(rec)
    fr = rec.get("cc") == "FR"
    ev_text = EVIDENCE_TEXT.search(text)
    ev_web = (EVIDENCE_WEB.search(url) or re.match(r".+", domain) if domain in WEBSITE_CHECKED_EVANGELICAL else EVIDENCE_WEB.search(url)) if url else None
    m_web = MAINLINE_WEB.search(domain) if domain else None
    family = den in PROTESTANT_DEN or MAINLINE_FAMILY_TEXT.search(text)
    inner_m = MAINLINE_EVANGELICAL_TEXT.search(f"{text} | {url}") or (
        UK_MAINLINE_EVANGELICAL_TEXT.search(f"{text} | {url}") if rec.get("cc") == "GB" else None)
    inner = inner_m.group(0) if inner_m else (other if other in EVANGELICAL_DEN_OTHER else "")
    # Names that look evangelical by one word but are not: the Huguenot "Assemblée du Désert" gathering, the Harrist
    # church, the Christian Community (Christengemeinschaft, "Mouvement pour un renouveau religieux").
    if fr and NOT_EVANGELICAL_FR.search(text):
        return "hidden", "uncertain: not an evangelical body (" + NOT_EVANGELICAL_FR.search(text).group(0) + ")"
    if m_web and not (inner or (ev_web and not MAINLINE_WEB.search(ev_web.group(0)))):
        return "hidden", f"mainline body: website {domain}"
    if family:
        if inner:
            return "keep", f"evangelical body in a historic family: {inner}"
        if den in EVANGELICAL_DEN and not den == "evangelical" and not re.search(r"lutheri|lutheran|evangelisch", text):
            return "keep", reason
        fam = MAINLINE_FAMILY_TEXT.search(text)
        # France: "Ministère évangélique la Réforme…", "Église presbytérienne coréenne évangélique": evangelical words win
        # over a Reformed / Presbyterian / Methodist word (never over Lutheran, Anglican, EPUdF / UEPAL words or a tag).
        if fr and den not in PROTESTANT_DEN and fam and re.match(r"reform|presbyter$|methodist|congregational", fam.group(0)) and re.search(
                r"evangeli(?!sch)|pentec|\bbapti|charismat|assemblees? de dieu|\bministere", plain) and not re.search(
                r"lutheri|anglican|episcopal|protestante? unie|consistoire|conseil presbyteral|evangelisch", text):
            return "keep", "evangelical name with a Reformed / Presbyterian / Methodist word: " + fam.group(0)
        what = f"tagged {den}" if den in PROTESTANT_DEN else fam.group(0)
        return "hidden", f"mainline body: {what} without evangelical evidence"
    if not fr:
        return "keep", reason
    if den in EVANGELICAL_DEN - {"evangelical"}:
        return "keep", reason
    if den == "evangelical":
        # An OSM denomination=evangelical tag on a generic "Temple" / "Église Saint-…" is not enough (Lutheran / EPUdF
        # buildings carry it too); in Alsace-Moselle / Montbéliard "évangélique" next to a saint's name is Lutheran.
        lutheran_region = bool(LUTHERAN_SAINT_POSTCODES.search(rec.get("postcode", "") or ""))
        saint = re.search(r"\b(?:saint|sainte|st|ste)\b|redemptorist", name)
        generic = FR_GENERIC_PROTESTANT.search(name) or saint
        if rec.get("src") == "rna" or not generic:
            return "keep", reason
        if ev_text and not (saint and lutheran_region and ev_text.group(0).startswith("evangel")):
            return "keep", f"evangelical evidence: {ev_text.group(0)}"
        if ev_web:
            return "keep", f"evangelical website: {domain}"
        return "hidden", "uncertain: tagged evangelical, generic temple / saint's name" + (
            " in a Lutheran region (Alsace-Moselle / Montbéliard)" if lutheran_region else "")
    if ev_text:
        return "keep", f"evangelical evidence: {ev_text.group(0)}"
    if ev_web:
        return "keep", f"evangelical website: {domain}"
    return "hidden", "uncertain: no evangelical evidence (temple / protestant name, no union, network or website)"


_CLOSED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "closed.json")
with open(_CLOSED_FILE, encoding="utf-8") as _closed_f:
    CLOSED_IDS = json.load(_closed_f)


# ---- United Kingdom (cc GB only; Nov 17 2026) ------------------------------------------------------------------------
UK_NOT_CONGREGATION = re.compile(
    r"\bcemetery\b|\bmortuary\b|crematori|chapel of rest|funeral|\bschool chapel\b|\bcollege chapel\b|\bhospital\b|\binfirmary\b"
    r"|\bhospice\b|\bprison\b|\bairport\b|\bchapel \(level|\bbarracks\b|\braf\b|\bgarrison\b|\bcathedral\b|\bminster\b|\babbey\b|\bpriory\b"
    r"|\bcollege\b|\buniversity\b|\bschool\b|\bchaplaincy\b|\bmemorial chapel\b|\bprivate chapel\b|\bestate chapel\b|\bchantry\b")
UK_MAINLINE_NAME = re.compile(
    r"\bkirk\b|\bparish\b|^(?:the )?(?:parish )?church of (?:st|saint|all saints|the holy|holy)\b|^(?:the )?(?:all saints|all souls|christ church|holy trinity|holy cross"
    r"|holy spirit|holy innocents|holy rood|holy sepulchre|st\.? |saint |ss\.? |sts\.? )|\bunited reform|\burc\b|salvation army|\bcitadel\b"
    r"|\bchurch of scotland\b|\bc of e\b|\bc of s\b|\bscottish episcopal\b|\bchurch in wales\b|\beglwys yng nghymru\b|\bchurch of ireland\b"
    r"|\bpresbyterian church in ireland\b|\bmethodist church in ireland\b"
    r"|\beglwys\s+(?:\w+\s+)?sant(?:es)?\b|\beglwys (?:y )?plwyf\b|\beglwys (?:fair|mair|crist|y drindod)\b|^(?:the )?(?:chapel|church)$")
UK_HIDE_BODY = re.compile(r"plymouth brethren christian church|\bpbcc\b|celestial church of christ|\bmeeting room\b")
UK_ONENESS = re.compile(r"\btrue jesus church\b")


def _uk_pass(rec, action, reason):
    """Extra rules for UK records the general rules keep: non-congregation chapels, mainline names with no tag."""
    name = fold(rec.get("name", ""))
    text = f"{name} | {fold(rec.get('denOther', ''))} | {fold(rec.get('network', ''))}"
    if UK_ONENESS.search(text):
        return "remove", "oneness pentecostal (non-Trinitarian): true jesus church"
    if action != "keep":
        return action, reason
    if UK_NOT_CONGREGATION.search(name) and not EVANGELICAL_TEXT.search(name):
        return "hidden", "uncertain: institutional / cemetery chapel or cathedral, not a local congregation (UK)"
    if UK_HIDE_BODY.search(text):
        return "hidden", "uncertain: closed or syncretic body (UK): " + UK_HIDE_BODY.search(text).group(0)
    tagged_ev = (rec.get("den") or "") in EVANGELICAL_DEN - {"evangelical"} and not (rec.get("den") or "") in PROTESTANT_DEN
    if UK_MAINLINE_NAME.search(name) and not tagged_ev and not UK_MAINLINE_EVANGELICAL_TEXT.search(text) and not re.search(
            r"evangelical|baptist|pentecost|elim|gospel|free church|fellowship|vineyard|assembl|brethren|congregational|independent", re.sub(
                r"\bjohn(?:'?s)? the baptist\b", " ", name)):
        return "hidden", "mainline name without evangelical evidence (UK): " + UK_MAINLINE_NAME.search(name).group(0).strip()
    return action, reason


# ---- Canada (cc CA only; Nov 18 2026) ------------------------------------------------------------------------------
CA_NOT_CONGREGATION = re.compile(
    r"\bcemetery\b|\bcimetiere\b|crematori|chapel of rest|funeral|\bschool chapel\b|\bcollege chapel\b|\bhospital\b"
    r"|\bhospice\b|\bprison\b|\bairport\b|\bcathedral\b|\babbey\b|\bpriory\b|\bchaplaincy\b|\bmemorial chapel\b")
CA_MAINLINE_NAME = re.compile(
    r"\bunited church of canada\b|\beglise unie(?: du canada)?\b|\bunited church\b|\banglican church of canada\b|\beglise anglicane du canada\b"
    r"|\bpresbyterian church in canada\b|\beglise presbyterienne du canada\b"
    r"|\bevangelical lutheran church in canada\b|\beglise lutherienne evangelique du canada\b|\belcic\b"
    r"|^(?:the )?(?:st\.? |saint |holy trinity|christ church|all saints)")
CA_EVANGELICAL_INNER = re.compile(
    r"fellowship baptist|associated gospel|\bagc\b|christian and missionary alliance|\bcmacan\b|\balliance church\b"
    r"|pentecostal assemblies|\bpaoc\b|vineyard|foursquare|calvary|free methodist|wesleyan|mennonite brethren"
    r"|evangelical free|evangelical missionary|anglican network|\banic\b|canadian reformed|free reformed"
    r"|christian reformed|\bcrcna\b|\bbaptist\b|\bpentecost|\bassemblee de|assemblees de dieu"
    r"|eglises? evangeli|evangelical(?: church| fellowship| community| assembly)")

def _ca_pass(rec, action, reason):
    """Extra rules for Canadian records: United/Anglican/Presbyterian/ELCIC names with no evangelical evidence."""
    name = fold(rec.get("name", ""))
    text = f"{name} | {fold(rec.get('denOther', ''))} | {fold(rec.get('network', ''))}"
    if action != "keep":
        return action, reason
    if CA_NOT_CONGREGATION.search(name) and not EVANGELICAL_TEXT.search(name):
        return "hidden", "uncertain: institutional / cemetery chapel or cathedral, not a local congregation (CA)"
    tagged_ev = (rec.get("den") or "") in EVANGELICAL_DEN - {"evangelical"}
    if CA_MAINLINE_NAME.search(name) and not tagged_ev and not CA_EVANGELICAL_INNER.search(f"{text} | {fold(rec.get('website', ''))}"):
        # "Evangelical Lutheran Church in Canada" is the mainline ELCIC, not WEA-evangelical.
        if re.search(r"evangelical lutheran church in canada|\belcic\b", name) or not re.search(r"evangelical|baptiste?|pentecost|alliance|gospel|fellowship|vineyard|assemblee", name):
            return "hidden", "mainline name without evangelical evidence (CA): " + CA_MAINLINE_NAME.search(name).group(0).strip()
    return action, reason


# ---- Switzerland (cc CH only; Nov 18 2026) -------------------------------------------------------------------------
# "Église évangélique réformée" / "Evangelisch-reformiert" is the cantonal Protestant landeskirche (FEPS/SEK), not
# evangelical in the World Evangelical Alliance sense. "evangelikal" (German) and FREE / FEG / Chrischona are.
CH_LANDESKIRCHE = re.compile(
    r"evangelisch[- ]reformiert|eglise evangeli(?:que|cale)? reformee|eglise reformee (?:du |de |d')?(?:canton|geneve|vaud|neuchatel|berne|fribourg|jura|valais|suisse)"
    r"|\bkirchgemeinde\b|\blandeskirche\b|\bparoisse (?:protestante|reformee)\b"
    r"|\beglise protestante de geneve\b|\bepg\b|\beerv\b|\beers\b|\bfeps\b"
    r"|federation des eglises protestantes|schweizerischer evangelischer kirchenbund"
    r"|\breformierte kirche\b|\breformierte kirchgemeinde\b"
    r"|\bchristkathol|\bchristian catholic|\baltkathol"
    r"|\bevangelisch[- ]methodistisch|\bemk\b")
CH_EVANGELICAL = re.compile(
    r"\bevangelikal\b|\bevangelique(?:s)?(?! reformee)|\beglise(?:s)? libres?\b|\bfreie evangelische|\bfeg\b"
    r"|\bchrischona\b|\bviva kirche\b|\bbewegungplus\b|\bbewegung plus\b"
    r"|\bicf\b|\bvineyard\b|\bbaptiste?\b|\bbaptist\b|\bpfingst|\bpentecot"
    r"|assemblees? de dieu|\breseau evangelique|\bevangelische allianz|\balliance evangelique|\bsea-?res\b"
    r"|\bsalvation army|\barmee du salut|\bheilsarmee\b|\bgospel\b|\bbibel(?:kirche|gemeinde)"
    r"|\bbethaus\b|gemeinde fuer christus|\bcentre chretien\b|\bchristian (?:centre|center|fellowship)\b"
    r"|\bfree church\b|\bchiesa evangelica|\bcentro cristiano\b")
CH_CATHOLIC_NAME = re.compile(
    r"\b(?:kath\.?|katholisch|pfarrei|pfarrkirche|christkonig|christ-roi|lourdes|oratorio|cappella|capella"
    r"|beata vergine|madonna (?:di|del|della|delle)|sacro (?:cuore|monte)|ossario|beinhaus)\b"
    r"|chiesetta|parrocchia|capele?\b")
CH_JW_NAME = re.compile(r"jehovas zeugen|zeugen jehovas|konigreichssaal|koenigreichssaal")
CH_NOT_CONGREGATION = re.compile(
    r"\bfriedhof\b|\bcimetiere\b|\bcemetery\b|krematori|\bspital\b|\bhopital\b|\bhospital\b"
    r"|\bschul(?:haus)?kapelle\b|\bflughafen\b|\bairport\b|\bkathedrale\b|\bcathedral\b|\babtei\b"
    r"|\babdankung|\baufbahrung")
CH_GENERIC_BUILDING = re.compile(
    r"kirche|kapelle|chapel|eglise|chiesa|temple|baselgia|auditoire|kloster|couvent|klosterkirche")
CH_REFORMED_WORD = re.compile(r"reformad|reformiert|refuormad|refurmad|refurmada|evangelisch(?![- ]methodist|[- ]methodistisch)")


def _ch_pass(rec, action, reason):
    """Keep only congregations with clear evangelical evidence. Landeskirchen, wayside chapels and
    untagged parish buildings stay hidden. OSM often tags the Reformed church denomination=evangelical."""
    name = fold(rec.get("name", ""))
    text = f"{name} | {fold(rec.get('denOther', ''))} | {fold(rec.get('network', ''))} | {fold(rec.get('website', ''))}"
    if CH_JW_NAME.search(name):
        return "remove", "jehovahs witnesses (de): " + CH_JW_NAME.search(name).group(0)
    if CH_CATHOLIC_NAME.search(name) and not CH_EVANGELICAL.search(text):
        return "remove", "catholic name (CH): " + CH_CATHOLIC_NAME.search(name).group(0).strip()
    if CH_EVANGELICAL.search(text):
        if action == "remove":
            return action, reason
        return "keep", "swiss evangelical network or vocabulary: " + CH_EVANGELICAL.search(text).group(0).strip()
    den = rec.get("den") or ""
    if den in EVANGELICAL_DEN - {"evangelical"}:
        if action == "remove":
            return action, reason
        return "keep", reason or "tagged evangelical family"
    if action == "remove":
        return action, reason
    if CH_LANDESKIRCHE.search(text) or CH_REFORMED_WORD.search(text) or den in {"reformed", "anglican", "lutheran", "methodist"}:
        return "hidden", "mainline swiss landeskirche / historic Protestant body"
    if CH_NOT_CONGREGATION.search(name) or CH_GENERIC_BUILDING.search(name):
        return "hidden", "uncertain: generic or institutional church building without evangelical evidence (CH)"
    return "hidden", "no swiss evangelical evidence"




# ---- World wave 1 (Nov 19 2026): DE, BE, AU, BR and francophone Africa ---------------------------------------------
# Strict evidence rule, as for Switzerland: a record is kept only with positive evangelical evidence (name, free-text
# denomination, network or website) or an unambiguous evangelical family tag. Germany and Belgium tag the
# Landeskirche / Protestant union "denomination=evangelical", so that tag alone is not evidence there.
WORLD_CCS = {"DE", "BE", "AU", "BR", "CI", "CM", "CD", "SN", "BJ", "TG", "BF", "MG"}
WORLD_AFRICA = {"CI", "CM", "CD", "SN", "BJ", "TG", "BF", "MG"}
WORLD_REMOVE = re.compile(
    # non-Christian or non-Trinitarian / syncretic movements
    r"jehovah|jehova|temoins? de j|salles? (?:du|des) royaumes?|zeugen jehovas|konigreichssaal|testemunhas de jeova|salao do reino"
    r"|celeste|celestial|harriste|kimbangu|eckankar|ekancar|neo[- ]?apostolique|neuapostol|nova apostolica|new apostolic"
    r"|\bmormon|santos dos ultimos dias|derniers jours"
    r"|universal do reino|\biurd\b|igreja universal|^universal$|\bcatolic"
    r"|espirita|spiritis|umbanda|candomble|vodou|vaudou"
    # Catholic markers (fr / pt / de / nl / en / mg)
    r"|\bparoisse\b|\bmonseigneur\b|\bmgr\b|sainte[- ]famille|sacre[- ]coeur|notre[- ]dame|cathedrale|basilique|noviciat|couvent"
    r"|monastere|abbaye|pelerinage|pilgrimage|province ecclesiastique|coeur agonisant|\bsoeurs?\b|\bfreres (?:de|des|hospitaliers)"
    r"|mission catholique|\bcatholi|\bkatholi|\bkath\.|\bpfarr|\bkloster\b|herz[- ]jesu|\bst\.? (?:maria|marien)\b|\bmarien(?:kirche|kapelle)"
    r"|\bparoquia|\bmatriz\b|nossa senhora|\bsantuario|\bcatedral (?:de|da|do|metropolitana|sao)|\bbasilica|capela (?:de |do |da )?(?:sao|santo|santa|nossa)"
    r"|\bsao (?:jose|joao|pedro|paulo|francisco|sebastiao|benedito|judas|jorge|luiz|luis|miguel|antonio|vicente|cristovao)\b"
    r"|\bsanto antonio\b|\bsanta (?:luzia|rita|ana|barbara|clara|terezinha|teresinha|cruz|edwiges|maria|isabel)\b|divino espirito santo"
    r"|^(?:eglise |chapelle |paroisse |temple )?saint(?:e|es|s)?[- ]|stigmates?\b|\bpresbytere\b|\baumonerie\b|spiritain|congregation du saint|\bsint[- ]|\bonze[- ]lieve[- ]vrouw|\bkapel\b|\bparochie|\bkatedraly|\bmasindahy|\bkatolika|\bfiangonana katolika|\bekar\b|jean[- ]baptiste|johann\w*[- ]baptist|joao batista|sao joao"
    r"|^(?:igreja |capela |paroquia |matriz )?(?:de |da |do |dos )?(?:sao|santo|santa|santos|santissim[ao]|nossa senhora|senhor bom jesus|bom jesus|menino jesus|imaculad[ao]|rainha da paz)\b")
WORLD_MAINLINE = re.compile(
    # Germany: EKD Landeskirchen and confessional Lutherans
    r"evangelisch[- ]lutherisch|\bev\.?[- ]?luth|evangelisch[- ]reformiert|\bev\.?[- ]?ref|(?<!landeskirchliche )\bkirchengemeinde\b"
    r"|\bkirchgemeinde\b|(?<!landeskirchliche gemeinschaft )\blandeskirche\b|\bekd\b|\bevangelische kirche\b|\bev\. kirche\b|\bselk\b|altlutherisch"
    r"|evangelisch[- ]methodistisch|\bemk\b|\bevangelische (?:stadt|dorf|pfarr|kreuz|christus|johannes|lukas|markus|paulus|petrus|martin|matthaus)"
    # Belgium: United Protestant Church
    r"|eglise protestante unie|\bepub\b|verenigde protestantse|\bvpkb\b|\bprotestantse kerk\b"
    # Australia
    r"|uniting church|\banglican|\blutheran|\bluther\b"
    # Brazil
    r"|\bluterana\b|\bieclb\b|\bielb\b|\banglicana\b|\bepiscopal anglicana|confissao luterana"
    # Africa / Madagascar: WCC mainline Reformed, Methodist, Lutheran, Anglican bodies
    r"|\bmethodis\w*|\bmetodista\b|\bmetodista unida|eglise evangelique du cameroun|\beec\b|presbyterienne camerounaise|eglise presbyterienne"
    r"|eglise evangelique presbyterienne|\beept\b|\blutherienne|\banglicane|\bfjkm\b|fiangonan.?i jesoa kristy|fiangonan.?i jesosy kristy|eglise de jesus[- ]christ a madagascar"
    r"|\bflm\b|fiangonana loterana|\bloterana\b|\bepiskopaly")
WORLD_EVANGELICAL = re.compile(
    # French (Belgium, Africa)
    r"evangeli(?:que|cal|ste|sation)|assembl\w* de dieu|\bad\b|\badd\b|pentec|baptist|\bcma\b|alliance chretienne|alliance evangelique"
    r"|plein evangile|deeper life|rachetes? de dieu|redeemed|winners?'?s? chapel|lighthouse chapel|impact centre chretien|\bicc\b|\bcmci\b"
    r"|foursquare|quadrangulaire|vie abondante|\breveil\b|nazareen|armee du salut|salvation army|\bcepac\b|\bcbco\b|\bcbca\b|\bcbc\b|\bfepaco\b|\bcbfc\b|\bfemec\b"
    r"|communaute (?:baptiste|evangelique|pentecotiste|des eglises (?:baptistes|evangeliques|pentecotistes|libres))|eglise (?:de dieu|apostolique)"
    r"|eglise libre|eglises? chretiennes? (?:evangelique|biblique)|mission evangelique|centre chretien|eglise biblique|tabernacle"
    r"|ministere (?:evangelique|chretien|international)|eglise du christ (?:roi )?(?:ministere|international)|vineyard|hillsong|calvary chapel"
    # Dutch (Belgium)
    r"|evangelische (?:kerk|gemeente)|evangelisch(?:e)? (?:christen)?gemeente|pinkster|vrije evangelische|volle evangelie|christengemeente"
    r"|\bvbeg\b|\bfeb\b|\bseb\b|baptistenkerk"
    # German
    r"|freikirch|evangelikal|evangelisch[- ]freikirchlich|\befg\b|\bfeg\b|freie evangelische|baptisten|pfingst|\bbfp\b|mulheimer|muelheimer"
    r"|volksmission|christliches zentrum|christus[- ]zentrum|gemeinde gottes|\belim\b|\bicf\b|gospel|biblische|bibelgemeinde|bru(?:e)?dergemeinde"
    r"|mennonit|freie christengemeinde|evangeliums[- ]?christen|landeskirchliche gemeinschaft|evangelische gemeinschaft|\bev\. gemeinschaft"
    r"|stadtmission|heilsarmee|calvary|foursquare|nazarener|apostolische kirche|jesus[- ]gemeinde|christengemeinde"
    # English (Australia)
    r"|evangelical|pentecostal|assembl(?:y|ies) of god|\bacc\b|australian christian churches|\bc3\b|planetshakers|\bcrc\b|christian revival"
    r"|churches? of christ|christian (?:city )?church|christian (?:centre|center)|christian fellowship|community church|bible church"
    r"|life church|new life|apostolic church|wesleyan|reformed baptist|free reformed|christian reformed|presbyterian church of (?:eastern )?australia"
    # Portuguese (Brazil)
    r"|evangelic|assembleia de deus|\bad\b|batista|quadrangular|pentecost|presbiteriana|congregacional|bola de neve|lagoinha|videira|\bccb\b"
    r"|sara nossa terra|renascer|comunidade (?:evangelica|crista)|maranata|congregacao crista|deus e amor|evangelho|internacional da graca"
    r"|apostolica|brasil para cristo|igreja de deus|nova vida|ministerio|avivamento|\bcristo vive|igreja crista"
    # Malagasy
    r"|pentekotista|batista|fifohazana|apokalypsy|jesosy mamonjy|\brhema\b|ara-pilazantsara|\bfaa\b|assemblees de dieu")
WORLD_TAG_EVANGELICAL = EVANGELICAL_DEN - {"evangelical"}
# In Germany an English name ("… Church", "… Chapel") is a free church / international congregation.
WORLD_DE_ENGLISH = re.compile(r"\bchurch\b|\bchapel\b|\bministries\b")


SAINT_BAPTIST = re.compile(r"(?:\bsaint|\bsint|\bst\.?|\bsan|\bsao|\bjohann\w*|\bjean|\bjohn(?: the)?|\bjoao)[- ]+(?:(?:jan|jean|john|joao|johannes)[- ]+)?(?:the[- ]+)?(?:baptist\w*|batista)")


# Shared-vocabulary words that are not evidence on their own in these countries: "igreja" / "templo" is any church in
# Brazil, "protestant" there and in Australia / Madagascar is mostly the historic (mainline) churches.
WORLD_WEAK = {
    "BR": re.compile(r"^(?:igreja|templo|temple|cristiana?|protestant\w*|reformed|reformee?s?|lutheri\w*|lutheran|methodist)$"),
    "AU": re.compile(r"^(?:protestant\w*|temple|reformed|lutheri\w*|lutheran|methodist)$"),
    "MG": re.compile(r"^(?:protestant\w*|reformee?s?|lutheri\w*|lutheran|methodist)$"),
}


def _world_text_evidence(text, cc):
    weak = WORLD_WEAK.get(cc)
    for m in EVANGELICAL_TEXT.finditer(text):
        if not weak or not weak.match(m.group(0).strip()):
            return m
    return None


def _world_pass(rec, action, reason):
    """Strict evidence rule for the wave 1 countries (see WORLD_* above)."""
    cc = rec.get("cc") or ""
    name = fold(rec.get("name", ""))
    text = f"{name} | {fold(rec.get('denOther', ''))} | {fold(rec.get('network', ''))}"
    web = fold(rec.get("website", ""))
    if action == "remove":
        return action, reason
    # "St John the Baptist", "Sint-Jan Baptist", "Jean-Baptiste": a saint's name, not Baptist evidence.
    text = SAINT_BAPTIST.sub(" ", text)
    name = SAINT_BAPTIST.sub(" ", name)
    if (rec.get("den") or "") == "catholic" and not re.search(r"evangeli|freikirch|pentec|pfingst|assemble", name):
        return "remove", f"tagged catholic ({cc})"
    m = WORLD_REMOVE.search(text)
    if m and not re.search(r"evangeli|baptist|batista|pentec|assemble", name):
        return "remove", f"non-evangelical body or Catholic name ({cc}): " + m.group(0).strip()
    if reason == "adventist" or ADVENTIST_TEXT.search(text):
        return "hidden", f"adventist ({cc})"
    m = WORLD_MAINLINE.search(text)
    if m and not re.search(r"freikirch|evangelikal|landeskirchliche gemeinschaft|baptist|pentec|pfingst", text):
        return "hidden", f"mainline body ({cc}): " + m.group(0).strip()
    # Germany / Belgium: "evangelisch" and "protestant" name the Landeskirche / EPUB, so the shared French-English
    # vocabulary (EVANGELICAL_TEXT) is not evidence there; only the WORLD_EVANGELICAL free-church vocabulary is.
    m = WORLD_EVANGELICAL.search(text) or (cc not in {"DE", "BE"} and _world_text_evidence(text, cc)) or EVIDENCE_WEB.search(web) \
        or (cc == "DE" and WORLD_DE_ENGLISH.search(name))
    if m:
        return "keep", f"evangelical evidence ({cc}): " + m.group(0).strip()
    den = rec.get("den") or ""
    if den in WORLD_TAG_EVANGELICAL:
        return "keep", f"tagged {den} ({cc})"
    if den == "evangelical" and cc not in {"DE", "BE"}:
        return "keep", f"tagged evangelical ({cc})"
    if den in PROTESTANT_DEN:
        return "hidden", f"mainline body ({cc}): tagged {den}"
    return "hidden", f"uncertain: no evangelical evidence ({cc})"


def classify(rec):
    if rec.get("cc") == "GB":
        if re.search(r"\bjohn(?:'?s)? the baptist\b", fold(rec.get("name", ""))):
            rec = dict(rec, name=re.sub(r"(?i)\bjohn(?:'?s)? the baptist\b", "John", rec.get("name", "")))
        return _uk_pass(rec, *_classify(rec))
    if rec.get("cc") == "CA":
        return _ca_pass(rec, *_classify(rec))
    if rec.get("cc") == "CH":
        return _ch_pass(rec, *_classify(rec))
    if rec.get("cc") in WORLD_CCS:
        return _world_pass(rec, *_classify(rec))
    return _classify(rec)


def _classify(rec):
    """(remove | hidden | keep, reason) for one directory record (dict with name, den, denOther, network, cc, postcode, src).

    hidden: kept in the data (public/osm/h/), off the map, lists, directory, SEO pages and sitemap; shown again once a
    leader's claim is accepted with the charter checkbox ticked (src/nexus/evangelical.ts, isListable).
    """
    rec_id = rec.get("id") or rec.get("osmId") or ""
    if rec_id in CLOSED_IDS:
        return "remove", "closed: " + CLOSED_IDS[rec_id].get("why", rec_id)
    action, reason = _first_pass(rec)
    if action != "remove":
        name = fold(rec.get("name", ""))
        if RUIN_NAME.search(name):
            return "remove", "ruin / abandoned building, not a church"
        if rec.get("cc") == "FR" and UEPAL_NAME.search(name):
            return "hidden", "mainline body: UEPAL parish council (Alsace-Moselle)"
    if action == "keep":
        return _evidence_pass(rec, reason)
    if action != "review":
        return action, reason
    name = fold(rec.get("name", ""))
    other = fold(rec.get("denOther", ""))
    text = f"{name} | {other} | {fold(rec.get('network', ''))}"
    plain = SAINT_WORDS.sub(" ", name)
    if reason.startswith("oneness"):
        return "remove", reason
    if reason.startswith("other tradition") or reason.startswith("unlisted denomination") or reason.startswith("mainline body"):
        m = NONTRINITARIAN_OTHER.search(text)
        # A US "Apostolic Christian / Apostolic Faith" church with a stray New Apostolic tag: hidden, not removed.
        stray = m and "apostolic" in m.group(0) and not re.search(r"new apostolic|neuapostol|neo[- ]?apostolique", name)
        if m and not stray and not (m.group(0) == "unitarian" and "episcopal" in text):
            return "remove", "non-Trinitarian body: " + m.group(0)
    if reason.startswith("unlisted denomination"):
        if other in NONTRINITARIAN_DEN_OTHER:
            return "remove", f"non-Trinitarian body: '{rec.get('denOther', '')}'"
        if other in EVANGELICAL_DEN_OTHER:
            return _evidence_pass(rec, f"evangelical family (denomination '{rec.get('denOther', '')}')")
    if reason == "mainline body: quaker" and re.search(r"\bseminaire\b", name):
        # Larressore: the former Catholic seminary carries a stray denomination=quaker tag.
        return "remove", "former Catholic seminary (stray quaker tag)"
    if reason.startswith("mixed signals") or (reason.startswith("tagged ") and "the name reads" in reason):
        if ORTHODOX_TEXT.search(name) and re.search(r"armenian apostolic|apostolique armenienne", name):
            return "remove", "orthodox name: armenian apostolic"
        if STRONG_PROTESTANT_TEXT.search(plain) and not re.search(r"catholi", name) and not (
                ORTHODOX_TEXT.search(name) and ETHNIC_ORTHODOX_TEXT.search(name)):
            return _evidence_pass(rec, reason.replace("the name reads", "a Protestant name with") + " (keep)")
        if ORTHODOX_TEXT.search(name) and ETHNIC_ORTHODOX_TEXT.search(name) and not STRONG_PROTESTANT_TEXT.search(
                re.sub(r"\bjohns? baptist\b", " ", plain)):
            return "remove", "orthodox name: " + reason
        if re.search(r"catholi", name) or (reason.startswith("tagged ") and not re.search(r"episcopal|anglican", name) and CATHOLIC_TEXT.search(
                re.sub(r"\b(?:paroiss\w*|parish|sanctuaire|sanctuary)\b", " ", name)) and not (
                rec.get("cc") == "FR" and LUTHERAN_SAINT_POSTCODES.search(rec.get("postcode", "") or ""))):
            return "remove", "catholic name: " + reason
    if reason.startswith("untagged saint") and CATHEDRAL_EVANGELICAL.search(name) and not re.search(
            r"^(?:the )?(?:saint|st|sts|san|santa)\b|\b(?:saint|st)\.? [a-z]|christ church|trinity|\bcross\b|chapel", name):
        return _evidence_pass(rec, "evangelical-style cathedral name")
    return "hidden", reason
