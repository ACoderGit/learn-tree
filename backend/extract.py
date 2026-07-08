"""Content extraction: turn a URL into clean text + a title.

Handles YouTube (via transcripts) and generic web articles (via trafilatura).
Everything degrades gracefully — a failure returns whatever we could get so the
rest of the pipeline still runs.
"""
import html as html_lib
import json
import re
from urllib.parse import urlparse, parse_qs, parse_qsl, urlencode, urlunparse

import requests
import trafilatura


YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"}
TRANSCRIPT_LANGUAGES = ("en", "en-US", "en-GB")


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


def is_youtube_url(url: str) -> bool:
    return _youtube_id(url) is not None


def _join_transcript(snippets) -> str:
    parts = []
    for snippet in snippets or []:
        if isinstance(snippet, dict):
            text = snippet.get("text", "")
        else:
            text = getattr(snippet, "text", "")
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            parts.append(text)
    return " ".join(parts)


def _youtube_transcript(video_id: str) -> str:
    """Fetch a transcript across youtube-transcript-api v0.x and v1.x APIs."""
    from youtube_transcript_api import YouTubeTranscriptApi

    # v1.x: instance .fetch() returning snippet objects with .text.
    try:
        api = YouTubeTranscriptApi()
        text = _join_transcript(api.fetch(video_id, languages=TRANSCRIPT_LANGUAGES))
        if text:
            return text
    except AttributeError:
        pass
    except Exception:
        pass

    # v1.x fallback: inspect available transcripts, prefer English, then
    # translate a translatable transcript to English if YouTube allows it.
    try:
        transcripts = YouTubeTranscriptApi().list(video_id)
        for finder in (transcripts.find_manually_created_transcript,
                       transcripts.find_generated_transcript,
                       transcripts.find_transcript):
            try:
                transcript = finder(TRANSCRIPT_LANGUAGES)
                text = _join_transcript(transcript.fetch())
                if text:
                    return text
            except Exception:
                pass
        for transcript in transcripts:
            try:
                if getattr(transcript, "is_translatable", False):
                    text = _join_transcript(transcript.translate("en").fetch())
                else:
                    text = _join_transcript(transcript.fetch())
                if text:
                    return text
            except Exception:
                pass
    except AttributeError:
        pass
    except Exception:
        pass

    # v0.x: static .get_transcript() returning list of dicts
    try:
        chunks = YouTubeTranscriptApi.get_transcript(video_id, languages=TRANSCRIPT_LANGUAGES)
        return _join_transcript(chunks)
    except Exception:
        return ""


def _caption_url_with_json(base_url: str) -> str:
    parsed = urlparse(html_lib.unescape(base_url))
    query = dict(parse_qsl(parsed.query))
    query.setdefault("fmt", "json3")
    return urlunparse(parsed._replace(query=urlencode(query)))


def _timedtext_to_text(raw: str) -> str:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # XML fallback.
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_lib.unescape(raw))).strip()

    parts = []
    for event in data.get("events", []):
        for seg in event.get("segs", []):
            text = re.sub(r"\s+", " ", seg.get("utf8", "")).strip()
            if text:
                parts.append(text)
    return " ".join(parts)


def _youtube_transcript_from_html(downloaded: str) -> str:
    if not downloaded:
        return ""

    match = re.search(r'"captionTracks":(\[.*?\])\s*,\s*"audioTracks"', downloaded)
    if not match:
        match = re.search(r'"captionTracks":(\[.*?\])\s*,\s*"translationLanguages"', downloaded)
    if not match:
        return ""

    try:
        tracks = json.loads(html_lib.unescape(match.group(1)))
    except json.JSONDecodeError:
        return ""

    def score(track):
        lang = track.get("languageCode", "")
        kind = track.get("kind", "")
        if lang in TRANSCRIPT_LANGUAGES and kind != "asr":
            return 0
        if lang.startswith("en") and kind != "asr":
            return 1
        if lang in TRANSCRIPT_LANGUAGES:
            return 2
        if lang.startswith("en"):
            return 3
        return 4

    for track in sorted(tracks, key=score):
        base_url = track.get("baseUrl")
        if not base_url:
            continue
        try:
            r = requests.get(_caption_url_with_json(base_url), timeout=15)
            if r.ok and r.text:
                text = _timedtext_to_text(r.text)
                if text:
                    return text
        except Exception:
            pass
    return ""


def _youtube_title(url: str, video_id: str) -> str:
    try:
        r = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": url, "format": "json"},
            timeout=8,
        )
        if r.ok:
            title = (r.json().get("title") or "").strip()
            if title:
                return title
    except Exception:
        pass
    return f"YouTube video {video_id}"


def _extract_youtube(video_id: str, url: str) -> dict:
    text = _youtube_transcript(video_id)

    title = _youtube_title(url, video_id)
    downloaded = _fetch_url(url)
    if downloaded:
        meta = trafilatura.extract_metadata(downloaded)
        if meta and meta.title:
            title = meta.title
        if not text:
            text = _youtube_transcript_from_html(downloaded)
        if not text:
            text = trafilatura.extract(downloaded) or ""
    if not text:
        text = _fallback_text(url, title)

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
