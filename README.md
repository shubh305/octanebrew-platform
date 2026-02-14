# OCTANEBREW PLATFORM

**Status:** `OPERATIONAL` // **Version:** `2026.1`

Centralized infrastructure for the OctaneBrew ecosystem. Hosts shared services (store, stream, bus, logs) on a single Cloud VM.

## ARCHITECTURE

| Component | Path | Description |
| :--- | :--- | :--- |
| **Core** | `./` | Docker Compose source of truth & Env vars. |
| **Gateway** | `nginx-gateway/` | SSL termination, routing, and static assets. |
| **Ingestion** | `services/ingestion/` | High-throughput AI content pipeline (Two-Pass). |
| **Intelligence** | `services/intelligence/` | Central AI gateway & model orchestrator. |
| **Linguistics** | `services/dictionary-service/` | NLP engine for word analysis & grammar. |
| **Storage** | `services/storage-service/` | gRPC/S3 shared asset management. |
| **Video Ops** | `services/ffmpeg-worker/` | Automated FLV -> MP4 transcoding & thumbnails. |
| **Web** | `html/` | Landing page entrypoint. |

## SERVICES

### [Ingestion Service](./services/ingestion/README.md)
The gateway for all platform content. Implements a **Two-Pass Architecture**:
1.  **Pass 1**: Instant keyword indexing in Elasticsearch via Kafka.
2.  **Pass 2**: Asynchronous AI enrichment (summarization + vector embedding) via the Oplog pattern.

### [Intelligence Service](./services/intelligence/README.md)
A high-performance abstraction layer for LLMs (Gemini, OpenAI). Provides standardized vector embeddings and chat completions with Redis-backed rate limiting.

### [Dictionary Service](./services/dictionary-service/README.md)
Linguistic utility for the OpenStream ecosystem. Features POS tagging, multi-layered language detection (Romaji-aware), and real-time grammar checking.

### [Storage Service](./services/storage-service/)
A NestJS-based gRPC microservice that provides a unified interface for file operations across S3 and local volumes.

### [FFmpeg Worker](./services/ffmpeg-worker/README.md)
A stateless Kafka consumer that handles VOD processing. Automatically converts live recordings to web-compatible MP4s and extracts thumbnails.

## DEPLOYMENT

```bash
docker-compose up -d
```

## NETWORK

All services communicate via `octane-net` (Bridge).
External projects (e.g., `openstream-backend`) must attach to this network.

## ENDPOINTS

- **Web:** `https://octanebrew.dev`
- **Stream:** `rtmp://stream.octanebrew.dev/live`
- **Stats:** `https://stats.octanebrew.dev`
- **Ops:** `https://grafana.octanebrew.dev` 
- **Logs:** `https://dozzle.octanebrew.dev`
- **Elasticsearch:** `https://kibana.octanebrew.dev`