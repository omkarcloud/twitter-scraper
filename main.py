"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json.
"""
import json
import os

from twitter import refs
from twitter.trends import trends
from twitter.tweets import details
from twitter.users import profile

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # a post id or any x.com / twitter.com post link
    save("tweet_1585841080431321088.json", details(refs.resolve_tweet("https://x.com/elonmusk/status/1585841080431321088")))

    # a username, numeric user id or profile link
    save("profile_elonmusk.json", profile(refs.resolve_user("elonmusk")))

    # a WOEID, a country code or a place name
    save("trends_us.json", trends("US"))
