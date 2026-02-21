"""Enrichment — Intelligence Service calls for OCR cleanup and clip title generation."""

import logging
import httpx

from .config import settings

logger = logging.getLogger(__name__)

# Timeout for Intelligence Service calls
TIMEOUT = httpx.Timeout(30.0, connect=10.0)


import json
from .prompts import HIGHLIGHT_TITLE_SYSTEM_PROMPT, build_highlight_batch_prompt

async def generate_batch_clip_titles(
    clips_context: list[tuple[int, str]],
    video_title: str,
    video_description: str,
    video_category: str = "Unknown",
) -> dict[int, str]:
    """
    Call Intelligence Service to generate titles for a batch of clips.

    Returns:
        Dict mapping integer clip index to its generated title.
    """
    default_titles = {idx: f"Highlight #{idx + 1}" for idx, _ in clips_context}
    
    if not settings.INTELLIGENCE_SVC_URL or not clips_context:
        return default_titles

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            prompt_content = build_highlight_batch_prompt(video_title, video_description, clips_context, video_category)
            
            response = await client.post(
                f"{settings.INTELLIGENCE_SVC_URL}/v1/chat/completions",
                headers={
                    "X-API-KEY": settings.SERVICE_API_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "system": HIGHLIGHT_TITLE_SYSTEM_PROMPT,
                    "prompt": prompt_content,
                    "model": "fast"
                },
            )
            response.raise_for_status()
            data = response.json()

            content = data.get("content", "")

            # Attempt to parse json
            # Handle markdown code blocks if present
            import re
            json_match = re.search(r"```json\s*(\{.*?\})\s*```", content, re.DOTALL)
            if json_match:
                content = json_match.group(1)
            else:
                # Fallback: strip backticks if they are lone
                content = content.replace("```json", "").replace("```", "").strip()

            if not content:
                logger.warning("Empty response from Intelligence Service for batch titles")
                return default_titles
                
            try:
                parsed_json = json.loads(content)
            except json.JSONDecodeError as je:
                logger.error(f"Failed to parse LLM JSON: {je}. Raw: {content}")
                return default_titles
            
            # Map back to int keys safely
            result_titles = {}
            for k, v in parsed_json.items():
                try:
                    result_titles[int(k)] = str(v).strip()
                except (ValueError, TypeError):
                    continue
            
            # Merge with defaults for missing keys
            for idx, _ in clips_context:
                if idx not in result_titles:
                    result_titles[idx] = default_titles[idx]
                    
            return result_titles

    except Exception as e:
        logger.error(f"Failed to generate batch titles: {e}")
        return default_titles


async def enrich_clips(
    clips: list[dict],
    video_title: str,
    video_description: str = "",
    vtt_content: str | None = None,
    video_category: str = "Unknown",
) -> list[dict]:
    """
    Enrich clip dicts with AI-generated titles.
    
    Modifies clips in-place but also returns them.
    """
    if not clips:
        return []

    # Prepare contexts for each clip
    clips_contexts = []
    for clip in clips:
        try:
            # Simple context: combine OCR words if present
            context_parts = []
            
            if vtt_content:
                # Filter transcript to clip window
                context_parts.append(f"TRANSCRIPT SNIPPET: {vtt_content[:2000]}")

            ocr_results = clip.get('signals', {}).get('ocr_raw', [])
            if ocr_results:
                words = [r.get('text', '') for r in ocr_results]
                context_parts.append(f"DETECTED TEXT: {' '.join(words)}")
                
            # Add signal intent
            signals = clip.get('signals', {})
            active = [k for k, v in signals.items() if v and k != 'ocr_raw']
            if active:
                context_parts.append(f"SYSTEM SIGNALS: {', '.join(active)}")

            clips_contexts.append((clip.get('index', 0), "\n".join(context_parts)))
        except Exception as e:
            logger.warning(f"Context extraction failed for clip {clip.get('index')}: {e}")

    # Generate batch titles
    batch_titles = await generate_batch_clip_titles(clips_contexts, video_title, video_description, video_category)

    for clip in clips:
        idx = clip.get('index', 0)
        clip['title'] = batch_titles.get(idx, f"Highlight #{idx + 1}")

    return clips
