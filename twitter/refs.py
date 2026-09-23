"""X / Twitter reference parsing: ONE param per input that auto-detects
its forms (tripadvisor QueryOrIdField convention — never a sibling
`url`/`id` pair).

  user       elonmusk | @elonmusk | https://x.com/elonmusk | twitter.com/elonmusk/with_replies
             | 44196397 (a numeric user id) | https://x.com/i/user/44196397
             -> {"screen_name": "elonmusk"} or {"user_id": "44196397"}
  tweet      2102207241101144450 | https://x.com/elonmusk/status/2102207241101144450
             | x.com/i/web/status/<id> | mobile.twitter.com/.../status/<id>/photo/1
             -> "2102207241101144450"
  list       1343798673386434560 | https://x.com/i/lists/1343798673386434560
             | https://x.com/nelligan_14/lists/marvel-star-wars-34765
             -> {"list_id": "..."} or {"slug": "...", "owner": "..."}
  community  1601841656147345410 | https://x.com/i/communities/1601841656147345410
             -> "1601841656147345410"

Hosts accepted for links: x.com, twitter.com, mobile.twitter.com and the
common mirror front-ends (fxtwitter, vxtwitter, fixupx, nitter.*) since
they keep X's path layout.
"""
import re
from urllib.parse import urlparse

SITE = "https://x.com"

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_ID_RE = re.compile(r"^\d{1,25}$")
_SLUG_RE = re.compile(r"^[A-Za-z0-9_\-]{1,100}$")
_HOSTS = ("x.com", "twitter.com", "fxtwitter.com", "vxtwitter.com", "fixupx.com", "fixvx.com",
          "twittpr.com", "nitter.net")
_RESERVED = {"i", "home", "explore", "search", "settings", "messages", "notifications", "login",
             "signup", "hashtag", "intent", "share", "compose", "jobs", "tos", "privacy", "about",
             "download", "account", "who_to_follow", "lists", "communities", "topics", "status"}


def _is_link(value):
    low = value.lower()
    return low.startswith(("http://", "https://", "//")) or any(
        low.startswith(h + "/") or low.startswith("www." + h + "/") or low.startswith("mobile." + h + "/")
        for h in _HOSTS)


def _parts(value, what):
    url = value
    if url.startswith("//"):
        url = "https:" + url
    elif not url.lower().startswith("http"):
        url = "https://" + url
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not any(host == h or host.endswith("." + h) for h in _HOSTS):
        raise ValueError(f"'{value}' is not an x.com / twitter.com link ({what})")
    return [s for s in parsed.path.split("/") if s]


# ---- users --------------------------------------------------------------------------

def resolve_user(value):
    """-> {"screen_name": ...} or {"user_id": ...}."""
    raw = (value or "").strip()
    if not raw:
        raise ValueError("user is required")
    if _is_link(raw):
        segments = _parts(raw, "user")
        if len(segments) >= 3 and segments[0] == "i" and segments[1] == "user" and _ID_RE.match(segments[2]):
            return {"user_id": segments[2]}
        if segments and segments[0].lower() not in _RESERVED and _USERNAME_RE.match(segments[0]):
            return {"screen_name": segments[0]}
        raise ValueError(f"'{value}' is not a profile link (expected x.com/<username>)")
    raw = raw.lstrip("@")
    if _ID_RE.match(raw) and len(raw) >= 5:
        return {"user_id": raw}
    if _USERNAME_RE.match(raw):
        return {"screen_name": raw}
    raise ValueError(f"'{value}' is not an X username, user id or profile link")


def resolve_users(value, limit=20):
    """Comma-separated usernames / ids / links -> list of resolve_user dicts."""
    out, seen = [], set()
    for raw in str(value or "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        ref = resolve_user(raw)
        key = tuple(sorted(ref.items()))
        if key not in seen:
            seen.add(key)
            out.append(ref)
    if not out:
        raise ValueError("at least one user is required")
    if len(out) > limit:
        raise ValueError(f"at most {limit} users per call")
    return out


def username_of(ref):
    return ref.get("screen_name")


def user_link(screen_name):
    return f"{SITE}/{screen_name}" if screen_name else None


# ---- tweets -------------------------------------------------------------------------

def resolve_tweet(value):
    raw = (value or "").strip()
    if not raw:
        raise ValueError("tweet is required")
    if _is_link(raw):
        segments = _parts(raw, "tweet")
        for i, seg in enumerate(segments):
            if seg == "status" and i + 1 < len(segments) and _ID_RE.match(segments[i + 1]):
                return segments[i + 1]
        raise ValueError(f"'{value}' is not a post link (expected x.com/<user>/status/<id>)")
    if _ID_RE.match(raw):
        return raw
    raise ValueError(f"'{value}' is not a post id or post link")


def resolve_tweets(value, limit=20):
    out = []
    for raw in str(value or "").split(","):
        raw = raw.strip()
        if raw:
            tid = resolve_tweet(raw)
            if tid not in out:
                out.append(tid)
    if not out:
        raise ValueError("at least one post is required")
    if len(out) > limit:
        raise ValueError(f"at most {limit} posts per call")
    return out


def tweet_link(screen_name, tweet_id):
    if not tweet_id:
        return None
    return f"{SITE}/{screen_name}/status/{tweet_id}" if screen_name else f"{SITE}/i/web/status/{tweet_id}"


# ---- lists --------------------------------------------------------------------------

def resolve_list(value):
    """-> {"list_id": "..."} or {"slug": "...", "owner": "..."}."""
    raw = (value or "").strip()
    if not raw:
        raise ValueError("list is required")
    if _is_link(raw):
        segments = _parts(raw, "list")
        if len(segments) >= 3 and segments[0] == "i" and segments[1] == "lists" and _ID_RE.match(segments[2]):
            return {"list_id": segments[2]}
        if len(segments) >= 3 and segments[1] == "lists" and _USERNAME_RE.match(segments[0]):
            if _ID_RE.match(segments[2]):
                return {"list_id": segments[2]}
            if _SLUG_RE.match(segments[2]):
                return {"slug": segments[2], "owner": segments[0]}
        raise ValueError(f"'{value}' is not a list link (expected x.com/i/lists/<id>)")
    if _ID_RE.match(raw):
        return {"list_id": raw}
    raise ValueError(f"'{value}' is not a list id or list link")


def list_link(list_id):
    return f"{SITE}/i/lists/{list_id}" if list_id else None


# ---- communities --------------------------------------------------------------------

def resolve_community(value):
    raw = (value or "").strip()
    if not raw:
        raise ValueError("community is required")
    if _is_link(raw):
        segments = _parts(raw, "community")
        if len(segments) >= 3 and segments[0] == "i" and segments[1] == "communities" and _ID_RE.match(segments[2]):
            return segments[2]
        raise ValueError(f"'{value}' is not a community link (expected x.com/i/communities/<id>)")
    if _ID_RE.match(raw):
        return raw
    raise ValueError(f"'{value}' is not a community id or community link")


def community_link(community_id):
    return f"{SITE}/i/communities/{community_id}" if community_id else None
