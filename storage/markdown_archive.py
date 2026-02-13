import asyncio
import json
import os
import re
import urllib.request
import uuid
from urllib.parse import urlsplit

from astrbot.api import logger


class MarkdownArchive:
    def __init__(
        self,
        root_dir: str,
        save_assets: bool = True,
        asset_max_mb: int = 20,
    ):
        self.root_dir = os.path.abspath(root_dir)
        self.save_assets = save_assets
        self.asset_max_bytes = max(1, int(asset_max_mb)) * 1024 * 1024

        self._lock = asyncio.Lock()
        self._index_dir = os.path.join(self.root_dir, "index")
        self._index_file = os.path.join(self._index_dir, "message_ids.json")

        os.makedirs(self._index_dir, exist_ok=True)
        if not os.path.exists(self._index_file):
            with open(self._index_file, "w", encoding="utf-8") as f:
                json.dump({}, f, ensure_ascii=False)

    @staticmethod
    def _safe_name(name: str, fallback: str) -> str:
        text = (name or "").strip() or fallback
        text = re.sub(r"[\\/:*?\"<>|]+", "_", text)
        text = text.replace("\n", " ").replace("\r", " ").strip()
        return text[:180] or fallback

    async def has_processed(self, message_key: str) -> bool:
        async with self._lock:
            try:
                with open(self._index_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                return False
            return str(message_key) in data

    async def mark_processed(self, message_key: str, value: dict):
        async with self._lock:
            try:
                with open(self._index_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                data = {}

            data[str(message_key)] = value
            with open(self._index_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    async def append_entry(self, day_str: str, content: str) -> str:
        async with self._lock:
            day_dir = os.path.join(self.root_dir, day_str)
            os.makedirs(day_dir, exist_ok=True)
            target_file = os.path.join(day_dir, "messages.md")
            with open(target_file, "a", encoding="utf-8") as f:
                f.write(content)
            return target_file

    async def save_url_asset(
        self,
        day_str: str,
        category: str,
        url: str,
        preferred_name: str,
    ) -> str | None:
        if not self.save_assets:
            return None
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            return None

        safe_name = self._safe_name(preferred_name, f"asset_{uuid.uuid4().hex[:8]}")

        day_dir = os.path.join(self.root_dir, day_str)
        asset_dir = os.path.join(day_dir, category)
        os.makedirs(asset_dir, exist_ok=True)

        target_name = f"{uuid.uuid4().hex[:8]}_{safe_name}"
        target_path = os.path.join(asset_dir, target_name)

        def _download() -> bool:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with (
                urllib.request.urlopen(req, timeout=25) as resp,
                open(target_path, "wb") as out,
            ):
                total = 0
                while True:
                    chunk = resp.read(1024 * 64)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > self.asset_max_bytes:
                        raise ValueError("asset_too_large")
                    out.write(chunk)
            return os.path.exists(target_path) and os.path.getsize(target_path) > 0

        try:
            ok = await asyncio.to_thread(_download)
            if not ok:
                return None
            rel = f"{category}/{target_name}".replace("\\", "/")
            logger.info(f"[QQ2TG][Archive] 附件已保存: {day_str}/{rel}")
            return rel
        except ValueError as exc:
            if str(exc) == "asset_too_large":
                logger.info(
                    f"[QQ2TG][Archive] 附件超过上限({self.asset_max_bytes // (1024 * 1024)}MB): {preferred_name}"
                )
            return None
        except Exception as exc:
            logger.warning(f"[QQ2TG][Archive] 下载附件失败: {exc}")
            try:
                if os.path.exists(target_path):
                    os.remove(target_path)
            except Exception:
                pass
            return None

    @staticmethod
    def guess_name_from_url(url: str, fallback: str) -> str:
        if not isinstance(url, str):
            return fallback
        try:
            parsed = urlsplit(url)
            base = os.path.basename(parsed.path)
            if base:
                return base
        except Exception:
            pass
        return fallback
