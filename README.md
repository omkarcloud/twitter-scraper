# 🐦 Twitter Scraper

Twitter Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Twitter (X) data for free.

## ✨ What Can I Get?

- 🐦 **Full details on any tweet** — text, photos, HD video links, likes, retweets, bookmarks & views
- 👤 **Complete profiles, 20 per call** — bio, website, followers, following, tweet counts & join date
- 🔥 **Trending topics in 467 places** — top 50 trends for 62 countries and hundreds of cities
- 💬 **Replies, threads, top tweets & communities** — the conversation around any tweet or account

## 🎥 Example: A Full Tweet

```json
{
  "id": "1671370010743263233",
  "link": "https://x.com/FonsDK/status/1671370010743263233",
  "text": "Watching Twitter videos on my TV only took me a few seconds to set up🤯\n\nAn awesome feature, if you’re watching longer videos on X/Twitter @elonmusk",
  "language": "en",
  "created_at": "2023-06-21T04:10:37Z",
  "author": {
    "id": "2337692699",
    "username": "FonsDK",
    "name": "Mathias Føns",
    "link": "https://x.com/FonsDK",
    "profile_image": "https://pbs.twimg.com/profile_images/1485391315819020292/1_3QNpYj_400x400.jpg",
    "is_blue_verified": true,
    "followers_count": 41048
  },
  "media": [
    {
      "type": "video",
      "image": "https://pbs.twimg.com/amplify_video_thumb/1671367628504309761/img/WoU2L8IXtzfmhlq9.jpg",
      "width": 1080,
      "height": 1920,
      "duration_ms": 8333,
      "video_link": "https://video.twimg.com/amplify_video/1671367628504309761/vid/720x1280/YSMJaf2mPv_41IO7.mp4?tag=14"
    }
  ],
  "mentions": [
    { "id": "44196397", "username": "elonmusk", "name": "Elon Musk", "link": "https://x.com/elonmusk" }
  ],
  "stats": { "replies": 1274, "retweets": 1938, "likes": 16167, "quotes": 206, "bookmarks": 827 },
  "source": "Twitter for iPad"
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Twitter Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/twitter-scraper
cd twitter-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/tweets/details?tweet=1585841080431321088"
```

```json
{
  "tweet": {
    "id": "1585841080431321088",
    "link": "https://x.com/elonmusk/status/1585841080431321088",
    "text": "the bird is freed",
    "language": "en",
    "created_at": "2022-10-28T03:49:11Z",
    "author": {
      "id": "44196397",
      "username": "elonmusk",
      "name": "Elon Musk",
      "link": "https://x.com/elonmusk",
      "is_blue_verified": true,
      "followers_count": 241706680
    },
    "is_reply": false,
    "is_quote": false,
    "is_retweet": false,
    "stats": { "replies": 121371, "retweets": 292891, "likes": 2165682, "quotes": 51733, "bookmarks": 8228 },
    "source": "Twitter for iPhone"
  }
}
```

All 20 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

20 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Tweet Details | `/tweets/details` | Everything about one tweet: text, media, video links, stats |
| Tweet Details (Batch) | `/tweets/details/batch` | Up to 20 full tweets in one call |
| Tweet Replies | `/tweets/replies` | Top reply threads plus the total reply count |
| Tweet Thread | `/tweets/thread` | Parent chain and the author's own continuation |
| Tweet Embed | `/tweets/embed` | Official embed HTML, ready to paste |
| User Profile | `/users/profile` | Bio, website, followers, following, counts and join date |
| User Profiles (Batch) | `/users/profiles` | Up to 20 full profiles in one call |
| User Tweets | `/users/tweets` | Pinned tweet plus the latest original tweets |
| User Top Tweets | `/users/top-tweets` | Up to ~100 most-liked tweets, best first |
| User Highlights | `/users/highlights` | Highlighted tweets with cursor pagination |
| Similar Accounts | `/users/recommendations` | Accounts X suggests next to a profile, full profiles |
| Check Follow | `/users/check-follow` | Does A follow B, and does B follow back |
| Trending Topics | `/trends` | Top 50 trends for any country or city |
| Trend Locations | `/trends/locations` | All 467 trend places with WOEIDs |
| Search Places | `/places/search` | Places with coordinates and bounding boxes |
| Hashflags | `/hashflags` | Active hashtag emoji campaigns with dates |
| List Details | `/lists/details` | Name, members, subscribers, owner and creation date |
| List Tweets | `/lists/tweets` | Latest tweets from a list's members |
| Community Details | `/communities/details` | Members, topic, join policy, creator and banner |
| Community Tweets | `/communities/tweets` | A community's top tweets, ranked by likes |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-twitter-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-twitter-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-twitter-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/tweets/details",
    params={"tweet": "1585841080431321088"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Twitter Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://api.whatsapp.com/send?phone=918178804274&text=I%20need%20help%20using%20the%20Twitter%20Scraper%20API.)

[![Ask Us by Email about Twitter Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Twitter%20Scraper%20API&body=I%20need%20help%20using%20the%20Twitter%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/twitter-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/twitter-scraper)
