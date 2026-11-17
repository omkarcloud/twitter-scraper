"""Offline tests for the Twitter transport's guest-token handling
(twitter/fetch.py graphql): X's PLAIN-TEXT 429 for a spent guest token
mints one fresh token and retries, concurrent 429s share one mint, and a
users/profiles batch survives the token running out mid-burst. The curl
session is a script; no network.

    python -m pytest twitter/test_fetch.py -q
"""
import json
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from twitter import fetch as F, users  # noqa: E402

SPENT = (429, "Rate limit exceeded\n")      # what X really sends (2026-10-26)


def _user(name):
    return {"data": {"user": {"result": {"__typename": "User", "rest_id": "1", "legacy": {"screen_name": name}}}}}


class _Resp:
    def __init__(self, status, text):
        self.status_code, self.text = status, text
        self.headers = {}

    def json(self):
        return json.loads(self.text)


class _Box:
    """Scripted X: each guest token serves `budget` lookups, then answers the
    plain-text 429. guest/activate hands out tok-1, tok-2, ..."""

    def __init__(self, budget):
        self.budget, self.lock = budget, threading.Lock()
        self.used, self.minted, self.calls = {}, [], []

    def post(self, url, headers=None, **kw):
        with self.lock:
            self.minted.append(f"tok-{len(self.minted) + 1}")
            return _Resp(200, json.dumps({"guest_token": self.minted[-1]}))

    def get(self, url, params=None, headers=None, **kw):
        tok = headers.get("x-guest-token")
        name = json.loads(params["variables"]).get("screen_name", "x")
        with self.lock:
            self.calls.append(tok)
            if self.used.get(tok, 0) >= self.budget:
                return _Resp(*SPENT)
            self.used[tok] = self.used.get(tok, 0) + 1
        return _Resp(200, json.dumps(_user(name)))

    def close(self):
        pass


@pytest.fixture
def x(monkeypatch):
    def make(budget):
        box = _Box(budget)
        monkeypatch.setattr(F, "_session", lambda: box)
        monkeypatch.setattr(F, "_drop_session", lambda: None)
        monkeypatch.setattr(F, "query_id", lambda op: "qid")
        monkeypatch.setattr(F.time, "sleep", lambda s: None)
        monkeypatch.setattr(config, "MAX_RETRIES", 3)
        F._guest.update(token=None, minted=0.0, served=0)
        return box
    yield make
    F._guest.update(token=None, minted=0.0, served=0)


def test_a_plain_text_429_mints_a_fresh_token_and_retries(x):
    box = x(budget=1)
    assert F.graphql("UserByScreenName", {"screen_name": "a"})["user"]["result"]["legacy"]["screen_name"] == "a"
    data = F.graphql("UserByScreenName", {"screen_name": "b"})          # tok-1 spent -> 429 text -> tok-2
    assert data["user"]["result"]["legacy"]["screen_name"] == "b"
    assert box.minted == ["tok-1", "tok-2"] and box.calls == ["tok-1", "tok-1", "tok-2"]


def test_a_burst_that_outruns_one_token_succeeds_whole(x):
    """20-user batches, 8 lookups in flight: the token runs out mid-burst
    (the customer pattern), every batch still answers in full."""
    box = x(budget=30)
    batches = [[{"screen_name": f"u{b}_{i}"} for i in range(20)] for b in range(5)]
    out = [users.profiles(batch) for batch in batches]
    assert all(o["count"] == 20 and all("error" not in u for u in o["users"]) for o in out)
    assert len(box.minted) == 4                                       # 100 lookups / 30 per token: one mint per spent token
    assert sum(box.used.values()) == 100


def test_concurrent_429s_on_one_spent_token_share_one_mint(x):
    box = x(budget=50)
    F._guest.update(token="tok-0", minted=F.time.time() - 600, served=50)   # served 50, now spent
    box.used["tok-0"] = 50
    barrier = threading.Barrier(8)
    results = []

    def lookup(i):
        barrier.wait()
        results.append(F.graphql("UserByScreenName", {"screen_name": f"c{i}"}))
    threads = [threading.Thread(target=lookup, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 8 and box.minted == ["tok-1"]             # 8 refusals, ONE fresh token


def test_a_fresh_token_refused_at_once_is_an_ip_block_not_a_mint_storm(x, monkeypatch):
    """If X refuses even a brand-new token, minting again cannot help: the
    call is blocked (new sessions go to the fallback exit) instead of
    minting up to 4 tokens per attempt, and after GUEST_REMINT_PAUSE one
    re-mint is allowed again."""
    box = x(budget=0)
    monkeypatch.setattr(config, "twitter_fallback_proxy", lambda: "http://u:p@gw:10001")
    with pytest.raises(F.TwitterBlocked, match="before its first call"):
        F.graphql("UserByScreenName", {"screen_name": "e"})
    assert box.minted == ["tok-1"]                                    # every retry reused it: no mint storm
    assert F._fallback_until > F.time.time()                          # new sessions use the fallback exit
    F._guest["minted"] -= F.GUEST_REMINT_PAUSE + 1                    # the pause is over
    box.budget = 5
    box.used["tok-1"] = 5                                             # that token itself stays refused
    assert F.graphql("UserByScreenName", {"screen_name": "e"})["user"]
    assert box.minted == ["tok-1", "tok-2"]                           # so one re-mint is allowed now


def test_a_json_403_still_refreshes_the_token(x):
    box = x(budget=5)
    F._guest.update(token="bad", minted=F.time.time() - 600, served=3)   # worked, now rejected
    orig = box.get

    def get(url, params=None, headers=None, **kw):
        if headers.get("x-guest-token") == "bad":
            box.calls.append("bad")
            return _Resp(403, json.dumps({"errors": [{"message": "Bad guest token"}]}))
        return orig(url, params=params, headers=headers, **kw)
    box.get = get
    assert F.graphql("UserByScreenName", {"screen_name": "d"})["user"]
    assert box.minted == ["tok-1"] and box.calls[0] == "bad"
