import asyncio
import logging
import random
import time
from pathlib import Path

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

def random_user_agent() -> str:
    return random.choice(USER_AGENTS)


def setup_logging(log_file: str):
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
    )
    return logging.getLogger("halal_pipeline")


class DomainRateLimiter:
    def __init__(self, default_seconds: float, overrides: dict[str, float],
                 jitter_fraction: float = 0.4):
        self.default_seconds = default_seconds
        self.overrides = overrides
        self.jitter_fraction = jitter_fraction
        self._last_hit: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def wait(self, domain: str):
        async with self._lock:
            base_gap = self.overrides.get(domain, self.default_seconds)
            jitter = base_gap * self.jitter_fraction
            min_gap = max(base_gap + random.uniform(-jitter, jitter), 0.05)
            last = self._last_hit.get(domain, 0)
            now = time.monotonic()
            wait_for = min_gap - (now - last)
            self._last_hit[domain] = max(now, last) + (wait_for if wait_for > 0 else 0)
        if wait_for > 0:
            await asyncio.sleep(wait_for)


class DomainConcurrencyLimiter:
    def __init__(self, max_per_domain: int = 2):
        self.max_per_domain = max_per_domain
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._lock = asyncio.Lock()

    async def _get_semaphore(self, domain: str) -> asyncio.Semaphore:
        async with self._lock:
            if domain not in self._semaphores:
                self._semaphores[domain] = asyncio.Semaphore(self.max_per_domain)
            return self._semaphores[domain]

    def limit(self, domain: str):
        return _DomainLimitContext(self, domain)


class _DomainLimitContext:
    def __init__(self, limiter, domain):
        self.limiter = limiter
        self.domain = domain
        self.semaphore = None

    async def __aenter__(self):
        self.semaphore = await self.limiter._get_semaphore(self.domain)
        await self.semaphore.acquire()

    async def __aexit__(self, *exc):
        self.semaphore.release()


class DomainCircuitBreaker:
    """
    Was: permanent block for the rest of the run once tripped -> sources
    stayed dead forever even if the block was temporary, shrinking coverage
    as a long run progressed. Now: cools down after cooldown_seconds and
    allows a retry, instead of blacklisting a domain for good.
    """

    def __init__(self, failure_threshold: int, enabled: bool = True,
                 cooldown_seconds: float = 300.0):
        self.failure_threshold = failure_threshold
        self.enabled = enabled
        self.cooldown_seconds = cooldown_seconds
        self._consecutive_failures: dict[str, int] = {}
        self._tripped_at: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def is_open(self, domain: str) -> bool:
        if not self.enabled:
            return False
        tripped_at = self._tripped_at.get(domain)
        if tripped_at is None:
            return False
        if time.monotonic() - tripped_at >= self.cooldown_seconds:
            return False  # cooldown elapsed -> allow a retry
        return True

    async def record_result(self, domain: str, success: bool):
        if not self.enabled:
            return
        async with self._lock:
            if success:
                self._consecutive_failures[domain] = 0
                self._tripped_at.pop(domain, None)
            else:
                count = self._consecutive_failures.get(domain, 0) + 1
                self._consecutive_failures[domain] = count
                if count >= self.failure_threshold:
                    self._tripped_at[domain] = time.monotonic()