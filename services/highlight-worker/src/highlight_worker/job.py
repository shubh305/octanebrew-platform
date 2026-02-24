"""Job orchestrator — top-level highlight generation pipeline."""

import asyncio
import logging
import os
import time
import tempfile
from pathlib import Path

from .config import load_yaml_config, settings
from .governance import GovernanceMonitor
from .scoring import compute_scores, qualify_seconds
from .consolidation import consolidate_clips
from .extraction import extract_all_clips
from .enrichment import enrich_clips
from .storage import (
    upload_all_clips,
    upload_highlights_json,
    get_minio_client,
    cleanup_temp_files,
)
from .metrics import (
    JOBS_PROCESSED, JOB_LATENCY, CLIPS_GENERATED, SIGNAL_LATENCY,
    SIGNAL_FAILURES, VTT_USED, INTELLIGENCE_CALLS,
)

# Signal modules
from .signals.audio_spike import AudioSpikeSignal
from .signals.scene_change import SceneChangeSignal
from .signals.chat_spike import ChatSpikeSignal
from .signals.vtt_semantic import VttSemanticSignal
from .signals.ocr_keyword import OCRKeywordSignal

logger = logging.getLogger(__name__)

# Registry of available signals
SIGNAL_REGISTRY = {
    "audio_spike": AudioSpikeSignal,
    "scene_change": SceneChangeSignal,
    "chat_spike": ChatSpikeSignal,
    "vtt_semantic": VttSemanticSignal,
    "ocr_keyword": OCRKeywordSignal,
}


async def run_highlight_job(payload: dict) -> dict:
    """
    Execute a full highlight generation job.

    Args:
        payload: Kafka message body with videoId, proxy480pPath, sourceVideoPath,
                 chatPath, configPath, ownerId

    Returns:
        Result dict for the Kafka completion event
    """
    video_id = payload["videoId"]
    start_time = time.time()
    warnings: list[str] = []

    logger.info(f"Starting highlight job for video {video_id}")

    # 1. Load configuration
    config = load_yaml_config(payload.get("configPath"))
    scoring_cfg = config.get("scoring", {})
    signals_cfg = config.get("signals", {})
    governance_cfg = config.get("governance", {})

    # 2. Setup governance
    governor = GovernanceMonitor(
        max_cpu_percent=governance_cfg.get("max_cpu_percent", settings.MAX_CPU_PERCENT),
        max_memory_mb=governance_cfg.get("max_memory_mb", settings.MAX_MEMORY_MB),
        poll_interval=governance_cfg.get("poll_interval", 10),
        nice_priority=governance_cfg.get("nice_priority", 15),
    )
    governor.apply_nice()

    # 3. Resolve video paths
    proxy_storage = payload.get("proxy480pPath", "")
    source_storage = payload.get("sourceVideoPath", "")

    proxy_path = _resolve_path(proxy_storage)
    source_path = _resolve_path(source_storage)

    await governor.wait_until_safe()
    download_dir = tempfile.mkdtemp(prefix=f"highlight_{video_id}_dl_")

    def _is_url(p: str) -> bool:
        return p.startswith("http://") or p.startswith("https://")

    if not proxy_path or (not _is_url(proxy_path) and not os.path.exists(proxy_path)):
        if not proxy_storage:
            raise FileNotFoundError("No proxy video provided in payload")
        if _is_url(proxy_storage):
            proxy_path = proxy_storage
        else:
            proxy_path = os.path.join(download_dir, "proxy.mp4")
            _download_from_storage(proxy_storage, proxy_path)

    if not source_path or (not _is_url(source_path) and not os.path.exists(source_path)):
        if source_storage:
            if _is_url(source_storage):
                source_path = source_storage
            else:
                source_path = os.path.join(download_dir, "source.mp4")
                try:
                    _download_from_storage(source_storage, source_path)
                except Exception as e:
                    logger.warning(f"Failed to download source {source_storage}: {e}")
                    source_path = proxy_path
        else:
            source_path = proxy_path

    # 4. Get video duration
    duration = await _get_duration(proxy_path)
    if duration <= 0:
        raise ValueError(f"Invalid video duration: {duration}")

    # 5. Run signal modules
    signal_outputs: dict[str, dict[int, float]] = {}
    signal_weights: dict[str, float] = {}

    # Check for VTT file
    vtt_path = _find_vtt(video_id)
    VTT_USED.labels(used=str(vtt_path is not None)).inc()

    expensive_signals = ["ocr_keyword"]
    for sig_name, sig_cfg in signals_cfg.items():
        if not sig_cfg.get("enabled", False) or sig_name not in SIGNAL_REGISTRY:
            continue
        if sig_name in expensive_signals:
            continue

        signal_weights[sig_name] = sig_cfg.get("weight", 0.0)
        try:
            await governor.wait_until_safe()
            signal = SIGNAL_REGISTRY[sig_name]()
            sig_start = time.time()
            result = await asyncio.wait_for(
                signal.detect(proxy_path, sig_cfg, chat_path=payload.get("chatPath"), vtt_path=vtt_path, duration=duration),
                timeout=governance_cfg.get("job_timeout", settings.JOB_TIMEOUT_SECONDS)
            )
            signal_outputs[sig_name] = result
            logger.info(f"Pass 1: Signal '{sig_name}' complete ({time.time() - sig_start:.1f}s)")
        except Exception as e:
            logger.error(f"Pass 1: Signal '{sig_name}' failed: {e}")

    # --- Identify Candidate Windows for OCR ---
    candidate_seconds = set()
    initial_scores = await compute_scores(signal_outputs, signal_weights, int(duration))
    # Collect all seconds > 0.1 score + buffer ±5s
    for sec, data in initial_scores.items():
        if data["total"] >= 0.1:
            for buf_sec in range(max(0, sec - 5), min(int(duration), sec + 6)):
                candidate_seconds.add(buf_sec)
    
    # --- Pass 2: Expensive Signals (OCR) ---
    if "ocr_keyword" in signals_cfg and signals_cfg["ocr_keyword"].get("enabled"):
        sig_name = "ocr_keyword"
        sig_cfg = signals_cfg[sig_name]
        signal_weights[sig_name] = sig_cfg.get("weight", 0.0)
        try:
            await governor.wait_until_safe()
            signal = SIGNAL_REGISTRY[sig_name]()
            sig_start = time.time()
            result = await asyncio.wait_for(
                signal.detect(proxy_path, sig_cfg, duration=duration, target_seconds=list(candidate_seconds)),
                timeout=governance_cfg.get("job_timeout", settings.JOB_TIMEOUT_SECONDS)
            )
            signal_outputs[sig_name] = result
            logger.info(f"Pass 2: OCR complete on {len(candidate_seconds)} candidate seconds ({time.time() - sig_start:.1f}s)")
        except Exception as e:
            logger.error(f"Pass 2: OCR failed: {e}")

    # 6. Score and qualify
    aggregate = await compute_scores(signal_outputs, signal_weights, int(duration))
    qualified = await qualify_seconds(
        aggregate, scoring_cfg.get("qualification_threshold", 0.35)
    )

    if not qualified:
        logger.info(f"No qualifying seconds for {video_id} — 0 clips")
        JOBS_PROCESSED.labels(status="empty").inc()
        return {
            "videoId": video_id,
            "clipCount": 0,
            "highlightsJsonPath": "",
            "durationMs": int((time.time() - start_time) * 1000),
            "vttUsed": vtt_path is not None,
            "warnings": warnings,
        }

    # 7. Consolidate into clip windows
    clips = consolidate_clips(
        qualified,
        min_duration=scoring_cfg.get("min_clip_duration", 8),
        max_duration=scoring_cfg.get("max_clip_duration", 60),
        context_buffer=scoring_cfg.get("context_buffer", 3),
        min_gap=scoring_cfg.get("min_gap", 5),
        max_clips=scoring_cfg.get("max_clips", 5),
    )

    if not clips:
        logger.info(f"No clips after consolidation for {video_id}")
        return {
            "videoId": video_id,
            "clipCount": 0,
            "highlightsJsonPath": "",
            "durationMs": int((time.time() - start_time) * 1000),
            "vttUsed": vtt_path is not None,
            "warnings": warnings,
        }

    # 8. Extract clips (stream copy)
    await governor.wait_until_safe()
    temp_dir = tempfile.mkdtemp(prefix=f"highlight_{video_id}_")

    try:
        extracted = await extract_all_clips(source_path, clips, temp_dir, config)

        if not extracted:
            raise RuntimeError("No clips could be extracted")

        # 9. Enrich with Intelligence Service
        try:
            vtt_content = None
            vtt_content = None
            if vtt_path and os.path.exists(vtt_path):
                vtt_content = Path(vtt_path).read_text(encoding="utf-8")
            
            video_title = payload.get("videoTitle", "Untitled Video")
            video_desc = payload.get("videoDescription", "")
            video_category = payload.get("videoCategory", "Unknown")
            
            await enrich_clips(extracted, video_title, video_desc, vtt_content, video_category)
            INTELLIGENCE_CALLS.labels(type="title_gen").inc(len(extracted))
        except Exception as e:
            warnings.append(f"Enrichment partial failure: {e}")

        # 10. Upload to MinIO
        uploaded = upload_all_clips(extracted, video_id)

        # Build final highlights data
        highlights_data = []
        for clip in uploaded:
            highlights_data.append({
                "index": clip.get("index", 0),
                "start": clip["start"],
                "end": clip["end"],
                "score": clip["score"],
                "title": clip.get("title", f"Highlight #{clip.get('index', 0) + 1}"),
                "signals": {
                    sig: signal_outputs[sig].get(clip.get("peak_second", clip["start"]), 0)
                    for sig in signal_outputs
                },
                "clipUrl": clip.get("clipUrl", ""),
                "thumbnailUrl": clip.get("thumbnailUrl", ""),
            })

        # 11. Write highlights.json
        json_path = upload_highlights_json(video_id, highlights_data)

        CLIPS_GENERATED.inc(len(extracted))
        JOBS_PROCESSED.labels(status="success").inc()
        JOB_LATENCY.observe(time.time() - start_time)

        result = {
            "videoId": video_id,
            "clipCount": len(extracted),
            "highlightsJsonPath": json_path,
            "durationMs": int((time.time() - start_time) * 1000),
            "vttUsed": vtt_path is not None,
            "warnings": warnings,
        }

        logger.info(
            f"Highlight job COMPLETE for {video_id}: "
            f"{len(extracted)} clips in {time.time() - start_time:.1f}s"
        )
        return result

    finally:
        cleanup_temp_files(temp_dir)
        try:
            if 'download_dir' in locals() and os.path.exists(download_dir):
                import shutil
                shutil.rmtree(download_dir, ignore_errors=True)
                logger.info(f"Cleaned up download dir: {download_dir}")
        except Exception as e:
            logger.warning(f"Failed to cleanup download dir: {e}")


def _resolve_path(path: str) -> str:
    """Resolve a storage path to the volume mount."""
    if not path:
        return ""
    if path.startswith("http://") or path.startswith("https://"):
        return path
    vol = settings.OPENSTREAM_VOL_PATH.rstrip("/")
    if path.startswith("/"):
        return path
    return f"{vol}/{path}"

def _download_from_storage(storage_path: str, local_path: str) -> None:
    import shutil
    bucket = settings.MINIO_BUCKET
    if storage_path.startswith(f"{bucket}/"):
        storage_path = storage_path[len(bucket) + 1 :]
        
    vol = settings.OPENSTREAM_VOL_PATH.rstrip("/")
    direct_path = f"{vol}/{bucket}/{storage_path}"
    
    if os.path.exists(direct_path) and os.path.isfile(direct_path):
        logger.info(f"Downloading via direct mount: {direct_path}")
        shutil.copy2(direct_path, local_path)
        return
    
    client = get_minio_client()
    logger.info(f"Downloading s3://{bucket}/{storage_path} to {local_path} via API...")
    client.fget_object(bucket, storage_path, local_path)
    logger.info("Download complete.")



async def _get_duration(video_path: str) -> float:
    """Get video duration in seconds via ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    try:
        return float(stdout.decode().strip())
    except (ValueError, AttributeError):
        return 0.0


def _find_vtt(video_id: str) -> str | None:
    """
    Find the en.vtt file from F-09 subtitle pipeline (opportunistic).
    Returns the path if it exists locally or successfully downloads from MinIO, None otherwise.
    """
    vol = settings.OPENSTREAM_VOL_PATH.rstrip("/")
    bucket = settings.MINIO_BUCKET
    
    vtt_path_uploads = f"{vol}/openstream-uploads/subtitles/{video_id}/en.vtt"
    vtt_path_default = f"{vol}/{bucket}/subtitles/{video_id}/en.vtt"
    
    if os.path.isfile(vtt_path_uploads):
        logger.info(f"Found VTT file locally: {vtt_path_uploads}")
        return vtt_path_uploads
    elif os.path.isfile(vtt_path_default):
        logger.info(f"Found VTT file locally: {vtt_path_default}")
        return vtt_path_default

    # Fallback to fetching directly from MinIO API
    download_dir = f"/tmp/highlight_jobs/{video_id}"
    os.makedirs(download_dir, exist_ok=True)
    local_vtt_path = os.path.join(download_dir, "en.vtt")
    
    storage_path = f"subtitles/{video_id}/en.vtt"
    client = get_minio_client()
    
    try:
        # Try finding it in openstream-uploads bucket
        try:
            client.fget_object("openstream-uploads", storage_path, local_vtt_path)
            logger.info(f"Downloaded VTT from S3 via API (openstream-uploads bucket)")
            return local_vtt_path
        except Exception as e:
            logger.warning(f"S3 openstream-uploads VTT check failed: {e}")
            # Fallback to default bucket
            try:
                client.fget_object(bucket, storage_path, local_vtt_path)
                logger.info(f"Downloaded VTT from S3 via API ({bucket} bucket)")
                return local_vtt_path
            except Exception as inner_e:
                logger.warning(f"S3 fallback VTT check failed: {inner_e}")
    except Exception as e:
        logger.warning(f"S3 VTT fetch crashed: {e}")
        
    return None
