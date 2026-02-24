import clickhouse_connect
from clickhouse_connect.driver.client import Client
from ..config import settings
import json
from typing import List

class ClickHouseManager:
    def __init__(self):
        self.host = settings.CLICKHOUSE_HOST
        self.port = settings.CLICKHOUSE_PORT
        self.client = self._get_client()
        self.init_db()

    def _get_client(self) -> Client:
        # Connect to default first to ensure database exists
        client = clickhouse_connect.get_client(
            host=self.host,
            port=self.port,
            username=settings.CLICKHOUSE_USER, 
            password=settings.CLICKHOUSE_PASSWORD
        )
        client.command(f'CREATE DATABASE IF NOT EXISTS {settings.CLICKHOUSE_DB}')
        
        # Now get client for the specific database
        return clickhouse_connect.get_client(
            host=self.host,
            port=self.port,
            username=settings.CLICKHOUSE_USER, 
            password=settings.CLICKHOUSE_PASSWORD,
            database=settings.CLICKHOUSE_DB
        )

    def init_db(self):
        # Universal Schema
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS octane_events (
            timestamp DateTime64(3),
            app_id LowCardinality(String),
            event_name LowCardinality(String),
            user_id String,
            properties String,
            created_at DateTime DEFAULT now()
        ) ENGINE = MergeTree()
        PARTITION BY toYYYYMM(timestamp)
        ORDER BY (app_id, event_name, timestamp);
        """
        self.client.command(create_table_sql)

    def bulk_insert(self, events: List[dict]):
        if not events:
            return
            
        # Prepare data for insertion
        data = []
        for event in events:
            props_json = json.dumps(event.get('properties', {}))
            row = [
                event.get('timestamp'),
                event.get('app_id'),
                event.get('event_name'),
                event.get('user_id'),
                props_json
            ]
            data.append(row)
        
        self.client.insert(
            'octane_events',
            data,
            column_names=['timestamp', 'app_id', 'event_name', 'user_id', 'properties']
        )
