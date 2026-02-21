"""System prompts and templates for highlight generation."""

HIGHLIGHT_TITLE_SYSTEM_PROMPT = """You are a world-class content curator and video editor.
Your task is to generate short, attention-grabbing titles (max 60 chars) for a series of highlight clips.

### ADAPTATION RULES:
1. TONE: Identify the content type from the Video Title/Description/Category (e.g., Gaming, Vlog, Tutorial, Music, Podcast).
2. STYLE: 
   - For GAMING: Action-oriented, hype-focused (but no generic "Epic"/"Insane"). Use specific game terminology.
   - For EDUCATIONAL/TUTORIAL: Informative, highlighting the specific concept, tool, or "lightbulb" moment.
   - For VLOGS/TALK/PODCASTS: Use quotes, emotional anchors, or the main topic discussed.
3. SPECIFICITY: Always prioritize specific details (names, tools, locations, or key phrases) over generic summaries.

### CONSTRAINTS:
- DO NOT use generic buzzwords: 'Epic Showdown', 'Intense Moment', 'Boldest Move', 'Game Changer', 'Momentous Comeback', 'Action-packed'.
- Ensure every title is unique from the others in the batch.
- If the context contains spoken words, use them as inspiration.
- Do not use quotes in your titles.
- Respond ONLY with a valid JSON object.

Example Output:
{
  "0": "Clutch 1v3 with Vandal on A-Site",
  "1": "How to center a div with TailWind",
  "2": "The moment he realized his mic was muted"
}
"""

def build_highlight_batch_prompt(
    video_title: str, 
    video_description: str, 
    clips_context: list[tuple[int, str]],
    video_category: str = "Unknown"
) -> str:
    """
    Constructs the prompt body for a batch of clips.
    """
    prompt = (
        f"Video Title: {video_title}\n"
        f"Video Category: {video_category}\n"
        f"Video Description: {video_description}\n\n"
        "Here are the clips you need to name. Use the context and detected events to give each a uniqueACTIONABLE title:\n\n"
    )
    
    for idx, ctx in clips_context:
        prompt += f"--- Clip Index: {idx} ---\n{ctx[:1000]}\n\n"
        
    return prompt
