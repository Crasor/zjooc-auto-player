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
        self.stats = {"videos_watched": 0, "start_time": None}
        self._on_state_change = None
        self._on_progress_update = None
        self._section_name = ""

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
            await self._set_state(State.SKIP_TO_NEXT)
            return

        if await self.player.wait_for_video(timeout=6.0):
            await self.player.set_mute(self.mute)
            await self.player.set_speed(self.speed)
            await self.player.play()
            sec = await self.navigator.get_current_section()
            self._section_name = sec.get("title", "") if sec else ""
            await self._set_state(State.VIDEO_PLAYING)
        elif await self.navigator.detect_section_type() == SectionType.DOCUMENT:
            await self.navigator.handle_document_section()
            await asyncio.sleep(3)
            await self._set_state(State.SKIP_TO_NEXT)
        else:
            await asyncio.sleep(2)

    # ========= VIDEO_PLAYING =========

    async def _playing(self):
        st = await self.player.ensure_playing()
        if not st.get("ok"):
            await self._set_state(State.IDLE)
            return

        p = await self.player.get_progress()
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
                console.newline()
                await self._set_state(State.SKIP_TO_NEXT)
        else:
            console.print(f"  {self._section_name[:20]}  [加载...]")

    # ========= SKIP_TO_NEXT（直接在当前页找下一个未完成） =========

    async def _skip_to_next(self):
        """
        先尝试点下一个子标签；本节没了就 GOTO_NEXT_SECTION
        """
        # 先试子标签
        subtabs = await self.navigator.get_subtabs()
        if subtabs:
            active_idx = -1
            for i, t in enumerate(subtabs):
                if t.get("isActive"):
                    active_idx = i
                    break

            # 往后找第一个未完成的
            for i in range(active_idx + 1, len(subtabs)):
                if not subtabs[i].get("isCompleted"):
                    await self.page.evaluate(f"""
                        () => {{ const tabs = document.querySelectorAll('.plan-detailvideo .el-tabs__item.is-top');
                                 if (tabs[{i}]) tabs[{i}].click(); }}
                    """)
                    print(f"[跳过] → {subtabs[i]['label']}")
                    await asyncio.sleep(3)
                    await self._set_state(State.IDLE)
                    return

        # 本节子标签全完成了 → 跨节
        await self._set_state(State.GOTO_NEXT_SECTION)

    # ========= GOTO_NEXT_SECTION（回 notice 点继续学习） =========

    async def _goto_next_section(self):
        if not self.notice_url:
            await self._set_state(State.FINISHED)
            return

        print("[跨节] 回公告页点继续学习...")
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

        # 再跳过本节内已完成的子标签
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
