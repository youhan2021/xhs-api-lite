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

> 自包含实现，不依赖 xhs_ai_publisher 项目。登录态存放在 `~/.xhs_system/`。

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

### 2. 手机号登录（只需执行一次）

```bash
python3 ~/.hermes/skills/xhs-api-lite/scripts/xhs_api.py login --phone 13800138000
```

流程：打开浏览器 → 填写手机号 → 点击获取验证码 → 查收短信输入验证码 → 登录成功自动保存。

### 3. 预览发草稿（推荐首次使用）

```bash
python3 ~/.hermes/skills/xhs-api-lite/scripts/xhs_api.py publish \
  --title "你的笔记标题" \
  --content "正文内容..." \
  --images ~/.hermes/research/imgs/cover.png \
           ~/.hermes/research/imgs/page1.png \
           ~/.hermes/research/imgs/page2.png \
  --auto-publish false
```

浏览器打开，内容自动填入，**停在发布确认页**，你去手动点发布。

### 4. 直接发布（无人值守）

```bash
python3 ~/.hermes/skills/xhs-api-lite/scripts/xhs_api.py publish \
  --title "你的笔记标题" \
  --content "正文内容..." \
  --images ~/.hermes/research/imgs/cover.png \
           ~/.hermes/research/imgs/page1.png \
  --auto-publish true
```

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
