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
        min_score: float = 0.5,
        vector_threshold: float = 0.7,
        return_chunks: bool = True
    ):
        target_index = index_name or self.index_name
        
        # 1. Base Filters
        filter_clauses = []
        if filters:
            filter_clauses = [
                {"term": {SchemaRegistry.map_filter_field(k): v}} 
                for k, v in filters.items()
            ]

        # 2. Construct kNN Query
        knn_query = {
            "field": "chunks.vector",
            "query_vector": vector,
            "k": limit * 2,
            "num_candidates": 100,
            "similarity": vector_threshold 
        }
        
        if filter_clauses:
            knn_query["filter"] = {"bool": {"must": filter_clauses}}
            
        if return_chunks:
            # Re-retrieve specific nested hits
            knn_query["inner_hits"] = {
                "name": "matched_chunks",
                "_source": ["text_chunk"],
                "size": 1
            }

        # 3. Construct Lexical Query
        lexical_query = {
            "bool": {
                "must": [
                    {
                        "multi_match": {
                            "query": query_text,
                            "fields": ["title^3", "content", "chunks.text_chunk"],
                            "type": "best_fields"
                        }
                    }
                ],
                "filter": filter_clauses
            }
        }

        # 4. Search - Combined lexical query + kNN query
        search_body = {
            "size": limit,
            "min_score": min_score,
            "query": {
                "bool": {
                    "should": [
                        {
                            "multi_match": {
                                "query": query_text,
                                "fields": ["title^3", "content", "chunks.text_chunk"],
                                "boost": 1.0
                            }
                        },
                        {
                            "nested": {
                                "path": "chunks",
                                "query": {
                                    "knn": {
                                        "field": "chunks.vector",
                                        "query_vector": vector,
                                        "k": limit,
                                        "num_candidates": 100,
                                        "similarity": vector_threshold
                                    }
                                },
                                "inner_hits": {
                                    "name": "matched_chunks",
                                    "size": 1
                                },
                                "boost": 50.0
                            }
                        }
                    ],
                    "filter": filter_clauses
                }
            }
        }

        resp = await self.client.search(
            index=target_index,
            body=search_body,
            source=["title", "content", "metadata", "entity_id", "source_app"]
        )
        return resp['hits']['hits']

    async def close(self):
        await self.client.close()
