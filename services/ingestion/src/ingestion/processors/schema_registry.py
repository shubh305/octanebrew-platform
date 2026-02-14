from typing import Dict, Any

class SchemaRegistry:
    @staticmethod
    def get_base_properties() -> Dict[str, Any]:
        return {
            "source_app": { "type": "keyword" },
            "entity_id": { "type": "keyword" },
            "title": { "type": "text", "analyzer": "standard" },
            "content": { "type": "text", "analyzer": "standard" },
            "summary": { "type": "text", "analyzer": "standard" },
            "status": { "type": "keyword" },
            "metadata": { "type": "flattened" }
        }

    @staticmethod
    def get_entity_mappings() -> Dict[str, Any]:
        return {
            "video": {
                "properties": {
                    "duration": { "type": "float" },
                    "thumbnail_url": { "type": "keyword" }
                }
            },
            "blog": {
                "properties": {
                    "author": { "type": "keyword" },
                    "tags": { "type": "keyword" }
                }
            }
        }

    @staticmethod
    def get_vector_mapping(dims: int) -> Dict[str, Any]:
        return {
            "type": "nested",
            "properties": {
                "text_chunk": { "type": "text" },
                "vector": {
                    "type": "dense_vector",
                    "dims": dims,
                    "index": True,
                    "similarity": "cosine"
                }
            }
        }

    @staticmethod
    def get_full_mapping(dims: int) -> Dict[str, Any]:
        properties = SchemaRegistry.get_base_properties()
        properties.update(SchemaRegistry.get_entity_mappings())
        properties["chunks"] = SchemaRegistry.get_vector_mapping(dims)
        
        return {
            "dynamic": "strict",
            "properties": properties
        }

    @staticmethod
    def map_filter_field(field_name: str) -> str:
        """Maps a generic field name to its typed path in the schema."""
        video_fields = ['duration', 'thumbnail_url']
        blog_fields = ['author', 'tags']
        base_fields = ['source_app', 'entity_id', 'status']
        
        if field_name in video_fields:
            return f"video.{field_name}"
        if field_name in blog_fields:
            return f"blog.{field_name}"
        if field_name in base_fields:
            return field_name
            
        return f"metadata.{field_name}"
