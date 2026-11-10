import os
import json
import time
import asyncio
import logging
from typing import List, Optional, Callable, Dict, Any
from collections import deque
from pathlib import Path

from app.modules.monitoring.data_contract import NormalizedReadingMessage

logger = logging.getLogger(__name__)


class BoundedGatewayBuffer:
    """Thread-safe bounded memory queue with batching, backpressure,
    retry with exponential backoff, and local disk buffering fallback.
    """

    def __init__(
        self,
        gateway_id: str = "gw-default",
        max_queue_size: int = 5000,
        batch_size: int = 50,
        flush_interval_sec: float = 1.0,
        disk_buffer_dir: Optional[str] = None,
        max_disk_buffer_bytes: int = 50 * 1024 * 1024,  # 50 MB
    ):
        self.gateway_id = gateway_id
        self.max_queue_size = max_queue_size
        self.batch_size = batch_size
        self.flush_interval_sec = flush_interval_sec
        self.disk_buffer_dir = Path(disk_buffer_dir or Path(__file__).resolve().parent / ".gateway_buffer")
        self.max_disk_buffer_bytes = max_disk_buffer_bytes

        self._queue: deque[NormalizedReadingMessage] = deque()
        self._lock = asyncio.Lock()
        self._dropped_count: int = 0
        self._buffered_disk_count: int = 0
        self._is_running: bool = False
        self._worker_task: Optional[asyncio.Task] = None
        self._ingestion_handler: Optional[Callable[[List[NormalizedReadingMessage]], Any]] = None

        # Ensure disk buffer directory exists
        try:
            self.disk_buffer_dir.mkdir(parents=True, exist_ok=True)
            overflow_file = self.disk_buffer_dir / "gateway_overflow.jsonl"
            if overflow_file.exists():
                with open(overflow_file, "r", encoding="utf-8") as f:
                    self._buffered_disk_count = sum(1 for line in f if line.strip())
        except Exception as e:
            logger.warning(f"Failed to create disk buffer directory {self.disk_buffer_dir}: {e}")

    def set_ingestion_handler(self, handler: Callable[[List[NormalizedReadingMessage]], Any]) -> None:
        """Register the backend ingestion callback."""
        self._ingestion_handler = handler

    async def push(self, reading: NormalizedReadingMessage) -> bool:
        """Enqueue reading with bounded capacity protection (Requirement 7)."""
        async with self._lock:
            if len(self._queue) >= self.max_queue_size:
                # Try saving to disk buffer before dropping
                if self._try_write_to_disk(reading):
                    self._buffered_disk_count += 1
                    return True
                else:
                    self._dropped_count += 1
                    logger.warning(
                        f"[GatewayBuffer] Queue full ({self.max_queue_size}) and disk buffer limit reached. Reading dropped."
                    )
                    return False

            self._queue.append(reading)
            return True

    def get_metrics(self) -> Dict[str, Any]:
        """Return real-time queue depth and buffering statistics."""
        return {
            "gateway_id": self.gateway_id,
            "queue_depth": len(self._queue),
            "buffered_readings": self._buffered_disk_count,
            "dropped_readings": self._dropped_count,
            "max_queue_size": self.max_queue_size,
        }

    async def start(self) -> None:
        """Start the background flush loop."""
        if self._is_running:
            return
        self._is_running = True
        self._worker_task = asyncio.create_task(self._flush_loop())
        logger.info(f"[GatewayBuffer] Started flush loop for gateway {self.gateway_id}")

    async def stop(self) -> None:
        """Stop worker and flush remaining items."""
        self._is_running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        # Final flush
        await self.flush()
        logger.info(f"[GatewayBuffer] Stopped flush loop for gateway {self.gateway_id}")

    async def flush(self) -> int:
        """Manually trigger flush of queue to ingestion handler."""
        # 1. First recover disk buffer if any
        await self._recover_disk_buffer()

        batch: List[NormalizedReadingMessage] = []
        async with self._lock:
            while self._queue and len(batch) < self.batch_size:
                batch.append(self._queue.popleft())

        if not batch:
            return 0

        if self._ingestion_handler:
            success = await self._send_with_retry(batch)
            if not success:
                # Backend outage: save to disk buffer to prevent data loss
                for item in batch:
                    if self._try_write_to_disk(item):
                        self._buffered_disk_count += 1
                    else:
                        self._dropped_count += 1
                return 0

        return len(batch)

    async def _flush_loop(self) -> None:
        """Periodic batch ingestion worker."""
        while self._is_running:
            try:
                await asyncio.sleep(self.flush_interval_sec)
                while len(self._queue) > 0:
                    flushed = await self.flush()
                    if flushed == 0:
                        break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[GatewayBuffer] Unexpected error in flush loop: {e}")

    async def _send_with_retry(self, batch: List[NormalizedReadingMessage], max_retries: int = 3) -> bool:
        """Execute ingestion with bounded exponential backoff."""
        delay = 0.5
        for attempt in range(1, max_retries + 1):
            try:
                res = self._ingestion_handler(batch)
                if asyncio.iscoroutine(res):
                    await res
                return True
            except Exception as e:
                logger.warning(
                    f"[GatewayBuffer] Ingestion attempt {attempt}/{max_retries} failed: {e}"
                )
                if attempt < max_retries:
                    await asyncio.sleep(delay)
                    delay *= 2.0
        return False

    def _try_write_to_disk(self, reading: NormalizedReadingMessage) -> bool:
        """Write item to local disk buffer with strict size ceiling."""
        try:
            buffer_file = self.disk_buffer_dir / "gateway_overflow.jsonl"
            if buffer_file.exists() and buffer_file.stat().st_size >= self.max_disk_buffer_bytes:
                return False

            with open(buffer_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(reading.to_dict()) + "\n")
            return True
        except Exception as e:
            logger.error(f"[GatewayBuffer] Failed to write to disk buffer: {e}")
            return False

    async def _recover_disk_buffer(self) -> None:
        """Replay disk buffer items back into queue when space becomes available."""
        buffer_file = self.disk_buffer_dir / "gateway_overflow.jsonl"
        if not buffer_file.exists() or buffer_file.stat().st_size == 0:
            return

        recovered: List[NormalizedReadingMessage] = []
        try:
            with open(buffer_file, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        recovered.append(NormalizedReadingMessage(**data))
                    except Exception:
                        pass

            # Truncate file once read
            with open(buffer_file, "w", encoding="utf-8") as f:
                f.truncate(0)

            async with self._lock:
                for r in recovered:
                    if len(self._queue) < self.max_queue_size:
                        self._queue.append(r)
                        if self._buffered_disk_count > 0:
                            self._buffered_disk_count -= 1
                    else:
                        self._try_write_to_disk(r)
        except Exception as e:
            logger.error(f"[GatewayBuffer] Error recovering disk buffer: {e}")

