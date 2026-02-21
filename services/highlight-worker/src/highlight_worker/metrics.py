"""Prometheus metric definitions for highlight worker."""

from prometheus_client import Counter, Histogram, Gauge

# Job-level metrics
JOBS_PROCESSED = Counter(
    "octane_highlight_jobs_total",
    "Total highlight jobs processed",
    ["status"],
)
JOB_LATENCY = Histogram(
    "octane_highlight_job_seconds",
    "Time spent processing a highlight job",
    buckets=[30, 60, 120, 300, 600, 900, 1800],
)
CLIPS_GENERATED = Counter(
    "octane_highlight_clips_total",
    "Total highlight clips generated",
)

# Signal-level metrics
SIGNAL_LATENCY = Histogram(
    "octane_highlight_signal_seconds",
    "Time per signal module",
    ["signal"],
)

# Resource governance
CPU_USAGE = Gauge(
    "octane_highlight_cpu_percent",
    "Current CPU usage percent",
)
MEMORY_USAGE = Gauge(
    "octane_highlight_memory_mb",
    "Current memory usage in MB",
)
THROTTLE_COUNT = Counter(
    "octane_highlight_throttle_total",
    "Number of self-throttle pauses",
)

# Spec §4.17 — remaining required metrics
SIGNAL_FAILURES = Counter(
    "openstream_highlight_signal_failures_total",
    "Signal module failures",
    ["signal"],
)
VTT_USED = Counter(
    "openstream_highlight_vtt_used_total",
    "How often VTT semantic signal was available",
    ["used"],
)
INTELLIGENCE_CALLS = Counter(
    "openstream_highlight_intelligence_calls_total",
    "Intelligence Service calls by type",
    ["type"],
)
