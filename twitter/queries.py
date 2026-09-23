"""GraphQL persisted-query ids of x.com's legacy web app, harvested from
https://abs.twimg.com/responsive-web/client-web/main.60bedca26c9a9faaa.js on
2026-09-22 (regex queryId:"…",operationName:"…"). X rotates them with every
client build; twitter/fetch.py re-harvests the table from a fresh main.js
when an operation that used to work starts answering 404 / "Query not
found". Only the operations this package calls are listed — all of them
work with a guest token (no account cookie is ever used)."""

QUERY_IDS = {
    "UserByScreenName": "KybxDj9RrADIITXlGG8kpw",
    "UserTweets": "jeAA-59Y9FL7FmjgBNIVPw",
    "UserHighlightsTweets": "TtovDhtuqVtzzfZ9fpztlw",
    "TweetResultByRestId": "Xl0tsHf4AzflMRjbw9e70A",
    "GenericTimelineById": "6KKcBTcCsVtXvAx4aFDzRQ",
}

MAIN_JS = "https://abs.twimg.com/responsive-web/client-web/main.60bedca26c9a9faaa.js"
