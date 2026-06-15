"""
反检测模块
运行时注入页面，对抗平台的播放检测机制：
1. 防止切标签页暂停视频（覆写 visibility API）
2. 模拟用户鼠标活动（防止无操作检测）
3. 定时重设倍速和静音（防止播放器回写覆盖）
"""

import asyncio
from playwright.async_api import Page


class AntiDetect:
    """运行时反检测注入器

    在浏览器 init_script 之外提供额外的运行时注入能力。
    init_script 处理静态 API 覆写，本类处理周期性任务。
    """

    def __init__(
        self,
        page: Page,
        enable_mouse_sim: bool = True,
        mouse_interval: float = 30.0,
        enable_speed_guard: bool = True,
        speed_guard_interval: float = 5.0,
        speed: float = 2.0,
        mute: bool = True,
    ):
        self.page = page
        self.enable_mouse_sim = enable_mouse_sim
        self.mouse_interval = mouse_interval
        self.enable_speed_guard = enable_speed_guard
        self.speed_guard_interval = speed_guard_interval
        self.speed = speed
        self.mute = mute
        self._tasks: list[asyncio.Task] = []

    async def start(self):
        """启动所有反检测后台任务"""
        if self.enable_mouse_sim:
            task = asyncio.create_task(self._mouse_simulator())
            self._tasks.append(task)

        if self.enable_speed_guard:
            task = asyncio.create_task(self._speed_guardian())
            self._tasks.append(task)

        print(f"[反检测] 已启动 {len(self._tasks)} 个保护任务")

    async def stop(self):
        """停止所有后台任务"""
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        print("[反检测] 已停止所有保护任务")

    async def _mouse_simulator(self):
        """定时模拟鼠标移动事件，防止无操作检测"""
        while True:
            try:
                await asyncio.sleep(self.mouse_interval)
                await self.page.evaluate("""
                    () => {
                        const x = Math.random() * window.innerWidth;
                        const y = Math.random() * window.innerHeight;
                        document.dispatchEvent(new MouseEvent('mousemove', {
                            clientX: x, clientY: y,
                            screenX: x, screenY: y,
                            bubbles: true, cancelable: true
                        }));
                    }
                """)
            except asyncio.CancelledError:
                break
            except Exception:
                # 页面可能已关闭，忽略错误
                pass

    async def _speed_guardian(self):
        """定时守卫：确保倍速和静音设置没有被播放器回写覆盖"""
        while True:
            try:
                await asyncio.sleep(self.speed_guard_interval)
                await self.page.evaluate("""
                    (speed, muted) => {
                        const v = document.querySelector('video');
                        if (!v) return;
                        if (v.playbackRate !== speed) {
                            v.playbackRate = speed;
                        }
                        if (v.muted !== muted) {
                            v.muted = muted;
                        }
                    }
                """, self.speed, self.mute)
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    @staticmethod
    async def inject_visibility_override(page: Page):
        """运行时重新注入可见性覆写（在页面导航后可能需要）"""
        await page.evaluate("""
            () => {
                // 重新覆写（某些 SPA 页面可能重置了这些属性）
                try {
                    Object.defineProperty(document, 'hidden', {
                        value: false,
                        writable: false,
                        configurable: false,
                    });
                } catch(e) {}

                try {
                    Object.defineProperty(document, 'visibilityState', {
                        value: 'visible',
                        writable: false,
                        configurable: false,
                    });
                } catch(e) {}
            }
        """)

    @staticmethod
    async def inject_autoplay_unlock(page: Page):
        """解除浏览器自动播放限制（需要先有用户交互或静音）"""
        await page.evaluate("""
            () => {
                // 尝试解锁音频上下文
                const videos = document.querySelectorAll('video');
                videos.forEach(v => {
                    v.muted = true;
                    const p = v.play();
                    if (p) p.catch(() => {});
                });

                // 尝试恢复被挂起的 AudioContext
                if (window.AudioContext || window.webkitAudioContext) {
                    const AC = window.AudioContext || window.webkitAudioContext;
                    // 遍历所有可能的 AudioContext 实例
                    // （实际实现中这很难，但尝试一下）
                }
            }
        """)
