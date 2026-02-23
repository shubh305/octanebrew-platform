"""VTT Semantic signal — compiled regex pattern groups + window aggregation + negation filtering."""

import asyncio
import logging
import re
from pathlib import Path
from . import BaseSignal

logger = logging.getLogger(__name__)

# ── WebVTT timestamp parser
VTT_TIME_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})\.(\d{3})"
)


def _vtt_time(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


# ── Compiled pattern groups (module-level, compiled once)

EXCITEMENT_RE = re.compile(
    r"\b(amazing|incredible|unbelievable|insane|crazy|no\s+way|let'?s?\s+go"
    r"|wow+|oh+\s+my+\s+god+|lets\s+go|omg)\b",
    re.IGNORECASE,
)

CLUTCH_RE = re.compile(
    r"\b(clutch|last\s+(man|player|one)|1v[1-5]|match\s+point|overtime"
    r"|this\s+is\s+it|sudden\s+death)\b",
    re.IGNORECASE,
)

SHOCK_RE = re.compile(
    r"\b(what[!?]+|how[!?]+|are\s+you\s+serious|no\s+shot|that'?s\s+wild|ohhh+|no+\s+way)\b",
    re.IGNORECASE,
)

VICTORY_RE = re.compile(
    r"\b(win(s|ning|ner)?|victor(y|ious)|champion|we\s+got\s+it"
    r"|that'?s\s+game|game\s+over|gg)\b",
    re.IGNORECASE,
)

NEGATION_RE = re.compile(
    r"\b(not\s+amazing|not\s+good|no\s+hype|wasn'?t|not\s+even|boring)\b",
    re.IGNORECASE,
)

ESCALATION_RE = re.compile(
    r"\b(wait\s+wait|watch\s+this|look\s+at\s+this|right\s+now|here\s+we\s+go|oh\s+no)\b",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation except ! and ?, collapse repeated chars."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9!?\s']", " ", text)
    text = re.sub(r"(.)\1{2,}", r"\1\1", text)
    return text


def _score_text(text: str, repetition_boost: bool, negation_filter: bool) -> float:
    """Score a single normalized text snippet."""
    score = 0.0

    if EXCITEMENT_RE.search(text):
        score += 0.4
    if CLUTCH_RE.search(text):
        score += 0.5
    if SHOCK_RE.search(text):
        score += 0.4
    if VICTORY_RE.search(text):
        score += 0.6

    if score == 0.0:
        return 0.0

    if repetition_boost and text.count("!") >= 2:
        score += 0.2

    if negation_filter and NEGATION_RE.search(text):
        score = max(0.0, score - 0.3)

    return min(1.0, score)


class VttSemanticSignal(BaseSignal):
    """
    Upgrade over v1:
    - Compiled regex pattern groups instead of flat keyword list
    - Context-based graded scoring (excitement/clutch/shock/victory)
    - Repetition boost (!! in text → +0.2)
    - Negation filter (reduce on "not amazing" etc.)
    - Escalation boost (escalation phrase within window → +0.2)
    - Window aggregation: cumulative score in window_seconds → highlight candidate
    """

    @property
    def name(self) -> str:
        return "vtt_semantic"

    async def detect(self, proxy_path: str, config: dict, **kwargs) -> dict[int, float]:
        vtt_path = kwargs.get("vtt_path")
        if not vtt_path or not Path(vtt_path).is_file():
            logger.info("VttSemantic: no valid en.vtt file found — skipping")
            return {}

        window_seconds = float(config.get("window_seconds", 3.0))
        repetition_boost = bool(config.get("repetition_boost", True))
        escalation_boost = bool(config.get("escalation_boost", True))
        negation_filter = bool(config.get("negation_filter", True))

        try:
            content = Path(vtt_path).read_text(encoding="utf-8")
        except OSError as e:
            logger.warning(f"VttSemantic: failed to read VTT: {e}")
            return {}

        # ── Parse VTT cues
        cues: list[tuple[float, float, str]] = []
        lines = content.split("\n")
        current_start = 0.0
        current_end = 0.0

        for line in lines:
            time_match = VTT_TIME_RE.match(line.strip())
            if time_match:
                groups = time_match.groups()
                current_start = _vtt_time(*groups[:4])
                current_end = _vtt_time(*groups[4:])
            elif line.strip() and not line.strip().startswith("WEBVTT") and not line.strip().isdigit():
                cues.append((current_start, current_end, _normalize(line.strip())))

        logger.info(f"VttSemantic: Parsed {len(cues)} total cues from VTT")

        # ── Score each cue
        cue_scores: list[tuple[float, float, float]] = []
        
        esc_ptr = 0
        
        for i, (start, end, text) in enumerate(cues):
            s = _score_text(text, repetition_boost, negation_filter)

            if escalation_boost and s > 0:
                window_start = start - 2.0
                # Move esc_ptr forward to window_start
                while esc_ptr < len(cues) and cues[esc_ptr][0] < window_start:
                    esc_ptr += 1
                
                # Check from esc_ptr up to current cue
                for k in range(esc_ptr, i):
                    if ESCALATION_RE.search(cues[k][2]):
                        s = min(1.0, s + 0.2)
                        break

            if s > 0:
                cue_scores.append((start, end, s))
            
            if i % 2000 == 0:
                await asyncio.sleep(0)

        # ── Window aggregation: aggregate over window_seconds
        scores: dict[int, float] = {}
        
        right_ptr = 0
        for i, (start, end, score) in enumerate(cue_scores):
            window_end = start + window_seconds
            
            # Advance right_ptr to the end of the window
            while right_ptr < len(cue_scores) and cue_scores[right_ptr][0] <= window_end:
                right_ptr += 1
            
            # Window is cue_scores[i : right_ptr]
            cumulative = sum(sc for _, _, sc in cue_scores[i : right_ptr])

            cumulative = min(1.0, cumulative)
            sec_start = int(start)
            sec_end = int(end)
            for sec in range(sec_start, sec_end + 1):
                scores[sec] = max(scores.get(sec, 0), cumulative)
                
            if i % 1000 == 0:
                await asyncio.sleep(0)

        logger.info(
            f"VttSemantic: {len(scores)} scored seconds from {len(cue_scores)} matching cues"
        )
        return scores
