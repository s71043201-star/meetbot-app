// 核銷文件產生器 v39 — 美化版 + pywebview 真實 API
// 視覺從 v34 美化版移植，事件全部接 window.pywebview.api

const REGION_NAMES = ["北投", "士林", "中山"];
const DEFAULT_THRESHOLDS = { 北投: 0, 士林: 0, 中山: 0 };

// pywebview API helper：等 API 注入 + 統一錯誤處理
// pywv helper：透過 fetch /api/<name> 呼叫後端，SSE 接事件
const pywv = {
  ready: Promise.resolve(),
  async call(name, ...args) {
    const r = await fetch("/api/" + name, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ args }),
    });
    const j = await r.json();
    if (!j.ok) throw new Error(j.err || "API 呼叫失敗");
    return j.result;
  },
};

// SSE：把 server 推來的 log-line / progress-update 轉成 window CustomEvent
(function () {
  if (window.__sse_started) return;
  window.__sse_started = true;
  const es = new EventSource("/api/events");
  es.addEventListener("log-line", (e) => {
    window.dispatchEvent(new CustomEvent("log-line", { detail: JSON.parse(e.data) }));
  });
  es.addEventListener("progress-update", (e) => {
    window.dispatchEvent(new CustomEvent("progress-update", { detail: JSON.parse(e.data) }));
  });
})();

const App = () => {
  // ── 檔案路徑（跟 Python 後端一致：用「絕對路徑字串」溝通） ──
  const [excel, setExcel] = React.useState("");        // 處方核發 Excel
  const [execExcel, setExecExcel] = React.useState(""); // 處方執行 Excel
  const [peopleDb, setPeopleDb] = React.useState("");   // 人員個資
  const [regionsDb, setRegionsDb] = React.useState(""); // 診所分區
  const [output, setOutput] = React.useState("");       // 輸出資料夾

  // ── 申報設定 ──
  const [year, setYear] = React.useState(115);
  const [month, setMonth] = React.useState(1);
  const [region, setRegion] = React.useState("全部");
  const [thresholds, setThresholds] = React.useState(DEFAULT_THRESHOLDS);

  // ── 文件勾選 ──
  const [docs, setDocs] = React.useState({
    doctor: { expanded: true, items: [
      { key: "gen_doctor_presc_detail", name: "處方費 民眾明細表", checked: true },
      { key: "gen_doctor_exec_detail",  name: "處方執行費 民眾明細表", checked: true },
      { key: "gen_doctor_receipt",      name: "處方費＋處方執行費 領據", checked: true },
      { key: "gen_doctor_summary",      name: "彙整總表 + Excel 統計檔", checked: true },
    ]},
    clinic: { expanded: false, items: [
      { key: "gen_health_detail",  name: "健康管理費 民眾明細表", checked: true },
      { key: "gen_health_receipt", name: "健康管理費 領據", checked: true },
      { key: "gen_health_summary", name: "健管費合併總表 + 個別 Excel", checked: true },
    ]},
    instructor: { expanded: false, items: [
      { key: "gen_treatment_detail",  name: "處方處置費 民眾明細表", checked: true },
      { key: "gen_treatment_receipt", name: "處方處置費 領據", checked: true },
      { key: "gen_treatment_summary", name: "處方處置費合併總表", checked: true },
    ]},
  });

  // ── 進階：選定診所 ──
  const [selectedClinics, setSelectedClinics] = React.useState(null); // null = 全部
  const [clinicPicker, setClinicPicker] = React.useState(null);       // {groups} or null

  // ── 流程狀態 ──
  const [progress, setProgress] = React.useState(null); // null | {pct, label, file}
  const [success, setSuccess] = React.useState(false);
  const [showLog, setShowLog] = React.useState(false);
  const [logLines, setLogLines] = React.useState([]);
  const [currentStep, setCurrentStep] = React.useState(0);
  const [maxReached, setMaxReached] = React.useState(0);
  const [toast, setToast] = React.useState(null); // {msg, kind}
  const [masterPassword, setMasterPassword] = React.useState(""); // PDF 驗證主密碼
  const [cloudPwModal, setCloudPwModal] = React.useState(false); // 從雲端帶入密碼框
  const [cloudPwInput, setCloudPwInput] = React.useState("");
  const [cloudPwErr, setCloudPwErr] = React.useState("");
  const [cloudBusy, setCloudBusy] = React.useState(false);
  const [peopleFromCloud, setPeopleFromCloud] = React.useState(false);
  const [regionsFromCloud, setRegionsFromCloud] = React.useState(false);

  // 拿到所有勾選旗標的 flat object
  const docFlags = React.useMemo(() => {
    const o = {};
    Object.values(docs).forEach(g => g.items.forEach(it => o[it.key] = it.checked));
    return o;
  }, [docs]);
  const totalDocs = Object.values(docFlags).filter(Boolean).length;

  // ── 初始化：從後端拿預設值 ──
  React.useEffect(() => {
    pywv.call("getInitialState").then((s) => {
      setYear(s.year);
      setMonth(s.month);
      setPeopleDb(s.peopleDb || "");
      setRegionsDb(s.regionsDb || "");
      setOutput(s.output || "");
      // 隱藏啟動畫面
      const boot = document.getElementById("boot");
      if (boot) { boot.classList.add("gone"); setTimeout(() => boot.remove(), 400); }
    }).catch(err => console.error("getInitialState 失敗", err));
  }, []);

  // ── 監聽後端事件 ──
  React.useEffect(() => {
    const onProgress = (e) => {
      const d = e.detail || {};
      setProgress({
        pct: Math.round((d.pct || 0) * 100),
        label: d.status || "處理中…",
        file: d.file || "",
      });
      if (d.kind === "success") {
        setTimeout(() => {
          setProgress(null);
          setSuccess(true);
          setTimeout(() => setSuccess(false), 4000);
        }, 400);
      }
    };
    const onLog = (e) => {
      setLogLines(prev => [...prev.slice(-300), e.detail]);
    };
    window.addEventListener("progress-update", onProgress);
    window.addEventListener("log-line", onLog);
    return () => {
      window.removeEventListener("progress-update", onProgress);
      window.removeEventListener("log-line", onLog);
    };
  }, []);

  // ── Step 定義 ──
  const stepDefs = [
    { n: "01", title: "匯入處方紀錄", desc: "選擇本月份的核發 Excel；如核發/執行不同月則指定執行 Excel。", complete: !!excel },
    { n: "02", title: "申報設定", desc: "設定本次申報的年月、分區，調整健管費最低份數門檻。", complete: !!year && !!month },
    { n: "03", title: "選擇要產生的文件", desc: "勾選的項目才會產出；可一次全產，也可只產缺漏的。", complete: totalDocs > 0 },
    { n: "04", title: "人員個資檔", desc: "領據需要身分證、地址、銀行資料；可從舊領據自動匯入。", complete: !!peopleDb },
    { n: "05", title: "診所分區名單", desc: "Excel 三分頁：北投／士林／中山；可指定產生子集。", complete: !!regionsDb },
    { n: "06", title: "輸出位置", desc: "選擇要把核銷文件寫到哪個資料夾。", complete: !!output },
  ];

  const goTo = (idx) => {
    if (idx < 0 || idx >= stepDefs.length) return;
    setCurrentStep(idx);
    setMaxReached(m => Math.max(m, idx));
  };

  // ── 操作 helpers ──
  const flash = (msg, kind = "info") => {
    setToast({ msg, kind });
    setTimeout(() => setToast(null), 3000);
  };

  const pickFile = async (setter, hint = "xlsx") => {
    try {
      const path = await pywv.call("pickFile", hint);
      if (path) setter(path);
    } catch (e) { flash(e.message || "選檔失敗", "err"); }
  };
  const pickFolder = async (setter) => {
    try {
      const path = await pywv.call("pickFolder");
      if (path) setter(path);
    } catch (e) { flash(e.message || "選資料夾失敗", "err"); }
  };

  const createPeopleTpl = async () => {
    if (peopleDb && await pywv.call("fileExists", peopleDb)) {
      if (!confirm("已存在個資檔，要覆蓋嗎？")) return;
    }
    try {
      const p = await pywv.call("createPeopleTemplate", peopleDb || "");
      setPeopleDb(p);
      flash("✓ 已建立空白個資範本");
    } catch (e) { flash(e.message, "err"); }
  };
  const createRegionsTpl = async () => {
    if (regionsDb && await pywv.call("fileExists", regionsDb)) {
      if (!confirm("已存在分區檔，要覆蓋嗎？")) return;
    }
    try {
      const p = await pywv.call("createRegionsTemplate", regionsDb || "");
      setRegionsDb(p);
      flash("✓ 已建立空白分區範本");
    } catch (e) { flash(e.message, "err"); }
  };

  const importFromReceipts = async () => {
    try {
      const dir = await pywv.call("pickFolder");
      if (!dir) return;
      flash("開始匯入… 請看詳細記錄");
      setShowLog(true);
      const r = await pywv.call("importFromReceipts", dir, peopleDb || "");
      setPeopleDb(r.path);
      flash(`✓ 已從舊領據匯入 ${r.count} 筆`);
    } catch (e) { flash(e.message, "err"); }
  };

  const syncRegionsFromCloud = async () => {
    try {
      const r = await pywv.call("syncRegionsFromDrive");
      if (r && r.ok) {
        if (r.path) setRegionsDb(r.path);
        setRegionsFromCloud(true);
        flash("✓ 診所分區已從雲端更新");
      } else {
        flash((r && r.message) || "雲端同步失敗", "err");
      }
    } catch (e) {
      flash((e && e.message) || "雲端同步失敗", "err");
    }
  };

  const submitCloudPeople = async () => {
    setCloudPwErr("");
    setCloudBusy(true);
    try {
      const r = await pywv.call("syncPeopleFromDrive", cloudPwInput);
      if (!r || !r.ok) {
        setCloudPwErr((r && r.message) || "帶入失敗");
        return;
      }
      setPeopleDb(r.path);
      setPeopleFromCloud(true);
      flash("✓ 人員個資已從雲端帶入");
      setCloudPwModal(false);
      setCloudPwInput("");
    } catch (e) {
      setCloudPwErr((e && e.message) || "帶入失敗");
    } finally {
      setCloudBusy(false);
    }
  };

  const openClinicPicker = async () => {
    try {
      const r = await pywv.call("loadClinics", regionsDb, excel);
      setClinicPicker({ groups: r.groups, sel: new Set(selectedClinics || []) });
    } catch (e) { flash(e.message, "err"); }
  };

  const toggleDocItem = (gKey, idx) => {
    setDocs(prev => ({
      ...prev,
      [gKey]: { ...prev[gKey], items: prev[gKey].items.map(
        (it, i) => i === idx ? { ...it, checked: !it.checked } : it) }
    }));
  };
  const toggleDocAll = (gKey) => {
    setDocs(prev => {
      const items = prev[gKey].items;
      const allOn = items.every(i => i.checked);
      return { ...prev, [gKey]: { ...prev[gKey], items: items.map(i => ({...i, checked: !allOn})) } };
    });
  };
  const toggleDocExpand = (gKey) => {
    setDocs(prev => ({ ...prev, [gKey]: { ...prev[gKey], expanded: !prev[gKey].expanded } }));
  };

  const handleGenerate = async () => {
    if (progress) return;
    if (!excel) { flash("請先選擇處方核發 Excel", "err"); goTo(0); return; }
    if (!output) { flash("請先選擇輸出資料夾", "err"); goTo(5); return; }

    setSuccess(false);
    setLogLines([]);
    setProgress({ pct: 0, label: "啟動中…", file: "" });

    const settings = {
      excel, execExcel, year, month, region,
      output, peopleDb, regionsDb,
      minByRegion: thresholds,
      selectedClinics: selectedClinics ? [...selectedClinics] : null,
      masterPassword,
      ...docFlags,
    };
    try {
      await pywv.call("generateDocs", settings);
    } catch (e) {
      setProgress(null);
      flash(`產生失敗：${e.message || e}`, "err");
    }
  };

  const handleEmail = async () => {
    if (!output) { flash("請先選擇輸出資料夾", "err"); goTo(5); return; }
    try {
      await pywv.call("openEmailPreview", { year, month, output, peopleDb, senderEmail: "" });
    } catch (e) { flash(e.message, "err"); }
  };

  return (
    <div className="app">
      <TitleBar />
      <Hero totalDocs={totalDocs} year={year} month={month} />
      <StepNav steps={stepDefs} current={currentStep} maxReached={maxReached} onJump={goTo} />
      <main className="main wizard">
        <div className="wizard-head">
          <div className="mono small dim">STEP {String(currentStep+1).padStart(2,"0")} / {String(stepDefs.length).padStart(2,"0")}</div>
          <h2 className="wizard-title">{stepDefs[currentStep].title}</h2>
          <p className="wizard-desc">{stepDefs[currentStep].desc}</p>
        </div>
        <div key={currentStep} className="wizard-body">
          {currentStep === 0 && (
            <div className="step-body">
              <FilePicker label="核發" path={excel} onPick={() => pickFile(setExcel, "xlsx")} onClear={() => setExcel("")} required />
              <FilePicker label="執行" path={execExcel} hint="留白＝同核發" onPick={() => pickFile(setExecExcel, "xlsx")} onClear={() => setExecExcel("")} />
            </div>
          )}
          {currentStep === 1 && (
            <div className="step-body">
              <ConfigGrid year={year} setYear={setYear} month={month} setMonth={setMonth} region={region} setRegion={setRegion} />
              <Thresholds thresholds={thresholds} setThresholds={setThresholds} />
            </div>
          )}
          {currentStep === 2 && (
            <div className="step-body">
              {Object.entries(docs).map(([key, d]) => (
                <DocCard key={key} dKey={key} doc={d} onToggleAll={() => toggleDocAll(key)} onToggle={(i) => toggleDocItem(key, i)} onExpand={() => toggleDocExpand(key)} />
              ))}
            </div>
          )}
          {currentStep === 3 && (
            <div className="step-body">
              <FileLine
                path={peopleDb}
                placeholder="尚未選擇個資檔"
                onPick={() => { setPeopleFromCloud(false); pickFile(setPeopleDb, "xlsx"); }}
                badge={peopleFromCloud ? "☁ 雲端帶入" : null}
              />
              <div className="actions">
                <BtnAccent icon="☁" onClick={() => { setCloudPwErr(""); setCloudPwInput(""); setCloudPwModal(true); }}>從雲端帶入（需密碼）</BtnAccent>
                <BtnGhost icon="＋" onClick={createPeopleTpl}>建立空白範本</BtnGhost>
                <BtnGhost icon="✎" onClick={() => peopleDb && pywv.call("openFile", peopleDb)}>開啟編輯</BtnGhost>
                <BtnAccent icon="↺" onClick={importFromReceipts}>從舊領據匯入</BtnAccent>
                <span className="hint">每人一行：姓名、身分證、地址、電話、銀行資訊</span>
              </div>
            </div>
          )}
          {currentStep === 4 && (
            <div className="step-body">
              <FileLine
                path={regionsDb}
                placeholder="尚未選擇分區檔"
                onPick={() => { setRegionsFromCloud(false); pickFile(setRegionsDb, "xlsx"); }}
                badge={regionsFromCloud ? "☁ 雲端帶入" : null}
              />
              <div className="actions">
                <BtnAccent icon="☁" onClick={syncRegionsFromCloud}>從雲端帶入最新分區</BtnAccent>
                <BtnGhost icon="＋" onClick={createRegionsTpl}>建立空白範本</BtnGhost>
                <BtnGhost icon="✎" onClick={() => regionsDb && pywv.call("openFile", regionsDb)}>開啟編輯</BtnGhost>
                <BtnAccent icon="▦" onClick={openClinicPicker}>選擇要產生的診所</BtnAccent>
                <span className="hint">
                  {selectedClinics === null ? "目前：全部診所（預設）" : `已選 ${selectedClinics.size} 間`}
                </span>
                {selectedClinics !== null && (
                  <button className="btn-ghost" style={{padding: "6px 10px"}} onClick={() => setSelectedClinics(null)}>重設</button>
                )}
              </div>
            </div>
          )}
          {currentStep === 5 && (
            <div className="step-body">
              <FileLine path={output} placeholder="尚未選擇輸出資料夾" onPick={() => pickFolder(setOutput)} folder />
              <div className="actions">
                <BtnGhost icon="📂" onClick={() => output && pywv.call("openFile", output)}>開啟資料夾</BtnGhost>
                <span className="hint">最終 Word/PDF/Excel 會放在這個資料夾下，依年月分組</span>
              </div>
              <div style={{ marginTop: 18 }}>
                <label className="mono small dim" style={{ display: "block", marginBottom: 6 }}>
                  🔒 PDF 驗證主密碼（選填）
                </label>
                <input
                  type="password"
                  value={masterPassword}
                  onChange={(e) => setMasterPassword(e.target.value)}
                  placeholder="留空＝不設主密碼"
                  style={{ width: "100%", padding: "10px 12px", border: "1px solid var(--line, #ddd)", borderRadius: 8, fontSize: 14 }}
                />
                <span className="hint" style={{ display: "block", marginTop: 6 }}>
                  合併 PDF 預設用該人身分證加密；填了主密碼後你也能用此密碼開啟所有 PDF（驗證用）。身分證空白者不加密，會在 receipt 資料夾留「未加密清單.txt」。
                </span>
              </div>
            </div>
          )}
        </div>
        <WizardNav
          current={currentStep}
          total={stepDefs.length}
          steps={stepDefs}
          onPrev={() => goTo(currentStep - 1)}
          onNext={() => goTo(currentStep + 1)}
          onJump={goTo}
          onGenerate={handleGenerate}
          progress={progress}
          success={success}
        />
      </main>
      <GenerateBar totalDocs={totalDocs} year={year} month={month} progress={progress} success={success} onEmail={handleEmail} />
      <LogPanel showLog={showLog} setShowLog={setShowLog} logLines={logLines} />
      <footer className="footer">
        <span>核銷文件產生器</span>
        <span className="mono">v39 · pywebview 版</span>
      </footer>
      {success && <SuccessToast count={totalDocs} year={year} month={month} onOpen={() => output && pywv.call("openFile", output)} />}
      {toast && <FlashToast {...toast} />}
      {clinicPicker && <ClinicPickerModal data={clinicPicker} onClose={() => setClinicPicker(null)} onConfirm={(sel) => { setSelectedClinics(sel); setClinicPicker(null); }} />}
      {cloudPwModal && (
        <CloudPasswordModal
          value={cloudPwInput}
          err={cloudPwErr}
          busy={cloudBusy}
          onChange={setCloudPwInput}
          onClose={() => !cloudBusy && setCloudPwModal(false)}
          onSubmit={submitCloudPeople}
        />
      )}
    </div>
  );
};

// 🔒 雲端帶入個資 — 密碼框
const CloudPasswordModal = ({ value, err, busy, onChange, onClose, onSubmit }) => (
  <div style={{
    position: "fixed", inset: 0, background: "rgba(0,0,0,.4)",
    display: "flex", alignItems: "center", justifyContent: "center", zIndex: 200,
  }} onClick={onClose}>
    <div style={{
      background: "#fff", borderRadius: 14, width: "min(440px, 92vw)",
      padding: "24px 26px",
      boxShadow: "0 20px 60px rgba(0,0,0,.25)",
    }} onClick={(e) => e.stopPropagation()}>
      <div className="mono small dim">CLOUD IMPORT</div>
      <h3 style={{ margin: "4px 0 14px", fontSize: 20 }}>🔒 從雲端帶入人員個資</h3>
      <p style={{ margin: "0 0 14px", fontSize: 13, color: "#777" }}>
        個資檔需密碼才能從 Google Drive 下載，下載後會覆蓋本機快取。
      </p>
      <input
        type="password"
        autoFocus
        value={value}
        disabled={busy}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && !busy) onSubmit(); }}
        placeholder="輸入密碼"
        style={{ width: "100%", padding: "10px 12px", border: "1px solid #DDD", borderRadius: 8, fontSize: 14, boxSizing: "border-box" }}
      />
      {err && (
        <div style={{ marginTop: 10, color: "#C0392B", fontSize: 13 }}>
          ⚠ {err}
        </div>
      )}
      <div style={{ marginTop: 18, display: "flex", justifyContent: "flex-end", gap: 8 }}>
        <button className="btn-ghost" disabled={busy} onClick={onClose}>取消</button>
        <button className="btn-accent" disabled={busy || !value} onClick={onSubmit}>
          {busy ? "下載中…" : "確認帶入"}
        </button>
      </div>
    </div>
  </div>
);

// ─── 子元件 ───────────────────────────────────────────

const TitleBar = () => (
  <div className="titlebar">
    <span className="dot"></span>
    <span className="mono small">核銷產生器</span>
    <span className="mono small dim">/ 健康台灣深耕計畫</span>
    <span className="tb-controls">
      <span className="mono small dim">v39 · pywebview</span>
    </span>
  </div>
);

const Hero = ({ totalDocs, year, month }) => {
  const [count, setCount] = React.useState(totalDocs);
  React.useEffect(() => {
    let f, start = count, target = totalDocs, t0 = performance.now(), dur = 400;
    const step = (t) => {
      const k = Math.min(1, (t - t0) / dur);
      setCount(Math.round(start + (target - start) * (1 - Math.pow(1 - k, 3))));
      if (k < 1) f = requestAnimationFrame(step);
    };
    f = requestAnimationFrame(step);
    return () => cancelAnimationFrame(f);
  }, [totalDocs]);
  return (
    <div className="hero">
      <div className="hero-meta">
        <span className="mono small dim">臺北市醫師公會 · 核銷工具</span>
        <span className="mono small dim">{year} / {String(month).padStart(2, "0")}</span>
      </div>
      <div className="hero-row">
        <div className="hero-title">
          <h1>核銷文件產生器</h1>
          <p>匯入處方紀錄與人員資料，自動產出領據、處方費等核銷文件。</p>
        </div>
        <div className="hero-stat">
          <div className="stat-label mono small">將產出</div>
          <div className="stat-num mono">{count}<span className="stat-unit"> 份</span></div>
        </div>
      </div>
    </div>
  );
};

const StepNav = ({ steps, current, maxReached, onJump }) => (
  <nav className="stepnav">
    {steps.map((s, i) => {
      const state = i === current ? "current" : i <= maxReached ? "visited" : "future";
      const accessible = i <= maxReached;
      return (
        <React.Fragment key={i}>
          {i > 0 && <span className={`stepnav-line ${i <= maxReached ? "active" : ""}`}></span>}
          <button
            className={`stepnav-item ${state}`}
            onClick={() => accessible && onJump(i)}
            disabled={!accessible}
          >
            <span className="stepnav-circle">
              {s.complete && i !== current ? <span className="stepnav-tick">✓</span> : <span className="mono">{s.n}</span>}
            </span>
            <span className="stepnav-label">{s.title}</span>
          </button>
        </React.Fragment>
      );
    })}
  </nav>
);

const WizardNav = ({ current, total, steps, onPrev, onNext, onJump, onGenerate, progress, success }) => {
  const [openJump, setOpenJump] = React.useState(false);
  const ref = React.useRef(null);
  const btnRef = React.useRef(null);
  const isLast = current >= total - 1;
  const onMove = (e) => {
    const el = btnRef.current; if (!el) return;
    const r = el.getBoundingClientRect();
    el.style.setProperty('--mx', `${e.clientX - r.left}px`);
    el.style.setProperty('--my', `${e.clientY - r.top}px`);
  };
  React.useEffect(() => {
    if (!openJump) return;
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpenJump(false); };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [openJump]);
  return (
    <div className="wizard-nav">
      <button className="btn-ghost wnav-prev" onClick={onPrev} disabled={current === 0}>
        <span className="btn-icon">←</span> 上一步
      </button>
      <div className="wnav-center" ref={ref}>
        <button className="wnav-jump" onClick={() => setOpenJump(o => !o)}>
          跳至… <span className={`chev ${openJump ? "open" : ""}`}>▾</span>
        </button>
        {openJump && (
          <div className="wnav-jump-menu">
            <div className="wnav-jump-title mono small dim">跳到</div>
            {steps.map((s, i) => (
              <button
                key={i}
                className={`wnav-jump-item ${i === current ? "current" : ""}`}
                onClick={() => { onJump(i); setOpenJump(false); }}
              >
                <span className="mono small">{s.n}</span>
                <span>{s.title}</span>
                {i === current && <span className="mono small dim">當前</span>}
              </button>
            ))}
          </div>
        )}
      </div>
      {isLast ? (
        <button
          ref={btnRef}
          onMouseMove={onMove}
          className={`btn-primary glow wnav-generate ${progress ? "loading" : ""} ${success ? "success" : ""}`}
          onClick={onGenerate}
          disabled={!!progress}
        >
          {progress ? (
            <span className="btn-progress">
              <span className="mono small">{progress.label}</span>
              <span className="mono small">{progress.pct}%</span>
              <span className="bar"><span className="bar-fill" style={{ width: `${progress.pct}%` }}></span></span>
            </span>
          ) : success ? (
            <span className="btn-content"><span className="check">✓</span> 完成</span>
          ) : (
            <span className="btn-content">⚡ 產生文件 <span className="arrow">→</span></span>
          )}
        </button>
      ) : (
        <button className="btn-accent wnav-next" onClick={onNext}>
          下一步 <span className="btn-icon">→</span>
        </button>
      )}
    </div>
  );
};

const FilePicker = ({ label, path, hint, onPick, onClear, required }) => {
  const filename = path ? path.split(/[\\/]/).pop() : "";
  return (
    <div
      className={`file-drop ${path ? "loaded" : ""}`}
      onClick={onPick}
    >
      <div className="fd-label">{label}{required ? " *" : ""}</div>
      <div className="fd-content">
        {path ? (
          <>
            <span className="fd-icon fd-icon-loaded">📄</span>
            <span className="mono small fd-name fd-name-loaded">{filename}</span>
            <span className="fd-status fd-status-loaded">已載入</span>
          </>
        ) : (
          <span className="fd-prompt"><span className="fd-icon">⊕</span> {hint || "點擊選擇 Excel 檔"}</span>
        )}
      </div>
      {path && onClear && (
        <button className="fd-clear" onClick={(e) => { e.stopPropagation(); onClear(); }}>×</button>
      )}
    </div>
  );
};

const FileLine = ({ path, placeholder, onPick, folder, badge }) => {
  const filename = path ? path.split(/[\\/]/).pop() : "";
  const dir = path ? path.replace(/[\\/][^\\/]*$/, "") : "";
  return (
    <div className="file-line" onClick={onPick}>
      <span className="fl-dot"></span>
      <span className="fl-content">
        <span className="mono small fl-name-anim">{filename || placeholder}</span>
        {badge && (
          <span style={{
            marginLeft: 8, padding: "2px 8px", fontSize: 11,
            background: "#E8F5E9", color: "#2E7D32",
            borderRadius: 10, fontWeight: 600, letterSpacing: "0.04em",
          }}>{badge}</span>
        )}
        {dir && <span className="mono small dim fl-path"> · {dir}</span>}
      </span>
      <span className="fl-action">{folder ? "選擇資料夾" : "變更"} →</span>
    </div>
  );
};

const ConfigGrid = ({ year, setYear, month, setMonth, region, setRegion }) => (
  <div className="config-grid">
    <Field label="YEAR · 民國">
      <input type="number" value={year} onChange={(e) => setYear(+e.target.value)} className="num-input" />
    </Field>
    <Field label="MONTH · 月份">
      <Combobox
        value={month}
        options={Array.from({length: 12}, (_, i) => ({ value: i+1, label: String(i+1).padStart(2, "0"), suffix: "月" }))}
        onChange={setMonth}
      />
    </Field>
    <Field label="DISTRICT · 分區">
      <Combobox
        value={region}
        options={["全部", ...REGION_NAMES].map(v => ({ value: v, label: v }))}
        onChange={setRegion}
      />
    </Field>
  </div>
);

const Combobox = ({ value, options, onChange }) => {
  const [open, setOpen] = React.useState(false);
  const [hover, setHover] = React.useState(-1);
  const ref = React.useRef(null);
  const current = options.find(o => o.value === value) || options[0];
  const currentIdx = options.findIndex(o => o.value === value);
  React.useEffect(() => {
    if (!open) return;
    setHover(currentIdx);
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    const onKey = (e) => {
      if (e.key === "Escape") setOpen(false);
      if (e.key === "ArrowDown") { e.preventDefault(); setHover(h => Math.min(options.length - 1, h + 1)); }
      if (e.key === "ArrowUp") { e.preventDefault(); setHover(h => Math.max(0, h - 1)); }
      if (e.key === "Enter") { e.preventDefault(); if (hover >= 0) { onChange(options[hover].value); setOpen(false); } }
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
  }, [open, hover, currentIdx, options, onChange]);
  return (
    <div className={`combo ${open ? "open" : ""}`} ref={ref}>
      <button className="combo-trigger" onClick={() => setOpen(o => !o)}>
        <span className="combo-value">
          <span className="mono combo-label">{current.label}</span>
          {current.suffix && <span className="combo-suffix">{current.suffix}</span>}
        </span>
        <span className={`combo-chev ${open ? "open" : ""}`}>▾</span>
      </button>
      {open && (
        <div className="combo-menu">
          {options.map((opt, i) => (
            <button
              key={opt.value}
              className={`combo-item ${opt.value === value ? "selected" : ""} ${i === hover ? "hover" : ""}`}
              onMouseEnter={() => setHover(i)}
              onClick={() => { onChange(opt.value); setOpen(false); }}
            >
              <span className="mono combo-item-label">{opt.label}</span>
              {opt.suffix && <span className="combo-item-suffix">{opt.suffix}</span>}
              {opt.value === value && <span className="combo-check">✓</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

const Field = ({ label, children }) => (
  <div className="field">
    <div className="mono small dim field-label">{label}</div>
    {children}
  </div>
);

const Thresholds = ({ thresholds, setThresholds }) => (
  <div className="thresh">
    <div className="thresh-head">
      <h3>健管費最低份數</h3>
      <span className="hint">填 0 代表不過濾、全部產出</span>
    </div>
    <div className="thresh-grid">
      {REGION_NAMES.map((k) => (
        <div key={k} className="thresh-item">
          <span className="thresh-k">{k}</span>
          <input
            type="number" step="4"
            value={thresholds[k] || 0}
            onChange={(e) => setThresholds({ ...thresholds, [k]: +e.target.value })}
            className="num-input thresh-input"
          />
          <span className="mono small dim">份</span>
        </div>
      ))}
    </div>
  </div>
);

const DocCard = ({ dKey, doc, onToggleAll, onToggle, onExpand }) => {
  const checkedCount = doc.items.filter(i => i.checked).length;
  const total = doc.items.length;
  const allChecked = checkedCount === total;
  const noneChecked = checkedCount === 0;
  const titles = { doctor: "【醫師】處方費 / 處方執行費", clinic: "【診所】健康管理費", instructor: "【課程老師】處方處置費" };
  const kinds = { doctor: "DOCTOR", clinic: "CLINIC", instructor: "INSTRUCTOR" };
  return (
    <div className={`doc-card ${noneChecked ? "unchecked" : "checked"}`}>
      <div className="doc-row">
        <button className="checkbox" onClick={onToggleAll} aria-pressed={allChecked}>
          <span className={`check-box ${allChecked ? "all" : !noneChecked ? "some" : ""}`}>
            {allChecked && <span className="check-mark">✓</span>}
            {!allChecked && !noneChecked && <span className="check-dash"></span>}
          </span>
        </button>
        <div className="doc-info">
          <div className="mono small dim">{kinds[dKey]}</div>
          <div className="doc-title">{titles[dKey]}</div>
        </div>
        <span className={`doc-count ${noneChecked ? "muted" : ""} mono`}>
          {checkedCount}/{total}
        </span>
        <button className="doc-expand" onClick={onExpand}>
          詳情 <span className={`chev ${doc.expanded ? "open" : ""}`}>▾</span>
        </button>
      </div>
      <div className={`doc-details ${doc.expanded ? "open" : ""}`}>
        <div className="details-inner">
          {doc.items.map((item, i) => (
            <button
              key={i}
              className={`detail-item ${item.checked ? "on" : "off"}`}
              onClick={() => onToggle(i)}
            >
              <span className="mono small dim">{String(i+1).padStart(2, "0")}</span>
              <span className={`mini-check ${item.checked ? "on" : ""}`}>
                {item.checked && <span className="mini-check-mark">✓</span>}
              </span>
              <span className="detail-name">{item.name}</span>
              <span className={`mono small ${item.checked ? "ok" : "skip"}`}>
                {item.checked ? "● 將產出" : "○ 跳過"}
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};

const BtnGhost = ({ icon, children, onClick }) => (
  <button className="btn-ghost" onClick={onClick}>
    {icon && <span className="btn-icon">{icon}</span>}
    {children}
  </button>
);
const BtnAccent = ({ icon, children, onClick }) => (
  <button className="btn-accent" onClick={onClick}>
    {icon && <span className="btn-icon">{icon}</span>}
    {children}
  </button>
);

const GenerateBar = ({ totalDocs, year, month, progress, success, onEmail }) => {
  const ref = React.useRef(null);
  const [stuck, setStuck] = React.useState(false);
  React.useEffect(() => {
    if (!ref.current) return;
    const sentinel = document.createElement('div');
    sentinel.style.cssText = 'position:absolute;bottom:100%;height:1px;width:1px;';
    ref.current.appendChild(sentinel);
    const io = new IntersectionObserver(([e]) => setStuck(!e.isIntersecting), { threshold: 0 });
    io.observe(sentinel);
    return () => io.disconnect();
  }, []);
  return (
    <div ref={ref} className={`genbar genbar-summary-only ${stuck ? 'stuck' : ''}`}>
      <div className="genbar-info">
        <div className="mono small dim">{progress ? "GENERATING" : success ? "DONE" : "READY TO GENERATE"}</div>
        <div className="genbar-summary">
          <span className="mono genbar-num">{totalDocs}</span>
          <span className="genbar-unit">份文件 ·</span>
          <span className="mono dim">{year}/{String(month).padStart(2, "0")}</span>
        </div>
      </div>
      <div className="genbar-status mono small dim" style={{flex: 1, textAlign: "right"}}>
        {progress ? `${progress.label}${progress.file ? ` · ${progress.file}` : ""} · ${progress.pct}%` : success ? "✓ 已產出至資料夾" : "前往最後一步以產生"}
      </div>
      <button className="btn-ghost" onClick={onEmail} style={{marginLeft: "16px"}}>
        <span className="btn-icon">📧</span> 預覽並寄送 Gmail
      </button>
    </div>
  );
};

const LogPanel = ({ showLog, setShowLog, logLines }) => (
  <div className={`logpanel ${showLog ? "open" : ""}`}>
    <button className="logpanel-toggle" onClick={() => setShowLog(s => !s)}>
      <span className="mono small dim">DETAILS</span>
      <span className="logpanel-toggle-label">
        {showLog ? "隱藏詳細記錄" : "顯示詳細記錄"}
      </span>
      <span className={`chev ${showLog ? "open" : ""}`}>▾</span>
      {logLines.length > 0 && (
        <span className="logpanel-count mono small">{logLines.length} 條</span>
      )}
    </button>
    {showLog && (
      <div className="logpanel-body">
        {logLines.length === 0 ? (
          <div className="logpanel-empty mono small dim">尚無紀錄。產生文件時這裡會即時顯示處理過程。</div>
        ) : (
          <div className="logpanel-lines mono small">
            {logLines.map((line, i) => (
              <div key={i} className="logpanel-line">
                <span className="logpanel-idx dim">{String(i+1).padStart(3, "0")}</span>
                <span style={{whiteSpace: "pre-wrap"}}>{line}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    )}
  </div>
);

const SuccessToast = ({ count, year, month, onOpen }) => (
  <div className="toast">
    <span className="toast-check">✓</span>
    <div>
      <div className="toast-title">已產出 {count} 份文件</div>
      <div className="mono small dim">資料夾：{year}年{String(month).padStart(2,"0")}月／</div>
    </div>
    <button className="toast-action" onClick={onOpen}>開啟資料夾 →</button>
  </div>
);

const FlashToast = ({ msg, kind }) => (
  <div className="toast" style={{
    background: kind === "err" ? "#D4452C" : "#0A0A0A",
  }}>
    <span className="toast-check" style={{
      background: kind === "err" ? "rgba(255,255,255,.2)" : "var(--ok)"
    }}>
      {kind === "err" ? "!" : "i"}
    </span>
    <div>
      <div className="toast-title" style={{whiteSpace: "pre-wrap"}}>{msg}</div>
    </div>
  </div>
);

// ─── 診所選擇 Modal ───
const ClinicPickerModal = ({ data, onClose, onConfirm }) => {
  const [sel, setSel] = React.useState(data.sel);
  const toggle = (c) => {
    const s = new Set(sel);
    if (s.has(c)) s.delete(c); else s.add(c);
    setSel(s);
  };
  const allCount = data.groups.reduce((n, [_, cs]) => n + cs.length, 0);
  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,.4)",
      display: "flex", alignItems: "center", justifyContent: "center", zIndex: 200,
    }} onClick={onClose}>
      <div style={{
        background: "#fff", borderRadius: 14, width: "min(560px, 92vw)",
        maxHeight: "82vh", display: "flex", flexDirection: "column",
        boxShadow: "0 20px 60px rgba(0,0,0,.25)",
      }} onClick={(e) => e.stopPropagation()}>
        <div style={{ padding: "20px 24px 12px", borderBottom: "1px solid #E8E8E5" }}>
          <div className="mono small dim">CLINIC PICKER</div>
          <h3 style={{ margin: "4px 0 0", fontSize: 20 }}>選擇要產生的診所</h3>
          <div className="mono small dim" style={{ marginTop: 6 }}>
            已選 {sel.size} / {allCount}
          </div>
        </div>
        <div style={{ overflowY: "auto", padding: "8px 12px", flex: 1 }}>
          {data.groups.map(([region, clinics]) => (
            <div key={region} style={{ marginBottom: 16 }}>
              <div style={{
                display: "flex", alignItems: "center", gap: 8,
                padding: "8px 12px", fontSize: 13, fontWeight: 600,
              }}>
                <span>{region}</span>
                <button className="btn-ghost" style={{ padding: "2px 8px", fontSize: 11 }}
                  onClick={() => {
                    const s = new Set(sel);
                    const allOn = clinics.every(c => s.has(c));
                    clinics.forEach(c => allOn ? s.delete(c) : s.add(c));
                    setSel(s);
                  }}>
                  全選/取消
                </button>
              </div>
              {clinics.map(c => (
                <label key={c} style={{
                  display: "flex", alignItems: "center", gap: 10,
                  padding: "8px 14px", borderRadius: 8, cursor: "pointer",
                  background: sel.has(c) ? "#F2F2EF" : "transparent",
                }}>
                  <input type="checkbox" checked={sel.has(c)} onChange={() => toggle(c)} />
                  <span style={{ fontSize: 13 }}>{c}</span>
                </label>
              ))}
            </div>
          ))}
        </div>
        <div style={{
          padding: "14px 20px", borderTop: "1px solid #E8E8E5",
          display: "flex", gap: 10, justifyContent: "flex-end",
        }}>
          <BtnGhost onClick={() => setSel(new Set())}>清除</BtnGhost>
          <BtnGhost onClick={onClose}>取消</BtnGhost>
          <button className="btn-primary" style={{ minWidth: "auto", height: 40, padding: "0 18px" }}
            onClick={() => onConfirm(sel.size === 0 ? null : sel)}>
            確定（{sel.size === 0 ? "全部" : sel.size + " 間"}）
          </button>
        </div>
      </div>
    </div>
  );
};

// ─── 載入子元件（從外部 jsx 檔，避免單檔過大）──────────
ReactDOM.createRoot(document.getElementById("root")).render(<App />);
