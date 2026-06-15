"""
终端进度显示工具
提供 ASCII 进度条、时间格式化、单行动态刷新
"""

import sys
import os
import re

# 修复 Windows GBK 编码问题
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Windows 下启用 ANSI 转义序列支持
if sys.platform == "win32":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass


def terminal_width() -> int:
    """获取终端宽度"""
    try:
        return os.get_terminal_size().columns
    except Exception:
        return 80


class ProgressBar:
    """ASCII 进度条"""

    @staticmethod
    def draw(percent: float, width: int = 30) -> str:
        filled = int(width * percent / 100)
        empty = width - filled
        bar = "=" * filled + "-" * empty
        return f"[{bar}] {percent:5.1f}%"

    @staticmethod
    def format_time(seconds: float) -> str:
        if seconds < 0:
            seconds = 0
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m:02d}:{s:02d}"


class ConsoleLine:
    """
    终端单行动态刷新
    先清整行再写新内容，确保不残留
    """

    def __init__(self):
        self._ansi_ok = hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()

    @staticmethod
    def _strip_ansi(text: str) -> str:
        """去除 ANSI 转义序列，只留可见文本"""
        return re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)

    @staticmethod
    def _visible_width(text: str) -> int:
        """计算可见宽度（中文≈2，ASCII≈1）"""
        clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
        w = 0
        for ch in clean:
            if '一' <= ch <= '鿿' or '　' <= ch <= '〿' or '＀' <= ch <= '￯':
                w += 2
            else:
                w += 1
        return w

    @staticmethod
    def _truncate_visible(text: str, max_width: int) -> str:
        """截断文本使其显示宽度不超过 max_width"""
        w = 0
        result = []
        for ch in text:
            cw = 2 if ('一' <= ch <= '鿿' or '　' <= ch <= '〿') else 1
            if w + cw > max_width:
                break
            result.append(ch)
            w += cw
        return ''.join(result)

    def print(self, text: str):
        """
        原地刷新当前行: \r + 文本(截断到终端宽) + 空格补满
        """
        tw = max(terminal_width(), 60)
        vw = self._visible_width(text)
        if vw > tw:
            text = self._truncate_visible(text, tw)
            vw = self._visible_width(text)
        pad = max(0, tw - vw)
        sys.stdout.write(f"\r{text}{' ' * pad}")
        sys.stdout.flush()

    def newline(self):
        sys.stdout.write("\n")
        sys.stdout.flush()


# 模块级实例
console = ConsoleLine()
