"""
课程章节导航模块 v2.1
新增: 跳过已完成章节/子标签、计数统计
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
    skipped: bool = False  # 是否因为已完成而跳过


class Navigator:
    """课程导航器"""

    def __init__(self, page: Page):
        self.page = page
        self.total_sections = 0
        self.completed_sections = 0

    # ========= 进度统计 =========

    async def count_progress(self) -> dict:
        """统计总章节数和已完成数"""
        return await self.page.evaluate("""
            () => {
                const aside = document.querySelector('.base-asider');
                if (!aside) return { total: 0, completed: 0 };

                let total = 0, completed = 0;
                const submenus = aside.querySelectorAll('ul.el-menu-vertical-demo > li.el-submenu');
                submenus.forEach(ch => {
                    const items = ch.querySelectorAll('ul.el-menu--inline > li.el-menu-item');
                    items.forEach(sec => {
                        total++;
                        // 已完成图标带 .complete 类
                        const icon = sec.querySelector('i.complete');
                        if (icon) completed++;
                    });
                });
                return { total, completed };
            }
        """)

    async def count_subtabs(self) -> dict:
        """统计当前节内子标签总数和已完成数"""
        return await self.page.evaluate("""
            () => {
                const tabs = document.querySelectorAll('.plan-detailvideo .el-tabs__item.is-top');
                let total = 0, completed = 0;
                tabs.forEach(tab => {
                    total++;
                    const icon = tab.querySelector('.label i');
                    if (icon && icon.classList.contains('complete')) completed++;
                });
                return { total, completed };
            }
        """)

    # ========= 侧栏结构 =========

    async def get_sidebar_structure(self) -> dict:
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
                        const icon = sec.querySelector('i');
                        const isCompleted = icon ? icon.classList.contains('complete') : false;
                        sections.push({ index: si, title: name, isActive: isActiveSec, isCompleted });
                    });
                    chapters.push({ index: ci, title, isActive: isActiveCh, expanded: ch.classList.contains('is-opened'), sections });
                });
                return { chapters };
            }
        """)

    async def get_current_position(self) -> dict:
        return await self.page.evaluate("""
            () => {
                const aside = document.querySelector('.base-asider');
                if (!aside) return null;
                const submenus = aside.querySelectorAll('ul.el-menu-vertical-demo > li.el-submenu');
                let chapterIdx = -1, sectionIdx = -1, chapterTitle = '', sectionTitle = '';
                submenus.forEach((ch, ci) => {
                    if (ch.classList.contains('is-active')) { chapterIdx = ci; chapterTitle = ch.querySelector('.el-submenu__title > span')?.innerText?.trim() || ''; }
                    const items = ch.querySelectorAll('ul.el-menu--inline > li.el-menu-item');
                    items.forEach((sec, si) => {
                        if (sec.classList.contains('is-active')) { sectionIdx = si; sectionTitle = sec.querySelector('span')?.innerText?.trim() || ''; }
                    });
                });
                return { chapterIndex: chapterIdx, sectionIndex: sectionIdx, chapterTitle, sectionTitle };
            }
        """)

    async def get_current_section(self) -> dict | None:
        pos = await self.get_current_position()
        if not pos: return None
        # 侧栏路径: 章 > 节
        sidebar = f"{pos['chapterTitle']} > {pos['sectionTitle']}" if pos['chapterTitle'] else pos['sectionTitle']
        # 子标签名（当前播放的视频具体名字）
        subtab = await self.get_active_subtab_label()
        if subtab:
            return {"title": f"{sidebar} > {subtab}"}
        return {"title": sidebar}

    # ========= 子标签导航（带跳过已完成） =========

    async def get_active_subtab_label(self) -> str:
        """获取当前激活的子标签名（视频的具体名字）"""
        return await self.page.evaluate("""
            () => {
                const active = document.querySelector('.plan-detailvideo .el-tabs__item.is-top.is-active');
                if (!active) return '';
                return active.querySelector('.label span')?.innerText?.trim() || active.innerText?.trim() || '';
            }
        """)

    async def get_subtabs(self) -> list[dict]:
        return await self.page.evaluate("""
            () => {
                const tabs = document.querySelectorAll('.plan-detailvideo .el-tabs__item.is-top');
                const result = [];
                tabs.forEach((tab, i) => {
                    const label = tab.querySelector('.label span')?.innerText?.trim() || tab.innerText?.trim() || '';
                    const icon = tab.querySelector('.label i');
                    const isCompleted = icon ? icon.classList.contains('complete') : false;
                    const isActive = tab.classList.contains('is-active');
                    result.push({ index: i, label, isCompleted, isActive });
                });
                return result;
            }
        """)

    async def click_next_subtab(self) -> NavResult:
        """点击节内的下一个未完成的子标签"""
        raw = await self.page.evaluate("""
            () => {
                const tabs = document.querySelectorAll('.plan-detailvideo .el-tabs__item.is-top');
                let activeIdx = -1;
                for (let i = 0; i < tabs.length; i++) {
                    if (tabs[i].classList.contains('is-active')) { activeIdx = i; break; }
                }
                for (let i = activeIdx + 1; i < tabs.length; i++) {
                    const icon = tabs[i].querySelector('.label i');
                    if (!icon || !icon.classList.contains('complete')) {
                        tabs[i].click();
                        return { success: true, finished: false, reason: 'next_subtab', skipped: i - activeIdx - 1 };
                    }
                }
                return { success: false, finished: true, reason: 'no_more_subtabs', skipped: 0 };
            }
        """)
        return NavResult(**raw)

    # ========= 章节导航（带跳过已完成） =========

    async def click_next_section(self) -> NavResult:
        """
        导航到下一个未完成的节（同步点击，不用 setTimeout）
        """
        raw = await self.page.evaluate("""
            () => {
                const aside = document.querySelector('.base-asider');
                if (!aside) return { success: false, finished: true, reason: 'no_asider', skipped: 0 };

                const submenus = aside.querySelectorAll('ul.el-menu-vertical-demo > li.el-submenu');
                let activeChIdx = -1, activeSecIdx = -1;

                for (let ci = 0; ci < submenus.length; ci++) {
                    const items = submenus[ci].querySelectorAll('ul.el-menu--inline > li.el-menu-item');
                    for (let si = 0; si < items.length; si++) {
                        if (items[si].classList.contains('is-active')) {
                            activeChIdx = ci; activeSecIdx = si; break;
                        }
                    }
                    if (activeChIdx >= 0) break;
                }

                if (activeChIdx < 0) {
                    // 从第一个章的未完成节开始
                    for (let ci = 0; ci < submenus.length; ci++) {
                        const items = submenus[ci].querySelectorAll('ul.el-menu--inline > li.el-menu-item');
                        for (let si = 0; si < items.length; si++) {
                            const icon = items[si].querySelector('i');
                            if (!icon || !icon.classList.contains('complete')) {
                                // 展开章并点击节（同步）
                                const title = submenus[ci].querySelector('.el-submenu__title');
                                if (title) title.click();
                                items[si].click();
                                return { success: true, finished: false, reason: 'first_uncompleted', skipped: 0 };
                            }
                        }
                    }
                    return { success: false, finished: true, reason: 'all_done', skipped: 0 };
                }

                // 同章内往后找未完成节
                const currentItems = submenus[activeChIdx].querySelectorAll('ul.el-menu--inline > li.el-menu-item');
                for (let si = activeSecIdx + 1; si < currentItems.length; si++) {
                    const icon = currentItems[si].querySelector('i');
                    if (!icon || !icon.classList.contains('complete')) {
                        currentItems[si].click();
                        return { success: true, finished: false, reason: 'next_section', skipped: si - activeSecIdx - 1 };
                    }
                }

                // 下一章的第一个未完成节
                for (let ci = activeChIdx + 1; ci < submenus.length; ci++) {
                    const items = submenus[ci].querySelectorAll('ul.el-menu--inline > li.el-menu-item');
                    for (let si = 0; si < items.length; si++) {
                        const icon = items[si].querySelector('i');
                        if (!icon || !icon.classList.contains('complete')) {
                            const title = submenus[ci].querySelector('.el-submenu__title');
                            if (title) title.click();
                            items[si].click();
                            return { success: true, finished: false, reason: 'next_chapter', skipped: 0 };
                        }
                    }
                }

                return { success: false, finished: true, reason: 'all_sections_done', skipped: 0 };
            }
        """)
        return NavResult(**raw)

    async def navigate_to_next(self) -> NavResult:
        """综合导航: 子标签 → 下一节 → 完成"""
        subtab = await self.click_next_subtab()
        if subtab.success:
            return subtab
        return await self.click_next_section()

    # ========= 当前节是否已完成 =========

    async def is_current_completed(self) -> bool:
        """当前节/子标签是否已完成"""
        return await self.page.evaluate("""
            () => {
                // 先检查子标签
                const activeTab = document.querySelector('.plan-detailvideo .el-tabs__item.is-top.is-active');
                if (activeTab) {
                    const icon = activeTab.querySelector('.label i');
                    if (icon && icon.classList.contains('complete')) return true;
                }
                // 再检查侧栏节
                const activeSec = document.querySelector('.base-asider .el-menu-item.is-active');
                if (activeSec) {
                    const icon = activeSec.querySelector('i');
                    if (icon && icon.classList.contains('complete')) return true;
                }
                return false;
            }
        """)

    # ========= 内容类型检测 =========

    async def detect_section_type(self) -> SectionType:
        result = await self.page.evaluate("""
            () => {
                const v = document.querySelector('video');
                if (v && v.readyState !== undefined) return 'video';
                const cc = document.querySelector('.base_ccplayer, .CCH5playerContainer, .ccH5playerBox');
                if (cc) return 'video';
                const docs = document.querySelectorAll('.article-content, .doc-content, .rich-text, [class*="document"], .ql-editor');
                for (const d of docs) { if (d.innerText && d.innerText.trim().length > 50) return 'document'; }
                const q = document.querySelector('.quiz, .exam, .test, [class*="question"]');
                if (q) return 'quiz';
                return 'unknown';
            }
        """)
        type_map = {"video": SectionType.VIDEO, "document": SectionType.DOCUMENT, "quiz": SectionType.QUIZ}
        return type_map.get(result, SectionType.UNKNOWN)

    async def wait_for_page_ready(self, timeout: float = 15.0) -> bool:
        try:
            await self.page.wait_for_load_state("networkidle", timeout=timeout * 1000)
            await asyncio.sleep(1.5)
            await self.page.wait_for_selector(".base-asider", timeout=5000)
            return True
        except Exception:
            return False

    async def wait_for_content_ready(self, timeout: float = 10.0) -> str:
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

    async def handle_document_section(self) -> dict:
        return await self.page.evaluate("""
            () => {
                const doc = document.querySelector('.article-content, .doc-content, .rich-text, .ql-editor, [class*="document"]');
                if (doc) { doc.scrollTop = doc.scrollHeight; window.scrollTo(0, document.body.scrollHeight); }
                const btn = document.querySelector('button:has-text("完成"), button:has-text("下一页"), button:has-text("继续")');
                if (btn) { btn.click(); return { ok: true, clicked: true }; }
                return { ok: true, scrolled: true };
            }
        """)

    async def handle_quiz_section(self) -> bool:
        result = await self.page.evaluate("() => !!document.querySelector('.quiz, .exam, .test, [class*=\"question\"]')")
        if result:
            print("[导航] ⚠️ 检测到测验，需要手动完成！")
            input("[导航] 完成后按 Enter 继续...")
        return True
