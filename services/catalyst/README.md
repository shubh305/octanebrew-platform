# Catalyst — Product Launch Intelligence Spoke

**Status:** `ACTIVE` // **Version:** `1.1` // **Platform:** OctaneBrew v2026.02

Catalyst is the Product Launch Intelligence Spoke on the OctaneBrew Platform. It maintains high-fidelity catalogs of **Indian cars & bikes**, **global books**, and **mobile smartphones**. It continuously monitors Reddit for launch signals and surfaces this data to **Conduit's** editor via slash commands (`/cars`, `/bikes`, `/books`, `/mobiles`).

---

## Architecture

Catalyst is designed as a hybrid system with a containerized API layer and decoupled local processing workers for data ingestion.

```mermaid
graph TD
    subgraph Local Workers
        CL[Catalog Loader] -->|Upsert| DB[(PostgreSQL)]
        CL -->|Index| ES[Elasticsearch]
        RW[Reddit Watcher] -->|Oplog| DB
        RW -->|Stream| K[Kafka]
        MW[Matcher Worker] -->|Fuzzy Link| ES
        MW -->|Save Links| DB
    end

    subgraph Containerized API (Catalyst)
        API[FastAPI Gateway] -->|Query| DB
        API -->|Search| ES
        API -.->|Verify| IS[Intelligence Service]
    end

    Conduit[Conduit Editor] -->|Slash Commands| API
```

---

## Directory Structure

```
catalyst/
├── src/catalyst/          # FastAPI API service (Dockerized)
│   ├── main.py
│   ├── models.py          # Pydantic models for Typed Results
│   ├── routers/           # cars, bikes, books, mobiles, products
│   └── services/          # search (ES+rerank), db
├── workers/               # Decoupled processing layer (Local execution)
│   ├── catalog_loader/    # Dataset ingestion & ES synchronization
│   ├── reddit_watcher/    # Active Reddit stream monitoring
│   └── matcher/           # Kafka-driven signal matching
├── migrations/            # Versioned PostgreSQL schema migrations
├── config/                # YAML configurations for keyword triggers
├── Dockerfile             # Production API service image
├── pyproject.toml         # Dependency management
└── uv.lock                # Deterministic dependency lock
```

---

## The Search Pipeline

Catalyst uses a sophisticated two-stage search and ranking pipeline to ensure high precision for product mentions.

### 1. Elasticsearch Fuzzy Retrieval (Stage 1)
Using **Elasticsearch**, we perform a `multi_match` boolean query across product names, brands, and technical summaries.
- **Fuzziness**: `AUTO` (handles typos and slight model name variations).
- **Phrase Matching**: High boost for exact phrase prefixes to favor specific models (e.g., "iPhone 15 Pro").
- **Filtering**: Strict category-based isolation.

### 2. Intelligence Reranking (Stage 2)
Top hits from Elasticsearch are passed to the **Intelligence Service** for semantic reranking.
- Uses a **Cross-Encoder** model to evaluate the relevance of the search term against the candidate product names.
- **Circuit Breaker**: If the Intelligence Service is slow or down, the pipeline falls back to raw ES scores to ensure zero API downtime.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/cars/search?q=<q>` | Search Indian car catalog (Make, Model, Year) |
| `GET` | `/bikes/search?q=<q>` | Search Indian bike catalog (Segment, Fuel Type) |
| `GET` | `/books/search?q=<q>` | Search global book corpus (Author, Title) |
| `GET` | `/mobiles/search?q=<q>` | Search smartphones (OS, 5G, RAM filters) |
| `GET` | `/products/{id}` | **Enriched specs** (merged JSONB) |
| `GET` | `/health` | Liveness & Readiness probe |

### Product Enrichment
The `/products/{id}` endpoint provides a unified view of any product. For Automobiles and Mobiles, it merges over **50+ technical attributes** (engine specs, camera configs, battery tech) from the `specs` JSONB storage into the response `specs` dictionary.

---

## Observability

- **Metrics**: Prometheus instrumentation at `:8002/metrics`.
- **Tracing**: OpenTelemetry integration for tracing searches through the Intel reranker.
- **Logs**: JSON-formatted structured logging for production auditing.
- **Messaging**: Kafka topics: `octane.catalyst.reddit_posts`.
