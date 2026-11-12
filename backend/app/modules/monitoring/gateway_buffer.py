import os
import json
import time
import asyncio
import logging
from typing import List, Optional, Callable, Dict, Any
from collections import deque
from pathlib import Path
from datetime import datetime, timezone

from app.modules.monitoring.data_contract import NormalizedReadingMessage

logger = logging.getLogger(__name__)


class BoundedGatewayBuffer:
    """Thread-safe bounded memory queue with batching, backpressure,
    retry with exponential backoff, crash-safe staging disk buffer,
    and audit-grade overflow observability (Fix 3 & Fix 4).
    """

    def __init__(
        self,
        gateway_id: str = "gw-default",
        max_queue_size: int = 5000,
        batch_size: int = 50,
        flush_interval_sec: float = 1.0,
        disk_buffer_dir: Optional[str] = None,
        buffer_dir: Optional[str] = None,
        max_disk_buffer_bytes: int = 50 * 1024 * 1024,  # 50 MB
    ):
        self.gateway_id = gateway_id
        self.max_queue_size = max_queue_size
        self.batch_size = batch_size
        self.flush_interval_sec = flush_interval_sec
        chosen_dir = disk_buffer_dir or buffer_dir or Path(__file__).resolve().parent / ".gateway_buffer"
        self.disk_buffer_dir = Path(chosen_dir)
        self.max_disk_buffer_bytes = max_disk_buffer_bytes

        self._queue: deque[NormalizedReadingMessage] = deque()
        self._lock = asyncio.Lock()
        self._dropped_count: int = 0
        self._dropped_first_timestamp: Optional[str] = None
        self._dropped_last_timestamp: Optional[str] = None
        self._overflow_alert_triggered: bool = False
        self._buffered_disk_count: int = 0
        self._quarantined_corrupt_count: int = 0  # Carry forward security: Quarantined corrupt records counter
        self._is_running: bool = False
        self._worker_task: Optional[asyncio.Task] = None
        self._ingestion_handler: Optional[Callable[[List[NormalizedReadingMessage]], Any]] = None

        # Ensure disk buffer directory exists with restrictive permissions
        try:
            self.disk_buffer_dir.mkdir(parents=True, exist_ok=True)
            if hasattr(os, "chmod") and os.name == "posix":
                os.chmod(self.disk_buffer_dir, 0o700)

            # Count existing disk buffer items across overflow and recovering staging files
            overflow_file = self.disk_buffer_dir / "gateway_overflow.jsonl"
            recovering_file = self.disk_buffer_dir / "gateway_recovering.jsonl"
            count = 0
            for fpath in (overflow_file, recovering_file):
                if fpath.exists():
                    with open(fpath, "r", encoding="utf-8") as f:
                        count += sum(1 for line in f if line.strip())
            self._buffered_disk_count = count
        except Exception as e:
            logger.warning(f"Failed to initialize disk buffer directory {self.disk_buffer_dir}: {e}")

    def set_ingestion_handler(self, handler: Callable[[List[NormalizedReadingMessage]], Any]) -> None:
        """Register the backend ingestion callback."""
        self._ingestion_handler = handler

    async def push(self, reading: NormalizedReadingMessage) -> bool:
        """Enqueue reading with bounded capacity protection and disk fallback."""
        async with self._lock:
            if len(self._queue) >= self.max_queue_size:
                # Try saving to disk buffer before dropping
                if self._try_write_to_disk(reading):
                    self._buffered_disk_count += 1
                    return True
                else:
                    self._dropped_count += 1
                    now_iso = datetime.now(timezone.utc).isoformat()
                    if not self._dropped_first_timestamp:
                        self._dropped_first_timestamp = now_iso
                    self._dropped_last_timestamp = now_iso
                    return False

            self._queue.append(reading)
            return True

    def get_metrics(self) -> Dict[str, Any]:
        """Return real-time queue depth, disk utilization, and overflow audit metrics (Fix 4)."""
        overflow_file = self.disk_buffer_dir / "gateway_overflow.jsonl"
        recovering_file = self.disk_buffer_dir / "gateway_recovering.jsonl"
        disk_bytes = 0
        try:
            if overflow_file.exists():
                disk_bytes += overflow_file.stat().st_size
            if recovering_file.exists():
                disk_bytes += recovering_file.stat().st_size
        except OSError:
            pass

        util_pct = round((disk_bytes / self.max_disk_buffer_bytes) * 100.0, 2) if self.max_disk_buffer_bytes > 0 else 0.0

        return {
            "gateway_id": self.gateway_id,
            "queue_depth": len(self._queue),
            "max_queue_size": self.max_queue_size,
            "buffered_readings": self._buffered_disk_count,
            "disk_usage_bytes": disk_bytes,
            "max_disk_buffer_bytes": self.max_disk_buffer_bytes,
            "disk_utilization_pct": util_pct,
            "dropped_readings": self._dropped_count,
            "quarantined_corrupt_records": self._quarantined_corrupt_count,
            "dropped_first_timestamp": self._dropped_first_timestamp,
            "dropped_last_timestamp": self._dropped_last_timestamp,
            "overflow_active": disk_bytes >= self.max_disk_buffer_bytes,
            "overflow_policy": "BOUNDED_DROP_ON_CAPACITY_EXCEEDED",
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
        # 1. Recover crash-safe disk buffer if any
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
                # Backend outage: save to persistent disk buffer with fsync
                for item in batch:
                    if self._try_write_to_disk(item):
                        self._buffered_disk_count += 1
                    else:
                        self._dropped_count += 1
                        now_iso = datetime.now(timezone.utc).isoformat()
                        if not self._dropped_first_timestamp:
                            self._dropped_first_timestamp = now_iso
                        self._dropped_last_timestamp = now_iso
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
                    res = await res
                if res is True or res is None:
                    return True
                # If explicit False returned from handler (e.g. HTTP 403 or 500)
                if res is False:
                    raise RuntimeError("Handler returned failure")
            except Exception as e:
                logger.warning(
                    f"[GatewayBuffer] Ingestion attempt {attempt}/{max_retries} failed: {e}"
                )
                if attempt < max_retries:
                    await asyncio.sleep(delay)
                    delay *= 2.0
        return False

    def _try_write_to_disk(self, reading: NormalizedReadingMessage) -> bool:
        """Write item to local disk buffer with strict size ceiling and durability fsync (Fix 3 & Fix 4)."""
        try:
            overflow_file = self.disk_buffer_dir / "gateway_overflow.jsonl"
            recovering_file = self.disk_buffer_dir / "gateway_recovering.jsonl"

            # Calculate total disk usage
            current_disk_bytes = 0
            if overflow_file.exists():
                current_disk_bytes += overflow_file.stat().st_size
            if recovering_file.exists():
                current_disk_bytes += recovering_file.stat().st_size

            if current_disk_bytes >= self.max_disk_buffer_bytes:
                now_iso = datetime.now(timezone.utc).isoformat()
                if not self._dropped_first_timestamp:
                    self._dropped_first_timestamp = now_iso
                self._dropped_last_timestamp = now_iso

                if not self._overflow_alert_triggered:
                    self._overflow_alert_triggered = True
                    logger.critical(
                        f"[CRITICAL GATEWAY OVERFLOW ALERT] Disk buffer limit (50 MB) reached on gateway '{self.gateway_id}'! "
                        f"Incoming telemetry dropped. Timestamp: {now_iso}. "
                        f"Capacity: {self.max_disk_buffer_bytes} bytes. Offline outage exceeded maximum retention boundary."
                    )
                return False

            with open(overflow_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(reading.to_dict()) + "\n")
                f.flush()
                try:
                    os.fsync(f.fileno())
                except (AttributeError, OSError):
                    pass

            # Reset alert flag once buffer is safely writing again
            if current_disk_bytes < (self.max_disk_buffer_bytes * 0.9):
                self._overflow_alert_triggered = False

            return True
        except Exception as e:
            logger.error(f"[GatewayBuffer] Failed to write to disk buffer: {e}")
            return False

    async def _recover_disk_buffer(self) -> None:
        """Replay disk buffer items back into queue using crash-safe staging file (Fix 3).
        
        NEVER deletes unacknowledged readings. Staging file is only deleted/truncated
        after items are safely accepted into memory or delivered.
        """
        overflow_file = self.disk_buffer_dir / "gateway_overflow.jsonl"
        recovering_file = self.disk_buffer_dir / "gateway_recovering.jsonl"
        quarantine_file = self.disk_buffer_dir / "gateway_corrupt_records.jsonl"

        # 1. If no recovering file exists, but overflow file exists and is non-empty, atomically stage it
        if not recovering_file.exists() or recovering_file.stat().st_size == 0:
            if overflow_file.exists() and overflow_file.stat().st_size > 0:
                try:
                    os.replace(overflow_file, recovering_file)
                    self._fsync_dir()
                except Exception as e:
                    logger.error(f"[GatewayBuffer] Error staging overflow file: {e}")
                    return
            else:
                return

        # 2. Read valid lines from recovering staging file
        valid_readings: List[NormalizedReadingMessage] = []
        corrupt_lines_count = 0
        try:
            with open(recovering_file, "r", encoding="utf-8") as f:
                for line in f:
                    line_str = line.strip()
                    if not line_str:
                        continue
                    try:
                        data = json.loads(line_str)
                        valid_readings.append(NormalizedReadingMessage(**data))
                    except Exception as ex:
                        corrupt_lines_count += 1
                        self._quarantined_corrupt_count += 1
                        # Carry forward security: Quarantine corrupt records with critical alert
                        now_iso = datetime.now(timezone.utc).isoformat()
                        logger.critical(
                            f"[CRITICAL BUFFER INTEGRITY ALERT] Quarantined corrupted buffer record on gateway '{self.gateway_id}': "
                            f"{ex}. Raw record: {line_str[:120]}..."
                        )
                        try:
                            with open(quarantine_file, "a", encoding="utf-8") as qf:
                                qf.write(json.dumps({
                                    "quarantined_at": now_iso,
                                    "gateway_id": self.gateway_id,
                                    "error": str(ex),
                                    "raw_line": line_str,
                                }) + "\n")
                                qf.flush()
                                try:
                                    os.fsync(qf.fileno())
                                except (AttributeError, OSError):
                                    pass
                        except Exception as q_err:
                            logger.error(f"[GatewayBuffer] Failed to write quarantine log: {q_err}")

            if corrupt_lines_count > 0:
                logger.warning(
                    f"[GatewayBuffer] Recovered {len(valid_readings)} valid readings, "
                    f"quarantined {corrupt_lines_count} corrupted records to {quarantine_file.name}."
                )

            # 3. Safely load into memory queue without dropping unacknowledged readings
            async with self._lock:
                available_capacity = self.max_queue_size - len(self._queue)
                if available_capacity > 0:
                    to_enqueue = valid_readings[:available_capacity]
                    remaining = valid_readings[available_capacity:]

                    for r in to_enqueue:
                        self._queue.append(r)
                        if self._buffered_disk_count > 0:
                            self._buffered_disk_count -= 1

                    # If all were loaded, we can safely unlink the recovering staging file!
                    if not remaining:
                        try:
                            recovering_file.unlink(missing_ok=True)
                            self._fsync_dir()
                        except Exception:
                            pass
                    else:
                        # Overwrite recovering file with only the remaining un-enqueued readings with fsync
                        with open(recovering_file, "w", encoding="utf-8") as f:
                            for r in remaining:
                                f.write(json.dumps(r.to_dict()) + "\n")
                            f.flush()
                            try:
                                os.fsync(f.fileno())
                            except (AttributeError, OSError):
                                pass
                        self._fsync_dir()
        except Exception as e:
            logger.error(f"[GatewayBuffer] Error during crash-safe recovery: {e}")

    def _fsync_dir(self) -> None:
        """Best-effort directory fsync for metadata durability on platforms that support it."""
        if os.name != "posix":
            return
        try:
            if hasattr(os, "O_DIRECTORY"):
                dfd = os.open(str(self.disk_buffer_dir), os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(dfd)
                finally:
                    os.close(dfd)
        except (AttributeError, OSError):
            pass
