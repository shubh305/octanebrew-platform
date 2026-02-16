from elasticsearch import AsyncElasticsearch
from .schema_registry import SchemaRegistry
from ..config import settings
from typing import List
import logging

logger = logging.getLogger(__name__)

class ElasticManager:
    def __init__(self):
        self.host = settings.ES_HOST
        self.dims = settings.EMBEDDING_DIMS
        self.index_name = settings.ES_INDEX_NAME
        es_kwargs = {"hosts": [self.host]}
        if settings.ES_USER and settings.ES_PASSWORD:
            es_kwargs["basic_auth"] = (settings.ES_USER, settings.ES_PASSWORD)
        if self.host.startswith("https://"):
            import ssl
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            es_kwargs["ssl_context"] = ssl_context
        self.client = AsyncElasticsearch(**es_kwargs)

    async def init_index(self):
        if not await self.client.indices.exists(index=self.index_name):
            mapping = {
                "mappings": SchemaRegistry.get_full_mapping(self.dims)
            }
            await self.client.indices.create(index=self.index_name, body=mapping)
            logger.info(f"Initialized Elasticsearch index: {self.index_name}")

    async def upsert_text(self, doc_id: str, body: dict, index_name: str = None):
        target_index = index_name or self.index_name
        
        # Ensure index exists with correct mapping
        if not await self.client.indices.exists(index=target_index):
            mapping = {
                "mappings": SchemaRegistry.get_full_mapping(self.dims)
            }
            await self.client.indices.create(index=target_index, body=mapping)
            logger.info(f"Initialized new index: {target_index}")

        await self.client.index(index=target_index, id=doc_id, document=body)

    async def update_vectors(self, doc_id: str, chunks: list, summary_data: dict = None, index_name: str = None):
        """
        Update document with vector embeddings and structured summary.
        
        Args:
            doc_id: Document ID
            chunks: List of {text_chunk, vector, entities} dicts
            summary_data: Structured summary from AI (dict with overview, key_concepts, entities, language)
            index_name: Target index
        """
        target_index = index_name or self.index_name
        doc = {
            "chunks": chunks,
            "status": "ready"
        }
        
        # Handle structured LLM output
        if summary_data and isinstance(summary_data, dict):
            if 'overview' in summary_data:
                doc["summary"] = summary_data['overview']
            elif 'summary' in summary_data:
                doc["summary"] = summary_data['summary']
                
            if 'key_concepts' in summary_data:
                doc["key_concepts"] = summary_data['key_concepts']
                
            if 'entities' in summary_data:
                doc["entities"] = summary_data['entities']
                
            if 'language' in summary_data:
                doc["language"] = summary_data['language']
        elif summary_data:
            doc["summary"] = str(summary_data)
            
        import json
        logger.info(f"Updating vectors for {doc_id} in {target_index}. Fields: {list(doc.keys())}")
        await self.client.update(index=target_index, id=doc_id, doc=doc)
    
    async def search(self, 
        query_text: str,
        vector: list[float], 
        limit: int = 10, 
        filters: dict = None, 
        index_name: str = None,
        use_hybrid: bool = True,
        min_score: float = 25.0,
        vector_threshold: float = 0.65,
        return_chunks: bool = True,
        sort_by: str = "relevancy",
        entities: List[str] = None,
        query_language: str = "en",
        debug: bool = False
    ):
        target_index = index_name or self.index_name
        logger.info(f"Search: query='{query_text}', lang='{query_language}', hybrid={use_hybrid}, entities={entities}")
        
        # 1. Base Filters
        filter_clauses = [{"term": {"status": "ready"}}]
        if filters:
            filter_clauses.extend([
                {"term": {SchemaRegistry.map_filter_field(k): v}} 
                for k, v in filters.items()
            ])

        # 2. Construct Lexical Query
        should_clauses = [
            {
                "match_phrase": {
                    "title": {
                        "query": query_text,
                        "boost": 50.0,
                        "_name": "title_proximity_bonus"
                    }
                }
            },
            {
                "multi_match": {
                    "query": query_text,
                    "fields": ["title^2", "summary^1.5", "content"],
                    "type": "most_fields",
                    "operator": "and",
                    "boost": 2.0,
                    "_name": "keyword_density"
                }
            }
        ]
        
        # 2.1 Entity Boosting
        if entities:
            should_clauses.append({
                "terms": {
                    "entities": entities,
                    "boost": 20.0,
                    "_name": "entity_match_bonus"
                }
            })
            should_clauses.append({
                "nested": {
                    "path": "chunks",
                    "inner_hits": {},
                    "query": {
                        "terms": {
                            "chunks.entities": entities,
                            "boost": 10.0
                        }
                    },
                    "_name": "chunk_entity_match_bonus"
                }
            })

        # 2.2 Language Match Bonus
        should_clauses.append({
            "term": {
                "language": {
                    "value": query_language,
                    "boost": 10.0,
                    "_name": "language_match_bonus"
                }
            }
        })
        # 3. Construct KNN Query
        chunk_should = []
        
        chunk_should.append({
            "constant_score": {
                "filter": { "match_phrase": { "chunks.text_chunk": query_text } },
                "boost": 15.0,
                "_name": "chunk_proximity_bonus"
            }
        })

        if use_hybrid and vector:
            chunk_should.append({
                "knn": {
                    "field": "chunks.vector",
                    "query_vector": vector,
                    "num_candidates": 100,
                    "similarity": vector_threshold,
                    "boost": 25.0,
                    "_name": "chunk_semantic"
                }
            })

        nested_clause = {
            "nested": {
                "path": "chunks",
                "score_mode": "max",
                "query": {
                    "bool": {
                        "should": chunk_should,
                        "minimum_should_match": 1
                    }
                },
                "inner_hits": {
                    "name": "matched_chunks",
                    "size": 1,
                    "_source": ["chunks.text_chunk"]
                } if return_chunks else {},
                "boost": 1.0,
                "_name": "nested_chunk_match" 
            }
        }
        
        should_clauses.append(nested_clause)

        # 4. Search - Combined lexical query + kNN query
        search_body = {
            "size": limit,
            "min_score": min_score if sort_by == "relevancy" else 0,
            "query": {
                "bool": {
                    "should": should_clauses,
                    "minimum_should_match": 1,
                    "filter": filter_clauses
                }
            }
        }
        
        # Apply recency bias based on sort_by mode
        if sort_by == "recency":
            search_body["sort"] = [{"published_at": {"order": "desc", "missing": "_last"}}]
        elif sort_by == "balanced":
            search_body["query"] = {
                "function_score": {
                    "query": search_body["query"],
                    "functions": [
                        {
                            "exp": {
                                "published_at": {
                                    "origin": "now",
                                    "scale": "7d",
                                    "offset": "0d",
                                    "decay": 0.5
                                }
                            },
                            "weight": 15
                        }
                    ],
                    "score_mode": "sum",
                    "boost_mode": "sum"
                }
            }
        search_body["_source"] = {
            "includes": ["title", "summary", "metadata", "entity_id", "source_app", "chunks.text_chunk", "published_at", "entities", "key_concepts", "language"],
            "excludes": ["content", "chunks.vector"]
        }

        resp = await self.client.search(
            index=target_index,
            body=search_body
        )
        
        hits = resp['hits']['hits']
        
        for i, hit in enumerate(hits):
            if debug:
                hit['_debug_signals'] = hit.get('matched_queries', [])
                
            if i < 3:
                score = hit['_score']
                entity_id = hit['_source'].get('entity_id')
                logger.info(f"Audit [Hit {i+1}] ({entity_id}): score={score:.2f}, signals={hit.get('matched_queries', [])}")

        logger.info(f"Search returned {len(hits)} results (max score: {resp['hits'].get('max_score')})")
        return hits

    async def close(self):
        await self.client.close()

