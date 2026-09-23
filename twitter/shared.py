"""Lookups and helpers shared by the /twitter/* endpoint modules: username
<-> numeric id resolution, the SSR page loaders, one generic "GraphQL
timeline -> page" helper and the in-process memo (ids never change)."""
import threading
import time

from twitter import parsers as P
from twitter import relay
from twitter.fetch import TwitterLoginWalled, TwitterNotFound, graphql, page, rest

ID_TTL = 24 * 3600
_lock = threading.Lock()
_memo = {}


def memo(key, ttl, build):
    now = time.time()
    with _lock:
        hit = _memo.get(key)
        if hit and hit[0] > now:
            return hit[1]
    value = build()
    with _lock:
        _memo[key] = (now + ttl, value)
    return value


def remember(key, ttl, value):
    with _lock:
        _memo[key] = (time.time() + ttl, value)


# ---- users ---------------------------------------------------------------------------

def user_result(screen_name):
    """The raw GraphQL User result for a username (guest). NotFound for a
    missing / suspended account."""
    data = graphql("UserByScreenName", {"screen_name": screen_name, "withGrokTranslatedBio": False},
                   label=f"user @{screen_name}")
    result = (data.get("user") or {}).get("result") if isinstance(data, dict) else None
    if not isinstance(result, dict) or not result:
        raise TwitterNotFound(f"user @{screen_name} not found")
    if result.get("__typename") == "UserUnavailable":
        reason = result.get("reason") or (result.get("message") or "unavailable")
        raise TwitterNotFound(f"user @{screen_name} is unavailable ({reason})")
    if not result.get("rest_id"):
        raise TwitterNotFound(f"user @{screen_name} not found")
    remember(("id", screen_name.lower()), ID_TTL, result["rest_id"])
    remember(("name", result["rest_id"]), ID_TTL, (result.get("core") or {}).get("screen_name") or screen_name)
    return result


def screen_name_of(ref):
    """{"screen_name"} | {"user_id"} -> the username. A bare id is resolved
    through friendships/show (which echoes the source's screen_name and is
    open to guests)."""
    if ref.get("screen_name"):
        return ref["screen_name"]
    user_id = ref["user_id"]

    def build():
        body = rest("/1.1/friendships/show.json", {"source_id": user_id, "target_screen_name": "X"},
                    label=f"user id {user_id}")
        source = ((body or {}).get("relationship") or {}).get("source") or {}
        name = source.get("screen_name")
        if not name:
            raise TwitterNotFound(f"user id {user_id} not found")
        return name
    try:
        return memo(("name", user_id), ID_TTL, build)
    except TwitterNotFound:
        raise
    except Exception:
        raise TwitterNotFound(f"user id {user_id} not found")


def user_id_of(ref):
    """{"screen_name"} | {"user_id"} -> the numeric id (profile call memoised)."""
    if ref.get("user_id"):
        return ref["user_id"]
    name = ref["screen_name"]
    return memo(("id", name.lower()), ID_TTL, lambda: user_result(name)["rest_id"])


def user_label(ref):
    return f"@{ref['screen_name']}" if ref.get("screen_name") else f"user id {ref.get('user_id')}"


# ---- SSR pages -------------------------------------------------------------------------

def ssr_page(path, label):
    """Fetch one logged-out page -> (relay records, router matches). Raises
    NotFound when the page carried no Relay store (unknown user / post /
    community, or a path X serves as the empty SPA shell)."""
    html, final = page(path, label=label)
    records = relay.page_records(html)
    matches = relay.router_matches(html)
    if not records:
        if "/i/flow/login" in (final or "") or "/i/jf/" in (final or ""):
            raise TwitterLoginWalled(f"{label}: X asks for a login on this page")
        raise TwitterNotFound(f"{label}: not found")
    return records, matches


def loader_of(matches, needle):
    """The first router match whose route id contains `needle` and has
    loader data."""
    for match in matches:
        route = str(match.get("i") or "")
        if needle in route and isinstance(match.get("l"), dict) and match["l"]:
            return match["l"]
    return {}


# ---- timelines -----------------------------------------------------------------------

def find_instructions(node, depth=0):
    """Depth-first search for the first {"instructions": [...]} block in a
    GraphQL response (each operation nests its timeline differently)."""
    if depth > 8:
        return None
    if isinstance(node, dict):
        if isinstance(node.get("instructions"), list):
            return node
        for value in node.values():
            found = find_instructions(value, depth + 1)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = find_instructions(value, depth + 1)
            if found is not None:
                return found
    return None


def timeline_page(operation, variables, *, label=None):
    """One page of a guest GraphQL timeline -> {"count", "items",
    "next_cursor", "has_more"}."""
    data = graphql(operation, variables, label=label or operation)
    timeline = find_instructions(data)
    walk = P.walk_timeline(timeline or {})
    items = walk["tweets"]
    cursor = walk["cursors"]["bottom"]
    has_more = bool(cursor) and bool(items)
    return {"count": len(items), "items": items, "next_cursor": cursor if has_more else None,
            "has_more": has_more}
