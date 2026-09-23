"""Cache TTL per /twitter/* endpoint (cache.py, keyed on the validated params).

Tiers follow how fast X moves each surface: counts on a fresh post change
every second, a profile card a few times a day, the WOEID table a few
times a year.
"""
from datetime import timedelta

# --- users -----------------------------------------------------------------------
PROFILE_CACHE = timedelta(minutes=10)
USER_TWEETS_CACHE = timedelta(minutes=3)
TOP_TWEETS_CACHE = timedelta(minutes=30)
HIGHLIGHTS_CACHE = timedelta(minutes=15)
FOLLOW_CHECK_CACHE = timedelta(minutes=10)
RECOMMENDATIONS_CACHE = timedelta(hours=1)

# --- tweets ----------------------------------------------------------------------
TWEET_CACHE = timedelta(minutes=3)
REPLIES_CACHE = timedelta(minutes=3)
THREAD_CACHE = timedelta(minutes=5)
EMBED_CACHE = timedelta(days=1)

# --- trends / reference tables ---------------------------------------------------
TRENDS_CACHE = timedelta(minutes=5)
LOCATIONS_CACHE = timedelta(days=1)
HASHFLAGS_CACHE = timedelta(hours=6)
PLACES_CACHE = timedelta(days=1)

# --- lists / communities ---------------------------------------------------------
LIST_CACHE = timedelta(minutes=15)
LIST_TWEETS_CACHE = timedelta(minutes=3)
COMMUNITY_CACHE = timedelta(minutes=15)
COMMUNITY_TWEETS_CACHE = timedelta(minutes=5)
