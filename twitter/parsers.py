"""X / Twitter normalizers: the three raw spellings X uses for the same
entities -> one clean snake_case shape.

  * GraphQL results (guest / account persisted queries): User{rest_id,
    core, avatar, relationship_counts, …}, Tweet{rest_id, core, legacy,
    views, note_tweet, quoted_status_result, …}
  * the logged-out SSR pages' Relay records (twitter/relay.py): the same
    User; Tweet{rest_id, core, counts, views, details, media_entities2,
    url_entities, quoted_tweet_results, reply_to_results, …}
  * classic 1.1 objects (lists/show, recommendations, the syndication list
    timeline) and the syndication tweet-result widget JSON

Output conventions (shared with the other scrapers here): `link` for page
URLs, `image`/`profile_image`/`banner` for pictures, `*_count` inside
`stats`/user objects, `is_*`/`has_*` for booleans, ISO-8601 UTC
("2026-09-22T01:23:58Z") for timestamps, numbers as numbers, null for
missing. Tweet text has every t.co link expanded and the trailing media
links removed. Entity vocabulary:

  user   {id, username, name, link, bio, location, website, profile_image,
          banner, is_blue_verified, is_verified, verified_type, is_protected,
          affiliate, professional, followers_count, following_count,
          tweets_count, media_count, likes_count, listed_count,
          subscriptions_count, pinned_tweet_ids, is_possibly_sensitive,
          created_at}
  tweet  {id, link, text, language, created_at, author, is_pinned, is_reply,
          reply_to, is_quote, quoted_tweet, is_retweet, retweeted_tweet,
          conversation_id, media, links, hashtags, mentions, cashtags, card,
          poll, community, community_note, place, stats, is_long_form,
          is_possibly_sensitive, is_edited, edit_tweet_ids, source}

Deliberately dropped as noise: `__typename`, Relay `id` (base64 node ids),
`unmention_data`, `is_translatable` / grok translate blocks, `edit_control`
bookkeeping beyond the edit ids, `sort_index`, `client_event_info`,
`feedback_info`, `promoted_metadata` (promoted posts are skipped entirely),
`display_text_range`, `indices`, media `sizes` / `features` / `focus_rects`
/ `ext_media_availability`, card binding values that only style the card,
the viewer-relative flags (`favorited`, `retweeted`, `bookmarked`,
`following`, `blocking`, `muting`, `notifications`, `follow_request_sent`,
`can_dm`… — meaningless for an anonymous reader), `super_follow_*`,
`has_graduated_access`, `profile_image_shape`, `profile_interstitial_type`,
`media_permissions`, `translator_type`, `profile_sort_enabled`,
the legacy `utc_offset`/`time_zone`/`geo_enabled`/`contributors_enabled`/
`profile_background_*`/`profile_link_color` theme fields and `id` (int
duplicates of `id_str`).
"""
import html as html_lib
import re
from datetime import datetime, timezone

from twitter import refs

SITE = refs.SITE
_TWITTER_DATE = "%a %b %d %H:%M:%S %z %Y"
_SOURCE_RE = re.compile(r"<a[^>]*>(.*?)</a>", re.S)
_TCO_RE = re.compile(r"https?://t\.co/[A-Za-z0-9]+")


# ---- value helpers ------------------------------------------------------------------

def to_int(value):
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def to_float(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def text(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def bool_or_none(value):
    return value if isinstance(value, bool) else None


def as_dict(value):
    return value if isinstance(value, dict) else {}


def as_list(value):
    return value if isinstance(value, list) else []


def iso_datetime(value):
    """'Tue Jun 02 20:12:29 +0000 2009', '2023-06-21T04:10:37.000Z',
    1790040238000 (ms) or 1790040238 (s) -> '2009-06-02T20:12:29Z'."""
    if value in (None, "", 0):
        return None
    if isinstance(value, (int, float)):
        secs = value / 1000 if value > 10_000_000_000 else value
        try:
            return datetime.fromtimestamp(secs, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if raw.isdigit():
        return iso_datetime(int(raw))
    try:
        dt = datetime.strptime(raw, _TWITTER_DATE)
    except ValueError:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def source_name(value):
    """'<a href="…" rel="nofollow">Twitter for iPad</a>' -> 'Twitter for iPad'."""
    if not isinstance(value, str):
        return None
    match = _SOURCE_RE.search(value)
    return text(html_lib.unescape(match.group(1) if match else value))


def hd_profile_image(link):
    """…/xyz_normal.jpg -> …/xyz_400x400.jpg (the largest size X serves)."""
    if not isinstance(link, str) or not link:
        return None
    return re.sub(r"_(normal|bigger|mini|200x200)(\.[a-z]+)$", r"_400x400\2", link)


def expand_text(raw_text, url_entities, media_entities=()):
    """Replace t.co links with their expanded form and drop the trailing
    media links (the picture is in `media`)."""
    out = raw_text if isinstance(raw_text, str) else ""
    if not out:
        return None
    for media in media_entities or ():
        short = as_dict(media).get("url")
        if short:
            out = out.replace(short, "")
    for ent in url_entities or ():
        ent = as_dict(ent)
        short, expanded = ent.get("url"), ent.get("expanded_url")
        if short and expanded:
            out = out.replace(short, expanded)
    out = html_lib.unescape(out)
    return text(re.sub(r"[ \t]+\n", "\n", out)) or None


# ---- users --------------------------------------------------------------------------

def user_ref(raw):
    """Compact author card from any user spelling."""
    full = user(raw)
    if not full:
        return None
    keys = ("id", "username", "name", "link", "profile_image", "is_blue_verified", "is_verified",
            "followers_count")
    return {k: full.get(k) for k in keys}


def _affiliate_label(label):
    label = as_dict(label)
    if not label:
        return None
    badge = as_dict(label.get("badge"))
    link = as_dict(label.get("url")).get("url") if isinstance(label.get("url"), dict) else label.get("url")
    return {
        "name": text(label.get("description")),
        "badge_image": text(badge.get("url")),
        "link": text(link),
        "type": text(label.get("userLabelType") or label.get("user_label_type")),
    }


def _professional(raw):
    raw = as_dict(raw)
    if not raw:
        return None
    categories = [text(as_dict(c).get("name")) for c in as_list(raw.get("category"))]
    return {"type": text(raw.get("professional_type")),
            "categories": [c for c in categories if c]}


def _website(raw, legacy):
    """The profile website, expanded (profile_bio.entities.url in the new
    shape, legacy.entities.url in the old one, else the raw url)."""
    for block in (as_dict(raw.get("profile_bio")), legacy):
        urls = as_list(as_dict(as_dict(block.get("entities")).get("url")).get("urls"))
        if urls:
            first = as_dict(urls[0])
            return text(first.get("expanded_url") or first.get("url"))
    site = raw.get("website")
    if isinstance(site, dict):
        site = site.get("url")
    return text(site if isinstance(site, str) else legacy.get("url"))


def user(raw):
    """A GraphQL / SSR User result, or a classic 1.1 user object -> user
    dict; None for an unavailable/suspended user or junk."""
    raw = as_dict(raw)
    inner = raw.get("result")
    if isinstance(inner, dict) and ("core" in inner or "legacy" in inner or "screen_name" in inner
                                    or str(raw.get("__typename", "")).endswith("Results")):
        raw = inner                            # UserResults wrapper (SSR copies rest_id onto it)
    if not raw:
        return None
    if raw.get("__typename") == "UserUnavailable":
        return None
    if "rest_id" not in raw and "screen_name" in raw:
        return _classic_user(raw)
    core = as_dict(raw.get("core"))
    legacy = as_dict(raw.get("legacy"))
    username = text(core.get("screen_name") or legacy.get("screen_name"))
    if not username and not raw.get("rest_id"):
        return None
    bio_block = as_dict(raw.get("profile_bio"))
    bio_urls = as_list(as_dict(as_dict(bio_block.get("entities")).get("description")).get("urls")) \
        or as_list(as_dict(as_dict(legacy.get("entities")).get("description")).get("urls"))
    bio = expand_text(bio_block.get("description") or legacy.get("description"), bio_urls)
    counts = as_dict(raw.get("relationship_counts"))
    tweet_counts = as_dict(raw.get("tweet_counts"))
    verification = as_dict(raw.get("verification"))
    label = as_dict(as_dict(raw.get("affiliates_highlighted_label")).get("label")) or \
        as_dict(as_dict(raw.get("identity_profile_labels_highlighted_label")).get("label"))
    location = raw.get("location")
    if isinstance(location, dict):
        location = location.get("location")
    avatar = as_dict(raw.get("avatar")).get("image_url") or legacy.get("profile_image_url_https")
    banner = as_dict(raw.get("banner")).get("image_url") or legacy.get("profile_banner_url")
    is_blue = raw.get("is_blue_verified")
    if not isinstance(is_blue, bool):
        is_blue = verification.get("is_blue_verified")
    pinned = as_list(as_dict(raw.get("pinned_items")).get("tweet_ids_str")) or as_list(legacy.get("pinned_tweet_ids_str"))
    return {
        "id": text(raw.get("rest_id") or legacy.get("id_str")),
        "username": username,
        "name": text(core.get("name") or legacy.get("name")),
        "link": refs.user_link(username),
        "bio": bio,
        "location": text(location if isinstance(location, str) else legacy.get("location")),
        "website": _website(raw, legacy),
        "profile_image": hd_profile_image(avatar),
        "banner": text(banner),
        "is_blue_verified": bool_or_none(is_blue),
        "is_verified": bool_or_none(verification.get("verified") if "verified" in verification else legacy.get("verified")),
        "verified_type": text(verification.get("verified_type") or legacy.get("verified_type")),
        "is_protected": bool_or_none(as_dict(raw.get("privacy")).get("protected") if raw.get("privacy") else legacy.get("protected")),
        "affiliate": _affiliate_label(label),
        "professional": _professional(raw.get("professional")),
        "followers_count": to_int(counts.get("followers") if counts else legacy.get("followers_count")),
        "following_count": to_int(counts.get("following") if counts else legacy.get("friends_count")),
        "tweets_count": to_int(tweet_counts.get("tweets") if tweet_counts else legacy.get("statuses_count")),
        "media_count": to_int(tweet_counts.get("media_tweets") if "media_tweets" in tweet_counts else legacy.get("media_count")),
        "likes_count": to_int(as_dict(raw.get("action_counts")).get("favorites_count") if raw.get("action_counts") else legacy.get("favourites_count")),
        "listed_count": to_int(legacy.get("listed_count")),
        "subscriptions_count": to_int(raw.get("creator_subscriptions_count")),
        "pinned_tweet_ids": [text(p) for p in pinned if text(p)],
        "is_possibly_sensitive": bool_or_none(raw.get("possibly_sensitive")),
        "created_at": iso_datetime(core.get("created_at") or legacy.get("created_at")),
    }


def _classic_user(raw):
    """A 1.1 / syndication user object (screen_name, followers_count, …)."""
    username = text(raw.get("screen_name"))
    ents = as_dict(raw.get("entities"))
    bio_urls = as_list(as_dict(ents.get("description")).get("urls"))
    site_urls = as_list(as_dict(ents.get("url")).get("urls"))
    website = text(as_dict(site_urls[0]).get("expanded_url")) if site_urls else text(raw.get("url"))
    label = as_dict(raw.get("highlighted_label"))
    return {
        "id": text(raw.get("id_str") or raw.get("id")),
        "username": username,
        "name": text(raw.get("name")),
        "link": refs.user_link(username),
        "bio": expand_text(raw.get("description"), bio_urls),
        "location": text(raw.get("location")),
        "website": website,
        "profile_image": hd_profile_image(raw.get("profile_image_url_https")),
        "banner": text(raw.get("profile_banner_url")),
        "is_blue_verified": bool_or_none(raw.get("is_blue_verified")),
        "is_verified": bool_or_none(raw.get("verified")),
        "verified_type": text(raw.get("verified_type")),
        "is_protected": bool_or_none(raw.get("protected")),
        "affiliate": _affiliate_label(label) if label else None,
        "professional": None,
        "followers_count": to_int(raw.get("followers_count")),
        "following_count": to_int(raw.get("friends_count")),
        "tweets_count": to_int(raw.get("statuses_count")),
        "media_count": to_int(raw.get("media_count")),
        "likes_count": to_int(raw.get("favourites_count")),
        "listed_count": to_int(raw.get("listed_count")),
        "subscriptions_count": None,
        "pinned_tweet_ids": [text(p) for p in as_list(raw.get("pinned_tweet_ids_str")) if text(p)],
        "is_possibly_sensitive": None,
        "created_at": iso_datetime(raw.get("created_at")),
    }


# ---- media / entities ---------------------------------------------------------------

def media_item(raw):
    raw = as_dict(raw)
    kind = text(raw.get("type"))
    info = as_dict(raw.get("video_info"))
    variants = []
    for v in as_list(info.get("variants")):
        v = as_dict(v)
        if v.get("url"):
            variants.append({"link": v["url"], "bitrate": to_int(v.get("bitrate")),
                             "content_type": text(v.get("content_type"))})
    mp4s = [v for v in variants if (v["content_type"] or "").endswith("mp4")]
    best = max(mp4s, key=lambda v: v["bitrate"] or 0) if mp4s else None
    original = as_dict(raw.get("original_info"))
    return {
        "type": kind,
        "id": text(raw.get("id_str") or raw.get("media_key")),
        "link": text(raw.get("expanded_url")),
        "image": text(raw.get("media_url_https")),
        "width": to_int(original.get("width")),
        "height": to_int(original.get("height")),
        "alt_text": text(raw.get("ext_alt_text")),
        "duration_ms": to_int(info.get("duration_millis")) if kind in ("video", "animated_gif") else None,
        "video_link": best["link"] if best else None,
        "video_variants": variants or None,
    }


def link_entity(raw):
    raw = as_dict(raw)
    return {
        "link": text(raw.get("expanded_url") or raw.get("url")),
        "display_text": text(raw.get("display_url")),
    }


def mention_entity(raw):
    raw = as_dict(raw)
    username = text(raw.get("screen_name"))
    return {"id": text(raw.get("id_str")), "username": username, "name": text(raw.get("name")),
            "link": refs.user_link(username)}


def _tag_entity(raw):
    return text(as_dict(raw).get("text"))


def _card(raw):
    """A legacy card (link preview / poll / …) -> {type, title, description,
    link, image} + `poll` choices when it is a poll."""
    raw = as_dict(raw)
    legacy = as_dict(raw.get("legacy")) or raw
    name = text(legacy.get("name") or raw.get("name"))
    values = {}
    for row in as_list(legacy.get("binding_values")):
        row = as_dict(row)
        key = row.get("key")
        val = as_dict(row.get("value"))
        if not key:
            continue
        values[key] = (val.get("string_value") or val.get("boolean_value")
                       or as_dict(val.get("image_value")).get("url") or as_dict(val.get("user_value")).get("id_str"))
    if isinstance(legacy.get("binding_values"), dict):   # classic map spelling
        for key, val in legacy["binding_values"].items():
            val = as_dict(val)
            values[key] = (val.get("string_value") or val.get("boolean_value")
                           or as_dict(val.get("image_value")).get("url"))
    if not name and not values:
        return None, None
    poll = None
    if name and name.startswith("poll"):
        choices = []
        for i in range(1, 5):
            label = values.get(f"choice{i}_label")
            if label:
                choices.append({"label": text(label), "votes": to_int(values.get(f"choice{i}_count"))})
        total = sum(c["votes"] or 0 for c in choices)
        poll = {
            "choices": [dict(c, share=round((c["votes"] or 0) * 100 / total, 1) if total else None) for c in choices],
            "total_votes": total,
            "is_open": not bool(values.get("counts_are_final")),
            "ends_at": iso_datetime(values.get("end_datetime_utc")),
        }
    image = (values.get("photo_image_full_size_large") or values.get("summary_photo_image_large")
             or values.get("thumbnail_image_large") or values.get("player_image_large")
             or values.get("photo_image_full_size") or values.get("thumbnail_image"))
    card = {
        "type": name,
        "title": text(values.get("title")),
        "description": text(values.get("description")),
        "link": text(values.get("card_url") or raw.get("rest_id") or raw.get("url")),
        "domain": text(values.get("domain") or values.get("vanity_url")),
        "image": text(image) if isinstance(image, str) else None,
    }
    return card, poll


def _community_note(raw):
    raw = as_dict(raw)
    if not raw:
        return None
    note = as_dict(raw.get("note"))
    return {"title": text(raw.get("title")), "text": text(note.get("text")),
            "link": text(as_dict(raw.get("destinationUrl")).get("url") if isinstance(raw.get("destinationUrl"), dict) else raw.get("destinationUrl"))}


def _place(raw):
    raw = as_dict(raw)
    if not raw or not (raw.get("id") or raw.get("full_name") or raw.get("name")):
        return None
    return {"id": text(raw.get("id")), "name": text(raw.get("name")),
            "full_name": text(raw.get("full_name")), "country": text(raw.get("country")),
            "country_code": text(raw.get("country_code")), "type": text(raw.get("place_type"))}


def _community_ref(raw):
    result = as_dict(as_dict(raw).get("result")) or as_dict(raw)
    if not result:
        return None
    cid = text(result.get("id_str") or result.get("rest_id"))
    return {"id": cid, "name": text(result.get("name")), "link": refs.community_link(cid)}


# ---- posts (tweets) -------------------------------------------------------------------

def tweet_result(container):
    """tweet_results / quoted_status_result / … -> the inner Tweet result
    (unwrapping TweetWithVisibilityResults); None when absent."""
    container = as_dict(container)
    if "result" in container:
        result = as_dict(container.get("result"))     # {"result": null} = no tweet
    else:
        result = container
    if result.get("__typename") == "TweetWithVisibilityResults" or ("tweet" in result and "rest_id" not in result):
        result = as_dict(result.get("tweet"))
    if not result or not (result.get("rest_id") or result.get("id_str") or result.get("__typename")):
        return None
    return result


def _unavailable(raw):
    kind = raw.get("__typename")
    if kind in ("TweetUnavailable", "TweetTombstone"):
        reason = text(raw.get("reason")) or text(as_dict(as_dict(raw.get("tombstone")).get("text")).get("text"))
        return {"id": text(raw.get("rest_id")), "is_available": False, "reason": reason}
    return None


def tweet(raw, *, pinned=False, depth=0):
    """A GraphQL / SSR Tweet result, a classic 1.1 status or a syndication
    tweet-result -> tweet dict; None for junk. Nested quoted / retweeted tweets
    are normalized one level deep."""
    raw = tweet_result(raw)
    if not raw:
        return None
    gone = _unavailable(raw)
    if gone:
        return gone
    if "legacy" not in raw and "details" not in raw and ("full_text" in raw or "text" in raw):
        return _classic_or_syndication_tweet(raw, depth=depth)

    legacy = as_dict(raw.get("legacy"))
    details = as_dict(raw.get("details"))            # SSR spelling
    counts = as_dict(raw.get("counts")) or legacy      # SSR ApiCounts vs legacy counters
    tweet_id = text(raw.get("rest_id") or legacy.get("id_str"))
    author = user(as_dict(as_dict(raw.get("core")).get("user_results")))
    username = author.get("username") if author else None

    entities = as_dict(legacy.get("entities"))
    ext = as_dict(legacy.get("extended_entities"))
    media_raw = as_list(ext.get("media")) or as_list(entities.get("media")) or as_list(raw.get("media_entities2"))
    url_raw = as_list(entities.get("urls")) or as_list(raw.get("url_entities"))
    mention_raw = as_list(entities.get("user_mentions")) or as_list(raw.get("mention_entities"))
    hashtag_raw = as_list(entities.get("hashtags")) or as_list(details.get("hashtag_entities"))
    cashtag_raw = as_list(entities.get("symbols")) or as_list(details.get("cashtag_entities"))

    body = legacy.get("full_text") or details.get("full_text")
    note = as_dict(as_dict(as_dict(raw.get("note_tweet")).get("note_tweet_results")).get("result"))
    is_long_form = False
    if note.get("text"):
        body = note["text"]
        is_long_form = True
        note_ents = as_dict(note.get("entity_set"))
        url_raw = as_list(note_ents.get("urls")) or url_raw
        mention_raw = as_list(note_ents.get("user_mentions")) or mention_raw
        hashtag_raw = as_list(note_ents.get("hashtags")) or hashtag_raw
        cashtag_raw = as_list(note_ents.get("symbols")) or cashtag_raw
    article = as_dict(as_dict(as_dict(raw.get("article")).get("article_results")).get("result"))
    if article.get("title") and not is_long_form:
        is_long_form = True

    # relationships
    retweeted = None
    rt_container = legacy.get("retweeted_status_result") or legacy.get("retweeted_status_results")
    if rt_container and depth < 2:
        retweeted = tweet(rt_container, depth=depth + 1)
    quoted = None
    q_container = raw.get("quoted_status_result") or raw.get("quoted_tweet_results")
    if q_container and depth < 2:
        quoted = tweet(q_container, depth=depth + 1)
    reply_to = None
    parent = as_dict(raw.get("reply_to_results"))
    parent_user = as_dict(raw.get("reply_to_user_results"))
    if legacy.get("in_reply_to_status_id_str") or parent.get("result"):
        parent_tweet = tweet_result(parent) or {}
        parent_author = user(as_dict(as_dict(parent_tweet.get("core")).get("user_results"))) if parent_tweet else None
        if not parent_author and parent_user:
            parent_author = user(parent_user)
        p_username = (parent_author or {}).get("username") or text(legacy.get("in_reply_to_screen_name"))
        p_id = text(legacy.get("in_reply_to_status_id_str") or parent_tweet.get("rest_id"))
        reply_to = {
            "tweet_id": p_id,
            "user_id": (parent_author or {}).get("id") or text(legacy.get("in_reply_to_user_id_str")),
            "username": p_username,
            "link": refs.tweet_link(p_username, p_id),
        }

    card, poll = _card(raw.get("card"))
    views = as_dict(raw.get("views")).get("count")
    body_text = expand_text(body, url_raw, media_raw)
    text_range = as_list(legacy.get("display_text_range") or details.get("display_text_range"))
    if body_text and not is_long_form and media_raw and len(text_range) == 2 and isinstance(body, str):
        # the trailing pic.x.com link has no url entity in the SSR spelling:
        # cut at the display range end (code points, like Python indexes)
        end = to_int(text_range[1])
        if end is not None and end < len(body) and _TCO_RE.search(body[end:]):
            body_text = expand_text(body[:end], url_raw, media_raw)
    if retweeted and retweeted.get("text"):
        body_text = retweeted["text"]
    edit = as_dict(raw.get("edit_control"))
    edit_ids = [text(e) for e in as_list(edit.get("edit_tweet_ids") or as_dict(edit.get("edit_control_initial")).get("edit_tweet_ids")) if text(e)]
    place = _place(legacy.get("place") or raw.get("place"))
    created = legacy.get("created_at") or details.get("created_at_ms")
    link = refs.tweet_link(username, tweet_id)
    media = [media_item(m) for m in media_raw]
    for i, item in enumerate(media, 1):        # SSR media carry no page link
        if not item["link"] and link:
            item["link"] = f"{link}/{'photo' if item['type'] == 'photo' else 'video'}/{i}"

    return {
        "id": tweet_id,
        "link": link,
        "text": body_text,
        "language": text(legacy.get("lang") or details.get("lang")),
        "created_at": iso_datetime(created),
        "author": user_ref(as_dict(as_dict(raw.get("core")).get("user_results"))),
        "is_pinned": bool(pinned),
        "is_reply": reply_to is not None,
        "reply_to": reply_to,
        "is_quote": quoted is not None or bool(legacy.get("is_quote_status")),
        "quoted_tweet": quoted,
        "is_retweet": retweeted is not None,
        "retweeted_tweet": retweeted,
        "conversation_id": text(legacy.get("conversation_id_str")),
        "media": media,
        "links": [link_entity(u) for u in url_raw if as_dict(u).get("expanded_url") or as_dict(u).get("url")],
        "hashtags": [h for h in (_tag_entity(h) for h in hashtag_raw) if h],
        "mentions": [mention_entity(m) for m in mention_raw],
        "cashtags": [c for c in (_tag_entity(c) for c in cashtag_raw) if c],
        "card": card,
        "poll": poll,
        "community": _community_ref(raw.get("community_results")),
        "community_note": _community_note(raw.get("birdwatch_pivot")),
        "place": place,
        "stats": {
            "replies": to_int(counts.get("reply_count")),
            "retweets": to_int(counts.get("retweet_count")),
            "likes": to_int(counts.get("favorite_count")),
            "quotes": to_int(counts.get("quote_count")),
            "bookmarks": to_int(counts.get("bookmark_count")),
            "views": to_int(views),
        },
        "is_long_form": is_long_form,
        "is_possibly_sensitive": bool_or_none(legacy.get("possibly_sensitive")),
        "is_edited": len(edit_ids) > 1 if edit_ids else False,
        "edit_tweet_ids": edit_ids if len(edit_ids) > 1 else [],
        "source": source_name(raw.get("source")),
    }


def _classic_or_syndication_tweet(raw, depth=0):
    """Classic 1.1 status (syndication list timeline) or the syndication
    tweet-result widget JSON."""
    author = user(raw.get("user"))
    username = author.get("username") if author else None
    tweet_id = text(raw.get("id_str"))
    entities = as_dict(raw.get("entities"))
    media_raw = as_list(as_dict(raw.get("extended_entities")).get("media")) or as_list(raw.get("mediaDetails")) \
        or as_list(entities.get("media"))
    url_raw = as_list(entities.get("urls"))
    retweeted = tweet(raw["retweeted_status"], depth=depth + 1) if isinstance(raw.get("retweeted_status"), dict) and depth < 2 else None
    quoted_raw = raw.get("quoted_status") or raw.get("quoted_tweet")
    quoted = tweet(quoted_raw, depth=depth + 1) if isinstance(quoted_raw, dict) and depth < 2 else None
    reply_to = None
    parent = as_dict(raw.get("parent"))
    if raw.get("in_reply_to_status_id_str") or parent:
        p_id = text(raw.get("in_reply_to_status_id_str") or parent.get("id_str"))
        p_user = text(raw.get("in_reply_to_screen_name") or as_dict(parent.get("user")).get("screen_name"))
        reply_to = {"tweet_id": p_id, "user_id": text(raw.get("in_reply_to_user_id_str") or as_dict(parent.get("user")).get("id_str")),
                    "username": p_user, "link": refs.tweet_link(p_user, p_id)}
    card, poll = _card(raw.get("card"))
    edit = as_dict(raw.get("edit_control"))
    edit_ids = [text(e) for e in as_list(edit.get("edit_tweet_ids")) if text(e)]
    body_text = expand_text(raw.get("full_text") or raw.get("text"), url_raw, media_raw)
    if retweeted and retweeted.get("text"):
        body_text = retweeted["text"]          # the RT line is truncated upstream
    return {
        "id": tweet_id,
        "link": refs.tweet_link(username, tweet_id),
        "text": body_text,
        "language": text(raw.get("lang")),
        "created_at": iso_datetime(raw.get("created_at")),
        "author": user_ref(raw.get("user")),
        "is_pinned": False,
        "is_reply": reply_to is not None,
        "reply_to": reply_to,
        "is_quote": quoted is not None or bool(raw.get("is_quote_status")),
        "quoted_tweet": quoted,
        "is_retweet": retweeted is not None,
        "retweeted_tweet": retweeted,
        "conversation_id": text(raw.get("conversation_id_str")),
        "media": [media_item(m) for m in media_raw],
        "links": [link_entity(u) for u in url_raw if as_dict(u).get("expanded_url") or as_dict(u).get("url")],
        "hashtags": [h for h in (_tag_entity(h) for h in as_list(entities.get("hashtags"))) if h],
        "mentions": [mention_entity(m) for m in as_list(entities.get("user_mentions"))],
        "cashtags": [c for c in (_tag_entity(c) for c in as_list(entities.get("symbols"))) if c],
        "card": card,
        "poll": poll,
        "community": None,
        "community_note": None,
        "place": _place(raw.get("place")),
        "stats": {
            "replies": to_int(raw.get("reply_count") if "reply_count" in raw else raw.get("conversation_count")),
            "retweets": to_int(raw.get("retweet_count")),
            "likes": to_int(raw.get("favorite_count")),
            "quotes": to_int(raw.get("quote_count")),
            "bookmarks": to_int(raw.get("bookmark_count")),
            "views": to_int(raw.get("view_count")),
        },
        "is_long_form": False,
        "is_possibly_sensitive": bool_or_none(raw.get("possibly_sensitive")),
        "is_edited": bool(raw.get("isEdited")) or len(edit_ids) > 1,
        "edit_tweet_ids": edit_ids if len(edit_ids) > 1 else [],
        "source": source_name(raw.get("source")),
    }


# ---- timelines ------------------------------------------------------------------------

def _entry_id(entry):
    return as_dict(entry).get("entryId") or as_dict(entry).get("entry_id") or ""


def _item_content(content):
    """TimelineTimelineItem content -> its TimelineTweet / TimelineUser
    payload, in either spelling (GraphQL itemContent / SSR content)."""
    content = as_dict(content)
    inner = content.get("itemContent")
    if inner is None:
        inner = content.get("content")
    return as_dict(inner)


def _module_items(content):
    out = []
    for row in as_list(as_dict(content).get("items")):
        row = as_dict(row)
        item = as_dict(row.get("item"))
        out.append((row.get("entryId") or row.get("entry_id") or "", _item_content(item)))
    return out


def _tweet_of_item(payload, pinned=False):
    payload = as_dict(payload)
    kind = payload.get("itemType") or payload.get("__typename") or ""
    if payload.get("promotedMetadata") or payload.get("promoted_metadata"):
        return None
    if "tweet_results" in payload or kind == "TimelineTweet":
        social = as_dict(payload.get("socialContext") or payload.get("social_context"))
        is_pinned = pinned or social.get("contextType") == "Pin" or social.get("context_type") == "Pin"
        return tweet(payload.get("tweet_results"), pinned=is_pinned)
    return None


def _user_of_item(payload):
    payload = as_dict(payload)
    if "user_results" in payload:
        return user(payload.get("user_results"))
    return None


def instructions_of(timeline):
    """A `timeline` container in any spelling -> its instructions list."""
    node = as_dict(timeline)
    for _ in range(4):
        if "instructions" in node:
            return as_list(node.get("instructions"))
        inner = node.get("timeline") or node.get("timeline_v2") or node.get("result")
        if not isinstance(inner, dict):
            break
        node = inner
    return []


def _instruction_type(instr):
    return as_dict(instr).get("type") or as_dict(instr).get("__typename") or ""


def _cursor_value(content):
    content = as_dict(content)
    payload = _item_content(content) if "itemContent" in content or "content" in content else content
    kind = (content.get("entryType") or content.get("__typename") or payload.get("itemType")
            or payload.get("__typename") or "")
    if "Cursor" in kind or content.get("cursorType") or payload.get("cursorType"):
        return text(content.get("value") or payload.get("value")), \
            text(content.get("cursorType") or payload.get("cursorType") or content.get("cursor_type"))
    return None, None


def walk_timeline(timeline):
    """-> {"tweets": [...], "users": [...], "cursors": {"top", "bottom"},
    "modules": [[tweets per conversation module], ...]} over every
    TimelinePinEntry / TimelineAddEntries / TimelineAddToModule /
    TimelineReplaceEntry instruction, in order; promoted entries and
    who-to-follow shelves skipped."""
    tweets, users, modules = [], [], []
    cursors = {"top": None, "bottom": None}
    seen = set()

    def take_tweet(payload, pinned=False):
        post = _tweet_of_item(payload, pinned=pinned)
        if post and post.get("id") and post["id"] not in seen:
            seen.add(post["id"])
            tweets.append(post)
            return post
        return None

    def take_entry(entry, pinned=False):
        eid = _entry_id(entry)
        content = as_dict(as_dict(entry).get("content"))
        if eid.startswith(("promoted", "promotedTweet", "who-to-follow", "whoToFollow", "messageprompt",
                           "relevance", "toptabsrpusermodule", "tweetdetailrelatedtweets", "bottom-cursor-label")):
            return
        value, kind = _cursor_value(content)
        if value:
            key = "top" if (kind or "").lower() == "top" or "cursor-top" in eid else "bottom"
            if key == "bottom" and cursors["bottom"] and "showmore" in eid.lower():
                return
            cursors[key] = value
            return
        kind_name = content.get("entryType") or content.get("__typename") or ""
        if kind_name == "TimelineTimelineModule" or "items" in content:
            group = []
            for item_id, payload in _module_items(content):
                value, ckind = _cursor_value(payload)
                if value:
                    continue
                post = take_tweet(payload)
                if post:
                    group.append(post)
                person = _user_of_item(payload)
                if person:
                    users.append(person)
            if group:
                modules.append(group)
            return
        payload = _item_content(content)
        take_tweet(payload, pinned=pinned)
        person = _user_of_item(payload)
        if person:
            users.append(person)

    for instr in instructions_of(timeline):
        kind = _instruction_type(instr)
        if kind == "TimelinePinEntry":
            take_entry(as_dict(instr).get("entry"), pinned=True)
        elif kind in ("TimelineAddEntries",):
            for entry in as_list(as_dict(instr).get("entries")):
                take_entry(entry)
        elif kind == "TimelineReplaceEntry":
            take_entry(as_dict(instr).get("entry"))
        elif kind == "TimelineAddToModule":
            group = []
            for row in as_list(as_dict(instr).get("moduleItems") or as_dict(instr).get("module_items")):
                payload = _item_content(as_dict(as_dict(row).get("item")))
                post = take_tweet(payload)
                if post:
                    group.append(post)
            if group:
                modules.append(group)
    return {"tweets": tweets, "users": users, "cursors": cursors, "modules": modules}


# ---- trends / lists / communities / misc ---------------------------------------------

def trend(raw):
    raw = as_dict(raw)
    name = text(raw.get("name"))
    query = text(raw.get("query")) or name
    return {
        "name": name,
        "query": query,
        "link": f"{SITE}/search?q={query}" if query else None,
        "tweets_count": to_int(raw.get("tweet_volume")),
        "is_promoted": raw.get("promoted_content") is not None,
    }


def trend_location(raw):
    raw = as_dict(raw)
    place_type = as_dict(raw.get("placeType"))
    return {
        "woeid": to_int(raw.get("woeid")),
        "name": text(raw.get("name")),
        "type": text(place_type.get("name")),
        "country": text(raw.get("country")),
        "country_code": text(raw.get("countryCode")),
        "parent_woeid": to_int(raw.get("parentid")),
    }


def twitter_list(raw):
    raw = as_dict(raw)
    list_id = text(raw.get("id_str") or raw.get("id"))
    return {
        "id": list_id,
        "name": text(raw.get("name")),
        "slug": text(raw.get("slug")),
        "link": refs.list_link(list_id),
        "description": text(raw.get("description")),
        "is_private": raw.get("mode") == "private",
        "members_count": to_int(raw.get("member_count")),
        "subscribers_count": to_int(raw.get("subscriber_count")),
        "created_at": iso_datetime(raw.get("created_at")),
        "owner": user_ref(raw.get("user")),
    }


def list_header(props):
    """The syndication list embed's headerProps -> partial list dict."""
    props = as_dict(props)
    owner = as_dict(props.get("owner"))
    username = text(owner.get("screenName"))
    return {
        "name": text(props.get("name")),
        "members_count": to_int(props.get("memberCount")),
        "owner": {
            "id": None, "username": username, "name": text(owner.get("name")),
            "link": refs.user_link(username),
            "profile_image": hd_profile_image(owner.get("profileImageUrl")),
            "is_blue_verified": bool_or_none(owner.get("isBlueVerified")),
            "is_verified": bool_or_none(owner.get("isVerified")), "followers_count": None,
        } if username else None,
    }


def community(loader, records_result=None):
    """The community page's router loader data (+ its Relay record) ->
    community dict."""
    loader = as_dict(loader)
    cid = text(loader.get("restId")) or text(as_dict(records_result).get("rest_id"))
    banner = as_dict(loader.get("image"))
    creator_username = text(loader.get("creatorScreenName"))
    return {
        "id": cid,
        "name": text(loader.get("metaTitle") or loader.get("name")),
        "link": refs.community_link(cid),
        "description": text(loader.get("description")),
        "members_count": to_int(loader.get("memberCount")),
        "tweets_count": to_int(loader.get("postCount")) or None,
        "join_policy": text(loader.get("joinPolicy")),
        "primary_topic": text(loader.get("primaryTopic")),
        "is_nsfw": bool_or_none(loader.get("isNsfw")),
        "banner": {"link": text(banner.get("url")), "width": to_int(banner.get("width")),
                   "height": to_int(banner.get("height"))} if banner.get("url") else None,
        "creator": {"username": creator_username, "name": text(loader.get("creatorName")),
                    "link": refs.user_link(creator_username)} if creator_username else None,
        "member_avatars": [hd_profile_image(u) for u in as_list(loader.get("facepileUrls")) if isinstance(u, str)],
        "created_at": iso_datetime(loader.get("createdAtMs")),
    }


def profile_loader(loader):
    """The profile page's router loader data -> the few fields the Relay
    store lacks (creation date, availability)."""
    loader = as_dict(loader)
    return {
        "created_at": iso_datetime(loader.get("createdAtMs")),
        "status": text(loader.get("profileStatus")),
        "is_unavailable": bool_or_none(loader.get("isUnavailable")),
        "has_highlights": bool_or_none(loader.get("hasHighlights")),
        "affiliates_count": to_int(loader.get("affiliatesCount")),
    }


def friendship(raw):
    rel = as_dict(as_dict(raw).get("relationship"))
    source, target = as_dict(rel.get("source")), as_dict(rel.get("target"))

    def side(node):
        username = text(node.get("screen_name"))
        return {"id": text(node.get("id_str")), "username": username, "link": refs.user_link(username)}

    return {
        "source": side(source),
        "target": side(target),
        "source_follows_target": bool_or_none(source.get("following")),
        "target_follows_source": bool_or_none(source.get("followed_by")),
        "can_dm": bool_or_none(source.get("can_dm")),
    }


def hashflag(raw):
    raw = as_dict(raw)
    return {
        "hashtag": text(raw.get("hashtag")),
        "image": text(raw.get("asset_url")),
        "starts_at": iso_datetime(raw.get("starting_timestamp_ms")),
        "ends_at": iso_datetime(raw.get("ending_timestamp_ms")),
        "has_hashfetti": bool_or_none(raw.get("is_hashfetti_enabled")),
    }


def geo_place(raw):
    raw = as_dict(raw)
    centroid = as_list(raw.get("centroid"))
    box = as_dict(raw.get("bounding_box"))
    coords = as_list(as_list(box.get("coordinates"))[0] if as_list(box.get("coordinates")) else None)
    return {
        "id": text(raw.get("id")),
        "name": text(raw.get("name")),
        "full_name": text(raw.get("full_name")),
        "type": text(raw.get("place_type")),
        "country": text(raw.get("country")),
        "country_code": text(raw.get("country_code")),
        "latitude": to_float(centroid[1]) if len(centroid) == 2 else None,
        "longitude": to_float(centroid[0]) if len(centroid) == 2 else None,
        "bounding_box": [[to_float(p[0]), to_float(p[1])] for p in coords if isinstance(p, list) and len(p) == 2] or None,
        "contained_within": [text(as_dict(c).get("full_name")) for c in as_list(raw.get("contained_within"))],
    }


def oembed(raw, tweet_id):
    raw = as_dict(raw)
    return {
        "id": tweet_id,
        "link": text(raw.get("url")),
        "author_name": text(raw.get("author_name")),
        "author_link": text(raw.get("author_url")),
        "html": raw.get("html"),
        "width": to_int(raw.get("width")),
        "height": to_int(raw.get("height")),
    }
