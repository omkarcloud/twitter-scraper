"""/twitter/trends* and the small open reference tables: trends by place
(WOEID / country code / place name), the trend locations list, active
hashflag campaigns and place search."""
from twitter import parsers as P
from twitter import shared
from twitter.fetch import TwitterBadRequest, TwitterNotFound, rest

TABLE_TTL = 6 * 3600
WORLDWIDE = 1


def _available():
    """[trend_location, …] memoised (the table changes a few times a year)."""
    def build():
        body = rest("/1.1/trends/available.json", label="trend locations")
        return [P.trend_location(r) for r in (body if isinstance(body, list) else [])]
    return shared.memo("trend_locations", TABLE_TTL, build)


def resolve_location(value):
    """'1' | '23424848' (WOEID) | 'IN' | 'india' | 'new york' -> a location
    row. Countries win over cities on a name clash."""
    raw = str(value or "").strip()
    if not raw or raw.lower() in ("worldwide", "world", "global"):
        raw = str(WORLDWIDE)
    rows = _available()
    if raw.isdigit():
        woeid = int(raw)
        for row in rows:
            if row["woeid"] == woeid:
                return row
        raise TwitterBadRequest(f"WOEID {woeid} is not a trend location (see /twitter/trends/locations)")
    low = raw.lower()
    if len(low) == 2 and low.isalpha():
        for row in rows:
            if (row["country_code"] or "").lower() == low and row["type"] == "Country":
                return row
    exact = [r for r in rows if (r["name"] or "").lower() == low]
    if exact:
        exact.sort(key=lambda r: r["type"] != "Country")
        return exact[0]
    partial = [r for r in rows if low in (r["name"] or "").lower()]
    if partial:
        partial.sort(key=lambda r: (r["type"] != "Country", len(r["name"] or "")))
        return partial[0]
    raise TwitterBadRequest(f"'{value}' matches no trend location (a WOEID, a country code like IN, "
                            "or a place name from /twitter/trends/locations)")


def trends(location="1", exclude_hashtags=None):
    """The top 50 trends for a place, with post volumes where X reports them."""
    place = resolve_location(location)
    params = {"id": place["woeid"]}
    if exclude_hashtags:
        params["exclude"] = "hashtags"
    body = rest("/1.1/trends/place.json", params, label=f"trends {place['woeid']}")
    block = body[0] if isinstance(body, list) and body else {}
    rows = [P.trend(t) for t in (block.get("trends") or [])]
    if not rows and not block:
        raise TwitterNotFound(f"no trends for {place['name']}")
    return {
        "location": place,
        "as_of": P.iso_datetime(block.get("as_of")),
        "count": len(rows),
        "trends": rows,
    }


def locations(query=None):
    """Every place X reports trends for (WOEIDs), optionally filtered by
    name / country / country code."""
    rows = _available()
    if query:
        low = query.lower()
        rows = [r for r in rows if low in (r["name"] or "").lower() or low in (r["country"] or "").lower()
                or low == (r["country_code"] or "").lower()]
    return {"count": len(rows), "locations": rows}


def hashflags():
    """Active hashtag emoji campaigns (hashflags) and their date windows."""
    body = rest("/1.1/hashflags.json", label="hashflags")
    rows = [P.hashflag(r) for r in (body if isinstance(body, list) else []) if isinstance(r, dict)]
    rows = [r for r in rows if r["hashtag"]]
    return {"count": len(rows), "hashflags": rows}


def places(query):
    """Places X knows by name (the geo search behind post location tags)."""
    body = rest("/1.1/geo/search.json", {"query": query}, label=f"places {query}")
    result = (body or {}).get("result") if isinstance(body, dict) else {}
    rows = [P.geo_place(p) for p in ((result or {}).get("places") or [])]
    return {"query": query, "count": len(rows), "places": rows}
