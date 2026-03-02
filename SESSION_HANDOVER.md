# AstrBot 重构会话交接总结（2026-02-13）

## 本次讨论结论

- 现有方案是 QQ -> Telegram 转发，但受 Telegram bot-to-bot 限制影响，继续以 TG 作为中转不理想。
- 新方向确定为：直接从 QQ 侧提取消息并落地为 Markdown 聊天归档，不再依赖 Telegram 二次转发。
- 归档目标目录风格参考 Telegram 导出结构（按日期分目录/分文件）。

## 已确认的技术可行性

- 已确认容器可访问并写入宿主机目录。
- 目标宿主机目录：
  - `/opt/1panel/apps/openclaw/openclaw/data/workspace/JXNU-PUBLISH`
- AstrBot 容器内挂载点：
  - `/workspace/JXNU-PUBLISH`
- 挂载类型：本机目录（bind mount），权限：读写（rw）。
- 验证命令与结果：

```bash
ls -la /workspace/JXNU-PUBLISH
touch /workspace/JXNU-PUBLISH/.astrbot_write_test && ls -l /workspace/JXNU-PUBLISH/.astrbot_write_test && rm /workspace/JXNU-PUBLISH/.astrbot_write_test
```

- 写入测试成功（文件显示为 `root:root`），说明容器当前以 root 用户写文件。

## 数据样本与格式观察

- 用户提供了 Telegram 导出目录：`ChatExport_2026-02-13 (1)`。
- 核心样本文件：`ChatExport_2026-02-13 (1)/result.json`。
- 已观察到字段类型包含：
  - 文本消息：`text` / `text_entities`
  - 图片：`photo`
  - 文件：`file` / `file_name` / `mime_type` / `file_size`
- 现有转发结果在导出中表现为“头信息 + 正文/附件拆分多条”，进一步支持“直接归档”方案更干净。

## 拟定重构方向（尚未开始改代码）

- 引入输出模式配置：`telegram`（兼容旧逻辑）与 `markdown_archive`（新逻辑）。
- 新增归档配置建议：
  - `archive_root`（例：`/workspace/JXNU-PUBLISH/archive`）
  - `archive_split`（按天）
  - `archive_save_assets`（是否保存附件）
- 归档目录建议：
  - `archive/YYYY-MM-DD/messages.md`
  - `archive/YYYY-MM-DD/files/...`
  - `archive/YYYY-MM-DD/photos/...`
  - `archive/index/message_ids.json`（去重索引）
- 复用现有消息解析逻辑（含合并转发展开），仅替换最终输出端（从发 TG 改为写 MD）。

## 下一步待办（新会话继续）

1. 先实现最小可用版本：文本与元信息写入 `messages.md`。
2. 再实现附件落地与相对路径链接（files/photos）。
3. 加入去重索引（按 `group_id + message_id`）。
4. 更新 README 与 `_conf_schema.json` 配置说明。
5. 最后做真实消息回归测试（文本/图片/文件/json 卡片）。

## 备注

- 当前工作区也存在插件仓库 `astrbot-QQtoTele`，本次只是讨论与可行性验证，尚未对业务代码做改动。
- 若后续在宿主机以普通用户维护文件，建议尽早统一容器运行用户 UID/GID，避免归档文件权限不一致。
