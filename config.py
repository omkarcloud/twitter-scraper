"""Configuration for the Twitter Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT           port the API listens on (default 8000)
    TWITTER_PROXY  proxy URL for every request, e.g. http://user:pass@host:port
                   (default: none — direct). X ran no bot protection on these
                   surfaces and a 30-call burst from one IP all returned 200, so
                   you very likely don't need this. Set it only if you start
                   seeing 403/429 errors at high volume.

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

# After a 403/429, new sessions use the fallback proxy (if any) this long.
TWITTER_BLOCK_COOLDOWN = 900

TWITTER_PROXY = os.environ.get("TWITTER_PROXY") or None


def twitter_proxy():
    """Proxy for every session (None = direct)."""
    return os.environ.get("TWITTER_PROXY") or None


def twitter_fallback_proxy():
    """Proxy a worker switches to after a 403/429 (None = no fallback)."""
    return os.environ.get("TWITTER_PROXY") or None
