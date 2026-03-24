import { useState, useEffect, useRef, useCallback } from "react";
import * as mammoth from "mammoth";

// ── 固定團隊成員 ──────────────────────────────
const TEAM = ["黃琴茹","蔡蕙芳","吳承儒","張鈺微","吳亞璇","許雅淇","戴豐逸","陳佩研"];
const AVATAR_COLORS = ["#4f8cff","#00e5c3","#ff9f43","#ff5b79","#a78bfa","#34d399","#f97316","#06b6d4"];
const STORAGE_KEY   = "meetbot-tasks-v1";
const REMINDER_KEY  = "meetbot-reminders-v1";
const BACKEND_URL   = "https://meetbot-backend.onrender.com";

// ── 示範任務 ──────────────────────────────────
const DEMO_TASKS = [
  { id:1, title:"彙整各診所回報的處方數量，傳給主任", assignee:"蔡蕙芳", deadline:"2026-03-28", meeting:"週會 3/21", done:false, urgent:true,  progressNote:"", progressNoteTime:"" },
  { id:2, title:"確認 Q2 採購預算核准文件",           assignee:"戴豐逸", deadline:"2026-03-28", meeting:"週會 3/21", done:false, urgent:false, progressNote:"", progressNoteTime:"" },
  { id:3, title:"更新居民追蹤名單並上傳系統",         assignee:"吳承儒", deadline:"2026-03-31", meeting:"週會 3/21", done:false, urgent:false, progressNote:"", progressNoteTime:"" },
  { id:4, title:"準備下週社區衛教活動講義",           assignee:"張鈺微", deadline:"2026-04-01", meeting:"週會 3/21", done:false, urgent:false, progressNote:"", progressNoteTime:"" },
  { id:5, title:"聯絡信義診所確認藥品庫存",           assignee:"黃琴茹", deadline:"2026-03-20", meeting:"週會 3/14", done:true,  urgent:false, progressNote:"", progressNoteTime:"" },
  { id:6, title:"整理上季健康檢查統計報告",           assignee:"吳亞璇", deadline:"2026-03-22", meeting:"月度檢討 3/7", done:true, urgent:false, progressNote:"", progressNoteTime:"" },
];

// ── 提醒預設值 ────────────────────────────────
const DEFAULT_REMINDERS = {
  dayBefore:    { on: true,  days: 1,  hour: 9  },
  hourBefore:   { on: true,  hours: 2             },
  weeklyReport: { on: false, weekday: 5, hour: 16 },
  overdueAlert: { on: true                         },
};

// ── 工具函式 ──────────────────────────────────
const today    = () => new Date().toISOString().slice(0,10);
const daysLeft = (d) => Math.ceil((new Date(d) - new Date(today())) / 86400000);
const memberColor = (n) => AVATAR_COLORS[TEAM.indexOf(n) % AVATAR_COLORS.length] || "#888";
const pad2 = (n) => String(n).padStart(2,"0");
const nowTW = () => new Date().toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hour12: false }).replace(/\//g,"-");


// ── Avatar ────────────────────────────────────
function Avatar({ name, size = 32 }) {
  return (
    <div style={{
      width: size, height: size, borderRadius: "50%",
      background: memberColor(name),
      display: "flex", alignItems: "center", justifyContent: "center",
      fontSize: size * 0.42, fontWeight: 700, color: "#fff", flexShrink: 0,
      fontFamily: "'Noto Sans TC', sans-serif"
    }}>{name[0]}</div>
  );
}

// ── DeadlineBadge ─────────────────────────────
function DeadlineBadge({ deadline, done }) {
  if (done) return <span style={bdg("#00e5c3","rgba(0,229,195,0.12)")}>完成</span>;
  const d = daysLeft(deadline);
  if (d < 0)   return <span style={bdg("#ff5b79","rgba(255,91,121,0.12)")}>逾期 {Math.abs(d)} 天</span>;
  if (d === 0) return <span style={bdg("#ff5b79","rgba(255,91,121,0.12)")}>今天截止</span>;
  if (d <= 2)  return <span style={bdg("#ff9f43","rgba(255,159,67,0.12)")}>剩 {d} 天</span>;
  return <span style={bdg("#6b7494","rgba(107,116,148,0.12)")}>{deadline.slice(5).replace("-","/")} 截止</span>;
}
const bdg = (c,bg) => ({ fontSize:38, padding:"4px 14px", borderRadius:20, background:bg, color:c, fontWeight:600, whiteSpace:"nowrap" });

// ── Toggle ────────────────────────────────────
function Toggle({ on, onChange }) {
  return (
    <div onClick={onChange} style={{
      width:48, height:28, borderRadius:14, cursor:"pointer", position:"relative", flexShrink:0,
      background: on ? "var(--accent)" : "var(--border)", transition:"background 0.2s"
    }}>
      <div style={{
        position:"absolute", width:22, height:22, borderRadius:"50%", background:"#fff",
        top:3, left: on ? 23 : 3, transition:"left 0.2s", boxShadow:"0 1px 4px rgba(0,0,0,0.3)"
      }}/>
    </div>
  );
}

// ── Stepper ───────────────────────────────────
function Stepper({ value, min, max, onChange, suffix="" }) {
  return (
    <div style={{ display:"flex", alignItems:"center", gap:10 }}>
      <div onClick={() => onChange(Math.max(min, value-1))} style={{
        width:34, height:34, borderRadius:8, background:"var(--card)", border:"1px solid var(--border)",
        display:"flex", alignItems:"center", justifyContent:"center", cursor:"pointer", fontSize:38, userSelect:"none"
      }}>−</div>
      <span style={{ fontSize:38, fontWeight:700, minWidth:32, textAlign:"center", fontFamily:"'DM Mono',monospace" }}>{value}</span>
      <div onClick={() => onChange(Math.min(max, value+1))} style={{
        width:34, height:34, borderRadius:8, background:"var(--card)", border:"1px solid var(--border)",
        display:"flex", alignItems:"center", justifyContent:"center", cursor:"pointer", fontSize:38, userSelect:"none"
      }}>+</div>
      {suffix && <span style={{ fontSize:34, color:"var(--muted)" }}>{suffix}</span>}
    </div>
  );
}

// ── 進度備註 Modal ────────────────────────────
function NoteModal({ task, onSave, onClose }) {
  const [note, setNote] = useState(task.progressNote || "");
  return (
    <div style={{
      position:"fixed", inset:0, background:"rgba(0,0,0,0.75)", zIndex:200,
      display:"flex", alignItems:"center", justifyContent:"center", padding:"20px"
    }}>
      <div style={{
        background:"var(--card)", border:"1px solid var(--border)", borderRadius:16,
        padding:"24px", width:"100%", maxWidth:520, display:"flex", flexDirection:"column", gap:16
      }}>
        <div style={{ fontSize:38, fontWeight:700 }}>📝 工作進度備註</div>
        <div style={{
          background:"var(--surf)", borderRadius:10, padding:"12px 14px",
          fontSize:34, color:"var(--muted)", lineHeight:1.6
        }}>
          {task.title}
        </div>
        <textarea
          autoFocus
          value={note}
          onChange={e => setNote(e.target.value)}
          placeholder="請輸入目前工作進度備註..."
          style={{
            background:"var(--surf)", border:"1px solid var(--accent)", borderRadius:10,
            color:"var(--text)", fontSize:38, lineHeight:1.7, padding:"14px",
            resize:"vertical", minHeight:120, fontFamily:"'Noto Sans TC',sans-serif",
            outline:"none"
          }}
        />
        {task.progressNoteTime && (
          <div style={{ fontSize:34, color:"var(--muted)" }}>
            上次備註時間：{task.progressNoteTime}
          </div>
        )}
        <div style={{ display:"flex", gap:10 }}>
          <button onClick={onClose} style={{
            flex:1, padding:"13px", borderRadius:10, border:"1px solid var(--border)",
            background:"var(--surf)", color:"var(--muted)", fontSize:34, fontWeight:600,
            cursor:"pointer", fontFamily:"inherit"
          }}>取消</button>
          <button onClick={() => onSave(note)} style={{
            flex:2, padding:"13px", borderRadius:10, border:"none",
            background:"linear-gradient(135deg,var(--accent),#00b89c)", color:"#fff",
            fontSize:34, fontWeight:700, cursor:"pointer", fontFamily:"inherit"
          }}>儲存備註</button>
        </div>
      </div>
    </div>
  );
}

// ── Word 匯出 ─────────────────────────────────
function exportToWord(tasks) {
  const nowStr = nowTW();
  const dateStr = new Date().toISOString().slice(0,10);
  const total = tasks.length;
  const done  = tasks.filter(t => t.done).length;
  const pct   = total ? Math.round(done / total * 100) : 0;

  let html = `<!DOCTYPE html><html><head>
<meta charset="utf-8">
<style>
  body { font-family: "Microsoft JhengHei","微軟正黑體",sans-serif; font-size: 12pt; margin:40px; }
  h1   { font-size:20pt; color:#1a1a2e; border-bottom:3px solid #4f8cff; padding-bottom:8px; margin-bottom:16px; }
  h2   { font-size:15pt; color:#4f8cff; margin-top:28px; margin-bottom:10px; }
  .summary { background:#f0f4ff; padding:14px 18px; border-radius:6px; margin-bottom:24px; font-size:13pt; line-height:2; }
  table { width:100%; border-collapse:collapse; margin-bottom:24px; font-size:11pt; }
  th    { background:#4f8cff; color:white; padding:9px 12px; text-align:left; font-size:12pt; }
  td    { padding:8px 12px; border-bottom:1px solid #ddd; vertical-align:top; line-height:1.6; }
  tr:nth-child(even) { background:#f9f9f9; }
  .done    { color:#00b89c; font-weight:600; }
  .overdue { color:#ff5b79; font-weight:600; }
  .urgent  { color:#ff9f43; font-weight:600; }
  .pending { color:#6b7494; }
  .note    { color:#444; }
  .ntime   { color:#999; font-size:10pt; }
  .footer  { margin-top:32px; font-size:10pt; color:#999; border-top:1px solid #ddd; padding-top:10px; }
  .no-task { color:#aaa; font-style:italic; }
</style>
</head><body>
<h1>MeetBot 工作進度彙整報告</h1>
<div class="summary">
  <strong>匯出時間：</strong>${nowStr}<br>
  <strong>整體完成率：</strong>${pct}%（已完成 ${done} / 共 ${total} 項）
</div>`;

  TEAM.forEach(name => {
    const myTasks = tasks.filter(t => t.assignee === name);
    const myDone  = myTasks.filter(t => t.done).length;
    const myPct   = myTasks.length ? Math.round(myDone / myTasks.length * 100) : 0;
    html += `<h2>👤 ${name}　${myDone}/${myTasks.length} 完成・${myPct}%</h2>`;

    if (myTasks.length === 0) {
      html += `<p class="no-task">（尚無指派任務）</p>`;
      return;
    }

    html += `<table>
<tr><th>#</th><th>任務</th><th>截止日</th><th>狀態</th><th>進度備註</th><th>備註時間</th></tr>`;
    myTasks.forEach((t, i) => {
      const d = daysLeft(t.deadline);
      let cls, txt;
      if (t.done)       { cls="done";    txt="✓ 已完成"; }
      else if (d < 0)   { cls="overdue"; txt=`逾期 ${Math.abs(d)} 天`; }
      else if (d === 0) { cls="overdue"; txt="今天截止"; }
      else if (d <= 2)  { cls="urgent";  txt=`剩 ${d} 天`; }
      else              { cls="pending"; txt=t.deadline; }
      html += `<tr>
<td>${i+1}</td>
<td>${t.title}</td>
<td>${t.deadline}</td>
<td class="${cls}">${txt}</td>
<td class="note">${t.progressNote || ""}</td>
<td class="ntime">${t.progressNoteTime || ""}</td>
</tr>`;
    });
    html += `</table>`;
  });

  html += `<div class="footer">此報告由 MeetBot 系統自動生成 &nbsp;|&nbsp; 匯出時間：${nowStr}</div>
</body></html>`;

  const blob = new Blob(["\uFEFF" + html], { type: "application/msword;charset=utf-8" });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href     = url;
  a.download = `工作進度彙整_${dateStr}.doc`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ── 計算下次提醒時間 ──────────────────────────
function calcNextReminder(tasks, reminders) {
  const pending = tasks.filter(t => !t.done);
  const hits = [];
  const now = new Date();
  pending.forEach(t => {
    const dl = new Date(t.deadline + "T23:59:00");
    if (reminders.hourBefore.on) {
      const fireAt = new Date(dl.getTime() - reminders.hourBefore.hours * 3600000);
      if (fireAt > now) hits.push({ task: t, at: fireAt, type: `截止前 ${reminders.hourBefore.hours} 小時` });
    }
    if (reminders.dayBefore.on) {
      const fireAt = new Date(dl);
      fireAt.setDate(fireAt.getDate() - reminders.dayBefore.days);
      fireAt.setHours(reminders.dayBefore.hour, 0, 0, 0);
      if (fireAt > now) hits.push({ task: t, at: fireAt, type: `截止前 ${reminders.dayBefore.days} 天` });
    }
  });
  hits.sort((a,b) => a.at - b.at);
  return hits.slice(0,5);
}

// ── AI 解析 ───────────────────────────────────
async function parseWithAI(text) {
  const today_str = new Date().toISOString().slice(0,10);
  const res = await fetch(`${BACKEND_URL}/parse-meeting`, {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({ text: `你是會議記錄分析助理。從以下會議紀錄中，找出所有「任務/行動項目」。
每個任務需包含：負責人、任務描述、截止日期。今天是 ${today_str}。
若日期只說「本週五」請換算成實際日期。若無法確定截止日期，設定為 7 天後。
負責人請從以下名單選最接近的：${TEAM.join("、")}。若無法對應，填「待指派」。
請只回傳 JSON 陣列，格式如下，不要有任何說明文字：
[{"title":"任務描述","assignee":"負責人","deadline":"YYYY-MM-DD"}]
會議紀錄：\n${text}` })
  });
  const data = await res.json();
  return data.items || [];
}

// ── Storage ───────────────────────────────────
async function loadTasks() {
  try { const r = await window.storage.get(STORAGE_KEY,true); return JSON.parse(r.value); }
  catch { try { await window.storage.set(STORAGE_KEY,JSON.stringify(DEMO_TASKS),true); } catch {} return DEMO_TASKS; }
}
async function saveTasks(tasks) {
  try { await window.storage.set(STORAGE_KEY,JSON.stringify(tasks),true); } catch {}
}
async function loadReminders() {
  try { const r = await window.storage.get(REMINDER_KEY,true); return { ...DEFAULT_REMINDERS, ...JSON.parse(r.value) }; }
  catch { return DEFAULT_REMINDERS; }
}
async function saveReminders(r) {
  try { await window.storage.set(REMINDER_KEY,JSON.stringify(r),true); } catch {}
}

// ── 呼叫後端發送 LINE 提醒 ────────────────────
async function checkAndNotify(tasks, reminders) {
  try {
    const res = await fetch(`${BACKEND_URL}/check-reminders`, {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({ tasks, reminders })
    });
    const data = await res.json();
    return data.sent || 0;
  } catch { return 0; }
}

// ── 主元件 ────────────────────────────────────
export default function MeetBot() {
  const [tasks,        setTasks]        = useState([]);
  const [reminders,    setReminders]    = useState(DEFAULT_REMINDERS);
  const [loading,      setLoading]      = useState(true);
  const [syncing,      setSyncing]      = useState(false);
  const [lastSync,     setLastSync]     = useState(null);
  const [lastNotify,   setLastNotify]   = useState(null);
  const [tab,          setTab]          = useState("dashboard");
  const [filter,       setFilter]       = useState("all");
  const [memberFilter, setMemberFilter] = useState("all");
  const [parsing,      setParsing]      = useState(false);
  const [parseResult,  setParseResult]  = useState(null);
  const [docName,      setDocName]      = useState("");
  const [manualForm,   setManualForm]   = useState({ title:"", assignee:TEAM[0], deadline:"", meeting:"" });
  const [toast,        setToast]        = useState(null);
  const [savedPulse,   setSavedPulse]   = useState(false);
  const [editingTask,  setEditingTask]  = useState(null); // 備註 modal

  const [isWide, setIsWide] = useState(false);

  const fileRef       = useRef();
  const rootRef       = useRef();
  const isFirstRender = useRef(true);
  const isSaving      = useRef(false);
  const tasksRef      = useRef([]);
  const remindersRef  = useRef(DEFAULT_REMINDERS);

  const showToast = (msg, color="#4f8cff") => {
    setToast({ msg, color });
    setTimeout(() => setToast(null), 2800);
  };

  // ── 寬度偵測（ResizeObserver，在 iframe/嵌入環境也可靠）──
  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    const ro = new ResizeObserver(entries => {
      for (const e of entries) setIsWide(e.contentRect.width >= 900);
    });
    ro.observe(el);
    // 立即讀一次，避免等第一次 resize 事件
    setIsWide(el.getBoundingClientRect().width >= 900);
    return () => ro.disconnect();
  }, [loading]); // loading 變 false 後 rootRef 才指向主 div，需要重跑

  // ── 初始載入 ──
  const fetchAll = useCallback(async (quiet=false) => {
    if (!quiet) setLoading(true); else setSyncing(true);
    const [t, r] = await Promise.all([loadTasks(), loadReminders()]);
    setTasks(t); setReminders(r);
    tasksRef.current = t; remindersRef.current = r;
    setLastSync(new Date());
    if (!quiet) setLoading(false); else setSyncing(false);
  }, []);

  useEffect(() => {
    fetchAll(false);
    const poll = setInterval(() => { if (!isSaving.current) fetchAll(true); }, 15000);
    const reminderCheck = setInterval(async () => {
      const sent = await checkAndNotify(tasksRef.current, remindersRef.current);
      if (sent > 0) { setLastNotify(new Date()); showToast(`已發送 ${sent} 則 LINE 提醒`,"#00e5c3"); }
    }, 3600000);
    return () => { clearInterval(poll); clearInterval(reminderCheck); };
  }, [fetchAll]);

  // ── 任務自動存 ──
  useEffect(() => {
    if (isFirstRender.current) { isFirstRender.current = false; return; }
    if (loading) return;
    tasksRef.current = tasks;
    isSaving.current = true;
    saveTasks(tasks).finally(() => { isSaving.current = false; setLastSync(new Date()); });
  }, [tasks, loading]);

  // ── 提醒設定存檔 ──
  const saveReminderSettings = async (newR) => {
    setReminders(newR); remindersRef.current = newR;
    await saveReminders(newR);
    setSavedPulse(true); setTimeout(() => setSavedPulse(false), 1500);
  };
  const updateReminder = (key, patch) => saveReminderSettings({ ...reminders, [key]: { ...reminders[key], ...patch } });

  // ── 上傳 docx ──
  const handleFile = async (e) => {
    const file = e.target.files[0]; if (!file) return;
    setDocName(file.name); setParsing(true); setParseResult(null);
    try {
      const ab = await file.arrayBuffer();
      const { value: text } = await mammoth.extractRawText({ arrayBuffer: ab });
      setParseResult(await parseWithAI(text));
    } catch { showToast("解析失敗，請再試一次","#ff5b79"); }
    setParsing(false);
  };

  const confirmTasks = () => {
    const meeting = docName.replace(/\.docx$/i,"") || "匯入會議";
    const newTasks = parseResult.map((t,i) => ({
      id: Date.now()+i, title:t.title, assignee:t.assignee,
      deadline:t.deadline, meeting, done:false,
      urgent: daysLeft(t.deadline)<=1,
      progressNote: "", progressNoteTime: "",
    }));
    setTasks(prev => [...newTasks,...prev]);
    setParseResult(null); setDocName(""); setTab("dashboard");
    showToast(`已同步 ${newTasks.length} 項任務給全團隊`);
  };

  const addManualTask = () => {
    if (!manualForm.title.trim() || !manualForm.deadline) {
      showToast("請填寫任務名稱與截止日期","#ff5b79"); return;
    }
    const newTask = {
      id: Date.now(), title: manualForm.title.trim(),
      assignee: manualForm.assignee, deadline: manualForm.deadline,
      meeting: manualForm.meeting.trim() || "手動新增",
      done: false, urgent: daysLeft(manualForm.deadline) <= 1,
      progressNote: "", progressNoteTime: "",
    };
    setTasks(prev => [newTask, ...prev]);
    setManualForm({ title:"", assignee:TEAM[0], deadline:"", meeting:"" });
    showToast("已新增 1 項任務");
  };

  const toggleDone = (id) => {
    setTasks(prev => {
      const updated = prev.map(t => {
        if (t.id !== id) return t;
        const nowDone = !t.done;
        // 剛變成完成時才發通知
        if (nowDone) {
          fetch(`${BACKEND_URL}/notify-task-done`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ task: { ...t, done: true } })
          }).catch(() => {});
        }
        return { ...t, done: nowDone };
      });
      return updated;
    });
  };

  // ── 儲存備註 ──
  const saveNote = (note) => {
    if (!editingTask) return;
    const time = nowTW();
    setTasks(prev => prev.map(t =>
      t.id === editingTask.id ? { ...t, progressNote: note, progressNoteTime: note ? time : "" } : t
    ));
    setEditingTask(null);
    showToast("備註已儲存","#00e5c3");
  };

  // ── 衍生統計 ──
  const filtered = tasks.filter(t => {
    if (memberFilter!=="all" && t.assignee!==memberFilter) return false;
    if (filter==="pending") return !t.done;
    if (filter==="urgent")  return !t.done && daysLeft(t.deadline)<=2;
    if (filter==="done")    return t.done;
    return true;
  });
  const pendingCount = tasks.filter(t=>!t.done).length;
  const doneCount    = tasks.filter(t=>t.done).length;
  const urgentCount  = tasks.filter(t=>!t.done && daysLeft(t.deadline)<=2).length;
  const pct = tasks.length ? Math.round(doneCount/tasks.length*100) : 0;
  const memberStats = TEAM.map(name => {
    const mine = tasks.filter(t=>t.assignee===name);
    const done = mine.filter(t=>t.done).length;
    return { name, total:mine.length, done, pct: mine.length ? Math.round(done/mine.length*100):0 };
  }).filter(m=>m.total>0);

  const nextReminders = calcNextReminder(tasks, reminders);
  const syncLabel = lastSync ? `${pad2(lastSync.getHours())}:${pad2(lastSync.getMinutes())} 同步` : "同步中...";
  const WEEKDAYS = ["日","一","二","三","四","五","六"];

  // ── Loading ──
  if (loading) return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;700&display=swap');
        *{box-sizing:border-box;margin:0;padding:0}
        @keyframes slide{0%{transform:translateX(-200%)}100%{transform:translateX(400%)}}
      `}</style>
      <div style={{ fontFamily:"'Noto Sans TC',sans-serif", background:"#080b12", color:"#e8eaf2", minHeight:"100vh", display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:18 }}>
        <div style={{ fontSize:72 }}>📋</div>
        <div style={{ fontWeight:700, fontSize:38 }}>載入共用清單中...</div>
        <div style={{ width:180, height:4, background:"#232840", borderRadius:2, overflow:"hidden" }}>
          <div style={{ height:"100%", background:"linear-gradient(90deg,#4f8cff,#00e5c3)", animation:"slide 1.2s infinite", width:"50%" }}/>
        </div>
        <div style={{ fontSize:34, color:"#5a6285" }}>所有成員共用同一份資料</div>
      </div>
    </>
  );

  // ── CSS 變數、動畫與響應式佈局 ──
  const styleBlock = `
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@300;400;500;700;900&family=DM+Mono:wght@400;500&display=swap');
    *{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
    html,body{background:#080b12;height:100%}
    :root{
      --bg:#080b12;--surf:#10141e;--card:#181d2a;--border:#232840;
      --accent:#4f8cff;--green:#00e5c3;--orange:#ff9f43;--red:#ff5b79;
      --text:#e8eaf2;--muted:#6b7494;
    }
    @keyframes fadeUp{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
    @keyframes slide{0%{transform:translateX(-100%)}100%{transform:translateX(350%)}}
    @keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}
    @keyframes savedPop{0%{transform:scale(1)}50%{transform:scale(1.08)}100%{transform:scale(1)}}
    ::-webkit-scrollbar{width:5px}::-webkit-scrollbar-thumb{background:#232840;border-radius:3px}

    /* ── 響應式佈局 ── */
    .mb-root{ max-width:560px; margin:0 auto; min-height:100vh; position:relative; }
    .mb-main{ display:block; }
    .mb-sidebar{ display:none; }
    .mb-tabs{ display:flex; overflow-x:auto; scrollbar-width:none; background:var(--surf); border-bottom:1px solid var(--border); }
    .mb-tabs::-webkit-scrollbar{ display:none; }
    .mb-content-pad{ padding:14px 14px 80px; }
    .mb-task-grid{ display:block; }
    .mb-member-grid{ display:block; }
    .mb-member-card{ margin-bottom:10px; }

    .mb-wide{ max-width:none !important; margin:0 !important; display:flex !important; flex-direction:column !important; }
    .mb-wide .mb-topbar-inner{ padding:14px 32px !important; }
    .mb-wide .mb-topbar-logo{ width:44px !important; height:44px !important; font-size:22px !important; }
    .mb-wide .mb-topbar-title{ font-size:26px !important; }
    .mb-wide .mb-topbar-sub{ display:block !important; }
    .mb-wide .mb-main{ display:flex !important; flex:1; min-height:0; }
    .mb-wide .mb-sidebar{
      display:flex !important; flex-direction:column; gap:6px;
      width:230px; min-width:230px; flex-shrink:0;
      background:var(--surf); border-right:1px solid var(--border);
      padding:24px 14px; position:sticky; top:72px;
      height:calc(100vh - 72px); overflow-y:auto;
    }
    .mb-wide .mb-tabs{ display:none !important; }
    .mb-wide .mb-content-area{ flex:1; overflow-y:auto; }
    .mb-wide .mb-content-pad{ padding:24px 32px 40px !important; }
    .mb-wide .mb-task-grid{ display:grid !important; grid-template-columns:1fr 1fr; gap:12px; }
    .mb-wide .mb-member-grid{ display:grid !important; grid-template-columns:1fr 1fr; gap:12px; }
    .mb-wide .mb-member-card{ margin-bottom:0 !important; }
  `;

  // ── 任務卡片 ──
  const TaskCard = ({ t }) => (
    <div style={{
      background: t.done ? "rgba(24,29,42,0.5)" : "var(--card)",
      border: `1px solid ${t.urgent&&!t.done ? "rgba(255,91,121,0.35)" : "var(--border)"}`,
      borderRadius:14, padding:"15px 16px", marginBottom:10,
      display:"flex", flexDirection:"column", gap:10,
      opacity: t.done ? 0.6 : 1, transition:"all 0.2s",
    }}>
      {/* 上排：勾選 + 內容 */}
      <div style={{ display:"flex", gap:14, alignItems:"flex-start" }}>
        {/* 勾選圓圈 */}
        <div
          onClick={() => toggleDone(t.id)}
          style={{
            width:26, height:26, borderRadius:"50%", flexShrink:0, marginTop:2, cursor:"pointer",
            border:`2.5px solid ${t.done?"var(--green)":t.urgent?"var(--red)":"var(--border)"}`,
            background:t.done?"var(--green)":"transparent",
            display:"flex", alignItems:"center", justifyContent:"center",
            fontSize:34, color:"#fff", transition:"all 0.2s"
          }}>{t.done?"✓":""}</div>

        {/* 內容 */}
        <div style={{ flex:1, minWidth:0 }}>
          <div style={{
            fontSize:38, fontWeight:500, lineHeight:1.5, marginBottom:8,
            textDecoration:t.done?"line-through":"none",
            color:t.done?"var(--muted)":"var(--text)"
          }}>{t.title}</div>
          <div style={{ display:"flex", gap:8, flexWrap:"wrap", alignItems:"center", marginBottom: t.progressNote ? 8 : 0 }}>
            <div style={{ display:"flex", alignItems:"center", gap:5 }}>
              <Avatar name={t.assignee} size={22}/>
              <span style={{ fontSize:34, color:"var(--muted)" }}>{t.assignee}</span>
            </div>
            <DeadlineBadge deadline={t.deadline} done={t.done}/>
            {t.urgent&&!t.done && <span style={bdg("var(--red)","rgba(255,91,121,0.1)")}>緊急</span>}
          </div>
          {t.progressNote && (
            <div style={{ background:"rgba(79,140,255,0.07)", border:"1px solid rgba(79,140,255,0.2)", borderRadius:8, padding:"8px 12px", marginTop:4 }}>
              <div style={{ fontSize:34, color:"var(--accent)", fontWeight:600, marginBottom:3 }}>📝 進度備註</div>
              <div style={{ fontSize:34, color:"var(--text)", lineHeight:1.6 }}>{t.progressNote}</div>
              {t.progressNoteTime && <div style={{ fontSize:30, color:"var(--muted)", marginTop:4 }}>{t.progressNoteTime}</div>}
            </div>
          )}
          <div style={{ fontSize:34, color:"var(--muted)", marginTop:8 }}>來自：{t.meeting}</div>
        </div>
      </div>

      {/* 備註按鈕（全寬，底部） */}
      <div
        onClick={() => setEditingTask(t)}
        style={{
          width:"100%", padding:"12px 0", borderRadius:10, cursor:"pointer",
          background: t.progressNote ? "rgba(79,140,255,0.13)" : "var(--surf)",
          border:`1.5px solid ${t.progressNote ? "rgba(79,140,255,0.4)" : "var(--border)"}`,
          display:"flex", alignItems:"center", justifyContent:"center", gap:8,
          fontSize:30, fontWeight:600, color: t.progressNote ? "var(--accent)" : "var(--muted)",
          transition:"all 0.2s"
        }}
      >📝 {t.progressNote ? "編輯工作進度備註" : "新增工作進度備註"}</div>
    </div>
  );

  // ── 儀表板內容 ──
  const DashboardContent = () => (
    <div className="mb-content-pad">
      <div style={{ background:"rgba(79,140,255,0.08)", border:"1px solid rgba(79,140,255,0.25)", borderRadius:14, padding:"12px 16px", marginBottom:14, display:"flex", alignItems:"center", gap:12 }}>
        <div style={{ fontSize:40 }}>🔗</div>
        <div>
          <div style={{ fontSize:34, fontWeight:600 }}>共用清單・即時同步</div>
          <div style={{ fontSize:34, color:"var(--muted)" }}>所有成員共用同一份資料，每 15 秒自動更新</div>
        </div>
      </div>

      <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr 1fr", gap:10, marginBottom:14 }}>
        {[{num:pendingCount,label:"待完成",color:"var(--accent)"},{num:doneCount,label:"已完成",color:"var(--green)"},{num:urgentCount,label:"緊急",color:"var(--red)"}].map(s=>(
          <div key={s.label} style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:14, padding:"14px 8px", textAlign:"center" }}>
            <div style={{ fontSize:50, fontWeight:900, fontFamily:"'DM Mono',monospace", color:s.color, lineHeight:1 }}>{s.num}</div>
            <div style={{ fontSize:34, color:"var(--muted)", marginTop:6 }}>{s.label}</div>
          </div>
        ))}
      </div>

      <div style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:14, padding:"14px 16px", marginBottom:14 }}>
        <div style={{ display:"flex", justifyContent:"space-between", fontSize:34, marginBottom:8 }}>
          <span style={{ color:"var(--muted)" }}>整體完成進度</span>
          <span style={{ fontWeight:700, color:"var(--green)", fontFamily:"'DM Mono',monospace" }}>{doneCount}/{tasks.length}</span>
        </div>
        <div style={{ height:8, background:"var(--border)", borderRadius:4, overflow:"hidden" }}>
          <div style={{ height:"100%", width:`${pct}%`, background:"linear-gradient(90deg,var(--accent),var(--green))", borderRadius:4, transition:"width 0.6s ease" }}/>
        </div>
      </div>

      {nextReminders.length>0 && (
        <div style={{ background:"rgba(255,159,67,0.06)", border:"1px solid rgba(255,159,67,0.2)", borderRadius:14, padding:"12px 16px", marginBottom:14 }}>
          <div style={{ fontSize:34, fontWeight:700, color:"var(--orange)", marginBottom:8 }}>即將觸發的提醒</div>
          {nextReminders.slice(0,3).map((r,i)=>(
            <div key={i} style={{ display:"flex", justifyContent:"space-between", fontSize:34, color:"var(--muted)", paddingBottom:i<2?6:0, borderBottom:i<Math.min(nextReminders.length,3)-1?"1px solid var(--border)":"none", marginBottom:i<2?6:0 }}>
              <span style={{ overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap", maxWidth:"55%" }}>• {r.task.title}</span>
              <span style={{ color:"var(--orange)", fontWeight:600, whiteSpace:"nowrap" }}>{r.type} · {`${pad2(r.at.getMonth()+1)}/${pad2(r.at.getDate())} ${pad2(r.at.getHours())}:00`}</span>
            </div>
          ))}
        </div>
      )}

      {/* 篩選列 */}
      <div style={{ display:"flex", gap:7, marginBottom:12, overflowX:"auto", paddingBottom:4, scrollbarWidth:"none" }}>
        {[["all","全部"],["pending","待辦"],["urgent","緊急"],["done","完成"]].map(([k,l])=>(
          <div key={k} onClick={()=>setFilter(k)} style={{ padding:"7px 14px", borderRadius:20, fontSize:34, fontWeight:600, cursor:"pointer", whiteSpace:"nowrap", background:filter===k?"var(--accent)":"var(--card)", color:filter===k?"#fff":"var(--muted)", border:`1px solid ${filter===k?"var(--accent)":"var(--border)"}`, transition:"all 0.2s" }}>{l}</div>
        ))}
        <div style={{ width:1, background:"var(--border)", margin:"0 3px", flexShrink:0 }}/>
        {["all",...TEAM].map(m=>(
          <div key={m} onClick={()=>setMemberFilter(m)} style={{ padding:"7px 14px", borderRadius:20, fontSize:34, cursor:"pointer", whiteSpace:"nowrap", background:memberFilter===m?memberColor(m):"var(--card)", color:memberFilter===m?"#fff":"var(--muted)", border:`1px solid ${memberFilter===m?memberColor(m):"var(--border)"}`, transition:"all 0.2s", fontWeight:memberFilter===m?700:400 }}>{m==="all"?"全員":m}</div>
        ))}
      </div>

      {/* 任務清單 */}
      {filtered.length===0 && <div style={{ textAlign:"center", color:"var(--muted)", padding:"40px 0", fontSize:34 }}>沒有符合的任務</div>}
      <div className="mb-task-grid">
        {filtered.map(t => <TaskCard key={t.id} t={t}/>)}
      </div>

      <div onClick={()=>fetchAll(true)} style={{ textAlign:"center", padding:"18px 0", fontSize:34, color:"var(--muted)", cursor:"pointer" }}>↻ 手動重新整理</div>
    </div>
  );

  // ── 上傳內容 ──
  const UploadContent = () => (
    <div className="mb-content-pad">
      <div style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:14, padding:"16px", marginBottom:16 }}>
        <div style={{ fontWeight:700, color:"var(--text)", marginBottom:14, fontSize:38 }}>新增單筆任務</div>
        <input
          placeholder="任務名稱"
          value={manualForm.title}
          onChange={e=>setManualForm(f=>({...f,title:e.target.value}))}
          style={{ width:"100%", padding:"12px 14px", borderRadius:10, border:"1px solid var(--border)", background:"var(--bg)", color:"var(--text)", fontSize:34, fontFamily:"inherit", marginBottom:10, outline:"none" }}
        />
        <select
          value={manualForm.assignee}
          onChange={e=>setManualForm(f=>({...f,assignee:e.target.value}))}
          style={{ width:"100%", padding:"12px 14px", borderRadius:10, border:"1px solid var(--border)", background:"var(--bg)", color:"var(--text)", fontSize:34, fontFamily:"inherit", marginBottom:10 }}
        >
          {TEAM.map(name=><option key={name} value={name}>{name}</option>)}
        </select>
        <input
          type="date"
          value={manualForm.deadline}
          onChange={e=>setManualForm(f=>({...f,deadline:e.target.value}))}
          style={{ width:"100%", padding:"12px 14px", borderRadius:10, border:"1px solid var(--border)", background:"var(--bg)", color:"var(--text)", fontSize:34, fontFamily:"inherit", marginBottom:10, outline:"none" }}
        />
        <input
          placeholder="會議名稱（選填）"
          value={manualForm.meeting}
          onChange={e=>setManualForm(f=>({...f,meeting:e.target.value}))}
          style={{ width:"100%", padding:"12px 14px", borderRadius:10, border:"1px solid var(--border)", background:"var(--bg)", color:"var(--text)", fontSize:34, fontFamily:"inherit", marginBottom:14, outline:"none" }}
        />
        <button onClick={addManualTask} style={{ width:"100%", padding:"14px", borderRadius:12, border:"none", background:"linear-gradient(135deg,var(--accent),#7c5fe6)", color:"#fff", fontSize:38, fontWeight:700, cursor:"pointer", fontFamily:"inherit" }}>新增任務</button>
      </div>
      <div onClick={()=>!parsing&&fileRef.current.click()} style={{ border:`2px dashed ${parsing?"var(--accent)":"var(--border)"}`, borderRadius:16, padding:"36px 20px", textAlign:"center", cursor:"pointer", background:"var(--card)", marginBottom:16, transition:"border-color 0.2s" }}>
        <input ref={fileRef} type="file" accept=".docx" onChange={handleFile} style={{ display:"none" }}/>
        {parsing ? (<>
          <div style={{ fontSize:54, marginBottom:12 }}>⚙️</div>
          <div style={{ fontWeight:700, fontSize:38, marginBottom:6 }}>AI 解析中...</div>
          <div style={{ fontSize:34, color:"var(--muted)" }}>正在從會議紀錄提取任務</div>
          <div style={{ marginTop:16, height:4, background:"var(--border)", borderRadius:2, overflow:"hidden" }}>
            <div style={{ height:"100%", background:"linear-gradient(90deg,var(--accent),var(--green))", animation:"slide 1.2s infinite", width:"40%" }}/>
          </div>
        </>) : (<>
          <div style={{ fontSize:66, marginBottom:12 }}>📄</div>
          <div style={{ fontWeight:700, fontSize:38, marginBottom:6 }}>{docName||"點擊上傳 .docx 會議紀錄"}</div>
          <div style={{ fontSize:34, color:"var(--muted)" }}>AI 自動解析任務、負責人、截止日期</div>
        </>)}
      </div>
      {parseResult && (
        <div style={{ animation:"fadeUp 0.4s ease" }}>
          <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:12, fontSize:34, color:"var(--green)", fontWeight:700 }}>找到 {parseResult.length} 項任務，確認後同步給全團隊</div>
          {parseResult.map((t,i)=>(
            <div key={i} style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:14, padding:"14px 16px", marginBottom:10 }}>
              <div style={{ fontSize:38, fontWeight:500, marginBottom:8 }}>{t.title}</div>
              <div style={{ display:"flex", gap:8, flexWrap:"wrap" }}>
                <div style={{ display:"flex", alignItems:"center", gap:5 }}><Avatar name={t.assignee} size={22}/><span style={{ fontSize:34, color:"var(--muted)" }}>{t.assignee}</span></div>
                <span style={bdg("var(--orange)","rgba(255,159,67,0.1)")}>📅 {t.deadline}</span>
              </div>
            </div>
          ))}
          <button onClick={confirmTasks} style={{ width:"100%", padding:"16px", borderRadius:12, border:"none", background:"linear-gradient(135deg,var(--green),#00b89c)", color:"#fff", fontSize:38, fontWeight:700, cursor:"pointer", fontFamily:"inherit", boxShadow:"0 4px 20px rgba(0,229,195,0.3)", marginTop:4 }}>同步給全團隊</button>
        </div>
      )}
      {!parsing&&!parseResult && (
        <div style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:14, padding:"16px", fontSize:34, color:"var(--muted)", lineHeight:2 }}>
          <div style={{ fontWeight:700, color:"var(--text)", marginBottom:8, fontSize:38 }}>使用說明</div>
          上傳包含會議決議事項的 Word 文件<br/>
          AI 會自動辨識「負責人」「任務」「截止時間」<br/>
          確認後立即同步給所有團隊成員
        </div>
      )}
    </div>
  );

  // ── 成員內容 ──
  const TeamContent = () => (
    <div className="mb-content-pad">
      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:14 }}>
        <div style={{ fontSize:34, color:"var(--muted)", fontWeight:700, letterSpacing:1.5, textTransform:"uppercase" }}>成員完成率（即時）</div>
        <button onClick={()=>exportToWord(tasks)} style={{
          padding:"9px 16px", borderRadius:10, border:"1px solid var(--border)",
          background:"var(--card)", color:"var(--text)", fontSize:34, fontWeight:600,
          cursor:"pointer", fontFamily:"inherit", display:"flex", alignItems:"center", gap:6
        }}>📄 匯出 Word</button>
      </div>
      {memberStats.length===0 && <div style={{ color:"var(--muted)", fontSize:34, textAlign:"center", padding:30 }}>尚無任務資料</div>}
      <div className="mb-member-grid">
        {memberStats.map(m=>(
          <div key={m.name} className="mb-member-card" style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:14, padding:"16px" }}>
            <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:12 }}>
              <div style={{ display:"flex", alignItems:"center", gap:12 }}>
                <Avatar name={m.name} size={42}/>
                <div><div style={{ fontWeight:700, fontSize:38 }}>{m.name}</div><div style={{ fontSize:34, color:"var(--muted)" }}>{m.done}/{m.total} 項完成</div></div>
              </div>
              <div style={{ fontFamily:"'DM Mono',monospace", fontSize:42, fontWeight:700, color:m.pct===100?"var(--green)":m.pct>=50?"var(--accent)":"var(--orange)" }}>{m.pct}%</div>
            </div>
            <div style={{ height:6, background:"var(--border)", borderRadius:3, overflow:"hidden", marginBottom:10 }}>
              <div style={{ height:"100%", width:`${m.pct}%`, borderRadius:3, background:`linear-gradient(90deg,${memberColor(m.name)},${memberColor(m.name)}aa)`, transition:"width 0.6s" }}/>
            </div>
            <div>
              {tasks.filter(t=>t.assignee===m.name&&!t.done).slice(0,3).map(t=>(
                <div key={t.id} style={{ fontSize:34, color:"var(--muted)", padding:"6px 0", borderTop:"1px solid var(--border)", display:"flex", justifyContent:"space-between", gap:8, alignItems:"flex-start" }}>
                  <div style={{ flex:1 }}>
                    <div style={{ overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}>• {t.title}</div>
                    {t.progressNote && <div style={{ fontSize:30, color:"var(--accent)", marginTop:3 }}>📝 {t.progressNote.length>30?t.progressNote.slice(0,30)+"…":t.progressNote}</div>}
                  </div>
                  <DeadlineBadge deadline={t.deadline} done={false}/>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
      <div style={{ fontSize:34, color:"var(--muted)", fontWeight:700, letterSpacing:1.5, textTransform:"uppercase", margin:"22px 0 12px" }}>固定成員</div>
      <div style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:14, padding:"16px" }}>
        <div style={{ display:"flex", flexWrap:"wrap", gap:10 }}>
          {TEAM.map(name=>(
            <div key={name} style={{ display:"flex", alignItems:"center", gap:7, background:"var(--surf)", borderRadius:24, padding:"6px 14px 6px 7px" }}>
              <Avatar name={name} size={26}/><span style={{ fontSize:34 }}>{name}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );

  // ── 提醒內容 ──
  const RemindersContent = () => (
    <div className="mb-content-pad">
      <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:16 }}>
        <div style={{ fontSize:34, color:"var(--muted)", fontWeight:700, letterSpacing:1.5, textTransform:"uppercase" }}>提醒規則設定</div>
        <div style={{ fontSize:34, color: savedPulse?"var(--green)":"var(--muted)", fontWeight:600, transition:"color 0.3s", animation: savedPulse?"savedPop 0.4s ease":undefined }}>
          {savedPulse ? "✓ 已儲存" : "修改後自動儲存"}
        </div>
      </div>

      {/* 規則 1：截止前 N 天 */}
      <div style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:14, padding:"18px", marginBottom:12 }}>
        <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:reminders.dayBefore.on?16:0 }}>
          <div style={{ display:"flex", alignItems:"center", gap:12 }}>
            <div style={{ width:40, height:40, borderRadius:10, background:"rgba(79,140,255,0.12)", display:"flex", alignItems:"center", justifyContent:"center", fontSize:38 }}>📅</div>
            <div><div style={{ fontSize:38, fontWeight:600 }}>截止日前提醒</div><div style={{ fontSize:34, color:"var(--muted)" }}>在截止日的前幾天早上提醒</div></div>
          </div>
          <Toggle on={reminders.dayBefore.on} onChange={()=>updateReminder("dayBefore",{on:!reminders.dayBefore.on})}/>
        </div>
        {reminders.dayBefore.on && (
          <div style={{ display:"flex", flexDirection:"column", gap:14, paddingTop:16, borderTop:"1px solid var(--border)" }}>
            <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between" }}>
              <span style={{ fontSize:34, color:"var(--muted)" }}>提前幾天</span>
              <Stepper value={reminders.dayBefore.days} min={1} max={7} suffix="天前" onChange={v=>updateReminder("dayBefore",{days:v})}/>
            </div>
            <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", flexWrap:"wrap", gap:8 }}>
              <span style={{ fontSize:34, color:"var(--muted)" }}>提醒時間</span>
              <div style={{ display:"flex", gap:7, flexWrap:"wrap" }}>
                {[7,8,9,10,12,14].map(h=>(
                  <div key={h} onClick={()=>updateReminder("dayBefore",{hour:h})} style={{ padding:"5px 12px", borderRadius:8, fontSize:34, cursor:"pointer", fontFamily:"'DM Mono',monospace", background:reminders.dayBefore.hour===h?"var(--accent)":"var(--surf)", color:reminders.dayBefore.hour===h?"#fff":"var(--muted)", border:`1px solid ${reminders.dayBefore.hour===h?"var(--accent)":"var(--border)"}`, transition:"all 0.2s" }}>{pad2(h)}:00</div>
                ))}
              </div>
            </div>
            <div style={{ background:"var(--surf)", borderRadius:8, padding:"10px 14px", fontSize:34, color:"var(--muted)" }}>
              例：任務截止日為週五，將在<span style={{ color:"var(--accent)", fontWeight:600 }}>週{WEEKDAYS[(5-reminders.dayBefore.days+7)%7]} {pad2(reminders.dayBefore.hour)}:00</span> 提醒負責人
            </div>
          </div>
        )}
      </div>

      {/* 規則 2：截止前 N 小時 */}
      <div style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:14, padding:"18px", marginBottom:12 }}>
        <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:reminders.hourBefore.on?16:0 }}>
          <div style={{ display:"flex", alignItems:"center", gap:12 }}>
            <div style={{ width:40, height:40, borderRadius:10, background:"rgba(255,159,67,0.12)", display:"flex", alignItems:"center", justifyContent:"center", fontSize:38 }}>⏰</div>
            <div><div style={{ fontSize:38, fontWeight:600 }}>截止前緊急提醒</div><div style={{ fontSize:34, color:"var(--muted)" }}>截止前幾小時發出最後警示</div></div>
          </div>
          <Toggle on={reminders.hourBefore.on} onChange={()=>updateReminder("hourBefore",{on:!reminders.hourBefore.on})}/>
        </div>
        {reminders.hourBefore.on && (
          <div style={{ paddingTop:16, borderTop:"1px solid var(--border)" }}>
            <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between" }}>
              <span style={{ fontSize:34, color:"var(--muted)" }}>提前幾小時</span>
              <Stepper value={reminders.hourBefore.hours} min={1} max={24} suffix="小時前" onChange={v=>updateReminder("hourBefore",{hours:v})}/>
            </div>
          </div>
        )}
      </div>

      {/* 規則 3：逾期提示 */}
      <div style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:14, padding:"18px", marginBottom:12 }}>
        <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between" }}>
          <div style={{ display:"flex", alignItems:"center", gap:12 }}>
            <div style={{ width:40, height:40, borderRadius:10, background:"rgba(255,91,121,0.12)", display:"flex", alignItems:"center", justifyContent:"center", fontSize:38 }}>🚨</div>
            <div><div style={{ fontSize:38, fontWeight:600 }}>逾期高亮提示</div><div style={{ fontSize:34, color:"var(--muted)" }}>逾期任務在儀表板醒目標示</div></div>
          </div>
          <Toggle on={reminders.overdueAlert.on} onChange={()=>updateReminder("overdueAlert",{on:!reminders.overdueAlert.on})}/>
        </div>
      </div>

      {/* 規則 4：每週報告 */}
      <div style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:14, padding:"18px", marginBottom:12 }}>
        <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:reminders.weeklyReport.on?16:0 }}>
          <div style={{ display:"flex", alignItems:"center", gap:12 }}>
            <div style={{ width:40, height:40, borderRadius:10, background:"rgba(0,229,195,0.12)", display:"flex", alignItems:"center", justifyContent:"center", fontSize:38 }}>📊</div>
            <div><div style={{ fontSize:38, fontWeight:600 }}>每週完成率報告</div><div style={{ fontSize:34, color:"var(--muted)" }}>固定時間推播團隊整體進度</div></div>
          </div>
          <Toggle on={reminders.weeklyReport.on} onChange={()=>updateReminder("weeklyReport",{on:!reminders.weeklyReport.on})}/>
        </div>
        {reminders.weeklyReport.on && (
          <div style={{ display:"flex", flexDirection:"column", gap:14, paddingTop:16, borderTop:"1px solid var(--border)" }}>
            <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between" }}>
              <span style={{ fontSize:34, color:"var(--muted)" }}>每週幾</span>
              <div style={{ display:"flex", gap:6 }}>
                {[1,2,3,4,5].map(d=>(
                  <div key={d} onClick={()=>updateReminder("weeklyReport",{weekday:d})} style={{ width:38, height:38, borderRadius:8, display:"flex", alignItems:"center", justifyContent:"center", fontSize:34, cursor:"pointer", background:reminders.weeklyReport.weekday===d?"var(--accent)":"var(--surf)", color:reminders.weeklyReport.weekday===d?"#fff":"var(--muted)", border:`1px solid ${reminders.weeklyReport.weekday===d?"var(--accent)":"var(--border)"}`, transition:"all 0.2s" }}>週{WEEKDAYS[d]}</div>
                ))}
              </div>
            </div>
            <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", flexWrap:"wrap", gap:8 }}>
              <span style={{ fontSize:34, color:"var(--muted)" }}>發送時間</span>
              <div style={{ display:"flex", gap:7 }}>
                {[9,12,14,16,17,18].map(h=>(
                  <div key={h} onClick={()=>updateReminder("weeklyReport",{hour:h})} style={{ padding:"5px 12px", borderRadius:8, fontSize:34, cursor:"pointer", fontFamily:"'DM Mono',monospace", background:reminders.weeklyReport.hour===h?"var(--green)":"var(--surf)", color:reminders.weeklyReport.hour===h?"#fff":"var(--muted)", border:`1px solid ${reminders.weeklyReport.hour===h?"var(--green)":"var(--border)"}`, transition:"all 0.2s" }}>{pad2(h)}:00</div>
                ))}
              </div>
            </div>
            <div style={{ background:"var(--surf)", borderRadius:8, padding:"10px 14px", fontSize:34, color:"var(--muted)" }}>
              每週{WEEKDAYS[reminders.weeklyReport.weekday]} <span style={{ color:"var(--green)", fontWeight:600 }}>{pad2(reminders.weeklyReport.hour)}:00</span> 推播完成率摘要給全團隊
            </div>
          </div>
        )}
      </div>

      {nextReminders.length>0 && (
        <div style={{ marginTop:22 }}>
          <div style={{ fontSize:34, color:"var(--muted)", fontWeight:700, letterSpacing:1.5, textTransform:"uppercase", marginBottom:12 }}>依目前設定，即將提醒</div>
          {nextReminders.map((r,i)=>(
            <div key={i} style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:10, padding:"13px 16px", marginBottom:7, display:"flex", alignItems:"center", justifyContent:"space-between", gap:12 }}>
              <div style={{ flex:1, minWidth:0 }}>
                <div style={{ fontSize:34, fontWeight:500, overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}>{r.task.title}</div>
                <div style={{ fontSize:34, color:"var(--muted)", marginTop:3 }}>{r.task.assignee} · {r.type}</div>
              </div>
              <div style={{ fontSize:34, color:"var(--orange)", fontWeight:700, fontFamily:"'DM Mono',monospace", whiteSpace:"nowrap" }}>
                {`${pad2(r.at.getMonth()+1)}/${pad2(r.at.getDate())} ${pad2(r.at.getHours())}:00`}
              </div>
            </div>
          ))}
        </div>
      )}

      <div style={{ background:"rgba(79,140,255,0.06)", border:"1px solid rgba(79,140,255,0.2)", borderRadius:14, padding:"16px", marginTop:18, fontSize:34, color:"var(--muted)", lineHeight:1.9 }}>
        <div style={{ fontWeight:700, color:"var(--text)", marginBottom:8, fontSize:38 }}>自動提醒說明</div>
        系統每小時整點自動檢查，符合條件時直接發 LINE 給負責人，不需要手動操作。
      </div>

      <button onClick={async () => {
        showToast("發送中...","#6b7494");
        const sent = await checkAndNotify(tasks, reminders);
        if (sent > 0) { setLastNotify(new Date()); showToast(`已發送 ${sent} 則 LINE 提醒`,"#00e5c3"); }
        else showToast("目前沒有符合條件的提醒","#6b7494");
      }} style={{ width:"100%", padding:"15px", borderRadius:12, border:"1px solid var(--border)", background:"var(--card)", color:"var(--text)", fontSize:34, fontWeight:600, cursor:"pointer", fontFamily:"inherit", marginTop:12 }}>
        立即檢查並發送 LINE 提醒
      </button>
      {lastNotify && <div style={{ textAlign:"center", fontSize:34, color:"var(--muted)", marginTop:10 }}>上次發送：{pad2(lastNotify.getHours())}:{pad2(lastNotify.getMinutes())}</div>}
    </div>
  );

  const TABS = [["dashboard","📊","任務"],["upload","📄","上傳"],["team","👥","成員"],["reminders","⏰","提醒"]];

  // ══════════════════════════════════════════════
  // ── 單一佈局（CSS media query 切換桌機/手機）──
  // ══════════════════════════════════════════════
  return (
    <>
      <style>{styleBlock}</style>
      <div ref={rootRef} className={isWide ? "mb-root mb-wide" : "mb-root"} style={{ fontFamily:"'Noto Sans TC',sans-serif", background:"var(--bg)", color:"var(--text)" }}>

        {/* 頂部欄 */}
        <div className="mb-topbar-inner" style={{ background:"var(--surf)", borderBottom:"1px solid var(--border)", padding:"13px 16px", display:"flex", alignItems:"center", justifyContent:"space-between", position:"sticky", top:0, zIndex:50 }}>
          <div style={{ display:"flex", alignItems:"center", gap:12 }}>
            <div className="mb-topbar-logo" style={{ width:36, height:36, borderRadius:10, background:"linear-gradient(135deg,#4f8cff,#00e5c3)", display:"flex", alignItems:"center", justifyContent:"center", fontSize:36 }}>📋</div>
            <div>
              <div className="mb-topbar-title" style={{ fontWeight:700, fontSize:38 }}>MeetBot</div>
              <div className="mb-topbar-sub" style={{ fontSize:30, color:"var(--muted)" }}>會議任務追蹤系統</div>
            </div>
          </div>
          <div style={{ display:"flex", alignItems:"center", gap:10, flexWrap:"wrap", justifyContent:"flex-end" }}>
            {urgentCount>0 && <div style={{ background:"rgba(255,91,121,0.15)", border:"1px solid var(--red)", color:"var(--red)", fontSize:30, fontWeight:700, padding:"3px 12px", borderRadius:20 }}>緊急 {urgentCount} 項</div>}
            <div style={{ background:"rgba(0,229,195,0.1)", border:"1px solid rgba(0,229,195,0.3)", color:"var(--green)", fontSize:30, fontWeight:700, padding:"3px 12px", borderRadius:20 }}>{pct}% 完成</div>
            <button onClick={()=>exportToWord(tasks)} style={{
              padding:"5px 14px", borderRadius:10, border:"1px solid var(--border)",
              background:"var(--card)", color:"var(--text)", fontSize:30, fontWeight:600,
              cursor:"pointer", fontFamily:"inherit", display:"flex", alignItems:"center", gap:5
            }}>📄 匯出 Word</button>
            <div style={{ display:"flex", alignItems:"center", gap:5, fontSize:30, color: syncing?"var(--accent)":"var(--muted)" }}>
              <div style={{ width:8, height:8, borderRadius:"50%", background: syncing?"var(--accent)":"var(--green)", animation: syncing?"pulse 1s infinite":"none" }}/>
              {syncing ? "同步中..." : syncLabel}
            </div>
          </div>
        </div>

        {/* 主體：側邊欄 + 內容 */}
        <div className="mb-main">

          {/* 側邊欄（桌機才顯示，CSS 控制） */}
          <div className="mb-sidebar">
            {TABS.map(([id,ic,lb])=>(
              <div key={id} onClick={()=>setTab(id)} style={{
                display:"flex", alignItems:"center", gap:12, padding:"14px 16px", borderRadius:10,
                cursor:"pointer", fontSize:34, fontWeight: tab===id ? 700 : 400,
                background: tab===id ? "rgba(79,140,255,0.12)" : "transparent",
                color: tab===id ? "var(--accent)" : "var(--muted)",
                border: tab===id ? "1px solid rgba(79,140,255,0.25)" : "1px solid transparent",
                transition:"all 0.2s"
              }}>
                <span style={{ fontSize:38 }}>{ic}</span>{lb}
              </div>
            ))}
          </div>

          {/* 內容區 */}
          <div className="mb-content-area" style={{ flex:1, minWidth:0 }}>

            {/* 頁籤列（手機才顯示，CSS 控制） */}
            <div className="mb-tabs">
              {TABS.map(([id,ic,lb])=>(
                <div key={id} onClick={()=>setTab(id)} style={{
                  flex:1, minWidth:68, textAlign:"center", padding:"10px 4px 8px", fontSize:30, cursor:"pointer",
                  color: tab===id ? "var(--accent)" : "var(--muted)",
                  borderBottom: tab===id ? "2.5px solid var(--accent)" : "2.5px solid transparent",
                  fontWeight: tab===id ? 700 : 400, transition:"all 0.2s", whiteSpace:"nowrap"
                }}><div style={{ fontSize:38, marginBottom:2 }}>{ic}</div>{lb}</div>
              ))}
            </div>

            {/* 頁面內容 */}
            {tab==="dashboard" && <DashboardContent/>}
            {tab==="upload"    && <UploadContent/>}
            {tab==="team"      && <TeamContent/>}
            {tab==="reminders" && <RemindersContent/>}
          </div>
        </div>

        {/* 備註 Modal */}
        {editingTask && <NoteModal task={editingTask} onSave={saveNote} onClose={()=>setEditingTask(null)}/>}

        {/* Toast */}
        {toast && (
          <div style={{ position:"fixed", bottom:28, left:"50%", transform:"translateX(-50%)", background:toast.color, color:"#fff", padding:"12px 24px", borderRadius:24, fontSize:34, fontWeight:600, zIndex:999, whiteSpace:"nowrap", boxShadow:"0 4px 20px rgba(0,0,0,0.4)", animation:"fadeUp 0.3s ease" }}>{toast.msg}</div>
        )}
      </div>
    </>
  );
}
