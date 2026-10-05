import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; HackathonOutreachBot/1.0)"}


def fetch(url: str, timeout: int = 8, max_bytes: int = 600_000):
    """Return (final_url_after_redirects, text). Empty text on any failure."""
    try:
        with requests.get(url, headers=HEADERS, timeout=timeout, stream=True, allow_redirects=True) as r:
            if r.status_code >= 400 or "text" not in r.headers.get("content-type", "text"):
                return r.url, ""
            data = r.raw.read(max_bytes, decode_content=True)
            return r.url, data.decode(r.encoding or "utf-8", errors="ignore")
    except requests.RequestException:
        return url, ""
