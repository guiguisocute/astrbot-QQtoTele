import asyncio
import html
import json
import os
import re
import tempfile
import time
import uuid
import urllib.request
from datetime import datetime, time as dtime
from urllib.parse import parse_qsl, quote, urlsplit, urlunsplit

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, MessageEventResult, filter
import astrbot.api.message_components as Comp
from astrbot.api.star import Context, Star, register
from astrbot.core.star.filter.platform_adapter_type import PlatformAdapterType

from .storage.local_cache import LocalCache


@register("astrbot_qq_to_telegram", "guiguisocute", "QQ -> Telegram 搬运插件", "1.0.6")
class SowingDiscord(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        config = config or {}

        self.instance_id = str(uuid.uuid4())[:8]

        self.banshi_interval = int(config.get("banshi_interval", 600))
        self.banshi_cache_seconds = int(config.get("banshi_cache_seconds", 3600))
        self.cooldown_day_seconds = int(config.get("banshi_cooldown_day_seconds", 600))
        self.cooldown_night_seconds = int(
            config.get("banshi_cooldown_night_seconds", 3600)
        )
        self.cooldown_day_start_str = config.get("banshi_cooldown_day_start", "09:00")
        self.cooldown_night_start_str = config.get(
            "banshi_cooldown_night_start", "01:00"
        )
        self._day_start = self._parse_time_str(self.cooldown_day_start_str, dtime(9, 0))
        self._night_start = self._parse_time_str(
            self.cooldown_night_start_str, dtime(1, 0)
        )

        self.banshi_group_list = self._normalize_int_list(
            config.get("banshi_group_list")
        )
        self.banshi_target_list = self._normalize_int_list(
            config.get("banshi_target_list")
        )
        self.telegram_target_unified_origins = self._normalize_str_list(
            config.get("telegram_target_unified_origins")
        )

        self.block_source_messages = bool(config.get("block_source_messages", False))
        self.banshi_waiting_time = int(config.get("banshi_waiting_time", 1))
        self.telegram_upload_files = bool(config.get("telegram_upload_files", True))
        self.telegram_upload_max_mb = int(config.get("telegram_upload_max_mb", 10))
        self.telegram_upload_max_bytes = (
            max(1, self.telegram_upload_max_mb) * 1024 * 1024
        )
        self.local_cache = LocalCache(
            max_age_seconds=self.banshi_cache_seconds,
            waiting_time=self.banshi_waiting_time,
        )

        self.forward_lock = asyncio.Lock()
        self._forward_task = None

        logger.info(f"[QQ2TG][ID:{self.instance_id}] 插件初始化完成")
        logger.info(f"[QQ2TG][ID:{self.instance_id}] 来源群: {self.banshi_group_list}")
        logger.info(
            f"[QQ2TG][ID:{self.instance_id}] Telegram 目标: {self.telegram_target_unified_origins}"
        )

    @staticmethod
    def _normalize_int_list(raw):
        if isinstance(raw, (int, str)):
            return [int(raw)] if str(raw).isdigit() else []
        if isinstance(raw, list):
            return [int(x) for x in raw if str(x).isdigit()]
        return []

    @staticmethod
    def _normalize_str_list(raw):
        if isinstance(raw, str):
            return [raw.strip()] if raw.strip() else []
        if isinstance(raw, list):
            return [str(x).strip() for x in raw if str(x).strip()]
        return []

    def _parse_time_str(self, time_str: str, fallback: dtime) -> dtime:
        try:
            if isinstance(time_str, str):
                parts = time_str.split(":")
                hour = int(parts[0])
                minute = int(parts[1]) if len(parts) > 1 else 0
                if 0 <= hour < 24 and 0 <= minute < 60:
                    return dtime(hour, minute)
        except Exception as exc:
            logger.warning(
                f"[QQ2TG][ID:{self.instance_id}] 冷却时间解析失败: {time_str}, error={exc}"
            )
        return fallback

    def _get_banshi_interval_dynamic(self) -> int:
        now = datetime.now().time()
        if now >= self._day_start or now < self._night_start:
            return self.cooldown_day_seconds
        return self.cooldown_night_seconds

    def _is_source_group(self, group_id_raw) -> bool:
        if group_id_raw in self.banshi_group_list:
            return True
        try:
            return int(group_id_raw) in self.banshi_group_list
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _is_queryable_message_id(message_id) -> bool:
        return isinstance(message_id, (int, str)) and str(message_id).isdigit()

    @staticmethod
    def _pick_file_name(file_data: dict) -> str:
        raw_name = file_data.get("name") or ""
        if isinstance(raw_name, str):
            cleaned = raw_name.strip()
            if cleaned and cleaned not in {"拓展名", "扩展名", "unknown", "file.bin"}:
                return cleaned

        raw_file = file_data.get("file") or ""
        if isinstance(raw_file, str):
            cleaned = raw_file.strip()
            if cleaned and not cleaned.startswith(("http://", "https://")):
                return cleaned

        return "unknown_file"

    @staticmethod
    def _ensure_fname_in_url(file_url: str, file_name: str) -> str:
        if not isinstance(file_url, str) or not file_url.startswith(
            ("http://", "https://")
        ):
            return file_url

        try:
            parsed = urlsplit(file_url)
            query_items = parse_qsl(parsed.query, keep_blank_values=True)

            has_fname = False
            new_items = []
            for key, value in query_items:
                if key == "fname":
                    has_fname = True
                    if value:
                        new_items.append((key, value))
                    else:
                        new_items.append((key, file_name))
                else:
                    new_items.append((key, value))

            if not has_fname:
                new_items.append(("fname", file_name))

            new_query = "&".join(
                [
                    f"{quote(str(k), safe='')}={quote(str(v), safe='')}"
                    for k, v in new_items
                ]
            )
            return urlunsplit(
                (parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment)
            )
        except Exception:
            return file_url

    @staticmethod
    def _safe_file_name(file_name: str) -> str:
        name = (file_name or "unknown_file").strip()
        name = re.sub(r"[\\/:*?\"<>|]+", "_", name)
        return name[:180] or "unknown_file"

    @staticmethod
    def _find_first_nonempty_by_keys(obj, keys: set[str]) -> str:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if str(k).lower() in keys and isinstance(v, (str, int, float)):
                    text = str(v).strip()
                    if text:
                        return text
            for v in obj.values():
                found = SowingDiscord._find_first_nonempty_by_keys(v, keys)
                if found:
                    return found
            return ""

        if isinstance(obj, list):
            for item in obj:
                found = SowingDiscord._find_first_nonempty_by_keys(item, keys)
                if found:
                    return found
            return ""

        return ""

    @classmethod
    def _parse_json_segment_summary(cls, data: dict) -> str:
        raw = data.get("data")
        obj = None

        if isinstance(raw, dict):
            obj = raw
        elif isinstance(raw, str):
            payload = raw.strip()
            if payload:
                candidates = [payload, html.unescape(payload)]
                for candidate in candidates:
                    try:
                        parsed = json.loads(candidate)
                        if isinstance(parsed, str):
                            parsed = json.loads(parsed)
                        if isinstance(parsed, (dict, list)):
                            obj = parsed
                            break
                    except Exception:
                        continue

        if obj is None:
            preview = str(raw).strip() if raw is not None else ""
            if len(preview) > 160:
                preview = preview[:157] + "..."
            return f"[JSON卡片] {preview}" if preview else "[JSON卡片]"

        title = cls._find_first_nonempty_by_keys(
            obj, {"title", "prompt", "source", "name"}
        )
        desc = cls._find_first_nonempty_by_keys(
            obj, {"desc", "description", "summary", "text", "content"}
        )
        url = cls._find_first_nonempty_by_keys(
            obj,
            {
                "url",
                "jumpurl",
                "qqdocurl",
                "newsurl",
                "docurl",
                "target",
                "link",
            },
        )

        parts = ["[JSON卡片]"]
        if title:
            parts.append(f"标题: {title}")
        if desc and desc != title:
            parts.append(f"摘要: {desc}")
        if url:
            parts.append(f"链接: {url}")

        return " | ".join(parts)

    async def _download_file_to_temp(self, file_url: str, file_name: str) -> str | None:
        safe_name = self._safe_file_name(file_name)
        tmp_dir = os.path.join(tempfile.gettempdir(), "astrbot_qq2tg_files")
        os.makedirs(tmp_dir, exist_ok=True)
        tmp_path = os.path.join(tmp_dir, f"{uuid.uuid4().hex}_{safe_name}")

        def _download() -> str | None:
            req = urllib.request.Request(
                file_url,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            with (
                urllib.request.urlopen(req, timeout=25) as resp,
                open(tmp_path, "wb") as f,
            ):
                total = 0
                while True:
                    chunk = resp.read(1024 * 64)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > self.telegram_upload_max_bytes:
                        raise ValueError("file_too_large")
                    f.write(chunk)

            if os.path.getsize(tmp_path) <= 0:
                return None
            return tmp_path

        try:
            return await asyncio.to_thread(_download)
        except ValueError as exc:
            if str(exc) == "file_too_large":
                logger.info(
                    f"[QQ2TG] 文件超过上限({self.telegram_upload_max_mb}MB)，回退为链接: {safe_name}"
                )
            return None
        except Exception as exc:
            logger.warning(f"[QQ2TG] 下载文件失败，回退为链接: {exc}")
            return None

    async def _resolve_file_url(self, client, source_group_id, file_data: dict) -> str:
        direct_url = file_data.get("url") or file_data.get("file")
        if isinstance(direct_url, str) and direct_url.startswith(
            ("http://", "https://")
        ):
            return direct_url

        file_id = (
            file_data.get("file_id") or file_data.get("id") or file_data.get("fid")
        )
        busid = file_data.get("busid") or file_data.get("bus_id")

        if not client or not source_group_id or not file_id:
            return ""

        try:
            payload = {"group_id": int(source_group_id), "file_id": str(file_id)}
            busid_text = str(busid).strip() if busid is not None else ""
            if busid_text.isdigit():
                payload["busid"] = int(busid_text)

            resp = await client.api.call_action("get_group_file_url", **payload)
            if isinstance(resp, dict):
                url = (
                    resp.get("url")
                    or resp.get("file_url")
                    or (resp.get("data") or {}).get("url")
                )
                if isinstance(url, str) and url.startswith(("http://", "https://")):
                    return url
        except Exception as exc:
            logger.debug(
                f"[QQ2TG] get_group_file_url 失败, data={file_data}, error={exc}"
            )

        return ""

    def _render_message_text(self, message_segments) -> str:
        if not isinstance(message_segments, list):
            return str(message_segments)

        parts = []
        for seg in message_segments:
            if not isinstance(seg, dict):
                parts.append(str(seg))
                continue

            seg_type = seg.get("type")
            data = seg.get("data", {})

            if seg_type == "text":
                parts.append(data.get("text", ""))
            elif seg_type == "at":
                parts.append(f"@{data.get('qq', 'unknown')}")
            elif seg_type == "image":
                parts.append("[图片]")
            elif seg_type == "face":
                parts.append("[表情]")
            elif seg_type == "reply":
                parts.append("[回复]")
            elif seg_type == "file":
                file_name = data.get("name") or data.get("file") or "unknown"
                parts.append(f"[文件:{file_name}]")
            elif seg_type == "record":
                parts.append("[语音]")
            elif seg_type == "video":
                parts.append("[视频]")
            elif seg_type == "forward":
                parts.append("[合并转发]")
            elif seg_type == "json":
                parts.append(self._parse_json_segment_summary(data))
            else:
                parts.append(f"[{seg_type or 'unknown'}]")

        text = " ".join([p for p in parts if p]).strip()
        return text or "[空消息]"

    @staticmethod
    def _format_msg_time(raw_time, fallback: str = "") -> str:
        if isinstance(raw_time, (int, float)):
            try:
                ts = int(raw_time)
                if ts > 0:
                    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
            except Exception:
                pass
        if isinstance(raw_time, str) and raw_time.strip():
            return raw_time.strip()
        return fallback or "未知时间"

    @staticmethod
    def _extract_forward_id(seg_data: dict) -> str:
        for key in ("id", "resid", "forward_id"):
            value = seg_data.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return ""

    async def _call_get_forward_msg(self, client, forward_id: str) -> list:
        if not forward_id:
            return []

        try:
            resp = await client.api.call_action("get_forward_msg", id=forward_id)
            if isinstance(resp, dict) and isinstance(resp.get("messages"), list):
                return resp["messages"]
        except Exception as exc:
            logger.warning(
                f"[QQ2TG] get_forward_msg 失败, id={forward_id}, error={exc}"
            )
        return []

    @staticmethod
    def _extract_node_segments(node: dict):
        if not isinstance(node, dict):
            return []

        for key in ("content", "message", "messages"):
            value = node.get(key)
            if isinstance(value, list):
                return value

        raw_message = node.get("raw_message")
        if isinstance(raw_message, str) and raw_message.strip():
            return [{"type": "text", "data": {"text": raw_message}}]
        return []

    def _extract_node_meta(
        self, node: dict, fallback_name: str, fallback_id, fallback_time: str
    ):
        sender = node.get("sender") if isinstance(node, dict) else None
        if not isinstance(sender, dict):
            sender = {}

        sender_name = (
            sender.get("card")
            or sender.get("nickname")
            or node.get("name")
            or node.get("nickname")
            or fallback_name
            or "未知用户"
        )
        sender_id = (
            sender.get("user_id")
            or node.get("user_id")
            or node.get("uin")
            or fallback_id
            or "未知ID"
        )
        msg_time_str = self._format_msg_time(node.get("time"), fallback=fallback_time)
        return sender_name, sender_id, msg_time_str

    async def _expand_segments_to_entries(
        self,
        client,
        msg_segments,
        sender_name: str,
        sender_id,
        msg_time_str: str,
        depth: int = 0,
    ):
        if depth >= 4:
            return [
                {
                    "msg_content": [
                        {
                            "type": "text",
                            "data": {"text": "[嵌套合并转发层数过多]"},
                        }
                    ],
                    "sender_name": sender_name,
                    "sender_id": sender_id,
                    "msg_time_str": msg_time_str,
                }
            ]

        if not isinstance(msg_segments, list):
            msg_segments = [{"type": "text", "data": {"text": str(msg_segments)}}]

        entries = []
        normal_buffer = []

        def flush_normal_buffer():
            if not normal_buffer:
                return
            entries.append(
                {
                    "msg_content": list(normal_buffer),
                    "sender_name": sender_name,
                    "sender_id": sender_id,
                    "msg_time_str": msg_time_str,
                }
            )
            normal_buffer.clear()

        for seg in msg_segments:
            if (
                isinstance(seg, dict)
                and seg.get("type") == "forward"
                and isinstance(seg.get("data"), dict)
            ):
                flush_normal_buffer()

                forward_id = self._extract_forward_id(seg.get("data", {}))
                child_nodes = await self._call_get_forward_msg(client, forward_id)
                if not child_nodes:
                    entries.append(
                        {
                            "msg_content": [
                                {
                                    "type": "text",
                                    "data": {
                                        "text": f"[合并转发:{forward_id or 'unknown'}]"
                                    },
                                }
                            ],
                            "sender_name": sender_name,
                            "sender_id": sender_id,
                            "msg_time_str": msg_time_str,
                        }
                    )
                    continue

                for node in child_nodes:
                    if not isinstance(node, dict):
                        continue

                    node_sender_name, node_sender_id, node_time_str = (
                        self._extract_node_meta(
                            node=node,
                            fallback_name=sender_name,
                            fallback_id=sender_id,
                            fallback_time=msg_time_str,
                        )
                    )
                    node_segments = self._extract_node_segments(node)

                    if not node_segments:
                        entries.append(
                            {
                                "msg_content": [
                                    {"type": "text", "data": {"text": "[空消息]"}}
                                ],
                                "sender_name": node_sender_name,
                                "sender_id": node_sender_id,
                                "msg_time_str": node_time_str,
                            }
                        )
                        continue

                    nested_entries = await self._expand_segments_to_entries(
                        client=client,
                        msg_segments=node_segments,
                        sender_name=node_sender_name,
                        sender_id=node_sender_id,
                        msg_time_str=node_time_str,
                        depth=depth + 1,
                    )
                    entries.extend(nested_entries)
                continue

            normal_buffer.append(seg)

        flush_normal_buffer()

        if entries:
            return entries

        return [
            {
                "msg_content": [{"type": "text", "data": {"text": "[空消息]"}}],
                "sender_name": sender_name,
                "sender_id": sender_id,
                "msg_time_str": msg_time_str,
            }
        ]

    @staticmethod
    def _escape_markdown(text: str) -> str:
        if not isinstance(text, str):
            return ""
        escape_chars = r"_*[]()~`>#+-=|{}.!"
        out = []
        for ch in text:
            if ch in escape_chars:
                out.append("\\" + ch)
            else:
                out.append(ch)
        return "".join(out)

    async def _build_forward_chain(
        self,
        msg_content,
        source_group_name: str,
        source_group_id,
        source_group_id_raw,
        sender_name: str,
        sender_id,
        msg_time_str: str,
        client=None,
    ):
        safe_group = self._escape_markdown(str(source_group_name))
        safe_group_id = self._escape_markdown(str(source_group_id))
        safe_sender = self._escape_markdown(str(sender_name))
        safe_sender_id = self._escape_markdown(str(sender_id))
        safe_time = self._escape_markdown(str(msg_time_str))

        header_markdown = (
            "*QQ -> Telegram 转发*\n"
            f"*来源群*: `{safe_group}` (`{safe_group_id}`)\n"
            f"*发送者*: `{safe_sender}` (`{safe_sender_id}`)\n"
            f"*时间*: `{safe_time}`\n"
        )

        chains = [Comp.Plain(header_markdown)]
        temp_files = []
        text_parts = []

        if not isinstance(msg_content, list):
            msg_content = [
                {
                    "type": "text",
                    "data": {"text": str(msg_content)},
                }
            ]

        for seg in msg_content:
            if not isinstance(seg, dict):
                text_parts.append(str(seg))
                continue

            seg_type = seg.get("type")
            data = seg.get("data", {})

            if seg_type == "text":
                txt = data.get("text", "")
                if txt:
                    text_parts.append(txt)
                continue

            if seg_type == "at":
                text_parts.append(f"@{data.get('qq', 'unknown')}")
                continue

            if seg_type == "reply":
                text_parts.append("[回复]")
                continue

            if seg_type == "image":
                image_url = data.get("url") or data.get("file")
                if isinstance(image_url, str) and image_url.startswith(
                    ("http://", "https://")
                ):
                    chains.append(Comp.Image.fromURL(image_url))
                else:
                    text_parts.append("[图片]")
                continue

            if seg_type == "file":
                file_url = await self._resolve_file_url(
                    client=client,
                    source_group_id=source_group_id_raw,
                    file_data=data,
                )
                file_name = self._pick_file_name(data)
                if isinstance(file_url, str) and file_url.startswith(
                    ("http://", "https://")
                ):
                    fixed_url = self._ensure_fname_in_url(file_url, file_name)
                    if self.telegram_upload_files:
                        local_path = await self._download_file_to_temp(
                            fixed_url, file_name
                        )
                        if local_path:
                            temp_files.append(local_path)
                            chains.append(Comp.File(file=local_path, name=file_name))
                        else:
                            text_parts.append(f"[文件:{file_name}] {fixed_url}")
                    else:
                        text_parts.append(f"[文件:{file_name}] {fixed_url}")
                else:
                    text_parts.append(f"[文件:{file_name}]")
                continue

            if seg_type == "video":
                text_parts.append("[视频]")
                continue

            if seg_type == "record":
                text_parts.append("[语音]")
                continue

            if seg_type == "face":
                text_parts.append("[表情]")
                continue

            if seg_type == "json":
                text_parts.append(self._parse_json_segment_summary(data))
                continue

            text_parts.append(f"[{seg_type or 'unknown'}]")

        body = " ".join([x for x in text_parts if x]).strip()
        if body:
            chains.append(Comp.Plain(body))
        elif len(chains) == 1:
            chains.append(Comp.Plain("[空消息]"))

        return chains, temp_files

    @filter.command("qq2tg_show_umo")
    async def qq2tg_show_umo(self, event: AstrMessageEvent):
        yield event.plain_result(
            f"当前会话 unified_msg_origin:\n{event.unified_msg_origin}\n"
            f"平台: {event.get_platform_name()}"
        )

    @filter.command("qq2tg_bind_target")
    async def qq2tg_bind_target(self, event: AstrMessageEvent):
        platform = event.get_platform_name()
        if platform != "telegram":
            yield event.plain_result("请在 Telegram 目标聊天中执行此命令。")
            return

        umo = event.unified_msg_origin
        if umo not in self.telegram_target_unified_origins:
            self.telegram_target_unified_origins.append(umo)

        yield event.plain_result(
            "已绑定当前 Telegram 会话为转发目标(仅本次运行生效)。\n"
            f"请把下面这一项写入插件配置 telegram_target_unified_origins:\n{umo}"
        )

    @filter.platform_adapter_type(PlatformAdapterType.AIOCQHTTP)
    async def handle_message(self, event: AstrMessageEvent):
        group_id = event.message_obj.group_id
        msg_id = event.message_obj.message_id
        is_source = self._is_source_group(group_id)

        logger.info(
            f"[QQ2TG][ID:{self.instance_id}] 收到 QQ 消息 id={msg_id}, group={group_id}, in_source={is_source}"
        )

        if is_source:
            if self._is_queryable_message_id(msg_id):
                await self.local_cache.add_cache(msg_id, group_id=group_id)
            else:
                logger.debug(f"[QQ2TG] 跳过不可查询消息ID: {msg_id}")

        has_pending = await self.local_cache.has_pending_messages()
        if has_pending and not self.forward_lock.locked():
            await self._execute_forward_and_cool(event)

        if self.block_source_messages and is_source:
            return MessageEventResult(None)
        return None

    async def _execute_forward_and_cool(self, event: AstrMessageEvent):
        client = event.bot
        self._forward_task = asyncio.current_task()

        try:
            cleaned = await self.local_cache._cleanup_expired_cache()
            if cleaned:
                logger.info(
                    f"[QQ2TG][ID:{self.instance_id}] 清理过期缓存: {cleaned} 条"
                )

            async with self.forward_lock:
                while True:
                    waiting_messages = await self.local_cache.get_waiting_messages()
                    if not waiting_messages:
                        if await self.local_cache.has_pending_messages():
                            earliest = await self.local_cache.get_earliest_timestamp()
                            if earliest:
                                wait_time = self.banshi_waiting_time - (
                                    time.time() - earliest
                                )
                                if wait_time > 0:
                                    await asyncio.sleep(wait_time + 0.1)
                                continue
                        break

                    for msg_id in waiting_messages:
                        earliest_timestamp_limit = (
                            time.time() - self.banshi_cache_seconds
                        )
                        try:
                            msg_detail = await client.api.call_action(
                                "get_msg", message_id=msg_id
                            )
                        except Exception as exc:
                            logger.warning(
                                f"[QQ2TG] get_msg 失败, id={msg_id}, error={exc}"
                            )
                            await self.local_cache.remove_cache(msg_id)
                            continue

                        msg_time = msg_detail.get("time", 0)
                        msg_content = msg_detail.get("message", [])
                        if msg_time < earliest_timestamp_limit or not msg_content:
                            await self.local_cache.remove_cache(msg_id)
                            continue

                        if not self.telegram_target_unified_origins:
                            logger.warning(
                                "[QQ2TG] telegram_target_unified_origins 为空，跳过转发。"
                            )
                            await self.local_cache.remove_cache(msg_id)
                            continue

                        sender_info = msg_detail.get("sender", {})
                        sender_name = (
                            sender_info.get("card")
                            or sender_info.get("nickname")
                            or "未知用户"
                        )
                        sender_id = sender_info.get("user_id", "未知ID")
                        cached_group_id = await self.local_cache.get_message_group_id(
                            msg_id
                        )
                        origin_group_id = (
                            msg_detail.get("group_id")
                            or cached_group_id
                            or sender_info.get("group_id")
                        )
                        origin_group_id_text = (
                            str(origin_group_id) if origin_group_id else "未知群号"
                        )
                        source_group_name = "未知群"

                        if origin_group_id:
                            try:
                                group_info = await client.api.call_action(
                                    "get_group_info",
                                    group_id=int(origin_group_id),
                                    no_cache=False,
                                )
                                source_group_name = group_info.get(
                                    "group_name", source_group_name
                                )
                            except Exception:
                                pass

                        msg_time_str = self._format_msg_time(msg_time)
                        entry_list = await self._expand_segments_to_entries(
                            client=client,
                            msg_segments=msg_content,
                            sender_name=sender_name,
                            sender_id=sender_id,
                            msg_time_str=msg_time_str,
                        )

                        for entry in entry_list:
                            chains, temp_files = await self._build_forward_chain(
                                msg_content=entry["msg_content"],
                                source_group_name=source_group_name,
                                source_group_id=origin_group_id_text,
                                source_group_id_raw=origin_group_id,
                                sender_name=entry["sender_name"],
                                sender_id=entry["sender_id"],
                                msg_time_str=entry["msg_time_str"],
                                client=client,
                            )

                            for target_umo in self.telegram_target_unified_origins:
                                try:
                                    message_chain = MessageChain()
                                    message_chain.chain = list(chains)
                                    await self.context.send_message(
                                        target_umo, message_chain
                                    )
                                    logger.info(
                                        f"[QQ2TG] 转发成功: msg={msg_id} -> {target_umo}"
                                    )
                                except Exception as exc:
                                    logger.error(
                                        f"[QQ2TG] 转发失败: msg={msg_id} -> {target_umo}, error={exc}"
                                    )
                                await asyncio.sleep(0.2)

                            for temp_path in temp_files:
                                try:
                                    if temp_path and os.path.exists(temp_path):
                                        os.remove(temp_path)
                                except Exception:
                                    pass

                        await self.local_cache.remove_cache(msg_id)
                        interval = self._get_banshi_interval_dynamic()
                        await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.warning(f"[QQ2TG][ID:{self.instance_id}] 转发任务被取消")
            raise
        finally:
            self._forward_task = None

    async def terminate(self):
        try:
            if self._forward_task and not self._forward_task.done():
                self._forward_task.cancel()
        except Exception as exc:
            logger.error(f"[QQ2TG][ID:{self.instance_id}] terminate 失败: {exc}")
