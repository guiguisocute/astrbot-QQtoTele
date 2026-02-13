# AstrBot QQ -> Telegram Forward

把 QQ 群消息转发到 Telegram，同时可选本地 Markdown 归档。

## 功能

- 监听 `banshi_group_list` 中的 QQ 群消息
- 支持双通道输出：Telegram 转发 + Markdown 归档（可分别开关）
- Telegram 支持多个目标会话
- 兼容图片、文件处理（依赖 QQ 消息中可用的 URL）
- 可展开合并转发消息，按条输出
- 可选屏蔽源群内机器人回复

## 配置项

- `banshi_group_list`: QQ 来源群号列表
- `telegram_target_unified_origins`: Telegram 目标会话列表
  - 每项形如 `telegram:group_message:<chat_id>` 或 `telegram:private_message:<chat_id>`
- `enable_telegram_forward`: 是否启用 Telegram 转发通道（默认 `true`）
- `enable_markdown_archive`: 是否启用 Markdown 归档通道（默认 `true`）
- `archive_root`: Markdown 归档根目录（容器内路径，默认 `/AstrBot/data/qq2tg_archive`）
- `archive_save_assets`: 是否下载并保存归档附件（默认 `true`）
- `archive_asset_max_mb`: 归档附件下载大小上限 MB（默认 `20`）
- `telegram_upload_files`: 是否下载 QQ 文件并重新上传 Telegram（默认开启）
- `telegram_upload_max_mb`: 上传文件大小上限，超限回退为链接（默认 10）
- `banshi_waiting_time`: 缓存后等待多少秒再转发
- `banshi_cache_seconds`: 缓存最大保留时长
- `banshi_cooldown_day_seconds`: 白天转发冷却秒数
- `banshi_cooldown_night_seconds`: 夜间转发冷却秒数
- `banshi_cooldown_day_start`: 白天开始时间（HH:MM）
- `banshi_cooldown_night_start`: 夜间开始时间（HH:MM）
- `block_source_messages`: 是否屏蔽源群消息

## 快速配置

1. 在 AstrBot 里创建并启用 QQ 和 Telegram 平台适配器。
2. 在 Telegram 目标群或私聊发送命令 `/qq2tg_show_umo`，拿到当前会话 `unified_msg_origin`。
3. 把拿到的值填进插件配置 `telegram_target_unified_origins`。
4. 把需要监听的 QQ 群号填进 `banshi_group_list`。
5. 若启用归档，设置 `archive_root` 为容器内可写路径（如 `/workspace/JXNU-PUBLISH/archive`）。
6. 保存插件配置并重载插件。

## 示例配置

```json
{
  "banshi_group_list": [
    "123456789"
  ],
  "enable_telegram_forward": true,
  "enable_markdown_archive": true,
  "telegram_target_unified_origins": [
    "telegram:group_message:-1001234567890"
  ],
  "archive_root": "/workspace/JXNU-PUBLISH/archive",
  "archive_save_assets": true,
  "archive_asset_max_mb": 20,
  "banshi_waiting_time": 2,
  "banshi_cache_seconds": 3600,
  "banshi_cooldown_day_seconds": 30,
  "banshi_cooldown_night_seconds": 60,
  "banshi_cooldown_day_start": "09:00",
  "banshi_cooldown_night_start": "01:00",
  "block_source_messages": false
}
```

## 归档目录结构

当启用 `enable_markdown_archive` 后，默认按天写入：

```text
archive/
  2026-02-13/
    messages.md
    files/
    photos/
  index/
    message_ids.json
```

- `messages.md`: 每条消息一个块，包含时间、来源群、发送者、正文、附件。
- `files/` `photos/`: 保存下载成功的附件；下载失败或超限时回退为链接记录。
- `index/message_ids.json`: 消息去重索引，避免重复写入。

## 辅助命令

- `/qq2tg_show_umo`: 显示当前会话的 `unified_msg_origin`
- `/qq2tg_show_archive`: 显示当前输出通道状态与归档目录
- `/qq2tg_bind_target`: 在 Telegram 中执行，把当前会话加入内存目标列表并回显可写入配置的值

注意：`/qq2tg_bind_target` 仅在当前进程内生效，重启后仍需以配置文件为准。
