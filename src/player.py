"""
视频播放控制模块（基于真实 DOM 结构重写）

真实 DOM（从 course_study.html 分析）:
  播放器容器: .base_ccplayer > .CCH5playerContainer > .ccH5playerBox
  视频元素:   <video id="动态ID" src="blob:...">
  控制栏:     div.controlbgbar{动态后缀}

CC 播放器特点:
  - 视频 ID 动态生成
  - 使用 blob URL
  - 有自定义控制栏
"""

from dataclasses import dataclass
from playwright.async_api import Page


@dataclass
class VideoProgress:
    current: float
    duration: float
    is_finished: bool

    @property
    def percent(self) -> float:
        if self.duration <= 0:
            return 0.0
        return min(self.current / self.duration * 100, 100.0)


class PlayerController:
    """视频播放器控制器 — 适配 CC Player"""

    def __init__(self, page: Page, speed: float = 2.0, mute: bool = True):
        self.page = page
        self.speed = speed
        self.mute = mute

    # ========= 视频检测 =========

    async def has_video(self) -> bool:
        """检查页面是否有视频元素"""
        return await self.page.evaluate("""
            () => {
                const v = document.querySelector('video');
                return v !== null && v.readyState !== undefined;
            }
        """)

    async def wait_for_video(self, timeout: float = 15.0) -> bool:
        """等待视频元素出现"""
        try:
            await self.page.wait_for_selector("video", timeout=timeout * 1000)
            return True
        except Exception:
            # 也检查 CC 播放器容器
            try:
                await self.page.wait_for_selector(".ccH5playerBox video, .base_ccplayer video", timeout=3000)
                return True
            except Exception:
                return False

    # ========= 播放控制 =========

    async def play(self) -> dict:
        """确保视频播放"""
        return await self.page.evaluate("""
            () => {
                const v = document.querySelector('video');
                if (!v) return { ok: false, reason: 'no_video' };

                if (v.paused || v.ended) {
                    // 尝试 CC 播放器的播放按钮
                    const playBtn = document.querySelector('.prism-play-btn, .plyr__play, [class*="play-btn"], button[title*="播放"]');
                    if (playBtn) playBtn.click();

                    // 直接调用 play()
                    const p = v.play();
                    if (p) p.catch(() => {});
                }

                return {
                    ok: true,
                    paused: v.paused,
                    ended: v.ended,
                    muted: v.muted,
                    playbackRate: v.playbackRate,
                    currentTime: v.currentTime,
                    duration: v.duration
                };
            }
        """)

    async def ensure_playing(self) -> dict:
        """确保视频正在播放，暂停则恢复"""
        return await self.page.evaluate("""
            () => {
                const v = document.querySelector('video');
                if (!v) return { ok: false, reason: 'no_video' };

                if (v.paused && !v.ended) {
                    // 方法1: 尝试点击 CC 播放器的大播放按钮
                    const bigBtn = document.querySelector('.prism-big-play-btn, .plyr__play--large, [class*="big-play"]');
                    if (bigBtn) bigBtn.click();

                    // 方法2: 直接调用
                    const p = v.play();
                    if (p) p.catch(() => {});
                }

                // 如果视频已结束，不重播（由状态机处理跳转）

                // 确保设置生效
                v.muted = true;

                return {
                    ok: true,
                    paused: v.paused,
                    ended: v.ended,
                    playbackRate: v.playbackRate,
                    muted: v.muted
                };
            }
        """)

    # ========= 静音 =========

    async def set_mute(self, mute: bool = True) -> dict:
        """设置静音"""
        return await self.page.evaluate("""
            (mute) => {
                const v = document.querySelector('video');
                if (!v) return { ok: false, reason: 'no_video' };

                v.muted = mute;

                // CC 播放器静音按钮
                const muteBtn = document.querySelector(
                    '.prism-mute-btn, .plyr__mute, [class*="mute"], button[title*="静音"], button[title*="Mute"]'
                );
                if (muteBtn) {
                    const isMuted = v.muted;
                    if (isMuted !== mute) muteBtn.click();
                }

                return { ok: true, muted: v.muted };
            }
        """, mute)

    # ========= 倍速 =========

    async def set_speed(self, speed: float) -> dict:
        """设置播放倍速"""
        return await self.page.evaluate("""
            (speed) => {
                const v = document.querySelector('video');
                if (!v) return { ok: false, reason: 'no_video' };

                // 直接设置
                v.playbackRate = speed;

                // 查找 CC 播放器的倍速按钮
                const speedBtn = document.querySelector(
                    '.prism-speed-btn, .plyr__speed, [class*="speed"], button[title*="倍速"], button[title*="Speed"]'
                );
                if (speedBtn) {
                    speedBtn.click();
                    // 在弹出菜单中找对应倍速
                    setTimeout(() => {
                        const menu = document.querySelector(
                            '.prism-speed-menu, .plyr__menu, [class*="speed"][class*="menu"]'
                        );
                        if (menu) {
                            const items = menu.querySelectorAll('li, .item, span, div, button');
                            for (const item of items) {
                                const text = item.innerText || item.textContent || '';
                                if (text.includes(speed + 'x') || text.includes(speed + '.0x')) {
                                    item.click();
                                    break;
                                }
                            }
                        }
                        // 关闭菜单
                        if (speedBtn) speedBtn.click();
                    }, 300);
                }

                return { ok: true, playbackRate: v.playbackRate };
            }
        """, speed)

    # ========= 进度检测 =========

    async def get_progress(self) -> VideoProgress | None:
        """获取视频播放进度"""
        result = await self.page.evaluate("""
            () => {
                const v = document.querySelector('video');
                if (!v) return null;

                const current = v.currentTime || 0;
                const duration = v.duration || 0;

                // 如果 duration 无效，尝试从控制栏文本解析
                if (duration <= 0 || isNaN(duration)) {
                    // CC 播放器时间显示
                    const timeDisplay = document.querySelector(
                        '.prism-time-display, .plyr__time, [class*="time-display"], [class*="duration"]'
                    );
                    if (timeDisplay) {
                        const text = timeDisplay.innerText || timeDisplay.textContent || '';
                        const match = text.match(/(\d{1,2}:\d{2})\s*\/\s*(\d{1,2}:\d{2})/);
                        if (match) {
                            const parseTime = (t) => {
                                const parts = t.split(':').map(Number);
                                return parts[0] * 60 + parts[1];
                            };
                            return {
                                currentTime: parseTime(match[1]),
                                duration: parseTime(match[2]),
                                valid: true
                            };
                        }
                    }
                    return { currentTime: current, duration: 0, valid: false };
                }

                return { currentTime: current, duration: duration, valid: true };
            }
        """)

        if not result or not result.get("valid"):
            return None

        current = result["currentTime"]
        duration = result["duration"]
        is_finished = duration > 0 and current >= duration - 2.0

        return VideoProgress(current=current, duration=duration, is_finished=is_finished)

    # ========= 综合状态 =========

    async def get_state(self) -> dict:
        """获取播放器完整状态"""
        return await self.page.evaluate("""
            () => {
                const v = document.querySelector('video');
                if (!v) return { hasVideo: false };

                const ccContainer = document.querySelector('.ccH5playerBox, .base_ccplayer');

                return {
                    hasVideo: true,
                    hasCCPlayer: !!ccContainer,
                    paused: v.paused,
                    ended: v.ended,
                    muted: v.muted,
                    playbackRate: v.playbackRate,
                    currentTime: v.currentTime,
                    duration: v.duration,
                    readyState: v.readyState,
                    src: v.currentSrc || v.src || '(blob)'
                };
            }
        """)
