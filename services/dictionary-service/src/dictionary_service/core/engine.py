import logging
import inflect
from textblob import Word, TextBlob
import language_tool_python
from googletrans import Translator
from langdetect import detect_langs, DetectorFactory
from typing import List, Dict, Any, Optional
from jamdict import Jamdict
import jamdict_data
import jaconv

# Set seed for deterministic detection
DetectorFactory.seed = 0

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

class DictionaryEngine:
    def __init__(self):
        # Initialize NLP models and tools
        self.p = inflect.engine()
        self.tool = language_tool_python.LanguageTool('en-US')
        self.translator = Translator()
        
        # Initialize Jamdict
        try:
            logger.info("Initializing Jamdict with bundled data...")
            self.jmd = Jamdict(db_file=jamdict_data.JAMDICT_DB_PATH)
        except Exception as e:
             logger.warning(f"Failed to initialize Jamdict with bundled data: {e}. Falling back to default.")
             self.jmd = Jamdict()


    def _contains_japanese(self, text: str) -> bool:
        """Check if text contains Japanese characters (Hiragana, Katakana, or Kanji)."""
        # Unicode ranges for Japanese characters
        # Hiragana: 3040-309F
        # Katakana: 30A0-30FF
        # Kanji: 4E00-9FFF
        for char in text:
            code = ord(char)
            if (0x3040 <= code <= 0x309F or
                0x30A0 <= code <= 0x30FF or
                0x4E00 <= code <= 0x9FFF):
                return True
        return False

    def _lookup_jmdict(self, query: str, original_word: str, reading: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
        try:
            jmd_result = self.jmd.lookup(query)
            if not jmd_result.entries:
                return None
                
            logger.info(f"Found {len(jmd_result.entries)} JMDict entries for '{query}'")
            entries = []
            
            for entry in jmd_result.entries:
                # Extract readings (kana)
                readings = [k.text for k in entry.kana_forms]
                
                # Extract meanings
                meanings_list = []
                for sense in entry.senses:
                    # Convert glosses to string definitions
                    glosses = [g.text for g in sense.gloss]
                    definition_text = "; ".join(glosses)
                    
                    pos = "unknown"
                    if sense.pos:
                        pos = ", ".join([str(p) for p in sense.pos])
                    
                    meanings_list.append({
                        "partOfSpeech": pos,
                        "definitions": [{
                            "definition": definition_text,
                            "synonyms": [],
                            "antonyms": [],
                            "example": None
                        }],
                        "synonyms": [],
                        "antonyms": []
                    })
                
                # Determine primary phonetic (reading)
                primary_phonetic = readings[0] if readings else None
                
                entries.append({
                    "word": original_word,
                    "phonetic": primary_phonetic,
                    "phonetics": [{"text": r} for r in readings],
                    "meanings": meanings_list,
                    "metadata": {
                        "detected_language": "ja",
                        "translation": None,
                        "analysis_word": original_word,
                        "plurals": [],
                        "is_correct": True,
                        "suggestions": []
                    }
                })
            
            # Filtering Logic
            if reading:
                target_readings = {reading}
                try:
                    # Convert potential Romaji to Hiragana/Katakana for matching
                    hira = jaconv.alphabet2kana(reading)
                    if hira != reading:
                        target_readings.add(hira)
                    kata = jaconv.hira2kata(hira)
                    if kata != reading:
                        target_readings.add(kata)
                except Exception as e:
                    logger.warning(f"jaconv conversion failed: {e}")
                
                logger.info(f"Target readings for filtering: {target_readings}")
                
                filtered_entries = [
                    e for e in entries 
                    if any(p["text"] in target_readings for p in e["phonetics"]) 
                       or (e["phonetic"] in target_readings)
                ]
                
                if filtered_entries:
                    logger.info(f"Filtered to {len(filtered_entries)} entries matching reading")
                    return filtered_entries
            
            return entries

        except Exception as e:
            logger.error(f"JMDict helper lookup failed: {e}")
            return None

    def analyze(self, word: str, reading: Optional[str] = None) -> List[Dict[str, Any]]:
        # Normalization
        word = word.strip()
        reading = reading.strip() if reading else None
        
        logger.info(f"Analyzing word: '{word}', reading: '{reading}'")
        original_word = word
        
        # Check if word contains Japanese characters
        contains_japanese = self._contains_japanese(word)
        logger.info(f"Contains Japanese characters: {contains_japanese}")
        
        # 1. Try JMDict Lookup (Japanese Dictionary)
        # ----------------------------------------------------------------
        if contains_japanese:
            jmd_entries = self._lookup_jmdict(word, word, reading)
            if jmd_entries:
                return jmd_entries
        else:
            # Try Romaji-to-Kana lookup for Latin characters
            try:
                # Basic conversion
                kana_query = jaconv.alphabet2kana(word.lower().replace(" ", ""))
                if kana_query != word:
                    logger.info(f"Trying Romaji JMDict lookup as: {kana_query}")
                    jmd_entries = self._lookup_jmdict(kana_query, word, reading)
                    if jmd_entries:
                        return jmd_entries
                    
                    # Special case for Romaji ending in 'o' which might be 'ou' (e.g., Gochisosama)
                    if kana_query.endswith("そ") or kana_query.endswith("う"):
                        kana_query_long = kana_query + "う"
                        logger.info(f"Trying Romaji JMDict lookup with long vowel: {kana_query_long}")
                        jmd_entries = self._lookup_jmdict(kana_query_long, word, reading)
                        if jmd_entries:
                            return jmd_entries
            except Exception as e:
                logger.warning(f"Romaji-to-Kana lookup failed: {e}")


        # 2. Standard Flow - Translation & Language Detection
        src_lang = "unknown"
        analysis_word = word
        translation_to_en = None
        
        try:
            if contains_japanese:
                # Strategy 1: Japanese Characters
                logger.info("Strategy: Japanese Characters -> EN")
                translated = self.translator.translate(word, src="ja", dest="en")
                src_lang = "ja"
            else:
                # Strategy 2: Auto-detect for Latin/Other characters
                logger.info("Strategy: Auto-detect -> EN")
                translated = self.translator.translate(word, dest="en")
                src_lang = translated.src
                
                # Check for suspicious detections common for Romaji (e.g., et, vi, tl)
                suspicious_langs = ["et", "vi", "tl", "sq", "la", "it"]
                is_identity = not translated.text or translated.text.strip().lower() == word.strip().lower()
                
                if is_identity and (src_lang in suspicious_langs or src_lang == "unknown"):
                    logger.info(f"Detection suspicious ({src_lang}), trying Japanese fallback")
                    fb_trans = self.translator.translate(word, src="ja", dest="en")
                    if fb_trans.text and fb_trans.text.strip().lower() != word.strip().lower():
                        translated = fb_trans
                        src_lang = "ja"

            if translated.text and translated.text.strip().lower() != word.strip().lower():
                translation_to_en = translated.text
                analysis_word = translated.text
                logger.info(f"Translation SUCCESS: {src_lang} -> {translation_to_en}")
            else:
                # Default to English for Latin text if no translation found
                if not contains_japanese and src_lang != "ja":
                    src_lang = "en"
                logger.info(f"No translation found, using original word (src_lang={src_lang})")
                
        except Exception as e:
            logger.error(f"Translation flow error: {e}")
            if not contains_japanese:
                src_lang = "en"
        
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
        if not meanings and translation_to_en and translation_to_en != word:
            logger.info("No WordNet meanings, providing synthetic translation meaning.")
            meanings.append({
                "partOfSpeech": "noun" if contains_japanese else "translation",
                "definitions": [{
                    "definition": translation_to_en,
                    "synonyms": [],
                    "antonyms": [],
                    "example": None
                }],
                "synonyms": [],
                "antonyms": []
            })
        
        # Handle case where we have no meanings and no translation
        if not meanings:
            logger.warning(f"No translation or meanings found for '{word}'")
            if contains_japanese and reading:
                meanings.append({
                    "partOfSpeech": "unknown",
                    "definitions": [{
                        "definition": f"Japanese word with reading '{reading}'. Translation unavailable in dictionary.",
                        "synonyms": [],
                        "antonyms": [],
                        "example": None
                    }],
                    "synonyms": [],
                    "antonyms": []
                })
            else:
                meanings.append({
                    "partOfSpeech": "unknown",
                    "definitions": [{
                        "definition": "Translation unavailable.",
                        "synonyms": [],
                        "antonyms": [],
                        "example": None
                    }],
                    "synonyms": [],
                    "antonyms": []
                })

        plurals = []
        # Only pluralize if it's likely a noun or we have a single word
        if " " not in analysis_word and translation_to_en and translation_to_en != word:
            plural_word = self.p.plural(translation_to_en)
            if plural_word and plural_word != translation_to_en:
                plurals.append(plural_word)

        # 5. Grammar and Spell Check (LanguageTool)
        is_correct = True
        suggestions = []
        if src_lang == "en" or (src_lang == "ja" and translation_to_en):
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
            "phonetic": reading if reading else None,
            "phonetics": [{"text": reading}] if reading else [],
            "meanings": meanings,
            "metadata": {
                "detected_language": src_lang if src_lang != "unknown" else "ja" if contains_japanese else "unknown",
                "translation": translation_to_en if (translation_to_en and translation_to_en != word) else None,
                "analysis_word": translation_to_en if (translation_to_en and translation_to_en != word) else original_word,
                "plurals": plurals,
                "is_correct": is_correct,
                "suggestions": suggestions[:5]
            }
        }

        return [entry]

engine = DictionaryEngine()
