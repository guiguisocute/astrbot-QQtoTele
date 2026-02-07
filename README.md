# AstrBot QQ -> Telegram Forward

把 QQ 群消息转发到 Telegram 聊天。

## 功能

- 监听 `banshi_group_list` 中的 QQ 群消息
- 按等待时间和冷却时间转发到 Telegram
- 支持多个 Telegram 目标会话
- 兼容图片、文件转发（依赖 QQ 消息中可用的 URL）
- 转发头使用 Markdown 风格文本
- 可选屏蔽源群内机器人回复

## 配置项

- `banshi_group_list`: QQ 来源群号列表
- `telegram_target_unified_origins`: Telegram 目标会话列表
  - 每项形如 `telegram:group_message:<chat_id>` 或 `telegram:private_message:<chat_id>`
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
5. 保存插件配置并重载插件。

## 示例配置

```json
{
  "banshi_group_list": [
    "123456789"
  ],
  "telegram_target_unified_origins": [
    "telegram:group_message:-1001234567890"
  ],
  "banshi_waiting_time": 2,
  "banshi_cache_seconds": 3600,
  "banshi_cooldown_day_seconds": 30,
  "banshi_cooldown_night_seconds": 60,
  "banshi_cooldown_day_start": "09:00",
  "banshi_cooldown_night_start": "01:00",
  "block_source_messages": false
}
```

## 辅助命令

- `/qq2tg_show_umo`: 显示当前会话的 `unified_msg_origin`
- `/qq2tg_bind_target`: 在 Telegram 中执行，把当前会话加入内存目标列表并回显可写入配置的值

注意：`/qq2tg_bind_target` 仅在当前进程内生效，重启后仍需以配置文件为准。
