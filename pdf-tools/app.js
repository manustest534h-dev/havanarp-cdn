/* أدوات PDF — منطق التطبيق. كل المعالجة داخل المتصفح. */
(function () {
  "use strict";

  const { PDFDocument, degrees, rgb, StandardFonts } = PDFLib;
  if (window.pdfjsLib) {
    pdfjsLib.GlobalWorkerOptions.workerSrc =
      "https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.worker.min.js";
  }

  const workspace = document.getElementById("main").querySelector("#workspace");
  const toastEl = document.getElementById("toast");
  const themeToggle = document.getElementById("themeToggle");

  /* ---------- الوضع الليلي ---------- */
  const savedTheme = localStorage.getItem("pdf-theme") || "dark";
  applyTheme(savedTheme);
  themeToggle.addEventListener("click", () => {
    const next = document.documentElement.getAttribute("data-theme") === "light" ? "dark" : "light";
    applyTheme(next);
    localStorage.setItem("pdf-theme", next);
  });
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    const icon = themeToggle.querySelector(".theme-icon");
    const label = themeToggle.querySelector(".theme-label");
    if (theme === "light") { icon.textContent = "☀️"; label.textContent = "الوضع النهاري"; }
    else { icon.textContent = "🌙"; label.textContent = "الوضع الليلي"; }
  }

  /* ---------- أدوات مساعدة ---------- */
  function toast(msg, isError) {
    toastEl.textContent = msg;
    toastEl.classList.toggle("error", !!isError);
    toastEl.classList.add("show");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => toastEl.classList.remove("show"), 3200);
  }

  function download(bytes, name) {
    const blob = new Blob([bytes], { type: "application/pdf" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  }

  const readAsBytes = (file) =>
    new Promise((res, rej) => {
      const r = new FileReader();
      r.onload = () => res(new Uint8Array(r.result));
      r.onerror = rej;
      r.readAsArrayBuffer(file);
    });

  // تحليل نطاق صفحات: "1-3,5,8-10" (يبدأ من 1) -> مصفوفة فهارس تبدأ من 0
  function parsePageRange(text, total) {
    const out = [];
    (text || "").split(",").forEach((chunk) => {
      chunk = chunk.trim();
      if (!chunk) return;
      const m = chunk.match(/^(\d+)\s*-\s*(\d+)$/);
      if (m) {
        let a = +m[1], b = +m[2];
        if (a > b) [a, b] = [b, a];
        for (let i = a; i <= b; i++) if (i >= 1 && i <= total) out.push(i - 1);
      } else if (/^\d+$/.test(chunk)) {
        const n = +chunk;
        if (n >= 1 && n <= total) out.push(n - 1);
      }
    });
    return out;
  }

  function el(html) {
    const t = document.createElement("template");
    t.innerHTML = html.trim();
    return t.content.firstElementChild;
  }

  /* ---------- التنقّل بين الأدوات ---------- */
  const tools = {};
  document.querySelectorAll(".tool-card").forEach((card) => {
    card.addEventListener("click", () => openTool(card.dataset.tool));
  });

  function openTool(name) {
    document.querySelectorAll(".tool-card").forEach((c) =>
      c.classList.toggle("active", c.dataset.tool === name)
    );
    workspace.hidden = false;
    workspace.innerHTML = "";
    (tools[name] || (() => { workspace.innerHTML = "<p>قريباً…</p>"; }))();
    workspace.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function shell(title, hint, bodyHTML) {
    const wrap = el(`<div>
      <div class="ws-head"><h3>${title}</h3><button class="ws-close" aria-label="إغلاق">×</button></div>
      <p class="ws-hint">${hint}</p>
      <div class="ws-body"></div>
    </div>`);
    wrap.querySelector(".ws-close").addEventListener("click", () => {
      workspace.hidden = true; workspace.innerHTML = "";
      document.querySelectorAll(".tool-card").forEach((c) => c.classList.remove("active"));
    });
    wrap.querySelector(".ws-body").appendChild(el(bodyHTML));
    workspace.appendChild(wrap);
    return wrap.querySelector(".ws-body");
  }

  // منطقة إفلات ملفات قابلة لإعادة الاستخدام
  function makeDropzone(body, accept, multiple, onFiles) {
    const dz = body.querySelector(".dropzone");
    const input = el(`<input type="file" accept="${accept}" ${multiple ? "multiple" : ""} hidden />`);
    body.appendChild(input);
    dz.addEventListener("click", () => input.click());
    input.addEventListener("change", () => onFiles([...input.files]));
    ["dragover", "dragenter"].forEach((e) =>
      dz.addEventListener(e, (ev) => { ev.preventDefault(); dz.classList.add("dragover"); })
    );
    ["dragleave", "drop"].forEach((e) =>
      dz.addEventListener(e, () => dz.classList.remove("dragover"))
    );
    dz.addEventListener("drop", (ev) => {
      ev.preventDefault();
      onFiles([...ev.dataTransfer.files]);
    });
  }

  /* ==================== الأدوات ==================== */

  /* دمج ملفات */
  tools.merge = function () {
    const body = shell("🧩 دمج ملفات PDF", "ارفع ملفين أو أكثر ورتّبهم بالسحب، وسيتم دمجهم بملف واحد.",
      `<div><div class="dropzone">اسحب الملفات هنا أو <strong>اضغط للاختيار</strong> (PDF فقط)</div>
       <ul class="file-list"></ul>
       <div class="actions"><button class="btn" disabled>دمج وتحميل</button></div></div>`);
    const list = body.querySelector(".file-list");
    const btn = body.querySelector(".btn");
    let files = [];
    function render() {
      list.innerHTML = "";
      files.forEach((f, i) => {
        const li = el(`<li class="file-item draggable" draggable="true"><span class="fi-name">📄 ${f.name}</span><button class="fi-remove" aria-label="حذف">×</button></li>`);
        li.querySelector(".fi-remove").addEventListener("click", () => { files.splice(i, 1); render(); });
        li.addEventListener("dragstart", () => li.classList.add("dragging"));
        li.addEventListener("dragend", () => { li.classList.remove("dragging"); reorderFromDOM(); });
        list.appendChild(li);
      });
      btn.disabled = files.length < 2;
    }
    list.addEventListener("dragover", (e) => {
      e.preventDefault();
      const dragging = list.querySelector(".dragging");
      const after = [...list.querySelectorAll(".file-item:not(.dragging)")].find((c) => {
        const box = c.getBoundingClientRect();
        return e.clientY < box.top + box.height / 2;
      });
      if (after) list.insertBefore(dragging, after); else list.appendChild(dragging);
    });
    function reorderFromDOM() {
      const names = [...list.querySelectorAll(".fi-name")].map((n) => n.textContent.replace("📄 ", ""));
      files.sort((a, b) => names.indexOf(a.name) - names.indexOf(b.name));
    }
    makeDropzone(body, "application/pdf", true, (fs) => {
      files = files.concat(fs.filter((f) => f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf")));
      render();
    });
    btn.addEventListener("click", async () => {
      try {
        btn.disabled = true; toast("جارٍ الدمج…");
        const out = await PDFDocument.create();
        for (const f of files) {
          const src = await PDFDocument.load(await readAsBytes(f), { ignoreEncryption: true });
          const pages = await out.copyPages(src, src.getPageIndices());
          pages.forEach((p) => out.addPage(p));
        }
        download(await out.save(), "مدموج.pdf");
        toast("تم الدمج بنجاح ✅");
      } catch (e) { console.error(e); toast("صار خطأ أثناء الدمج", true); }
      finally { btn.disabled = false; }
    });
  };

  /* تقسيم / استخراج صفحات */
  tools.split = function () {
    const body = shell("✂️ تقسيم / استخراج صفحات", "ارفع ملف PDF واكتب الصفحات المطلوبة مثل: 1-3,5,8",
      `<div><div class="dropzone">اسحب ملف PDF أو <strong>اضغط للاختيار</strong></div>
       <ul class="file-list"></ul>
       <div class="field"><label>الصفحات المطلوبة</label><input type="text" class="pages" placeholder="مثال: 1-3,5,8-10" /><p class="hint-inline">اترك الحقل فارغاً لاستخراج كل الصفحات.</p></div>
       <div class="actions"><button class="btn" disabled>استخراج وتحميل</button></div></div>`);
    let file = null;
    const btn = body.querySelector(".btn");
    const list = body.querySelector(".file-list");
    makeDropzone(body, "application/pdf", false, (fs) => {
      file = fs[0]; if (!file) return;
      list.innerHTML = `<li class="file-item"><span class="fi-name">📄 ${file.name}</span></li>`;
      btn.disabled = false;
    });
    btn.addEventListener("click", async () => {
      try {
        btn.disabled = true; toast("جارٍ الاستخراج…");
        const src = await PDFDocument.load(await readAsBytes(file), { ignoreEncryption: true });
        const total = src.getPageCount();
        const txt = body.querySelector(".pages").value.trim();
        const idx = txt ? parsePageRange(txt, total) : src.getPageIndices();
        if (!idx.length) { toast("ما في صفحات مطابقة للنطاق", true); btn.disabled = false; return; }
        const out = await PDFDocument.create();
        const pages = await out.copyPages(src, idx);
        pages.forEach((p) => out.addPage(p));
        download(await out.save(), "مستخرج.pdf");
        toast(`تم استخراج ${idx.length} صفحة ✅`);
      } catch (e) { console.error(e); toast("صار خطأ أثناء الاستخراج", true); }
      finally { btn.disabled = false; }
    });
  };

  /* صور إلى PDF */
  tools.images2pdf = function () {
    const body = shell("🖼️ تحويل الصور إلى PDF", "ارفع صور (JPG أو PNG) ورتّبهم، وكل صورة بتصير صفحة.",
      `<div><div class="dropzone">اسحب الصور هنا أو <strong>اضغط للاختيار</strong></div>
       <ul class="file-list"></ul>
       <div class="field"><label>حجم الصفحة</label><select class="psize"><option value="fit">حسب حجم الصورة</option><option value="a4">A4</option></select></div>
       <div class="actions"><button class="btn" disabled>إنشاء PDF</button></div></div>`);
    let imgs = [];
    const list = body.querySelector(".file-list");
    const btn = body.querySelector(".btn");
    function render() {
      list.innerHTML = "";
      imgs.forEach((f, i) => {
        const li = el(`<li class="file-item"><span class="fi-name">🖼️ ${f.name}</span><button class="fi-remove">×</button></li>`);
        li.querySelector(".fi-remove").addEventListener("click", () => { imgs.splice(i, 1); render(); });
        list.appendChild(li);
      });
      btn.disabled = imgs.length === 0;
    }
    makeDropzone(body, "image/png,image/jpeg", true, (fs) => {
      imgs = imgs.concat(fs.filter((f) => /image\/(png|jpe?g)/.test(f.type)));
      render();
    });
    btn.addEventListener("click", async () => {
      try {
        btn.disabled = true; toast("جارٍ الإنشاء…");
        const out = await PDFDocument.create();
        const a4 = body.querySelector(".psize").value === "a4";
        for (const f of imgs) {
          const bytes = await readAsBytes(f);
          const img = /png/.test(f.type) ? await out.embedPng(bytes) : await out.embedJpg(bytes);
          if (a4) {
            const page = out.addPage([595.28, 841.89]);
            const s = Math.min(page.getWidth() / img.width, page.getHeight() / img.height) * 0.94;
            const w = img.width * s, h = img.height * s;
            page.drawImage(img, { x: (page.getWidth() - w) / 2, y: (page.getHeight() - h) / 2, width: w, height: h });
          } else {
            const page = out.addPage([img.width, img.height]);
            page.drawImage(img, { x: 0, y: 0, width: img.width, height: img.height });
          }
        }
        download(await out.save(), "صور.pdf");
        toast("تم إنشاء الـ PDF ✅");
      } catch (e) { console.error(e); toast("صار خطأ أثناء الإنشاء", true); }
      finally { btn.disabled = false; }
    });
  };

  /* إضافة صورة على صفحة */
  tools.addimage = function () {
    const body = shell("➕ إضافة صورة على صفحة", "ارفع ملف PDF وصورة، وحدّد الصفحة والموضع والحجم.",
      `<div><div class="dropzone">اسحب ملف PDF أو <strong>اضغط للاختيار</strong></div>
       <ul class="file-list"></ul>
       <div class="field"><label>الصورة (PNG/JPG)</label><input type="file" class="imgpick" accept="image/png,image/jpeg" /></div>
       <div class="field-row">
         <div class="field"><label>رقم الصفحة</label><input type="number" class="pnum" value="1" min="1" /></div>
         <div class="field"><label>العرض (نقطة)</label><input type="number" class="iw" value="150" min="10" /></div>
       </div>
       <div class="field-row">
         <div class="field"><label>البُعد من اليسار (x)</label><input type="number" class="ix" value="50" /></div>
         <div class="field"><label>البُعد من الأسفل (y)</label><input type="number" class="iy" value="50" /></div>
       </div>
       <div class="actions"><button class="btn" disabled>إضافة وتحميل</button></div></div>`);
    let file = null, imgFile = null;
    const btn = body.querySelector(".btn");
    const list = body.querySelector(".file-list");
    makeDropzone(body, "application/pdf", false, (fs) => {
      file = fs[0]; if (!file) return;
      list.innerHTML = `<li class="file-item"><span class="fi-name">📄 ${file.name}</span></li>`;
      update();
    });
    body.querySelector(".imgpick").addEventListener("change", (e) => { imgFile = e.target.files[0]; update(); });
    function update() { btn.disabled = !(file && imgFile); }
    btn.addEventListener("click", async () => {
      try {
        btn.disabled = true; toast("جارٍ الإضافة…");
        const doc = await PDFDocument.load(await readAsBytes(file), { ignoreEncryption: true });
        const bytes = await readAsBytes(imgFile);
        const img = /png/.test(imgFile.type) ? await doc.embedPng(bytes) : await doc.embedJpg(bytes);
        const pnum = Math.min(Math.max(1, +body.querySelector(".pnum").value), doc.getPageCount());
        const page = doc.getPage(pnum - 1);
        const w = +body.querySelector(".iw").value;
        const h = (img.height / img.width) * w;
        page.drawImage(img, { x: +body.querySelector(".ix").value, y: +body.querySelector(".iy").value, width: w, height: h });
        download(await doc.save(), "معدّل.pdf");
        toast("تمت إضافة الصورة ✅");
      } catch (e) { console.error(e); toast("صار خطأ أثناء الإضافة", true); }
      finally { btn.disabled = false; }
    });
  };

  /* إضافة نص */
  tools.addtext = function () {
    const body = shell("✍️ إضافة نص على صفحة", "اكتب نص (يدعم العربية) وحدّد الصفحة والموضع والحجم واللون.",
      `<div><div class="dropzone">اسحب ملف PDF أو <strong>اضغط للاختيار</strong></div>
       <ul class="file-list"></ul>
       <div class="field"><label>النص</label><input type="text" class="txt" placeholder="اكتب النص هنا…" /></div>
       <div class="field-row">
         <div class="field"><label>رقم الصفحة</label><input type="number" class="pnum" value="1" min="1" /></div>
         <div class="field"><label>حجم الخط</label><input type="number" class="fs" value="24" min="6" /></div>
       </div>
       <div class="field-row">
         <div class="field"><label>x (من اليسار)</label><input type="number" class="tx" value="50" /></div>
         <div class="field"><label>y (من الأسفل)</label><input type="number" class="ty" value="700" /></div>
         <div class="field"><label>اللون</label><input type="color" class="tc" value="#e5766b" style="height:44px" /></div>
       </div>
       <p class="hint-inline">ملاحظة: تُدمج خط عربي تلقائياً لدعم الحروف العربية بشكل صحيح.</p>
       <div class="actions"><button class="btn" disabled>إضافة وتحميل</button></div></div>`);
    let file = null, arabicFontBytes = null;
    const btn = body.querySelector(".btn");
    const list = body.querySelector(".file-list");
    makeDropzone(body, "application/pdf", false, (fs) => {
      file = fs[0]; if (!file) return;
      list.innerHTML = `<li class="file-item"><span class="fi-name">📄 ${file.name}</span></li>`;
      btn.disabled = false;
    });
    async function getArabicFont() {
      if (arabicFontBytes) return arabicFontBytes;
      const res = await fetch("https://cdn.jsdelivr.net/npm/@fontsource/cairo@5.0.19/files/cairo-arabic-400-normal.woff");
      if (!res.ok) throw new Error("font");
      arabicFontBytes = new Uint8Array(await res.arrayBuffer());
      return arabicFontBytes;
    }
    btn.addEventListener("click", async () => {
      try {
        btn.disabled = true; toast("جارٍ الإضافة…");
        const doc = await PDFDocument.load(await readAsBytes(file), { ignoreEncryption: true });
        const text = body.querySelector(".txt").value || "";
        let font;
        try { doc.registerFontkit(fontkit); font = await doc.embedFont(await getArabicFont(), { subset: true }); }
        catch (_) { font = await doc.embedFont(StandardFonts.Helvetica); }
        const pnum = Math.min(Math.max(1, +body.querySelector(".pnum").value), doc.getPageCount());
        const page = doc.getPage(pnum - 1);
        const size = +body.querySelector(".fs").value;
        const hex = body.querySelector(".tc").value;
        const c = [1, 3, 5].map((i) => parseInt(hex.substr(i, 2), 16) / 255);
        let x = +body.querySelector(".tx").value;
        try { const wdt = font.widthOfTextAtSize(text, size); if (/[\u0600-\u06FF]/.test(text)) x = Math.max(0, x); void wdt; } catch (_) {}
        page.drawText(text, { x, y: +body.querySelector(".ty").value, size, font, color: rgb(c[0], c[1], c[2]) });
        download(await doc.save(), "بنص.pdf");
        toast("تمت إضافة النص ✅");
      } catch (e) { console.error(e); toast("صار خطأ أثناء الإضافة", true); }
      finally { btn.disabled = false; }
    });
  };

  /* تدوير صفحات */
  tools.rotate = function () {
    const body = shell("🔄 تدوير صفحات", "اختر زاوية التدوير والصفحات المطلوبة (فارغ = كل الصفحات).",
      `<div><div class="dropzone">اسحب ملف PDF أو <strong>اضغط للاختيار</strong></div>
       <ul class="file-list"></ul>
       <div class="field-row">
         <div class="field"><label>الزاوية</label><select class="ang"><option value="90">90° يمين</option><option value="180">180°</option><option value="270">90° يسار</option></select></div>
         <div class="field"><label>الصفحات</label><input type="text" class="pages" placeholder="مثال: 1,3-5 (فارغ = الكل)" /></div>
       </div>
       <div class="actions"><button class="btn" disabled>تدوير وتحميل</button></div></div>`);
    let file = null;
    const btn = body.querySelector(".btn");
    const list = body.querySelector(".file-list");
    makeDropzone(body, "application/pdf", false, (fs) => {
      file = fs[0]; if (!file) return;
      list.innerHTML = `<li class="file-item"><span class="fi-name">📄 ${file.name}</span></li>`;
      btn.disabled = false;
    });
    btn.addEventListener("click", async () => {
      try {
        btn.disabled = true; toast("جارٍ التدوير…");
        const doc = await PDFDocument.load(await readAsBytes(file), { ignoreEncryption: true });
        const total = doc.getPageCount();
        const txt = body.querySelector(".pages").value.trim();
        const idx = txt ? parsePageRange(txt, total) : doc.getPageIndices();
        const ang = +body.querySelector(".ang").value;
        idx.forEach((i) => {
          const p = doc.getPage(i);
          const cur = p.getRotation().angle || 0;
          p.setRotation(degrees((cur + ang) % 360));
        });
        download(await doc.save(), "مدوّر.pdf");
        toast(`تم تدوير ${idx.length} صفحة ✅`);
      } catch (e) { console.error(e); toast("صار خطأ أثناء التدوير", true); }
      finally { btn.disabled = false; }
    });
  };

  /* حذف صفحات */
  tools.delete = function () {
    const body = shell("🗑️ حذف صفحات", "حدّد الصفحات المراد حذفها. الباقي بينحفظ بملف جديد.",
      `<div><div class="dropzone">اسحب ملف PDF أو <strong>اضغط للاختيار</strong></div>
       <ul class="file-list"></ul>
       <div class="field"><label>الصفحات المراد حذفها</label><input type="text" class="pages" placeholder="مثال: 2,4-6" /></div>
       <div class="actions"><button class="btn" disabled>حذف وتحميل</button></div></div>`);
    let file = null;
    const btn = body.querySelector(".btn");
    const list = body.querySelector(".file-list");
    makeDropzone(body, "application/pdf", false, (fs) => {
      file = fs[0]; if (!file) return;
      list.innerHTML = `<li class="file-item"><span class="fi-name">📄 ${file.name}</span></li>`;
      btn.disabled = false;
    });
    btn.addEventListener("click", async () => {
      try {
        btn.disabled = true; toast("جارٍ الحذف…");
        const src = await PDFDocument.load(await readAsBytes(file), { ignoreEncryption: true });
        const total = src.getPageCount();
        const toDelete = new Set(parsePageRange(body.querySelector(".pages").value, total));
        const keep = src.getPageIndices().filter((i) => !toDelete.has(i));
        if (!keep.length) { toast("ما بينفع تحذف كل الصفحات", true); btn.disabled = false; return; }
        const out = await PDFDocument.create();
        const pages = await out.copyPages(src, keep);
        pages.forEach((p) => out.addPage(p));
        download(await out.save(), "بعد-الحذف.pdf");
        toast(`تم الحذف، بقي ${keep.length} صفحة ✅`);
      } catch (e) { console.error(e); toast("صار خطأ أثناء الحذف", true); }
      finally { btn.disabled = false; }
    });
  };

  /* ترتيب صفحات */
  tools.reorder = function () {
    const body = shell("🔀 ترتيب الصفحات", "ارفع ملف واكتب الترتيب الجديد للصفحات، مثل: 3,1,2,4",
      `<div><div class="dropzone">اسحب ملف PDF أو <strong>اضغط للاختيار</strong></div>
       <ul class="file-list"></ul>
       <div class="field"><label>الترتيب الجديد</label><input type="text" class="order" placeholder="مثال: 3,1,2" /><p class="hint-inline">اكتب أرقام الصفحات بالترتيب المطلوب. الصفحات غير المذكورة تُحذف.</p></div>
       <div class="actions"><button class="btn" disabled>إعادة الترتيب</button></div></div>`);
    let file = null;
    const btn = body.querySelector(".btn");
    const list = body.querySelector(".file-list");
    makeDropzone(body, "application/pdf", false, (fs) => {
      file = fs[0]; if (!file) return;
      list.innerHTML = `<li class="file-item"><span class="fi-name">📄 ${file.name}</span></li>`;
      btn.disabled = false;
    });
    btn.addEventListener("click", async () => {
      try {
        btn.disabled = true; toast("جارٍ الترتيب…");
        const src = await PDFDocument.load(await readAsBytes(file), { ignoreEncryption: true });
        const total = src.getPageCount();
        const order = (body.querySelector(".order").value || "")
          .split(",").map((s) => +s.trim() - 1).filter((n) => n >= 0 && n < total);
        if (!order.length) { toast("اكتب ترتيب صحيح", true); btn.disabled = false; return; }
        const out = await PDFDocument.create();
        const pages = await out.copyPages(src, order);
        pages.forEach((p) => out.addPage(p));
        download(await out.save(), "مُعاد-الترتيب.pdf");
        toast("تم إعادة الترتيب ✅");
      } catch (e) { console.error(e); toast("صار خطأ أثناء الترتيب", true); }
      finally { btn.disabled = false; }
    });
  };

  /* إنشاء PDF من نص */
  tools.create = function () {
    const body = shell("📝 إنشاء PDF جديد", "اكتب عنوان ومحتوى، وسننشئ لك مستند PDF بخط عربي واضح.",
      `<div>
       <div class="field"><label>العنوان</label><input type="text" class="title" placeholder="عنوان المستند" /></div>
       <div class="field"><label>المحتوى</label><textarea class="content" placeholder="اكتب محتوى المستند هنا… كل سطر بينزل بسطر."></textarea></div>
       <div class="field-row">
         <div class="field"><label>حجم الخط</label><input type="number" class="fs" value="16" min="8" /></div>
         <div class="field"><label>حجم الصفحة</label><select class="psize"><option value="a4">A4</option><option value="letter">Letter</option></select></div>
       </div>
       <div class="actions"><button class="btn">إنشاء وتحميل</button></div></div>`);
    const btn = body.querySelector(".btn");
    let arabicFontBytes = null;
    async function getArabicFont() {
      if (arabicFontBytes) return arabicFontBytes;
      const res = await fetch("https://cdn.jsdelivr.net/npm/@fontsource/cairo@5.0.19/files/cairo-arabic-400-normal.woff");
      if (!res.ok) throw new Error("font");
      arabicFontBytes = new Uint8Array(await res.arrayBuffer());
      return arabicFontBytes;
    }
    btn.addEventListener("click", async () => {
      try {
        btn.disabled = true; toast("جارٍ الإنشاء…");
        const doc = await PDFDocument.create();
        let font;
        try { doc.registerFontkit(fontkit); font = await doc.embedFont(await getArabicFont(), { subset: true }); }
        catch (_) { font = await doc.embedFont(StandardFonts.Helvetica); }
        const dims = body.querySelector(".psize").value === "letter" ? [612, 792] : [595.28, 841.89];
        const size = +body.querySelector(".fs").value;
        const title = body.querySelector(".title").value.trim();
        const content = body.querySelector(".content").value;
        const margin = 56;
        let page = doc.addPage(dims);
        let y = dims[1] - margin;
        const rtl = (s) => s; // pdf-lib يرسم النص كما هو؛ الخط العربي يحافظ على الحروف
        function line(text, fSize, gap) {
          if (y < margin + fSize) { page = doc.addPage(dims); y = dims[1] - margin; }
          const w = font.widthOfTextAtSize(text, fSize);
          const x = /[\u0600-\u06FF]/.test(text) ? dims[0] - margin - w : margin; // محاذاة يمين للعربي
          page.drawText(rtl(text), { x: Math.max(margin, x), y, size: fSize, font, color: rgb(0.1, 0.12, 0.15) });
          y -= fSize + gap;
        }
        if (title) { line(title, size + 8, 14); }
        content.split("\n").forEach((ln) => {
          if (!ln.trim()) { y -= size * 0.6; return; }
          // لفّ السطور الطويلة
          const words = ln.split(" ");
          let cur = "";
          words.forEach((w) => {
            const test = cur ? cur + " " + w : w;
            if (font.widthOfTextAtSize(test, size) > dims[0] - margin * 2) { line(cur, size, 8); cur = w; }
            else cur = test;
          });
          if (cur) line(cur, size, 8);
        });
        download(await doc.save(), (title || "مستند") + ".pdf");
        toast("تم إنشاء المستند ✅");
      } catch (e) { console.error(e); toast("صار خطأ أثناء الإنشاء", true); }
      finally { btn.disabled = false; }
    });
  };

})();
