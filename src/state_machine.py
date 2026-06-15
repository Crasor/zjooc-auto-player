"""
核心状态机模块（基于真实 DOM 重写）

状态流转:
  IDLE → 检测内容类型
    → VIDEO_PLAYING (有视频)
    → DOCUMENT_READING (图文)
    → QUIZ_WAITING (测验)
  VIDEO_PLAYING → 播放完成 → NEXT_SUBTAB → 尝试节内下一个子标签
  NEXT_SECTION → 尝试侧栏下一节
  NAVIGATING → 等待加载 → IDLE
  FINISHED → 全部完成

关键变化：节内可能有多个子标签 (sub-tabs)，需要逐个播放
"""

import asyncio
from enum import Enum
from datetime import datetime

from playwright.async_api import Page

from src.player import PlayerController
from src.navigator import Navigator, SectionType
from src.anti_detect import AntiDetect


class State(Enum):
    IDLE = "idle"
    VIDEO_PLAYING = "video_playing"
    DOCUMENT_READING = "document_reading"
    QUIZ_WAITING = "quiz_waiting"
    NEXT_SUBTAB = "next_subtab"
    NEXT_SECTION = "next_section"
    NAVIGATING = "navigating"
    FINISHED = "finished"


class ZjoocStateMachine:
    """在浙学刷课状态机 v2.0"""

    def __init__(
        self,
        page: Page,
        speed: float = 2.0,
        mute: bool = True,
        poll_interval: float = 3.0,
        enable_anti_detect: bool = True,
        mouse_interval: float = 30.0,
    ):
        self.page = page
        self.state = State.IDLE
        self.poll_interval = poll_interval
        self.speed = speed
        self.mute = mute

        self.player = PlayerController(page, speed=speed, mute=mute)
        self.navigator = Navigator(page)
        self.anti_detect = AntiDetect(
            page,
            enable_mouse_sim=enable_anti_detect,
            mouse_interval=mouse_interval,
            speed=speed,
            mute=mute,
        )

        self.stats = {
            "videos_watched": 0,
            "documents_read": 0,
            "start_time": None,
        }

        self._on_state_change = None
        self._on_progress_update = None
        self._retry_count = 0
        self._max_retries = 5

    def on_state_change(self, callback):
        self._on_state_change = callback

    def on_progress_update(self, callback):
        self._on_progress_update = callback

    async def _set_state(self, new_state: State):
        old = self.state
        self.state = new_state
        if old != new_state:
            print(f"[状态] {old.value} → {new_state.value}")
            if self._on_state_change:
                await self._on_state_change(new_state.value)

    async def _notify_progress(self, current: float, duration: float):
        pct = (current / duration * 100) if duration > 0 else 0
        if self._on_progress_update:
            await self._on_progress_update(current, duration, pct)

    # ========= 主循环 =========

    async def run(self):
        self.stats["start_time"] = datetime.now()
        await self.anti_detect.start()

        print(f"\n[状态机] 启动，轮询间隔: {self.poll_interval}s")

        while self.state != State.FINISHED:
            try:
                await self._tick()
            except Exception as e:
                print(f"[状态机] 异常: {e}")
                self._retry_count += 1
                if self._retry_count > self._max_retries:
                    print("[状态机] 重试次数过多，跳过当前节")
                    await self._set_state(State.NEXT_SECTION)
                    self._retry_count = 0
                await asyncio.sleep(self.poll_interval)

        await self.anti_detect.stop()
        elapsed = datetime.now() - self.stats["start_time"]
        print(f"\n[状态机] 🎉 课程全部完成！")
        print(f"  视频: {self.stats['videos_watched']} | 图文: {self.stats['documents_read']}")
        print(f"  耗时: {elapsed}")

    async def _tick(self):
        if self.state == State.IDLE:
            await self._handle_idle()
        elif self.state == State.VIDEO_PLAYING:
            await self._handle_video_playing()
        elif self.state == State.DOCUMENT_READING:
            await self._handle_document_reading()
        elif self.state == State.QUIZ_WAITING:
            await self._handle_quiz_waiting()
        elif self.state == State.NEXT_SUBTAB:
            await self._handle_next_subtab()
        elif self.state == State.NEXT_SECTION:
            await self._handle_next_section()
        elif self.state == State.NAVIGATING:
            await self._handle_navigating()

        await asyncio.sleep(self.poll_interval)

    # ========= IDLE =========

    async def _handle_idle(self):
        """等待页面加载，检测内容类型"""
        section_type = await self.navigator.detect_section_type()

        if section_type == SectionType.VIDEO:
            has_video = await self.player.wait_for_video(timeout=8.0)
            if has_video:
                await self.player.set_mute(self.mute)
                await self.player.set_speed(self.speed)
                await self.player.play()
                self._retry_count = 0
                await self._set_state(State.VIDEO_PLAYING)
            else:
                print("[IDLE] 未检测到视频，等待中...")
        elif section_type == SectionType.DOCUMENT:
            await self._set_state(State.DOCUMENT_READING)
        elif section_type == SectionType.QUIZ:
            await self._set_state(State.QUIZ_WAITING)
        else:
            print("[IDLE] 类型未知，等待加载...")
            await self.navigator.wait_for_page_ready(timeout=5.0)

    # ========= VIDEO_PLAYING =========

    async def _handle_video_playing(self):
        """监控视频播放进度"""
        state = await self.player.ensure_playing()
        if not state.get("ok"):
            await self._set_state(State.IDLE)
            return

        progress = await self.player.get_progress()

        if progress and progress.duration > 0:
            await self._notify_progress(progress.current, progress.duration)
            print(f"[播放] {progress.current:.0f}s / {progress.duration:.0f}s ({progress.percent:.0f}%)")

            if progress.is_finished:
                self.stats["videos_watched"] += 1
                await self._set_state(State.NEXT_SUBTAB)
        else:
            # 无法读取进度，可能视频还没加载
            print(f"[播放] 等待视频加载...")

    # ========= DOCUMENT =========

    async def _handle_document_reading(self):
        """处理图文"""
        result = await self.navigator.handle_document_section()
        self.stats["documents_read"] += 1
        print(f"[图文] {'已点击完成按钮' if result.get('clicked') else '已滚动到底部'}")
        await asyncio.sleep(3)
        await self._set_state(State.NEXT_SUBTAB)

    # ========= QUIZ =========

    async def _handle_quiz_waiting(self):
        """测验需人工处理"""
        await self.navigator.handle_quiz_section()
        await self._set_state(State.NEXT_SUBTAB)

    # ========= NEXT_SUBTAB =========

    async def _handle_next_subtab(self):
        """尝试导航到节内下一个子标签"""
        result = await self.navigator.click_next_subtab()

        if result.success:
            print(f"[子标签] 跳转: {result.reason}")
            await self._set_state(State.NAVIGATING)
        else:
            # 当前节无更多子标签 → 尝试下一节
            print("[子标签] 本节无更多子标签 → 尝试下一节")
            await self._set_state(State.NEXT_SECTION)

    # ========= NEXT_SECTION =========

    async def _handle_next_section(self):
        """导航到侧栏的下一节"""
        result = await self.navigator.click_next_section()

        if result.finished:
            print("[导航] 全部章节完成！")
            await self._set_state(State.FINISHED)
        elif result.success:
            print(f"[导航] 跳转: {result.reason}")
            await self._set_state(State.NAVIGATING)
        else:
            print(f"[导航] 未知状态: {result.reason}")
            await asyncio.sleep(2)

    # ========= NAVIGATING =========

    async def _handle_navigating(self):
        """等待页面加载"""
        ready = await self.navigator.wait_for_page_ready(timeout=10.0)
        if ready:
            await AntiDetect.inject_visibility_override(self.page)
            await AntiDetect.inject_autoplay_unlock(self.page)
            await asyncio.sleep(2)
            await self._set_state(State.IDLE)
        else:
            print("[跳转] 页面加载超时，继续等待...")

    # ========= 控制接口 =========

    async def pause_automation(self):
        print("[控制] 暂停自动化")
        await self.player.page.evaluate("() => { const v = document.querySelector('video'); if (v) v.pause(); }")

    async def resume_automation(self):
        print("[控制] 恢复自动化")
        await self._set_state(State.IDLE)

    async def set_speed(self, speed: float):
        self.speed = speed
        self.anti_detect.speed = speed
        await self.player.set_speed(speed)

    async def set_mute(self, mute: bool):
        self.mute = mute
        self.anti_detect.mute = mute
        await self.player.set_mute(mute)
