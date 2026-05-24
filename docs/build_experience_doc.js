// 生成《路线改改鸭 · 体验流程》Word 文档
const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, HeadingLevel, LevelFormat, BorderStyle, WidthType,
  ShadingType,
} = require('docx');

const FONT = "Microsoft YaHei";

const tx = (t, opts = {}) =>
  new TextRun({ text: t, font: { name: FONT, hint: 'eastAsia' }, ...opts });
const tBold = t => tx(t, { bold: true });

const p = (text, opts = {}) =>
  new Paragraph({
    spacing: { line: 360, before: 80, after: 80 },
    children: [tx(text)],
    ...opts,
  });

const h1 = text => new Paragraph({
  heading: HeadingLevel.HEADING_1,
  spacing: { before: 280, after: 160 },
  children: [tx(text, { bold: true, size: 32, color: "C0392B" })],
});
const h2 = text => new Paragraph({
  heading: HeadingLevel.HEADING_2,
  spacing: { before: 220, after: 120 },
  children: [tx(text, { bold: true, size: 26, color: "2E4E7E" })],
});
const h3 = text => new Paragraph({
  spacing: { before: 160, after: 80 },
  children: [tx(text, { bold: true, size: 22, color: "5B4636" })],
});

const bullet = (items) =>
  items.map(text => new Paragraph({
    numbering: { reference: "bullets", level: 0 },
    spacing: { line: 340, before: 30, after: 30 },
    children: typeof text === 'string' ? [tx(text)] : text,
  }));

const number = (items) =>
  items.map(text => new Paragraph({
    numbering: { reference: "numbers", level: 0 },
    spacing: { line: 340, before: 40, after: 40 },
    children: typeof text === 'string' ? [tx(text)] : text,
  }));

// 代码 / 命令块（无衬线等宽风格）
const codeBlock = (text) => new Paragraph({
  spacing: { line: 300, before: 80, after: 80 },
  shading: { fill: "F4EFE4", type: ShadingType.CLEAR },
  border: {
    top:    { style: BorderStyle.SINGLE, size: 4, color: "C9B894" },
    bottom: { style: BorderStyle.SINGLE, size: 4, color: "C9B894" },
    left:   { style: BorderStyle.SINGLE, size: 4, color: "C9B894" },
    right:  { style: BorderStyle.SINGLE, size: 4, color: "C9B894" },
  },
  indent: { left: 200, right: 200 },
  children: [new TextRun({ text, font: { name: "Consolas", hint: 'ascii' }, size: 20, color: "2B2118" })],
});

// 提示框（💡 / ⚠️）
const tipBox = (icon, color, lines) => {
  const border = { style: BorderStyle.SINGLE, size: 12, color };
  return new Table({
    width: { size: 9026, type: WidthType.DXA },
    columnWidths: [9026],
    rows: [new TableRow({
      children: [new TableCell({
        width: { size: 9026, type: WidthType.DXA },
        margins: { top: 160, bottom: 160, left: 240, right: 240 },
        shading: { fill: color === "E5A572" ? "FFF6E3" : "E6F4EA", type: ShadingType.CLEAR },
        borders: { top: border, bottom: border, left: border, right: border },
        children: lines.map((line, idx) => new Paragraph({
          spacing: { line: 340, before: 20, after: 20 },
          children: idx === 0
            ? [tx(icon + "  ", { bold: true, size: 24 }), tBold(line)]
            : [tx(line)],
        })),
      })],
    })],
  });
};

// 步骤卡片（编号 + 标题 + 内容）
const stepCard = (n, title, blocks) => {
  return [
    new Paragraph({
      spacing: { before: 240, after: 80 },
      children: [
        tx(`STEP ${n}`, { bold: true, size: 24, color: "C0392B" }),
        tx("  ·  ", { size: 24, color: "C9B894" }),
        tx(title, { bold: true, size: 26, color: "2B2118" }),
      ],
    }),
    ...blocks,
  ];
};

// ============================================================
//  正文
// ============================================================
const children = [
  // 封面
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 0, after: 100 },
    children: [tx("🦆 路线改改鸭 · 体验流程", { bold: true, size: 44, color: "2B2118" })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 240 },
    children: [tx("First-Time Experience Guide · 从打开网页到导出攻略", { italics: true, size: 22, color: "6B5A47" })],
  }),

  p("本指南带你完整体验「路线改改鸭」，从环境准备到生成自己的第一份攻略，再到一句话修改和导出。整个体验耗时约 10–20 分钟（视视频数量和模型速度而定）。"),

  tipBox("💡", "E5A572", [
    "三句话理解这个项目",
    "1. 你上传 1–5 个旅行视频 → AI 看 / 听 / 读出博主真正去过的地点；",
    "2. 它结合你的天数 / 预算 / 偏好 / 同行人，生成一份可执行的多日攻略和地图；",
    "3. 想改？一句话告诉它，不用重新喂视频。",
  ]),

  // ---------- STEP 0: 环境准备 ----------
  h1("一、开始之前：环境准备"),
  h3("0.1 你需要准备什么"),
  ...bullet([
    "一台 Windows / macOS / Linux 电脑，能联网。",
    "Python 3.10+（项目自带 .venv，无需重装；如自行部署见 README）。",
    "一个支持 Chat Completions 协议的 API Key（推荐有视觉能力的多模态模型，如 GPT-4o / Claude / Qwen-VL）。",
    "想体验视频生成攻略：1–5 个本地旅行视频（mp4/mov 任意时长）；或一条抖音分享文案。",
  ]),

  h3("0.2 一键启动"),
  p("在项目根目录打开终端，执行（Windows 用 run.bat / Linux/macOS 用 run.sh）："),
  codeBlock("E:\\Desktop\\X\\Claude\\py\\.venv\\Scripts\\python.exe server.py"),
  p("看到 🌐 http://127.0.0.1:5000 即说明 Flask 服务已就绪，用浏览器打开这个地址。"),

  tipBox("⚠️", "7CB05A", [
    "首次启动小贴士",
    "· 首次启动会自动从 imageio CDN 下载 ~30MB 的 ffmpeg，请保持联网。",
    "· 如果浏览器空白或地图打不开，看终端日志，多半是端口被占或代理拦截。",
  ]),

  // ---------- STEP 1: 第一印象 ----------
  h1("二、第一印象：先看一遍样例"),
  ...stepCard(1, "用「长三角 5 日游」样例熟悉界面", [
    p("打开 http://127.0.0.1:5000 后，页面会自动加载长三角样例，让你 0 视频也能立刻看到产品形态。"),
    h3("界面布局（横版 Bento）"),
    ...bullet([
      "左侧 · STEP 1 · 投递视频：表单 + 必去 / 避雷小卡。",
      "中间 · 地图：高德地图底图 + 按天分色的真实路网路线，每个站点是一枚 emoji 圆贴纸。",
      "右侧 · STEP 2 · 故事手账：按天分色卡片，每个 stop 包含活动、交通、Tips、评分条等。",
      "顶部 · 元数据条：天数 / 预算 / 城市 / 强度。",
      "底部 · 🎬 视频贡献值：每个视频对最终攻略地点的命中比例。",
    ]),
    h3("先点点试试"),
    ...bullet([
      "点地图上任意一个 emoji 贴纸 → 右侧对应卡片会高亮闪烁。",
      "点右上角 🔄 → 一键重置为长三角样例（任何时候都能回到初始状态）。",
      "切换地图右上角图层 → 高德 / OpenStreetMap / Carto 淡彩 / 卫星图 + 标签。",
    ]),
  ]),

  // ---------- STEP 2: 真正开始用 ----------
  h1("三、生成你自己的第一份攻略"),

  ...stepCard(2, "投递视频（最多 5 个）", [
    p("在左侧 STEP 1 区域，点击虚线框「📼 点击或拖入视频」，或直接把本地视频拖进去。"),
    ...bullet([
      "支持一次添加 1–5 个，文件列表里能逐项删除。",
      "纯本地处理，不会上传到任何第三方（除调用 LLM 时只发送转写后的文本和关键帧）。",
      "如果你只有抖音链接，目前 UI 主推本地上传；想用链接可在 API（/api/generate）里传 share_text。",
    ]),
    tipBox("💡", "E5A572", [
      "视频选择建议",
      "· 同一目的地的 2–3 个视频组合，效果最好（互相印证 + 互补遗漏）。",
      "· 单段过长（>20 分钟）会让 ASR 变慢，可先裁段精华。",
      "· 同一视频重复上传会命中缓存，不会再跑一遍 ASR/OCR。",
    ]),
  ]),

  ...stepCard(3, "填写你的旅行偏好", [
    p("视频是「候选池」，偏好才是「筛选器」。下面这些字段决定 AI 帮你筛掉什么、安排什么："),
    ...bullet([
      "🗓 天数 / 👥 人数 / 💴 预算/天 —— 总预算自动 = 天数 × 预算。",
      "🎒 强度：轻松型（每天 2–3 站）/ 标准型（3–4 站）/ 特种兵（4–5 站）。",
      "👨‍👩‍👧 适合人群：大人 / 情侣 / 亲子 / 老人 / 朋友 —— 影响排队、爬坡、夜活动等。",
      "🎨 主题（多选）：自然 / 人文 / 徒步 / 美食 / 摄影 / 夜生活 / 二次元。",
      "📝 补充偏好（最关键）：用人话写 ——「不爬山」「想多吃小吃」「拒绝早起」「带 5 岁小孩」等。",
      "🔑 API Key：如服务器端已配 VECTRUST_API_KEY/OPENAI_API_KEY 环境变量可不填。",
    ]),
    tipBox("⚠️", "E5A572", [
      "「补充偏好」拥有最高优先级",
      "AI 会把它放到「比视频博主推荐还高」的位置 —— 即使博主反复说某个网红店，但你写「避开网红打卡点」，它就会进 backup_list 而非主路线。",
    ]),
  ]),

  ...stepCard(4, "点「✏️ 开始绘制地图」，看着进度跑", [
    p("点击大珊瑚色按钮后，左侧出现进度条 🛫，并按顺序经过以下阶段："),
    ...number([
      "上传中：浏览器把视频依次发到服务器（看到「上传 N/M」即正常）。",
      "并行解析视频：ffmpeg 抽音 → Whisper 转写中文 → 抽关键帧 → RapidOCR 识别画面文字。",
      "多视频文本融合：把所有视频整理成一份带视频编号的「融合知识」。",
      "调用大模型：把融合文本 + 你的偏好 + 关键帧图像（视觉模型时）一起发给 LLM。",
      "地理编码：LLM 批量给坐标，国内补 AMap，海外/疑难再走 Nominatim。",
      "路线优化：贪心最近邻重排，OSRM 算真实道路 polyline。",
      "落盘 + 完成提示 🎉。",
    ]),
    h3("我能控制进度吗？"),
    ...bullet([
      "⏸ 暂停：在下一步交接点停下，可随时 ▶ 继续。",
      "✕ 终止：协作式取消，会在下次 progress 回调点抛出 JobCancelled。",
      "进度条上的「转写 → 关键帧 → 模型 → 路线」是预计阶段顺序，可对照判断当前所处步骤。",
    ]),
  ]),

  // ---------- STEP 5–8: 浏览与互动 ----------
  h1("四、阅读你的攻略"),

  ...stepCard(5, "看地图：按天颜色 + 真实路网", [
    ...bullet([
      "每天用不同颜色串成一条 polyline；跨天用灰色虚线 + 🚄/✈️/🚇 emoji 标交通方式。",
      "每个 stop 是一枚 emoji 贴纸（自动按类型选 🏞 / 🍜 / 🛍 / 🏯 等），点击它 → 右侧对应卡片高亮闪烁。",
      "右上角图层控件支持切换：高德地图、OpenStreetMap、Carto 淡彩、卫星图 + 标签。",
    ]),
    tipBox("💡", "E5A572", [
      "地图小细节",
      "· 国内城市默认高德底图，与 AMap GCJ-02 坐标原生对齐，无偏移。",
      "· 海外城市自动切到 OpenStreetMap。",
      "· 鼠标悬停 stop 圆贴纸会显示 popup —— 包含活动、评分、交通、视频线索。",
    ]),
  ]),

  ...stepCard(6, "右栏每日卡片：故事手账", [
    ...bullet([
      "每天一座彩色「岛屿」卡片，标题是当天主题，meta 显示总时长 / 总预算 / 站点数。",
      "每个 stop 卡片：emoji 圆 + 编号 + 地名 + 类型 chip + 时长 / 预算 / 交通 + 活动 / 推荐美食 chips + 评分条 + Tips。",
      "顶部「📔 每天 · 每一站」上方的圆点药丸是按天的快捷锚点 —— 点 Day 1 直接跳到第一天的第一站。",
      "滚动到对应日时，药丸会自动高亮当前可见的那一天。",
    ]),
  ]),

  ...stepCard(7, "必去 / 避雷 / 备选清单", [
    ...bullet([
      "⭐ 必去清单：AI 总结的高优先级地点（带原因），未必都进了主路线。",
      "⚠️ 避雷清单：与你偏好冲突 / 视频里被吐槽 / 商业化重 / 排队夸张的点。",
      "📦 备选清单：候选但未安排（不顺路 / 体力不够 / 城市判断不确定），可按需替换主路线。",
    ]),
  ]),

  // ---------- STEP 8: 一句话修改 ----------
  h1("五、不满意？一句话改"),
  ...stepCard(8, "「✍️ 仅按这条偏好调整（不重传视频）」", [
    p("在左侧「📝 补充偏好」输入框写新诉求，点下方青色按钮，不需要重新上传视频："),
    ...bullet([
      "「第二天太累了，加一个下午茶停点」",
      "「把第一天的购物去掉，换成博物馆」",
      "「预算砍到 300/天」",
      "「我要带老人，所有爬坡都换掉」",
    ]),
    p("AI 会基于当前 plan 微调，并保留必去 / 避雷的 `{place, reason}` 结构 —— 修改后地图和右栏会自动刷新。"),
    tipBox("💡", "E5A572", [
      "几个好玩的小指令",
      "·「把所有 emoji 换成日式风格」 → 不影响路线、只换图标。",
      "·「让第三天主题变成『一个人的安静日』」 → 当天主题、节奏全变。",
      "·「把所有点都换成附近的咖啡馆」 → 极端测试 AI 的执行边界。",
    ]),
  ]),

  // ---------- STEP 9: 保存 / 导出 ----------
  h1("六、保存、再打开、导出"),

  ...stepCard(9, "顶部 3 个会话按钮", [
    ...bullet([
      "🔄 重置：把当前画面切回长三角样例（不删除你之前保存的）。",
      "💾 保存当前：把当前 plan 写到 output/guide.json，下次启动还能继续编辑。",
      "📂 打开上次保存：恢复到上一次 💾 时刻的 plan。",
    ]),
  ]),

  ...stepCard(10, "📦 原始素材 · 一键导出", [
    p("点击底部「📦 原始素材」按钮 → 弹出模态框，里面有 6 个 Tab："),
    ...bullet([
      "📝 Markdown：人类友好的攻略全文（可贴小红书 / 公众号）。",
      "🧩 JSON：结构化 plan（程序化二次加工的入口）。",
      "🎙 转写：所有视频的 ASR 中文文本。",
      "🔤 OCR：关键帧识别出的招牌、路牌、字幕。",
      "📚 融合：按视频分段的融合知识。",
      "🎞 关键帧：等比例缩放的关键帧网格。",
    ]),
    p("想一次性带走全部？调用 GET /api/export → 自动打包 guide.json + guide.md + map.html + frames + README 为 zip。"),
  ]),

  // ---------- 七、常见情况速查 ----------
  h1("七、常见情况速查"),

  h2("7.1 「我没有 API Key 怎么办？」"),
  ...bullet([
    "可以先用样例熟悉界面（无需 API Key）。",
    "本地若装了 faster-whisper，ASR 会自动降级到本地推理；但 LLM 攻略生成必须有 Key。",
    "服务器端预置环境变量 VECTRUST_API_KEY / OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL 即可全员免填。",
  ]),

  h2("7.2 「地图上有些 stop 没显示」"),
  ...bullet([
    "通常是地理编码失败：海外网络环境下 Nominatim 可能不通，会自动跳过。",
    "解决：在右下角看 backup_list，或对个别地点用「✍️ 改」让 LLM 给坐标。",
    "想离线兜底：服务器端设置 AMAP_KEY 环境变量，国内点位优先走高德。",
  ]),

  h2("7.3 「为什么生成出来的攻略和我预期不一样？」"),
  ...bullet([
    "检查「📝 补充偏好」是否表达明确：「不太累」太模糊，「不爬山 + 不超过 3 站/天」更清晰。",
    "视频可能覆盖了多个城市/区域，AI 会按 city 字段筛选 —— 必要时一句话「只要东京 23 区内」。",
    "需要更具体？点 stop 看 reason / source_hint，能看到 AI 安排的依据来自哪段视频。",
  ]),

  h2("7.4 「想看具体某段视频的贡献」"),
  ...bullet([
    "底部「🎬 视频贡献值」面板：每个视频对最终攻略地点的命中比例 + 命中的地点示例。",
    "命中率 = 该视频段文本中包含最终 itinerary 地点的数量比，越高代表这条视频「真正帮上了你」。",
  ]),

  h2("7.5 「想换一份样例打底再改」"),
  ...bullet([
    "把 output/guide_sample.json 替换成你心仪的攻略模板，重启服务即可。",
    "样例文件不会被覆盖，每次打开页面、点 🔄 都会回到它。",
  ]),

  // ---------- 八、彩蛋 ----------
  h1("八、彩蛋玩法"),
  ...bullet([
    "🎬 同一行程喂 2 个完全不同博主的视频，让 AI 在两条「人设」中调和 —— 会出现非常有趣的中间解。",
    "🏯 输入「假装这是一份李白游记」「假装这是宇航员的火星旅行」做 AI 创意改写，娱乐性满分。",
    "🌐 用国内视频 + 海外偏好（如「假装这是京都」），观察模型如何识别错位并修正。",
    "📱 完成后用手机扫电脑屏的 map.html → 一份本地可访问的离线导航网页。",
  ]),

  // ---------- 结语 ----------
  h1("九、写在最后"),
  p("「路线改改鸭」希望你把它当作一份会动的初稿：先用样例感受形态，再用一段你最近收藏的视频，结合自己的真实偏好生成一份属于你的攻略。"),
  p("如果你想改、想吐槽、想加站点，都不需要重新来过 —— 一句话告诉它，它会改。这就是它叫「改改鸭」的原因 🦆。"),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 280, after: 120 },
    children: [tx("祝你旅行愉快，攻略好做。", { bold: true, size: 26, color: "C0392B" })],
  }),
];

// ============================================================
//  Document
// ============================================================
const doc = new Document({
  creator: "Travel Map Team",
  title: "路线改改鸭 · 体验流程",
  styles: {
    default: {
      document: {
        run: { font: { name: FONT, hint: 'eastAsia' }, size: 22 },
        paragraph: { spacing: { line: 320 } },
      },
    },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, font: { name: FONT, hint: 'eastAsia' } },
        paragraph: { spacing: { before: 280, after: 160 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, font: { name: FONT, hint: 'eastAsia' } },
        paragraph: { spacing: { before: 220, after: 120 }, outlineLevel: 1 } },
    ],
  },
  numbering: {
    config: [
      { reference: "bullets",
        levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
      { reference: "numbers",
        levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
    ],
  },
  sections: [{
    properties: {
      page: {
        size: { width: 11906, height: 16838 }, // A4
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
      },
    },
    children,
  }],
});

const outPath = path.join(__dirname, "体验流程.docx");
Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync(outPath, buf);
  console.log("OK ->", outPath);
});
