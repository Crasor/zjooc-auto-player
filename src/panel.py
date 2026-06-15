"""
可视化配置面板模块
向课程页面注入一个右下角可折叠的控制面板

面板功能：
- 显示当前状态和章节名
- 播放进度条
- 倍速滑块调节
- 静音开关
- 暂停/继续按钮
- 统计信息
"""

import asyncio
from playwright.async_api import Page, JSHandle


PANEL_HTML = """
<div id="zjooc-helper-panel" style="
    position: fixed;
    bottom: 20px;
    right: 20px;
    z-index: 99999;
    font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif;
">
    <!-- 折叠按钮 -->
    <div id="zjooc-panel-toggle" style="
        width: 48px; height: 48px;
        background: linear-gradient(135deg, #409EFF, #66B1FF);
        border-radius: 50%;
        display: flex; align-items: center; justify-content: center;
        cursor: pointer;
        box-shadow: 0 4px 16px rgba(64,158,255,0.4);
        color: white;
        font-size: 22px;
        float: right;
        user-select: none;
        transition: transform 0.2s;
    " title="ZJOOC 刷课助手">⚙</div>

    <!-- 面板主体 -->
    <div id="zjooc-panel-body" style="
        display: none;
        background: white;
        border-radius: 12px;
        box-shadow: 0 8px 32px rgba(0,0,0,0.15);
        padding: 20px;
        width: 300px;
        margin-bottom: 12px;
        clear: both;
    ">
        <!-- 标题栏 -->
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
            <span style="font-size:16px;font-weight:700;color:#303133;">
                🎓 刷课助手
            </span>
            <span id="zjooc-status-badge" style="
                font-size:11px;padding:2px 10px;border-radius:10px;
                background:#E6F7E6;color:#52C41A;
            ">运行中</span>
        </div>

        <!-- 当前章节 -->
        <div style="margin-bottom:12px;">
            <div style="font-size:12px;color:#909399;margin-bottom:4px;">当前章节</div>
            <div id="zjooc-section-name" style="
                font-size:13px;color:#303133;
                white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
            ">--</div>
        </div>

        <!-- 进度条 -->
        <div style="margin-bottom:12px;">
            <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
                <span style="font-size:12px;color:#909399;">播放进度</span>
                <span id="zjooc-progress-text" style="font-size:12px;color:#409EFF;">0%</span>
            </div>
            <div style="
                width:100%;height:6px;background:#F0F2F5;border-radius:3px;overflow:hidden;
            ">
                <div id="zjooc-progress-bar" style="
                    width:0%;height:100%;
                    background:linear-gradient(90deg,#409EFF,#66B1FF);
                    border-radius:3px;
                    transition:width 0.5s;
                "></div>
            </div>
            <div id="zjooc-time-text" style="
                font-size:11px;color:#C0C4CC;margin-top:2px;
            ">00:00 / 00:00</div>
        </div>

        <!-- 倍速调节 -->
        <div style="margin-bottom:12px;">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <span style="font-size:12px;color:#909399;">播放倍速</span>
                <span id="zjooc-speed-label" style="
                    font-size:14px;font-weight:700;color:#409EFF;
                ">2.0x</span>
            </div>
            <input type="range" id="zjooc-speed-slider"
                min="0.5" max="16" step="0.5" value="2.0"
                style="width:100%;margin-top:4px;accent-color:#409EFF;"
            />
            <div style="display:flex;justify-content:space-between;font-size:10px;color:#C0C4CC;">
                <span>0.5x</span><span>4x</span><span>8x</span><span>16x</span>
            </div>
        </div>

        <!-- 控制按钮行 -->
        <div style="display:flex;gap:8px;margin-bottom:12px;">
            <button id="zjooc-btn-mute" style="
                flex:1;padding:8px;border:1px solid #DCDFE6;border-radius:8px;
                background:#fff;cursor:pointer;font-size:12px;color:#606266;
            ">🔊 已静音</button>
            <button id="zjooc-btn-pause" style="
                flex:1;padding:8px;border:none;border-radius:8px;
                background:#409EFF;color:#fff;cursor:pointer;font-size:12px;
            ">⏯ 暂停</button>
        </div>

        <!-- 统计 -->
        <div style="
            border-top:1px solid #F0F2F5;padding-top:8px;
            display:flex;justify-content:space-around;
            font-size:11px;color:#909399;
        ">
            <span>📹 <span id="zjooc-stat-videos">0</span> 视频</span>
            <span>📄 <span id="zjooc-stat-docs">0</span> 图文</span>
            <span>⏱ <span id="zjooc-stat-time">00:00</span></span>
        </div>
    </div>
</div>

<script>
(function() {
    // ---- 面板折叠 ----
    const toggle = document.getElementById('zjooc-panel-toggle');
    const body = document.getElementById('zjooc-panel-body');
    let panelOpen = false;

    toggle.addEventListener('click', () => {
        panelOpen = !panelOpen;
        body.style.display = panelOpen ? 'block' : 'none';
        toggle.style.transform = panelOpen ? 'rotate(90deg)' : 'rotate(0deg)';
    });

    // ---- 倍速滑块 ----
    const speedSlider = document.getElementById('zjooc-speed-slider');
    const speedLabel = document.getElementById('zjooc-speed-label');

    speedSlider.addEventListener('input', () => {
        const val = parseFloat(speedSlider.value);
        speedLabel.textContent = val.toFixed(1) + 'x';
        // 通知 Playwright 端（通过全局回调）
        if (window.__zjooc_on_speed_change) {
            window.__zjooc_on_speed_change(val);
        }
    });

    // ---- 静音按钮 ----
    const muteBtn = document.getElementById('zjooc-btn-mute');
    let isMuted = true;
    muteBtn.addEventListener('click', () => {
        isMuted = !isMuted;
        muteBtn.textContent = isMuted ? '🔇 已静音' : '🔊 有声音';
        if (window.__zjooc_on_mute_change) {
            window.__zjooc_on_mute_change(isMuted);
        }
    });

    // ---- 暂停按钮 ----
    const pauseBtn = document.getElementById('zjooc-btn-pause');
    let isPaused = false;
    pauseBtn.addEventListener('click', () => {
        isPaused = !isPaused;
        pauseBtn.textContent = isPaused ? '▶ 继续' : '⏯ 暂停';
        if (window.__zjooc_on_pause_change) {
            window.__zjooc_on_pause_change(isPaused);
        }
    });

    // ---- 暴露给 Playwright 的更新函数 ----
    window.__zjooc_update_panel = function(data) {
        if (data.status !== undefined) {
            const badge = document.getElementById('zjooc-status-badge');
            const colors = {
                'idle': { bg: '#FFF7E6', color: '#FAAD14', text: '等待中' },
                'video_playing': { bg: '#E6F7E6', color: '#52C41A', text: '播放中' },
                'document_reading': { bg: '#E6F0FF', color: '#1890FF', text: '阅读中' },
                'navigating': { bg: '#FFF0F6', color: '#EB2F96', text: '跳转中' },
                'finished': { bg: '#F0F2F5', color: '#909399', text: '已完成' },
            };
            const c = colors[data.status] || colors['idle'];
            badge.style.background = c.bg;
            badge.style.color = c.color;
            badge.textContent = c.text;
        }
        if (data.section !== undefined) {
            document.getElementById('zjooc-section-name').textContent = data.section;
        }
        if (data.progress !== undefined) {
            document.getElementById('zjooc-progress-bar').style.width = data.progress + '%';
            document.getElementById('zjooc-progress-text').textContent =
                data.progress.toFixed(0) + '%';
        }
        if (data.currentTime !== undefined && data.duration !== undefined) {
            const fmt = (s) => {
                const m = Math.floor(s / 60);
                const sec = Math.floor(s % 60);
                return String(m).padStart(2,'0') + ':' + String(sec).padStart(2,'0');
            };
            document.getElementById('zjooc-time-text').textContent =
                fmt(data.currentTime) + ' / ' + fmt(data.duration);
        }
        if (data.videos !== undefined) {
            document.getElementById('zjooc-stat-videos').textContent = data.videos;
        }
        if (data.documents !== undefined) {
            document.getElementById('zjooc-stat-docs').textContent = data.documents;
        }
        if (data.elapsed !== undefined) {
            document.getElementById('zjooc-stat-time').textContent = data.elapsed;
        }
    };

    // 注册全局回调占位
    window.__zjooc_on_speed_change = null;
    window.__zjooc_on_mute_change = null;
    window.__zjooc_on_pause_change = null;
})();
</script>
"""


class ControlPanel:
    """
    可视化控制面板
    注入到课程页面右下角，通过 page.evaluate 更新数据
    """

    def __init__(self, page: Page):
        self.page = page
        self._injected = False
        self._speed_callback = None
        self._mute_callback = None
        self._pause_callback = None

    async def inject(self):
        """向页面注入面板 HTML/CSS/JS"""
        if self._injected:
            return

        await self.page.evaluate(f"""
            () => {{
                // 避免重复注入
                if (document.getElementById('zjooc-helper-panel')) return;

                const container = document.createElement('div');
                container.innerHTML = `{PANEL_HTML}`;
                document.body.appendChild(container.firstElementChild);
            }}
        """)
        self._injected = True
        print("[面板] ✓ 已注入控制面板（右下角 ⚙ 按钮）")

        # 监听面板回调
        await self._register_callbacks()

    async def _register_callbacks(self):
        """注册面板 UI 事件 → Python 的回调"""
        # 倍速变化
        await self.page.evaluate("""
            () => {
                window.__zjooc_on_speed_change = (val) => {
                    window.__zjooc_pending_speed = val;
                };
                window.__zjooc_on_mute_change = (muted) => {
                    window.__zjooc_pending_mute = muted;
                };
                window.__zjooc_on_pause_change = (paused) => {
                    window.__zjooc_pending_pause = paused;
                };
            }
        """)

    async def poll_user_actions(self) -> list[dict]:
        """轮询面板上的用户操作，返回待处理的动作列表"""
        actions = []

        result = await self.page.evaluate("""
            () => {
                const actions = [];
                if (window.__zjooc_pending_speed !== undefined) {
                    actions.push({ type: 'speed', value: window.__zjooc_pending_speed });
                    delete window.__zjooc_pending_speed;
                }
                if (window.__zjooc_pending_mute !== undefined) {
                    actions.push({ type: 'mute', value: window.__zjooc_pending_mute });
                    delete window.__zjooc_pending_mute;
                }
                if (window.__zjooc_pending_pause !== undefined) {
                    actions.push({ type: 'pause', value: window.__zjooc_pending_pause });
                    delete window.__zjooc_pending_pause;
                }
                return actions;
            }
        """)
        return result

    async def update(self, **kwargs):
        """更新面板显示数据"""
        if not self._injected:
            return

        try:
            await self.page.evaluate(
                "(data) => { if (window.__zjooc_update_panel) window.__zjooc_update_panel(data); }",
                kwargs,
            )
        except Exception:
            pass  # 页面可能已导航

    async def remove(self):
        """移除面板"""
        if not self._injected:
            return
        try:
            await self.page.evaluate("""
                () => {
                    const el = document.getElementById('zjooc-helper-panel');
                    if (el) el.remove();
                }
            """)
        except Exception:
            pass
        self._injected = False
