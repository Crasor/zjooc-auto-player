"""
课程章节导航模块（基于真实 DOM 结构重写）

真实 DOM 结构（从 course_study.html 分析）:

侧栏 (.base-asider):
  ul.el-menu-vertical-demo.el-menu
    li.el-submenu                         ← 章 (Chapter)
      div.el-submenu__title > span        ← 章标题
      ul.el-menu.el-menu--inline          ← 节列表
        li.el-menu-item                   ← 节 (Section)
          span.of_eno                     ← 节标题

  激活状态:
    li.el-submenu.is-active.is-opened     ← 当前章
    li.el-menu-item.is-active             ← 当前节

主内容区 (main.el-main.fr > .plan-detailvideo):
  .el-tabs.el-tabs--top.el-tabs--border-card
    div.el-tabs__item.is-top              ← 节内子标签
    div.el-tabs__item.is-top.is-active    ← 当前子标签
"""

import asyncio
from dataclasses import dataclass
from enum import Enum
from playwright.async_api import Page


class SectionType(Enum):
    VIDEO = "video"
    DOCUMENT = "document"
    QUIZ = "quiz"
    UNKNOWN = "unknown"


@dataclass
class NavResult:
    success: bool
    finished: bool
    reason: str


class Navigator:
    """课程导航器 — 基于真实 DOM 结构"""

    def __init__(self, page: Page):
        self.page = page

    # ========= 侧栏结构读取 =========

    async def get_sidebar_structure(self) -> dict:
        """读取完整的侧栏章节结构"""
        return await self.page.evaluate("""
            () => {
                const aside = document.querySelector('.base-asider');
                if (!aside) return { chapters: [], error: 'no_asider' };

                const chapters = [];
                const submenus = aside.querySelectorAll('ul.el-menu-vertical-demo > li.el-submenu');

                submenus.forEach((ch, ci) => {
                    const title = ch.querySelector('.el-submenu__title > span')?.innerText?.trim() || '';
                    const isActiveCh = ch.classList.contains('is-active');

                    const sections = [];
                    const items = ch.querySelectorAll('ul.el-menu--inline > li.el-menu-item');
                    items.forEach((sec, si) => {
                        const name = sec.querySelector('span')?.innerText?.trim() || '';
                        const isActiveSec = sec.classList.contains('is-active');
                        sections.push({
                            index: si,
                            title: name,
                            isActive: isActiveSec
                        });
                    });

                    chapters.push({
                        index: ci,
                        title: title,
                        isActive: isActiveCh,
                        expanded: ch.classList.contains('is-opened'),
                        sections: sections
                    });
                });

                return { chapters };
            }
        """)

    async def get_current_position(self) -> dict:
        """获取当前所在章节位置"""
        return await self.page.evaluate("""
            () => {
                const aside = document.querySelector('.base-asider');
                if (!aside) return null;

                const submenus = aside.querySelectorAll('ul.el-menu-vertical-demo > li.el-submenu');
                let chapterIdx = -1, sectionIdx = -1, chapterTitle = '', sectionTitle = '';

                submenus.forEach((ch, ci) => {
                    if (ch.classList.contains('is-active')) {
                        chapterIdx = ci;
                        chapterTitle = ch.querySelector('.el-submenu__title > span')?.innerText?.trim() || '';
                    }
                    const items = ch.querySelectorAll('ul.el-menu--inline > li.el-menu-item');
                    items.forEach((sec, si) => {
                        if (sec.classList.contains('is-active')) {
                            sectionIdx = si;
                            sectionTitle = sec.querySelector('span')?.innerText?.trim() || '';
                        }
                    });
                });

                return {
                    chapterIndex: chapterIdx,
                    sectionIndex: sectionIdx,
                    chapterTitle,
                    sectionTitle
                };
            }
        """)

    async def get_current_section(self) -> dict | None:
        """获取当前激活的章节名"""
        pos = await self.get_current_position()
        if not pos:
            return None
        return {
            "title": f"{pos['chapterTitle']} > {pos['sectionTitle']}" if pos['chapterTitle'] else pos['sectionTitle']
        }

    # ========= 主内容区子标签 =========

    async def get_subtabs(self) -> list[dict]:
        """获取节内的子标签列表"""
        return await self.page.evaluate("""
            () => {
                const tabs = document.querySelectorAll('.plan-detailvideo .el-tabs__item.is-top');
                const result = [];
                tabs.forEach((tab, i) => {
                    const label = tab.querySelector('.label span')?.innerText?.trim() || tab.innerText?.trim() || '';
                    const icon = tab.querySelector('.label i');
                    const isCompleted = icon ? icon.classList.contains('complete') : false;
                    const isActive = tab.classList.contains('is-active');
                    const tabId = tab.getAttribute('aria-controls') || tab.id || '';
                    result.push({
                        index: i,
                        label: label,
                        isCompleted: isCompleted,
                        isActive: isActive,
                        tabId: tabId
                    });
                });
                return result;
            }
        """)

    async def get_active_subtab_index(self) -> int:
        """获取当前激活的子标签索引"""
        return await self.page.evaluate("""
            () => {
                const tabs = document.querySelectorAll('.plan-detailvideo .el-tabs__item.is-top');
                for (let i = 0; i < tabs.length; i++) {
                    if (tabs[i].classList.contains('is-active')) return i;
                }
                return -1;
            }
        """)

    async def click_next_subtab(self) -> NavResult:
        """点击节内的下一个子标签"""
        return await self.page.evaluate("""
            () => {
                const tabs = document.querySelectorAll('.plan-detailvideo .el-tabs__item.is-top');
                let activeIdx = -1;
                for (let i = 0; i < tabs.length; i++) {
                    if (tabs[i].classList.contains('is-active')) {
                        activeIdx = i;
                        break;
                    }
                }

                if (activeIdx >= 0 && activeIdx < tabs.length - 1) {
                    const nextTab = tabs[activeIdx + 1];
                    nextTab.click();
                    return { success: true, finished: false, reason: 'next_subtab' };
                }

                // 没有更多子标签
                return { success: false, finished: true, reason: 'no_more_subtabs' };
            }
        """)

    # ========= 章节导航 =========

    async def click_next_section(self) -> NavResult:
        """导航到侧栏下一个节"""
        return await self.page.evaluate("""
            () => {
                const aside = document.querySelector('.base-asider');
                if (!aside) return { success: false, finished: true, reason: 'no_asider' };

                const submenus = aside.querySelectorAll('ul.el-menu-vertical-demo > li.el-submenu');
                let activeCh = null, activeSec = null;

                for (const ch of submenus) {
                    const items = ch.querySelectorAll('ul.el-menu--inline > li.el-menu-item');
                    for (const sec of items) {
                        if (sec.classList.contains('is-active')) {
                            activeCh = ch;
                            activeSec = sec;
                            break;
                        }
                    }
                    if (activeSec) break;
                }

                if (!activeSec) {
                    // 没有找到当前激活的节
                    return { success: false, finished: true, reason: 'no_active_section' };
                }

                // 策略1: 在同章内找下一个节
                const allItems = activeCh.querySelectorAll('ul.el-menu--inline > li.el-menu-item');
                for (let i = 0; i < allItems.length - 1; i++) {
                    if (allItems[i] === activeSec) {
                        allItems[i + 1].click();
                        return { success: true, finished: false, reason: 'next_section_in_chapter' };
                    }
                }

                // 策略2: 找下一个章的第一个节
                let foundCurrent = false;
                for (const ch of submenus) {
                    if (foundCurrent) {
                        // 先展开这个章
                        const title = ch.querySelector('.el-submenu__title');
                        if (title) title.click();

                        // 点击第一个节
                        setTimeout(() => {
                            const firstItem = ch.querySelector('ul.el-menu--inline > li.el-menu-item');
                            if (firstItem) firstItem.click();
                        }, 300);

                        return { success: true, finished: false, reason: 'first_section_next_chapter' };
                    }
                    if (ch === activeCh) {
                        foundCurrent = true;
                    }
                }

                // 全部完成
                return { success: false, finished: true, reason: 'all_sections_done' };
            }
        """)

    async def navigate_to_next(self) -> NavResult:
        """
        综合导航：先尝试节内子标签 → 再尝试下一节
        4 层降级：
          1. 节内下一个子标签 (sub-tab)
          2. 同章下一节
          3. 下一章第一节
          4. 全部完成
        """
        # 第1层：节内子标签
        subtab_result = await self.click_next_subtab()
        if subtab_result.success:
            return subtab_result

        # 第2-4层：跨节导航
        return await self.click_next_section()

    # ========= 内容类型检测 =========

    async def detect_section_type(self) -> SectionType:
        """检测当前内容类型"""
        result = await self.page.evaluate("""
            () => {
                // 检测视频
                const video = document.querySelector('video');
                if (video && video.readyState !== undefined) return 'video';

                // 检测 CC 播放器容器
                const ccPlayer = document.querySelector('.base_ccplayer, .CCH5playerContainer, .ccH5playerBox');
                if (ccPlayer) return 'video';

                // 检测图文内容
                const docAreas = document.querySelectorAll('.article-content, .doc-content, .rich-text, [class*="document"], .ql-editor');
                for (const d of docAreas) {
                    if (d.innerText && d.innerText.trim().length > 50) return 'document';
                }

                // 检测测验
                const quiz = document.querySelector('.quiz, .exam, .test, [class*="question"]');
                if (quiz) return 'quiz';

                return 'unknown';
            }
        """)
        type_map = {"video": SectionType.VIDEO, "document": SectionType.DOCUMENT, "quiz": SectionType.QUIZ}
        return type_map.get(result, SectionType.UNKNOWN)

    # ========= 页面就绪等待 =========

    async def wait_for_page_ready(self, timeout: float = 15.0) -> bool:
        """等待课程页面渲染完成"""
        try:
            await self.page.wait_for_load_state("networkidle", timeout=timeout * 1000)
            await asyncio.sleep(1.5)

            # 等待侧栏渲染
            await self.page.wait_for_selector(".base-asider", timeout=5000)
            return True
        except Exception:
            return False

    async def wait_for_content_ready(self, timeout: float = 10.0) -> str:
        """等待页面内容就绪，返回内容类型"""
        try:
            await self.page.wait_for_selector("video, .base_ccplayer, .CCH5playerContainer", timeout=min(timeout * 1000, 8000))
            return "video"
        except Exception:
            pass
        try:
            await self.page.wait_for_selector(".article-content, .doc-content, .rich-text, .ql-editor", timeout=min(timeout * 1000, 5000))
            return "document"
        except Exception:
            pass
        return "unknown"

    # ========= 图文处理 =========

    async def handle_document_section(self) -> dict:
        """处理图文章节（滚动到底部，查找完成按钮）"""
        return await self.page.evaluate("""
            () => {
                const docArea = document.querySelector('.article-content, .doc-content, .rich-text, .ql-editor, [class*="document"]');
                if (docArea) {
                    docArea.scrollTop = docArea.scrollHeight;
                    window.scrollTo(0, document.body.scrollHeight);
                }

                const doneBtn = document.querySelector(
                    'button:has-text("完成"), button:has-text("下一页"), button:has-text("继续")'
                );
                if (doneBtn) {
                    doneBtn.click();
                    return { ok: true, clicked: true };
                }
                return { ok: true, scrolled: true };
            }
        """)

    async def handle_quiz_section(self) -> bool:
        """测验需要人工处理"""
        result = await self.page.evaluate("""
            () => !!document.querySelector('.quiz, .exam, .test, [class*="question"]')
        """)
        if result:
            print("[导航] ⚠️ 检测到测验/考试章节，需要手动完成！")
            input("[导航] 请手动完成测验后按回车继续...")
        return True
