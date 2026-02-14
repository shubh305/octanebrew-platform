from bs4 import BeautifulSoup
import re

class Sanitizer:
    @staticmethod
    def clean_html(html_content: str) -> str:
        """
        Removes HTML tags and cleans up whitespace.
        """
        if not html_content:
            return ""
        
        soup = BeautifulSoup(html_content, "html.parser")
        text = soup.get_text(separator=" ")
        
        # Collapse multiple spaces
        text = re.sub(r'\s+', ' ', text).strip()
        return text
