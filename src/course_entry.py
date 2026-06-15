"""
课程入口导航模块
从 notice 页面自动导航到视频播放页面

页面层级:
  课程列表 → /notice (公告页) → 章节内容 → /plan (计划页) → 点击视频 → /plan/detail (播放页)

真实 DOM (从 course_notice.html 分析):
  左侧菜单: ul.amenu-el-menu.el-menu > li.el-menu-item
    - 课程公告 (icon-xiaoxi3, 默认激活)
    - 学习进度 (icon-xuexijindu)
    - 章节内容 (icon-kecheng2)          ← 点击进入章节列表
    - 作业 / 考试 / 测验 / 讨论 / 笔记 / ...
  右侧内容: .right_view.course_main
  继续学习按钮: button > span:has-text("继续学习")
"""

import asyncio
from playwright.async_api import Page


class CourseEntry:
    """从课程公告页导航到视频播放页的入口处理器"""

    def __init__(self, page: Page):
        self.page = page

    async def enter_course(self, notice_url: str) -> bool:
        """
        从 notice 页面进入课程视频播放。

        策略（按优先级）:
          1. 点击「继续学习」按钮（直达上次学习位置）
          2. 点击「章节内容」→ 等待加载 → 点击第一个章节
          3. 直接修改 URL 跳转（兜底）
        """
        # 先导航到 notice 页面
        print(f"[入口] 导航到课程公告页...")
        await self.page.goto(notice_url, wait_until="networkidle")
        await asyncio.sleep(3)

        # 策略1: 点击「继续学习」
        if await self._try_continue_learning():
            return True

        # 策略2: 点击「章节内容」菜单
        if await self._try_chapter_content():
            return True

        # 策略3: 通过 URL 直接跳转 plan 页面
        if await self._try_direct_plan_url(notice_url):
            return True

        print("[入口] ❌ 所有策略失败，无法进入课程视频")
        return False

    # ===== 策略1: 继续学习 =====

    async def _try_continue_learning(self) -> bool:
        """尝试点击「继续学习」按钮"""
        result = await self.page.evaluate("""
            () => {
                // 查找「继续学习」按钮
                const btns = document.querySelectorAll('button');
                for (const btn of btns) {
                    const text = btn.innerText?.trim() || '';
                    if (text === '继续学习' || text.includes('继续')) {
                        btn.click();
                        return { clicked: true };
                    }
                }

                // 也查找 span 包含「继续学习」
                const spans = document.querySelectorAll('span');
                for (const s of spans) {
                    if (s.innerText?.trim() === '继续学习') {
                        const btn = s.closest('button');
                        if (btn) {
                            btn.click();
                            return { clicked: true };
                        }
                    }
                }
                return { clicked: false };
            }
        """)

        if result.get("clicked"):
            print("[入口] 点击「继续学习」...")
            await asyncio.sleep(4)

            # 检查是否进入了视频页面
            if await self._is_on_video_page():
                print("[入口] ✅ 已进入视频播放页")
                return True

            # 如果还在 notice 页，可能「继续学习」只刷新了右侧面板
            print("[入口] 继续学习后未进入视频页，尝试其他方式")

        return False

    # ===== 策略2: 章节内容菜单 =====

    async def _try_chapter_content(self) -> bool:
        """点击「章节内容」菜单项，然后点击第一个可用的章节"""
        # Step A: 点击「章节内容」菜单
        clicked_menu = await self.page.evaluate("""
            () => {
                // 查找左侧菜单中的「章节内容」
                const menuItems = document.querySelectorAll('.tac_left .el-menu-item, .course_nav .el-menu-item');
                for (const item of menuItems) {
                    const text = item.innerText?.trim() || '';
                    if (text.includes('章节内容') || text.includes('章节')) {
                        item.click();
                        return { clicked: true, text: text };
                    }
                }

                // 备选：通过 icon-kecheng2 图标找
                const icons = document.querySelectorAll('.tac_left i.iconfont');
                for (const icon of icons) {
                    if (icon.classList.contains('icon-kecheng2')) {
                        const menuItem = icon.closest('.el-menu-item');
                        if (menuItem) {
                            menuItem.click();
                            return { clicked: true, text: '章节内容(icon)' };
                        }
                    }
                }
                return { clicked: false };
            }
        """)

        if not clicked_menu.get("clicked"):
            print("[入口] 未找到「章节内容」菜单")
            return False

        print("[入口] 已点击「章节内容」菜单，等待加载...")
        await asyncio.sleep(3)

        # Step B: 寻找第一个可用的章节/视频入口
        found = await self._click_first_available_chapter()

        if found:
            await asyncio.sleep(4)
            if await self._is_on_video_page():
                print("[入口] ✅ 已进入视频播放页")
                return True

        return False

    async def _click_first_available_chapter(self) -> bool:
        """在章节内容面板中找到并点击第一个可用的章节"""
        return await self.page.evaluate("""
            () => {
                // 查找章节列表 - 在右侧内容区
                const rightView = document.querySelector('.right_view, .course_main');
                if (!rightView) return false;

                // 查找章节目录容器中的可点击项
                const clickables = rightView.querySelectorAll(
                    'a, .el-menu-item, .chapter-item, .section-item, ' +
                    '[class*="chapter"], [class*="section"], [class*="catalog"], ' +
                    '.el-collapse-item__header, .el-tree-node__content, ' +
                    'li[role="menuitem"], div[role="button"]'
                );

                for (const el of clickables) {
                    const text = el.innerText?.trim() || '';
                    // 跳过非内容的项
                    if (!text || text.includes('公告') || text.includes('评价') || text.includes('笔记')) {
                        continue;
                    }
                    // 找第一个有意义的章节名
                    if (text.length > 2 && text.length < 100) {
                        el.click();
                        return true;
                    }
                }

                // 备选：直接找任何可点击且看起来像课程标题的元素
                const allDivs = rightView.querySelectorAll('div, span, a, li');
                for (const el of allDivs) {
                    const text = el.innerText?.trim() || '';
                    // 匹配章节标题模式，如"第一章 xxx"或"1.1 xxx"
                    if (/^第[一二三四五六七八九十\d]+[章节]/.test(text) ||
                        /^\d+[\.\、\s]/.test(text) ||
                        text.includes('视频')) {
                        el.click();
                        return true;
                    }
                }

                return false;
            }
        """)

    # ===== 策略3: URL 直接跳转 =====

    async def _try_direct_plan_url(self, notice_url: str) -> bool:
        """尝试通过修改 URL 直接跳转到 plan 页面"""
        # notice URL 格式: .../course/study/{course_id}/notice
        # plan URL 格式:  .../course/study/{course_id}/plan/detail/{section_id}
        # 先尝试 plan 页面
        plan_url = notice_url.replace("/notice", "/plan")
        if plan_url != notice_url:
            print(f"[入口] 尝试直接访问 plan 页面: ...{plan_url[-50:]}")
            await self.page.goto(plan_url, wait_until="networkidle")
            await asyncio.sleep(3)

            if await self._is_on_video_page():
                print("[入口] ✅ 直接访问 plan 页面成功")
                return True

        return False

    # ===== 检测 =====

    async def _is_on_video_page(self) -> bool:
        """检查当前是否在视频播放页面"""
        return await self.page.evaluate("""
            () => {
                const url = window.location.href;
                // 视频页面 URL 包含 plan/detail
                if (url.includes('plan/detail') || url.includes('planDetail')) return true;
                // 有侧栏章节导航 .base-asider
                if (document.querySelector('.base-asider')) return true;
                // 有 CC 播放器
                if (document.querySelector('.ccH5playerBox, .base_ccplayer')) return true;
                // 有视频标签
                const video = document.querySelector('video');
                if (video && video.readyState !== undefined) return true;
                return false;
            }
        """)
