"""Base interface for signal modules."""

from abc import ABC, abstractmethod


class BaseSignal(ABC):
    """
    Each signal module receives the video proxy path and config,
    and returns a dict mapping second → signal_score (0.0–1.0).
    """

    @abstractmethod
    async def detect(
        self, proxy_path: str, config: dict, **kwargs
    ) -> dict[int, float]:
        """
        Analyze the video and return per-second scores.

        Args:
            proxy_path: Path to the 480p proxy video file
            config: Signal-specific configuration from YAML
            **kwargs: Additional inputs (e.g., chat_path, vtt_path)

        Returns:
            Dict mapping second offset to a normalized score (0.0–1.0)
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Signal module identifier."""
        ...
