
from typing import Optional

def get_system_prompt(entity_type: str = "article") -> str:
    """
    Returns the appropriate system prompt based on the entity type.
    """
    if entity_type == "video_transcript" or entity_type == "video":
        return """
You are an expert video content analyzer. Your task is to summarize the following video transcript to enhance discoverability.

Structure your response as follows:
1. **Topic**: The primary subject of the video.
2. **Summary**: A narrative summary of the discussion or presentation.
3. **Key Moments**: A bulleted list of key topics or questions addressed in the video.

Ignore filler words and focus on the substantive content.
""".strip()
    
    elif entity_type == "blog_post":
        return """
You are an expert content analyzer. Your task is to generate a comprehensive summary of the following article to optimize searchability.

Structure your response as follows:
1. **Title**: A representative title.
2. **Overview**: A concise paragraph summarizing the main thesis.
3. **Key Concepts**: A bulleted list of 5 important concepts, entities, or arguments discussed.

Ensure specific terminology and key entities are preserved.
""".strip()

    else:
        # Default fallback
        return """ 
Summarize the following text into exactly 5 concise sentences.

Each sentence must express a distinct key idea.
Avoid repetition, speculation, or adding information not present in the text.
Return only the five sentences as plain text.
""".strip()

def get_user_prompt(text: str, entity_type: str = "article") -> str:
    """
    Returns the user prompt combining the text and any specific instructions.
    Currently just passes the truncated text, but allows for future template expansion
    like "Analyze this text:\n\n{text}".
    """
    truncated_text = text[:10000]
    return f"Text to analyze:\n\n{truncated_text}"
