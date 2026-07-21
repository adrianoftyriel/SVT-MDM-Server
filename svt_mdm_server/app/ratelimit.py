"""A tiny in-process throttle for enrollment attempts.

Per-IP limiting is useless here because every request arrives through the
reverse proxy from a single source address. Instead we cap the number of
*failed* enrollment attempts (bad secret or bad/used token) across the whole
server within a sliding window, which is what actually protects the shared
enrollment secret from brute force. A successful enrollment clears the counter.

Single uvicorn process, so a module-level list guarded by a lock is enough.
"""

from __future__ import annotations

import threading
import time


class FailureThrottle:
    def __init__(self, max_failures: int, window_seconds: float) -> None:
        self.max_failures = max_failures
        self.window = window_seconds
        self._failures: list[float] = []
        self._lock = threading.Lock()

    def retry_after(self) -> float | None:
        """Seconds to wait if currently blocked, else None."""
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            if len(self._failures) >= self.max_failures:
                return max(0.0, self.window - (now - self._failures[0]))
        return None

    def record_failure(self) -> None:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            self._failures.append(now)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()

    def _prune(self, now: float) -> None:
        cutoff = now - self.window
        self._failures[:] = [t for t in self._failures if t > cutoff]


# 20 failed enrollment attempts within 10 minutes trips the throttle.
enroll_throttle = FailureThrottle(max_failures=20, window_seconds=600)
