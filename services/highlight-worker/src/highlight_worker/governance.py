"""Resource governance — CPU/memory self-throttling using psutil."""

import asyncio
import logging
import os
import psutil

from .metrics import CPU_USAGE, MEMORY_USAGE, THROTTLE_COUNT

logger = logging.getLogger(__name__)


class GovernanceMonitor:
    """Polls CPU and memory, pausing work when limits are breached."""

    def __init__(
        self,
        max_cpu_percent: int = 60,
        max_memory_mb: int = 900,
        poll_interval: int = 10,
        nice_priority: int = 15,
    ):
        self.max_cpu = max_cpu_percent
        self.max_memory = max_memory_mb
        self.poll_interval = poll_interval
        self.nice_priority = nice_priority
        self._should_throttle = False

    def apply_nice(self):
        """Set process nice priority for lower scheduling priority."""
        try:
            os.nice(self.nice_priority)
            logger.info(f"Applied nice priority: {self.nice_priority}")
        except (OSError, PermissionError) as e:
            logger.warning(f"Could not set nice priority: {e}")

    async def check_once(self) -> bool:
        """Single resource check. Returns True if throttling is needed."""
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.Process().memory_info().rss / (1024 * 1024)

        CPU_USAGE.set(cpu)
        MEMORY_USAGE.set(mem)

        if cpu > self.max_cpu or mem > self.max_memory:
            logger.warning(
                f"Resource limit breached — CPU: {cpu:.1f}% (max {self.max_cpu}%), "
                f"Memory: {mem:.0f}MB (max {self.max_memory}MB)"
            )
            THROTTLE_COUNT.inc()
            return True
        return False

    async def wait_until_safe(self):
        """Block until resources are within limits."""
        while await self.check_once():
            logger.info(
                f"Throttling — waiting {self.poll_interval}s for resources to free up"
            )
            await asyncio.sleep(self.poll_interval)
