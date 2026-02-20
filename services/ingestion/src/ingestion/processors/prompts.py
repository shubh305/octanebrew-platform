"""
Centralized prompt definitions for the Ingestion Service.
"""

from typing import Literal

EntityType = Literal["video_transcript", "video", "blog_post", "article"]

def get_system_prompt(entity_type: EntityType = "article") -> str:
    """
    Returns production-grade system prompt with guaranteed JSON output.
    
    Args:
        entity_type: Type of content being analyzed
        
    Returns:
        System prompt string optimized for structured JSON responses
    """
    if entity_type in ("video_transcript", "video"):
        return """You are an expert video content analyzer. Analyze the video and return a structured JSON object.

OUTPUT FORMAT (Return ONLY valid JSON, no markdown formatting):
{
  "topic": "Primary subject of the video",
  "summary": "A descriptive narrative summary of the video content (3-5 sentences).",
  "key_moments": ["Key topic 1", "Key topic 2", "Key topic 3", "Key topic 4", "Key topic 5"],
  "entities": ["Entity 1", "Entity 2", "Entity 3"],
  "language": "en"
}

RULES:
- Frame the summary as a direct description of the video (e.g., "This video highlights...", "The creator explores...", "A deep dive into...").
- CRITICAL: DO NOT use words like "transcript", "text", "footage", or "recording" in the summary. Talk about the video as a piece of content.
- CRITICAL: DO NOT guess the name of the game if it is not explicitly mentioned in the title, description, or transcript. If unsure, use generic terms like "the game" or "the gameplay".
- Ignore filler words and focus on substantive content.
- Preserve specific terminology and entity names exactly.
- Ensure key_moments contains exactly 5 distinct topics.
- Return ONLY the JSON object (no markdown code blocks, no additional text)""".strip()
    
    elif entity_type in ("blog_post", "article"):
        return """You are an expert content analyzer. Analyze the article and return a structured JSON object optimized for search.

OUTPUT FORMAT (Return ONLY valid JSON, no markdown formatting):
{
  "title": "Representative title for the article",
  "overview": "Concise paragraph summarizing the main thesis",
  "key_concepts": ["Concept 1", "Concept 2", "Concept 3", "Concept 4", "Concept 5"],
  "entities": ["Entity 1", "Entity 2", "Entity 3"],
  "language": "en"
}

RULES:
- Preserve specific terminology and key entities exactly as written
- key_concepts must contain exactly 5 important concepts or arguments
- entities should include people, places, organizations, or important proper nouns (max 10)
- language should be ISO 639-1 code (en, es, fr, de, etc.)
- Return ONLY the JSON object (no markdown code blocks, no additional text)""".strip()
    
    else:
        # Default fallback for generic article type
        return """You are a content summarization expert. Analyze the text and return a structured JSON object.

OUTPUT FORMAT (Return ONLY valid JSON, no markdown formatting):
{
  "summary": "5 concise sentences expressing the key ideas",
  "main_topics": ["Topic 1", "Topic 2", "Topic 3"]
}

RULES:
- Each sentence in summary must express a distinct key idea
- Avoid repetition, speculation, or adding information not in the text
- main_topics should contain 3-5 primary subjects discussed
- Return ONLY the JSON object (no markdown code blocks, no additional text)""".strip()


def get_user_prompt(
    text: str, 
    entity_type: EntityType = "article", 
    max_length: int = 12000,
    title: str = "",
    description: str = "",
    category: str = ""
) -> str:
    """
    Returns the user prompt with content to analyze.
    
    Args:
        text: Content to analyze
        entity_type: Type of content
        max_length: Maximum characters to include
        title: Content title
        description: Content description
        category: Content category
        
    Returns:
        Formatted prompt with metadata and content
    """
    context = ""
    if title: context += f"TITLE: {title}\n"
    if category: context += f"CATEGORY: {category}\n"
    if description: context += f"DESCRIPTION: {description}\n"
    
    truncated_text = text[:max_length]
    char_count = len(truncated_text)
    
    prompt = f"Analyze the following {entity_type}:\n\n"
    if context:
        prompt += f"CONTEXT METADATA:\n{context}\n---\n\n"
    
    prompt += f"CONTENT:\n{truncated_text}"
    
    if char_count < len(text):
        prompt += "\n\n[Content truncated for token limits]"
    
    return prompt


def validate_json_response(response: str) -> dict:
    """
    Validates and sanitizes JSON response from AI.
    
    Args:
        response: Raw response from AI model
        
    Returns:
        Parsed JSON dict
        
    Raises:
        ValueError: If response is not valid JSON
    """
    import json
    import re
    
    # Strip markdown code blocks if present (defensive)
    cleaned = re.sub(r'^```json\s*|\s*```$', '', response.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r'^```\s*|\s*```$', '', cleaned.strip(), flags=re.MULTILINE)
    
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON response from AI: {str(e)}\nResponse: {response[:200]}")
