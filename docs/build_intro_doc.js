// 生成《路线改改鸭 · 项目介绍》Word 文档
const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, HeadingLevel, LevelFormat, BorderStyle, WidthType,
  ShadingType, PageOrientation
} = require('docx');

const FONT_HAN = "Microsoft YaHei";
const FONT_EN  = "Arial";

// ---------- 通用样式工具 ----------
const tx  = (t, opts = {}) => new TextRun({ text: t, font: { name: FONT_HAN, hint: 'eastAsia' }, ...opts });
const tBold = t => tx(t, { bold: true });

const p = (text, opts = {}) =>
  new Paragraph({
    spacing: { line: 360, before: 80, after: 80 },
    children: [tx(text)],
    ...opts,
  });

const h1 = text => new Paragraph({
  heading: HeadingLevel.HEADING_1,
  spacing: { before: 240, after: 160 },
  children: [tx(text, { bold: true, size: 32, color: "C0392B" })],
});

const h2 = text => new Paragraph({
  heading: HeadingLevel.HEADING_2,
  spacing: { before: 200, after: 120 },
  children: [tx(text, { bold: true, size: 26, color: "2E4E7E" })],
});

const bullet = text => new Paragraph({
  numbering: { reference: "bullets", level: 0 },
  spacing: { line: 340, before: 40, after: 40 },
  children: typeof text === 'string' ? [tx(text)] : text,
});

const bulletRich = (head, body) => new Paragraph({
  numbering: { reference: "bullets", level: 0 },
  spacing: { line: 340, before: 40, after: 40 },
  children: [tBold(head), tx(body)],
});

// ---------- Slogan 引文卡片 ----------
const sloganTable = () => {
  const cellTxt = (lines) => lines.map(l =>
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { line: 360, before: 40, after: 40 },
      children: [tx(l, { size: 24, color: "5B4636" })],
    })
  );
  const border = { style: BorderStyle.SINGLE, size: 12, color: "E5A572" };
  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [9360],
    rows: [new TableRow({
      children: [new TableCell({
        width: { size: 9360, type: WidthType.DXA },
        margins: { top: 240, bottom: 240, left: 360, right: 360 },
        shading: { fill: "FFF6E3", type: ShadingType.CLEAR },
        borders: { top: border, bottom: border, left: border, right: border },
        children: [
          new Paragraph({
            alignment: AlignmentType.CENTER,
            spacing: { line: 360, before: 40, after: 80 },
            children: [tx("「在快节奏生活中，需要旅行释放压力；",
                          { italics: true, size: 26, color: "8C5B2E" })],
          }),
          ...cellTxt([
            "但往往做攻略比游玩更耗费精力；",
            "茫茫数据中，如何结合不同博主视频，找到适合自己的攻略？」",
          ]),
          new Paragraph({
            alignment: AlignmentType.CENTER,
            spacing: { line: 360, before: 200, after: 40 },
            children: [tx("🦆 路线改改鸭，你的攻略好搭子",
                          { bold: true, size: 32, color: "C0392B" })],
          }),
        ],
      })],
    })],
  });
};

// ---------- 核心信息表 ----------
const metaTable = () => {
  const cell = (text, opts = {}) => new TableCell({
    width: { size: opts.width || 4680, type: WidthType.DXA },
    margins: { top: 100, bottom: 100, left: 160, right: 160 },
    shading: opts.shade ? { fill: opts.shade, type: ShadingType.CLEAR } : undefined,
    borders: {
      top:    { style: BorderStyle.SINGLE, size: 6, color: "C9B894" },
      bottom: { style: BorderStyle.SINGLE, size: 6, color: "C9B894" },
      left:   { style: BorderStyle.SINGLE, size: 6, color: "C9B894" },
      right:  { style: BorderStyle.SINGLE, size: 6, color: "C9B894" },
    },
    children: [new Paragraph({
      spacing: { line: 320 },
      children: [tx(text, opts.bold ? { bold: true } : {})],
    })],
  });
  const row = (k, v) => new TableRow({
    children: [
      cell(k, { width: 2400, bold: true, shade: "FFF1B5" }),
      cell(v, { width: 6960 }),
    ],
  });
  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [2400, 6960],
    rows: [
      row("项目名称", "路线改改鸭（Travel Map · Route Quack Quack）"),
      row("一句话简介", "把抖音/B站旅行视频，一键变成属于你的可改可玩的旅行攻略地图"),
      row("交付形态", "本地 Web 应用（Flask + Folium 地图 + 多模态 AI Agent）"),
      row("适用场景", "城市周边游 / 国内外多日深度游 / 跟着博主二刷线路"),
    ],
  });
};

// ============================================================
//  正文
// ============================================================
const children = [
  // 标题
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 0, after: 120 },
    children: [tx("🦆 路线改改鸭 · 项目介绍",
                  { bold: true, size: 44, color: "2B2118" })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 200 },
    children: [tx("Travel Map · 你的攻略好搭子",
                  { italics: true, size: 22, color: "6B5A47" })],
  }),

  sloganTable(),

  new Paragraph({ spacing: { before: 200, after: 80 }, children: [tx("")] }),
  metaTable(),

  // ---------- 1. 目标人群 ----------
  h1("一、定位目标人群"),
  p("我们把核心用户画像锁定在「会刷视频、想出门、但没时间做攻略」这三类有交叉的现代年轻人身上："),

  h2("1.1 核心人群"),
  bulletRich("种草型年轻人（22–35 岁）：",
    "每天刷抖音 / 小红书 / B 站时反复被旅行 vlog 种草，但收藏夹一直处于「躺平」状态，从未真正落地成行程。"),
  bulletRich("说走就走的轻量自由行用户：",
    "周末或小长假突发出行需求，没有几个晚上的时间慢慢做 Excel 表格、查地铁线、对照游记。"),
  bulletRich("社交型搭子党（情侣 / 闺蜜 / 同事局）：",
    "出行需要兼顾多人偏好，期望快速达成一份「我们都能接受」的路线方案，并可临时增删。"),
  bulletRich("跟练型博主粉：",
    "看了某个博主的成片就想原样去一遍，但视频里地点零散、信息割裂，缺一份能拍着去的清单。"),

  h2("1.2 次级人群"),
  bullet("陪伴老人 / 亲子出行的家庭用户，需要降强度、降步行、增加休息点的方案。"),
  bullet("旅行内容博主 / 探店主理人，需要快速复盘他人路线、做差异化选题。"),
  bullet("出境自由行用户（日本 / 东南亚等），希望把外语景点 / 地铁站名也能精准还原成中文路线。"),

  // ---------- 2. 痛点 & 用户价值 ----------
  h1("二、解决的痛点与用户价值"),

  h2("2.1 用户的真实痛点"),
  bulletRich("信息过载、注意力被分散：",
    "一次旅行平均看 5–10 个博主视频，时间轴零散，没有人帮你把这些视频「合并同类项」。"),
  bulletRich("做攻略比游玩更累：",
    "找点 → 查地铁 → 对照预算 → 评估老人/小孩能不能跟上 → 排序避免折返……每一步都是手工活儿。"),
  bulletRich("攻略与个人需求脱钩：",
    "网上现成的「3 日精华游」并不考虑你「不爬山 / 多吃小吃 / 想拍照 / 带娃」等真实偏好。"),
  bulletRich("信息孤岛，难以验证：",
    "博主推荐的店真的还在营业吗？这个景点和我所在的城市/区域顺路吗？画面里的招牌究竟叫什么？"),
  bulletRich("修改一次行程 = 全部重做：",
    "一旦想替换某个点或调整一天主题，几乎只能推倒重来，没有可交互的「攻略原稿」。"),

  h2("2.2 我们提供的用户价值"),
  bulletRich("时间价值：",
    "原本 2–4 小时的攻略工作量压缩到分钟级别 —— 投入视频 → 等几分钟 → 得到可执行的多日地图路线。"),
  bulletRich("决策价值：",
    "AI 不只复述视频，还会按用户偏好（强度 / 预算 / 人群 / 主题）筛选地点，把不顺路、不合预算的放入备选清单。"),
  bulletRich("可视化价值：",
    "结构化攻略 + 可点选地图 + 按天分色卡片 + 必去 & 避雷清单，一目了然，旅行当天直接看手机就能走。"),
  bulletRich("可改可玩：",
    "一句话「改改鸭」即可让 AI 微调路线，无需重新喂视频；满意后一键打包导出。"),
  bulletRich("可追溯价值：",
    "每个 stop 都附带视频线索（来自第几段 ASR / 哪张关键帧）、安排理由与替代建议，让用户敢相信也敢调整。"),

  // ---------- 3. 实现方案 ----------
  h1("三、实现方案"),
  p("「路线改改鸭」是一套围绕「多模态视频理解 → 多视频融合 → 偏好驱动的攻略生成 → 可交互修订」的本地 Web 应用，整体由 Python（Flask）+ 浏览器前端 + 多模态 LLM 组成。"),

  h2("3.1 总体架构"),
  bullet("前端（templates/index.html + static/app.js）：手绘 Bento 风格的横版信息画布，左上传 / 中地图 / 右每日故事手账。"),
  bullet("后端（server.py / pipeline.py / new_logic_agent.py）：异步任务调度，支持暂停 / 继续 / 取消，状态实时回推。"),
  bullet("AI 调用（兼容 OpenAI Chat Completions 协议）：默认用支持视觉的多模态模型，自动检测并降级为纯文本模式。"),
  bullet("地图渲染（visualize.py）：Folium + 高德 GCJ-02 瓦片 + ESRI 卫星图，OSRM 真实路网串联，跨天连线带交通方式 emoji。"),
  bullet("地理编码（geocode.py）：AMap → LLM 批量补坐标 → Nominatim 三级兜底，海外景点也能正确落点。"),

  h2("3.2 端到端流水线"),
  bulletRich("Step 1 · 视频投递：",
    "支持本地上传 1–5 个视频文件，或粘贴抖音分享文案让 yt-dlp 下载。"),
  bulletRich("Step 2 · 多视频并行解析：",
    "ffmpeg 抽音轨 → faster-whisper 转写中文 → OpenCV 等间隔抽关键帧 → RapidOCR 识别招牌/字幕；模型单例 + 缓存避免重复解析。"),
  bulletRich("Step 3 · 多视频文本融合：",
    "把每个视频的 ASR、OCR、元数据拼成「分段融合知识」，原文段落保留视频编号便于追溯。"),
  bulletRich("Step 4 · 偏好驱动的攻略生成：",
    "把用户的天数 / 人数 / 预算 / 强度 / 主题 / 适合人群 / 自定义偏好作为最高优先级注入 system prompt，让 LLM 在「视频候选池」上做硬约束筛选。"),
  bulletRich("Step 5 · 多模态视觉理解（关键帧 image_url）：",
    "对兼容视觉的模型，把 1024px 关键帧以 base64 image_url 形式塞进同一轮请求，让模型「真的看见」博主到过的招牌、人流、季节。"),
  bulletRich("Step 6 · 路线确定性优化：",
    "对每天 stops 做贪心最近邻排序 + OSRM 真实路网 polyline，避免 LLM 输出折返/交叉。"),
  bulletRich("Step 7 · 交互式修订：",
    "前端「✍️ 仅按这条偏好调整」按钮直接走 revise_plan，不重新喂视频，保留必去/避雷的 `{place, reason}` 结构。"),
  bulletRich("Step 8 · 一键打包导出：",
    "guide.json / guide.md / map.html / 转写 / 融合文本 / 关键帧 → zip，便于线下分享或继续二次编辑。"),

  h2("3.3 工程关键点"),
  bullet("协作式任务控制：worker 在每个 progress 回调点检查暂停 / 取消事件，UI 上可实时暂停继续。"),
  bullet("视频解析缓存：按「绝对路径 + size + mtime」做 MD5 命中，重复跑同一视频跳过 ASR / OCR。"),
  bullet("Whisper / RapidOCR 单例 + 线程锁：跨视频复用模型，跨视频时 ffmpeg 真正并行。"),
  bullet("视频贡献值面板：基于每个视频段对最终攻略地点的命中率反推贡献占比，可视化「哪个博主真正帮上了你」。"),

  // ---------- 4. 核心创新点 ----------
  h1("四、核心创新点"),

  h2("创新点 1 · 多视频融合的旅行 Agent"),
  p("市面上的 AI 旅行助手多是基于纯文本问答，无法吸收博主视频中的视觉/口播信息。我们让 AI 真正「看 + 听 + 读」多个视频："),
  bullet("ASR（faster-whisper）+ OCR（RapidOCR）+ 视频元数据 + 关键帧图像四路输入。"),
  bullet("跨视频文本按段融合，让 LLM 知道每条结论来自哪个博主的哪段语音/画面。"),
  bullet("跨视频候选池而非「按视频拼凑」，避免「一日 A 博主路线 + 一日 B 博主路线」的拼凑感。"),

  h2("创新点 2 · 多模态关键帧视觉理解"),
  bullet("自动识别视觉模型（GPT-4o / Claude / Qwen-VL / Gemini 等）并启用 image_url 模式，失败自动回退纯文本。"),
  bullet("视觉模型能从画面识别招牌中英日韩文、人流密度、季节、白天/夜晚，直接体现在 tip / avoid 字段。"),
  bullet("每个 stop 必带 source_hint，明确指出来自第几帧或哪段语音，让结果可追溯、可纠错。"),

  h2("创新点 3 · 偏好优先级驱动的硬约束筛选"),
  bullet("用户的额外要求（不爬山 / 多吃小吃 / 带老人）拥有最高优先级，高于视频博主推荐。"),
  bullet("System Prompt 中显式编码了 10 条偏好规则映射，让模型把偏好落到具体 stops 调整。"),
  bullet("不顺路 / 与偏好冲突 / 定位不确定 → 强制放入 backup_list 而非主路线，给用户「为什么不选它」的解释。"),

  h2("创新点 4 · 确定性的路线优化 + 真实路网渲染"),
  bullet("LLM 输出后再跑一遍贪心最近邻重排，保证每天 stops 首尾相接、不折返。"),
  bullet("Folium + OSRM 真实道路 polyline，而不是直线连接 —— 视觉上像真的导航。"),
  bullet("跨天连线自动识别「高铁 / 飞机 / 地铁 / 步行」并在中点贴对应 emoji + 颜色标签。"),

  h2("创新点 5 · 海内外通用的三级地理编码"),
  bullet("国内：AMap GCJ-02 直接喂高德瓦片，原生对齐不偏移。"),
  bullet("海外：LLM 批量给 WGS84 坐标（适用日本、东南亚等 Nominatim 不一定能直连的网络环境）。"),
  bullet("最后用 Nominatim 兜底；连接被拒时快速失败，整个流水线不卡死。"),

  h2("创新点 6 · 可改可玩的对话式攻略"),
  bullet("不只是「生成攻略」，而是「攻略原稿」+「一句话修订」+「一键回退到样例」的可玩闭环。"),
  bullet("修订时保留必去 / 避雷的 `{place, reason}` 结构，前端能逐项渲染「★ 地点 · 原因」。"),
  bullet("视频贡献值面板量化「谁的视频贡献最大」，让用户决定下一步要不要追看哪位博主。"),

  // ---------- 结语 ----------
  h1("五、写在最后"),
  p("我们希望「路线改改鸭」不只是一个生成器，而是你旅行中真正的搭子 —— 收藏夹里那些被吃灰的视频，它能帮你串成可执行的路线；行前临时想改主意，它能听懂、能改、还能告诉你为什么这么改。"),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 240, after: 120 },
    children: [tx("🦆 让攻略好做，让旅行好玩。",
                  { bold: true, size: 26, color: "C0392B" })],
  }),
];

// ============================================================
//  Document
// ============================================================
const doc = new Document({
  creator: "Travel Map Team",
  title: "路线改改鸭 · 项目介绍",
  styles: {
    default: {
      document: {
        run: { font: { name: FONT_HAN, hint: 'eastAsia' }, size: 22 },
        paragraph: { spacing: { line: 320 } },
      },
    },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, font: { name: FONT_HAN, hint: 'eastAsia' } },
        paragraph: { spacing: { before: 280, after: 160 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, font: { name: FONT_HAN, hint: 'eastAsia' } },
        paragraph: { spacing: { before: 220, after: 120 }, outlineLevel: 1 } },
    ],
  },
  numbering: {
    config: [{
      reference: "bullets",
      levels: [{
        level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 720, hanging: 360 } } },
      }],
    }],
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

const outPath = path.join(__dirname, "项目介绍.docx");
Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync(outPath, buf);
  console.log("OK ->", outPath);
});
