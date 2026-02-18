"""MusicBrainz and Wikipedia API integration for research-grounded pitches.

Fetches external data to ground sommelier pitches in verifiable facts:
release dates, personnel, recording context, and critical reception.
"""

import asyncio
import logging
from urllib.parse import unquote

import httpx

from backend.models import ResearchData

logger = logging.getLogger(__name__)

# MusicBrainz requires a User-Agent header
USER_AGENT = "MediaSage/1.0 (https://github.com/ecwilsonaz/mediasage)"

# Rate limiting: 1 request/second to MusicBrainz
MB_BASE_URL = "https://musicbrainz.org/ws/2"
MB_RATE_LIMIT = 1.0  # seconds between requests

WIKIPEDIA_API = "https://en.wikipedia.org/api/rest_v1/page/summary"
COVER_ART_BASE = "https://coverartarchive.org"


class MusicResearchClient:
    """Client for fetching album research data from MusicBrainz and Wikipedia."""

    def __init__(self):
        self._http: httpx.AsyncClient | None = None
        self._last_mb_request: float = 0
        self._rate_lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazily create the HTTP client."""
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                timeout=10.0,
                headers={"User-Agent": USER_AGENT},
            )
        return self._http

    async def _rate_limit(self) -> None:
        """Enforce MusicBrainz rate limiting (1 req/sec)."""
        import time
        async with self._rate_lock:
            now = time.time()
            elapsed = now - self._last_mb_request
            if elapsed < MB_RATE_LIMIT:
                await asyncio.sleep(MB_RATE_LIMIT - elapsed)
            self._last_mb_request = time.time()

    async def search_album(self, artist: str, album: str) -> str | None:
        """Search MusicBrainz for a release group by artist+album.

        Returns the release group MBID, or None if not found.
        """
        client = await self._get_client()
        await self._rate_limit()

        query = f'artist:"{artist}" AND releasegroup:"{album}"'
        try:
            resp = await client.get(
                f"{MB_BASE_URL}/release-group",
                params={"query": query, "fmt": "json", "limit": 5},
            )
            resp.raise_for_status()
            data = resp.json()

            release_groups = data.get("release-groups", [])
            if not release_groups:
                logger.info("No MusicBrainz match for %s — %s", artist, album)
                return None

            return release_groups[0].get("id")
        except Exception as e:
            logger.warning("MusicBrainz search failed for %s — %s: %s", artist, album, e)
            return None

    async def lookup_release_group(self, mbid: str) -> dict | None:
        """Look up a release group by MBID with URL rels and releases.

        Returns dict with wikipedia_url, allmusic_url, discogs_url,
        earliest_release_mbid, or None on failure.
        """
        client = await self._get_client()
        await self._rate_limit()

        try:
            resp = await client.get(
                f"{MB_BASE_URL}/release-group/{mbid}",
                params={"inc": "url-rels+releases", "fmt": "json"},
            )
            resp.raise_for_status()
            data = resp.json()

            result: dict = {}
            review_urls = []

            # Extract URLs from relations
            for rel in data.get("relations", []):
                rel_type = rel.get("type", "")
                url = rel.get("url", {}).get("resource", "")
                if rel_type == "wikipedia":
                    result["wikipedia_url"] = url
                elif rel_type == "discogs":
                    result["discogs_url"] = url
                elif rel_type == "review":
                    # Skip AllMusic (TOS prohibits automated access)
                    if "allmusic.com" not in url:
                        review_urls.append(url)

            result["review_urls"] = review_urls[:2]  # Limit to 2 reviews

            # Find earliest release MBID
            releases = data.get("releases", [])
            if releases:
                # Sort by date (earliest first)
                releases.sort(key=lambda r: r.get("date", "9999"))
                result["earliest_release_mbid"] = releases[0].get("id")
                result["release_date"] = releases[0].get("date")

            return result
        except Exception as e:
            logger.warning("MusicBrainz release group lookup failed for %s: %s", mbid, e)
            return None

    async def lookup_release(self, release_mbid: str) -> dict | None:
        """Look up a release by MBID for track listing, label, and credits.

        Returns dict with track_listing, label, credits, or None on failure.
        """
        client = await self._get_client()
        await self._rate_limit()

        try:
            resp = await client.get(
                f"{MB_BASE_URL}/release/{release_mbid}",
                params={"inc": "recordings+labels+artist-credits", "fmt": "json"},
            )
            resp.raise_for_status()
            data = resp.json()

            result: dict = {}

            # Track listing
            tracks = []
            for medium in data.get("media", []):
                for track in medium.get("tracks", []):
                    title = track.get("title", "")
                    if title:
                        tracks.append(title)
            result["track_listing"] = tracks

            # Label
            label_info = data.get("label-info", [])
            if label_info:
                label = label_info[0].get("label", {})
                result["label"] = label.get("name")

            # Credits from artist-credit
            artist_credit = data.get("artist-credit", [])
            credits = {}
            for credit in artist_credit:
                artist = credit.get("artist", {})
                if artist.get("name"):
                    credits["Primary Artist"] = artist["name"]
                    break
            result["credits"] = credits

            return result
        except Exception as e:
            logger.warning("MusicBrainz release lookup failed for %s: %s", release_mbid, e)
            return None

    async def fetch_wikipedia_summary(self, wikipedia_url: str) -> str | None:
        """Fetch article summary from Wikipedia.

        Args:
            wikipedia_url: Full Wikipedia article URL

        Returns:
            Summary text, or None on failure.
        """
        client = await self._get_client()

        try:
            # Extract article title from URL
            # e.g. https://en.wikipedia.org/wiki/Spirit_of_Eden -> Spirit_of_Eden
            parts = wikipedia_url.rstrip("/").split("/wiki/")
            if len(parts) < 2:
                return None
            title = unquote(parts[1])

            resp = await client.get(f"{WIKIPEDIA_API}/{title}")
            resp.raise_for_status()
            data = resp.json()
            return data.get("extract")
        except Exception as e:
            logger.warning("Wikipedia fetch failed for %s: %s", wikipedia_url, e)
            return None

    async def fetch_cover_art(self, release_mbid: str) -> str | None:
        """Fetch front cover art URL from Cover Art Archive.

        Returns the final image URL after redirect, or None if unavailable.
        """
        client = await self._get_client()

        try:
            resp = await client.get(
                f"{COVER_ART_BASE}/release/{release_mbid}/front",
                follow_redirects=True,
            )
            if resp.status_code == 200:
                return str(resp.url)
            return None
        except Exception as e:
            logger.warning("Cover Art Archive fetch failed for %s: %s", release_mbid, e)
            return None

    async def fetch_review_text(self, url: str) -> str | None:
        """Fetch and extract article text from a review URL.

        Uses readability-lxml to extract the main article content,
        stripping navigation, ads, and other page chrome.

        Args:
            url: Review page URL

        Returns:
            Extracted plain text (up to ~2000 chars), or None on failure.
        """
        # Skip AllMusic URLs (TOS prohibits automated access)
        if "allmusic.com" in url:
            logger.info("Skipping AllMusic URL (TOS): %s", url)
            return None

        client = await self._get_client()

        try:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()

            from readability import Document
            doc = Document(resp.text)
            # Get readable HTML, then strip tags for plain text
            readable_html = doc.summary()

            # Strip HTML tags to get plain text
            import re
            text = re.sub(r"<[^>]+>", " ", readable_html)
            text = re.sub(r"\s+", " ", text).strip()

            if not text:
                return None

            # Truncate to ~2000 chars at a sentence boundary
            if len(text) > 2000:
                cutoff = text.rfind(". ", 1500, 2000)
                if cutoff == -1:
                    cutoff = 2000
                text = text[:cutoff + 1]

            return text
        except Exception as e:
            logger.warning("Review fetch failed for %s: %s", url, e)
            return None

    async def research_album(
        self, artist: str, album: str, full: bool = True
    ) -> ResearchData:
        """Run the full research pipeline for an album.

        Args:
            artist: Artist name
            album: Album title
            full: If True, fetch Wikipedia summary too. If False, light research only.

        Returns:
            ResearchData with whatever could be fetched.
        """
        research = ResearchData()

        # Step 1: Search for release group
        rg_mbid = await self.search_album(artist, album)
        if not rg_mbid:
            return research
        research.musicbrainz_id = rg_mbid

        # Step 2: Look up release group for URLs and earliest release
        rg_data = await self.lookup_release_group(rg_mbid)
        if not rg_data:
            return research

        research.release_date = rg_data.get("release_date")
        research.review_links = rg_data.get("review_urls", [])

        # Step 3: Look up release for track listing, label, credits
        release_mbid = rg_data.get("earliest_release_mbid")
        if release_mbid:
            release_data = await self.lookup_release(release_mbid)
            if release_data:
                research.track_listing = release_data.get("track_listing", [])
                research.label = release_data.get("label")
                research.credits = release_data.get("credits", {})

        # Step 4: Wikipedia summary (full research only)
        if full and rg_data.get("wikipedia_url"):
            summary = await self.fetch_wikipedia_summary(rg_data["wikipedia_url"])
            if summary:
                research.wikipedia_summary = summary

        # Step 5: Fetch review texts (full research only)
        review_urls = rg_data.get("review_urls", [])
        if full and review_urls:
            for review_url in review_urls[:2]:
                text = await self.fetch_review_text(review_url)
                if text:
                    research.review_texts.append(text)

        return research

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._http and not self._http.is_closed:
            await self._http.aclose()
