from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_experimental.text_splitter import SemanticChunker
import httpx
import logging
import asyncio
import tiktoken
import re
from ..config import settings

logger = logging.getLogger(__name__)

# Initialize Tokenizer
try:
    encoding = tiktoken.get_encoding("cl100k_base")
except Exception:
    encoding = tiktoken.get_encoding("gpt2")

def get_token_count(text: str) -> int:
    return len(encoding.encode(text))

class IntelligenceEmbeddings:
    """Wrapper to make Intelligence Service compatible with LangChain Embeddings (Synchronous)"""
    def __init__(self):
        self.url = f"{settings.INTELLIGENCE_SVC_URL}/v1/embeddings"
        self.api_key = settings.SERVICE_API_KEY
        self.model = settings.EMBEDDING_MODEL

    def embed_documents(self, texts):
        try:
            logger.info(f"Embedding {len(texts)} documents for semantic chunking.")
            batch_size = 20
            all_embeddings = []
            
            with httpx.Client(timeout=60.0) as client:
                for i in range(0, len(texts), batch_size):
                    batch = texts[i : i + batch_size]
                    logger.info(f"Processing batch {i//batch_size + 1}/{(len(texts)-1)//batch_size + 1} ({len(batch)} items)")
                    resp = client.post(
                        self.url,
                        json={"input": batch, "model": self.model},
                        headers={"X-API-KEY": self.api_key}
                    )
                    resp.raise_for_status()
                    all_embeddings.extend(resp.json()["data"])
                    
            return all_embeddings
        except Exception as e:
            logger.error(f"Failed to embed documents for semantic chunking: {e}")
            raise

    def embed_query(self, text):
        res = self.embed_documents([text])
        return res[0]

class TextChunker:
    async def split_text(self, text: str, strategy: str = "recursive", chunk_size: int = 500, chunk_overlap: int = 50, intelligence_client=None):
        logger.info(f"Chunking Request: strategy={strategy}, requested_size={chunk_size} tokens, text_len={len(text)} chars")
        
        # Guard against overlap being >= chunk_size
        actual_overlap = min(chunk_overlap, chunk_size - 1) if chunk_size > 1 else 0

        # High-Fidelity Multi-Stage Separators
        smart_separators = ["\n\n", "\n", r"(?<=[.!?])\s+", r"(?<=[,;:])\s+", " ", ""]

        if strategy == "semantic":
            try:
                logger.info("Performing high-fidelity semantic grouping...")
                embeddings = IntelligenceEmbeddings()
                
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    # Pre-split into sentences/paragraphs
                    atom_splitter = RecursiveCharacterTextSplitter(
                        chunk_size=chunk_size * 5, 
                        chunk_overlap=0,
                        separators=smart_separators,
                        is_separator_regex=True,
                        length_function=get_token_count
                    )
                    sentences = atom_splitter.split_text(text)
                    
                    splitter = SemanticChunker(
                        embeddings, 
                        breakpoint_threshold_type="percentile"
                    )
                    
                    loop = asyncio.get_event_loop()
                    docs = await loop.run_in_executor(
                        executor, 
                        splitter.create_documents, 
                        sentences
                    )
                    chunks = [d.page_content for d in docs]
                    
                    final_chunks = []
                    # If a semantic cluster is too big, use smart recursive splitting 
                    refiner = RecursiveCharacterTextSplitter(
                        chunk_size=chunk_size,
                        chunk_overlap=actual_overlap,
                        separators=smart_separators,
                        is_separator_regex=True,
                        length_function=get_token_count
                    )

                    for c in chunks:
                        if get_token_count(c) > chunk_size * 1.5:
                            final_chunks.extend(refiner.split_text(c))
                        else:
                            final_chunks.append(c)
                            
                    logger.info(f"Semantic chunking completed: {len(final_chunks)} chunks.")
                    self._log_previews(final_chunks)
                    return final_chunks
            except Exception as e:
                logger.error(f"Semantic chunking failed: {e}. Falling back to recursive.")
                strategy = "recursive"

        # Recursive Strategy: Smart splitting with Tiktoken length awareness
        logger.info(f"Using Smart Recursive Splitting")
        base_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=actual_overlap,
            length_function=get_token_count,
            separators=smart_separators,
            is_separator_regex=True
        )
        chunks = base_splitter.split_text(text)
        
        logger.info(f"Done. Generated {len(chunks)} chunks.")
        self._log_previews(chunks)
        return chunks

    def _log_previews(self, chunks):
        for i, chunk in enumerate(chunks[:5]):
            tokens = get_token_count(chunk)
            preview = (chunk[:80].replace("\n", " ") + "...") if len(chunk) > 80 else chunk.replace("\n", " ")
            logger.info(f"  Chunk {i} ({tokens} tokens): [{preview}]")
