import { useState, useEffect, useRef, useCallback } from "react";
import * as mammoth from "mammoth";
import { initializeApp } from "firebase/app";
import { getDatabase, ref, set, get } from "firebase/database";

// ── Firebase 設定 ──────────────────────────────
const firebaseConfig = {
  apiKey: "AIzaSyABlghqrAFcwFlSeV5FgIbuu5LLfCnxY0k",
  authDomain: "meetbot-ede53.firebaseapp.com",
  databaseURL: "https://meetbot-ede53-default-rtdb.asia-southeast1.firebasedatabase.app",
  projectId: "meetbot-ede53",
  storageBucket: "meetbot-ede53.firebasestorage.app",
  messagingSenderId: "452091108377",
  appId: "1:452091108377:web:6ce5396d7e55ae6a68de88"
};
const firebaseApp = initializeApp(firebaseConfig);
const db = getDatabase(firebaseApp);

// ── 固定團隊成員 ──────────────────────────────
const TEAM = ["小明", "怡君", "阿偉", "美玲", "志豪", "逸"];
const AVATAR_COLORS = ["#4f8cff","#00e5c3","#ff9f43","#ff5b79","#a78bfa","#34d399"];
const BACKEND_URL = "https://meetbot-backend.onrender.com";

// ── 示範任務 ──────────────────────────────────
const DEMO_TASKS = [
  { id:1, title:"彙整各診所回報的處方數量，傳給主任", assignee:"怡君", deadline:"2026-03-28", meeting:"週會 3/21", done:false, urgent:false },
  { id:2, title:"確認 Q2 採購預算核准文件", assignee:"小明", deadline:"2026-03-28", meeting:"週會 3/21", done:false, urgent:false },
  { id:3, title:"更新居民追蹤名單並上傳系統", assignee:"阿偉", deadline:"2026-03-28", meeting:"週會 3/21", done:false, urgent:false },
];

// ── 提醒預設值 ────────────────────────────────
const DEFAULT_REMINDERS = {
  dayBefore:   { on: true,  days: 1,  hour: 9  },
  hourBefore:  { on: true,  hours: 2            },
  weeklyReport:{ on: false, weekday: 5, hour: 16 },
  overdueAlert:{ on: true                        },
};

// ── 工具函式 ──────────────────────────────────
const today    = () => new Date().toISOString().slice(0,10);
const daysLeft = (d) => Math.ceil((new Date(d) - new Date(today())) / 86400000);
const memberColor = (n) => AVATAR_COLORS[TEAM.indexOf(n) % AVATAR_COLORS.length] || "#888";
const pad2 = (n) => String(n).padStart(2,"0");

// ── Firebase Storage ──────────────────────────
async function loadTasks() {
  try {
    const snap = await get(ref(db, "meetbot/tasks"));
    if (snap.exists()) return Object.values(snap.val());
    await set(ref(db, "meetbot/tasks"), Object.fromEntries(DEMO_TASKS.map(t => [t.id, t])));
    return DEMO_TASKS;
  } catch { return DEMO_TASKS; }
}
async function saveTasks(tasks) {
  try { await set(ref(db, "meetbot/tasks"), Object.fromEntries(tasks.map(t => [t.id, t]))); } catch {}
}
async function loadReminders() {
  try {
    const snap = await get(ref(db, "meetbot/reminders"));
    return snap.exists() ? { ...DEFAULT_REMINDERS, ...snap.val() } : DEFAULT_REMINDERS;
  } catch { return DEFAULT_REMINDERS; }
}
async function saveReminders(r) {
  try { await set(ref(db, "meetbot/reminders"), r); } catch {}
}

// ── 呼叫後端發送 LINE 提醒 ────────────────────
async function checkAndNotify(tasks, reminders) {
  try {
    const res = await fetch(`${BACKEND_URL}/check-reminders`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tasks, reminders })
    });
    const data = await res.json();
    return data.sent || 0;
  } catch { return 0; }
}

// ── 計算下次提醒 ──────────────────────────────
function calcNextReminder(tasks, reminders) {
  const hits = [];
  const now = new Date();
  tasks.filter(t => !t.done).forEach(t => {
    const dl = new Date(t.deadline + "T23:59:00");
    if (reminders.hourBefore?.on) {
      const fireAt = new Date(dl.getTime() - reminders.hourBefore.hours * 3600000);
      if (fireAt > now) hits.push({ task: t, at: fireAt, type: `截止前 ${reminders.hourBefore.hours} 小時` });
    }
    if (reminders.dayBefore?.on) {
      const fireAt = new Date(dl);
      fireAt.setDate(fireAt.getDate() - reminders.dayBefore.days);
      fireAt.setHours(reminders.dayBefore.hour, 0, 0, 0);
      if (fireAt > now) hits.push({ task: t, at: fireAt, type: `截止前 ${reminders.dayBefore.days} 天` });
    }
  });
  return hits.sort((a,b) => a.at - b.at).slice(0,5);
}

// ── AI 解析 ───────────────────────────────────
async function parseWithAI(text) {
  const today_str = new Date().toISOString().slice(0,10);
  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({
      model:"claude-sonnet-4-20250514", max_tokens:1000,
      messages:[{ role:"user", content:
        `你是會議記錄分析助理。從以下會議紀錄中，找出所有「任務/行動項目」。
每個任務需包含：負責人、任務描述、截止日期。今天是 ${today_str}。
若日期只說「本週五」請換算成實際日期。若無法確定截止日期，設定為 7 天後。
負責人請從以下名單選最接近的：${TEAM.join("、")}。若無法對應，填「待指派」。
請只回傳 JSON 陣列，格式如下，不要有任何說明文字：
[{"title":"任務描述","assignee":"負責人","deadline":"YYYY-MM-DD"}]
會議紀錄：\n${text}` }]
    })
  });
  const data = await res.json();
  const raw = data.content?.find(b=>b.type==="text")?.text || "[]";
  return JSON.parse(raw.replace(/```json|```/g,"").trim());
}

// ── 元件 ──────────────────────────────────────
function Avatar({ name, size=28 }) {
  return <div style={{ width:size, height:size, borderRadius:"50%", background:memberColor(name), display:"flex", alignItems:"center", justifyContent:"center", fontSize:size*0.42, fontWeight:700, color:"#fff", flexShrink:0 }}>{name[0]}</div>;
}

function DeadlineBadge({ deadline, done }) {
  if (done) return <span style={bdg("#00e5c3","rgba(0,229,195,0.12)")}>✓ 完成</span>;
  const d = daysLeft(deadline);
  if (d < 0)   return <span style={bdg("#ff5b79","rgba(255,91,121,0.12)")}>逾期 {Math.abs(d)} 天</span>;
  if (d === 0) return <span style={bdg("#ff5b79","rgba(255,91,121,0.12)")}>今天截止</span>;
  if (d <= 2)  return <span style={bdg("#ff9f43","rgba(255,159,67,0.12)")}>剩 {d} 天</span>;
  return <span style={bdg("#6b7494","rgba(107,116,148,0.12)")}>{deadline.slice(5).replace("-","/")} 截止</span>;
}
const bdg = (c,bg) => ({ fontSize:11, padding:"2px 8px", borderRadius:20, background:bg, color:c, fontWeight:600, whiteSpace:"nowrap" });

function Toggle({ on, onChange }) {
  return <div onClick={onChange} style={{ width:42, height:24, borderRadius:12, cursor:"pointer", position:"relative", flexShrink:0, background: on ? "#4f8cff" : "#232840", transition:"background 0.2s" }}><div style={{ position:"absolute", width:18, height:18, borderRadius:"50%", background:"#fff", top:3, left: on ? 21 : 3, transition:"left 0.2s", boxShadow:"0 1px 4px rgba(0,0,0,0.3)" }}/></div>;
}

function Stepper({ value, min, max, onChange, suffix="" }) {
  return <div style={{ display:"flex", alignItems:"center", gap:8 }}>
    <div onClick={() => onChange(Math.max(min, value-1))} style={{ width:28, height:28, borderRadius:8, background:"#181d2a", border:"1px solid #232840", display:"flex", alignItems:"center", justifyContent:"center", cursor:"pointer", fontSize:16, userSelect:"none" }}>−</div>
    <span style={{ fontSize:14, fontWeight:700, minWidth:28, textAlign:"center", fontFamily:"monospace" }}>{value}</span>
    <div onClick={() => onChange(Math.min(max, value+1))} style={{ width:28, height:28, borderRadius:8, background:"#181d2a", border:"1px solid #232840", display:"flex", alignItems:"center", justifyContent:"center", cursor:"pointer", fontSize:16, userSelect:"none" }}>+</div>
    {suffix && <span style={{ fontSize:12, color:"#5a6285" }}>{suffix}</span>}
  </div>;
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
  const [toast,        setToast]        = useState(null);
  const [savedPulse,   setSavedPulse]   = useState(false);
  const fileRef      = useRef();
  const isFirst      = useRef(true);
  const isSaving     = useRef(false);
  const tasksRef     = useRef([]);
  const remindersRef = useRef(DEFAULT_REMINDERS);

  const showToast = (msg, color="#4f8cff") => { setToast({msg,color}); setTimeout(()=>setToast(null),2800); };

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
    const poll = setInterval(() => { if (!isSaving.current) fetchAll(true); }, 30000);
    const reminderCheck = setInterval(async () => {
      const sent = await checkAndNotify(tasksRef.current, remindersRef.current);
      if (sent > 0) { setLastNotify(new Date()); showToast(`📨 已發送 ${sent} 則 LINE 提醒`,"#00e5c3"); }
    }, 3600000);
    return () => { clearInterval(poll); clearInterval(reminderCheck); };
  }, [fetchAll]);

  useEffect(() => {
    if (isFirst.current) { isFirst.current = false; return; }
    if (loading) return;
    tasksRef.current = tasks;
    isSaving.current = true;
    saveTasks(tasks).finally(() => { isSaving.current = false; setLastSync(new Date()); });
  }, [tasks, loading]);

  const saveReminderSettings = async (newR) => {
    setReminders(newR); remindersRef.current = newR;
    await saveReminders(newR); setSavedPulse(true); setTimeout(()=>setSavedPulse(false),1500);
  };
  const updateReminder = (key, patch) => saveReminderSettings({ ...reminders, [key]: { ...reminders[key], ...patch } });

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
    const newTasks = parseResult.map((t,i) => ({ id: Date.now()+i, title:t.title, assignee:t.assignee, deadline:t.deadline, meeting, done:false, urgent: daysLeft(t.deadline)<=1 }));
    setTasks(prev => [...newTasks,...prev]);
    setParseResult(null); setDocName(""); setTab("dashboard");
    showToast(`🔗 已同步 ${newTasks.length} 項任務給全團隊`);
  };

  const toggleDone = (id) => setTasks(prev => prev.map(t => t.id===id ? {...t,done:!t.done} : t));

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

  if (loading) return (
    <div style={{ fontFamily:"'Noto Sans TC',sans-serif", background:"#080b12", color:"#e8eaf2", minHeight:"100vh", display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:16 }}>
      <div style={{ fontSize:40 }}>📋</div>
      <div style={{ fontWeight:700, fontSize:16 }}>載入中...</div>
      <div style={{ fontSize:11, color:"#5a6285" }}>連接 Firebase 資料庫</div>
    </div>
  );

  const S = {
    bg:"#080b12", surf:"#10141e", card:"#181d2a", border:"#232840",
    accent:"#4f8cff", green:"#00e5c3", orange:"#ff9f43", red:"#ff5b79",
    text:"#e8eaf2", muted:"#5a6285"
  };

  return (
    <div style={{ fontFamily:"'Noto Sans TC',sans-serif", background:S.bg, color:S.text, minHeight:"100vh", maxWidth:480, margin:"0 auto", position:"relative" }}>
      <style>{`@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700;900&display=swap');*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}body{background:#080b12}@keyframes fadeUp{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}@keyframes slide{0%{transform:translateX(-100%)}100%{transform:translateX(350%)}}@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}::-webkit-scrollbar{width:4px}::-webkit-scrollbar-thumb{background:#232840;border-radius:2px}`}</style>

      {/* TOPBAR */}
      <div style={{ background:S.surf, borderBottom:`1px solid ${S.border}`, padding:"12px 16px", display:"flex", alignItems:"center", justifyContent:"space-between", position:"sticky", top:0, zIndex:50 }}>
        <div style={{ display:"flex", alignItems:"center", gap:10 }}>
          <div style={{ width:32, height:32, borderRadius:10, background:"linear-gradient(135deg,#4f8cff,#00e5c3)", display:"flex", alignItems:"center", justifyContent:"center", fontSize:16 }}>📋</div>
          <div>
            <div style={{ fontWeight:700, fontSize:15 }}>MeetBot</div>
            <div style={{ fontSize:10, color:S.muted }}>會議任務追蹤系統</div>
          </div>
        </div>
        <div style={{ display:"flex", flexDirection:"column", alignItems:"flex-end", gap:4 }}>
          <div style={{ display:"flex", gap:5 }}>
            {urgentCount>0 && <div style={{ background:"rgba(255,91,121,0.15)", border:`1px solid ${S.red}`, color:S.red, fontSize:10, fontWeight:700, padding:"2px 7px", borderRadius:20 }}>⚡{urgentCount}</div>}
            <div style={{ background:"rgba(0,229,195,0.1)", border:"1px solid rgba(0,229,195,0.3)", color:S.green, fontSize:10, fontWeight:700, padding:"2px 7px", borderRadius:20 }}>{pct}%</div>
          </div>
          <div style={{ display:"flex", alignItems:"center", gap:4, fontSize:10, color: syncing?S.accent:S.muted }}>
            <div style={{ width:6, height:6, borderRadius:"50%", background: syncing?S.accent:S.green, animation: syncing?"pulse 1s infinite":"none" }}/>
            {syncing ? "同步中..." : syncLabel}
          </div>
        </div>
      </div>

      {/* TABS */}
      <div style={{ display:"flex", background:S.surf, borderBottom:`1px solid ${S.border}`, overflowX:"auto", scrollbarWidth:"none" }}>
        {[["dashboard","📊","任務"],["upload","📄","上傳"],["team","👥","成員"],["reminders","⏰","提醒"]].map(([id,ic,lb]) => (
          <div key={id} onClick={()=>setTab(id)} style={{ flex:1, minWidth:64, textAlign:"center", padding:"10px 4px 8px", fontSize:11, cursor:"pointer", color:tab===id?S.accent:S.muted, borderBottom:tab===id?`2px solid ${S.accent}`:"2px solid transparent", fontWeight:tab===id?700:400, transition:"all 0.2s", whiteSpace:"nowrap" }}>
            <div style={{ fontSize:18, marginBottom:2 }}>{ic}</div>{lb}
          </div>
        ))}
      </div>

      {/* ══ 儀表板 ══ */}
      {tab==="dashboard" && (
        <div style={{ padding:"14px 14px 100px" }}>
          <div style={{ background:"rgba(79,140,255,0.08)", border:"1px solid rgba(79,140,255,0.25)", borderRadius:12, padding:"10px 14px", marginBottom:12, display:"flex", alignItems:"center", gap:10 }}>
            <div style={{ fontSize:18 }}>🔗</div>
            <div>
              <div style={{ fontSize:12, fontWeight:600 }}>Firebase 共用清單・即時同步</div>
              <div style={{ fontSize:11, color:S.muted }}>所有成員共用同一份資料，30 秒自動更新</div>
            </div>
          </div>
          <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr 1fr", gap:8, marginBottom:12 }}>
            {[{num:pendingCount,label:"待完成",color:S.accent},{num:doneCount,label:"已完成",color:S.green},{num:urgentCount,label:"緊急",color:S.red}].map(s=>(
              <div key={s.label} style={{ background:S.card, border:`1px solid ${S.border}`, borderRadius:12, padding:"12px 8px", textAlign:"center" }}>
                <div style={{ fontSize:26, fontWeight:900, fontFamily:"monospace", color:s.color, lineHeight:1 }}>{s.num}</div>
                <div style={{ fontSize:10, color:S.muted, marginTop:5 }}>{s.label}</div>
              </div>
            ))}
          </div>
          <div style={{ background:S.card, border:`1px solid ${S.border}`, borderRadius:12, padding:"12px 14px", marginBottom:12 }}>
            <div style={{ display:"flex", justifyContent:"space-between", fontSize:12, marginBottom:8 }}>
              <span style={{ color:S.muted }}>整體完成進度</span>
              <span style={{ fontWeight:700, color:S.green, fontFamily:"monospace" }}>{doneCount}/{tasks.length}</span>
            </div>
            <div style={{ height:6, background:S.border, borderRadius:3, overflow:"hidden" }}>
              <div style={{ height:"100%", width:`${pct}%`, background:"linear-gradient(90deg,#4f8cff,#00e5c3)", borderRadius:3, transition:"width 0.6s ease" }}/>
            </div>
          </div>
          {nextReminders.length>0 && (
            <div style={{ background:"rgba(255,159,67,0.06)", border:"1px solid rgba(255,159,67,0.2)", borderRadius:12, padding:"12px 14px", marginBottom:12 }}>
              <div style={{ fontSize:11, fontWeight:700, color:S.orange, marginBottom:8 }}>⏰ 即將觸發的提醒</div>
              {nextReminders.slice(0,3).map((r,i)=>(
                <div key={i} style={{ display:"flex", justifyContent:"space-between", fontSize:11, color:S.muted, marginBottom: i<2?6:0, paddingBottom: i<2?6:0, borderBottom: i<2?`1px solid ${S.border}`:"none" }}>
                  <span style={{ overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap", maxWidth:"55%" }}>• {r.task.title}</span>
                  <span style={{ color:S.orange, fontWeight:600, whiteSpace:"nowrap" }}>{r.type} · {pad2(r.at.getMonth()+1)}/{pad2(r.at.getDate())} {pad2(r.at.getHours())}:00</span>
                </div>
              ))}
            </div>
          )}
          <div style={{ display:"flex", gap:6, marginBottom:10, overflowX:"auto", paddingBottom:4, scrollbarWidth:"none" }}>
            {[["all","全部"],["pending","待辦"],["urgent","緊急"],["done","完成"]].map(([k,l])=>(
              <div key={k} onClick={()=>setFilter(k)} style={{ padding:"5px 12px", borderRadius:20, fontSize:12, fontWeight:600, cursor:"pointer", whiteSpace:"nowrap", background:filter===k?S.accent:S.card, color:filter===k?"#fff":S.muted, border:`1px solid ${filter===k?S.accent:S.border}`, transition:"all 0.2s" }}>{l}</div>
            ))}
            <div style={{ width:1, background:S.border, margin:"0 2px", flexShrink:0 }}/>
            {["all",...TEAM].map(m=>(
              <div key={m} onClick={()=>setMemberFilter(m)} style={{ padding:"5px 12px", borderRadius:20, fontSize:12, cursor:"pointer", whiteSpace:"nowrap", background:memberFilter===m?memberColor(m):S.card, color:memberFilter===m?"#fff":S.muted, border:`1px solid ${memberFilter===m?memberColor(m):S.border}`, transition:"all 0.2s", fontWeight:memberFilter===m?700:400 }}>{m==="all"?"全員":m}</div>
            ))}
          </div>
          {filtered.length===0 && <div style={{ textAlign:"center", color:S.muted, padding:"40px 0", fontSize:13 }}>沒有符合的任務</div>}
          {filtered.map(t=>(
            <div key={t.id} onClick={()=>toggleDone(t.id)} style={{ background:t.done?"rgba(24,29,42,0.5)":S.card, border:`1px solid ${t.urgent&&!t.done?"rgba(255,91,121,0.3)":S.border}`, borderRadius:12, padding:"13px 14px", marginBottom:8, display:"flex", gap:12, alignItems:"flex-start", cursor:"pointer", opacity:t.done?0.55:1, transition:"all 0.2s" }}>
              <div style={{ width:22, height:22, borderRadius:"50%", flexShrink:0, marginTop:1, border:`2px solid ${t.done?S.green:t.urgent?S.red:S.border}`, background:t.done?S.green:"transparent", display:"flex", alignItems:"center", justifyContent:"center", fontSize:11, color:"#fff", transition:"all 0.2s" }}>{t.done?"✓":""}</div>
              <div style={{ flex:1, minWidth:0 }}>
                <div style={{ fontSize:14, fontWeight:500, lineHeight:1.5, marginBottom:6, textDecoration:t.done?"line-through":"none", color:t.done?S.muted:S.text }}>{t.title}</div>
                <div style={{ display:"flex", gap:6, flexWrap:"wrap", alignItems:"center" }}>
                  <div style={{ display:"flex", alignItems:"center", gap:4 }}><Avatar name={t.assignee} size={18}/><span style={{ fontSize:11, color:S.muted }}>{t.assignee}</span></div>
                  <DeadlineBadge deadline={t.deadline} done={t.done}/>
                  {t.urgent&&!t.done && <span style={bdg(S.red,"rgba(255,91,121,0.1)")}>⚡ 緊急</span>}
                </div>
                <div style={{ fontSize:10, color:S.muted, marginTop:5 }}>📋 {t.meeting}</div>
              </div>
            </div>
          ))}
          <div onClick={()=>fetchAll(true)} style={{ textAlign:"center", padding:"16px 0", fontSize:12, color:S.muted, cursor:"pointer" }}>↻ 手動重新整理</div>
        </div>
      )}

      {/* ══ 上傳會議 ══ */}
      {tab==="upload" && (
        <div style={{ padding:"16px 14px 100px" }}>
          <div onClick={()=>!parsing&&fileRef.current.click()} style={{ border:`2px dashed ${parsing?S.accent:S.border}`, borderRadius:14, padding:"32px 20px", textAlign:"center", cursor:"pointer", background:S.card, marginBottom:14, transition:"border-color 0.2s" }}>
            <input ref={fileRef} type="file" accept=".docx" onChange={handleFile} style={{ display:"none" }}/>
            {parsing ? (<>
              <div style={{ fontSize:32, marginBottom:10 }}>⚙️</div>
              <div style={{ fontWeight:700, marginBottom:4 }}>AI 解析中...</div>
              <div style={{ marginTop:14, height:3, background:S.border, borderRadius:2, overflow:"hidden" }}>
                <div style={{ height:"100%", background:"linear-gradient(90deg,#4f8cff,#00e5c3)", animation:"slide 1.2s infinite", width:"40%" }}/>
              </div>
            </>) : (<>
              <div style={{ fontSize:40, marginBottom:10 }}>📄</div>
              <div style={{ fontWeight:700, marginBottom:4 }}>{docName||"點擊上傳 .docx 會議紀錄"}</div>
              <div style={{ fontSize:12, color:S.muted }}>AI 自動解析任務、負責人、截止日期</div>
            </>)}
          </div>
          {parseResult && (
            <div style={{ animation:"fadeUp 0.4s ease" }}>
              <div style={{ fontSize:13, color:S.green, fontWeight:700, marginBottom:10 }}>✦ 找到 {parseResult.length} 項任務</div>
              {parseResult.map((t,i)=>(
                <div key={i} style={{ background:S.card, border:`1px solid ${S.border}`, borderRadius:12, padding:"12px 14px", marginBottom:8 }}>
                  <div style={{ fontSize:14, fontWeight:500, marginBottom:6 }}>{t.title}</div>
                  <div style={{ display:"flex", gap:8, flexWrap:"wrap" }}>
                    <div style={{ display:"flex", alignItems:"center", gap:4 }}><Avatar name={t.assignee} size={18}/><span style={{ fontSize:11, color:S.muted }}>{t.assignee}</span></div>
                    <span style={bdg(S.orange,"rgba(255,159,67,0.1)")}>📅 {t.deadline}</span>
                  </div>
                </div>
              ))}
              <button onClick={confirmTasks} style={{ width:"100%", padding:"14px", borderRadius:12, border:"none", background:"linear-gradient(135deg,#00e5c3,#00b89c)", color:"#fff", fontSize:14, fontWeight:700, cursor:"pointer", fontFamily:"inherit", marginTop:4 }}>🔗 同步給全團隊</button>
            </div>
          )}
          {!parsing&&!parseResult && (
            <div style={{ background:S.card, border:`1px solid ${S.border}`, borderRadius:12, padding:"14px", fontSize:12, color:S.muted, lineHeight:1.8 }}>
              <div style={{ fontWeight:700, color:S.text, marginBottom:6 }}>📌 使用說明</div>
              上傳包含會議決議事項的 Word 文件<br/>AI 會自動辨識「負責人」「任務」「截止時間」<br/>確認後立即同步給所有團隊成員
            </div>
          )}
        </div>
      )}

      {/* ══ 成員 ══ */}
      {tab==="team" && (
        <div style={{ padding:"16px 14px 100px" }}>
          <div style={{ fontSize:11, color:S.muted, fontWeight:700, letterSpacing:1.5, textTransform:"uppercase", marginBottom:12 }}>成員完成率</div>
          {memberStats.length===0 && <div style={{ color:S.muted, fontSize:13, textAlign:"center", padding:30 }}>尚無任務資料</div>}
          {memberStats.map(m=>(
            <div key={m.name} style={{ background:S.card, border:`1px solid ${S.border}`, borderRadius:12, padding:"14px", marginBottom:8 }}>
              <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:10 }}>
                <div style={{ display:"flex", alignItems:"center", gap:10 }}>
                  <Avatar name={m.name} size={36}/>
                  <div><div style={{ fontWeight:700, fontSize:14 }}>{m.name}</div><div style={{ fontSize:11, color:S.muted }}>{m.done}/{m.total} 項完成</div></div>
                </div>
                <div style={{ fontFamily:"monospace", fontSize:22, fontWeight:700, color:m.pct===100?S.green:m.pct>=50?S.accent:S.orange }}>{m.pct}%</div>
              </div>
              <div style={{ height:5, background:S.border, borderRadius:3, overflow:"hidden" }}>
                <div style={{ height:"100%", width:`${m.pct}%`, borderRadius:3, background:`linear-gradient(90deg,${memberColor(m.name)},${memberColor(m.name)}aa)`, transition:"width 0.6s" }}/>
              </div>
              {tasks.filter(t=>t.assignee===m.name&&!t.done).slice(0,2).map(t=>(
                <div key={t.id} style={{ fontSize:11, color:S.muted, padding:"5px 0", borderTop:`1px solid ${S.border}`, marginTop:8, display:"flex", justifyContent:"space-between", gap:8 }}>
                  <span style={{ overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}>• {t.title}</span>
                  <DeadlineBadge deadline={t.deadline} done={false}/>
                </div>
              ))}
            </div>
          ))}
          <div style={{ fontSize:11, color:S.muted, fontWeight:700, letterSpacing:1.5, textTransform:"uppercase", margin:"20px 0 12px" }}>固定成員</div>
          <div style={{ background:S.card, border:`1px solid ${S.border}`, borderRadius:12, padding:"14px" }}>
            <div style={{ display:"flex", flexWrap:"wrap", gap:10 }}>
              {TEAM.map(name=>(
                <div key={name} style={{ display:"flex", alignItems:"center", gap:6, background:S.surf, borderRadius:20, padding:"5px 12px 5px 6px" }}>
                  <Avatar name={name} size={22}/><span style={{ fontSize:12 }}>{name}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ══ 提醒設定 ══ */}
      {tab==="reminders" && (
        <div style={{ padding:"16px 14px 100px" }}>
          <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:14 }}>
            <div style={{ fontSize:11, color:S.muted, fontWeight:700, letterSpacing:1.5, textTransform:"uppercase" }}>提醒規則設定</div>
            <div style={{ fontSize:11, color: savedPulse?S.green:S.muted, fontWeight:600 }}>{savedPulse ? "✓ 已儲存" : "修改後自動儲存"}</div>
          </div>

          {[
            { key:"dayBefore", icon:"📅", title:"截止日前提醒", sub:"在截止日的前幾天早上提醒",
              extra: reminders.dayBefore.on && (
                <div style={{ display:"flex", flexDirection:"column", gap:12, paddingTop:14, borderTop:`1px solid ${S.border}` }}>
                  <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between" }}>
                    <span style={{ fontSize:13, color:S.muted }}>提前幾天</span>
                    <Stepper value={reminders.dayBefore.days} min={1} max={7} suffix="天前" onChange={v=>updateReminder("dayBefore",{days:v})}/>
                  </div>
                  <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between" }}>
                    <span style={{ fontSize:13, color:S.muted }}>提醒時間</span>
                    <div style={{ display:"flex", gap:6, flexWrap:"wrap", justifyContent:"flex-end" }}>
                      {[7,8,9,10,12,14].map(h=>(
                        <div key={h} onClick={()=>updateReminder("dayBefore",{hour:h})} style={{ padding:"4px 10px", borderRadius:8, fontSize:12, cursor:"pointer", fontFamily:"monospace", background:reminders.dayBefore.hour===h?S.accent:S.surf, color:reminders.dayBefore.hour===h?"#fff":S.muted, border:`1px solid ${reminders.dayBefore.hour===h?S.accent:S.border}` }}>{pad2(h)}:00</div>
                      ))}
                    </div>
                  </div>
                </div>
              )
            },
            { key:"hourBefore", icon:"⏰", title:"截止前緊急提醒", sub:"截止前幾小時發出最後警示",
              extra: reminders.hourBefore.on && (
                <div style={{ paddingTop:14, borderTop:`1px solid ${S.border}` }}>
                  <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between" }}>
                    <span style={{ fontSize:13, color:S.muted }}>提前幾小時</span>
                    <Stepper value={reminders.hourBefore.hours} min={1} max={24} suffix="小時前" onChange={v=>updateReminder("hourBefore",{hours:v})}/>
                  </div>
                </div>
              )
            },
            { key:"overdueAlert", icon:"🚨", title:"逾期高亮提示", sub:"逾期任務在儀表板醒目標示" },
          ].map(row=>(
            <div key={row.key} style={{ background:S.card, border:`1px solid ${S.border}`, borderRadius:12, padding:"16px", marginBottom:10 }}>
              <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom: row.extra?14:0 }}>
                <div style={{ display:"flex", alignItems:"center", gap:10 }}>
                  <div style={{ width:36, height:36, borderRadius:10, background:"rgba(79,140,255,0.12)", display:"flex", alignItems:"center", justifyContent:"center", fontSize:18 }}>{row.icon}</div>
                  <div><div style={{ fontSize:14, fontWeight:600 }}>{row.title}</div><div style={{ fontSize:11, color:S.muted }}>{row.sub}</div></div>
                </div>
                <Toggle on={reminders[row.key].on} onChange={()=>updateReminder(row.key,{on:!reminders[row.key].on})}/>
              </div>
              {row.extra}
            </div>
          ))}

          {nextReminders.length>0 && (
            <div style={{ marginTop:20 }}>
              <div style={{ fontSize:11, color:S.muted, fontWeight:700, letterSpacing:1.5, textTransform:"uppercase", marginBottom:10 }}>即將提醒</div>
              {nextReminders.map((r,i)=>(
                <div key={i} style={{ background:S.card, border:`1px solid ${S.border}`, borderRadius:10, padding:"11px 14px", marginBottom:6, display:"flex", alignItems:"center", justifyContent:"space-between", gap:10 }}>
                  <div style={{ flex:1, minWidth:0 }}>
                    <div style={{ fontSize:12, fontWeight:500, overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}>{r.task.title}</div>
                    <div style={{ fontSize:11, color:S.muted, marginTop:3 }}>{r.task.assignee} · {r.type}</div>
                  </div>
                  <div style={{ fontSize:11, color:S.orange, fontWeight:700, fontFamily:"monospace", whiteSpace:"nowrap" }}>{pad2(r.at.getMonth()+1)}/{pad2(r.at.getDate())} {pad2(r.at.getHours())}:00</div>
                </div>
              ))}
            </div>
          )}

          <div style={{ background:"rgba(79,140,255,0.06)", border:"1px solid rgba(79,140,255,0.2)", borderRadius:12, padding:"14px", marginTop:16, fontSize:12, color:S.muted, lineHeight:1.8 }}>
            <div style={{ fontWeight:700, color:S.text, marginBottom:6 }}>💡 自動提醒說明</div>
            系統每小時整點自動檢查，符合條件時直接發 LINE 給負責人。
          </div>

          <button onClick={async () => {
            showToast("發送中...","#6b7494");
            const sent = await checkAndNotify(tasks, reminders);
            if (sent > 0) { setLastNotify(new Date()); showToast(`📨 已發送 ${sent} 則 LINE 提醒`,"#00e5c3"); }
            else showToast("目前沒有符合條件的提醒","#6b7494");
          }} style={{ width:"100%", padding:"13px", borderRadius:12, border:`1px solid ${S.border}`, background:S.card, color:S.text, fontSize:13, fontWeight:600, cursor:"pointer", fontFamily:"inherit", marginTop:10 }}>
            📨 立即檢查並發送 LINE 提醒
          </button>
          {lastNotify && <div style={{ textAlign:"center", fontSize:11, color:S.muted, marginTop:8 }}>上次發送：{pad2(lastNotify.getHours())}:{pad2(lastNotify.getMinutes())}</div>}
        </div>
      )}

      {/* BOTTOM NAV */}
      <div style={{ position:"fixed", bottom:0, left:"50%", transform:"translateX(-50%)", width:"100%", maxWidth:480, background:S.surf, borderTop:`1px solid ${S.border}`, padding:"8px 0 18px", display:"flex", zIndex:50 }}>
        {[["dashboard","📊","任務"],["upload","📄","上傳"],["team","👥","成員"],["reminders","⏰","提醒"]].map(([id,ic,lb])=>(
          <div key={id} onClick={()=>setTab(id)} style={{ flex:1, display:"flex", flexDirection:"column", alignItems:"center", gap:3, cursor:"pointer", padding:"6px 0" }}>
            <div style={{ fontSize:22 }}>{ic}</div>
            <div style={{ fontSize:10, color:tab===id?S.accent:S.muted, fontWeight:tab===id?700:400 }}>{lb}</div>
          </div>
        ))}
      </div>

      {toast && <div style={{ position:"fixed", bottom:90, left:"50%", transform:"translateX(-50%)", background:toast.color, color:"#fff", padding:"10px 20px", borderRadius:20, fontSize:13, fontWeight:600, zIndex:999, whiteSpace:"nowrap", boxShadow:"0 4px 20px rgba(0,0,0,0.4)", animation:"fadeUp 0.3s ease" }}>{toast.msg}</div>}
    </div>
  );
}
