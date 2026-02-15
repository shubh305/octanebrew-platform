from elasticsearch import AsyncElasticsearch
from .schema_registry import SchemaRegistry
from ..config import settings
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

    async def update_vectors(self, doc_id: str, chunks: list, summary: str = None, index_name: str = None):
        target_index = index_name or self.index_name
        doc = {
            "chunks": chunks,
            "status": "ready"
        }
        if summary:
            doc["summary"] = summary
            
        import json
        logger.info(f"Updating vectors for {doc_id} in {target_index}. Payload sample: {json.dumps(doc)[:1000]}...")
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
        return_chunks: bool = True
    ):
        target_index = index_name or self.index_name
        logger.info(f"Search: query='{query_text}', hybrid={use_hybrid}, limit={limit}, index={target_index}")
        
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
                "constant_score": {
                    "filter": { "match_phrase": { "title": query_text } },
                    "boost": 50.0,
                    "_name": "title_proximity_bonus"
                }
            },
            {
                "multi_match": {
                    "_name": "lexical_base",
                    "query": query_text,
                    "fields": ["title^3", "summary^2", "content^0.5"],
                    "type": "most_fields",
                    "operator": "and",
                    "boost": 2.0 
                }
            }
        ]

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
                    "_name": "chunk_semantic",
                    "field": "chunks.vector",
                    "query_vector": vector,
                    "k": limit * 5,
                    "num_candidates": 200,
                    "similarity": vector_threshold,
                    "boost": 25.0 
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
                "boost": 1.0 
            }
        }
        
        should_clauses.append(nested_clause)

        # 4. Search - Combined lexical query + kNN query
        search_body = {
            "size": limit,
            "min_score": min_score,
            "query": {
                "bool": {
                    "should": should_clauses,
                    "minimum_should_match": 1,
                    "filter": filter_clauses
                }
            }
        }

        resp = await self.client.search(
            index=target_index,
            body=search_body,
            source={
                "includes": ["title", "summary", "content", "metadata", "entity_id", "source_app", "chunks.text_chunk"]
            }
        )
        
        hits = resp['hits']['hits']
        
        for i, hit in enumerate(hits[:3]):
            signals = hit.get('matched_queries', [])
            score = hit['_score']
            entity_id = hit['_source'].get('entity_id')
            logger.info(f"Audit [Hit {i+1}] ({entity_id}): score={score:.2f}, signals={signals}")

        logger.info(f"Search returned {len(hits)} results (max score: {resp['hits'].get('max_score')})")
        return hits

    async def close(self):
        await self.client.close()

