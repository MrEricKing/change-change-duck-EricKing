# <img src="docs/图片1.png" alt="路线改改鸭" height="40" /> 路线改改鸭

> **把抖音视频里的"种草"，自动拼成可视化的旅行地图。**
> 上传一段抖音/B站旅游视频 → 自动转写 + 关键帧 OCR + LLM 规划 → 输出按天分色路线 + 站点 emoji 标记 + 评分卡 + 必去/避雷清单。

课程报告见 `Report/`：
[Markdown](<Report/第19组 金之杭 12525032.md>) /
[PDF](<Report/第19组 金之杭 12525032.pdf>)

当前仓库包含小组项目基础功能，以及个人课程实践扩展：`STEP 3 · 旅行后记录`、历史偏好库、旅行后攻略和投递视频评价。

## 界面预览

**当前课程版主界面**：在原有 `STEP 1 · 投递视频`、地图和 `STEP 2 · 故事手账` 基础上，右侧新增 `STEP 3 · 旅行后记录`。

![当前课程版主界面：含 Step 3 旅行后记录](docs/演示1.png)

**地图与路线展示**：小组项目的基础能力，用地图呈现 AI 生成的地点分布、按天路线和跨城市交通关系。

![地图与路线展示](docs/演示2.png)

**每日攻略卡片**：小组项目的基础能力，用故事手账形式展示每天每一站的时间、预算、交通、活动和提示。

![每日攻略卡片](docs/演示3.png)

---

## ✨ 功能一览

- 🎬 **多模态视频解析**：yt-dlp 下载 + Whisper 转写 + 关键帧 OCR + 视频元数据
- 🧠 **LLM 路线规划**：兼容 OpenAI 接口，输出结构化攻略（人群/预算/强度可定制）
- 🗺 **Folium + OSM 地图**：每个站点 emoji 大圆贴纸 + 永久地名标签 + 跨天交通方式标注
- 🚇 **路线优化**：贪心最近邻自动重排，每天不交叉、按地铁/公交线路串联
- 📍 **地理编码**：高德 / LLM / Nominatim 三级兜底自动补 lat/lng
- ✍️ **一句话改路线**：「删掉武康路，加上田子坊」直接重算
- 🧾 **旅行后记录**：记录实际去了哪里、没去成哪里、花费、节奏、照片和真实体验
- 🧠 **历史偏好库**：把旅行复盘提炼成偏好，下一次规划时可主动选择并注入
- 📝 **旅行后攻略 / 视频评价**：基于真实体验生成复盘攻略，并评价投递视频是否可靠
- 🔑 **可配置模型接口**：支持网页填写 API Key / Base URL / Model，并提供 DeepSeek V4 Pro 快捷按钮
- 📦 **一键打包**：导出 zip（含 guide.json/md、map.html、关键帧）

---

## 🚀 快速开始（4 步）

### 1. 安装 Python 3.10+

下载 https://www.python.org/downloads/ —— 建议 3.10 / 3.11 / 3.12。
安装时勾选 **"Add Python to PATH"**。

> 不需要单独安装 FFmpeg，依赖里的 `imageio-ffmpeg` 会自动下载二进制。

### 2. 创建虚拟环境 + 装依赖

打开终端（Windows 用 PowerShell / CMD / Git Bash 都行），cd 到项目目录：

**Windows：**
```cmd
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

**Mac / Linux：**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

如果使用 Conda，也可以：
```bash
conda create -n change-change-duck python=3.11
conda activate change-change-duck
pip install -r requirements.txt
```

首次安装约 200MB（含 numpy、opencv、curl-cffi 等）；如有可选包失败可忽略。

### 3. 配置 API Key（任选一种）

本工具支持任何兼容 OpenAI Chat Completions + Whisper 的接口（OpenAI 官方、`openai-next.com`、`vectrust` 等）。

**方式 A · 环境变量（推荐）：**

Windows PowerShell：
```powershell
$env:VECTRUST_API_KEY = "sk-你的key"
$env:OPENAI_BASE_URL  = "https://api.openai-next.com"  # 可选
$env:OPENAI_MODEL     = "gpt-4o-mini"                  # 可选
```

Mac / Linux：
```bash
export VECTRUST_API_KEY="sk-你的key"
export OPENAI_BASE_URL="https://api.openai-next.com"
export OPENAI_MODEL="gpt-4o-mini"
```

DeepSeek 示例：
```bash
export VECTRUST_API_KEY="你的 DeepSeek Key"
export OPENAI_BASE_URL="https://api.deepseek.com"
export OPENAI_MODEL="deepseek-v4-pro"
```

**方式 B · 网页填入**：启动后在左侧表单填写 `API Key`、`Base URL` 和 `Model`。如果使用 DeepSeek，可直接点 **使用 DeepSeek V4 Pro**。

### 4. 启动

**Windows**：双击根目录的 `run.bat`
**Mac / Linux**：`bash run.sh`

或手动：
```bash
python server.py
```

终端看到这一行说明启动成功：
```
🌐 http://127.0.0.1:5000
```

浏览器打开 **http://127.0.0.1:5000** 即可。

---

## 📖 使用方法

打开页面后默认展示 **长三角样例攻略**；右上角 `🔄` 可重置样例，`💾` 保存当前攻略，`📂` 打开上次保存的攻略。当前课程演示中，`📂` 可打开已保存的东京路线案例。

```
┌────────────────────────────────────────────────────────────────────────────┐
│ 路线改改鸭 Travel Map                 🗓 天数  💴 预算  📍 城市  🎒 强度   │
├────────────┬──────────────────────────────┬──────────────┬───────────────┤
│ STEP 1     │                              │ STEP 2       │ STEP 3        │
│ 投递视频    │        🗺 Folium 地图        │ 故事手账       │ 旅行后记录      │
│ 参数/API    │  地点贴纸 + 彩色路线 + 交通  │ 每天/每站卡片   │ 复盘/照片/偏好库 │
│ 历史偏好入口 │                              │              │ 攻略/视频评价    │
└────────────┴──────────────────────────────┴──────────────┴───────────────┘
```

### 三种典型用法

#### 🅰 只看现有样例（无需 API Key）
直接看默认页 → 操作地图、查看行程卡。

#### 🅱 用一句话改路线（需 API Key）
在 `STEP 1` 的「补充偏好」中输入想法，点 **按已选偏好调整路线（不重传视频）**。也可以勾选历史偏好后不写补充偏好，直接让 AI 按已选偏好调整当前路线。

#### 🅲 从视频生成新攻略
1. 左侧「📮 STEP 1 · 投递视频」拖入或选择 MP4
2. 设置天数 / 人数 / 预算 / 强度
3. 填 API Key / Base URL / Model（或已配环境变量则留空）
4. 点 **「✏️ 开始绘制地图」**
5. 进度条会显示：下载→提取音频→Whisper转写→关键帧→OCR→LLM→路线优化→渲染
6. 约 1-3 分钟后地图、行程卡、必去/避雷全部刷新

> ⚠️ **抖音直链下载受反爬限制**：建议用 https://snaptik.app 等工具先下载 MP4，再上传本地文件。

#### 🅳 记录旅行后体验并反哺下一次规划
1. 在 `STEP 3 · 旅行后记录` 填写实际去了哪里、没去成哪里、实际花费、节奏和真实体验
2. 点 **保存旅行记录**
3. 点 **提炼并保存**，将复盘整理成历史偏好
4. 下一次规划或调整路线时，在 `STEP 1` 勾选 **生成时参考已选历史偏好**，再点 **从历史偏好中选择**
5. 可继续生成旅行后攻略，或评价投递视频与真实体验之间的差距

---

## 📁 目录结构

```
路线改改鸭-发布版/
├── server.py             # Flask 后端入口
├── pipeline.py           # 视频→攻略 流水线（ffmpeg/yt-dlp/whisper/LLM）
├── visualize.py          # Folium + OSM 地图渲染
├── geocode.py            # 三级地理编码（AMap > LLM > Nominatim）
├── travel_memory.py      # 历史偏好库：保存、检索、注入旅行偏好
├── post_trip.py          # 旅行后记录：复盘事实、照片、攻略和视频评价
├── templates/
│   └── index.html        # 主页面（横版 bento 布局，手绘风）
├── static/
│   ├── app.js            # 前端逻辑
│   └── logo.png
├── output/               # 生成结果与课程演示数据
│   ├── guide_sample.json # 冻结的长三角样例，点 🔄 加载
│   ├── guide.json        # 当前/上次保存攻略，点 📂 加载
│   ├── guide.md
│   ├── case_japan_before.json / .md
│   ├── case_yangtze_video_evaluation.md
│   ├── route_map_from_new_logic.html
│   └── geocache.json
├── Report/               # 课程报告 Markdown、PDF 与图片素材
├── try.mp4               # 演示视频（4 分钟东京 vlog）
├── requirements.txt
├── README.md
├── run.bat               # Windows 启动
└── run.sh                # Mac/Linux 启动
```

---

## ⚙️ 高级配置

### 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `VECTRUST_API_KEY` 或 `OPENAI_API_KEY` | —— | LLM + Whisper 必填 |
| `OPENAI_BASE_URL` | `https://api.openai-next.com` | API base，可改 `https://api.openai.com` |
| `OPENAI_MODEL` | `gpt-4o-mini` | Chat 模型名 |
| `AMAP_KEY` | —— | 高德地图 Web Key（可选，国内地理编码更准） |
| `HOST` | `127.0.0.1` | 监听 IP |
| `PORT` | `5000` | 监听端口 |
| `ENABLE_OSRM` | —— | 设为 `1` 时尝试请求 OSRM 路网；默认关闭，避免外部请求卡顿 |
| `OSRM_TIMEOUT` | `2` | OSRM 请求超时秒数 |

### 切换模型 / 接口

可以直接改环境变量 `OPENAI_BASE_URL` 和 `OPENAI_MODEL`，也可以在网页左侧填写。当前前端提供 **使用 DeepSeek V4 Pro** 快捷按钮。

### 旅行记忆数据

旅行后记录和历史偏好默认保存在本地：

- `output/post_trip_records.json`
- `output/travel_memory.json`
- `output/post_trip_video_evaluation.md`
- `output/post_trip_photos/`

这些文件属于个人运行数据，默认在 `.gitignore` 中，不会随仓库同步。课程报告中的案例材料已经整理在 `Report/` 和部分 `output/case_*` 文件中。

### 长视频 Whisper API 超时
`pipeline.py` 已实现：先整段提交，超时（524/504/timeout）自动切 60 秒小段重试。仍失败时回退本地 `faster-whisper`（首次会下载 ~500MB 模型）。

---

## 🐛 常见问题

**Q：打开页面是空白 / 地图不显示？**
A：浏览器按 `Ctrl + F5` 强刷一次。

**Q：上传时报 "缺少 ffmpeg"？**
A：`pip install imageio-ffmpeg` 重新安装；首次启动会自动复制 `ffmpeg.exe` 到 venv Scripts 目录。

**Q：Whisper API 524 网关超时？**
A：长视频已自动切片重试；若全部失败请检查 API Key 余额 / 网络代理。

**Q：抖音直链下载失败？**
A：抖音反爬严格，用 https://snaptik.app 等先下载 MP4，再选择"本地视频"上传。

**Q：站点地理编码不准 / 缺坐标？**
A：注册高德 Web Key 设置 `AMAP_KEY` 环境变量；或直接编辑 `output/guide.json` 手动改 lat/lng。

---

## 📜 License

仅供个人学习 / 评审 / Demo 演示使用。所引用模型、地图、视频版权归原作者所有。
