# TRMNL Serverless function (Python) for the "Philly Sports" private plugin.
# Fetches ESPN schedules for the Eagles, Phillies, Flyers and 76ers and returns
# a compact, pre-formatted payload for the Liquid markup.

import requests
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta, tzinfo
from zoneinfo import ZoneInfo

ESPN = "https://site.api.espn.com/apis/site/v2/sports"

TEAMS = [
    {"key": "eagles",   "name": "Eagles",   "path": "football/nfl"},
    {"key": "phillies", "name": "Phillies", "path": "baseball/mlb"},
    {"key": "flyers",   "name": "Flyers",   "path": "hockey/nhl"},
    {"key": "sixers",   "name": "76ers",    "path": "basketball/nba"},
]

DEFAULT_TZ = "America/New_York"


def get_json(url, params=None):
    try:
        r = requests.get(url, params=params, timeout=4)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


def parse_date(s):
    # ESPN dates look like "2026-10-27T00:15Z" or "2026-10-27T00:15:00Z"
    s = s.replace("Z", "+00:00")
    if len(s) == len("2026-10-27T00:15+00:00"):
        s = s.replace("+00:00", ":00+00:00")
    return datetime.fromisoformat(s)


def pick_logo(team):
    logos = team.get("logos") or []
    for l in logos:
        if "scoreboard" in l.get("rel", []) and "dark" not in l.get("rel", []):
            return l["href"]
    if logos:
        return logos[0]["href"]
    return team.get("logo", "")


def score_of(c):
    s = c.get("score")
    if isinstance(s, dict):
        return s.get("displayValue", "")
    return s or ""


def split(comp):
    """Return (phi, opp) competitor dicts for a competition."""
    cs = comp.get("competitors", [])
    phi = next((c for c in cs if c.get("team", {}).get("abbreviation") == "PHI"), cs[0] if cs else {})
    opp = next((c for c in cs if c is not phi), {})
    return phi, opp


def fmt_day(dt, now):
    d = dt.date()
    if d == now.date():
        return "Today"
    if d == now.date() + timedelta(days=1):
        return "Tomorrow"
    if d == now.date() - timedelta(days=1):
        return "Yesterday"
    return dt.strftime("%a %-m/%-d")


def fmt_time(dt):
    return dt.strftime("%-I:%M %p")


def tv_of(comp):
    casts = comp.get("broadcasts") or []
    national = [b for b in casts if b.get("market", {}).get("type") == "National"]
    home = [b for b in casts if b.get("market", {}).get("type") == "Home"]
    for b in national + home + casts:
        name = (b.get("media") or {}).get("shortName") or ""
        if name:
            return name
    return ""


def opp_info(comp, tz):
    phi, opp = split(comp)
    ot = opp.get("team", {})
    return {
        "opp": ot.get("abbreviation", "TBD"),
        "opp_name": ot.get("shortDisplayName") or ot.get("nickname") or ot.get("displayName", ""),
        "opp_logo": pick_logo(ot),
        "ha": "vs" if phi.get("homeAway") == "home" else "@",
    }, phi, opp


def summarize_last(event, tz, now):
    comp = event["competitions"][0]
    info, phi, opp = opp_info(comp, tz)
    us, them = score_of(phi), score_of(opp)
    if phi.get("winner"):
        result = "W"
    elif opp.get("winner"):
        result = "L"
    else:
        result = "T"
    detail = comp.get("status", {}).get("type", {}).get("shortDetail", "Final")
    extra = detail.split("/", 1)[1] if "/" in detail else ""  # OT, SO, 10, ...
    dt = parse_date(event["date"]).astimezone(tz)
    info.update({
        "result": result,
        "us": us,
        "them": them,
        "extra": extra,
        "date": fmt_day(dt, now),
    })
    return info


def summarize_live(event, tz):
    comp = event["competitions"][0]
    info, phi, opp = opp_info(comp, tz)
    info.update({
        "us": score_of(phi),
        "them": score_of(opp),
        "clock": comp.get("status", {}).get("type", {}).get("shortDetail", "Live"),
    })
    return info


def summarize_next(event, tz, now):
    comp = event["competitions"][0]
    info, _, _ = opp_info(comp, tz)
    dt = parse_date(event["date"]).astimezone(tz)
    time_valid = event.get("timeValid", comp.get("timeValid", True))
    stype = (event.get("seasonType") or {}).get("type")
    if stype == 1:
        label = "Preseason"
    elif stype == 3:
        label = "Playoffs"
    else:
        label = "Next game"
    # Far-off games (off-season) read better with a full date
    if (dt - now).days > 30:
        date = dt.strftime("%a %b %-d")
    else:
        date = fmt_day(dt, now)
    info.update({
        "label": label,
        "date": date,
        "time": fmt_time(dt) if time_valid else "TBD",
        "tv": tv_of(comp),
    })
    return info


def events_of(sched):
    evs = sched.get("events") or []
    return sorted(evs, key=lambda e: e.get("date", ""))


def state(e):
    return e["competitions"][0].get("status", {}).get("type", {}).get("state")


def completed(e):
    t = e["competitions"][0].get("status", {}).get("type", {})
    return t.get("state") == "post" and t.get("completed")


def build_team(t, tz, now):
    base = f"{ESPN}/{t['path']}/teams/phi"
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_sched = ex.submit(get_json, base + "/schedule")
        f_team = ex.submit(get_json, base)
        sched, team = f_sched.result(), f_team.result().get("team", {})

    events = events_of(sched)
    done = [e for e in events if completed(e)]

    # Between season phases (e.g. postseason started but PHI hasn't played,
    # or a new season with no games yet) fall back to earlier schedules.
    if not done:
        year = (sched.get("requestedSeason") or sched.get("season") or {}).get("year") or now.year
        for season, stype in ((year, 2), (year - 1, 3), (year - 1, 2)):
            older = events_of(get_json(base + "/schedule", {"season": season, "seasontype": stype}))
            done = [e for e in older if completed(e)]
            if done:
                break

    live = next((e for e in events if state(e) == "in"), None)
    upcoming = [e for e in events if state(e) == "pre" and parse_date(e["date"]) > now]
    nxt = upcoming[0] if upcoming else None
    if nxt is None:
        # Off-season: ESPN's team endpoint knows the next scheduled game
        # (e.g. spring training or the season opener) even when the
        # current schedule doesn't.
        ne = (team.get("nextEvent") or [None])[0]
        if ne and ne["competitions"][0].get("status", {}).get("type", {}).get("state") == "pre":
            nxt = ne

    sched_team = sched.get("team", {})
    record = ""
    items = (team.get("record") or {}).get("items") or []
    if items:
        record = items[0].get("summary", "")
        # NHL summaries omit overtime losses (W-L only); add them back as W-L-OTL
        stats = {s.get("name"): s.get("value") for s in items[0].get("stats", [])}
        if t["path"].endswith("nhl") and stats.get("otLosses") is not None:
            record = f"{int(stats.get('wins', 0))}-{int(stats.get('losses', 0))}-{int(stats['otLosses'])}"
    record = record or sched_team.get("recordSummary", "")

    return {
        "key": t["key"],
        "name": t["name"],
        "league": t["path"].split("/")[1].upper(),
        "logo": pick_logo(team) or sched_team.get("logo", ""),
        "record": record,
        "standing": team.get("standingSummary") or sched_team.get("standingSummary", ""),
        "last": summarize_last(done[-1], tz, now) if done else None,
        "live": summarize_live(live, tz) if live else None,
        "next": summarize_next(nxt, tz, now) if nxt else None,
    }


class Eastern(tzinfo):
    """US Eastern fallback for runtimes without the IANA time zone database."""

    def _dst(self, dt):
        y = dt.year
        # 2nd Sunday in March to 1st Sunday in November, 2 AM local
        start = datetime(y, 3, 8 + (6 - datetime(y, 3, 8).weekday()) % 7, 2)
        end = datetime(y, 11, 1 + (6 - datetime(y, 11, 1).weekday()) % 7, 2)
        return start <= dt.replace(tzinfo=None) < end

    def utcoffset(self, dt):
        return timedelta(hours=-4) if self._dst(dt) else timedelta(hours=-5)

    def dst(self, dt):
        return timedelta(hours=1) if self._dst(dt) else timedelta(0)

    def tzname(self, dt):
        return "EDT" if self._dst(dt) else "EST"

    def fromutc(self, dt):
        # DST runs 2 AM EST (07:00 UTC) in March to 2 AM EDT (06:00 UTC) in November
        utc = dt.replace(tzinfo=None)
        y = utc.year
        start = datetime(y, 3, 8 + (6 - datetime(y, 3, 8).weekday()) % 7, 7)
        end = datetime(y, 11, 1 + (6 - datetime(y, 11, 1).weekday()) % 7, 6)
        offset = timedelta(hours=-4) if start <= utc < end else timedelta(hours=-5)
        return (utc + offset).replace(tzinfo=self)


def get_tz(input):
    name = DEFAULT_TZ
    try:
        name = input["trmnl"]["user"]["time_zone_iana"] or DEFAULT_TZ
    except Exception:
        pass
    for candidate in (name, DEFAULT_TZ):
        try:
            return ZoneInfo(candidate)
        except Exception:
            pass
    return Eastern()


def safe_build(t, tz, now):
    try:
        return build_team(t, tz, now)
    except Exception as e:
        return {"key": t["key"], "name": t["name"], "league": t["path"].split("/")[1].upper(),
                "logo": "", "record": "", "standing": f"Error: {e}"[:60],
                "last": None, "live": None, "next": None}


def run(input):
    tz = get_tz(input or {})
    now = datetime.now(timezone.utc).astimezone(tz)

    with ThreadPoolExecutor(max_workers=4) as ex:
        teams = list(ex.map(lambda t: safe_build(t, tz, now), TEAMS))

    return {
        "teams": teams,
        "updated_at": now.strftime("%a %-m/%-d %-I:%M %p"),
    }
