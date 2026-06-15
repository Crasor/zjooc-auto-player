# 🎓 ZJOOC 刷课助手 v2.1

自动播放 [在浙学](https://www.zjooc.cn) 课程视频，基于 Playwright 浏览器自动化。

## ✨ 功能

- **零配置** — 无需填写账号密码或课程 URL，首次浏览器手动登录后全自动
- **智能无头** — 登录后自动切后台运行，不弹浏览器窗口
- **自动跳转** — 视频播完直接切下一个，本节刷完自动跨节
- **跳过已完成** — 进入课程自动检测已完成视频并跳过
- **倍速静音** — 0.5x ~ 16x 可调，静音后台播放
- **反检测** — 覆写页面可见性 API，切窗口不暂停
- **终端进度条** — ASCII 进度条原地刷新，实时显示进度
- **Cookie 持久化** — 一次登录，后续免登

## 🚀 快速开始

```bash
# 1. 创建环境
conda create -n zjooc python=3.11 -y

# 2. 安装依赖
pip install -r requirements.txt
playwright install chromium

# 3. 运行（首次会弹出浏览器手动登录）
python main.py
```

无需任何配置，程序自动完成一切。

## ⌨️ 命令行参数

| 参数 | 说明 |
|------|------|
| `--speed 4` | 播放倍速 |
| `--mute` / `--no-mute` | 静音 / 不静音 |
| `--show` | 强制显示浏览器窗口 |
| `--headless` | 强制无头模式 |
| `--reset-session` | 清除登录缓存，重新登录 |

## ⚙️ 配置文件（可选）

`config.yaml` 可调整播放参数，不填也能正常运行：

```yaml
playback:
  speed: 2.0
  mute: true
  poll_interval: 3

anti_detect:
  simulate_activity: true
  activity_interval: 30
```

## 📁 项目结构

```
├── main.py              # 入口
├── config.yaml           # 配置文件（可选）
├── requirements.txt      # 依赖
├── run.bat              # Windows 快捷启动
└── src/
    ├── browser.py        # 浏览器管理 + 反检测注入
    ├── login.py          # 手动登录 + Cookie 持久化
    ├── course_entry.py   # 从公告页导航到视频页
    ├── player.py         # 视频播放控制（CC Player）
    ├── navigator.py      # 章节导航 + 已完成跳过
    ├── state_machine.py  # 核心状态机
    ├── anti_detect.py    # 运行时反检测
    ├── panel.py          # 可视化控制面板
    └── progress.py       # 终端进度条
```

## ⚠️ 免责声明

本工具仅供学习 Python 爬虫和浏览器自动化技术使用。

## 📄 License

MIT
