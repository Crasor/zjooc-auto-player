"""
浏览器生命周期管理模块
负责启动/关闭 Playwright Chromium 浏览器，注入反检测脚本
支持 Cookie 持久化（storage_state）
"""

import json
from pathlib import Path
from playwright.async_api import async_playwright, Browser, BrowserContext, Page


# 反检测初始化脚本 — 在每一个页面加载前注入
ANTI_DETECT_INIT_SCRIPT = """
// 移除 webdriver 标记
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
});

// 伪造 chrome 对象
window.chrome = {
    runtime: {},
    loadTimes: function() {},
    csi: function() {},
    app: {}
};

// 伪造 plugins 数组
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
});

// 伪造 languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['zh-CN', 'zh', 'en'],
});

// 覆写页面可见性 API — 防止平台检测到切后台而暂停视频
Object.defineProperty(document, 'hidden', {
    value: false,
    writable: false,
    configurable: false,
});
Object.defineProperty(document, 'visibilityState', {
    value: 'visible',
    writable: false,
    configurable: false,
});

// 阻断 visibilitychange 事件
document.addEventListener(
    'visibilitychange',
    (e) => e.stopImmediatePropagation(),
    true
);
"""

# 登录状态持久化路径
STORAGE_STATE_PATH = Path(__file__).parent.parent / "auth_state.json"


class BrowserManager:
    """Playwright 浏览器管理器"""

    def __init__(self, headless: bool = False, load_session: bool = True):
        self.headless = headless
        self.load_session = load_session
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    @property
    def context(self) -> BrowserContext:
        if self._context is None:
            raise RuntimeError("浏览器未启动，请先调用 start()")
        return self._context

    async def start(self) -> Page:
        """启动浏览器并返回主 Page 对象"""
        self._playwright = await async_playwright().start()

        # 检查是否有已保存的登录状态
        storage_state = None
        if self.load_session and STORAGE_STATE_PATH.exists():
            try:
                with open(STORAGE_STATE_PATH, "r", encoding="utf-8") as f:
                    storage_state = json.load(f)
                print("[浏览器] 加载已保存的会话状态")
            except Exception:
                pass

        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=AudioAutoplayMuting",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-infobars",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )

        # 使用 storage_state 创建 context（如果有的话）
        context_kwargs = {
            "viewport": {"width": 1366, "height": 768},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        }
        if storage_state:
            context_kwargs["storage_state"] = storage_state

        self._context = await self._browser.new_context(**context_kwargs)

        # 在每个页面加载前注入反检测脚本
        await self._context.add_init_script(ANTI_DETECT_INIT_SCRIPT)

        self._page = await self._context.new_page()
        return self._page

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("浏览器未启动，请先调用 start()")
        return self._page

    async def save_session(self):
        """保存当前会话状态"""
        try:
            state = await self._context.storage_state()
            with open(STORAGE_STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            print(f"[浏览器] 会话已保存")
        except Exception as e:
            print(f"[浏览器] 保存会话失败: {e}")

    async def close(self):
        """关闭浏览器并清理资源"""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
