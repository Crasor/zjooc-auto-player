"""
登录模块（Cookie 持久化版本）
策略：
  1. 如果存在保存的 storage_state，直接加载，跳过登录
  2. 否则打开登录页，让用户手动登录（处理验证码）
  3. 登录成功后保存 storage_state 供后续复用
"""

import asyncio
import json
import os
from pathlib import Path
from playwright.async_api import Page, BrowserContext

# 存储登录状态的路径
STORAGE_STATE_PATH = Path(__file__).parent.parent / "auth_state.json"


class LoginHandler:
    """登录处理器 — 手动登录 + Cookie 持久化"""

    def __init__(self, page: Page, context: BrowserContext, login_url: str):
        self.page = page
        self.context = context
        self.login_url = login_url

    async def try_load_session(self) -> bool:
        """
        尝试加载已保存的登录状态
        Returns: True 表示加载成功，无需重新登录
        """
        if not STORAGE_STATE_PATH.exists():
            print("[会话] 未找到已保存的登录状态")
            return False

        try:
            # 先导航到网站首页，再注入 cookies
            await self.page.goto("https://www.zjooc.cn/", wait_until="domcontentloaded")
            await asyncio.sleep(1)

            # 加载 storage state（包含 cookies 和 localStorage）
            with open(STORAGE_STATE_PATH, "r", encoding="utf-8") as f:
                state = json.load(f)

            # 手动注入 cookies（storage_state 的 cookie 格式兼容）
            if state.get("cookies"):
                await self.context.add_cookies(state["cookies"])
                print(f"[会话] 已加载 {len(state['cookies'])} 个 cookies")

            # 刷新页面使 cookies 生效
            await self.page.goto("https://www.zjooc.cn/ucenter/student/course/build/list", wait_until="domcontentloaded")
            await asyncio.sleep(2)

            # 验证是否登录成功（检查页面是否跳转到课程列表而非登录页）
            current_url = self.page.url
            if "login" not in current_url.lower() and "ucenter" in current_url.lower():
                print("[会话] ✅ Cookie 登录成功！")
                return True
            else:
                print(f"[会话] Cookie 已过期，当前URL: {current_url}")
                STORAGE_STATE_PATH.unlink(missing_ok=True)
                return False

        except Exception as e:
            print(f"[会话] 加载失败: {e}")
            return False

    async def manual_login(self) -> bool:
        """
        打开登录页，让用户手动登录（处理验证码等）
        """
        print("\n" + "=" * 50)
        print("  请在浏览器中手动完成登录")
        print("  （验证码 / 手机验证等需要人工操作）")
        print("=" * 50)

        # 导航到登录页
        await self.page.goto(self.login_url, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        # 提示用户操作
        print("\n[登录] 浏览器已打开登录页面")
        print("[登录] 请手动输入账号密码和验证码后点击登录")
        print("[登录] 登录成功后，在终端按 Enter 继续...")
        input("\n>>> 登录完成后按 Enter: ")

        # 验证登录状态
        await asyncio.sleep(2)
        current_url = self.page.url

        if "login" in current_url.lower():
            print("[登录] ⚠️ 似乎仍在登录页面，再试一次？")
            input(">>> 如果已登录请按 Enter，否则请手动完成登录后按 Enter: ")
            await asyncio.sleep(2)
            current_url = self.page.url

        if "login" not in current_url.lower():
            print(f"[登录] ✅ 登录成功！当前页面: {current_url}")

            # 保存登录状态
            await self.save_session()
            return True
        else:
            print("[登录] ❌ 登录验证失败")
            return False

    async def save_session(self):
        """保存当前浏览器状态到文件"""
        try:
            state = await self.context.storage_state()
            with open(STORAGE_STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            print(f"[会话] ✅ 登录状态已保存到 {STORAGE_STATE_PATH}")
        except Exception as e:
            print(f"[会话] ⚠️ 保存失败: {e}")

    async def ensure_logged_in(self, username: str = "", password: str = "") -> bool:
        """
        确保已登录状态（优先加载缓存，否则手动登录）
        """
        # 策略1: 尝试加载已保存的会话
        if await self.try_load_session():
            return True

        # 策略2: 手动登录
        print("\n[登录] 需要手动登录（Cookie 不存在或已过期）")
        # 先尝试自动填充账号密码（可选，减少手动输入）
        if username and password:
            try:
                await self._auto_fill_credentials(username, password)
            except Exception:
                pass  # 自动填充失败也不影响，用户可手动填

        return await self.manual_login()

    async def _auto_fill_credentials(self, username: str, password: str):
        """尝试自动填充账号密码（验证码仍需手动处理）"""
        await self.page.goto(self.login_url, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        # 尝试各种选择器填充用户名
        username_selectors = [
            'input[type="text"]',
            'input[placeholder*="账号"]',
            'input[placeholder*="手机"]',
            'input[placeholder*="用户名"]',
            'input[placeholder*="学号"]',
            'input[name="username"]',
            'input[name="account"]',
        ]
        for sel in username_selectors:
            try:
                el = await self.page.wait_for_selector(sel, timeout=2000)
                if el:
                    await el.click()
                    await el.fill(username)
                    print(f"[自动填充] 已填入账号")
                    break
            except Exception:
                continue

        # 尝试填充密码
        password_selectors = [
            'input[type="password"]',
            'input[placeholder*="密码"]',
            'input[name="password"]',
        ]
        for sel in password_selectors:
            try:
                el = await self.page.wait_for_selector(sel, timeout=2000)
                if el:
                    await el.click()
                    await el.fill(password)
                    print(f"[自动填充] 已填入密码")
                    break
            except Exception:
                continue
