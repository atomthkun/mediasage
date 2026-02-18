"""Album recommendation pipeline for MediaSage.

Implements the 4-call LLM pipeline: gap analysis, question generation,
album selection, and pitch writing. Maintains in-memory session state
for "Show me another" functionality.
"""

import logging
import threading
import time
import uuid
from typing import Any

from backend.llm_client import LLMClient, LLMResponse
from backend.models import (
    AlbumCandidate,
    AlbumRecommendation,
    ClarifyingQuestion,
    ExtractedFacts,
    PitchIssue,
    PitchValidation,
    RecommendSessionState,
    ResearchData,
    SommelierPitch,
    TasteProfile,
)

logger = logging.getLogger(__name__)
cost_logger = logging.getLogger("recommend.cost")

# Dimension library for gap analysis
DIMENSION_LIBRARY = [
    {"id": "energy", "label": "Energy Level", "description": "Calm vs intense, quiet vs loud"},
    {"id": "emotional_direction", "label": "Emotional Direction", "description": "Sad, joyful, bittersweet, cathartic, neutral"},
    {"id": "attention_level", "label": "Attention Level", "description": "Background listening vs active listening"},
    {"id": "era", "label": "Era / Time Period", "description": "Classic, contemporary, timeless"},
    {"id": "familiarity", "label": "Familiarity", "description": "Well-known vs deep cuts, mainstream vs obscure"},
    {"id": "vocal_presence", "label": "Vocal Presence", "description": "Instrumental, minimal vocals, vocal-forward"},
    {"id": "lyrical_mood", "label": "Lyrical Mood", "description": "Introspective, storytelling, abstract, anthemic"},
    {"id": "social_context", "label": "Social Context", "description": "Solo listening, with friends, romantic, communal"},
    {"id": "complexity", "label": "Musical Complexity", "description": "Simple and direct vs layered and complex"},
    {"id": "rawness", "label": "Production Style", "description": "Lo-fi/raw vs polished/produced"},
    {"id": "tempo", "label": "Tempo", "description": "Slow, mid-tempo, fast-paced"},
    {"id": "cultural_specificity", "label": "Cultural Specificity", "description": "Universal appeal vs culturally rooted"},
]

# Session expiry in seconds (30 minutes)
SESSION_EXPIRY = 1800


class RecommendationPipeline:
    """Orchestrates the album recommendation flow."""

    def __init__(self, config: Any, llm_client: LLMClient):
        self.config = config
        self.llm_client = llm_client
        self._sessions: dict[str, tuple[RecommendSessionState, float]] = {}
        self._session_lock = threading.Lock()

    def _log_cost(
        self,
        call_name: str,
        response: LLMResponse,
        session_id: str,
        album_count: int = 0,
    ) -> None:
        """Emit structured cost log line for calibration."""
        cost = response.estimated_cost()
        cost_logger.info(
            "recommend.cost | call=%s model=%s input=%d output=%d cost=%.5f albums=%d session=%s",
            call_name,
            response.model,
            response.input_tokens,
            response.output_tokens,
            cost,
            album_count,
            session_id,
        )

    # ── Fact extraction ─────────────────────────────────────────────────

    def extract_facts(
        self,
        artist: str,
        album: str,
        research: ResearchData,
        session_id: str,
    ) -> ExtractedFacts:
        """Extract structured facts from raw research data.

        Uses the generation (cheap) model to convert raw Wikipedia text,
        review content, and MusicBrainz data into labeled, structured facts.

        Returns ExtractedFacts with fields populated from sources.
        """
        # Build source material
        sources = []

        if research.wikipedia_summary:
            sources.append(f"WIKIPEDIA:\n{research.wikipedia_summary}")

        for i, review in enumerate(research.review_texts):
            sources.append(f"REVIEW {i + 1}:\n{review}")

        if research.track_listing:
            tracks = ", ".join(research.track_listing)
            sources.append(f"TRACK LISTING:\n{tracks}")

        metadata_parts = []
        if research.release_date:
            metadata_parts.append(f"Release date: {research.release_date}")
        if research.label:
            metadata_parts.append(f"Label: {research.label}")
        if research.credits:
            creds = ", ".join(f"{role}: {name}" for role, name in research.credits.items())
            metadata_parts.append(f"Credits: {creds}")
        if metadata_parts:
            sources.append(f"MUSICBRAINZ METADATA:\n" + "\n".join(metadata_parts))

        sources_text = "\n\n".join(sources) if sources else "No sources available."

        system = (
            "You are a music research assistant. Extract verifiable facts about a specific "
            "album from the provided sources. Follow these rules strictly:\n\n"
            "1. ONLY state facts that appear in the sources below. Do not add knowledge from "
            "your training data.\n"
            "2. If a topic is not covered in the sources, write \"NOT IN SOURCES\" for that field.\n"
            "3. If sources conflict on a point, note the conflict.\n"
            "4. Be specific to THIS album — do not generalize from the artist's broader catalog.\n"
            "5. For vocal_approach, note the specific language(s) used and whether it varies by track.\n"
            "6. For common_misconceptions, note anything the sources clarify that could easily be "
            "misunderstood or overgeneralized.\n\n"
            "Return a JSON object with these fields:\n"
            "- origin_story: How/why the album was made, key events in its creation\n"
            "- personnel: List of key people involved (musicians, producers, engineers)\n"
            "- musical_style: Sound, instrumentation, production approach\n"
            "- vocal_approach: Language(s) sung in, singing style, notable vocal choices\n"
            "- cultural_context: Reception, significance, scene/movement\n"
            "- track_highlights: Notable individual tracks mentioned in sources\n"
            "- common_misconceptions: Things sources clarify or correct about common assumptions\n"
            "- source_coverage: Brief note on what topics the sources cover well vs poorly\n\n"
            "No explanation, just the JSON object."
        )

        user_prompt = (
            f"Album: {artist} — {album}\n\n"
            f"SOURCES:\n{sources_text}\n\n"
            f"Extract the structured facts."
        )

        response = self.llm_client.generate(user_prompt, system)
        self._log_cost("fact_extraction", response, session_id)

        raw = self.llm_client.parse_json_response(response)
        return ExtractedFacts(
            origin_story=raw.get("origin_story", ""),
            personnel=raw.get("personnel", []),
            musical_style=raw.get("musical_style", ""),
            vocal_approach=raw.get("vocal_approach", ""),
            cultural_context=raw.get("cultural_context", ""),
            track_highlights=raw.get("track_highlights", ""),
            common_misconceptions=raw.get("common_misconceptions", ""),
            source_coverage=raw.get("source_coverage", ""),
        )

    # ── Session management ──────────────────────────────────────────────

    def create_session(self, session_state: RecommendSessionState) -> str:
        """Create a new recommendation session, return session_id."""
        with self._session_lock:
            self._expire_old_sessions()
            session_id = f"rec_{uuid.uuid4().hex[:12]}"
            self._sessions[session_id] = (session_state, time.time())
            return session_id

    def get_session(self, session_id: str) -> RecommendSessionState | None:
        """Retrieve a session by ID, or None if expired/missing."""
        with self._session_lock:
            self._expire_old_sessions()
            entry = self._sessions.get(session_id)
            if entry is None:
                return None
            session_state, created_at = entry
            # Touch timestamp on access
            self._sessions[session_id] = (session_state, time.time())
            return session_state

    def _expire_old_sessions(self) -> None:
        """Remove sessions older than SESSION_EXPIRY. Caller must hold _session_lock."""
        now = time.time()
        expired = [
            sid for sid, (_, ts) in self._sessions.items()
            if now - ts > SESSION_EXPIRY
        ]
        for sid in expired:
            del self._sessions[sid]
            logger.info("Expired recommendation session %s", sid)

    # ── Pipeline steps ──────────────────────────────────────────────────

    def gap_analysis(self, prompt: str, session_id: str) -> list[str]:
        """Identify the 2 most impactful dimensions to clarify.

        Returns list of 2 dimension IDs.
        """
        dimension_text = "\n".join(
            f"- {d['id']}: {d['label']} — {d['description']}"
            for d in DIMENSION_LIBRARY
        )

        system = (
            "You are a music taste analyst. Given a user's album recommendation prompt, "
            "identify which 2 musical dimensions from the provided list would most help "
            "narrow down the perfect album. Return ONLY a JSON array of exactly 2 dimension "
            "IDs, e.g. [\"energy\", \"emotional_direction\"]. No explanation."
        )

        user_prompt = (
            f"User wants: \"{prompt}\"\n\n"
            f"Available dimensions:\n{dimension_text}\n\n"
            f"Which 2 dimensions have the biggest gap — where knowing the user's preference "
            f"would most change which album you'd recommend? Return JSON array of 2 IDs."
        )

        response = self.llm_client.analyze(user_prompt, system)
        self._log_cost("gap_analysis", response, session_id)

        dimensions = self.llm_client.parse_json_response(response)
        if not isinstance(dimensions, list) or len(dimensions) < 2:
            # Fallback to first two dimensions
            return ["energy", "emotional_direction"]

        # Validate dimension IDs
        valid_ids = {d["id"] for d in DIMENSION_LIBRARY}
        result = [d for d in dimensions[:2] if d in valid_ids]
        while len(result) < 2:
            for d in DIMENSION_LIBRARY:
                if d["id"] not in result:
                    result.append(d["id"])
                    break
        return result[:2]

    def generate_questions(
        self, prompt: str, dimension_ids: list[str], session_id: str
    ) -> list[ClarifyingQuestion]:
        """Generate 2 clarifying questions based on selected dimensions.

        Returns list of ClarifyingQuestion objects.
        """
        dim_lookup = {d["id"]: d for d in DIMENSION_LIBRARY}
        dim_descriptions = []
        for did in dimension_ids:
            d = dim_lookup.get(did, {"label": did, "description": did})
            dim_descriptions.append(f"{d['label']}: {d['description']}")

        system = (
            "You are a friendly music recommendation assistant. Generate exactly 2 clarifying "
            "questions to help pick the perfect album. Each question should:\n"
            "- Reference the user's words naturally\n"
            "- Have 3-4 short, tappable answer options\n"
            "- Address the specified musical dimension\n\n"
            "Return JSON array of objects with: question_text, options (array of 3-4 strings), dimension (the dimension id).\n"
            "No explanation, just the JSON array."
        )

        user_prompt = (
            f"User wants: \"{prompt}\"\n\n"
            f"Dimensions to ask about:\n"
            + "\n".join(f"- {did}: {desc}" for did, desc in zip(dimension_ids, dim_descriptions))
            + "\n\nGenerate 2 natural, conversational questions."
        )

        response = self.llm_client.generate(user_prompt, system)
        self._log_cost("question_gen", response, session_id)

        raw = self.llm_client.parse_json_response(response)
        questions = []
        for item in raw[:2]:
            questions.append(ClarifyingQuestion(
                question_text=item.get("question_text", ""),
                options=item.get("options", [])[:4],
                dimension=item.get("dimension", ""),
            ))
        return questions

    def select_albums(
        self,
        prompt: str,
        answers: list[str | None],
        answer_texts: list[str],
        album_candidates: list[AlbumCandidate],
        session_id: str,
    ) -> list[AlbumRecommendation]:
        """Select 1 primary + 2 secondary albums from the candidate pool.

        Returns list of AlbumRecommendation (without pitches yet).
        """
        # Edge case: very small pool — return all candidates directly
        if len(album_candidates) <= 3:
            recs = []
            for i, c in enumerate(album_candidates):
                recs.append(AlbumRecommendation(
                    rank="primary" if i == 0 else "secondary",
                    album=c.album,
                    artist=c.album_artist,
                    year=c.year,
                    rating_key=c.parent_rating_key,
                    track_rating_keys=c.track_rating_keys,
                    art_url=f"/api/art/{c.track_rating_keys[0]}" if c.track_rating_keys else None,
                ))
            return recs

        # Build album list for LLM
        album_lines = []
        for a in album_candidates:
            genres_str = ", ".join(a.genres[:3]) if a.genres else "Unknown"
            album_lines.append(f"- {a.album_artist} — {a.album} ({a.year or '?'}) [{genres_str}]")
        album_text = "\n".join(album_lines)

        # Build answer context
        answer_parts = []
        for i, ans in enumerate(answers):
            if ans:
                text = ans
                if i < len(answer_texts) and answer_texts[i]:
                    text += f" (also: {answer_texts[i]})"
                answer_parts.append(f"Q{i+1} answer: {text}")
            else:
                answer_parts.append(f"Q{i+1}: skipped")
        answers_text = "\n".join(answer_parts)

        system = (
            "You are a music recommendation expert. Pick exactly 3 albums from the provided list "
            "that best match the user's request and clarifying answers. The first pick is the PRIMARY "
            "recommendation (best match), the other two are SECONDARY (worth exploring).\n\n"
            "Return a JSON array of 3 objects, each with: artist (string), album (string), rank "
            "(\"primary\" for first, \"secondary\" for others). Pick from the list EXACTLY as written.\n"
            "No explanation, just the JSON array."
        )

        small_pool_note = ""
        if len(album_candidates) < 10:
            small_pool_note = (
                "\nNote: The pool is small. Pick the best matches available, "
                "even if the fit isn't perfect. Do your best with what's here."
            )

        user_prompt = (
            f"User wants: \"{prompt}\"\n\n"
            f"Clarifying answers:\n{answers_text}\n\n"
            f"Available albums ({len(album_candidates)} total):\n{album_text}\n\n"
            f"Pick 3 albums: 1 primary + 2 secondary.{small_pool_note}"
        )

        response = self.llm_client.generate(user_prompt, system)
        self._log_cost("selection", response, session_id, album_count=len(album_candidates))

        raw = self.llm_client.parse_json_response(response)
        recommendations = []
        # Build lookup for matching
        candidate_lookup: dict[str, AlbumCandidate] = {}
        for c in album_candidates:
            key = f"{c.album_artist.lower()}|||{c.album.lower()}"
            candidate_lookup[key] = c

        for item in raw[:3]:
            artist = item.get("artist", "")
            album = item.get("album", "")
            rank = item.get("rank", "secondary")

            # Match back to candidate (case-insensitive)
            lookup_key = f"{artist.lower()}|||{album.lower()}"
            candidate = candidate_lookup.get(lookup_key)

            rec = AlbumRecommendation(
                rank=rank if rank in ("primary", "secondary") else "secondary",
                album=album,
                artist=artist,
                year=candidate.year if candidate else None,
                rating_key=candidate.parent_rating_key if candidate else None,
                track_rating_keys=candidate.track_rating_keys if candidate else [],
                art_url=f"/api/art/{candidate.track_rating_keys[0]}" if candidate and candidate.track_rating_keys else None,
            )
            recommendations.append(rec)

        # Ensure we have at least 1 primary
        if recommendations and all(r.rank == "secondary" for r in recommendations):
            recommendations[0].rank = "primary"

        return recommendations

    def write_pitches(
        self,
        recommendations: list[AlbumRecommendation],
        prompt: str,
        answers: list[str | None],
        answer_texts: list[str],
        session_id: str,
        research: dict[str, ResearchData] | None = None,
        familiarity: dict[str, str] | None = None,
    ) -> list[AlbumRecommendation]:
        """Write sommelier pitches for each recommendation.

        Args:
            familiarity: Optional dict mapping rating_key -> "unplayed"|"light"|"well-loved"

        Returns the same recommendations with pitches filled in.
        """
        # Build album descriptions for context
        album_descs = []
        for rec in recommendations:
            desc = f"[{rec.rank.upper()}] {rec.artist} — {rec.album} ({rec.year or '?'})"
            # Add familiarity context
            if familiarity and rec.rating_key and rec.rating_key in familiarity:
                level = familiarity[rec.rating_key]
                desc += f"\nFamiliarity: {level}"
            # Add research data if available
            research_key = f"{rec.artist}|||{rec.album}"
            if research and research_key in research:
                rd = research[research_key]
                if rd.wikipedia_summary:
                    desc += f"\nResearch: {rd.wikipedia_summary[:500]}"
                if rd.label:
                    desc += f"\nLabel: {rd.label}"
                if rd.release_date:
                    desc += f"\nRelease: {rd.release_date}"
                if rd.credits:
                    creds = ", ".join(f"{role}: {name}" for role, name in list(rd.credits.items())[:3])
                    desc += f"\nCredits: {creds}"
            album_descs.append(desc)

        albums_text = "\n\n".join(album_descs)

        # Build answer context
        answer_parts = []
        for i, ans in enumerate(answers):
            if ans:
                text = ans
                if i < len(answer_texts) and answer_texts[i]:
                    text += f" ({answer_texts[i]})"
                answer_parts.append(text)
        answers_str = "; ".join(answer_parts) if answer_parts else "no specific preferences"

        familiarity_guidance = ""
        if familiarity:
            familiarity_guidance = (
                "\n\nFamiliarity framing guidance (when Familiarity data is provided for an album):\n"
                "- 'unplayed': Frame as discovery — 'you haven't given this a real shot yet', "
                "emphasize what makes it worth a dedicated listen\n"
                "- 'light': Frame as deeper exploration — 'you haven't done a full listen', "
                "highlight what they'll discover on a closer listen\n"
                "- 'well-loved': Frame as revisit — 'when's the last time you sat down with this?', "
                "offer a fresh angle or new way to appreciate it\n"
            )

        system = (
            "You are a passionate music sommelier. Write compelling pitches for album recommendations.\n\n"
            "For the PRIMARY album, write:\n"
            "- hook: A compelling one-liner that makes someone want to press play immediately\n"
            "- context: An interesting detail about the album (recording story, cultural significance, artist journey)\n"
            "- listening_guide: How to approach the listen — what to expect as it unfolds\n"
            "- connection: Why THIS album matches THIS specific request\n\n"
            "For each SECONDARY album, write:\n"
            "- short_pitch: 2-3 vivid sentences that sell the album\n\n"
            "Use specific, vivid language. Reference the user's words. Avoid generic music-critic clichés.\n"
            "If research data is provided, ground your pitch in real facts.\n"
            f"{familiarity_guidance}\n"
            "Return JSON array of objects with: artist, album, hook, context, listening_guide, connection "
            "(for primary), or short_pitch (for secondary). Include all applicable fields.\n"
            "No explanation, just the JSON array."
        )

        user_prompt = (
            f"User wanted: \"{prompt}\"\n"
            f"Their preferences: {answers_str}\n\n"
            f"Albums to pitch:\n{albums_text}\n\n"
            f"Write the pitches."
        )

        response = self.llm_client.analyze(user_prompt, system)
        self._log_cost("pitch_writing", response, session_id)

        raw = self.llm_client.parse_json_response(response)

        # Match pitches back to recommendations
        pitch_lookup = {}
        for item in raw:
            key = f"{item.get('artist', '').lower()}|||{item.get('album', '').lower()}"
            pitch_lookup[key] = item

        for rec in recommendations:
            key = f"{rec.artist.lower()}|||{rec.album.lower()}"
            item = pitch_lookup.get(key, {})

            if rec.rank == "primary":
                hook = item.get("hook", "")
                context = item.get("context", "")
                listening_guide = item.get("listening_guide", "")
                connection = item.get("connection", "")
                parts = [p for p in [hook, context, listening_guide, connection] if p]
                full_text = "\n\n".join(parts)
                rec.pitch = SommelierPitch(
                    hook=hook,
                    context=context,
                    listening_guide=listening_guide,
                    connection=connection,
                    full_text=full_text,
                )
            else:
                short_pitch = item.get("short_pitch", "")
                rec.pitch = SommelierPitch(
                    short_pitch=short_pitch,
                    full_text=short_pitch,
                )

            # Mark research availability
            if research and f"{rec.artist}|||{rec.album}" in research:
                rec.research_available = True

        return recommendations

    # ── Discovery mode helpers ──────────────────────────────────────────

    def build_taste_profile(self, album_candidates: list[AlbumCandidate]) -> TasteProfile:
        """Aggregate full album list into a taste profile for discovery mode."""
        genre_dist: dict[str, int] = {}
        decade_dist: dict[str, int] = {}
        artist_counts: dict[str, int] = {}
        owned: list[dict[str, str]] = []

        for album in album_candidates:
            for genre in album.genres:
                genre_dist[genre] = genre_dist.get(genre, 0) + 1
            if album.decade:
                decade_dist[album.decade] = decade_dist.get(album.decade, 0) + 1
            artist_counts[album.album_artist] = artist_counts.get(album.album_artist, 0) + 1
            owned.append({"artist": album.album_artist, "album": album.album})

        top_artists = sorted(artist_counts, key=artist_counts.get, reverse=True)[:20]

        return TasteProfile(
            genre_distribution=genre_dist,
            decade_distribution=decade_dist,
            top_artists=top_artists,
            total_albums=len(album_candidates),
            owned_albums=owned,
        )

    def select_discovery_albums(
        self,
        prompt: str,
        answers: list[str | None],
        answer_texts: list[str],
        taste_profile: TasteProfile,
        session_id: str,
    ) -> list[AlbumRecommendation]:
        """Select 1 primary + 2 secondary albums NOT in the user's library.

        Uses taste profile as context and owned_albums as exclusion list.
        Returns list of AlbumRecommendation (without pitches or rating_keys).
        """
        # Build taste summary
        top_genres = sorted(taste_profile.genre_distribution, key=taste_profile.genre_distribution.get, reverse=True)[:10]
        top_decades = sorted(taste_profile.decade_distribution, key=taste_profile.decade_distribution.get, reverse=True)[:5]

        taste_text = (
            f"Top genres: {', '.join(top_genres)}\n"
            f"Top decades: {', '.join(top_decades)}\n"
            f"Top artists: {', '.join(taste_profile.top_artists[:10])}\n"
            f"Library size: {taste_profile.total_albums} albums"
        )

        # Build exclusion list (sample to keep prompt size reasonable)
        owned_sample = taste_profile.owned_albums[:200]
        exclusion_text = "\n".join(
            f"- {a['artist']} — {a['album']}" for a in owned_sample
        )

        # Build answer context
        answer_parts = []
        for i, ans in enumerate(answers):
            if ans:
                text = ans
                if i < len(answer_texts) and answer_texts[i]:
                    text += f" (also: {answer_texts[i]})"
                answer_parts.append(f"Q{i+1} answer: {text}")
            else:
                answer_parts.append(f"Q{i+1}: skipped")
        answers_text = "\n".join(answer_parts)

        system = (
            "You are a music recommendation expert with encyclopedic knowledge. "
            "Recommend 3 albums the user does NOT already own that match their request and taste profile. "
            "The first pick is the PRIMARY recommendation (best match), the other two are SECONDARY.\n\n"
            "IMPORTANT: Do NOT recommend any album from the exclusion list below. "
            "Recommend real, existing albums with correct artist names and years.\n\n"
            "Return a JSON array of 3 objects, each with: artist (string), album (string), "
            "year (integer), rank (\"primary\" for first, \"secondary\" for others).\n"
            "No explanation, just the JSON array."
        )

        user_prompt = (
            f"User wants: \"{prompt}\"\n\n"
            f"Clarifying answers:\n{answers_text}\n\n"
            f"User's taste profile:\n{taste_text}\n\n"
            f"Albums user already owns (DO NOT recommend these):\n{exclusion_text}\n\n"
            f"Recommend 3 albums they don't own: 1 primary + 2 secondary."
        )

        response = self.llm_client.analyze(user_prompt, system)
        self._log_cost("discovery_selection", response, session_id)

        raw = self.llm_client.parse_json_response(response)
        recommendations = []

        for item in raw[:3]:
            rank = item.get("rank", "secondary")
            rec = AlbumRecommendation(
                rank=rank if rank in ("primary", "secondary") else "secondary",
                album=item.get("album", ""),
                artist=item.get("artist", ""),
                year=item.get("year"),
                rating_key=None,
                track_rating_keys=[],
                art_url=None,
            )
            recommendations.append(rec)

        if recommendations and all(r.rank == "secondary" for r in recommendations):
            recommendations[0].rank = "primary"

        return recommendations

    def validate_discovery_album(
        self,
        rec: AlbumRecommendation,
        research: ResearchData,
        prompt: str,
        session_id: str,
    ) -> bool:
        """Validate a discovery album against research data.

        Asks the LLM to confirm the album matches the user's request
        given the real research data. Returns True if valid.
        """
        research_text = f"Album: {rec.artist} — {rec.album}"
        if research.release_date:
            research_text += f"\nRelease date: {research.release_date}"
        if research.label:
            research_text += f"\nLabel: {research.label}"
        if research.genre_tags:
            research_text += f"\nGenres: {', '.join(research.genre_tags)}"
        if research.wikipedia_summary:
            research_text += f"\nAbout: {research.wikipedia_summary[:300]}"

        system = (
            "You are validating an album recommendation. Given the user's request and "
            "research data about the album, determine if this album genuinely matches "
            "the request in terms of genre, mood, and character.\n\n"
            "Return ONLY a JSON object: {\"valid\": true} or {\"valid\": false, \"reason\": \"...\"}"
        )

        user_prompt = (
            f"User wanted: \"{prompt}\"\n\n"
            f"Album research:\n{research_text}\n\n"
            f"Does this album genuinely match the request?"
        )

        response = self.llm_client.generate(user_prompt, system)
        self._log_cost("discovery_validation", response, session_id)

        result = self.llm_client.parse_json_response(response)
        return result.get("valid", True) if isinstance(result, dict) else True
