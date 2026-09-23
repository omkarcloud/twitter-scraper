"""Offline tests: ref parsing, the Relay-literal reader and the normalizers
against raw x.com responses captured 2026-09-22/23 (twitter/fixtures/*).

    python -m pytest twitter/test_parsers.py -q
"""
import json
import os

import pytest

from twitter import parsers as P
from twitter import refs, relay
from twitter import trends as T

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def fx(name):
    with open(os.path.join(FIX, name + ".json")) as f:
        return json.load(f)


def html(name):
    with open(os.path.join(FIX, name + ".html")) as f:
        return f.read()


def _no_camel_or_url_keys(obj, path="$"):
    """Every emitted key is snake_case and no key is named *url*."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            assert key == key.lower() and " " not in key, f"{path}.{key} not snake_case"
            assert "url" not in key, f"{path}.{key} should be a *link"
            _no_camel_or_url_keys(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            _no_camel_or_url_keys(value, f"{path}[{i}]")


# ---- refs -----------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("elonmusk", {"screen_name": "elonmusk"}), ("@NASA", {"screen_name": "NASA"}),
    ("https://x.com/elonmusk", {"screen_name": "elonmusk"}),
    ("twitter.com/elonmusk/with_replies", {"screen_name": "elonmusk"}),
    ("https://mobile.twitter.com/NASA?s=20", {"screen_name": "NASA"}),
    ("44196397", {"user_id": "44196397"}),
    ("https://x.com/i/user/44196397", {"user_id": "44196397"}),
])
def test_resolve_user(value, expected):
    assert refs.resolve_user(value) == expected


@pytest.mark.parametrize("value", ["", "bad user!", "thisusernameiswaytoolong", "https://x.com/i/lists/1",
                                   "https://instagram.com/nasa", "https://x.com/search?q=x"])
def test_resolve_user_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_user(value)


def test_resolve_users():
    assert refs.resolve_users("nasa, @NASA,https://x.com/spacex, 44196397") == [
        {"screen_name": "nasa"}, {"screen_name": "NASA"}, {"screen_name": "spacex"}, {"user_id": "44196397"}]
    with pytest.raises(ValueError):
        refs.resolve_users(",".join(str(10000 + i) for i in range(21)))


@pytest.mark.parametrize("value, expected", [
    ("2102207241101144450", "2102207241101144450"),
    ("https://x.com/elonmusk/status/2102207241101144450", "2102207241101144450"),
    ("https://x.com/elonmusk/status/2102207241101144450/photo/1?s=20", "2102207241101144450"),
    ("twitter.com/i/web/status/2102207241101144450", "2102207241101144450"),
    ("https://fxtwitter.com/NASA/status/2102502016610091359", "2102502016610091359"),
])
def test_resolve_tweet(value, expected):
    assert refs.resolve_tweet(value) == expected


@pytest.mark.parametrize("value", ["", "abc", "https://x.com/elonmusk", "https://t.co/abc"])
def test_resolve_tweet_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_tweet(value)


@pytest.mark.parametrize("value, expected", [
    ("1343798673386434560", {"list_id": "1343798673386434560"}),
    ("https://x.com/i/lists/1343798673386434560", {"list_id": "1343798673386434560"}),
    ("https://x.com/nelligan_14/lists/marvel-star-wars-34765", {"slug": "marvel-star-wars-34765", "owner": "nelligan_14"}),
])
def test_resolve_list(value, expected):
    assert refs.resolve_list(value) == expected


def test_resolve_community():
    assert refs.resolve_community("https://x.com/i/communities/1601841656147345410") == "1601841656147345410"
    with pytest.raises(ValueError):
        refs.resolve_community("https://x.com/elonmusk")


# ---- relay literal ------------------------------------------------------------------

def test_parse_literal_basics():
    value, end = relay.parse_literal('{a:1,"b c":"x\\u00e9",d:!0,e:!1,f:null,g:void 0,h:[1,,2],i:$R[3]={k:$R[3]}}')
    assert value["a"] == 1 and value["b c"] == "xé" and value["d"] is True and value["e"] is False
    assert value["f"] is None and "g" not in value and value["h"] == [1, None, 2]
    assert value["i"]["k"] is value["i"]          # self reference resolved


def test_page_records_and_root():
    records = relay.page_records(html("ssr_profile"))
    assert "client:root" in records
    root = relay.root(records)
    user = root["user_result_by_screen_name"]["result"]
    assert user["rest_id"] == "44196397" and user["core"]["screen_name"] == "elonmusk"
    # argument suffixes are stripped and refs followed
    assert "profile_user_originals_timeline" in user
    instructions = user["profile_user_originals_timeline"]["timeline"]["instructions"]
    assert any(i["__typename"] == "TimelineAddEntries" for i in instructions)


def test_router_matches():
    matches = relay.router_matches(html("ssr_community"))
    loader = next(m["l"] for m in matches if "communities" in str(m.get("i")) and m.get("l"))
    assert loader["memberCount"] > 100000 and loader["metaTitle"] == "Generative AI"


# ---- users ----------------------------------------------------------------------------

def test_user_graphql():
    user = P.user(fx("gql_user_by_screen_name")["data"]["user"]["result"])
    _no_camel_or_url_keys(user)
    assert user["id"] == "44196397" and user["username"] == "elonmusk"
    assert user["link"] == "https://x.com/elonmusk"
    assert user["profile_image"].endswith("_400x400.jpg")
    assert user["followers_count"] > 200_000_000 and user["following_count"] == 1407
    assert user["tweets_count"] == 108893 and user["media_count"] == 4722 and user["likes_count"] == 248947
    assert user["is_blue_verified"] is True and user["is_protected"] is False
    assert user["affiliate"]["name"] == "X" and user["affiliate"]["type"] == "BusinessLabel"
    assert user["pinned_tweet_ids"] == ["2102207241101144450"]
    assert user["created_at"] == "2009-06-02T20:12:29Z"
    assert user["subscriptions_count"] == 251


def test_user_ssr_and_classic():
    records = relay.page_records(html("ssr_profile"))
    ssr = P.user(relay.root(records)["user_result_by_screen_name"]["result"])
    assert ssr["username"] == "elonmusk" and ssr["followers_count"] > 200_000_000
    classic = P.user(fx("rest_recommendations")[0]["user"])
    _no_camel_or_url_keys(classic)
    assert classic["username"] == "BillGates" and classic["website"] == "https://gatesnot.es/tgn"
    assert classic["followers_count"] > 60_000_000 and classic["created_at"].startswith("2009-")
    assert P.user({"__typename": "UserUnavailable"}) is None
    assert P.user(None) is None


# ---- tweets ---------------------------------------------------------------------------

def test_tweet_graphql_video():
    tweet = P.tweet(fx("gql_tweet_result_video")["data"]["tweetResult"])
    _no_camel_or_url_keys(tweet)
    assert tweet["id"] == "1671370010743263233"
    assert tweet["link"] == "https://x.com/FonsDK/status/1671370010743263233"
    assert tweet["text"].startswith("Watching Twitter videos") and "t.co" not in tweet["text"]
    assert tweet["created_at"] == "2023-06-21T04:10:37Z" and tweet["language"] == "en"
    assert tweet["author"]["username"] == "FonsDK"
    assert tweet["stats"] == {"replies": 1274, "retweets": 1938, "likes": 16167, "quotes": 206,
                              "bookmarks": 827, "views": None}
    media = tweet["media"][0]
    assert media["type"] == "video" and media["duration_ms"] == 8333
    assert media["video_link"].endswith(".mp4?tag=14") and "720x1280" in media["video_link"]
    assert len(media["video_variants"]) == 4 and media["width"] == 1080
    assert tweet["mentions"][0]["username"] == "elonmusk"
    assert tweet["source"] == "Twitter for iPad"
    assert tweet["is_retweet"] is False and tweet["is_quote"] is False and tweet["is_reply"] is False


def test_tweet_timeline_walk():
    walk = P.walk_timeline(fx("gql_user_tweets_top")["data"]["user"]["result"]["timeline"])
    tweets = walk["tweets"]
    assert len(tweets) >= 12 and walk["cursors"] == {"top": None, "bottom": None}
    pinned = [t for t in tweets if t["is_pinned"]]
    assert pinned and pinned[0]["id"] == "2102207241101144450"
    quoted = [t for t in tweets if t["is_quote"]]
    assert quoted and quoted[0]["quoted_tweet"]["author"]["username"]
    assert all(t["author"]["username"] == "elonmusk" for t in tweets)
    ids = [t["id"] for t in tweets]
    assert len(ids) == len(set(ids))


def test_highlights_cursor():
    walk = P.walk_timeline(fx("gql_user_highlights")["data"]["user"]["result"]["timeline"])
    assert len(walk["tweets"]) == 6
    assert walk["cursors"]["bottom"] and walk["cursors"]["top"]


def test_ssr_profile_tweets():
    records = relay.page_records(html("ssr_profile"))
    user = relay.root(records)["user_result_by_screen_name"]["result"]
    walk = P.walk_timeline(user["profile_user_originals_timeline"])
    tweets = walk["tweets"]
    assert len(tweets) == 5 and tweets[0]["is_pinned"] is True
    assert tweets[0]["text"] == "Grok 4.7"                      # trailing pic.x.com link removed
    assert tweets[0]["media"][0]["link"] == "https://x.com/elonmusk/status/2102207241101144450/photo/1"
    assert tweets[0]["stats"]["views"] == 19945794 and tweets[0]["stats"]["likes"] == 27354
    assert tweets[0]["author"]["username"] == "elonmusk"
    assert tweets[1]["is_quote"] and tweets[1]["quoted_tweet"]["author"]["username"] == "marsrepublica"
    assert all(t["created_at"].startswith("2026-09-2") for t in tweets)


def test_ssr_status_conversation():
    records = relay.page_records(html("ssr_status"))
    root = relay.root(records)
    focal = P.tweet(root["tweet_result_by_rest_id"])
    assert focal["id"] == "2102207241101144450" and focal["stats"]["replies"] == 2051
    walk = P.walk_timeline(root["threaded_conversation_with_injections_v2"])
    assert [len(m) for m in walk["modules"]] == [1, 1, 1]
    reply = walk["modules"][0][0]
    assert reply["is_reply"] and reply["reply_to"] == {
        "tweet_id": "2102207241101144450", "user_id": "44196397", "username": "elonmusk",
        "link": "https://x.com/elonmusk/status/2102207241101144450"}
    assert reply["author"]["username"] == "Solvairo" and reply["text"] == "@elonmusk Bro why are you boosting your own posts"


def test_ssr_community():
    page = html("ssr_community")
    records = relay.page_records(page)
    result = relay.root(records)["community_results_by_rest_id"]["result"]
    loader = next(m["l"] for m in relay.router_matches(page) if "communities" in str(m.get("i")) and m.get("l"))
    card = P.community(loader, result)
    _no_camel_or_url_keys(card)
    assert card["id"] == "1601841656147345410" and card["name"] == "Generative AI"
    assert card["members_count"] == 253908 and card["join_policy"] == "Open"
    assert card["creator"]["username"] == "chrisfirst" and card["created_at"] == "2022-12-11T07:29:46Z"
    assert card["banner"]["width"] == 1462 and len(card["member_avatars"]) == 4
    walk = P.walk_timeline(result["ranked_community_timeline"])
    assert len(walk["tweets"]) == 20 and all(t["author"]["username"] for t in walk["tweets"])


def test_syndication_list_and_tweet():
    props = fx("synd_timeline_list")["props"]["pageProps"]
    rows = [P.tweet(e["content"]["tweet"]) for e in props["timeline"]["entries"]]
    for row in rows:
        _no_camel_or_url_keys(row)
    assert all(r["link"].startswith("https://x.com/") for r in rows)
    retweet = next(r for r in rows if r["is_retweet"])
    assert retweet["retweeted_tweet"]["author"]["username"] and not retweet["text"].startswith("RT @")
    assert next(r for r in rows if r["is_quote"])["quoted_tweet"]["id"]
    assert next(r for r in rows if r["is_reply"])["reply_to"]["tweet_id"]
    assert next(r for r in rows if r["media"])["media"][0]["image"].startswith("https://pbs.twimg.com/")
    header = P.list_header(props["headerProps"])
    assert header["name"] == "Marvel/Star Wars" and header["owner"]["username"] == "nelligan_14"
    compact = P.tweet(fx("synd_tweet_result_video"))
    assert compact["id"] == "1671370010743263233" and compact["media"][0]["video_link"]
    assert compact["is_edited"] is True and len(compact["edit_tweet_ids"]) == 2
    assert compact["stats"]["replies"] is not None


def test_tweet_unavailable_and_junk():
    gone = P.tweet({"result": {"__typename": "TweetTombstone", "tombstone": {"text": {"text": "This Post was deleted"}}}})
    assert gone["is_available"] is False and "deleted" in gone["reason"]
    assert P.tweet(None) is None and P.tweet({}) is None and P.tweet({"result": None}) is None
    assert P.walk_timeline(None) == {"tweets": [], "users": [], "cursors": {"top": None, "bottom": None}, "modules": []}


# ---- small entities --------------------------------------------------------------------

def test_trends_lists_misc():
    trend = P.trend(fx("rest_trends_place")[0]["trends"][0])
    assert trend["name"] == "#RPETAbhiyaan" and trend["link"] == "https://x.com/search?q=%23RPETAbhiyaan"
    place = P.trend_location(fx("rest_trends_available")[1])
    assert place["woeid"] == 2972 and place["country_code"] == "CA" and place["parent_woeid"] == 23424775
    lst = P.twitter_list(fx("rest_lists_show"))
    _no_camel_or_url_keys(lst)
    assert lst["id"] == "1343798673386434560" and lst["members_count"] == 19 and lst["is_private"] is False
    assert lst["owner"]["username"] == "nelligan_14" and lst["created_at"] == "2020-12-29T05:59:04Z"
    rel = P.friendship(fx("rest_friendships_show"))
    assert rel["source_follows_target"] is True and rel["target_follows_source"] is False
    flag = P.hashflag(fx("rest_hashflags")[0])
    assert flag["image"].startswith("https://abs.twimg.com/hashflags/") and flag["starts_at"] == "2026-07-12T12:00:00Z"
    geo = P.geo_place(fx("rest_geo_search")["result"]["places"][0])
    assert geo["full_name"] == "Paris, France" and abs(geo["latitude"] - 48.8588) < 0.01
    emb = P.oembed(fx("oembed"), "2102207241101144450")
    assert emb["author_name"] == "Elon Musk" and emb["html"].startswith("<blockquote")


def test_value_helpers():
    assert P.iso_datetime("Tue Jun 02 20:12:29 +0000 2009") == "2009-06-02T20:12:29Z"
    assert P.iso_datetime("2023-06-21T04:10:37.000Z") == "2023-06-21T04:10:37Z"
    assert P.iso_datetime(1790040238000) == "2026-09-22T01:23:58Z"
    assert P.iso_datetime("garbage") is None and P.iso_datetime(None) is None
    assert P.source_name('<a href="x" rel="nofollow">Twitter Web App</a>') == "Twitter Web App"
    assert P.hd_profile_image("https://pbs.twimg.com/profile_images/1/a_normal.jpg") == "https://pbs.twimg.com/profile_images/1/a_400x400.jpg"
    assert P.expand_text("hi https://t.co/a https://t.co/b", [{"url": "https://t.co/a", "expanded_url": "https://e.com"}],
                         [{"url": "https://t.co/b"}]) == "hi https://e.com"


def test_trend_location_resolution(monkeypatch):
    rows = [P.trend_location(r) for r in fx("rest_trends_available")]
    monkeypatch.setattr(T, "_available", lambda: rows)
    assert T.resolve_location("1")["name"] == "Worldwide"
    assert T.resolve_location("IN")["woeid"] == 23424848
    assert T.resolve_location("india")["woeid"] == 23424848
    assert T.resolve_location("winnipeg")["woeid"] == 2972
    with pytest.raises(Exception):
        T.resolve_location("atlantis")
