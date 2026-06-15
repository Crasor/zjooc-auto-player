# 🎓 ZJOOC 刷课助手

自动播放 [在浙学](https://www.zjooc.cn) 课程视频的 Python 工具，基于 Playwright 浏览器自动化。

## ✨ 功能

- **自动登录** — 首次手动登录后 Cookie 持久化，后续免登录
- **倍速播放** — 0.5x ~ 16x 可调，静音后台运行
- **自动跳转** — 视频播完自动切下一节，支持章→节→子标签三级导航
- **反检测** — 覆写页面可见性 API，切换窗口不暂停
- **可视面板** — 右下角控制面板，实时调速/静音/暂停
- **图文处理** — 自动滚动图文并点击完成

## 🚀 快速开始

```bash
# 1. 创建 conda 环境
conda create -n zjooc python=3.11 -y

# 2. 安装依赖
pip install -r requirements.txt
playwright install chromium

# 3. 配置
cp config.example.yaml config.yaml
# 编辑 config.yaml 填入账号密码和课程URL

# 4. 运行
python main.py
```

## 📁 项目结构

```
├── main.py              # 入口
├── config.yaml           # 用户配置（不提交git）
├── config.example.yaml   # 配置模板
├── requirements.txt      # 依赖
└── src/
    ├── browser.py        # 浏览器管理 + 反检测注入
    ├── login.py          # Cookie 持久化登录
    ├── course_entry.py   # 从公告页导航到视频页
    ├── player.py         # 视频播放控制（CC Player）
    ├── navigator.py      # 章节导航（4层降级策略）
    ├── state_machine.py  # 核心状态机
    ├── anti_detect.py    # 运行时反检测
    └── panel.py          # 可视化控制面板
```

## ⌨️ 命令行参数

| 参数 | 说明 |
|------|------|
| `--speed 4` | 播放倍速 |
| `--headless` | 无头模式（不显示浏览器） |
| `--reset-session` | 清除登录缓存，重新登录 |
| `--course-url <URL>` | 直接指定课程URL |

## ⚠️ 免责声明

本工具仅供学习 Python 爬虫和浏览器自动化技术使用。请遵守平台使用条款，合理使用。

## 📄 License

MIT
