# OCTANEBREW PLATFORM

**Status:** `OPERATIONAL` // **Version:** `2026.1`

Centralized infrastructure for the OctaneBrew ecosystem. Hosts shared services (store, stream, bus, logs) on a single Cloud VM.

## ARCHITECTURE

| Component | Path | Description |
| :--- | :--- | :--- |
| **Core** | `./` | Docker Compose source of truth & Env vars. |
| **Gateway** | `nginx-gateway/` | SSL termination, routing, and static assets. |
| **Stream** | `services/` | RTMP Ingest & Stats configuration. |
| **Web** | `html/` | Landing page entrypoint. |

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
- **Elasticsearch:** `https://kibana.octanebrew.dev`