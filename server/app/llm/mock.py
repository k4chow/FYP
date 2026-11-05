"""Mock LLM provider (D5) with a randomised reflective prompt bank (D27).

Empathetic, reflective replies that reference the film and the user's own
words. Reflection questions are drawn from prompt banks (openers, film
follow-ups, planning questions, free-reflection deepeners) and sampled
without repetition within a session: a question already asked in the bounded
history is not asked again until the bank is exhausted (then it resets,
still excluding the most recent question).

Randomness is injectable: pass ``MockLLMProvider(rng=random.Random(seed))``
for deterministic tests and demos. The default singleton (get_llm) uses an
unseeded ``random.Random`` so real sessions vary naturally.
"""

import random
import re

from .base import ChatContext, LLMProvider

_WORD_RE = re.compile(r"[a-z']+")

# Common words we never quote back at the user.
_STOPWORDS = {
    "about", "after", "again", "because", "before", "being", "between",
    "could", "every", "felt", "feels", "going", "maybe", "might", "movie",
    "loved", "love", "much", "never", "really", "scene", "should", "still", "that", "their",
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

# Opening prompts (used once per conversation, sampled per session).
_OPENERS_FILM = (
    "What stayed with you most after watching it?",
    "When you think back on it now, what's the first thing that comes up?",
    "If you had to keep just one moment of it, which would it be?",
    "How did it leave you feeling, once the credits rolled?",
)

_OPENERS_PLANNING = (
    "What draws you to it? What are you hoping it will make you feel?",
    "What made you add this one to your list?",
    "What would make this a great watch for you?",
)

_OPENERS_FREE = (
    "What's coming up for you as you sit with that?",
    "Where does your mind go first when you think about it?",
    "What feels most alive in that thought right now?",
)

_QUESTIONS_FREE = (
    "What feeling is strongest as you sit with that now?",
    "Does it connect to anything happening in your own life at the moment?",
    "What do you think drew that reaction out of you?",
    "If you had to describe the feeling in three words, what would they be?",
    "Is that a feeling you recognise from films you love, or something new?",
    "What would you want to remember about this a year from now?",
)

# Film Assistant discovery conversations (F10, Phase 6).
_OPENERS_DISCOVERY = (
    "What kind of story are you in the mood for right now?",
    "Is there a feeling you want your next film to leave you with?",
    "Are you after something familiar and comforting, or a surprise?",
)

_QUESTIONS_DISCOVERY = (
    "Is there a film you loved recently that we could use as a compass?",
    "Any genres or moods you're drawn to today — or ones you'd rather avoid?",
    "Do you want something light, or something that sits with you afterwards?",
    "Who are you watching with, if anyone — does that shape the pick?",
    "Would you rather revisit a world you know or step into a new one?",
    "What should this film leave you thinking about tomorrow?",
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


_QUICK_REPLIES = _NOT_SURE | _NEW_QUESTION | _MAYBE_LATER

# Observable film/reflection language only — deliberately no mental-health
# or personality inference. Values are phrased as qualities of the work.
_SIGNALS = (
    ("loved", "emotional connection"),
    ("love", "emotional connection"),
    ("moving", "emotional impact"),
    ("quiet", "quiet atmosphere"),
    ("atmosphere", "atmosphere"),
    ("grief", "treatment of grief"),
    ("loneliness", "treatment of loneliness"),
    ("connection", "treatment of connection"),
    ("honest", "honest relationships"),
    ("hopeful", "hopeful tone"),
    ("ending", "ending"),
)


def _normalised(text: str) -> str:
    return text.lower().strip().rstrip("?!.")


def _excerpt(text: str, limit: int = 110) -> str:
    clean = " ".join(text.split())
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


def _substantive_user_messages(messages: list[dict]) -> list[dict]:
    return [
        message
        for message in messages
        if message.get("role") == "user"
        and len(str(message.get("content", "")).split()) >= 3
        and _normalised(str(message.get("content", ""))) not in _QUICK_REPLIES
    ]


class MockLLMProvider(LLMProvider):
    """Scripted provider — the reference implementation of the seam a real
    provider (e.g. OpenAI) will fill later.

    `rng` is injectable (D27): seeded in tests, unseeded by default.
    """

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()

    def opening(self, context: ChatContext) -> str:
        film = context.film or {}
        title = film.get("title")
        name = f", {context.display_name}" if context.display_name else ""
        if title and context.watch_type == "planning":
            return (
                f"{title} is one you're planning to watch — a different kind of "
                f"reflection{name}. {self._rng.choice(_OPENERS_PLANNING)}"
            )
        if title:
            return (
                f"Let's talk about {title}{name}. Take your time — there are no "
                f"right or wrong answers here. {self._rng.choice(_OPENERS_FILM)}"
            )
        if context.conversation_type == "discovery":
            return (
                f"Let's find your next film{name}. The more honestly you "
                f"describe your mood, the better I can point you somewhere "
                f"worthwhile. {self._rng.choice(_OPENERS_DISCOVERY)}"
            )
        if context.title:
            return (
                f"You wanted to reflect on this: “{context.title}” "
                f"{self._rng.choice(_OPENERS_FREE)}"
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
                f"{self._question(context, messages)}"
            )
        if normalised in _MAYBE_LATER:
            return (
                "No pressure at all. Everything you've said is saved, and we can "
                "pick this up whenever you're ready — or simply sit with it."
            )

        parts: list[str] = [self._rng.choice(_ACKS)]

        hit = _genre_hit(text, film.get("genres") or [])
        keywords = _keywords(text)
        if hit:
            parts.append(
                f"You picked up on the {hit.lower()} side of {film_title} — "
                "that says something about what you notice in stories."
            )
        elif keywords:
            parts.append(self._rng.choice(_REFLECTIONS).format(kw=keywords[0]))

        # Occasionally weave in a confirmed memory (F4: confirmed only).
        if context.memories and context.turn % 3 == 2:
            memory = context.memories[(context.turn // 3) % len(context.memories)]
            parts.append(
                f'It echoes something you\'ve told me before — "{memory}". '
                "Does that feel present here too?"
            )

        parts.append(self._question(context, messages))
        return " ".join(parts)

    def _question(self, context: ChatContext, messages: list[dict]) -> str:
        """Sample a follow-up question not yet asked in this session (D27).

        Questions already present in the bounded assistant history are
        excluded; when the bank is exhausted it resets, still excluding the
        most recently asked question so back-to-back repeats never happen.
        """
        film = context.film or {}
        if context.watch_type == "planning" and film:
            bank = _QUESTIONS_PLANNING
        elif film:
            bank = _QUESTIONS_FILM
        elif context.conversation_type == "discovery":
            bank = _QUESTIONS_DISCOVERY
        else:
            bank = _QUESTIONS_FREE
        film_name = film.get("title") or "the film"
        formatted = [template.format(film=film_name) for template in bank]

        asked = [
            question
            for message in messages
            if message.get("role") == "assistant"
            for question in formatted
            if question in str(message.get("content", ""))
        ]
        fresh = [question for question in formatted if question not in asked]
        if fresh:
            return self._rng.choice(fresh)
        # Bank exhausted: reset, but never repeat the most recent question.
        last = asked[-1] if asked else None
        remaining = [question for question in formatted if question != last]
        return self._rng.choice(remaining or formatted)

    def extract_insights(
        self, messages: list[dict], context: ChatContext
    ) -> list[dict]:
        """Extract at most three deterministic, source-grounded proposals.

        The mock intentionally summarises observations about the film and the
        user's stated attention/preferences; it does not diagnose the user.
        """
        user_messages = _substantive_user_messages(messages)
        if not user_messages:
            return []

        film = context.film or {}
        film_title = film.get("title") or "this film"
        existing = {memory.strip().casefold() for memory in context.memories}
        proposals: list[dict] = []

        def source_ids(rows: list[dict]) -> list[str]:
            return [str(row.get("id", "")) for row in rows if row.get("id")]

        def add(content: str, kind: str, sources: list[dict], explanation: str) -> None:
            key = content.strip().casefold()
            if not content or not sources or key in existing:
                return
            if any(p["content"].strip().casefold() == key for p in proposals):
                return
            proposals.append(
                {
                    "content": content,
                    "kind": kind,
                    "explanation": explanation,
                    "source_message_ids": source_ids(sources),
                }
            )

        # 1. A theme is strongest when the user's own content words recur.
        occurrences: dict[str, list[dict]] = {}
        for message in user_messages:
            for word in set(_keywords(str(message.get("content", "")), limit=8)):
                occurrences.setdefault(word, []).append(message)
        recurring = [word for word, rows in occurrences.items() if len(rows) > 1]
        if recurring:
            rows = occurrences[recurring[0]][:2]
            if len(recurring) > 1:
                seen_ids = {row.get("id") for row in rows}
                rows += [
                    row
                    for row in occurrences[recurring[1]][:1]
                    if row.get("id") not in seen_ids
                ]
                content = (
                    f"You kept returning to {recurring[0]} and {recurring[1]} "
                    "in this reflection."
                )
            else:
                content = f"You kept returning to {recurring[0]} in this reflection."
            add(
                content,
                "theme",
                rows,
                "Proposed because this idea appears in more than one of your messages.",
            )
        else:
            first = user_messages[0]
            words = _keywords(str(first.get("content", "")), limit=2)
            if words:
                phrase = " and ".join(words)
                add(
                    f"You were drawn to {phrase} while reflecting on {film_title}.",
                    "theme",
                    [first],
                    f"Proposed because you wrote: “{_excerpt(str(first.get('content', '')))}”.",
                )

        # 2. One observable emotional/stylistic quality that shaped the reflection.
        signal_hits: list[tuple[str, dict]] = []
        for message in user_messages:
            lowered = str(message.get("content", "")).lower()
            for token, label in _SIGNALS:
                if re.search(rf"\b{re.escape(token)}\b", lowered):
                    signal_hits.append((label, message))
                    break
        if signal_hits:
            label, source = signal_hits[0]
            subject = f"{film_title}'s" if film else "This reflection's"
            add(
                f"{subject} {label} shaped what stayed with you.",
                "insight",
                [source],
                f"Proposed because you wrote: “{_excerpt(str(source.get('content', '')))}”.",
            )

        # 3. A cautious preference/attention observation, never one per message.
        if len(user_messages) > 1:
            remaining = [
                (label, source)
                for label, source in signal_hits
                if not any(p["source_message_ids"] == source_ids([source]) for p in proposals)
            ]
            if remaining:
                label, source = remaining[0]
                content = f"You respond to films with {label}."
            else:
                source = user_messages[-1]
                words = _keywords(str(source.get("content", "")), limit=2)
                label = " and ".join(words)
                content = f"In this reflection, you paid particular attention to {label}."
            add(
                content,
                "preference",
                [source],
                f"Proposed because you wrote: “{_excerpt(str(source.get('content', '')))}”.",
            )

        return proposals[:3]
