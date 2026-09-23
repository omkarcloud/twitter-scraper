"""The 20 Twitter endpoints. Every path is served with and without the
`/twitter` prefix, so code generated against the hosted API on RapidAPI (paths
like /tweets/details) runs unchanged against this server.

Params are validated by the marshmallow schemas in twitter/schemas.py: ONE
param per input — `user` takes a username, numeric id or profile link,
`tweet` a post id or link, `list` / `community` an id or link, `location` a
WOEID, country code or place name.
"""
import json

from bottle import request, response, route

from schema_fields import load_query
from scraper_errors import BadRequest, NotFound
from twitter import communities, lists, schemas, trends, tweets, users


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def query_dict():
    """The request query as unicode (bottle 0.12's .get() hands back latin-1
    decoded bytes, so a UTF-8 "Amélie" would arrive as "AmÃ©lie")."""
    return {key: request.query.getunicode(key) for key in request.query.keys()}


def call(label, schema_cls, fn):
    """Validate the query, run the scraper and map failures: bad params ->
    400, missing entity -> 404, transport/blocks -> 500."""
    data, error = load_query(schema_cls, query_dict())
    if error:
        return json_response(error, 400)
    try:
        return json_response(fn(**data))
    except ValueError as e:                # bad id / params
        return json_response({"error": str(e)}, 400)
    except BadRequest as e:                # upstream rejected the request
        return json_response({"error": f"twitter rejected the request: {e}"}, 400)
    except NotFound as e:
        return json_response({"error": str(e) or "not found"}, 404)
    except Exception as e:                 # retries exhausted / blocked
        return json_response({"error": f"twitter {label} failed: {e}"}, 500)


ENDPOINTS = [
    ("/tweets/details", schemas.TweetSchema, tweets.details),
    ("/tweets/details/batch", schemas.TweetsSchema, tweets.details_batch),
    ("/tweets/replies", schemas.RepliesSchema, tweets.replies),
    ("/tweets/thread", schemas.TweetSchema, tweets.thread),
    ("/tweets/embed", schemas.TweetSchema, tweets.embed),
    ("/users/profile", schemas.UserSchema, users.profile),
    ("/users/profiles", schemas.UsersSchema, users.profiles),
    ("/users/tweets", schemas.UserTweetsSchema, users.tweets),
    ("/users/top-tweets", schemas.TopTweetsSchema, users.top_tweets),
    ("/users/highlights", schemas.HighlightsSchema, users.highlights),
    ("/users/recommendations", schemas.RecommendationsSchema, users.recommendations),
    ("/users/check-follow", schemas.CheckFollowSchema, users.check_follow),
    ("/trends", schemas.TrendsSchema, trends.trends),
    ("/trends/locations", schemas.LocationsSchema, trends.locations),
    ("/places/search", schemas.PlacesSchema, trends.places),
    ("/hashflags", schemas.EmptySchema, trends.hashflags),
    ("/lists/details", schemas.ListSchema, lists.details),
    ("/lists/tweets", schemas.ListTweetsSchema, lists.tweets),
    ("/communities/details", schemas.CommunitySchema, communities.details),
    ("/communities/tweets", schemas.CommunityTweetsSchema, communities.tweets),
]


def mount(path, schema_cls, fn):
    """Serve one endpoint at /path and /twitter/path."""
    label = path.strip("/")

    def handler():
        return call(label, schema_cls, fn)
    handler.__name__ = "twitter_" + label.replace("/", "_").replace("-", "_")
    route(path, method="GET")(handler)
    route("/twitter" + path, method="GET")(handler)


for _path, _schema, _fn in ENDPOINTS:
    mount(_path, _schema, _fn)


@route("/", method="GET")
@route("/health", method="GET")
def health():
    return json_response({"status": "ok", "endpoints": [p for p, _, _ in ENDPOINTS]})
