# FFmpeg Worker Service

A dedicated, stateless microservice for video transcoding and thumbnail generation (VOD processing) in the OctaneBrew platform.

## Overview

This worker listens for Kafka events (`video.transcode`) triggered when a live stream ends. It processes the recorded FLV file using `ffmpeg`, converts it to MP4 (faststart), generates a thumbnail, and emits a completion event (`video.processed`) back to the backend.

## Architecture

1.  **Input**: Consumes `video.transcode` topic.
    *   Payload: `{ streamKey: string, filename: string }`
2.  **Process**:
    *   Locates file in `OPENSTREAM_VOL_PATH/recordings`.
    *   Transcodes FLV -> MP4.
    *   Extracts Thumbnail (JPG).
3.  **Output**: Emits `video.processed` topic.
    *   Payload: `{ streamKey: string, filename: string, thumbnail: string, duration: number }`

## Prerequisites

- **Node.js** (v18+)
- **FFmpeg** (v4+) installed on the host/container.
- **Kafka** (Running broker).
- **Shared Volume**: Must have access to the same storage path as the backend/ingest service.

## Environment Variables

| Variable | Description | Default |
| :--- | :--- | :--- |
| `KAFKA_BROKERS` | Kafka Connection String | `broker.octanebrew.dev:9092` |
| `OPENSTREAM_VOL_PATH` | Base path for media files | `/minio_data` |
| `FFMPEG_PATH` | Path to FFmpeg binary | `ffmpeg` |

## Installation

```bash
$ npm install
```

## Running the app

```bash
# development
$ npm run start

# watch mode
$ npm run start:dev

# production mode
$ npm run start:prod
```