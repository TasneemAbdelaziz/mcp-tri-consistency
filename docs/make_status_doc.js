// Builds the week-1 status report for Menna as an Arabic (RTL) Word document.
const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, WidthType, ShadingType,
  AlignmentType, HeadingLevel, LevelFormat, BorderStyle, ExternalHyperlink,
} = require("docx");

const OUT = process.argv[2];
const FONT = { ascii: "Calibri", hAnsi: "Calibri", cs: "Arial" };
const ACCENT = "1F4E79";
const PAGE_W = 11906, MARGIN = 1134, CONTENT_W = PAGE_W - 2 * MARGIN; // A4, 2 cm margins

// run(s): a string, or [text, {bold, code, color}] pieces
function runs(parts, base = {}) {
  if (typeof parts === "string") parts = [parts];
  return parts.map(p => {
    const [text, o] = typeof p === "string" ? [p, {}] : p;
    if (o.link) {
      return new ExternalHyperlink({ link: o.link, children: [new TextRun({
        text, style: "Hyperlink", rightToLeft: /[0600-06FF]/.test(text), font: FONT, size: base.size || 22 })] });
    }
    return new TextRun({
      text, bold: o.bold || base.bold, color: o.color || base.color, size: base.size || 22,
      rightToLeft: !o.code, font: o.code ? { ascii: "Consolas", hAnsi: "Consolas", cs: "Consolas" } : FONT,
    });
  });
}
const P = (parts, opts = {}) => new Paragraph({
  bidirectional: true, alignment: AlignmentType.START, spacing: { after: 120, line: 300 },
  children: runs(parts, opts), ...opts.para,
});
const H1 = text => new Paragraph({ heading: HeadingLevel.HEADING_1, bidirectional: true, children: runs(text) });
const H2 = text => new Paragraph({ heading: HeadingLevel.HEADING_2, bidirectional: true, children: runs(text) });
const bullet = (parts, level = 0) => new Paragraph({
  bidirectional: true, numbering: { reference: "bullets", level }, spacing: { after: 80, line: 290 },
  children: runs(parts),
});
const numbered = (parts, ref = "numbers") => new Paragraph({
  bidirectional: true, numbering: { reference: ref, level: 0 }, spacing: { after: 80, line: 290 },
  children: runs(parts),
});

// RTL table; widths are in DXA and must sum to CONTENT_W
function table(header, rows, widths) {
  const border = { style: BorderStyle.SINGLE, size: 4, color: "BFBFBF" };
  const borders = { top: border, bottom: border, left: border, right: border };
  const cell = (parts, w, head) => new TableCell({
    width: { size: w, type: WidthType.DXA }, borders,
    shading: head ? { type: ShadingType.CLEAR, color: "auto", fill: "DCE6F1" } : undefined,
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    children: [new Paragraph({ bidirectional: true, children: runs(parts, { bold: head, size: 20 }) })],
  });
  return new Table({
    visuallyRightToLeft: true, width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: widths,
    rows: [
      new TableRow({ tableHeader: true, children: header.map((h, i) => cell(h, widths[i], true)) }),
      ...rows.map(r => new TableRow({ children: r.map((c, i) => cell(c, widths[i], false)) })),
    ],
  });
}
const gap = () => new Paragraph({ children: [], spacing: { after: 60 } });
const code = t => [t, { code: true }];
const b = t => [t, { bold: true }];

const REPO = "https://github.com/TasneemAbdelaziz/mcp-tri-consistency";

const body = [
  new Paragraph({ heading: HeadingLevel.TITLE, bidirectional: true, alignment: AlignmentType.CENTER,
    children: runs("تحديث المشروع لمنة: وصلنا لفين") }),
  P(["الأسبوع الأول (13–18 أكتوبر 2026) · من تسنيم · ", ["GitHub repo", { link: REPO }]],
    { color: "595959", para: { alignment: AlignmentType.CENTER } }),

  H1("1. الملخص"),
  P("الأسبوع الأول خلص بالـ dataset متجهز، وأول نسخة من الـ detector بتاع Python شغّالة وبتطلّع تناقضات C↔A حقيقية. أهم 5 حاجات:"),
  numbered([b("الداتا بتاعتك جاهزة: "), "عندنا 77,084 tool، كل واحدة معاها الوصف والـ annotations والـ schema. تقدري تبدأي D↔A النهارده (القسم 3)."], "summary"),
  numbered([b("غيّرنا مصدر الـ dataset: "), "الـ remote servers اللي في الـ census أغلبها مافيهاش كود منشور، فبقينا بنجيب الـ servers من npm/PyPI ومن GitHub مباشرةً (القسم 2)."], "summary"),
  numbered([b("TypeScript هي الأغلبية: "), "حوالي 70% من الداتا TS، فدعم TS بقى أساسي، مش extension."], "summary"),
  numbered([b("الـ detector بتاع Python شغّال: "), "بيلاقي الـ tools والـ annotations، ويمشي في الكود لحد الـ sinks، ويطلّع التناقض بالمسار بتاعه في الكود (القسم 4)."], "summary"),
  numbered([b("محتاجين قرارات مع بعض: "), "6 حالات غامضة لازم نتفق عليها قبل الـ labeling (القسم 6)."], "summary"),

  H1("2. إيه اللي اتغير في الخطة"),
  P([b("الفكرة والـ RQs والتجارب والجدول الزمني زي ما هم. "), "اللي اتغير هو منين بنجيب الـ servers."]),
  H2("المشكلة"),
  bullet(["الـ census اللي كنا هنعتمد عليه (", code("flame-stream/mcp-annotation-census"), ") فيه remote servers بس، يعني servers شغّالة على سيرفرات شركات."]),
  bullet("جربنا clone لـ 10 repos منهم، و3 بس كان فيهم كود الـ server. الباقي README أو ملفات إعداد، والكود الحقيقي مقفول. ومن غير كود مفيش C(t)."),
  bullet(["شركة واحدة (", code("pipeworx-io"), ") عندها 1,248 server متولّدين من نفس الـ template. هنحللهم كـ case study لوحدهم بدل ما يسيطروا على النتايج."]),
  H2("الحل: 4 مصادر"),
  table(["المصدر", "الحجم", "الحالة", "ليه"], [
    ["npm/PyPI packages من الـ registry", "14,861 server في 13,087 repo", "خلص", "الأساسي: الـ package بيتبني من الـ repo، فالكود موجود"],
    ["GitHub Code Search على الـ annotations", "+88 ألف ملف لحد دلوقتي", "شغّال", "servers مش متسجلة في الـ registry"],
    ["Official reference servers", "7 servers", "خلص", "pilot و calibration و control group"],
    ["قايمة Hasan et al. (TOSEM)", "1,899 server", "مش منشورة", "ممكن نطلبها من المؤلفين لـ RQ3"],
  ], [2700, 2300, 1300, 3338]),
  gap(),
  P(["ملحوظة: الـ registry نفسه كبر من 18,688 server في يوليو لـ ", b("45,296"), " في أكتوبر. ده رقم ينفع في الـ Introduction."]),

  H1("3. الداتا الجاهزة ليكي"),
  P([b("الملف: "), code("data/raw/census_v2/tools_full.jsonl.gz"), " في الـ repo (27MB). فكّيه بـ ", code("gunzip"), ". كل سطر = tool واحدة."]),
  P("ده re-run للـ census عدّلته عشان يسجّل الوصف، على 3,718 server ردّوا علينا يوم 12 أكتوبر:"),
  table(["الحقل", "فيه إيه", "بيتستخدم في"], [
    [[code("description")], "وصف الـ tool زي ما الـ LLM بيشوفه", "D(t)"],
    [[code("annotations")], "الـ 4 hints، كل واحد true أو false أو omitted", "A(t)"],
    [[code("raw_annotations")], "الـ annotations زي ما رجعت من الـ server بالظبط", "مراجعة"],
    [[code("input_schema")], "الـ JSON schema بتاع المدخلات", "ablation: الوصف + الـ schema"],
    [[code("server_name"), " و ", code("tool_name")], "تعريف الـ tool", "الربط بالكود بعدين"],
  ], [2600, 4538, 2500]),
  gap(),
  P("الأرقام: 77,084 tool، منهم 77,047 معاهم وصف (99.95%)، و53,832 فيهم annotation واحدة على الأقل مكتوبة صراحةً."),
  H2("خلي بالك من الـ omitted"),
  P(["قيمة ", code("omitted"), " معناها إن الـ annotation مش مكتوبة، فالـ default بيتطبق: ", code("readOnlyHint=false"), " و", code("destructiveHint=true"), " و", code("openWorldHint=true"), ". الخطة بتقول نفصل دايماً بين explicit وdefault، والـ ablation الأخير عندك بيقيس الفرق ده."]),
  P("وبعدين، للـ servers اللي جاية من npm/PyPI، الـ parser هيطلّع الوصف من الكود نفسه (من @mcp.tool وregisterTool). هبعتهولك في ملف منفصل لما يجهز."),

  H1("4. الـ detector وصل لفين"),
  table(["الجزء", "بيعمل إيه", "الحالة"], [
    [[code("annotations.py")], "بيلاقي الـ tools في كود Python بـ 4 أشكال (FastMCP، add_tool، low-level Tool، dict) ويقرا كل hint", "شغّال، 14 test"],
    [[code("effects.py")], "بيمشي من الـ handler لحد عمق 3 دوال، يجمع الـ sinks، ويقارن بالـ annotations", "شغّال، 7 tests"],
    [[code("sinks/python.yaml")], "كتالوج الـ sinks: read/write/delete/execute/network + GitPython", "نسخة أولى"],
    ["TypeScript", "نفس الكلام لـ TS", "الخطوة الجاية"],
  ], [2400, 5338, 1900]),
  gap(),
  H2("قواعد التحقق (زي الخطة)"),
  bullet([code("readOnlyHint=true"), " ⇐ مفيش write ولا delete ولا execute"]),
  bullet([code("destructiveHint=false"), " ⇐ مفيش delete"]),
  bullet([code("openWorldHint=false"), " ⇐ مفيش network"]),
  P("الـ annotations المكتوبة صراحةً بس هي اللي ممكن تتناقض. الـ default عمره ما بيتناقض مع الكود."),
  P([b("إضافة: "), "الـ HTTP requests بنحسبها حسب نوعها: GET = read، وPOST/PUT/PATCH = write، وDELETE = delete. ده عشان كتير من الـ servers بتكلّم APIs ومش بتلمس ملفات خالص."]),

  H1("5. أول نتايج C↔A"),
  P("جربنا الـ detector على 14 repo حقيقي من الـ code search وعلى الـ git server الرسمي. لقى الـ handler لكل tool تقريباً، وبياخد من 0.1 لـ 11 ثانية للـ repo."),
  table(["Repo", "Tool", "الـ annotation", "الكود بيعمل", "الحكم"], [
    ["kalshi-ai-trading-bot", [code("settle")], "readOnly=true", "بيضيف سطور لملف", "تناقض حقيقي"],
    ["git (الرسمي)", [code("git_commit")], "destructive=false", [["بيمسح ", {}], code("MERGE_HEAD")], "محتاج قرار"],
    ["NTL-GPT-Clone", [code("clip_raster"), " و6 تانيين"], "destructive=false", "بيمسح ملفات output فشلت", "محتاج قرار"],
    ["ciscolive-potpourri", [code("generate_password")], "readOnly=true", "بيشغّل برنامج خارجي", "محتاج قرار"],
    ["course-companion", "7 tools", "openWorld=false", "قراية dict مش HTTP", "false positive، اتصلح"],
  ], [2100, 2000, 1700, 2238, 1600]),

  H1("6. قرارات محتاجين ناخدها مع بعض"),
  P(["الحالات دي هتأثر على الـ labeling والـ κ، فلازم نتفق عليها في جولة الـ calibration (30 tool). التفاصيل في ", code("labeling/open_questions.md"), "."]),
  numbered([b("مسح حالة داخلية: "), "لو الـ tool بتمسح ملف داخلي بتاعها (زي MERGE_HEAD)، ده destructive؟"], "decisions"),
  numbered([b("تنضيف output فاشل: "), "لو بتمسح ملف هي لسه عاملاه، ده destructive؟"], "decisions"),
  numbered([b("تشغيل برنامج مالوش أثر: "), "subprocess بيطلّع password بس، ده بيكسر readOnly؟ (الخطة بتقول execute = آه)"], "decisions"),
  numbered([b("POST للقراية: "), "APIs بتستخدم POST للبحث أو للـ token من غير ما تغيّر حاجة. نعتبرها consistent؟"], "decisions"),
  numbered([b("ملفات log: "), "لو readOnly وبتكتب في journal، ده تناقض؟ (شكله آه)"], "decisions"),
  numbered([b("git checkout: "), "ممكن يمسح تعديلات محلية. نحسبه delete ولا write؟"], "decisions"),
  P([b("وقرار أخير محتاجك فيه: "), "موافقة على تغيير مصدر الـ dataset؟ وإن الـ D(t) للـ servers الجديدة يتطلّع من الكود بدل tools/list؟"]),

  H1("7. الخطوات الجاية"),
  table(["مين", "إيه", "إمتى"], [
    ["تسنيم", "الـ parser والـ analyzer بتوع TypeScript", "الأسبوع ده"],
    ["تسنيم", "دمج المصادر الأربعة، وscan_repos.py يتأكد إن فيه annotations", "لما الـ code search يخلص"],
    ["منة", "تصميم prompt استخراج D(t) وتجربته على tools_full.jsonl", "دلوقتي"],
    ["منة", "D↔A على الـ 54 ألف tool اللي فيهم annotations", "الأسبوع 2"],
    ["الاتنين", "Pilot على 20 tool + calibration على الـ 6 حالات", "آخر الأسبوع 1"],
  ], [1600, 5638, 2400]),
  gap(),
  H2("الروابط"),
  bullet(["الـ repo: ", [REPO, { link: REPO }]]),
  bullet(["الداتا: ", code("data/raw/census_v2/tools_full.jsonl.gz")]),
  bullet(["الحالات الغامضة: ", code("labeling/open_questions.md")]),
  bullet(["الـ detector: ", code("detector/python/"), " والكتالوج ", code("detector/sinks/python.yaml")]),
];

const numberingConfig = ["numbers", "summary", "decisions"].map(reference => ({
  reference, levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.START,
    style: { paragraph: { indent: { start: 520, hanging: 360 } } } }],
}));

const doc = new Document({
  creator: "Tasneem AbdElaziz",
  title: "تحديث المشروع لمنة",
  styles: {
    default: { document: { run: { font: FONT, size: 22 }, paragraph: { bidirectional: true } } },
    paragraphStyles: [
      { id: "Title", name: "Title", basedOn: "Normal", run: { size: 40, bold: true, color: ACCENT, font: FONT },
        paragraph: { spacing: { after: 120 } } },
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 30, bold: true, color: ACCENT, font: FONT },
        paragraph: { spacing: { before: 320, after: 140 }, outlineLevel: 0,
          border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: "BFBFBF", space: 4 } } } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 25, bold: true, color: "404040", font: FONT },
        paragraph: { spacing: { before: 200, after: 100 }, outlineLevel: 1 } },
    ],
  },
  numbering: { config: [
    { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.START,
      style: { paragraph: { indent: { start: 520, hanging: 360 } } } }] },
    ...numberingConfig,
  ] },
  sections: [{
    properties: { page: { size: { width: PAGE_W, height: 16838 },
      margin: { top: MARGIN, bottom: MARGIN, left: MARGIN, right: MARGIN } } },
    children: body,
  }],
});

Packer.toBuffer(doc).then(buf => { fs.writeFileSync(OUT, buf); console.log("wrote", OUT); });
