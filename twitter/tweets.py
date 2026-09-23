"""/twitter/tweets/* — one post, batches, the reply threads under a post,
the author's thread (parents + continuation) and the embed HTML, all from
X's public surfaces. Every function takes a resolved tweet id."""
from twitter import parsers as P
from twitter import refs, relay, shared
from twitter.fetch import (TwitterLoginWalled, TwitterNotFound, graphql, oembed, run_parallel,
                           syndication_tweet)


def _result_by_id(tweet_id):
    """Raw guest GraphQL TweetResultByRestId result (None when X hides it)."""
    data = graphql("TweetResultByRestId", {"tweetId": tweet_id, "withCommunity": True,
                                           "includePromotedContent": False, "withVoice": False},
                   label=f"tweet {tweet_id}")
    return P.tweet_result((data or {}).get("tweetResult")) if isinstance(data, dict) else None


def details(tweet):
    """Everything about one post: text, media with video links, counts,
    views, author, quoted / replied post, card, poll, community note."""
    result = _result_by_id(tweet)
    if result:
        parsed = P.tweet(result)
        if parsed and parsed.get("is_available", True) and parsed.get("id"):
            return {"tweet": parsed}
        if parsed and parsed.get("is_available") is False:
            raise TwitterNotFound(f"tweet {tweet} is unavailable ({parsed.get('reason') or 'removed or protected'})")
    # the embed widget still answers for posts the GraphQL result omits
    compact = syndication_tweet(tweet)
    if not compact:
        raise TwitterNotFound(f"tweet {tweet} not found")
    return {"tweet": P.tweet(compact)}


def details_batch(tweets):
    """Up to 20 posts in one call; a missing post yields {"id", "error"}."""
    def one(tweet_id):
        def run():
            try:
                return details(tweet_id)["tweet"]
            except TwitterNotFound as e:
                return {"id": tweet_id, "error": str(e)}
        return run
    rows = run_parallel([one(t) for t in tweets])
    return {"count": len(rows), "tweets": rows}


# ---- SSR status page ------------------------------------------------------------------

def _status_page(tweet_id, username=None):
    """The server-rendered post page -> (root, matches). X needs the
    author's username in the path; /i/status/<id> redirects there."""
    path = f"/{username}/status/{tweet_id}" if username else f"/i/status/{tweet_id}"
    records, matches = shared.ssr_page(path, f"tweet {tweet_id} page")
    return relay.root(records), matches


def _status_root(tweet_id):
    try:
        root, matches = _status_page(tweet_id)
    except (TwitterNotFound, TwitterLoginWalled):
        author = (details(tweet_id)["tweet"].get("author") or {}).get("username")
        if not author:
            raise TwitterNotFound(f"tweet {tweet_id} not found")
        root, matches = _status_page(tweet_id, author)
    focal_raw = root.get("tweet_result_by_rest_id")
    focal = P.tweet(focal_raw) if focal_raw else None
    if not focal or not focal.get("id"):
        raise TwitterNotFound(f"tweet {tweet_id} not found")
    return root, matches, focal, focal_raw


def replies(tweet, count=20):
    """The reply threads X server-renders on the logged-out post page (the
    first few, in X's relevance order; X shows a visitor no more without a
    login, so there is no cursor)."""
    root, matches, focal, _ = _status_root(tweet)
    walk = P.walk_timeline(root.get("threaded_conversation_with_injections_v2") or {})
    rows = [t for t in walk["tweets"] if t.get("id") != tweet][:count]
    loader = shared.loader_of(matches, "status")
    total = P.to_int(((loader.get("metadata") or {}).get("replyCount")) if isinstance(loader, dict) else None)
    return {"tweet": focal, "count": len(rows), "total_replies": total or (focal.get("stats") or {}).get("replies"),
            "has_more": False,
            "note": "X shows a logged-out visitor only the first reply threads of a post.",
            "replies": rows}


def thread(tweet):
    """The post in its thread: the parent chain above it (oldest first), the
    post itself and the author's own continuation below it."""
    root, matches, focal, focal_raw = _status_root(tweet)
    parents = []
    node = P.tweet_result(focal_raw) or {}
    seen = {focal.get("id")}
    while node:
        parent = P.tweet_result(node.get("reply_to_results"))
        if not parent or not parent.get("rest_id") or parent["rest_id"] in seen:
            break
        seen.add(parent["rest_id"])
        parsed = P.tweet(parent)
        if parsed:
            parents.append(parsed)
        node = parent
    parents.reverse()
    author_id = (focal.get("author") or {}).get("id")
    walk = P.walk_timeline(root.get("threaded_conversation_with_injections_v2") or {})
    continuation = []
    for group in walk["modules"]:
        for post in group:
            if post.get("id") in seen:
                continue
            if author_id and (post.get("author") or {}).get("id") == author_id:
                continuation.append(post)
                seen.add(post.get("id"))
    # a self-thread module can also arrive as top-level entries (older pages)
    for post in walk["tweets"]:
        if post.get("id") not in seen and author_id and (post.get("author") or {}).get("id") == author_id \
                and (post.get("reply_to") or {}).get("user_id") == author_id:
            continuation.append(post)
            seen.add(post.get("id"))
    return {
        "tweet": focal,
        "parents_count": len(parents),
        "parents": parents,
        "continuation_count": len(continuation),
        "continuation": continuation,
    }


def embed(tweet):
    """The official embed (oEmbed) HTML for a post."""
    body = oembed(f"{refs.SITE}/i/status/{tweet}")     # the /i/web/ form is refused
    if not isinstance(body, dict) or not body.get("html"):
        raise TwitterNotFound(f"tweet {tweet} not found")
    return P.oembed(body, tweet)
