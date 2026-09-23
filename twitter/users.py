"""/twitter/users/* — profiles, latest / most-liked posts, highlights,
follow checks and suggested accounts, all from X's public (logged-out)
surfaces. Every function takes a resolved `user` ref ({"screen_name"} or
{"user_id"}, refs.py)."""
from twitter import parsers as P
from twitter import relay, shared
from twitter.fetch import TwitterNotFound, graphql, rest, run_parallel

# guest UserTweets answers the ~99 most-liked posts, ignores the cursor
TOP_TWEETS_MAX = 100


def profile(user):
    """The full profile card (guest GraphQL UserByScreenName)."""
    name = shared.screen_name_of(user)
    result = shared.user_result(name)
    return {"user": P.user(result)}


def profiles(users):
    """Up to 20 profiles in one call; a user that does not exist yields
    {"user": <as given>, "error": "not found"} instead of failing the batch."""
    def one(ref):
        def run():
            try:
                return profile(ref)["user"]
            except TwitterNotFound as e:
                return {"user": ref.get("screen_name") or ref.get("user_id"), "error": str(e)}
        return run
    results = run_parallel([one(r) for r in users])
    return {"count": len(results), "users": results}


def tweets(user, count=20):
    """The user's latest posts, newest first: the pinned post + the latest
    original posts X server-renders on the logged-out profile page (X shows
    a visitor no more without a login, so there is no cursor)."""
    name = shared.screen_name_of(user)
    records, matches = shared.ssr_page(f"/{name}", f"@{name} page")
    root = relay.root(records)
    result = (root.get("user_result_by_screen_name") or {}).get("result") or {}
    timeline = result.get("profile_user_originals_timeline")
    if not timeline:
        raise TwitterNotFound(f"@{name}: no public posts (unknown, protected or suspended account)")
    walk = P.walk_timeline(timeline)
    rows = walk["tweets"][:count]
    return {"user": name, "count": len(rows), "has_more": False,
            "note": "X shows a logged-out visitor the pinned post and the latest original posts only; "
                    "use /twitter/users/top-tweets for the most-liked posts.",
            "tweets": rows}


def top_tweets(user, count=20):
    """The user's most-liked posts (up to ~100), best first — the "top
    tweets" ranking X serves guests for a profile."""
    uid = shared.user_id_of(user)
    data = graphql("UserTweets", {"userId": uid, "count": TOP_TWEETS_MAX, "includePromotedContent": False,
                                  "withQuickPromoteEligibilityTweetFields": False, "withVoice": True},
                   label=f"{shared.user_label(user)} top tweets")
    walk = P.walk_timeline(shared.find_instructions(data) or {})
    rows = [t for t in walk["tweets"] if not t.get("is_pinned")]
    rows.sort(key=lambda t: (t.get("stats") or {}).get("likes") or 0, reverse=True)
    rows = rows[:count]
    return {"user": user.get("screen_name") or uid, "count": len(rows), "tweets": rows}


def highlights(user, count=20, cursor=None):
    """The posts the user pinned to their Highlights tab (Premium feature)."""
    uid = shared.user_id_of(user)
    variables = {"userId": uid, "count": count, "includePromotedContent": False, "withVoice": True}
    if cursor:
        variables["cursor"] = cursor
    pg = shared.timeline_page("UserHighlightsTweets", variables,
                              label=f"{shared.user_label(user)} highlights")
    return {"user": user.get("screen_name") or uid, "count": pg["count"], "next_cursor": pg["next_cursor"],
            "has_more": pg["has_more"], "tweets": pg["items"]}


def check_follow(source, target):
    """Does `source` follow `target` (and the reverse)? One open 1.1 call."""
    params = {}
    for prefix, ref in (("source", source), ("target", target)):
        if ref.get("screen_name"):
            params[f"{prefix}_screen_name"] = ref["screen_name"]
        else:
            params[f"{prefix}_id"] = ref["user_id"]
    try:
        body = rest("/1.1/friendships/show.json", params, label="friendship")
    except TwitterNotFound:
        raise TwitterNotFound("one of the two users does not exist")
    if not isinstance(body, dict) or "relationship" not in body:
        raise TwitterNotFound("one of the two users does not exist")
    return P.friendship(body)


def recommendations(user, count=20):
    """Accounts X suggests next to this profile ("You might like")."""
    uid = shared.user_id_of(user)
    body = rest("/1.1/users/recommendations.json", {"user_id": uid, "limit": count, "pc": "true",
                                                    "display_location": "profile_accounts_sidebar"},
                label=f"{shared.user_label(user)} recommendations")
    rows = [P.user(r.get("user")) for r in (body if isinstance(body, list) else []) if isinstance(r, dict)]
    rows = [r for r in rows if r]
    return {"user": user.get("screen_name") or uid, "count": len(rows), "users": rows}
