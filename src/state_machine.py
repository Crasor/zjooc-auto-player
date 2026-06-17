"""
核心状态机 v2.3
精简逻辑：
  进入时 → 跳过已完成 → 播视频 → 播完点下一个 → 本节没了去下一节 → 全部完成退出
  只有跨节时才回 notice 点「继续学习」
"""

import asyncio
from enum import Enum
from datetime import datetime
from playwright.async_api import Page
from src.player import PlayerController
from src.navigator import Navigator, SectionType
from src.anti_detect import AntiDetect
from src.progress import ProgressBar, console


class State(Enum):
    IDLE = "idle"
    VIDEO_PLAYING = "video_playing"
    SKIP_TO_NEXT = "skip_to_next"     # 跳过已完成 → 找下一个未完成
    GOTO_NEXT_SECTION = "goto_next_section"  # 本节全部完成，回 notice 跳下一节
    FINISHED = "finished"


class ZjoocStateMachine:

    def __init__(self, page: Page, notice_url: str = "",
                 speed: float = 2.0, mute: bool = True,
                 poll_interval: float = 3.0,
                 enable_anti_detect: bool = True, mouse_interval: float = 30.0):
        self.page = page
        self.notice_url = notice_url
        self.state = State.IDLE
        self.poll_interval = poll_interval
        self.speed = speed
        self.mute = mute
        self.player = PlayerController(page, speed=speed, mute=mute)
        self.navigator = Navigator(page)
        self.anti_detect = AntiDetect(
            page, enable_mouse_sim=enable_anti_detect,
            mouse_interval=mouse_interval, speed=speed, mute=mute)
        self.stats = {"videos_watched": 0, "documents_read": 0, "start_time": None}
        self._on_state_change = None
        self._on_progress_update = None
        self._section_name = ""
        self._watched_subtabs: set = set()  # 全局已刷视频 (完整路径)
        self._seen_sections: set = set()     # _fast_skip_completed 防循环 (章节位置)

    def on_state_change(self, cb): self._on_state_change = cb
    def on_progress_update(self, cb): self._on_progress_update = cb

    async def _set_state(self, s: State):
        old = self.state
        self.state = s
        if old != s:
            console.newline()
            print(f"[状态] {old.value} → {s.value}")
            if self._on_state_change:
                await self._on_state_change(s.value)

    # ========= 主循环 =========

    async def run(self):
        self.stats["start_time"] = datetime.now()
        await self.anti_detect.start()
        print(f"[状态机] 启动")

        # 进入时先检查当前是否已完成
        if await self.navigator.is_current_completed():
            print("[状态机] 当前已完成，跳过")
            await self._set_state(State.SKIP_TO_NEXT)

        while self.state != State.FINISHED:
            try:
                await self._tick()
            except Exception as e:
                print(f"[状态机] 异常: {e}")
                await asyncio.sleep(self.poll_interval)

        await self.anti_detect.stop()
        elapsed = datetime.now() - self.stats["start_time"]
        print(f"\n{'='*50}\n  全部完成！视频: {self.stats['videos_watched']} | 耗时: {elapsed}\n{'='*50}")

    async def _tick(self):
        if self.state == State.IDLE:
            await self._idle()
        elif self.state == State.VIDEO_PLAYING:
            await self._playing()
        elif self.state == State.SKIP_TO_NEXT:
            await self._skip_to_next()
        elif self.state == State.GOTO_NEXT_SECTION:
            await self._goto_next_section()
        await asyncio.sleep(self.poll_interval)

    # ========= IDLE =========

    async def _idle(self):
        if await self.navigator.is_current_completed():
            # 一次性连续跳过所有已完成，不用反复状态切换
            await self._fast_skip_completed()
            return

        # 检查当前 subtab 是否已刷过（防止绕回已刷视频）
        sec = await self.navigator.get_current_section()
        section_name = sec.get("title", "") if sec else ""
        if section_name and section_name in self._watched_subtabs:
            print(f"[入口] 已刷过: {section_name}，跳过")
            await self._fast_skip_completed()
            return

        if await self.player.wait_for_video(timeout=6.0):
            await self.player.set_mute(self.mute)
            await self.player.set_speed(self.speed)
            self._section_name = section_name
            await self._set_state(State.VIDEO_PLAYING)
        elif await self.navigator.detect_section_type() == SectionType.DOCUMENT:
            await self.navigator.handle_document_section()
            await asyncio.sleep(3)
            await self._set_state(State.SKIP_TO_NEXT)
        else:
            await asyncio.sleep(2)

    async def _fast_skip_completed(self):
        """一次性连续跳过所有已完成，直到找到未完成或全部结束
        使用全局 _seen_sections 和 _watched_subtabs 防止循环重播"""
        self._seen_sections.clear()  # 每次调用重置
        for _ in range(50):
            # 获取当前位置标识（用于防循环）
            pos = await self.navigator.get_current_position()
            pos_key = f"{pos['chapterIndex']}:{pos['sectionIndex']}" if pos else "unknown"
            if pos_key in self._seen_sections:
                print(f"[快速跳过] 检测到循环 ({pos_key})，全部完成")
                break
            self._seen_sections.add(pos_key)

            # 获取当前节名（用于拼 watcher key）
            sec = await self.navigator.get_current_section()
            section_title = sec.get("title", "") if sec else ""
            # 去掉子标签部分，保留 "章 > 节"
            parts = section_title.split(" > ")
            section_prefix = " > ".join(parts[:2]) if len(parts) >= 2 else section_title

            subtabs = await self.navigator.get_subtabs()

            # 找未完成且未刷过的子标签
            if subtabs:
                has_unwatched = False
                for t in subtabs:
                    if t.get("isActive"):
                        continue
                    if t.get("isCompleted"):
                        continue
                    # 构建完整 key 检查是否已刷过
                    full_key = f"{section_prefix} > {t['label']}"
                    if full_key in self._watched_subtabs:
                        continue  # 已刷过，跳过
                    # 找到未完成且未刷过的！
                    has_unwatched = True
                    idx = t["index"]
                    await self.page.evaluate(f"""
                        () => {{ const tabs = document.querySelectorAll('.plan-detailvideo .el-tabs__item.is-top');
                                 if (tabs[{idx}]) tabs[{idx}].click(); }}
                    """)
                    print(f"[快速跳过] → {t['label']}")
                    await asyncio.sleep(2)
                    await self._set_state(State.IDLE)
                    return

                if has_unwatched:
                    # 理论上不会到这里（上面已 return），但安全处理
                    pass

            # 子标签全完成或全刷过 → 跨节
            result = await self.navigator.click_next_section()
            if result.finished:
                break
            if result.success:
                print(f"[快速跳过] 跳节: {result.reason}")
                await asyncio.sleep(3)
                continue
            # 无法跳 → 回 notice
            if self.notice_url:
                await self.page.goto(self.notice_url, wait_until="networkidle")
                await asyncio.sleep(2)
                await self.page.evaluate("""
                    () => { const btns = document.querySelectorAll('button');
                            for (const b of btns) { if (b.innerText?.trim()==='继续学习') { b.click(); return; } } }
                """)
                await asyncio.sleep(5)
                continue
            break

        await self._set_state(State.FINISHED)

    # ========= VIDEO_PLAYING =========

    async def _playing(self):
        # 先查进度，防止 ensure_playing 覆盖已结束状态
        p = await self.player.get_progress()
        if p and p.is_finished:
            self.stats["videos_watched"] += 1
            self._watched_subtabs.add(self._section_name)
            console.newline()
            await self._set_state(State.SKIP_TO_NEXT)
            return

        st = await self.player.ensure_playing()
        if not st.get("ok"):
            await self._set_state(State.IDLE)
            return

        p = await self.player.get_progress()  # 更新进度
        if p and p.duration > 0:
            bar = ProgressBar.draw(p.percent)
            c = ProgressBar.format_time(p.current)
            d = ProgressBar.format_time(p.duration)
            parts = self._section_name.split(" > ")
            name = parts[-1] if parts else self._section_name
            if len(name) > 18: name = name[:16] + ".."
            console.print(f"  {name}  {bar}  {c}/{d}  #{self.stats['videos_watched']+1}")

            if p.is_finished:
                self.stats["videos_watched"] += 1
                self._watched_subtabs.add(self._section_name)
                console.newline()
                await self._set_state(State.SKIP_TO_NEXT)
        else:
            console.print(f"  {self._section_name[:20]}  [加载...]")

    # ========= SKIP_TO_NEXT（直接在当前页找下一个未完成） =========

    async def _skip_to_next(self):
        """
        先尝试点下一个子标签；本节没了就 GOTO_NEXT_SECTION
        """
        # 获取当前节名前缀（用于 watcher key）
        sec = await self.navigator.get_current_section()
        section_title = sec.get("title", "") if sec else ""
        parts = section_title.split(" > ")
        section_prefix = " > ".join(parts[:2]) if len(parts) >= 2 else section_title

        # 先试子标签
        subtabs = await self.navigator.get_subtabs()
        if subtabs:
            active_idx = -1
            for i, t in enumerate(subtabs):
                if t.get("isActive"):
                    active_idx = i
                    break

            # 往后找第一个未完成且未刷过的
            for i in range(active_idx + 1, len(subtabs)):
                if subtabs[i].get("isCompleted"):
                    continue
                full_key = f"{section_prefix} > {subtabs[i]['label']}"
                if full_key in self._watched_subtabs:
                    continue  # 已刷过
                await self.page.evaluate(f"""
                    () => {{ const tabs = document.querySelectorAll('.plan-detailvideo .el-tabs__item.is-top');
                             if (tabs[{i}]) tabs[{i}].click(); }}
                """)
                print(f"[跳过] → {subtabs[i]['label']}")
                await asyncio.sleep(3)
                await self._set_state(State.IDLE)
                return

        # 本节子标签全完成了 → 尝试侧栏跳转到下一节
        result = await self.navigator.click_next_section()
        if result.finished:
            print("[跳过] 全部章节完成！")
            await self._set_state(State.FINISHED)
        elif result.success:
            print(f"[跳过] 跳转下一节: {result.reason}, 跳过 {result.skipped} 个已完成")
            await asyncio.sleep(3)
            await self._set_state(State.IDLE)
        else:
            # 侧栏不可用 → 回 notice 点继续学习
            await self._set_state(State.GOTO_NEXT_SECTION)

    # ========= GOTO_NEXT_SECTION（回 notice 点继续学习，兜底方案） =========

    async def _goto_next_section(self):
        if not self.notice_url:
            await self._set_state(State.FINISHED)
            return

        print("[跨节] 侧栏不可用，回公告页点继续学习...")
        await self.page.goto(self.notice_url, wait_until="networkidle")
        await asyncio.sleep(2)

        clicked = await self.page.evaluate("""
            () => {
                const btns = document.querySelectorAll('button');
                for (const b of btns) {
                    if (b.innerText?.trim() === '继续学习') { b.click(); return true; }
                }
                return false;
            }
        """)
        if not clicked:
            await self._set_state(State.FINISHED)
            return

        await asyncio.sleep(5)
        await AntiDetect.inject_visibility_override(self.page)

        # 检查是否所有子标签都已完成或已刷过（防死循环）
        subtabs = await self.navigator.get_subtabs()
        sec = await self.navigator.get_current_section()
        section_title = sec.get("title", "") if sec else ""
        parts = section_title.split(" > ")
        section_prefix = " > ".join(parts[:2]) if len(parts) >= 2 else section_title

        all_handled = True
        if subtabs:
            for t in subtabs:
                if t.get("isCompleted"):
                    continue
                full_key = f"{section_prefix} > {t['label']}"
                if full_key not in self._watched_subtabs:
                    all_handled = False
                    break

        if all_handled:
            # 尝试侧栏导航判断是否真的全完
            result = await self.navigator.click_next_section()
            if result.finished:
                await self._set_state(State.FINISHED)
                return

        await self._set_state(State.SKIP_TO_NEXT)

    # ========= 控制 =========

    async def pause_automation(self):
        console.newline()
        print("[控制] 暂停")
    async def resume_automation(self):
        await self._set_state(State.IDLE)
    async def set_speed(self, s: float):
        self.speed = s; self.anti_detect.speed = s; await self.player.set_speed(s)
    async def set_mute(self, m: bool):
        self.mute = m; self.anti_detect.mute = m; await self.player.set_mute(m)
