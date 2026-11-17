"""X / Twitter transport: plain curl_cffi with browser-impersonated TLS,
no browser. Verified 2026-09-22 from direct egress and from proxy exits in
the US, GB and DE: X runs no anti-bot on these surfaces, only login walls.

Four upstream surfaces, all anonymous:

  * GRAPHQL   https://x.com/i/api/graphql/<queryId>/<Operation>
    The legacy web app's persisted queries (ids in twitter/queries.py),
    authorised with the public web bearer token + a guest token minted
    from POST api.x.com/1.1/guest/activate.json. A guest may call
    UserByScreenName, TweetResultByRestId, UserTweets (the "top tweets"
    guest variant: ~99 most-liked posts, no cursor), UserHighlightsTweets and
    GenericTimelineById; every other operation answers an EMPTY 404 for a
    guest (that is the login wall, not a missing query). Guest tokens are
    rate-limited per token: a 429 mints a fresh one and retries.

  * REST      https://x.com/i/api/1.1/...  (api.x.com serves the same)
    trends/place, trends/available, lists/show, friendships/show,
    users/recommendations, hashflags, geo/search work for a guest; the
    classic users/show, statuses/*, search/*, followers|friends/ids,
    lists/statuses|members are gone ("page does not exist", code 34).

  * SSR PAGES https://x.com/<user>, /<user>/status/<id>, /i/communities/<id>
    X's new logged-out "x-web" app server-renders these three page types
    with the Relay store inlined (twitter/relay.py): profile + pinned + the
    5 latest original posts, a post + its first reply threads, a community
    + its top 20 posts. Every other path (/with_replies, /media, /search,
    /hashtag/…, /i/lists/…) serves the empty legacy SPA shell.

  * SYNDICATION (embed widgets, no auth at all)
    cdn.syndication.twimg.com/tweet-result?id=&token=<any> (compact post
    JSON), syndication.twitter.com/srv/timeline-list/list-id/<id> (a list's
    ~80 latest posts inside __NEXT_DATA__), publish.twitter.com/oembed.
    The profile timeline widget answers 429 from every exit (dead).

Public data only: no account cookies, ever. Operations that need a login
(search, followers, replies, media, likes, …) are not offered.

Blocks: none seen. If the pod's egress ever starts answering 403/429 on
non-GraphQL calls, a worker moves its sessions to the fallback proxy
(config.twitter_fallback_proxy()) for config.TWITTER_BLOCK_COOLDOWN seconds.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  TwitterUpstreamError  transport failure / 5xx                    — retryable
  TwitterBlocked        403 / 429 / HTML where JSON expected        — retryable on a new exit
  TwitterBadRequest     upstream 400 / 422 / bad params             — never retried
  TwitterNotFound       404 / missing entity / suspended / protected — never retried
  TwitterLoginWalled    X answered with its login wall (a surface it no longer
                        serves anonymously) — 502, retryable in case it was a
                        transient guest-token refusal
"""
import json
import fastjson
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import egress
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from twitter import queries
from scraper_utils import debug, fanout, retry, sessions

SITE = "https://x.com"
API = "https://x.com/i/api"
GUEST_ACTIVATE = "https://api.x.com/1.1/guest/activate.json"
SYNDICATION_TWEET = "https://cdn.syndication.twimg.com/tweet-result"
SYNDICATION_LIST = "https://syndication.twitter.com/srv/timeline-list/list-id/"
OEMBED = "https://publish.twitter.com/oembed"
IMPERSONATE = "chrome"

# The public bearer token every x.com web client ships (not a secret).
BEARER = ("Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D"
          "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA")

TIMEOUT = 30
PAGE_TIMEOUT = 45
FANOUT_WORKERS = 8
GUEST_TOKEN_TTL = 2 * 3600
GUEST_REMINT_PAUSE = 60     # a token refused before its first call is not replaced sooner than this
QUERY_ID_REFRESH_MIN_INTERVAL = 600

API_HEADERS = {
    "authorization": BEARER,
    "accept": "*/*",
    "accept-language": egress.site_accept_language("twitter"),
    "content-type": "application/json",
    "referer": SITE + "/",
    "origin": SITE,
    "x-twitter-active-user": "yes",
    "x-twitter-client-language": "en",
}
PAGE_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": egress.site_accept_language("twitter"),
    "upgrade-insecure-requests": "1",
}


class TwitterUpstreamError(UpstreamError):
    """Transport failure or 5xx — retryable."""


class TwitterBlocked(TwitterUpstreamError, Blocked):
    """403 / 429 or an HTML body where JSON was expected — retryable."""


class TwitterBadRequest(BadRequest):
    """Upstream 400 / 422 — the params were rejected. Never retried."""


class TwitterNotFound(NotFound):
    """Entity / page does not exist (or is suspended / protected) — never retried."""


class TwitterLoginWalled(TwitterUpstreamError):
    """X answered with its login wall on a surface it should serve anonymously."""


# ---- sessions ------------------------------------------------------------------
_local = threading.local()
_fallback_until = 0.0
_fallback_lock = threading.Lock()


def _proxy_for_new_session():
    forced = config.twitter_proxy()
    if forced:
        return forced
    if time.time() < _fallback_until:
        return config.twitter_fallback_proxy()
    return None


def _session():
    return sessions.thread_session(_local, lambda: sessions.curl_session(
        IMPERSONATE, proxy_fn=_proxy_for_new_session))


def _drop_session():
    sessions.drop(_local)


def _note_block():
    global _fallback_until
    if config.twitter_fallback_proxy() is not None:
        with _fallback_lock:
            _fallback_until = time.time() + config.TWITTER_BLOCK_COOLDOWN


def dump_debug(name, text):
    debug.dump("TWITTER_DEBUG_DIR", name, text)


def _retrying(fn):
    return retry.run(fn, config, TwitterUpstreamError, lambda e: _drop_session())


# ---- guest token -------------------------------------------------------------------
_guest = {"token": None, "minted": 0.0, "served": 0}   # served: calls X answered on this token
_guest_lock = threading.Lock()


def guest_token(stale=None):
    """The shared guest token, minted on demand. `stale` is a token that
    was just refused: when another thread already replaced it, that newer
    token is returned without minting again."""
    with _guest_lock:
        token = _guest["token"]
        fresh = token and time.time() - _guest["minted"] < GUEST_TOKEN_TTL
        if fresh and token != stale:
            return token
        if stale and token == stale and not _guest["served"] and time.time() - _guest["minted"] < GUEST_REMINT_PAUSE:
            # refused before it served a single call: X is limiting this IP,
            # not the token, so another mint would be refused too. Block
            # instead (new sessions move to the fallback exit); after
            # GUEST_REMINT_PAUSE a re-mint is allowed again, so at most one
            # mint per pause while X refuses.
            _note_block()
            raise TwitterBlocked("a fresh guest token was refused before its first call; not minting again yet")
        sess = _session()
        try:
            resp = sess.post(GUEST_ACTIVATE, headers={"authorization": BEARER, "accept": "*/*"},
                             timeout=TIMEOUT)
        except Exception as e:
            raise TwitterUpstreamError(f"guest token request failed: {type(e).__name__}: {e}")
        if resp.status_code in (403, 429):
            _note_block()
            raise TwitterBlocked(f"HTTP {resp.status_code} minting a guest token")
        try:
            token = resp.json().get("guest_token")
        except Exception:
            token = None
        if not token:
            raise TwitterUpstreamError(f"guest token missing (HTTP {resp.status_code})")
        _guest["token"] = token
        _guest["minted"] = time.time()
        _guest["served"] = 0
        return token


def _served(headers):
    """Count one answered call on the guest token in `headers`."""
    with _guest_lock:
        if _guest["token"] == headers.get("x-guest-token"):
            _guest["served"] += 1


def _guest_headers():
    headers = dict(API_HEADERS)
    headers["x-guest-token"] = guest_token()
    return headers


# ---- classification -------------------------------------------------------------------

def _error_messages(body):
    if isinstance(body, dict):
        errors = body.get("errors")
        if isinstance(errors, list):
            return [str(e.get("message") or "") for e in errors if isinstance(e, dict)]
    return []


def _json_of(resp, label):
    text = resp.text or ""
    if not text.strip():
        return None
    if not text.lstrip().startswith(("{", "[")):
        dump_debug("nonjson", text)
        raise TwitterBlocked(f"{label} returned HTML, not JSON")
    try:
        return resp.json()
    except Exception:
        dump_debug("badjson", text)
        raise TwitterUpstreamError(f"could not parse JSON from {label}")


# ---- GraphQL --------------------------------------------------------------------------
# Optional read flags sent with every operation that returns posts. X only
# asks for the REQUIRED ones ("features cannot be null", learned below), so
# without these it silently leaves data out: no `views` object at all, so
# stats.views was null on every post (customer report 2026-10-23; with the
# flag the same post read 212,612). All are in X's own featureSwitches for
# these operations (main.js); over 19 live posts this set changed nothing
# but adding views. Posts from before Dec 2022 still have no count (X sends
# views {"state": "Enabled"} with no number), so null stays right for them.
TWEET_FEATURES = {
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "communities_web_enable_tweet_community_results_fetch": True,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "articles_preview_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "creator_subscriptions_tweet_preview_api_enabled": True,
}
TWEET_OPERATIONS = {"TweetResultByRestId", "UserTweets", "UserHighlightsTweets", "GenericTimelineById"}

_features = {}          # operation -> features learned from "cannot be null" errors
_features_lock = threading.Lock()
_query_ids = dict(queries.QUERY_IDS)
_query_ids_refreshed = 0.0
_query_lock = threading.Lock()
_QUERY_RE = re.compile(r'queryId:"([^"]+)",operationName:"([^"]+)"')
_MAIN_JS_RE = re.compile(r'https://abs\.twimg\.com/responsive-web/client-web(?:-legacy)?/main\.[a-z0-9]+\.js')

def query_id(operation):
    qid = _query_ids.get(operation)
    if not qid:
        raise TwitterBadRequest(f"unknown GraphQL operation {operation}")
    return qid


def _refresh_query_ids():
    """Re-read the operation -> queryId table from a fresh main.js (found
    in any legacy-shell page). Returns True when the table changed."""
    global _query_ids_refreshed
    with _query_lock:
        if time.time() - _query_ids_refreshed < QUERY_ID_REFRESH_MIN_INTERVAL:
            return False
        _query_ids_refreshed = time.time()
        sess = _session()
        try:
            html = sess.get(SITE + "/i/flow/login", headers=PAGE_HEADERS, timeout=PAGE_TIMEOUT).text or ""
            match = _MAIN_JS_RE.search(html)
            url = match.group(0) if match else queries.MAIN_JS
            js = sess.get(url, headers=PAGE_HEADERS, timeout=PAGE_TIMEOUT).text or ""
        except Exception as e:
            print(f"twitter: query id refresh failed: {type(e).__name__}: {e}")
            return False
        found = {op: qid for qid, op in _QUERY_RE.findall(js)}
        changed = False
        for op in list(_query_ids):
            if op in found and found[op] != _query_ids[op]:
                print(f"twitter: query id {op} {_query_ids[op]} -> {found[op]}")
                _query_ids[op] = found[op]
                changed = True
        return changed


def _learn_features(operation, messages):
    """'The following features cannot be null: a, b' -> remember a, b."""
    added = False
    for msg in messages:
        match = re.search(r"features cannot be null: (.*)", msg)
        if not match:
            continue
        with _features_lock:
            current = dict(_features.get(operation) or {})
            for name in re.split(r",\s*", match.group(1).strip()):
                name = name.strip().rstrip(".")
                if name and name not in current:
                    current[name] = True
                    added = True
            _features[operation] = current
    return added


def graphql(operation, variables, features=None, label=None):
    """GET one persisted GraphQL query with the guest token -> the response
    `data` dict. Operations that return posts always carry TWEET_FEATURES
    (an empty map is accepted but drops optional data such as views); any
    "features cannot be null" answer is learned and retried."""
    label = label or operation

    def once():
        sess = _session()
        headers = _guest_headers()
        feats = dict(TWEET_FEATURES) if operation in TWEET_OPERATIONS else {}
        with _features_lock:
            feats.update(_features.get(operation) or {})
        if features:
            feats.update(features)
        for attempt in range(4):
            params = {"variables": json.dumps(variables, separators=(",", ":")),
                      "features": json.dumps(feats, separators=(",", ":"))}
            url = f"{API}/graphql/{query_id(operation)}/{operation}"
            try:
                resp = sess.get(url, params=params, headers=headers, timeout=TIMEOUT)
            except Exception as e:
                raise TwitterUpstreamError(f"{label}: request failed: {type(e).__name__}: {e}")
            status = resp.status_code
            if status in (401, 403, 429):
                # Checked BEFORE the body is parsed: X answers a spent guest
                # token (150 lookups / 15 min per token) with a PLAIN-TEXT 429
                # "Rate limit exceeded", which _json_of reads as an HTML block.
                # Until 2026-10-26 that skipped this branch, so the call was
                # retried on the same spent token and failed (half of a
                # customer's users/profiles burst). A fresh token from the
                # same IP gets a fresh 150.
                headers["x-guest-token"] = guest_token(stale=headers.get("x-guest-token"))
                continue
            _served(headers)
            body = _json_of(resp, label) if (resp.text or "").strip() else None
            messages = _error_messages(body)
            if status == 400 and _learn_features(operation, messages):
                with _features_lock:
                    feats.update(_features.get(operation) or {})
                continue
            if status == 404:
                if any("not found" in m.lower() for m in messages) or "Query not found" in (resp.text or ""):
                    if _refresh_query_ids():
                        continue
                    raise TwitterUpstreamError(f"{label}: query id rejected and no newer bundle found")
                # an EMPTY 404 is X's login wall for guests
                raise TwitterLoginWalled(f"{label}: X no longer serves this to a guest (404)")
            if status >= 500:
                raise TwitterUpstreamError(f"{label}: HTTP {status}")
            if status != 200:
                raise TwitterBadRequest("; ".join(messages) or f"{label}: HTTP {status}")
            if not isinstance(body, dict):
                raise TwitterUpstreamError(f"{label}: empty response")
            data = body.get("data")
            if messages and not data:
                low = " ".join(messages).lower()
                if "rate limit" in low:
                    headers["x-guest-token"] = guest_token(stale=headers.get("x-guest-token"))
                    continue
                if "authorization" in low or "forbidden" in low:
                    raise TwitterLoginWalled(f"{label}: {messages[0]}")
                raise TwitterUpstreamError(f"{label}: {messages[0]}")
            return data or {}
        raise TwitterUpstreamError(f"{label}: gave up after repeated retries")
    return _retrying(once)


# ---- REST 1.1 ---------------------------------------------------------------------------

def rest(path, params=None, label=None):
    """GET https://x.com/i/api<path> -> parsed JSON."""
    label = label or path

    def once():
        sess = _session()
        headers = _guest_headers()
        for attempt in range(3):
            try:
                resp = sess.get(API + path, params=params, headers=headers, timeout=TIMEOUT)
            except Exception as e:
                raise TwitterUpstreamError(f"{label}: request failed: {type(e).__name__}: {e}")
            status = resp.status_code
            if status == 404:
                raise TwitterNotFound(f"{label}: not found")
            if status in (401, 403, 429):
                headers["x-guest-token"] = guest_token(stale=headers.get("x-guest-token"))
                continue
            _served(headers)
            body = _json_of(resp, label)
            messages = _error_messages(body)
            if status == 400 or status == 422:
                raise TwitterBadRequest("; ".join(messages) or f"{label}: HTTP {status}")
            if status >= 500:
                raise TwitterUpstreamError(f"{label}: HTTP {status}")
            if status != 200:
                raise TwitterUpstreamError("; ".join(messages) or f"{label}: HTTP {status}")
            return body
        _note_block()
        raise TwitterBlocked(f"{label}: guest token kept being refused")
    return _retrying(once)


# ---- SSR pages ----------------------------------------------------------------------------

def page(path, label=None):
    """GET one x.com HTML page -> (html, final path). The logged-out app
    server-renders profile, post and community pages; anything else comes
    back as the empty legacy SPA shell (no Relay data)."""
    label = label or path

    def once():
        sess = _session()
        try:
            resp = sess.get(SITE + path, headers=PAGE_HEADERS, timeout=PAGE_TIMEOUT, allow_redirects=True)
        except Exception as e:
            raise TwitterUpstreamError(f"{label}: request failed: {type(e).__name__}: {e}")
        status = resp.status_code
        if status == 404:
            raise TwitterNotFound(f"{label}: not found")
        if status in (403, 429):
            dump_debug("blocked", resp.text)
            _note_block()
            raise TwitterBlocked(f"{label}: HTTP {status}")
        if status >= 500 or status != 200:
            raise TwitterUpstreamError(f"{label}: HTTP {status}")
        return resp.text or "", resp.url
    return _retrying(once)


# ---- syndication / oembed -----------------------------------------------------------------

def _plain_get(url, params, label, headers=None):
    def once():
        sess = _session()
        try:
            resp = sess.get(url, params=params, headers=headers or {"accept": "*/*"}, timeout=TIMEOUT)
        except Exception as e:
            raise TwitterUpstreamError(f"{label}: request failed: {type(e).__name__}: {e}")
        status = resp.status_code
        if status == 404:
            raise TwitterNotFound(f"{label}: not found")
        if status in (403, 429):
            _note_block()
            raise TwitterBlocked(f"{label}: HTTP {status}")
        if status >= 500 or status != 200:
            raise TwitterUpstreamError(f"{label}: HTTP {status}")
        return resp
    return _retrying(once)


def syndication_tweet(tweet_id, lang="en"):
    """The embed widget's compact post JSON (None when the post is gone).
    The `token` param must be present; any value is accepted."""
    resp = _plain_get(SYNDICATION_TWEET, {"id": tweet_id, "token": "x", "lang": lang},
                      f"syndication post {tweet_id}")
    body = _json_of(resp, "syndication")
    if not isinstance(body, dict) or not body:
        return None
    if body.get("__typename") == "TweetTombstone":
        return None
    return body


_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


def syndication_list(list_id):
    """The list embed's __NEXT_DATA__ pageProps: {timeline: {entries}, headerProps}."""
    resp = _plain_get(SYNDICATION_LIST + str(list_id), None, f"list {list_id} timeline",
                      headers=PAGE_HEADERS)
    match = _NEXT_DATA_RE.search(resp.text or "")
    if not match:
        dump_debug("synd_list", resp.text)
        raise TwitterUpstreamError(f"list {list_id}: embed page carried no data")
    try:
        data = fastjson.loads(match.group(1))
    except ValueError:
        raise TwitterUpstreamError(f"list {list_id}: embed data unreadable")
    props = ((data or {}).get("props") or {}).get("pageProps") or {}
    if not props.get("timeline"):
        raise TwitterNotFound(f"list {list_id}: not found or private")
    return props


def oembed(url):
    resp = _plain_get(OEMBED, {"url": url, "omit_script": "true", "dnt": "true"}, "oembed")
    return _json_of(resp, "oembed")


# ---- fan-out --------------------------------------------------------------------------------

def run_parallel(fns):
    return fanout.per_call(fns, FANOUT_WORKERS)


def gather(mapping):
    """{key: callable} in parallel -> {key: result}; a NotFound / BadRequest
    for one key yields None instead of failing the set."""
    return fanout.gather(run_parallel, mapping, (TwitterNotFound, TwitterBadRequest))


if __name__ == "__main__":
    # Smoke test: python twitter/fetch.py [username]
    name = sys.argv[1] if len(sys.argv) > 1 else "elonmusk"
    user = graphql("UserByScreenName", {"screen_name": name, "withGrokTranslatedBio": False})
    result = ((user.get("user") or {}).get("result") or {})
    print(f"{name}: id={result.get('rest_id')} followers={(result.get('relationship_counts') or {}).get('followers')}")
    trends = rest("/1.1/trends/place.json", {"id": 1})
    print("worldwide trends:", [t["name"] for t in trends[0]["trends"][:5]])
