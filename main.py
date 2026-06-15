#!/usr/bin/env python3
"""
ZJOOC 刷课助手 v2.0 — 主入口
用法:
    python main.py                      # 使用 config.yaml 默认配置
    python main.py --speed 4            # 覆盖倍速
    python main.py --headless           # 无头模式
    python main.py --course-url <URL>   # 直接指定课程URL
    python main.py --reset-session      # 清除已保存的登录状态，重新登录
"""

import argparse
import asyncio
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


def load_config(config_path: Path | None = None) -> dict:
    path = config_path or ROOT_DIR / "config.yaml"
    if not path.exists():
        print(f"配置文件不存在: {path}")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ZJOOC 在浙学刷课助手 v2.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py
  python main.py --speed 4 --mute
  python main.py --headless
  python main.py --reset-session
        """,
    )
    parser.add_argument("--config", type=str, default=None, help="配置文件路径")
    parser.add_argument("--speed", type=float, default=None, help="播放倍速 (0.5~16)")
    parser.add_argument("--mute", action="store_true", default=None, help="静音播放")
    parser.add_argument("--no-mute", action="store_true", default=None, help="不静音")
    parser.add_argument("--headless", action="store_true", default=None, help="无头模式")
    parser.add_argument("--course-url", type=str, default=None, help="课程学习页面URL")
    parser.add_argument("--username", type=str, default=None, help="账号")
    parser.add_argument("--password", type=str, default=None, help="密码")
    parser.add_argument("--reset-session", action="store_true", default=False, help="清除登录缓存，重新登录")
    return parser.parse_args()


def merge_config(config: dict, args: argparse.Namespace) -> dict:
    if args.speed is not None:
        config.setdefault("playback", {})["speed"] = args.speed
    if args.mute:
        config.setdefault("playback", {})["mute"] = True
    if args.no_mute:
        config.setdefault("playback", {})["mute"] = False
    if args.headless:
        config.setdefault("playback", {})["headless"] = True
    if args.course_url:
        config.setdefault("course", {})["url"] = args.course_url
    if args.username:
        config.setdefault("account", {})["username"] = args.username
    if args.password:
        config.setdefault("account", {})["password"] = args.password
    return config


async def panel_action_poller(panel, state_machine, stop_event):
    """后台轮询面板用户操作"""
    while not stop_event.is_set():
        try:
            actions = await panel.poll_user_actions()
            for action in actions:
                if action["type"] == "speed":
                    await state_machine.set_speed(action["value"])
                    print(f"[面板] 倍速 → {action['value']}x")
                elif action["type"] == "mute":
                    await state_machine.set_mute(action["value"])
                    print(f"[面板] 静音 → {action['value']}")
                elif action["type"] == "pause":
                    if action["value"]:
                        await state_machine.pause_automation()
                    else:
                        await state_machine.resume_automation()
        except Exception:
            pass
        await asyncio.sleep(1)


async def panel_updater(panel, state_machine, stop_event):
    """后台定时更新面板数据"""
    while not stop_event.is_set():
        try:
            section_info = await state_machine.navigator.get_current_section()
            section_name = section_info.get("title", "--") if section_info else "--"

            progress = await state_machine.player.get_progress()

            elapsed_str = "--:--"
            if state_machine.stats["start_time"]:
                delta = datetime.now() - state_machine.stats["start_time"]
                mins = int(delta.total_seconds() // 60)
                secs = int(delta.total_seconds() % 60)
                elapsed_str = f"{mins:02d}:{secs:02d}"

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
    args = parse_args()
    config = load_config(args.config)
    config = merge_config(config, args)

    # 是否清除旧会话
    if args.reset_session and STORAGE_STATE_PATH.exists():
        STORAGE_STATE_PATH.unlink()
        print("[重置] 已清除登录缓存，将重新登录")

    account = config.get("account", {})
    username = account.get("username", "")
    password = account.get("password", "")

    playback = config.get("playback", {})
    anti_detect_cfg = config.get("anti_detect", {})

    headless = playback.get("headless", False)
    speed = playback.get("speed", 2.0)
    mute = playback.get("mute", True)
    poll_interval = playback.get("poll_interval", 3)

    simulate_activity = anti_detect_cfg.get("simulate_activity", True)
    activity_interval = anti_detect_cfg.get("activity_interval", 30)

    login_url = account.get("login_url", "https://www.zjooc.cn/login")

    # ========= 启动信息 =========
    print("=" * 50)
    print("  ZJOOC 在浙学刷课助手 v2.0")
    print("=" * 50)
    print(f"  倍速: {speed}x  |  静音: {'是' if mute else '否'}  |  无头: {'是' if headless else '否'}")
    print(f"  会话缓存: {'有' if STORAGE_STATE_PATH.exists() else '无（需登录）'}")
    print("=" * 50)

    # ========= 启动浏览器 =========
    has_session = STORAGE_STATE_PATH.exists()
    browser_manager = BrowserManager(headless=headless, load_session=has_session)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def signal_handler():
        print("\n\n收到中断信号，正在退出...")
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
        # ---- Step 1: 启动浏览器 ----
        page = await browser_manager.start()
        print("[启动] 浏览器就绪")

        # ---- Step 2: 登录 ----
        login_handler = LoginHandler(page, browser_manager.context, login_url)

        if has_session:
            # 尝试用已保存的 cookie 登录
            logged_in = await login_handler.try_load_session()
            if not logged_in:
                # Cookie 过期，手动登录
                logged_in = await login_handler.manual_login()

            if not logged_in:
                print("登录失败，程序退出")
                return
        else:
            # 首次运行，手动登录
            logged_in = await login_handler.manual_login()
            if not logged_in:
                print("登录失败，程序退出")
                return

        # 保存会话
        await browser_manager.save_session()

        # ---- Step 3: 获取课程URL ----
        course_url = config.get("course", {}).get("url", "")
        if not course_url:
            print("\n请输入课程页面URL（公告页或学习页均可）")
            print("（例如: https://www.zjooc.cn/ucenter/student/course/study/.../notice）")
            course_url = input("课程URL: ").strip()

        if not course_url:
            print("未提供课程URL，程序退出")
            return

        # ---- Step 4: 从课程入口进入视频播放页 ----
        print(f"\n[导航] 从课程公告页进入视频播放...")

        entry = CourseEntry(page)
        entered = await entry.enter_course(course_url)

        if not entered:
            print("\n⚠️ 自动导航失败，请手动在浏览器中进入视频播放页面")
            input("进入视频页后按 Enter 继续（或直接按 Enter 退出）: ")
            # 检查用户是否手动进入了
            if not await page.evaluate("() => !!document.querySelector('video, .base-asider')"):
                print("仍未检测到视频页面，退出")
                return
            print("[手动] 检测到视频页面，继续...")

        # ---- Step 5: 注入面板 ----
        panel = ControlPanel(page)
        await panel.inject()

        # ---- Step 6: 启动状态机 ----
        state_machine = ZjoocStateMachine(
            page=page,
            speed=speed,
            mute=mute,
            poll_interval=poll_interval,
            enable_anti_detect=simulate_activity,
            mouse_interval=activity_interval,
        )

        print("\n" + "=" * 50)
        print("  一切就绪，开始自动学习！")
        print("  右下角 齿轮按钮 打开控制面板")
        print("  Ctrl+C 退出")
        print("=" * 50 + "\n")

        # ---- Step 7: 后台任务 + 状态机 ----
        panel_poll_task = asyncio.create_task(panel_action_poller(panel, state_machine, stop_event))
        panel_update_task = asyncio.create_task(panel_updater(panel, state_machine, stop_event))
        sm_task = asyncio.create_task(state_machine.run())

        done, pending = await asyncio.wait(
            [sm_task, panel_poll_task, panel_update_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

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
