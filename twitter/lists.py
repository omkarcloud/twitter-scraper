"""/twitter/lists/* — a list's metadata (open 1.1 lists/show) and its
latest posts (the syndication list widget, ~80 posts, no cursor). `list` is
the resolved ref: {"list_id"} or {"slug", "owner"}."""
from twitter import parsers as P
from twitter import shared
from twitter.fetch import TwitterNotFound, rest, syndication_list

ID_TTL = 24 * 3600


def _raw(lst):
    if lst.get("list_id"):
        params = {"list_id": lst["list_id"]}
        label = f"list {lst['list_id']}"
    else:
        params = {"slug": lst["slug"], "owner_screen_name": lst["owner"]}
        label = f"list @{lst['owner']}/{lst['slug']}"
    try:
        body = rest("/1.1/lists/show.json", params, label=label)
    except TwitterNotFound:
        raise TwitterNotFound(f"{label} not found")
    if not isinstance(body, dict) or not body.get("id_str"):
        raise TwitterNotFound(f"{label} not found")
    return body


def _list_id(lst):
    if lst.get("list_id"):
        return lst["list_id"]
    key = ("list_id", lst["owner"].lower(), lst["slug"].lower())
    return shared.memo(key, ID_TTL, lambda: _raw(lst)["id_str"])


def details(list):  # noqa: A002 — public param name
    return {"list": P.twitter_list(_raw(list))}


def tweets(list, count=50):  # noqa: A002 — public param name
    """The list's latest posts (newest first)."""
    list_id = _list_id(list)
    props = syndication_list(list_id)
    entries = ((props.get("timeline") or {}).get("entries") or [])
    rows = []
    for entry in entries:
        raw = ((entry or {}).get("content") or {}).get("tweet")
        parsed = P.tweet(raw) if isinstance(raw, dict) else None
        if parsed and parsed.get("id"):
            rows.append(parsed)
    header = P.list_header(props.get("headerProps"))
    header = dict(header, id=list_id, link=P.refs.list_link(list_id))
    return {"list": header, "count": min(len(rows), count), "has_more": False,
            "tweets": rows[:count]}
