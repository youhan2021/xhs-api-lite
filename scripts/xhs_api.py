#!/usr/bin/env python3
"""
小红书发布 CLI — xhs-api-lite skill
自包含实现，不依赖 xhs_ai_publisher 项目
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

# ── 全局存储路径 ────────────────────────────────────────────────────────────
XHS_DATA_DIR = Path.home() / ".xhs_system"
XHS_DATA_DIR.mkdir(exist_ok=True)

# Playwright browsers 缓存路径
PLAYWRIGHT_BROWSERS_PATH = str(XHS_DATA_DIR / "ms-playwright")


# ═══════════════════════════════════════════════════════════════════════════
# 小红书发布器
# ═══════════════════════════════════════════════════════════════════════════

class XhsLitePoster:
    """
    小红书图文发布器 — 自包含实现，不依赖 xhs_ai_publisher

    工作流程：
      1. initialize()        → 启动浏览器，加载登录态
      2. login(phone)       → 手机号 + 短信验证码登录
      3. post_article()     → 填标题 + 正文 + 上传图片 + 发布

    存储路径：~/.xhs_system/
      xhs_storage_state.json   — 浏览器 storage_state（cookies + localStorage）
      xhs_cookies.json         — 明文 cookies 备份
      xhs_settings.json        — 手机号等配置
    """

    def __init__(self, data_dir: str = None):
        self.data_dir = Path(data_dir or str(XHS_DATA_DIR))
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self._logged_in = False

        self.storage_state_file = self.data_dir / "xhs_storage_state.json"
        self.cookies_file = self.data_dir / "xhs_cookies.json"
        self.settings_file = self.data_dir / "xhs_settings.json"

    # ── 浏览器启动 ────────────────────────────────────────────────────────

    async def initialize(self, headless: bool = False):
        """启动 Chromium，加载已有登录态"""
        from playwright.async_api import async_playwright

        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=headless,
            timeout=60_000,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--start-maximized",
                "--disable-automation",
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            ],
            executable_path=self._find_chromium(),
        )

        # 尝试从已有 storage_state 恢复上下文
        if self.storage_state_file.exists():
            try:
                self.context = await self.browser.new_context(
                    storage_state=str(self.storage_state_file),
                    viewport={"width": 1280, "height": 800},
                )
            except Exception:
                self.context = await self.browser.new_context(
                    viewport={"width": 1280, "height": 800},
                )
        else:
            self.context = await self.browser.new_context(
                viewport={"width": 1280, "height": 800},
            )

        # 加载 cookies 备用
        if self.cookies_file.exists():
            try:
                cookies = json.loads(self.cookies_file.read_text())
                for c in cookies:
                    c.setdefault("domain", ".xiaohongshu.com")
                    c.setdefault("path", "/")
                await self.context.add_cookies(cookies)
            except Exception as e:
                print(f"加载 cookies 失败（忽略）: {e}")

        self.page = await self.context.new_page()
        # 去除 webdriver 特征
        await self.page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)
        print("浏览器已启动")

    def _find_chromium(self) -> Optional[str]:
        """查找 Chromium 可执行文件"""
        candidates = [
            # Playwright 缓存（由 xhs-api-lite 自行安装）
            os.path.join(PLAYWRIGHT_BROWSERS_PATH, "chromium_headless_shell-1208", "chrome-linux", "headless_shell"),
            os.path.join(PLAYWRIGHT_BROWSERS_PATH, "chromium-1208", "chrome-linux", "chromium"),
            # 系统 chromium
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/usr/bin/google-chrome",
            # Playwright 默认
        ]
        for p in candidates:
            if os.path.exists(p):
                return p
        return None  # 让 Playwright 自己下载

    async def close(self):
        """关闭浏览器并保存登录态"""
        if self.page:
            await self.page.close()
        if self.context:
            try:
                state = await self.context.storage_state()
                self.storage_state_file.write_text(json.dumps(state))
            except Exception:
                pass
            try:
                cookies = await self.context.cookies()
                self.cookies_file.write_text(json.dumps(cookies))
            except Exception:
                pass
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    # ── 登录 ──────────────────────────────────────────────────────────────

    async def login(self, phone: str, country_code: str = "+86") -> bool:
        """
        手机号 + 短信验证码登录。
        返回 True 表示登录成功。
        """
        if not self.page:
            await self.initialize()

        await self.page.goto(
            "https://creator.xiaohongshu.com/login",
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        await asyncio.sleep(3)

        # 切换到手机号登录 tab
        await self._switch_to_phone_tab()

        # 填写手机号
        filled = await self._fill_phone(phone)
        if not filled:
            print("⚠️  无法自动填写手机号，请在浏览器中手动填写")
            input("填写完毕后回车...")

        # 点击获取验证码
        await self._click_sms_trigger()
        await asyncio.sleep(1)

        # 读取用户输入的验证码（后台运行时不接受 stdin，改用文件队列）
        code = self._read_sms_code()

        if code:
            filled = await self._fill_sms_code(code)
            if filled:
                await self._click_login_button()
            else:
                print("⚠️  无法自动填写验证码，请在浏览器中手动输入")
        else:
            print("请在浏览器中手动输入验证码并登录")

        await asyncio.sleep(3)

        # 保存手机号
        self._save_setting("phone", f"{country_code}{phone}")

        # 保存登录态
        try:
            state = await self.context.storage_state()
            self.storage_state_file.write_text(json.dumps(state))
            cookies = await self.context.cookies()
            self.cookies_file.write_text(json.dumps(cookies))
            print("登录态已保存")
        except Exception as e:
            print(f"保存登录态失败: {e}")

        self._logged_in = await self.is_logged_in()
        return self._logged_in

    async def is_logged_in(self) -> bool:
        """检查是否已登录"""
        if not self.page:
            return False
        try:
            await self.page.goto(
                "https://creator.xiaohongshu.com/new/home",
                wait_until="domcontentloaded",
                timeout=15_000,
            )
            await asyncio.sleep(2)
            url = self.page.url.lower()
            if "login" in url:
                return False
            body_text = await self.page.inner_text("body")
            return anyKW(body_text, ["创作服务平台", "发布笔记", "图文", "草稿"])
        except Exception:
            return False

    # ── 发布 ──────────────────────────────────────────────────────────────

    async def post_article(
        self,
        title: str,
        content: str,
        images: list = None,
        auto_publish: bool = False,
    ) -> bool:
        """
        发布图文笔记
          auto_publish=False → 预览发草稿（填完内容停在确认页，截图通知用户）
          auto_publish=True  → 直接发布
        """
        if not self.page:
            await self.initialize()

        if not await self.is_logged_in():
            print("⚠️  未登录，尝试恢复登录态...")
            if not await self._try_restore_login():
                print("❌ 登录态失效，请先运行 login 命令")
                return False

        # 导航到创作者中心发布页
        await self.page.goto(
            "https://creator.xiaohongshu.com/new/home",
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        await asyncio.sleep(3)

        # 点击「发布笔记」按钮
        await self._click_publish_button()
        await asyncio.sleep(2)

        # 切换到图文 tab
        await self._switch_to_image_tab()
        await asyncio.sleep(2)

        # 上传图片（封面必须第一张）
        if images:
            await self._upload_images(images)

        # 填写标题
        await self._fill_title(title)
        await asyncio.sleep(1)

        # 填写正文
        await self._fill_content(content)
        await asyncio.sleep(1)

        if auto_publish:
            ok = await self._click_publish_confirm()
            if ok:
                await asyncio.sleep(3)
                print("✅ 发布成功！")
            return ok
        else:
            ts = int(time.time())
            preview_path = self.data_dir / f"preview_{ts}.png"
            await self.page.screenshot(path=str(preview_path), timeout=10_000)
            print(f"✅ 内容已填入，截图: {preview_path}")
            print("请在浏览器中确认内容，点击发布。")
            return True

    # ── 验证码读取（支持后台 nohup 模式）─────────────────────────────────

    def _read_sms_code(self, timeout: int = 300, poll_interval: int = 3) -> str:
        """
        后台运行时无法读 stdin，改为文件队列轮询。
        打印队列路径，用户将验证码写入文件后自动读取。
        """
        queue_file = self.data_dir / "xhs_sms_queue.txt"
        queue_file.write_text("")  # 创建空文件

        print(f"\n{'='*50}")
        print(f"请查收短信验证码，收到后写入以下文件后回车：")
        print(f"  文件: {queue_file}")
        print(f"  例如: echo '123456' > {queue_file}")
        print(f"或直接在终端执行（另一窗口）：")
        print(f"  echo '你的验证码' > {queue_file}")
        print(f"{'='*50}\n")

        deadline = time.time() + timeout
        while time.time() < deadline:
            code = queue_file.read_text().strip()
            if code:
                queue_file.unlink(missing_ok=True)
                return code
            time.sleep(poll_interval)

        queue_file.unlink(missing_ok=True)
        return ""

    # ── 内部方法 ──────────────────────────────────────────────────────────

    async def _switch_to_phone_tab(self):
        """切换到手机号登录 tab"""
        patterns = [
            ("text", "手机号登录"),
            ("text", "手机登录"),
            ("css", "[class*='tab']:has-text('手机')"),
        ]
        for method, selector in patterns:
            try:
                loc = self.page.locator(selector) if method == "text" else self.page.locator(selector)
                if await loc.count() > 0:
                    await loc.first.click(timeout=3000)
                    print(f"已切换到手机号登录: {selector}")
                    await asyncio.sleep(1)
                    return
            except Exception:
                pass

    async def _fill_phone(self, phone: str) -> bool:
        for selector in [
            "input[type='tel']",
            "input[placeholder*='手机']",
            "input[placeholder*='phone']",
        ]:
            try:
                loc = self.page.locator(selector).first
                if await loc.count() > 0:
                    await loc.fill(phone, timeout=3000)
                    print(f"已填写手机号: {phone}")
                    return True
            except Exception:
                pass
        return False

    async def _click_sms_trigger(self) -> bool:
        for selector in [
            "text=获取验证码",
            "button:has-text('获取验证码')",
            "text=发送验证码",
        ]:
            try:
                loc = self.page.locator(selector).first
                if await loc.count() > 0:
                    await loc.click(timeout=3000)
                    print("已点击获取验证码")
                    return True
            except Exception:
                pass
        return False

    async def _fill_sms_code(self, code: str) -> bool:
        for selector in [
            "input[placeholder*='验证码']",
            "input[placeholder*='code']",
            "input[type='tel']",
        ]:
            try:
                loc = self.page.locator(selector).nth(1).first
                if await loc.count() > 0:
                    await loc.fill(code, timeout=3000)
                    print(f"已填写验证码: {code}")
                    return True
            except Exception:
                pass
        return False

    async def _click_login_button(self) -> bool:
        for selector in [
            "text=登录",
            "button:has-text('登录')",
            "button[type='submit']",
        ]:
            try:
                loc = self.page.locator(selector).first
                if await loc.count() > 0:
                    await loc.click(timeout=3000)
                    print("已点击登录")
                    return True
            except Exception:
                pass
        return False

    async def _try_restore_login(self) -> bool:
        """尝试验证已有登录态，或自动用保存的手机号登录"""
        if await self.is_logged_in():
            return True
        phone = self._load_setting("phone")
        if phone:
            print(f"尝试用 {phone} 重新登录...")
            return await self.login(phone.replace("+86", ""))
        return False

    async def _click_publish_button(self) -> bool:
        """点击顶部「发布笔记」按钮"""
        patterns = [
            "text=发布笔记",
            "button:has-text('发布笔记')",
            "[class*='publish']:has-text('发布')",
            ".creator-nav :has-text('发布')",
        ]
        for selector in patterns:
            try:
                loc = self.page.locator(selector).first
                if await loc.count() > 0:
                    await loc.click(timeout=5000)
                    print(f"已点击发布按钮: {selector}")
                    return True
            except Exception:
                pass
        raise Exception("无法找到「发布笔记」按钮，请手动点击页面上的发布入口")

    async def _switch_to_image_tab(self) -> bool:
        """切换到图文发布 tab"""
        patterns = [
            "text=图文",
            "button:has-text('图文')",
            "[role='tab']:has-text('图文')",
            "[class*='tab']:has-text('图文')",
        ]
        for selector in patterns:
            try:
                loc = self.page.locator(selector).first
                if await loc.count() > 0:
                    await loc.click(timeout=3000)
                    print(f"已切换图文tab: {selector}")
                    return True
            except Exception:
                pass
        print("未明确找到图文tab，尝试直接上传...")
        return False

    async def _upload_images(self, images: list) -> dict:
        """上传多张图片，返回 {index: True/False}"""
        results = {}
        try:
            file_inputs = self.page.locator("input[type='file']")
            count = await file_inputs.count()
            print(f"发现 {count} 个文件上传控件")
        except Exception:
            count = 0

        for i, img_path in enumerate(images):
            label = "封面" if i == 0 else f"第{i+1}张"
            print(f"上传 {label}: {Path(img_path).name}")
            try:
                # 小红书通常第一个 file input 就是图片上传
                inp = file_inputs.first
                await inp.set_input_files(img_path, timeout=15_000)
                await asyncio.sleep(3)  # 等待上传和预览渲染
                results[i] = True
                print(f"  ✅ {label}上传成功")
            except Exception as e:
                results[i] = False
                print(f"  ❌ {label}上传失败: {e}")

        if count == 0:
            # fallback: 尝试找上传区域点击后触发 file dialog
            print("未找到 file input，尝试点击上传区域...")
            for selector in [
                "[class*='upload']",
                "[class*='add']",
                ".upload-btn",
            ]:
                try:
                    loc = self.page.locator(selector).first
                    if await loc.count() > 0:
                        await loc.click(timeout=3000)
                        await asyncio.sleep(1)
                        # 注入文件到任意 file input
                        try:
                            await self.page.locator("input[type='file']").first.set_input_files(images[0])
                            await asyncio.sleep(2)
                        except Exception:
                            pass
                        break
                except Exception:
                    pass

        return results

    async def _fill_title(self, title: str) -> bool:
        for selector in [
            "input[placeholder*='标题']",
            "input[maxlength='100']",
            "[class*='title'] input",
            "[class*='input'][class*='title']",
        ]:
            try:
                loc = self.page.locator(selector).first
                if await loc.count() > 0 and await loc.is_editable(timeout=2000):
                    await loc.fill(title, timeout=5000)
                    print(f"已填写标题: {title[:30]}...")
                    return True
            except Exception:
                pass
        print(f"⚠️  未找到标题输入框，标题: {title[:30]}")
        return False

    async def _fill_content(self, content: str) -> bool:
        # contenteditable div
        for selector in [
            "[contenteditable='true'][class*='editor']",
            "[contenteditable='true'][class*='content']",
            "[contenteditable='true']",
            "textarea[placeholder*='正文']",
            "textarea[placeholder*='内容']",
        ]:
            try:
                loc = self.page.locator(selector).first
                if await loc.count() > 0 and await loc.is_editable(timeout=2000):
                    await loc.fill(content, timeout=5000)
                    print(f"已填写正文 ({len(content)} 字)")
                    return True
            except Exception:
                pass
        print(f"⚠️  未找到正文输入框，正文长度: {len(content)} 字")
        return False

    async def _click_publish_confirm(self) -> bool:
        """点击最终发布按钮"""
        patterns = [
            "text=发布",
            "button:has-text('发布'):not([class*='video'])",
            "[class*='publish']:text('发布')",
            "button[type='primary']",
        ]
        for selector in patterns:
            try:
                loc = self.page.locator(selector).first
                if await loc.count() > 0 and await loc.is_enabled(timeout=2000):
                    await loc.click(timeout=5000)
                    print(f"已点击发布: {selector}")
                    return True
            except Exception:
                pass
        print("⚠️  未找到明确的发布按钮，请在浏览器中手动点击发布")
        return False

    # ── 配置读写 ──────────────────────────────────────────────────────────

    def _save_setting(self, key: str, value: str):
        data = {}
        if self.settings_file.exists():
            try:
                data = json.loads(self.settings_file.read_text())
            except Exception:
                pass
        data[key] = value
        self.settings_file.write_text(json.dumps(data, ensure_ascii=False))

    def _load_setting(self, key: str) -> Optional[str]:
        if self.settings_file.exists():
            try:
                data = json.loads(self.settings_file.read_text())
                return data.get(key)
            except Exception:
                pass
        return None


# ── 辅助 ────────────────────────────────────────────────────────────────────

def anyKW(text: str, keywords: list) -> bool:
    return any(kw in text for kw in keywords)


# ═══════════════════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="小红书发布 CLI — xhs-api-lite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # status
    sub.add_parser("status", help="检查登录状态")

    # login
    login = sub.add_parser("login", help="手机号登录")
    login.add_argument("--phone", required=True, help="手机号")
    login.add_argument("--country-code", default="+86", help="国家代码（默认+86）")

    # publish
    pub = sub.add_parser("publish", help="发布图文")
    pub.add_argument("--title", required=True, help="笔记标题")
    pub.add_argument("--content", required=True, help="笔记正文")
    pub.add_argument("--images", nargs="+", required=True, help="图片路径（第一张必须为封面）")
    pub.add_argument("--auto-publish", default="false", choices=["true", "false"],
                     help="true=直接发布，false=预览发草稿（默认false）")
    pub.add_argument("--headless", default="false", choices=["true", "false"],
                     help="true=无头模式（不显示浏览器）")

    args = parser.parse_args()

    if args.cmd == "status":
        check_status()
    elif args.cmd == "login":
        run_login(args.phone, args.country_code)
    elif args.cmd == "publish":
        run_publish(args.title, args.content, args.images,
                    args.auto_publish == "true",
                    args.headless == "true")


def check_status():
    storage = XHS_DATA_DIR / "xhs_storage_state.json"
    cookies = XHS_DATA_DIR / "xhs_cookies.json"
    has_storage = storage.exists() and storage.stat().st_size > 100
    has_cookies = cookies.exists() and cookies.stat().st_size > 100
    print(f"Storage state: {'✅ 存在' if has_storage else '❌ 不存在'}")
    print(f"Cookies:       {'✅ 存在' if has_cookies else '❌ 不存在'}")
    if has_storage or has_cookies:
        print("\n✅ 登录态已保存，可直接调用 publish 发布。")
    else:
        print("\n❌ 未找到登录态，请先运行:")
        print(f"   python3 {sys.argv[0]} login --phone 你的手机号")


def run_login(phone: str, country_code: str):
    print(f"启动浏览器引导登录: {country_code} {phone}")

    async def _do():
        poster = XhsLitePoster()
        await poster.initialize(headless=False)
        ok = await poster.login(phone, country_code)
        if ok:
            print("✅ 登录成功！")
        else:
            print("❌ 登录失败，请检查验证码")
        await poster.close()
        sys.exit(0 if ok else 1)

    asyncio.run(_do())


def run_publish(title: str, content: str, images: list, auto_publish: bool, headless: bool):
    mode = "直接发布" if auto_publish else "预览发草稿"
    print(f"[{mode}] 标题: {title}")
    for i, img in enumerate(images):
        label = "封面" if i == 0 else f"第{i+1}张"
        if not Path(img).exists():
            print(f"❌ {label} 不存在: {img}")
            sys.exit(1)
        print(f"  {label}: {Path(img).name}")

    async def _do():
        poster = XhsLitePoster()
        await poster.initialize(headless=headless)
        ok = await poster.post_article(title, content, images, auto_publish=auto_publish)
        if not auto_publish and ok:
            print("\n内容已填入浏览器，请在浏览器中确认后点击发布。")
            print("按 Ctrl+C 关闭浏览器。")
            await asyncio.sleep(3600)  # 等待用户操作
        await poster.close()
        sys.exit(0 if ok else 1)

    asyncio.run(_do())


if __name__ == "__main__":
    main()
