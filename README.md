# HidenCloud Auto Renew 配置说明

## 必须配置的 Secrets

前往仓库 **Settings → Secrets and variables → Actions → New repository secret** 添加。

| Secret 名称 | 必填 | 说明 | 示例 |
|---|---|---|---|
| `GH_TOKEN` | ✅ | Personal Access Token，用于每日自动更新 cron 时间写回仓库。需勾选 `repo` + `workflow` 权限 | `ghp_xxxxxxxxxxxx` |
| `ACCOUNTS` | ✅ | HidenCloud 账号，格式 `邮箱---密码`，多账号用换行分隔 | `a@example.com---pass123` |
| `TG_BOT_TOKEN` | ⬜ | Telegram Bot Token，不填则不发通知 | `123456:ABCdef...` |
| `TG_CHAT_ID` | ⬜ | Telegram 接收通知的 Chat ID，不填则不发通知 | `123456789` |
| `PROXY_NODE` | ⬜ | 代理节点，不填直连。支持多行，每行一条，自动逐个重试 | 见下方说明 |

---

## ACCOUNTS 格式

单账号：
```
邮箱---密码
```

多账号（换行或逗号分隔均可）：
```
aaa@example.com---password1
bbb@example.com---password2
```

---

## PROXY_NODE 格式

不需要代理可以不填，脚本自动直连。

支持以下协议，每行填一条节点 URL，多条时自动逐个尝试直到连通为止：

```
vless://uuid@host:port?...
vmess://base64encoded...
trojan://password@host:port?...
ss://base64encoded@host:port
socks5://user:pass@host:port
```

以 `#` 开头的行视为注释，空行自动忽略。

---

## GH_TOKEN 申请步骤

1. GitHub 右上角头像 → **Settings**
2. 左侧底部 **Developer settings → Personal access tokens → Tokens (classic)**
3. **Generate new token (classic)**
4. 勾选权限：`repo`（全部）、`workflow`
5. 生成后复制，填入 Secret `GH_TOKEN`

> ⚠️ Token 只显示一次，请立即保存。

---

## 文件部署

将以下两个文件放入仓库对应路径：

```
仓库根目录/
├── main.py                                   ← 续期脚本
└── .github/
    └── workflows/
        └── hidencloud-auto-renew.yml         ← Workflow 文件
```

> ⚠️ Workflow 文件名必须是 `hidencloud-auto-renew.yml`，脚本内部自动更新 cron 时依赖此文件名。

---

## 运行逻辑

```
每日随机时间触发（北京时间 1~7 点之间）
        ↓
恢复缓存（浏览器 Profile + Cookie）
        ↓
启动代理（有 PROXY_NODE 则尝试节点，全败则直连）
        ↓
运行 main.py
  ├─ 尝试 Cookie 登录
  │    成功 → 直接续期
  │    失败 → 密码登录 → 保存 Cookie
  └─ 逐个服务续期，结果发 Telegram 通知
        ↓
保存缓存
        ↓
随机生成明日执行时间并写回 Workflow 文件
```

---

## 手动触发

仓库 **Actions → HidenCloud Auto Renew → Run workflow** 即可立即执行一次。
