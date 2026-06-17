#!/usr/bin/env python3
"""
ZJOOC 刷课助手 v2.1 — 主入口
用法:
    python main.py                      # 智能模式（有Cookie→无头，无Cookie→有头）
    python main.py --headless           # 强制无头（无头验证码登录）
    python main.py --show               # 强制显示浏览器
    python main.py --speed 4            # 覆盖倍速
    python main.py --reset-session      # 清除登录缓存
"""

import argparse
import asyncio
import logging
import signal
import sys
from datetime import datetime
from pathlib import Path

import yaml

from src.browser import BrowserManager, STORAGE_STATE_PATH
from src.login import LoginHandler
from src.course_entry import CourseEntry
from src.state_machine import ZjoocStateMachine
from src.panel import ControlPanel

ROOT_DIR = Path(__file__).parent


def setup_logging():
    """同时输出到终端和日志文件"""
    log_path = ROOT_DIR / "runtime.log"
    # 每次运行覆盖旧日志
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"ZJOOC 刷课助手日志 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n{'='*50}\n")

    class TeeWriter:
        def __init__(self, *files):
            self.files = files
        def write(self, text):
            for f in self.files:
                f.write(text)
                f.flush()
        def flush(self):
            for f in self.files:
                f.flush()

    log_file = open(log_path, "a", encoding="utf-8")
    sys.stdout = TeeWriter(sys.stdout, log_file)
    sys.stderr = TeeWriter(sys.stderr, log_file)


def load_config(config_path: Path | None = None) -> dict:
    path = config_path or ROOT_DIR / "config.yaml"
    if not path.exists():
        print(f"配置文件不存在: {path}")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ZJOOC 在浙学刷课助手 v2.1",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py                     # 智能模式
  python main.py --headless          # 无头模式（验证码截图识别）
  python main.py --show              # 强制显示浏览器
  python main.py --speed 4 --mute
  python main.py --reset-session
        """,
    )
    parser.add_argument("--config", type=str, default=None)
    parser.add_argument("--speed", type=float, default=None)
    parser.add_argument("--mute", action="store_true", default=None)
    parser.add_argument("--no-mute", action="store_true", default=None)
    parser.add_argument("--headless", action="store_true", default=None, help="强制无头模式")
    parser.add_argument("--show", action="store_true", default=False, help="强制显示浏览器")
    parser.add_argument("--reset-session", action="store_true", default=False, help="清除登录缓存")
    return parser.parse_args()


def merge_config(config: dict, args: argparse.Namespace) -> dict:
    if args.speed is not None:
        config.setdefault("playback", {})["speed"] = args.speed
    if args.mute:
        config.setdefault("playback", {})["mute"] = True
    if args.no_mute:
        config.setdefault("playback", {})["mute"] = False
    return config


def resolve_headless(args: argparse.Namespace, config: dict) -> tuple[bool, str]:
    """
    解析无头模式，优先级: --show > --headless > config > 智能默认
    返回 (headless, reason)
    """
    if args.show:
        return False, "--show 强制显示"
    if args.headless:
        return True, "--headless 强制无头"
    if config.get("playback", {}).get("headless"):
        return True, "config.yaml 指定无头"

    # 智能默认：有 Cookie 则无头
    if STORAGE_STATE_PATH.exists():
        return True, "智能模式（已有Cookie → 无头）"
    else:
        return False, "智能模式（需要登录 → 显示浏览器）"


async def panel_action_poller(panel, state_machine, stop_event):
    while not stop_event.is_set():
        try:
            actions = await panel.poll_user_actions()
            for action in actions:
                if action["type"] == "speed":
                    await state_machine.set_speed(action["value"])
                elif action["type"] == "mute":
                    await state_machine.set_mute(action["value"])
                elif action["type"] == "pause":
                    if action["value"]:
                        await state_machine.pause_automation()
                    else:
                        await state_machine.resume_automation()
        except Exception:
            pass
        await asyncio.sleep(1)


async def panel_updater(panel, state_machine, stop_event):
    while not stop_event.is_set():
        try:
            section_info = await state_machine.navigator.get_current_section()
            section_name = section_info.get("title", "--") if section_info else "--"
            progress = await state_machine.player.get_progress()
            elapsed_str = "--:--"
            if state_machine.stats["start_time"]:
                delta = datetime.now() - state_machine.stats["start_time"]
                elapsed_str = f"{int(delta.total_seconds() // 60):02d}:{int(delta.total_seconds() % 60):02d}"
            panel_data = {
                "status": state_machine.state.value,
                "section": section_name,
                "videos": state_machine.stats["videos_watched"],
                "documents": state_machine.stats["documents_read"],
                "elapsed": elapsed_str,
            }
            if progress:
                panel_data["progress"] = progress.percent
                panel_data["currentTime"] = progress.current
                panel_data["duration"] = progress.duration
            await panel.update(**panel_data)
        except Exception:
            pass
        await asyncio.sleep(2)


async def main():
    setup_logging()
    args = parse_args()
    config = load_config(args.config)
    config = merge_config(config, args)

    if args.reset_session and STORAGE_STATE_PATH.exists():
        STORAGE_STATE_PATH.unlink()
        print("[重置] 已清除登录缓存")

    playback = config.get("playback", {})
    anti_detect_cfg = config.get("anti_detect", {})

    headless, headless_reason = resolve_headless(args, config)
    speed = playback.get("speed", 2.0)
    mute = playback.get("mute", True)
    poll_interval = playback.get("poll_interval", 3)

    simulate_activity = anti_detect_cfg.get("simulate_activity", True)
    activity_interval = anti_detect_cfg.get("activity_interval", 30)

    # ========= 启动信息 =========
    print("=" * 50)
    print("  ZJOOC 在浙学刷课助手 v2.1")
    print("=" * 50)
    print(f"  倍速: {speed}x  |  静音: {'是' if mute else '否'}")
    print(f"  浏览器: {'无头' if headless else '可见'} ({headless_reason})")
    print(f"  会话: {'有' if STORAGE_STATE_PATH.exists() else '无'}")
    print("=" * 50)

    page = None
    browser_manager = None

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def signal_handler():
        print("\n\n收到中断信号，退出...")
        stop_event.set()

    try:
        loop.add_signal_handler(signal.SIGINT, signal_handler)
        loop.add_signal_handler(signal.SIGTERM, signal_handler)
    except NotImplementedError:
        pass

    state_machine = None
    panel = None
    panel_poll_task = None
    panel_update_task = None

    try:
        # ---- Step 1: 登录（如果需要） ----
        has_session = STORAGE_STATE_PATH.exists()

        if not has_session:
            # 首次登录：可见浏览器 → 用户手动登录 → 检测完成 → 关浏览器
            first_browser = BrowserManager(headless=False)
            first_page = await first_browser.start()
            print("[启动] 可见浏览器（首次登录）")

            login_handler = LoginHandler(first_page, first_browser.context, "https://www.zjooc.cn/login")
            logged_in = await login_handler.ensure_logged_in(False)
            if not logged_in:
                print("登录失败，退出")
                await first_browser.close()
                return

            await first_browser.save_session()
            await first_browser.close()
            print("[登录] 浏览器已关闭，切换到后台模式\n")
            # 首次登录后强制无头（除非用户指定 --show）
            if not args.show:
                headless = True

        # ---- Step 2: 启动工作浏览器 ----
        browser_manager = BrowserManager(headless=headless, load_session=True)
        page = await browser_manager.start()
        mode = "可见" if not headless else "无头"
        print(f"[启动] 工作浏览器就绪（{mode}模式）")

        # 验证 cookie 有效
        await page.goto("https://www.zjooc.cn/ucenter/student/course/build/list", wait_until="domcontentloaded")
        await asyncio.sleep(1)
        if "login" in page.url.lower():
            print("Cookie 无效，请删除 auth_state.json 重试")
            return

        # ---- Step 3: 自动进入课程 ----
        print("\n[导航] 自动进入课程...")

        # 从课程列表页点击「进入学习」
        clicked = await page.evaluate("""
            () => {
                const btns = document.querySelectorAll('button');
                for (const b of btns) {
                    if (b.innerText?.trim() === '进入学习') { b.click(); return true; }
                }
                return false;
            }
        """)
        if not clicked:
            print("未找到「进入学习」按钮")
            notice_url = input("请手动输入课程公告页URL: ").strip()
            if not notice_url:
                return
            await page.goto(notice_url, wait_until="networkidle")
        else:
            await asyncio.sleep(3)

        # 记录当前 notice URL（后续跨节跳转用）
        notice_url = page.url
        print(f"[导航] notice URL: ...{notice_url[-40:]}")

        # 从 notice 页进入视频
        entry = CourseEntry(page)
        entered = await entry.enter_course(notice_url)

        if not entered:
            if headless:
                print("\n无头模式下导航失败，请用 --show 重试")
                return
            print("\n自动导航失败，请手动进入视频页")
            input("进入视频页后按 Enter 继续: ")
            if not await page.evaluate("() => !!document.querySelector('video, .base-asider')"):
                print("未检测到视频页面，退出")
                return

        # ---- Step 4: 注入面板（仅可见模式） ----
        if not headless:
            panel = ControlPanel(page)
            await panel.inject()

        # ---- Step 5: 启动状态机 ----
        state_machine = ZjoocStateMachine(
            page=page, notice_url=notice_url,
            speed=speed, mute=mute,
            poll_interval=poll_interval,
            enable_anti_detect=simulate_activity,
            mouse_interval=activity_interval,
        )

        print("\n" + "=" * 50)
        print("  开始自动学习！")
        if not headless:
            print("  右下角 齿轮按钮 → 控制面板")
        print("  Ctrl+C 退出")
        print("=" * 50 + "\n")

        # ---- Step 7: 运行 ----
        if not headless:
            panel_poll_task = asyncio.create_task(panel_action_poller(panel, state_machine, stop_event))
            panel_update_task = asyncio.create_task(panel_updater(panel, state_machine, stop_event))

        sm_task = asyncio.create_task(state_machine.run())

        tasks = [sm_task]
        if not headless:
            tasks.extend([panel_poll_task, panel_update_task])

        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

        if sm_task in done:
            try:
                await sm_task
            except Exception as e:
                print(f"\n状态机异常: {e}")
                import traceback
                traceback.print_exc()

        stop_event.set()
        for task in pending:
            task.cancel()

    except KeyboardInterrupt:
        print("\n\n用户中断")
        stop_event.set()
    except Exception as e:
        print(f"\n运行错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        stop_event.set()
        if panel_poll_task:
            panel_poll_task.cancel()
        if panel_update_task:
            panel_update_task.cancel()
        if panel:
            try:
                await panel.remove()
            except Exception:
                pass
        if state_machine:
            try:
                await state_machine.anti_detect.stop()
            except Exception:
                pass
        if browser_manager:
            await browser_manager.close()
        print("\n程序已退出")


if __name__ == "__main__":
    asyncio.run(main())
