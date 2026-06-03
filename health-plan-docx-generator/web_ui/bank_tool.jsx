/* eslint-disable */
// 富邦匯款上傳檔 — 匯入已產出核銷資料（獨立頁）
// 相容兩種後端：pywebview（window.pywebview.api）與瀏覽器版（fetch /api）
const { useState, useEffect, useRef } = React;

const call = async (name, ...args) => {
  if (window.pywebview && window.pywebview.api) {
    return window.pywebview.api[name](...args);
  }
  const r = await fetch("/api/" + name, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ args }),
  });
  const j = await r.json();
  if (!j.ok) throw new Error(j.err || "API 呼叫失敗");
  return j.result;
};

function App() {
  const [folder, setFolder] = useState("");
  const [peopleDb, setPeopleDb] = useState("");
  const [year, setYear] = useState(115);
  const [month, setMonth] = useState(1);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState("");
  const [logs, setLogs] = useState([]);
  const logRef = useRef(null);

  useEffect(() => {
    call("getBankToolInit").then((s) => {
      if (s) { setYear(s.year); setMonth(s.month); }
    }).catch(() => {});
    // 瀏覽器版：訂閱 SSE log（pywebview 版用 dispatchEvent）
    const onLog = (e) => {
      const line = typeof e.detail === "string" ? e.detail : JSON.stringify(e.detail);
      setLogs((prev) => [...prev, line]);
    };
    window.addEventListener("log-line", onLog);
    let es = null;
    try {
      if (!(window.pywebview && window.pywebview.api)) {
        es = new EventSource("/api/events");
        es.addEventListener("log-line", (e) => {
          window.dispatchEvent(new CustomEvent("log-line", { detail: JSON.parse(e.data) }));
        });
      }
    } catch (_) {}
    return () => { window.removeEventListener("log-line", onLog); if (es) es.close(); };
  }, []);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [logs]);

  const pickFolder = async () => {
    const p = await call("pickFolder");
    if (p) {
      setFolder(p);
      // 從資料夾名稱自動帶入年月（例如 …\115年04月）避免月份選錯
      const m = p.match(/(\d{2,3})\s*年\s*0*(\d{1,2})\s*月/);
      if (m) { setYear(+m[1]); setMonth(+m[2]); }
    }
  };
  const pickPeople = async () => {
    const p = await call("pickFile", "xlsx");
    if (p) setPeopleDb(p);
  };

  const openOutput = async () => {
    if (!result || !result.path) return;
    try {
      const ok = await call("openFile", result.path);
      if (ok === false) {
        setErr("無法自動開啟（可能無關聯程式或檔案被佔用），請手動開啟：" + result.path);
      }
    } catch (e) {
      setErr("開啟失敗：" + (e.message || e) + "　路徑：" + result.path);
    }
  };

  const generate = async () => {
    if (!folder) { setErr("請先選擇已產出的核銷月份資料夾"); return; }
    setErr(""); setResult(null); setBusy(true); setLogs([]);
    try {
      const r = await call("generateBankFromReceipts", folder, year, month, peopleDb);
      setResult(r);
      if (r && !r.path) {
        const sk = (r.stats && r.stats.skipped) || 0;
        setErr("已讀取領據，但沒有可匯款對象（" + sk + " 筆缺帳號/銀行代碼），故未產生檔案。"
          + "若領據是在更新前產生、當時未帶入銀行帳戶，請重新產生核銷文件（含個資）後再試。");
      }
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  const st = result && result.stats;

  return (
    <div className="wrap">
      <h1>富邦匯款上傳檔</h1>
      <p className="sub">匯入「已產出的核銷月份資料夾」，自動讀回領據（姓名 / 帳戶 / 實付金額），
        填入富邦範本的整批轉帳、整批匯款與報稅基本資料三頁。產出檔放在所選資料夾內。</p>

      <div className="card">
        <span className="lbl">① 核銷月份資料夾（必選）</span>
        <div className="path">{folder || "尚未選擇（例如 …\\核銷文件\\115年01月）"}</div>
        <div className="row"><button onClick={pickFolder}>選擇資料夾</button></div>
      </div>

      <div className="card">
        <span className="lbl">② 人員個資檔（選用，補「身分別」以決定報稅類別）</span>
        <div className="path">{peopleDb || "未選擇 — 將依角色推定類別（醫師＝執業所得、課程老師＝薪資）"}</div>
        <div className="row"><button onClick={pickPeople}>選擇個資檔</button></div>
      </div>

      <div className="card">
        <span className="lbl">③ 申報年月（影響交易明細留言月份）</span>
        <div className="row">
          民國 <input type="number" value={year} onChange={(e) => setYear(+e.target.value)} /> 年
          <input type="number" value={month} min="1" max="12" onChange={(e) => setMonth(+e.target.value)} /> 月
        </div>
      </div>

      <div className="row">
        <button className="primary" onClick={generate} disabled={busy}>
          {busy ? "產生中…" : "產生富邦匯款上傳檔"}
        </button>
        {result && result.path && (
          <button onClick={openOutput}>開啟產出檔</button>
        )}
        {result && result.path && (
          <button onClick={() => call("openFile", folder)}>開啟資料夾</button>
        )}
      </div>

      {result && result.path && (
        <p className="hint" style={{ marginTop: 8, wordBreak: "break-all" }}>
          產出檔：{result.path}
        </p>
      )}

      {err && <p className="err" style={{ marginTop: 12 }}>⚠ {err}</p>}

      {st && (
        <div className="card" style={{ marginTop: 16 }}>
          <div className="stat ok"><span>富邦轉帳 <b>{st.fubon}</b> 筆</span>
            <span>跨行匯款 <b>{st.other}</b> 筆</span>
            <span>報稅清單 <b>{st.tax_rows || 0}</b> 筆</span>
            <span>匯款總額 <b>{(st.total_amount || 0).toLocaleString()}</b> 元（實付）</span>
          </div>
          {st.skipped > 0 && (
            <>
              <p className="warn" style={{ margin: "8px 0 4px" }}>
                缺帳戶 {st.skipped} 筆 — 已列入「缺帳戶清單」分頁並計入金額（實付小計 {(st.missing_total_net || 0).toLocaleString()} 元），待補帳戶後可手動轉入匯款頁：
              </p>
              <table className="skip">
                <thead><tr><th>姓名</th><th>角色</th><th>原因</th></tr></thead>
                <tbody>
                  {(st.skipped_detail || []).map((s, i) => (
                    <tr key={i}><td>{s[0]}</td><td>{s[1]}</td><td>{s[2]}</td></tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>
      )}

      <div className="card">
        <span className="lbl">處理紀錄</span>
        <div className="log" ref={logRef}>{logs.join("\n") || "（尚未開始）"}</div>
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
