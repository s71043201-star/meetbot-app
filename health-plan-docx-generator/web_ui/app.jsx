/* eslint-disable */
const { useState, useEffect, useRef, useCallback } = React;

// ─── pywebview API helper ───
const api = (() => {
  const wait = () => new Promise((resolve) => {
    if (window.pywebview && window.pywebview.api) {
      resolve(window.pywebview.api);
    } else {
      window.addEventListener('pywebviewready', () => resolve(window.pywebview.api));
    }
  });
  return new Proxy({}, {
    get: (_, name) => async (...args) => {
      const a = await wait();
      if (typeof a[name] === 'function') return a[name](...args);
      throw new Error('API not found: ' + name);
    },
  });
})();

// ─── Toast ───
function Toast({ msg, kind, onClose }) {
  useEffect(() => {
    const t = setTimeout(onClose, 3500);
    return () => clearTimeout(t);
  }, []);
  return <div className={`toast ${kind || ''}`}>{msg}</div>;
}

// ─── Stepper ───
const STEPS = [
  { id: 0, label: '匯入', validate: 'validateImport' },
  { id: 1, label: '申報', validate: 'validateSettings' },
  { id: 2, label: '文件', validate: 'validateOutputs' },
  { id: 3, label: '人員', validate: 'validatePeople' },
  { id: 4, label: '分區', validate: 'validateRegions' },
  { id: 5, label: '輸出', validate: 'validateOutput' },
];

function StepperHeader({ current, onClick }) {
  return (
    <div className="stepper-bar">
      {STEPS.map((s, i) => (
        <React.Fragment key={s.id}>
          <button
            className={`step-pill ${i === current ? 'active' : ''} ${i < current ? 'done' : ''}`}
            onClick={() => onClick(i)}
          >
            <span className="num">{i + 1}</span>
            <span>{s.label}</span>
          </button>
          {i < STEPS.length - 1 && (
            <span className={`step-connector ${i < current ? 'done' : ''}`} />
          )}
        </React.Fragment>
      ))}
    </div>
  );
}

// ─── 區塊標題 ───
function SectionHead({ num, title, sub }) {
  return (
    <div className="section-head">
      <div className="section-num">{num}</div>
      <div>
        <div className="section-title">{title}</div>
        {sub && <div className="section-sub">{sub}</div>}
      </div>
    </div>
  );
}

// ─── 檔案/資料夾選擇器 ───
function FilePicker({ value, onChange, kind, placeholder, accept }) {
  const pick = async () => {
    const sel = kind === 'folder'
      ? await api.pickFolder()
      : await api.pickFile(accept || '');
    if (sel) onChange(sel);
  };
  return (
    <div className="card-row">
      <input
        type="text" value={value || ''}
        placeholder={placeholder || '尚未選擇…'}
        onChange={(e) => onChange(e.target.value)}
        style={{ flex: 1 }}
      />
      <button className="btn btn-secondary" onClick={pick}>選擇{kind === 'folder' ? '資料夾' : '檔案'}</button>
    </div>
  );
}

// ─── Step 1：匯入 ───
function StepImport({ s, set }) {
  return (
    <>
      <SectionHead num="01" title="匯入處方紀錄"
        sub="選擇本月的處方紀錄 Excel —— 開立檔與執行檔分開匯入，方便跨月核銷" />
      <div className="card">
        <div className="field">
          <label className="label">開立處方 Excel</label>
          <div className="label-hint">處方費 + 健康管理費</div>
          <FilePicker value={s.excel} onChange={(v) => set({ excel: v })}
            accept=".xlsx" placeholder="尚未選擇檔案…" />
        </div>
        <div className="field">
          <label className="label">執行處方 Excel</label>
          <div className="label-hint">處方執行費 + 處方處置費；留空則用開立檔</div>
          <FilePicker value={s.execExcel} onChange={(v) => set({ execExcel: v })}
            accept=".xlsx" placeholder="（選填）尚未選擇檔案…" />
        </div>
      </div>
    </>
  );
}

// ─── Step 2：申報 ───
const REGIONS = ['北投', '士林', '中山'];
function StepSettings({ s, set }) {
  const setMin = (region, val) => set({
    minByRegion: { ...s.minByRegion, [region]: val }
  });
  const showRegion = (r) => s.region === '全部' || s.region === r;

  return (
    <>
      <SectionHead num="02" title="申報設定"
        sub="設定申報年月、要產出的分區，以及各區健康管理費的最低處方份數門檻" />
      <div className="card">
        <div className="card-row" style={{ marginBottom: 16 }}>
          <div style={{ flex: '0 0 100px' }}>
            <label className="label">申報年度</label>
            <input type="number" className="mono" value={s.year}
              onChange={(e) => set({ year: e.target.value })}
              style={{ textAlign: 'center', fontSize: 16, fontWeight: 700 }} />
          </div>
          <div style={{ flex: '0 0 100px' }}>
            <label className="label">月份</label>
            <select value={s.month} onChange={(e) => set({ month: e.target.value })}
              className="mono" style={{ textAlign: 'center', fontSize: 16, fontWeight: 700 }}>
              {[...Array(12)].map((_, i) => (
                <option key={i + 1} value={i + 1}>{i + 1}</option>
              ))}
            </select>
          </div>
          <div style={{ flex: '0 0 140px' }}>
            <label className="label">分區</label>
            <select value={s.region} onChange={(e) => set({ region: e.target.value })}>
              <option value="全部">全部</option>
              {REGIONS.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
        </div>

        <div style={{ borderTop: '1px solid var(--border)', paddingTop: 16, marginTop: 8 }}>
          <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 4 }}>
            健康管理費最低處方份數門檻
          </div>
          <div className="label-hint" style={{ marginBottom: 12 }}>
            皆需為 6 的倍數（對應人數需為整數）；0 = 不過濾、顯示 X/XX
          </div>
          <div className="region-grid">
            {REGIONS.filter(showRegion).map((r) => (
              <div className="region-cell" key={r}>
                <div className="region-cell-label">{r}</div>
                <input type="number" className="mono"
                  value={s.minByRegion[r] || '0'}
                  onChange={(e) => setMin(r, e.target.value)}
                  style={{ textAlign: 'center', fontWeight: 700 }} />
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}

// ─── Step 3：選文件 ───
const GROUPS = [
  {
    key: 'doctor', title: '【醫師】處方費 / 處方執行費',
    items: [
      ['gen_doctor_presc_detail', '處方處方費民眾明細/', '每位醫師的處方費民眾明細表'],
      ['gen_doctor_exec_detail', '處方執行費民眾明細/', '每位醫師的處方執行費民眾明細表'],
      ['gen_doctor_receipt', '處方處方費與處方執行費領據/', '每位醫師合併的領據(處方費 + 執行費)'],
      ['gen_doctor_summary', '其他內容/處方費、處方執行費總表明細表合併檔與Excel/', '醫師彙整總表(全部合併) + Excel 統計檔'],
    ],
  },
  {
    key: 'health', title: '【診所】健康管理費',
    items: [
      ['gen_health_detail', '健康管理費民眾明細/', '每間診所的民眾明細表'],
      ['gen_health_receipt', '健康管理費領據/', '每間診所的領據(對應診所行政人員)'],
      ['gen_health_summary', '其他內容/健康管理費合併總表與個人excel/', '健管費彙整總表 + 各診所個別 Excel'],
    ],
  },
  {
    key: 'treatment', title: '【課程老師】處方處置費',
    items: [
      ['gen_treatment_detail', '處方處置費民眾明細/', '每位老師的民眾明細表'],
      ['gen_treatment_receipt', '處方處置費領據/', '每位老師的領據'],
      ['gen_treatment_summary', '其他內容/處方處置費合併總表word/', '處方處置費核銷總表 + 執行人員民眾明細表(合併版)'],
    ],
  },
];

function GroupDetailModal({ group, s, set, onClose }) {
  const setItem = (k, v) => set({ [k]: v });
  const all = (val) => {
    const patch = {};
    group.items.forEach(([k]) => patch[k] = val);
    set(patch);
  };
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 720 }}>
        <div className="modal-title">◢ {group.title}</div>
        <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 12 }}>
          勾選 = 該資料夾才會產出。每個資料夾獨立控制。
        </div>
        <div className="card-row" style={{ marginBottom: 12 }}>
          <button className="btn btn-secondary btn-sm" onClick={() => all(true)}>✓ 全選</button>
          <button className="btn btn-ghost btn-sm" onClick={() => all(false)}>✕ 全不選</button>
        </div>
        <div className="modal-body">
          {group.items.map(([k, folder, desc]) => (
            <div className="detail-row" key={k}>
              <input type="checkbox" checked={s[k]} onChange={(e) => setItem(k, e.target.checked)}
                style={{ width: 18, height: 18, accentColor: 'var(--accent)' }} />
              <div style={{ flex: 1 }}>
                <div className="detail-folder">📁 {folder}</div>
                <div className="detail-desc">{desc}</div>
              </div>
            </div>
          ))}
        </div>
        <div className="modal-footer">
          <button className="btn btn-success" onClick={onClose}>完成</button>
        </div>
      </div>
    </div>
  );
}

function StepOutputs({ s, set }) {
  const [detailGroup, setDetailGroup] = useState(null);
  const groupStatus = (g) => {
    const n = g.items.filter(([k]) => s[k]).length;
    const total = g.items.length;
    if (n === total) return { kind: 'success', text: `${total}/${total} 項全部產出` };
    if (n === 0) return { kind: 'danger', text: '整組不產出' };
    return { kind: 'warn', text: `部分產出 (${n}/${total} 項)` };
  };
  const toggleGroup = (g) => {
    const allOn = g.items.every(([k]) => s[k]);
    const patch = {};
    g.items.forEach(([k]) => patch[k] = !allOn);
    set(patch);
  };
  return (
    <>
      <SectionHead num="03" title="選擇要產生的文件"
        sub="三大群組共 10 項，勾選 = 該資料夾才會產出。點「詳情」可微調每一項" />
      {GROUPS.map((g) => {
        const st = groupStatus(g);
        const allOn = g.items.every(([k]) => s[k]);
        return (
          <div className="card group-card" key={g.key}>
            <div className="group-row">
              <input type="checkbox" checked={allOn}
                onChange={() => toggleGroup(g)}
                style={{ width: 18, height: 18, accentColor: 'var(--accent)' }} />
              <div className="group-title">{g.title}</div>
              <div className={`group-status ${st.kind}`}>{st.text}</div>
              <button className="btn btn-secondary btn-sm"
                onClick={() => setDetailGroup(g)}>詳情 ▼</button>
            </div>
          </div>
        );
      })}
      {detailGroup && (
        <GroupDetailModal group={detailGroup} s={s} set={set}
          onClose={() => setDetailGroup(null)} />
      )}
    </>
  );
}

// ─── Step 4：人員 ───
function StepPeople({ s, set, log }) {
  const [showCloud, setShowCloud] = useState(false);
  const [cloudPw, setCloudPw] = useState('');
  const [cloudErr, setCloudErr] = useState('');
  const [cloudBusy, setCloudBusy] = useState(false);

  const importFromReceipts = async () => {
    const dir = await api.pickFolder();
    if (!dir) return;
    log('── 從舊領據匯入 ──');
    try {
      const result = await api.importFromReceipts(dir, s.peopleDb);
      log(`完成！共 ${result.count} 筆人員資料已存入:\n${result.path}`);
      window.alert(`已將 ${result.count} 筆人員資料存入個資檔\n\n${result.path}`);
      await api.openFile(result.path);
    } catch (e) {
      window.alert('匯入失敗: ' + e.message);
    }
  };

  const submitCloud = async () => {
    setCloudErr('');
    setCloudBusy(true);
    try {
      const r = await api.syncPeopleFromDrive(cloudPw);
      if (!r || !r.ok) {
        setCloudErr(r?.message || '帶入失敗');
        return;
      }
      set({ peopleDb: r.path });
      log(`✓ 人員個資已從雲端帶入: ${r.path}`);
      setShowCloud(false);
      setCloudPw('');
    } catch (e) {
      setCloudErr(e.message);
    } finally {
      setCloudBusy(false);
    }
  };

  return (
    <>
      <SectionHead num="04" title="人員個資（選填）"
        sub="醫師、診所、課程老師的姓名、身分證、地址、電話、銀行資訊。可從舊領據自動匯入" />
      <div className="card">
        <div className="field">
          <label className="label">個資 Excel 路徑</label>
          <FilePicker value={s.peopleDb} onChange={(v) => set({ peopleDb: v })}
            accept=".xlsx" />
        </div>
        <div className="card-row" style={{ marginBottom: 8 }}>
          <button className="btn btn-primary btn-sm"
            onClick={() => { setCloudErr(''); setCloudPw(''); setShowCloud(true); }}>
            🔄 從雲端帶入（需密碼）
          </button>
          <span className="label-hint" style={{ alignSelf: 'center' }}>
            或在下方手動選擇／建立本機檔案
          </span>
        </div>
        <div className="card-row">
          <button className="btn btn-secondary btn-sm"
            onClick={async () => {
              try {
                const path = await api.createPeopleTemplate(s.peopleDb);
                if (path) { set({ peopleDb: path }); await api.openFile(path); }
              } catch (e) { window.alert(e.message); }
            }}>建立空白範本</button>
          <button className="btn btn-secondary btn-sm"
            onClick={async () => {
              if (!s.peopleDb) return window.alert('請先選擇或建立人員個資檔');
              await api.openFile(s.peopleDb);
            }}>開啟編輯</button>
          <button className="btn btn-primary btn-sm" onClick={importFromReceipts}>
            📥 從舊領據匯入
          </button>
        </div>
        <div className="label-hint" style={{ marginTop: 12 }}>
          ℹ 每人一行：姓名、身分證、戶籍地址、聯絡電話、戶名、銀行及分行、銀行代碼、帳號
        </div>
      </div>

      {showCloud && (
        <div className="modal-backdrop" onClick={() => !cloudBusy && setShowCloud(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}
            style={{ maxWidth: 440 }}>
            <div className="modal-title">🔒 從雲端帶入人員個資</div>
            <div style={{ marginBottom: 12, fontSize: 13, color: 'var(--text-dim)' }}>
              此檔案含個資，請輸入密碼以從 Google Drive 下載最新版。
              下載後會覆蓋本機快取，並自動填入路徑。
            </div>
            <input type="password" autoFocus
              value={cloudPw}
              disabled={cloudBusy}
              onChange={(e) => setCloudPw(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !cloudBusy) submitCloud(); }}
              placeholder="輸入密碼" />
            {cloudErr && (
              <div style={{ marginTop: 8, color: 'var(--danger)', fontSize: 13 }}>
                ⚠ {cloudErr}
              </div>
            )}
            <div className="modal-footer" style={{ marginTop: 16 }}>
              <button className="btn btn-ghost" disabled={cloudBusy}
                onClick={() => setShowCloud(false)}>取消</button>
              <button className="btn btn-primary" disabled={cloudBusy || !cloudPw}
                onClick={submitCloud}>
                {cloudBusy ? '下載中…' : '確認帶入'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

// ─── Step 5：分區 ───
function ClinicSelectorModal({ s, set, onClose, log }) {
  const [data, setData] = useState(null);
  const [checks, setChecks] = useState({});

  useEffect(() => {
    (async () => {
      try {
        const d = await api.loadClinics(s.regionsDb, s.excel);
        setData(d);
        const initChecks = {};
        d.groups.forEach(([_, clinics]) => {
          clinics.forEach((c) => {
            initChecks[c] = s.selectedClinics ? s.selectedClinics.includes(c) : true;
          });
        });
        setChecks(initChecks);
      } catch (e) {
        window.alert(e.message);
        onClose();
      }
    })();
  }, []);

  if (!data) {
    return (
      <div className="modal-backdrop">
        <div className="modal">載入診所中…</div>
      </div>
    );
  }

  const setAll = (val) => {
    const next = {};
    Object.keys(checks).forEach((k) => next[k] = val);
    setChecks(next);
  };
  const invert = () => {
    const next = {};
    Object.keys(checks).forEach((k) => next[k] = !checks[k]);
    setChecks(next);
  };
  const toggleGroup = (clinics, val) => {
    const next = { ...checks };
    clinics.forEach((c) => next[c] = val);
    setChecks(next);
  };
  const confirm = () => {
    const sel = Object.keys(checks).filter((k) => checks[k]);
    const total = Object.keys(checks).length;
    if (sel.length === 0) {
      if (!window.confirm('未勾選任何診所，將不會產出診所相關文件。仍要套用嗎？')) return;
      set({ selectedClinics: [] });
    } else if (sel.length === total) {
      set({ selectedClinics: null });
    } else {
      set({ selectedClinics: sel });
    }
    onClose();
  };
  const checkedCount = Object.values(checks).filter(Boolean).length;
  const totalCount = Object.keys(checks).length;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 540 }}>
        <div className="modal-title">勾選要產生文件的診所</div>
        <div className="card-row" style={{ marginBottom: 12 }}>
          <button className="btn btn-ghost btn-sm" onClick={() => setAll(true)}>全選</button>
          <button className="btn btn-ghost btn-sm" onClick={() => setAll(false)}>全不選</button>
          <button className="btn btn-ghost btn-sm" onClick={invert}>反選</button>
          <div style={{ flex: 1 }} />
          <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>
            已勾 {checkedCount} / {totalCount}
          </span>
        </div>
        <div className="modal-body">
          {data.groups.map(([region, clinics]) => (
            <div key={region} style={{ marginBottom: 16 }}>
              <div style={{
                background: 'var(--surface-2)', padding: '6px 10px',
                borderRadius: 6, fontSize: 13, fontWeight: 700,
                display: 'flex', alignItems: 'center', gap: 6,
              }}>
                <span style={{ flex: 1 }}>📍 {region} ({clinics.length} 間)</span>
                <button className="btn btn-ghost btn-sm" onClick={() => toggleGroup(clinics, true)}>全選</button>
                <button className="btn btn-ghost btn-sm" onClick={() => toggleGroup(clinics, false)}>全不選</button>
              </div>
              <div style={{ paddingLeft: 16, marginTop: 6 }}>
                {clinics.map((c) => (
                  <label key={c} className="cb" style={{ display: 'flex', padding: '4px 0' }}>
                    <input type="checkbox" checked={!!checks[c]}
                      onChange={(e) => setChecks({ ...checks, [c]: e.target.checked })} />
                    <span>{c}</span>
                  </label>
                ))}
              </div>
            </div>
          ))}
        </div>
        <div className="modal-footer">
          <button className="btn btn-ghost" onClick={onClose}>取消</button>
          <button className="btn btn-success" onClick={confirm}>確認</button>
        </div>
      </div>
    </div>
  );
}

function StepRegions({ s, set, log }) {
  const [showSelector, setShowSelector] = useState(false);
  const filterText = (() => {
    const sel = s.selectedClinics;
    if (sel === null || sel === undefined) return '目前：全部診所（預設）';
    if (sel.length === 0) return '目前：未勾選任何診所（不會產出）';
    const preview = sel.slice(0, 3).join(', ');
    return sel.length > 3
      ? `目前：已選 ${sel.length} 間：${preview} 等`
      : `目前：已選 ${sel.length} 間：${preview}`;
  })();
  const filterColor = s.selectedClinics === null || s.selectedClinics === undefined
    ? 'var(--text-dim)' : (s.selectedClinics.length === 0 ? 'var(--danger)' : 'var(--accent)');

  return (
    <>
      <SectionHead num="05" title="診所分區"
        sub="Excel 三分頁：北投／士林／中山。可進階勾選只產出特定診所" />
      <div className="card">
        <div className="field">
          <label className="label">分區 Excel 路徑</label>
          <FilePicker value={s.regionsDb} onChange={(v) => {
            set({ regionsDb: v, selectedClinics: null });
          }} accept=".xlsx" />
        </div>
        <div className="card-row" style={{ marginBottom: 16 }}>
          <button className="btn btn-secondary btn-sm" onClick={async () => {
            try {
              const path = await api.createRegionsTemplate(s.regionsDb);
              if (path) { set({ regionsDb: path }); await api.openFile(path); }
            } catch (e) { window.alert(e.message); }
          }}>建立空白範本</button>
          <button className="btn btn-secondary btn-sm" onClick={async () => {
            if (!s.regionsDb) return window.alert('請先選擇或建立分區檔');
            await api.openFile(s.regionsDb);
          }}>開啟編輯</button>
        </div>
        <div style={{ borderTop: '1px solid var(--border)', paddingTop: 14 }}>
          <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>
            進階：選擇要產生的診所
          </div>
          <div className="card-row">
            <button className="btn btn-primary btn-sm" onClick={() => setShowSelector(true)}>
              📋 勾選診所
            </button>
            <span style={{ flex: 1, fontSize: 12, color: filterColor }}>{filterText}</span>
            <button className="btn btn-ghost btn-sm" onClick={() => set({ selectedClinics: null })}>重設</button>
          </div>
        </div>
      </div>
      {showSelector && (
        <ClinicSelectorModal s={s} set={set} log={log}
          onClose={() => setShowSelector(false)} />
      )}
    </>
  );
}

// ─── Step 6：輸出 ───
function StepOutput({ s, set }) {
  return (
    <>
      <SectionHead num="06" title="輸出位置 & 寄送設定"
        sub="選擇文件輸出資料夾。Gmail 為選填，可在產生後從底部按鈕寄送" />
      <div className="card">
        <div className="field">
          <label className="label">輸出資料夾</label>
          <FilePicker value={s.output} onChange={(v) => set({ output: v })}
            kind="folder" />
        </div>
      </div>
      <div className="card">
        <div className="field">
          <label className="label">🔒 PDF 驗證主密碼（選填）</label>
          <div className="label-hint">
            合併後的 PDF 預設用「該人身分證字號」加密；填了主密碼後，你也能用此密碼開啟所有 PDF（驗證用）。留空則只有身分證能開。身分證空白者不加密，並會在 receipt 資料夾產生「未加密清單.txt」。
          </div>
          <input type="password" value={s.masterPassword || ''}
            onChange={(e) => set({ masterPassword: e.target.value })}
            placeholder="留空 = 不設主密碼" />
        </div>
      </div>
      <div className="card">
        <div className="field">
          <label className="label">📧 Gmail 寄送設定（選填）</label>
          <div className="label-hint">
            App Password 會在按下底部「📧 預覽並寄送 Gmail」時輸入
          </div>
          <input type="email" value={s.senderEmail || ''}
            onChange={(e) => set({ senderEmail: e.target.value })}
            placeholder="your-name@gmail.com" />
        </div>
      </div>
      <div style={{ textAlign: 'center', marginTop: 24, fontSize: 13,
        fontWeight: 700, color: 'var(--accent)' }}>
        ✨ 設定完成！按右下角「產生文件」開始批次處理
      </div>
    </>
  );
}

// ─── Main App ───
function App() {
  const [step, setStep] = useState(0);
  const [direction, setDirection] = useState('forward');
  const [toasts, setToasts] = useState([]);
  const [generating, setGenerating] = useState(false);
  const [progress, setProgress] = useState({ pct: 0, status: '', file: '', kind: '' });
  const [logLines, setLogLines] = useState([]);
  const [logExpanded, setLogExpanded] = useState(false);

  const [s, setS] = useState({
    excel: '', execExcel: '',
    year: new Date().getFullYear() - 1911,
    month: new Date().getMonth() + 1,
    region: '全部',
    minByRegion: { '北投': '0', '士林': '0', '中山': '0' },
    gen_doctor_presc_detail: true, gen_doctor_exec_detail: true,
    gen_doctor_receipt: true, gen_doctor_summary: true,
    gen_health_detail: true, gen_health_receipt: true, gen_health_summary: true,
    gen_treatment_detail: true, gen_treatment_receipt: true, gen_treatment_summary: true,
    peopleDb: '', regionsDb: '', output: '',
    selectedClinics: null,
    senderEmail: '',
    masterPassword: '',
  });

  // 初始化：載入預設值
  useEffect(() => {
    (async () => {
      try {
        const init = await api.getInitialState();
        setS((prev) => ({ ...prev, ...init }));
      } catch (e) {
        console.warn('init failed', e);
      }
    })();

    // pywebview event listeners
    window.addEventListener('progress-update', (e) => {
      setProgress(e.detail);
    });
    window.addEventListener('log-line', (e) => {
      setLogLines((prev) => [...prev, e.detail]);
    });
  }, []);

  const set = (patch) => setS((prev) => ({ ...prev, ...patch }));
  const log = (line) => setLogLines((prev) => [...prev, line]);
  const toast = (msg, kind) => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, msg, kind }]);
  };

  // ─── 驗證 ───
  const validate = async (idx) => {
    const v = STEPS[idx].validate;
    if (v === 'validateImport') {
      if (!s.excel) { toast('請先選擇開立處方 Excel', 'danger'); return false; }
      const exists = await api.fileExists(s.excel);
      if (!exists) { toast('找不到開立處方 Excel', 'danger'); return false; }
      if (s.execExcel) {
        const exists2 = await api.fileExists(s.execExcel);
        if (!exists2) { toast('找不到執行處方 Excel', 'danger'); return false; }
      }
      return true;
    }
    if (v === 'validateSettings') {
      if (!Number.isInteger(+s.year) || !Number.isInteger(+s.month)) {
        toast('年月必須是數字', 'danger'); return false;
      }
      for (const [r, val] of Object.entries(s.minByRegion)) {
        const n = parseInt(val || '0');
        if (Number.isNaN(n) || n < 0) { toast(`${r} 份數錯誤`, 'danger'); return false; }
        if (n % 6 !== 0) { toast(`${r} 份數需為 6 的倍數`, 'danger'); return false; }
      }
      return true;
    }
    if (v === 'validateOutputs') {
      const any = ['gen_doctor_presc_detail','gen_doctor_exec_detail','gen_doctor_receipt',
        'gen_doctor_summary','gen_health_detail','gen_health_receipt','gen_health_summary',
        'gen_treatment_detail','gen_treatment_receipt','gen_treatment_summary'].some((k) => s[k]);
      if (!any) { toast('10 項都未勾選，至少要勾一項', 'danger'); return false; }
      return true;
    }
    if (v === 'validateOutput') {
      if (!s.output) { toast('請選擇輸出資料夾', 'danger'); return false; }
      return true;
    }
    return true;
  };

  const go = async (idx) => {
    if (idx === step) return;
    if (idx > step) {
      for (let i = step; i < idx; i++) {
        if (!await validate(i)) return;
      }
    }
    setDirection(idx > step ? 'forward' : 'back');
    setStep(idx);
  };

  const onPrev = () => { if (step > 0) { setDirection('back'); setStep(step - 1); } };
  const onNext = async () => {
    if (!await validate(step)) return;
    if (step < STEPS.length - 1) { setDirection('forward'); setStep(step + 1); }
  };

  // ─── 產生文件 ───
  const onGenerate = async () => {
    if (!await validate(STEPS.length - 1)) return;
    setLogLines([]);
    setProgress({ pct: 0, status: '準備中…', file: '', kind: '' });
    setGenerating(true);
    try {
      await api.generateDocs(s);
      setProgress({ pct: 1, status: '✓ 全部完成', file: '', kind: 'success' });
      toast('✓ 文件已產生！', 'success');
    } catch (e) {
      setProgress((p) => ({ ...p, status: '發生錯誤', kind: 'danger' }));
      toast('產生失敗: ' + e.message, 'danger');
    } finally {
      setGenerating(false);
    }
  };

  // ─── 寄送 Gmail ───
  const onSendEmail = async () => {
    if (!s.senderEmail) {
      toast('請在第 6 步填入寄件 Gmail', 'danger');
      return;
    }
    if (!s.senderEmail.includes('@')) {
      toast('Email 格式錯誤', 'danger');
      return;
    }
    if (!s.output) {
      toast('請先指定輸出資料夾', 'danger');
      return;
    }
    try {
      await api.openEmailPreview(s);
    } catch (e) {
      toast('開啟寄送預覽失敗: ' + e.message, 'danger');
    }
  };

  // ─── Render ───
  const stepProps = { s, set, log };
  const isLast = step === STEPS.length - 1;

  return (
    <>
      <div className="app-header">
        <div>
          <span className="app-title">⚡ 核銷文件產生器</span>
          <span className="app-version">v39</span>
        </div>
        <div className="app-org">台北市醫師公會 ◆ 健康台灣深耕計畫</div>
      </div>

      <StepperHeader current={step} onClick={go} />

      {generating && (
        <div className="progress-wrap">
          <div className="progress-row">
            <span className={`progress-status ${progress.kind || ''}`}>
              {progress.status || '準備中…'}
            </span>
            <span className="progress-pct">{Math.round((progress.pct || 0) * 100)}%</span>
          </div>
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${(progress.pct || 0) * 100}%` }} />
          </div>
          {progress.file && <div className="progress-file">{progress.file}</div>}
          <div style={{ maxWidth: 920, margin: '4px auto 0' }}>
            <button className="log-toggle" onClick={() => setLogExpanded(!logExpanded)}>
              {logExpanded ? '隱藏詳細記錄 ▲' : '顯示詳細記錄 ▼'}
            </button>
            {logExpanded && (
              <div className="log-box">
                {logLines.join('\n')}
              </div>
            )}
          </div>
        </div>
      )}

      <div className="app-body">
        <div className={`step-page ${direction === 'back' ? 'back' : ''}`} key={step}>
          {step === 0 && <StepImport {...stepProps} />}
          {step === 1 && <StepSettings {...stepProps} />}
          {step === 2 && <StepOutputs {...stepProps} />}
          {step === 3 && <StepPeople {...stepProps} />}
          {step === 4 && <StepRegions {...stepProps} />}
          {step === 5 && <StepOutput {...stepProps} />}
        </div>
      </div>

      <div className="sticky-bar">
        <div className="sticky-row">
          <button className="btn btn-secondary" onClick={onPrev} disabled={step === 0 || generating}>
            ← 上一步
          </button>
          <span className="sticky-hint">
            步驟 {step + 1} / {STEPS.length} · {STEPS[step].label}
          </span>
          {!isLast && (
            <button className="btn btn-primary" onClick={onNext} disabled={generating}>
              下一步 →
            </button>
          )}
          {isLast && (
            <button className="btn btn-success btn-lg" onClick={onGenerate} disabled={generating}>
              {generating ? '產生中…' : '✨ 產生文件'}
            </button>
          )}
          <button className="btn btn-secondary" onClick={onSendEmail} disabled={generating}>
            📧 預覽並寄送 Gmail
          </button>
        </div>
      </div>

      {toasts.map((t) => (
        <Toast key={t.id} {...t} onClose={() =>
          setToasts((prev) => prev.filter((x) => x.id !== t.id))} />
      ))}
    </>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
