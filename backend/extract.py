"""Content extraction: turn a URL into clean text + a title.

Handles YouTube (via transcripts) and generic web articles (via trafilatura).
Everything degrades gracefully — a failure returns whatever we could get so the
rest of the pipeline still runs.
"""
import re
from urllib.parse import urlparse, parse_qs

import requests
import trafilatura


YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"}


def _fetch_url(url: str) -> str:
    """Fetch HTML with trafilatura first, then a plain browser-like request."""
    downloaded = trafilatura.fetch_url(url)
    if downloaded:
        return downloaded
    try:
        r = requests.get(
            url,
            timeout=20,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0 Safari/537.36"
                )
            },
        )
        if r.ok and r.text.strip():
            return r.text
    except Exception:
        pass
    return ""


def _title_from_url(url: str) -> str:
    """Human title fallback for JS-gated pages that return no extractable HTML."""
    parsed = urlparse(url)
    slug = parsed.path.rstrip("/").split("/")[-1] or parsed.netloc
    parts = [p for p in re.split(r"[-_]+", slug) if p]
    if parts and re.fullmatch(r"[a-zA-Z]{2,}\d+[a-zA-Z0-9]*", parts[0]):
        parts = parts[1:]
    if parts[:1] == ["introduction"] and (len(parts) == 1 or parts[1] != "to"):
        parts.insert(1, "to")
    title = " ".join(parts).strip()
    if not title:
        return url
    words = title.title().split()
    return " ".join(w.lower() if i and w.lower() in {"to", "of", "and", "for"} else w
                    for i, w in enumerate(words))


def _fallback_text(url: str, title: str) -> str:
    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "")
    return (
        f"{title}. Source page from {domain}. "
        f"The URL slug suggests this learning resource is about {title}."
    )


def _youtube_id(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host not in YOUTUBE_HOSTS:
        return None
    if host == "youtu.be":
        return parsed.path.lstrip("/") or None
    if parsed.path == "/watch":
        return parse_qs(parsed.query).get("v", [None])[0]
    m = re.match(r"^/(embed|shorts|v)/([^/?]+)", parsed.path)
    if m:
        return m.group(2)
    return None


def _youtube_transcript(video_id: str) -> str:
    """Fetch a transcript across youtube-transcript-api v0.x and v1.x APIs."""
    from youtube_transcript_api import YouTubeTranscriptApi

    # v1.x: instance .fetch() returning snippet objects with .text
    try:
        api = YouTubeTranscriptApi()
        fetched = api.fetch(video_id)
        return " ".join(getattr(s, "text", "") for s in fetched)
    except AttributeError:
        pass
    except Exception:
        return ""

    # v0.x: static .get_transcript() returning list of dicts
    try:
        chunks = YouTubeTranscriptApi.get_transcript(video_id)
        return " ".join(c.get("text", "") for c in chunks)
    except Exception:
        return ""


def _extract_youtube(video_id: str, url: str) -> dict:
    text = _youtube_transcript(video_id)

    title = f"YouTube video {video_id}"
    downloaded = _fetch_url(url)
    if downloaded:
        meta = trafilatura.extract_metadata(downloaded)
        if meta and meta.title:
            title = meta.title
        if not text:
            text = trafilatura.extract(downloaded) or ""

    return {"url": url, "title": title, "text": text}


def _extract_article(url: str) -> dict:
    downloaded = _fetch_url(url)
    if not downloaded:
        title = _title_from_url(url)
        return {"url": url, "title": title, "text": _fallback_text(url, title)}

    text = trafilatura.extract(downloaded, include_comments=False,
                               include_tables=False) or ""
    title = url
    meta = trafilatura.extract_metadata(downloaded)
    if meta and meta.title:
        title = meta.title
    return {"url": url, "title": title, "text": text}


def extract(url: str) -> dict:
    """Return {'url', 'title', 'text'} for any supported URL."""
    url = url.strip()
    if not url:
        return {"url": url, "title": "", "text": ""}
    if not urlparse(url).scheme:
        url = "https://" + url

    vid = _youtube_id(url)
    if vid:
        return _extract_youtube(vid, url)
    return _extract_article(url)
