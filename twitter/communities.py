"""/twitter/communities/* — a community's card and its top posts, both from
the logged-out community page X server-renders (the page carries the
community metadata in its router loader data and the "Top" timeline, 20
posts ranked by likes, in the Relay store). `community` is the resolved id."""
from twitter import parsers as P
from twitter import relay, shared
from twitter.fetch import TwitterNotFound


def _page(community):
    records, matches = shared.ssr_page(f"/i/communities/{community}", f"community {community} page")
    loader = shared.loader_of(matches, "communities")
    root = relay.root(records)
    result = (root.get("community_results_by_rest_id") or {}).get("result") or {}
    if not loader and not result:
        raise TwitterNotFound(f"community {community} not found")
    return loader, result


def details(community):
    loader, result = _page(community)
    card = P.community(loader, result)
    if not card.get("name"):
        raise TwitterNotFound(f"community {community} not found")
    return {"community": card}


def tweets(community, count=20):
    """The community's top posts (X's "Top" tab, ranked by likes)."""
    loader, result = _page(community)
    timeline = result.get("ranked_community_timeline") or {}
    walk = P.walk_timeline(timeline)
    rows = walk["tweets"][:count]
    card = P.community(loader, result)
    return {
        "community": {k: card.get(k) for k in ("id", "name", "link", "members_count")},
        "count": len(rows),
        "has_more": False,
        "sort": "top",
        "tweets": rows,
    }
