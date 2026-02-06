import logging
import spacy
import inflect
from textblob import Word, TextBlob
import language_tool_python
from googletrans import Translator
from langdetect import detect_langs, DetectorFactory
from typing import List, Dict, Any, Optional

# Set seed for deterministic detection
DetectorFactory.seed = 0

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

class DictionaryEngine:
    def __init__(self):
        # Initialize NLP models and tools
        self.nlp = spacy.load("en_core_web_sm")
        self.p = inflect.engine()
        self.tool = language_tool_python.LanguageTool('en-US')
        self.translator = Translator()

    def analyze(self, word: str) -> List[Dict[str, Any]]:
        logger.info(f"Analyzing word: {word}")
        original_word = word
        
        # Multi-layered Language Detection & Translation
        src_lang = "unknown"
        analysis_word = word
        try:
            logger.info("Performing initial auto-translation...")
            translated = self.translator.translate(word, dest="en")
            src_lang = translated.src
            analysis_word = translated.text
            
            # Check for suspicious languages (common false positives)
            suspicious_langs = ["et", "vi", "tl", "sq", "la"]
            
            is_same = analysis_word.lower() == word.lower()
            if (is_same or src_lang in suspicious_langs) and src_lang != "en" and len(word) < 15:
                logger.info(f"Suspicious detection ({src_lang}). Trying common fallbacks...")
                for fallback_lang in ["ja", "es", "fr"]:
                    if fallback_lang == src_lang: continue
                    try:
                        fb_trans = self.translator.translate(word, src=fallback_lang, dest="en")
                        if fb_trans.text.lower() != word.lower():
                            src_lang = fallback_lang
                            analysis_word = fb_trans.text
                            logger.info(f"Fallback SUCCESS: {src_lang} -> {analysis_word}")
                            break
                    except:
                        continue
            
            translation_to_en = analysis_word if analysis_word.lower() != word.lower() else None
            logger.info(f"Final detection: {src_lang}, Translation: {translation_to_en}")
        except Exception as e:
            logger.error(f"Translation/Detection failed: {e}")
            translation_to_en = None

        logger.info(f"WordNet lookup for: {analysis_word}")
        blob_word = Word(analysis_word)
        
        # Mapping WordNet POS to full names
        pos_map = {
            'n': 'noun',
            'v': 'verb',
            'a': 'adjective',
            's': 'adjective satellite',
            'r': 'adverb'
        }

        meanings_dict = {}

        for synset in blob_word.synsets:
            pos = pos_map.get(synset.pos(), synset.pos())
            if pos not in meanings_dict:
                meanings_dict[pos] = {
                    "partOfSpeech": pos,
                    "definitions": [],
                    "synonyms": [],
                    "antonyms": []
                }
            
            definition = {
                "definition": synset.definition(),
                "synonyms": [],
                "antonyms": [],
                "example": synset.examples()[0] if synset.examples() else None
            }

            # Synonyms and Antonyms for this synset
            for lemma in synset.lemmas():
                lemma_name = lemma.name().replace('_', ' ')
                if lemma_name.lower() != analysis_word.lower():
                    definition["synonyms"].append(lemma_name)
                    meanings_dict[pos]["synonyms"].append(lemma_name)
                
                if lemma.antonyms():
                    antonym_name = lemma.antonyms()[0].name().replace('_', ' ')
                    definition["antonyms"].append(antonym_name)
                    meanings_dict[pos]["antonyms"].append(antonym_name)

            # Limit local synonyms/antonyms
            definition["synonyms"] = list(set(definition["synonyms"]))[:5]
            definition["antonyms"] = list(set(definition["antonyms"]))[:5]
            
            meanings_dict[pos]["definitions"].append(definition)

        meanings = []
        for pos_data in meanings_dict.values():
            pos_data["synonyms"] = list(set(pos_data["synonyms"]))[:10]
            pos_data["antonyms"] = list(set(pos_data["antonyms"]))[:10]
            meanings.append(pos_data)

        # Handle cases where no meanings found but word was translated
        if not meanings and translation_to_en:
            logger.info("No WordNet meanings, providing synthetic translation meaning.")
            meanings.append({
                "partOfSpeech": "translation",
                "definitions": [{
                    "definition": f"English translation of the {src_lang.upper()} word '{original_word}'",
                    "synonyms": [],
                    "antonyms": [],
                    "example": f"The {src_lang} word '{original_word}' translates to '{translation_to_en}' in English."
                }],
                "synonyms": [translation_to_en],
                "antonyms": []
            })

        plurals = []
        # Only pluralize if it's likely a noun or we have a single word
        if " " not in analysis_word:
            plural_word = self.p.plural(analysis_word)
            if plural_word and plural_word != analysis_word:
                plurals.append(plural_word)

        # 5. Grammar and Spell Check (LanguageTool)
        is_correct = True
        suggestions = []
        if src_lang == "en":
            try:
                logger.info("Spell checking...")
                matches = self.tool.check(analysis_word)
                is_correct = len(matches) == 0
                if not is_correct:
                    suggestions = matches[0].replacements
            except Exception as e:
                logger.error(f"Spell check failed: {e}")

        entry = {
            "word": original_word,
            "phonetic": None,
            "phonetics": [],
            "meanings": meanings,
            "metadata": {
                "detected_language": src_lang,
                "translation": translation_to_en,
                "analysis_word": analysis_word,
                "plurals": plurals,
                "is_correct": is_correct,
                "suggestions": suggestions[:5]
            }
        }

        return [entry]

engine = DictionaryEngine()
