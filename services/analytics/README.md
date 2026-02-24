# Analytics Service (`analytics`)

## Overview
The **Analytics Service** acts as the "Silent Ledger" of OctaneBrew. It is a dual-purpose service that functions as a high-volume Kafka background worker (inserting telemetry events into ClickHouse) and a FastAPI server that exposes analytics query endpoints for frontend applications.

**Role**: Event processing, Batch Ingestion, Data Warehousing, API Querying.
**Type**: Background Worker + FastAPI Service.

---

## 1. Architecture

```mermaid
graph LR
    App[External App] -->|Produce JSON| Kafka[Kafka: octane.events]
    Kafka -->|Consume Batch (getmany)| Worker[Analytics Worker]
    Worker -->|Bulk Insert| CH[(ClickHouse: ai_analytics_events)]
    Worker -->|Metrics| Prom[Prometheus:8000]
    API[Frontend Server] -->|POST /report| Worker[FastAPI API:8001]
    Worker -->|Execute Template| CH
```

---

## 2. Integration Guide (Data Contracts)

### A. Input: Kafka Topic
**Topic Name**: `octane.events`
**Serialization**: JSON
**Required Fields**: `app_id`, `event_name`, `timestamp`, `user_id`.

**Complete Payload Example:**
```json
{
  "app_id": "openstream",
  "event_name": "video_buffering",
  "user_id": "user_550e8400",
  "timestamp": "2026-02-02T12:00:00.000Z",
  "properties": {
    "stream_id": "st-998877",
    "buffer_duration_ms": 1500,
    "network_type": "5g",
    "client_version": "1.2.0"
  }
}
```
*Note: `properties` is a free-form dictionary. It is stored as a JSON string in ClickHouse to allow schema evolution without migration.*

### B. Output: ClickHouse Schema
**Database**: `default`
**Table**: `ai_analytics_events`

```sql
CREATE TABLE IF NOT EXISTS default.ai_analytics_events (
    timestamp DateTime CODEC(Delta, ZSTD),
    app_id String CODEC(ZSTD),
    event_name String CODEC(ZSTD),
    user_id String CODEC(ZSTD),
    properties String CODEC(ZSTD) -- Stored as JSON
) ENGINE = MergeTree()
ORDER BY (app_id, event_name, timestamp)
PARTITION BY toYYYYMM(timestamp)
TTL timestamp + INTERVAL 90 DAY;
```

### C. Output: Query API 
The service exposes a FastAPI backend on port `8001`:
- `POST /report`: Execute a predefined template (e.g., `overview_stats`, `search_analytics`, `top_content`). The service extracts metrics like `watch_time` directly from `video_heartbeat` payloads.
- `POST /query`: Execute raw ClickHouse SQL queries (internal use only, SELECT restricted).

---

## 3. Configuration

| Environment Variable | Default | Description |
|----------------------|---------|-------------|
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka:9092` | Kafka Broker List |
| `KAFKA_TOPIC` | `octane.events` | Topic to consume |
| `KAFKA_GROUP_ID` | `analytics-worker` | Consumer Group ID |
| `CLICKHOUSE_HOST` | `clickhouse` | ClickHouse Host (HTTP) |
| `CLICKHOUSE_PORT` | `8123` | ClickHouse Port |
| `BATCH_SIZE` | `1000` | Events per batch insert |
| `FLUSH_INTERVAL` | `5` | Max seconds before flush |

---

## 4. Observability

### Metrics
Exposed at `http://localhost:8000` (Prometheus)

While the API runs on `8001`, Prometheus metrics are exposed asynchronously on `8000`.

| Metric Name | Type | Description |
|-------------|------|-------------|
| `analytics_events_consumed_total` | Counter | Total Kafka messages read |
| `analytics_batch_flush_seconds` | Histogram | Time taken to flush to CH |
| `analytics_events_inserted_total` | Counter | Total events written to CH |
| `analytics_pipeline_errors_total` | Counter | Exceptions encountered |

### Tracing
OpenTelemetry is enabled for Kafka Consumer. Traces propagate from Producer -> Kafka -> Analytics Worker.

---

## 5. Testing
Run the independent test suite which mocks Kafka and ClickHouse:

```bash
uv run pytest tests/
```
