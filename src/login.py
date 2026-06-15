"""
登录模块 v2.1
支持两种模式:
  1. 有头模式（fallback）: 打开浏览器让用户手动操作
  2. 无头模式: 截图验证码 → 终端提示输入 → 自动提交
Cookie 持久化: auth_state.json
"""

import asyncio
import json
import os
from pathlib import Path
from playwright.async_api import Page, BrowserContext

STORAGE_STATE_PATH = Path(__file__).parent.parent / "auth_state.json"


class LoginHandler:
    """登录处理器"""

    def __init__(self, page: Page, context: BrowserContext, login_url: str):
        self.page = page
        self.context = context
        self.login_url = login_url

    # ========= 会话加载 =========

    async def try_load_session(self) -> bool:
        """尝试加载已保存的登录 Cookie"""
        if not STORAGE_STATE_PATH.exists():
            return False
        try:
            await self.page.goto("https://www.zjooc.cn/", wait_until="domcontentloaded")
            await asyncio.sleep(1)
            with open(STORAGE_STATE_PATH, "r", encoding="utf-8") as f:
                state = json.load(f)
            if state.get("cookies"):
                await self.context.add_cookies(state["cookies"])
            await self.page.goto("https://www.zjooc.cn/ucenter/student/course/build/list", wait_until="domcontentloaded")
            await asyncio.sleep(2)
            if "login" not in self.page.url.lower() and "ucenter" in self.page.url.lower():
                print("[会话] Cookie 登录成功")
                return True
            STORAGE_STATE_PATH.unlink(missing_ok=True)
            return False
        except Exception as e:
            print(f"[会话] 加载失败: {e}")
            return False

    async def save_session(self):
        try:
            state = await self.context.storage_state()
            with open(STORAGE_STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            print("[会话] 已保存")
        except Exception as e:
            print(f"[会话] 保存失败: {e}")

    # ========= 无头验证码登录 =========

    async def headless_login(self, username: str, password: str) -> bool:
        """
        无头模式登录：自动填表 + 截图验证码让用户输入
        """
        print("\n" + "=" * 50)
        print("  无头模式登录（验证码需手动输入）")
        print("=" * 50)

        await self.page.goto(self.login_url, wait_until="networkidle")
        await asyncio.sleep(2)

        # 1) 填账号
        filled_user = await self._fill_field([
            'input[type="text"]', 'input[placeholder*="账号"]', 'input[placeholder*="手机"]',
            'input[placeholder*="用户名"]', 'input[placeholder*="学号"]', 'input[name="username"]',
        ], username)
        if not filled_user:
            print("[无头登录] 未找到账号输入框，回退手动模式")
            return False

        # 2) 填密码
        filled_pwd = await self._fill_field([
            'input[type="password"]', 'input[placeholder*="密码"]', 'input[name="password"]',
        ], password)
        if not filled_pwd:
            print("[无头登录] 未找到密码输入框，回退手动模式")
            return False

        # 3) 处理验证码
        captcha_code = await self._capture_captcha()
        if captcha_code:
            await self._fill_field([
                'input[placeholder*="验证码"]', 'input[name="captcha"]', 'input[name="verifyCode"]',
            ], captcha_code)

        # 4) 点击登录
        clicked = await self.page.evaluate("""
            () => {
                const btns = document.querySelectorAll('button');
                for (const b of btns) {
                    if (b.innerText?.includes('登录')) { b.click(); return true; }
                }
                return false;
            }
        """)
        if not clicked:
            print("[无头登录] 未找到登录按钮")
            return False

        print("[无头登录] 已提交，等待跳转...")
        await asyncio.sleep(4)

        if "login" not in self.page.url.lower():
            print("[无头登录] 登录成功！")
            await self.save_session()
            return True

        # 检查错误提示
        error = await self.page.evaluate("""
            () => {
                const els = document.querySelectorAll('.el-message--error, [class*="error"], .msg-error');
                for (const e of els) { if (e.innerText?.trim()) return e.innerText.trim(); }
                return null;
            }
        """)
        if error:
            print(f"[无头登录] 登录失败: {error}")
        return False

    async def _fill_field(self, selectors: list[str], value: str) -> bool:
        """尝试用多个选择器填充输入框"""
        for sel in selectors:
            try:
                el = await self.page.wait_for_selector(sel, timeout=2000)
                if el:
                    await el.click()
                    await el.fill("")
                    await el.type(value, delay=30)
                    return True
            except Exception:
                continue
        return False

    async def _capture_captcha(self) -> str | None:
        """截图验证码并提示用户输入"""
        captcha_selectors = [
            'img[src*="captcha"]', 'img[src*="verify"]', '.captcha img',
            '.verify-code img', 'img[src*="code"]',
        ]
        for sel in captcha_selectors:
            try:
                el = await self.page.wait_for_selector(sel, timeout=2000)
                if el:
                    captcha_path = str(Path.cwd() / "captcha.png")
                    await el.screenshot(path=captcha_path)
                    print(f"\n[验证码] 已保存截图: {captcha_path}")
                    print("[验证码] 请打开图片查看并输入验证码")
                    code = input("[验证码] 请输入（无验证码直接回车）: ").strip()
                    return code if code else None
            except Exception:
                continue
        return None

    # ========= 有头手动登录（fallback） =========

    async def manual_login_visual(self) -> bool:
        """有头模式：打开浏览器，自动检测登录完成"""
        print("\n" + "=" * 50)
        print("  请在浏览器中手动完成登录")
        print("=" * 50)

        await self.page.goto(self.login_url, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        print("[登录] 等待登录完成（检测到登录成功会自动继续）...")

        # 轮询 URL，最多等 3 分钟
        for _ in range(90):
            await asyncio.sleep(2)
            url = self.page.url
            if "login" not in url.lower() and "ucenter" in url.lower():
                print("[登录] 检测到登录成功！")
                await self.save_session()
                return True

        print("[登录] 等待超时")
        return False

    # ========= 对外统一入口 =========

    async def ensure_logged_in(self, headless: bool, username: str = "", password: str = "") -> bool:
        """
        确保登录状态
        有 Cookie → 直接复用
        无 Cookie → 打开浏览器让用户手动登录
        """
        if await self.try_load_session():
            return True

        # 无论有无账号密码，都打开浏览器让用户手动操作（处理验证码）
        return await self.manual_login_visual()
