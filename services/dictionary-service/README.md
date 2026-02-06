# Dictionary Service

A multi-language linguistic analysis engine and dictionary utility for the OctaneBrew platform. 

The service provides deep word analysis, grammar checking, and cross-language translation, with specialized heuristics for handling romanized languages (e․g․, Romaji).

## Features

- **Advanced Word Analysis**: Powered by spaCy and TextBlob for POS tagging and linguistic structure.
- **Multi-layered Language Detection**: Custom fallback logic to correctly identify short Romaji strings (like "arigato") which are often misdetected as Estonian or Tagalog.
- **Linguistic Utilities**:
  - **Definitions**: Integrated with WordNet via TextBlob.
  - **Synonyms & Antonyms**: Comprehensive lexical relationships.
  - **Pluralization**: Intelligent plural generation via `inflect`.
  - **Grammar & Spell Checking**: Integration with LanguageTool for real-time English validation.
- **Synthetic Meaning Generation**: Provides meaningful context for translated phrases where direct dictionary entries might not exist.
- **Result Caching**: Redis-backed caching with a 1-hour TTL for high-performance repeat lookups.

## Security

The service is protected by a mandatory **Internal Authentication Layer**.

- **Header**: `X-API-KEY`
- **Validation**: Requests must include the platform-wide `SERVICE_API_KEY` defined in the root `.env`.

## Tech Stack

- **Core**: Python 3.12, FastAPI
- **NLP**: [spaCy](https://spacy.io/), [TextBlob](https://textblob.readthedocs.io/), [inflect](https://github.com/pwmanv/inflect)
- **Translation**: [googletrans](https://github.com/ssut/py-googletrans) (optimized)
- **Detection**: [langdetect](https://github.com/Mimino666/langdetect)
- **Grammar**: [LanguageTool](https://languagetool.org/)
- **Cache/Rate Limit**: Redis, `fastapi-limiter`
- **Build**: [uv](https://github.com/astral-sh/uv) (for ultra-fast package management and Docker layer caching)

## API Reference

### Word Lookup
`POST /v1/lookup`

**Request Headers:**
```http
X-API-KEY: your_service_api_key
Content-Type: application/json
```

**Request Body:**
```json
{
  "word": "arigato"
}
```

**Response Snapshot:**
```json
[
  {
    "word": "arigato",
    "meanings": [
      {
        "partOfSpeech": "translation",
        "definitions": [
          {
            "definition": "English translation of the JA word 'arigato'",
            "example": "The ja word 'arigato' translates to 'thank you' in English."
          }
        ]
      }
    ],
    "metadata": {
      "detected_language": "ja",
      "translation": "thank you",
      "analysis_word": "thank you",
      "is_correct": true
    }
  }
]
```

## ⚙️ Development & Testing

### **Dependency Management**
This project uses `uv`. To sync dependencies:
```bash
uv sync
```

### **Docker Build**
The Dockerfile is optimized for caching. NLP models and LanguageTool corpora are pre-downloaded in a cached layer to ensure extremely fast subsequent builds.
