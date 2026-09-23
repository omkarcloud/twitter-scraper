"""Live endpoint smoke tests: one call per /twitter/* route against a running
service, with example values proven to return data (2026-09-23). The
listing tooling reads each route's FIRST call from this file's AST as its
working example, so the values stay literals.

Skipped unless TWITTER_BASE points at a running service:

    ONLY_SCRAPER=twitter python run.py
    TWITTER_BASE=http://127.0.0.1:6002 python -m pytest twitter/test_endpoints.py -q
"""
import os

import pytest

BASE = os.environ.get("TWITTER_BASE", "").rstrip("/")

pytestmark = pytest.mark.skipif(not BASE, reason="set TWITTER_BASE to run live endpoint tests")


def call(path, status=200, **params):
    from curl_cffi import requests
    resp = requests.get(BASE + path, params=params, timeout=180)
    assert resp.status_code == status, f"{path} {params} -> {resp.status_code} {resp.text[:300]}"
    body = resp.json()
    assert body, f"{path} returned an empty body"
    return body


def test_users():
    user = call("/twitter/users/profile", user="elonmusk")["user"]
    assert user["id"] == "44196397" and user["followers_count"] > 100_000_000
    assert call("/twitter/users/profile", user="44196397")["user"]["username"] == "elonmusk"
    batch = call("/twitter/users/profiles", users="nasa,spacex,https://x.com/elonmusk")
    assert batch["count"] == 3 and all(u.get("id") for u in batch["users"])
    tweets = call("/twitter/users/tweets", user="nasa", count=10)
    assert tweets["count"] >= 1 and tweets["tweets"][0]["author"]["username"] == "NASA"
    top = call("/twitter/users/top-tweets", user="nasa", count=5)
    assert top["count"] == 5 and top["tweets"][0]["stats"]["likes"] >= top["tweets"][-1]["stats"]["likes"]
    assert call("/twitter/users/highlights", user="elonmusk", count=5)["tweets"]
    rel = call("/twitter/users/check-follow", source="elonmusk", target="x")
    assert rel["source_follows_target"] is True
    assert call("/twitter/users/recommendations", user="nasa", count=5)["users"]


def test_tweets():
    tweet = call("/twitter/tweets/details", tweet="https://x.com/FonsDK/status/1671370010743263233")["tweet"]
    assert tweet["media"][0]["video_link"].endswith(".mp4?tag=14")
    batch = call("/twitter/tweets/details/batch", tweets="1671370010743263233,2102207241101144450")
    assert batch["count"] == 2
    replies = call("/twitter/tweets/replies", tweet="2102207241101144450")
    assert replies["tweet"]["id"] == "2102207241101144450" and replies["replies"]
    thread = call("/twitter/tweets/thread", tweet="2102253452168511734")
    assert thread["parents_count"] == 1 and thread["parents"][0]["id"] == "2102207241101144450"
    assert call("/twitter/tweets/embed", tweet="2102207241101144450")["html"].startswith("<blockquote")


def test_trends_and_tables():
    trends = call("/twitter/trends", location="india")
    assert trends["location"]["woeid"] == 23424848 and trends["count"] >= 10
    assert call("/twitter/trends", location="1", exclude_hashtags="true")["trends"]
    assert call("/twitter/trends/locations", query="united")["count"] > 10
    assert call("/twitter/hashflags")["count"] > 10
    assert call("/twitter/places/search", query="paris")["places"][0]["country_code"] == "FR"


def test_lists_and_communities():
    lst = call("/twitter/lists/details", list="https://x.com/nelligan_14/lists/marvel-star-wars-34765")["list"]
    assert lst["id"] == "1343798673386434560"
    rows = call("/twitter/lists/tweets", list="1343798673386434560", count=5)
    assert rows["count"] == 5 and rows["list"]["name"]
    community = call("/twitter/communities/details", community="1601841656147345410")["community"]
    assert community["name"] == "Generative AI" and community["members_count"] > 100_000
    assert call("/twitter/communities/tweets", community="https://x.com/i/communities/1601841656147345410", count=5)["count"] == 5


def test_errors():
    call("/twitter/users/profile", status=400, user="bad user!")
    call("/twitter/users/profile", status=400, user="nasa", bogus="1")
    call("/twitter/tweets/details", status=404, tweet="1")
    call("/twitter/trends", status=400, location="atlantis")
