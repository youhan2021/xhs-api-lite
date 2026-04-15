---
name: xhs-api-lite
description: 小红书自动化发布工具 — 自包含实现，无外部依赖。登录态管理、预览发草稿、直接发布，支持 CLI 调用和 skill workflow
triggers:
  - "发小红书"
  - "发布小红书"
  - "小红书发布"
  - "xhs post"
  - "xhs publish"
---

# XHS API Lite — 小红书发布 Skill

> **完全自包含实现**，不依赖 xhs_ai_publisher 项目。所有逻辑自行重写，仅依赖 `playwright` 库。

---

## 能力范围

| 能力 | 支持情况 |
|------|----------|
| 登录态保存/复用 | ✅ |
| 手机号+短信验证码登录 | ✅ |
| 预览发草稿（auto_publish=False） | ✅ |
| 直接发布（auto_publish=True） | ✅ |
| 多图上传（封面必须第一张） | ✅ |
| 无头模式（headless） | ✅ |

---

## 工作流程

```
输入：标题 + 正文 + 图片路径列表
     ↓
检查 ~/.xhs_system/ 登录态
     ↓（有登录态）
启动浏览器，复用 storage_state
     ↓（无登录态）
CLI 引导手机号登录 → 保存登录态
     ↓
访问 creator.xiaohongshu.com/new/home
     ↓
填写标题 + 正文 + 上传图片
     ↓
[auto_publish=false] → 截图 → 浏览器保持打开等你确认发布
[auto_publish=true]  → 自动点发布 → 关闭浏览器
```

---

## 环境要求

- Python 3.8+
- `playwright`：`pip install playwright && python -m playwright install chromium`
- Chromium（由 playwright 自动管理，或使用 `~/.xhs_system/ms-playwright/` 下的缓存）

---

## 快速开始

### 1. 检查登录状态

```bash
python3 ~/.hermes/skills/xhs-api-lite/scripts/xhs_api.py status
```

### 2. 手机号登录（两阶段，推荐）

**阶段一：启动登录脚本发送验证码（必须 xvfb-run）**
```bash
nohup xvfb-run -a python3 -u ~/.hermes/skills/xhs-api-lite/scripts/xhs_api.py login \
  --phone 13800138000 > /tmp/xhs_login.log 2>&1 &
echo "PID=$!"
sleep 40 && cat /tmp/xhs_login.log
# 看到"已点击获取验证码"后进行阶段二
```

**阶段二：收到验证码后写入队列文件**
```bash
echo '6位验证码' > ~/.xhs_system/xhs_sms_queue.txt
sleep 10 && cat /tmp/xhs_login.log
```

> 如果日志显示"无法自动填写验证码"但队列文件被成功读取，说明验证码 input
> 选择器已失效（小红书 UI 频繁更新导致）。改用 browser 工具手动完成剩余步骤：
> 1. `browser_navigate` → https://creator.xiaohongshu.com/login
> 2. `browser_type` 手机号（ref=e3）→ `browser_click` 发送验证码
> 3. 收到短信后 `browser_type` 填入验证码（ref=e4）→ `browser_click` 登录
> 4. 登录成功后备份会话：
>    `cp ~/.xhs_system/xhs_storage_state.json ~/.xhs_system/xhs_storage_state.json.bak`

**已知坑：**
- `input()` 在 nohup 后台进程里无法读取，必须用文件队列
- 小红书 UI 更新会导致 SMS input 选择器失效，需切换 browser 工具手动填
- 登录态会过期，过期后需重新 login

### 3. 预览发草稿（默认方式）

```bash
python3 ~/.hermes/skills/xhs-api-lite/scripts/xhs_api.py publish \
  --title "你的笔记标题" \
  --content "正文内容..." \
  --images ~/.hermes/research/imgs/cover.png \
           ~/.hermes/research/imgs/page1.png \
           ~/.hermes/research/imgs/page2.png
```

浏览器打开，内容自动填入，**停在发布确认页**，你去手动点发布。`--auto-publish false`（默认）时适用。

### 4. 直接发布（无人值守）

```bash
python3 ~/.hermes/skills/xhs-api-lite/scripts/xhs_api.py publish \
  --title "你的笔记标题" \
  --content "正文内容..." \
  --images ~/.hermes/research/imgs/cover.png \
           ~/.hermes/research/imgs/page1.png \
  --auto-publish true
```

⚠️ 首次发帖建议用预览模式确认格式无误。

---

## 与 rednote-post 的配合

```
rednote-post skill
    ↓ 生成封面图 + 内容页图（输出路径列表）
    ↓
xhs-api-lite skill
    ↓ 填入标题 + 正文 + 图片
    ↓ 预览发草稿 / 直接发布
```

典型 workflow：
```bash
# 1. 用 rednote-post 生成图文，得到图片路径
# 2. 调用 xhs-api-lite 发布
python3 ~/.hermes/skills/xhs-api-lite/scripts/xhs_api.py publish \
  --title "日本40%企业AI导入率背后的结构性问题" \
  --content "约40%的日本企业还没有制定AI导入计划..." \
  --images ~/.hermes/research/imgs/cover.png \
           ~/.hermes/research/imgs/page1.png \
           ~/.hermes/research/imgs/page2.png \
  --auto-publish false
```

---

## 存储文件

| 文件 | 内容 |
|------|------|
| `~/.xhs_system/xhs_storage_state.json` | 浏览器完整 storage_state（登录态主文件） |
| `~/.xhs_system/xhs_cookies.json` | cookies 备份 |
| `~/.xhs_system/xhs_settings.json` | 手机号等配置 |
| `~/.xhs_system/preview_*.png` | 预览截图（auto_publish=false 时生成） |

---

## ⚠️ 关键：必须用 xvfb-run 包装

**所有命令（login / publish）都必须用 `xvfb-run` 包装**，否则 Playwright 启动 headed Chromium 时会报错 `Missing X server or $DISPLAY`：

```bash
# ✅ 正确：xvfb-run 包装
xvfb-run -a python3 ~/.hermes/skills/xhs-api-lite/scripts/xhs_api.py login --phone 13800138000
xvfb-run -a python3 ~/.hermes/skills/xhs-api-lite/scripts/xhs_api.py publish --title "..." --content "..." --images ...

# ❌ 错误：直接运行，无 DISPLAY 时必败
python3 ~/.hermes/skills/xhs-api-lite/scripts/xhs_api.py login --phone 13800138000
```

推荐 nohup 方式（后台运行，验证码通过文件队列写入）：
```bash
nohup xvfb-run -a python3 -u ~/.hermes/skills/xhs-api-lite/scripts/xhs_api.py \
  login --phone 13800138000 > /tmp/xhs_login.log 2>&1 &
echo "PID=$!"
```

## 验证码输入：后台运行模式

`login` 命令使用 nohup 启动，**不支持 `input()` 读 stdin**，改为文件轮询：

```
~/.xhs_system/xhs_sms_queue.txt
```

登录流程启动后：
1. 收到短信验证码
2. 执行 `echo '验证码' > ~/.xhs_system/xhs_sms_queue.txt`
3. 脚本每 3 秒检查一次，写入后自动继续

---

## 常见问题

### 1. 提示"需要登录"

```bash
python3 ~/.hermes/skills/xhs-api-lite/scripts/xhs_api.py status
```
无登录态则先运行 `login` 命令。

### 2. 浏览器被小红书风控拦截

登录时遇到滑块/设备验证：
- 先手动在 GUI 浏览器登录一次 `creator.xiaohongshu.com`
- 再运行 `login` 命令，登录态会被复用

### 3. 上传图片失败

- 图片格式：JPG/PNG/JPEG/WEBP
- 单张不超过 5MB
- 第一张图必须为封面
- 图片路径不要有中文或特殊字符

### 4. 标题/正文没有自动填入

小红书 UI 改版导致选择器失效。用 `--auto-publish false` 预览，手动补充填写后发布。发现新选择器请回报。

### 5. Playwright 浏览器找不到

```bash
PLAYWRIGHT_BROWSERS_PATH="$HOME/.xhs_system/ms-playwright" \
  python3 -m playwright install chromium
```

---

## Skill 架构

```
~/.hermes/skills/xhs-api-lite/
├── SKILL.md              ← 本文档
└── scripts/
    └── xhs_api.py        ← 自包含 CLI 实现
        XhsLitePoster      ← 核心发布类
        ├── initialize()  ← 启动浏览器
        ├── login()       ← 手机号登录
        └── post_article() ← 发布图文
```
