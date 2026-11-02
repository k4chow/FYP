"""Deterministic mock LLM provider (D5).

Empathetic, reflective replies that reference the film and the user's own
words. No randomness anywhere: template selection is a pure function of the
bounded history and the turn count, so demos, screenshots and tests are
reproducible without an API key.
"""

import re

from .base import ChatContext, LLMProvider

_WORD_RE = re.compile(r"[a-z']+")

# Common words we never quote back at the user.
_STOPWORDS = {
    "about", "after", "again", "because", "before", "being", "between",
    "could", "every", "felt", "feels", "going", "maybe", "might", "movie",
    "much", "never", "really", "scene", "should", "still", "that", "their",
    "them", "there", "these", "they", "thing", "think", "this", "those",
    "through", "watch", "watched", "watching", "were", "what", "when",
    "where", "which", "while", "with", "would", "your",
}

# Quick-reply chips (client sends these verbatim).
_NOT_SURE = {"i'm not sure", "im not sure", "not sure", "i don't know", "i dont know"}
_NEW_QUESTION = {"can you ask a different question", "ask a different question"}
_MAYBE_LATER = {"maybe later"}

_ACKS = (
    "Thank you for sharing that.",
    "That's a thoughtful observation.",
    "I appreciate you putting that into words.",
    "There's a lot in what you just said.",
    "That sounds genuinely meaningful.",
    "I'm glad you brought that up.",
)

_REFLECTIONS = (
    'The way you describe "{kw}" stands out — it clearly meant something to you.',
    'It\'s interesting that "{kw}" is what surfaced for you.',
    'Hearing you talk about "{kw}" says a lot about what you look for in a story.',
)

_QUESTIONS_FILM = (
    "Was there a particular scene or moment in {film} that you keep coming back to?",
    "Did any character in {film} remind you of yourself — or of someone you know?",
    "What do you think {film} is trying to say, underneath the story?",
    "How did you feel in the minutes after {film} ended?",
    "If you could step inside one moment of {film}, which would it be — and why?",
    "Did {film} change how you see anything in your own life, even slightly?",
)

_QUESTIONS_PLANNING = (
    "What are you hoping {film} will make you feel?",
    "Where did you first hear about {film} — and what stuck with you?",
    "Is there something in your life right now that makes this the right moment for {film}?",
    "What would make {film} a great watch for you, do you think?",
)

_QUESTIONS_FREE = (
    "What feeling is strongest as you sit with that now?",
    "Does it connect to anything happening in your own life at the moment?",
    "What do you think drew that reaction out of you?",
    "If you had to describe the feeling in three words, what would they be?",
    "Is that a feeling you recognise from films you love, or something new?",
    "What would you want to remember about this a year from now?",
)


def _keywords(text: str, limit: int = 3) -> list[str]:
    """Distinct content words (len >= 5) from the user's message, in order."""
    found: list[str] = []
    for word in _WORD_RE.findall(text.lower()):
        if len(word) >= 5 and word not in _STOPWORDS and word not in found:
            found.append(word)
    return found[:limit]


def _genre_hit(text: str, genres: list[str]) -> str | None:
    lowered = text.lower()
    for genre in genres:
        if genre.lower() in lowered:
            return genre
    return None


class MockLLMProvider(LLMProvider):
    """Scripted, deterministic provider — the reference implementation of the
    seam a real provider (e.g. OpenAI) will fill later."""

    def opening(self, context: ChatContext) -> str:
        film = context.film or {}
        title = film.get("title")
        name = f", {context.display_name}" if context.display_name else ""
        if title and context.watch_type == "planning":
            return (
                f"{title} is one you're planning to watch — a different kind of "
                f"reflection{name}. What draws you to it? What are you hoping "
                f"it will make you feel?"
            )
        if title:
            return (
                f"Let's talk about {title}{name}. Take your time — there are no "
                f"right or wrong answers here. What stayed with you most after "
                f"watching it?"
            )
        if context.title:
            return (
                f"You wanted to reflect on this: “{context.title}” "
                f"What's coming up for you as you sit with that?"
            )
        return "This is your space to reflect. What's on your mind today?"

    def chat(self, messages: list[dict], context: ChatContext) -> str:
        last = next((m for m in reversed(messages) if m.get("role") == "user"), None)
        text = (last or {}).get("content", "").strip()
        normalised = text.lower().strip().rstrip("?!.")
        film = context.film or {}
        film_title = film.get("title") or "the film"

        # Quick-reply chips get dedicated, gentle handling.
        if normalised in _NOT_SURE:
            if film:
                return (
                    "That's completely okay — there's no right answer here, and "
                    "uncertainty is a fine place to start. Let's make it smaller: "
                    f"in a single word, how did {film_title} leave you feeling?"
                )
            return (
                "That's completely okay — uncertainty is a fine place to start. "
                "Let's make it smaller: what's one word for how you feel right now?"
            )
        if normalised in _NEW_QUESTION:
            return (
                "Of course — let's try a different angle. "
                f"{self._question(context, offset=1)}"
            )
        if normalised in _MAYBE_LATER:
            return (
                "No pressure at all. Everything you've said is saved, and we can "
                "pick this up whenever you're ready — or simply sit with it."
            )

        parts: list[str] = [_ACKS[context.turn % len(_ACKS)]]

        hit = _genre_hit(text, film.get("genres") or [])
        keywords = _keywords(text)
        if hit:
            parts.append(
                f"You picked up on the {hit.lower()} side of {film_title} — "
                "that says something about what you notice in stories."
            )
        elif keywords:
            parts.append(
                _REFLECTIONS[context.turn % len(_REFLECTIONS)].format(kw=keywords[0])
            )

        # Occasionally weave in a confirmed memory (F4: confirmed only).
        if context.memories and context.turn % 3 == 2:
            memory = context.memories[(context.turn // 3) % len(context.memories)]
            parts.append(
                f'It echoes something you\'ve told me before — "{memory}". '
                "Does that feel present here too?"
            )

        parts.append(self._question(context))
        return " ".join(parts)

    def _question(self, context: ChatContext, offset: int = 0) -> str:
        film = context.film or {}
        if context.watch_type == "planning" and film:
            bank = _QUESTIONS_PLANNING
        elif film:
            bank = _QUESTIONS_FILM
        else:
            bank = _QUESTIONS_FREE
        return bank[(context.turn + offset) % len(bank)].format(
            film=film.get("title") or "the film"
        )

    def extract_insights(
        self, messages: list[dict], context: ChatContext
    ) -> list[dict]:
        # Phase 4: deterministic mock extraction for the Review & Edit flow.
        return []
