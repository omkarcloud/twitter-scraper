"""Marshmallow request schemas for every /twitter/* route. Generic fields
come from the shared schema_fields.py; this module adds the X resolvers.
Every schema's load() output is the kwargs dict its endpoint function takes.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair):

    user       a username (elonmusk, @elonmusk), a numeric user id, or any
               x.com / twitter.com profile link
    users      comma-separated usernames / ids / links (max 20)
    tweet      a post id OR any x.com / twitter.com post link
    tweets     comma-separated post ids / links (max 20)
    list       a list id, an x.com/i/lists/<id> link or an
               x.com/<owner>/lists/<slug> link
    community  a community id or an x.com/i/communities/<id> link
    location   a WOEID (1 = worldwide), a country code (IN) or a place name
"""
from schema_fields import BaseSchema, Flag, PageSizeField, QueryField, RefField, StrippedString
from twitter import refs


# ---- id-or-link fields -------------------------------------------------------------

class UserField(RefField):
    resolver = staticmethod(refs.resolve_user)


class UsersField(RefField):
    resolver = staticmethod(refs.resolve_users)


class TweetField(RefField):
    resolver = staticmethod(refs.resolve_tweet)


class TweetsField(RefField):
    resolver = staticmethod(refs.resolve_tweets)


class ListField(RefField):
    resolver = staticmethod(refs.resolve_list)


class CommunityField(RefField):
    resolver = staticmethod(refs.resolve_community)


class CursorField(StrippedString):
    """Opaque next_cursor from the previous page (absent = first page)."""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)


class CountField(PageSizeField):
    """Results per page (default 20, max 100)."""

    def __init__(self, default=20, max_size=100, **kwargs):
        super().__init__(default=default, max_size=max_size, **kwargs)


class LocationField(StrippedString):
    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", "1")
        super().__init__(**kwargs)


class EmptySchema(BaseSchema):
    pass


class UserSchema(BaseSchema):
    user = UserField()


class UsersSchema(BaseSchema):
    users = UsersField()


class UserTweetsSchema(BaseSchema):
    user = UserField()
    count = CountField(default=20, max_size=100)


class HighlightsSchema(BaseSchema):
    user = UserField()
    count = CountField(default=20, max_size=100)
    cursor = CursorField()


class TopTweetsSchema(BaseSchema):
    user = UserField()
    count = CountField(default=20, max_size=100)


class RecommendationsSchema(BaseSchema):
    user = UserField()
    count = CountField(default=20, max_size=50)


class CheckFollowSchema(BaseSchema):
    source = UserField()
    target = UserField()


class TweetSchema(BaseSchema):
    tweet = TweetField()


class TweetsSchema(BaseSchema):
    tweets = TweetsField()


class RepliesSchema(BaseSchema):
    tweet = TweetField()
    count = CountField(default=20, max_size=100)


class TrendsSchema(BaseSchema):
    location = LocationField()
    exclude_hashtags = Flag(load_default=False)


class LocationsSchema(BaseSchema):
    query = QueryField(required=False, load_default=None)


class PlacesSchema(BaseSchema):
    query = QueryField()


class ListSchema(BaseSchema):
    list = ListField()


class ListTweetsSchema(BaseSchema):
    list = ListField()
    count = CountField(default=50, max_size=100)


class CommunitySchema(BaseSchema):
    community = CommunityField()


class CommunityTweetsSchema(BaseSchema):
    community = CommunityField()
    count = CountField(default=20, max_size=100)


