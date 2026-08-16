# TRAE Work Tools

[English](#english) · [中文](#中文)

Automated daily check-in for **TRAE Work (China)**, plus credit-usage monitoring
and desktop/phone notifications. Runs entirely via the TRAE API — no UI clicks,
no need to keep your computer on. Deploy once on any always-on machine
(e.g. a cloud server) and it claims your 200 daily Work credits for you.

**TRAE Work（中国版）自动签到工具**：纯 API 实现每日自动签到领取 200 Work 积分，
同时监控每日积分消耗并在超额时通过手机（Server酱）和电脑桌面弹窗提醒。
无需开启客户端、无需人工点击，部署到任何常驻机器（如云服务器）即可。

---

## English

### Features

- **Daily auto check-in** — claims today's 200 Work credits via API every day
- **Auto token refresh** — keeps the access token alive using the refresh-token flow
- **Daily usage monitoring** — shows exactly how many credits were consumed today,
  per-session (which model, when, how much, with a message preview)
- **Over-threshold alert** — when daily consumption exceeds a configurable limit,
  a **high-priority desktop popup** is shown (prominent style + sound + no dedupe)
- **Notifications** — daily results pushed to your phone via [Server酱](https://sct.ftqq.com)
  and written to a file for your PC to pull

### Architecture

```
[Cloud server / any always-on machine]
  trae_checkin.py  ──►  TRAE API (api.trae.cn)
        │   daily check-in + usage fetch
        ├──► Server酱 push ──► phone
        ├──► pc_notice.txt ──────────┐
        └──► pc_alert.txt (if over threshold) ─┐
                                           │
[Your PC]  trae_remind_pc.py ◄───────────┘ (SSH pull, desktop toast)
```

### Files

| File | Purpose |
|------|---------|
| `trae_checkin.py` | Main script: refresh token, check in, fetch usage, send alerts. Runs on the server. |
| `trae_remind_pc.py` | Windows-side puller: SSH-fetches notice/alert files and shows desktop toasts. |
| `make_config.py` | Generates `trae_config.json` from your local TRAE credentials. |
| `capture_addon.py` / `cdp_capture.py` | Optional dev helpers for capturing TRAE web API traffic. |

### Quick start

1. **Generate your config** (run on the machine where TRAE Work is logged in):

   ```bash
   python make_config.py
   ```

   This writes `trae_config.json` containing your device credentials and tokens.

2. **Set the Server酱 key** (optional, for phone push) in `trae_config.json`:

   ```json
   {
     "server_key": "SCT12345...",
     "daily_consumption_alert_threshold": 200
   }
   ```

3. **Test**:

   ```bash
   python trae_checkin.py --test    # test push, no real check-in
   ```

4. **Run daily** (e.g. cron at 08:30):

   ```bash
   cd /path/to/trae-work-tools && python trae_checkin.py
   ```

5. **On your PC**, run `trae_remind_pc.py` periodically (Task Scheduler, every 6h)
   to receive desktop popups. Edit the SSH server host/user/password at the top
   of the file first.

### CLI

```
python trae_checkin.py            # normal run (check in + notify)
python trae_checkin.py --test     # test push only
python trae_checkin.py --refresh  # force token refresh, then exit
python trae_checkin.py -c path    # custom config path
```

### Security

`trae_config.json` contains your tokens, keys and device secrets — **never commit it**.
It is excluded via `.gitignore`. Re-generate it with `make_config.py` whenever the
refresh token expires.

### Disclaimer

This project calls public TRAE APIs for personal automation. Use at your own risk;
the author is not responsible for any account actions. Check TRAE's terms of service.

---

## 中文

### 功能

- **每日自动签到** — 每天通过 API 领取 200 Work 积分
- **自动刷新 token** — 使用 refresh-token 流程保持 access token 长期有效
- **每日用量监控** — 精确显示今日消耗了多少积分，按会话列出（模型、时间、消耗量、对话预览）
- **超额告警** — 当日消耗超过可配置阈值时，电脑桌面弹出**高优先级提醒**（醒目样式 + 提示音 + 强制弹出）
- **多端通知** — 每日结果通过 [Server酱](https://sct.ftqq.com) 推送到手机，同时写入文件供电脑端拉取

### 架构

```
[云服务器 / 任意常驻机器]
  trae_checkin.py  ──►  TRAE API (api.trae.cn)
        │   每日签到 + 用量拉取
        ├──► Server酱推送 ──► 手机
        ├──► pc_notice.txt ──────────┐
        └──► pc_alert.txt（超阈值时） ─┐
                                       │
[你的电脑]  trae_remind_pc.py ◄────────┘ (SSH 拉取，桌面弹窗)
```

### 文件说明

| 文件 | 用途 |
|------|------|
| `trae_checkin.py` | 主脚本：刷新 token、签到、拉取用量、发送告警。部署在服务器。 |
| `trae_remind_pc.py` | 电脑端拉取脚本：通过 SSH 拉取通知/告警文件并弹桌面通知。 |
| `make_config.py` | 从本地 TRAE 凭证生成 `trae_config.json`。 |
| `capture_addon.py` / `cdp_capture.py` | 可选的抓包开发辅助工具。 |

### 快速开始

1. **生成配置**（在 TRAE Work 已登录的电脑上运行）：

   ```bash
   python make_config.py
   ```

   会生成包含设备凭证和 token 的 `trae_config.json`。

2. **设置 Server酱 key**（可选，用于手机推送）写入 `trae_config.json`：

   ```json
   {
     "server_key": "SCT12345...",
     "daily_consumption_alert_threshold": 200
   }
   ```

3. **测试**：

   ```bash
   python trae_checkin.py --test    # 测试推送，不执行真实签到
   ```

4. **每日运行**（例如 cron 每天 08:30）：

   ```bash
   cd /path/to/trae-work-tools && python trae_checkin.py
   ```

5. **电脑端**：将 `trae_remind_pc.py` 加入计划任务（如每 6 小时），即可收到桌面弹窗。
   首次使用请修改文件顶部的 SSH 服务器地址、账号和密码。

### 命令行

```
python trae_checkin.py            # 正常运行（签到 + 通知）
python trae_checkin.py --test     # 仅测试推送
python trae_checkin.py --refresh  # 强制刷新 token 后退出
python trae_checkin.py -c path    # 指定配置文件路径
```

### 安全说明

`trae_config.json` 包含你的 token、密钥和设备凭证 — **切勿提交**。已通过 `.gitignore`
排除。当 refresh token 过期时，用 `make_config.py` 重新生成即可。

### 免责声明

本项目调用公开的 TRAE API 用于个人自动化。请自行承担使用风险，作者不对任何账号行为负责。
请遵守 TRAE 的服务条款。