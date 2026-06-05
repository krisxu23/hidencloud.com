# hidencloud.com


根据 yml 和 main.py，需要填的 Secrets：

| Secret | 说明 | 示例 |
|---|---|---|
| `ACCOUNTS` | 账号密码，多账号换行分隔 | `foo@mail.com---pass123` |
| `XRAY_CONFIG_JSON` | Xray 完整配置 JSON | `{"inbounds":[...],...}` |
| `TG_BOT_TOKEN` | Telegram Bot Token | `123456:ABCdef...` |
| `TG_CHAT_ID` | Telegram 聊天 ID | `123456789` |
| `GH_TOKEN` | GitHub Personal Access Token，需要 `repo` 写权限（用于写回 cron） | `ghp_xxxx...` |

`TG_BOT_TOKEN` 和 `TG_CHAT_ID` 不填也能跑，只是没有通知。
