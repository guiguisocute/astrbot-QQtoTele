# local_cache.py

from ..config import TEMP_DIR, WAITING_TIME
import os
import json
import time
import asyncio
from astrbot.api import logger


class LocalCache:
    def __init__(self, max_age_seconds: int = 3600, waiting_time: int | None = None):
        self.cache_file = os.path.join(TEMP_DIR, "local_cache.json")
        self.WAITING_TIME = waiting_time if waiting_time is not None else WAITING_TIME
        self.MAX_CACHE_AGE_SECONDS = max_age_seconds

        self._file_lock = asyncio.Lock()

        cache_dir = os.path.dirname(self.cache_file)
        os.makedirs(cache_dir, exist_ok=True)

        if not os.path.exists(self.cache_file):
            with open(self.cache_file, "w") as f:
                json.dump({}, f)

    @staticmethod
    def _parse_cache_entry(entry):
        if isinstance(entry, (int, float)):
            return float(entry), None, False
        if isinstance(entry, dict):
            ts_raw = entry.get("ts", entry.get("timestamp", 0))
            group_id = entry.get("group_id")
            ignore_forward = bool(entry.get("ignore_forward", False))
            try:
                ts = float(ts_raw)
            except (TypeError, ValueError):
                ts = 0.0
            return ts, group_id, ignore_forward
        return 0.0, None, False

    async def _cleanup_expired_cache(self) -> int:
        """清理缓存中超过 MAX_CACHE_AGE_SECONDS 的消息，并返回清理数量。"""
        current_time = time.time()
        cleaned_count = 0

        async with self._file_lock:
            try:
                with open(self.cache_file, "r") as f:
                    cache = json.load(f)

            except (FileNotFoundError, json.JSONDecodeError):
                logger.error("[LocalCache][CLEANUP] 错误：文件不存在或内容格式错误。")
                return 0

            keys_to_keep = {}
            for message_id_str, entry in cache.items():
                timestamp, group_id, ignore_forward = self._parse_cache_entry(entry)
                if (
                    timestamp <= 0
                    or current_time - timestamp > self.MAX_CACHE_AGE_SECONDS
                ):
                    cleaned_count += 1
                else:
                    keys_to_keep[message_id_str] = {
                        "ts": timestamp,
                        "group_id": group_id,
                        "ignore_forward": ignore_forward,
                    }

            if cleaned_count > 0:
                with open(self.cache_file, "w") as f:
                    json.dump(keys_to_keep, f)

            return cleaned_count

    async def add_cache(
        self, message_id: int, group_id=None, ignore_forward: bool = False
    ):
        """添加一条message_id进入缓存, 保存时间"""
        str_message_id = str(message_id)

        async with self._file_lock:
            try:
                with open(self.cache_file, "r") as f:
                    cache = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                cache = {}

            cache[str_message_id] = {
                "ts": time.time(),
                "group_id": group_id,
                "ignore_forward": bool(ignore_forward),
            }

            with open(self.cache_file, "w") as f:
                json.dump(cache, f)

    async def get_waiting_messages(self) -> list:
        """获取已经等待足够时间的消息列表"""

        waiting_messages = []
        current_time = time.time()

        async with self._file_lock:
            try:
                with open(self.cache_file, "r") as f:
                    cache = json.load(f)

            except (FileNotFoundError, json.JSONDecodeError):
                return []

        for message_id_str, entry in cache.items():
            timestamp, _, _ = self._parse_cache_entry(entry)
            if current_time - timestamp > self.WAITING_TIME:
                waiting_messages.append(message_id_str)

        return waiting_messages

    async def get_earliest_timestamp(self) -> float | None:
        """获取缓存中最早的时间戳，用于计算等待时间。如果没有消息返回 None。"""
        async with self._file_lock:
            try:
                with open(self.cache_file, "r") as f:
                    cache = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                return None

        if not cache:
            return None

        timestamps = []
        for entry in cache.values():
            ts, _, _ = self._parse_cache_entry(entry)
            if ts > 0:
                timestamps.append(ts)
        return min(timestamps) if timestamps else None

    async def get_message_group_id(self, message_id: int | str):
        str_message_id = str(message_id)

        async with self._file_lock:
            try:
                with open(self.cache_file, "r") as f:
                    cache = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                return None

        if str_message_id not in cache:
            return None

        _, group_id, _ = self._parse_cache_entry(cache[str_message_id])
        return group_id

    async def get_message_ignore_forward(self, message_id: int | str) -> bool:
        str_message_id = str(message_id)

        async with self._file_lock:
            try:
                with open(self.cache_file, "r") as f:
                    cache = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                return False

        if str_message_id not in cache:
            return False

        _, _, ignore_forward = self._parse_cache_entry(cache[str_message_id])
        return ignore_forward

    async def has_pending_messages(self) -> bool:
        """检查缓存中是否还有消息（无论是否成熟）"""
        async with self._file_lock:
            try:
                with open(self.cache_file, "r") as f:
                    cache = json.load(f)
                return bool(cache)
            except (FileNotFoundError, json.JSONDecodeError):
                return False

    async def remove_cache(self, message_id: int):
        """转发成功或失败后，手动删除指定的 message_id"""
        str_message_id = str(message_id)

        async with self._file_lock:
            try:
                with open(self.cache_file, "r") as f:
                    cache = json.load(f)

            except (FileNotFoundError, json.JSONDecodeError):
                return False

            if str_message_id in cache:
                del cache[str_message_id]

                with open(self.cache_file, "w") as f:
                    json.dump(cache, f)

                return True
            return False
