import { useState, useEffect, useRef, useCallback } from "react";
import * as mammoth from "mammoth";

// ── 固定團隊成員 ──────────────────────────────
const TEAM = ["小明", "怡君", "阿偉", "美玲", "志豪", "逸"];
const AVATAR_COLORS = ["#4f8cff","#00e5c3","#ff9f43","#ff5b79","#a78bfa","#34d399"];
const STORAGE_KEY   = "meetbot-tasks-v1";
const REMINDER_KEY  = "meetbot-reminders-v1";
const BACKEND_URL   = "https://meetbot-backend.onrender.com";

// ── 示範任務 ──────────────────────────────────
const DEMO_TASKS = [
  { id:1, title:"彙整各診所回報的處方數量，傳給主任", assignee:"怡君", deadline:"2026-03-21", meeting:"週會 3/21", done:false, urgent:true },
  { id:2, title:"確認 Q2 採購預算核准文件",           assignee:"小明", deadline:"2026-03-28", meeting:"週會 3/21", done:false, urgent:false },
  { id:3, title:"更新居民追蹤名單並上傳系統",         assignee:"阿偉", deadline:"2026-03-24", meeting:"週會 3/21", done:false, urgent:false },
  { id:4, title:"準備下週社區衛教活動講義",           assignee:"美玲", deadline:"2026-03-25", meeting:"週會 3/21", done:false, urgent:false },
  { id:5, title:"聯絡信義診所確認藥品庫存",           assignee:"小明", deadline:"2026-03-20", meeting:"週會 3/14", done:true,  urgent:false },
  { id:6, title:"整理上季健康檢查統計報告",           assignee:"志豪", deadline:"2026-03-22", meeting:"月度檢討 3/7", done:true, urgent:false },
];

// ── 提醒預設值 ────────────────────────────────
const DEFAULT_REMINDERS = {
  dayBefore:   { on: true,  days: 1,  hour: 9  },   // 截止前 N 天 HH:00
  hourBefore:  { on: true,  hours: 2             },   // 截止前 N 小時
  weeklyReport:{ on: false, weekday: 5, hour: 16 },   // 每週報告
  overdueAlert:{ on: true                         },   // 逾期立即提示
};

// ── 工具函式 ──────────────────────────────────
const today    = () => new Date().toISOString().slice(0,10);
const daysLeft = (d) => Math.ceil((new Date(d) - new Date(today())) / 86400000);
const memberColor = (n) => AVATAR_COLORS[TEAM.indexOf(n) % AVATAR_COLORS.length] || "#888";
const pad2 = (n) => String(n).padStart(2,"0");

function Avatar({ name, size=28 }) {
  return (
    <div style={{ width:size, height:size, borderRadius:"50%", background:memberColor(name),
      display:"flex", alignItems:"center", justifyContent:"center",
      fontSize:size*0.42, fontWeight:700, color:"#fff", flexShrink:0,
      fontFamily:"'Noto Sans TC',sans-serif" }}>{name[0]}</div>
  );
}

function DeadlineBadge({ deadline, done }) {
  if (done) return <span style={bdg("#00e5c3","rgba(0,229,195,0.12)")}>✓ 完成</span>;
  const d = daysLeft(deadline);
  if (d < 0)  return <span style={bdg("#ff5b79","rgba(255,91,121,0.12)")}>逾期 {Math.abs(d)} 天</span>;
  if (d === 0) return <span style={bdg("#ff5b79","rgba(255,91,121,0.12)")}>今天截止</span>;
  if (d <= 2)  return <span style={bdg("#ff9f43","rgba(255,159,67,0.12)")}>剩 {d} 天</span>;
  return <span style={bdg("#6b7494","rgba(107,116,148,0.12)")}>{deadline.slice(5).replace("-","/")} 截止</span>;
}
const bdg = (c,bg) => ({ fontSize:11, padding:"2px 8px", borderRadius:20, background:bg, color:c, fontWeight:600, whiteSpace:"nowrap" });

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
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tasks, reminders })
    });
    const data = await res.json();
    if (data.sent > 0) console.log(`📨 已發送 ${data.sent} 則 LINE 提醒`);
    return data.sent || 0;
  } catch (e) {
    console.error("LINE 提醒發送失敗:", e.message);
    return 0;
  }
}

// ── Toggle 元件 ───────────────────────────────
function Toggle({ on, onChange }) {
  return (
    <div onClick={onChange} style={{
      width:42, height:24, borderRadius:12, cursor:"pointer", position:"relative", flexShrink:0,
      background: on ? "var(--accent)" : "var(--border)", transition:"background 0.2s"
    }}>
      <div style={{
        position:"absolute", width:18, height:18, borderRadius:"50%", background:"#fff",
        top:3, left: on ? 21 : 3, transition:"left 0.2s", boxShadow:"0 1px 4px rgba(0,0,0,0.3)"
      }}/>
    </div>
  );
}

// ── Stepper 元件 ──────────────────────────────
function Stepper({ value, min, max, onChange, suffix="" }) {
  return (
    <div style={{ display:"flex", alignItems:"center", gap:8 }}>
      <div onClick={() => onChange(Math.max(min, value-1))} style={{
        width:28, height:28, borderRadius:8, background:"var(--card)", border:"1px solid var(--border)",
        display:"flex", alignItems:"center", justifyContent:"center", cursor:"pointer", fontSize:16, userSelect:"none"
      }}>−</div>
      <span style={{ fontSize:14, fontWeight:700, minWidth:28, textAlign:"center", fontFamily:"'DM Mono',monospace" }}>{value}</span>
      <div onClick={() => onChange(Math.min(max, value+1))} style={{
        width:28, height:28, borderRadius:8, background:"var(--card)", border:"1px solid var(--border)",
        display:"flex", alignItems:"center", justifyContent:"center", cursor:"pointer", fontSize:16, userSelect:"none"
      }}>+</div>
      {suffix && <span style={{ fontSize:12, color:"var(--muted)" }}>{suffix}</span>}
    </div>
  );
}

// ── 主元件 ────────────────────────────────────
export default function MeetBot() {
  const [tasks,       setTasks]       = useState([]);
  const [reminders,   setReminders]   = useState(DEFAULT_REMINDERS);
  const [loading,     setLoading]     = useState(true);
  const [syncing,     setSyncing]     = useState(false);
  const [lastSync,    setLastSync]    = useState(null);
  const [lastNotify,  setLastNotify]  = useState(null);
  const [tab,         setTab]         = useState("dashboard");
  const [filter,      setFilter]      = useState("all");
  const [memberFilter,setMemberFilter]= useState("all");
  const [parsing,     setParsing]     = useState(false);
  const [parseResult, setParseResult] = useState(null);
  const [docName,     setDocName]     = useState("");
  const [toast,       setToast]       = useState(null);
  const [savedPulse,  setSavedPulse]  = useState(false);
  const fileRef       = useRef();
  const isFirstRender = useRef(true);
  const isSaving      = useRef(false);
  const tasksRef      = useRef([]);
  const remindersRef  = useRef(DEFAULT_REMINDERS);

  const showToast = (msg, color="#4f8cff") => {
    setToast({ msg, color });
    setTimeout(() => setToast(null), 2800);
  };

  // ── 初始載入 ──
  const fetchAll = useCallback(async (quiet=false) => {
    if (!quiet) setLoading(true); else setSyncing(true);
    const [t, r] = await Promise.all([loadTasks(), loadReminders()]);
    setTasks(t);
    setReminders(r);
    tasksRef.current = t;
    remindersRef.current = r;
    setLastSync(new Date());
    if (!quiet) setLoading(false); else setSyncing(false);
  }, []);

  useEffect(() => {
    fetchAll(false);
    const poll = setInterval(() => { if (!isSaving.current) fetchAll(true); }, 15000);
    // 每小時整點自動檢查提醒
    const reminderCheck = setInterval(async () => {
      const sent = await checkAndNotify(tasksRef.current, remindersRef.current);
      if (sent > 0) {
        setLastNotify(new Date());
        showToast(`📨 已發送 ${sent} 則 LINE 提醒`,"#00e5c3");
      }
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
    setReminders(newR);
    remindersRef.current = newR;
    await saveReminders(newR);
    setSavedPulse(true);
    setTimeout(() => setSavedPulse(false), 1500);
  };

  const updateReminder = (key, patch) => {
    const newR = { ...reminders, [key]: { ...reminders[key], ...patch } };
    saveReminderSettings(newR);
  };

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
      deadline:t.deadline, meeting, done:false, urgent: daysLeft(t.deadline)<=1,
    }));
    setTasks(prev => [...newTasks,...prev]);
    setParseResult(null); setDocName(""); setTab("dashboard");
    showToast(`🔗 已同步 ${newTasks.length} 項任務給全團隊`);
  };

  const toggleDone = (id) => setTasks(prev => prev.map(t => t.id===id ? {...t,done:!t.done} : t));

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
      <style>{`@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;700&display=swap');*{box-sizing:border-box;margin:0;padding:0}@keyframes slide{0%{transform:translateX(-200%)}100%{transform:translateX(400%)}}`}</style>
      <div style={{ fontFamily:"'Noto Sans TC',sans-serif", background:"#080b12", color:"#e8eaf2", minHeight:"100vh", maxWidth:480, margin:"0 auto", display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:16 }}>
        <div style={{ fontSize:40 }}>📋</div>
        <div style={{ fontWeight:700, fontSize:16 }}>載入共用清單中...</div>
        <div style={{ width:160, height:3, background:"#232840", borderRadius:2, overflow:"hidden" }}>
          <div style={{ height:"100%", background:"linear-gradient(90deg,#4f8cff,#00e5c3)", animation:"slide 1.2s infinite", width:"50%" }}/>
        </div>
        <div style={{ fontSize:11, color:"#5a6285" }}>所有成員共用同一份資料</div>
      </div>
    </>
  );

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@300;400;500;700;900&family=DM+Mono:wght@400;500&display=swap');
        *{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
        body{background:#080b12}
        :root{
          --bg:#080b12;--surf:#10141e;--card:#181d2a;--border:#232840;
          --accent:#4f8cff;--green:#00e5c3;--orange:#ff9f43;--red:#ff5b79;
          --text:#e8eaf2;--muted:#5a6285;
        }
        @keyframes fadeUp{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
        @keyframes slide{0%{transform:translateX(-100%)}100%{transform:translateX(350%)}}
        @keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}
        @keyframes savedPop{0%{transform:scale(1)}50%{transform:scale(1.08)}100%{transform:scale(1)}}
        ::-webkit-scrollbar{width:4px}::-webkit-scrollbar-thumb{background:#232840;border-radius:2px}
      `}</style>

      <div style={{ fontFamily:"'Noto Sans TC',sans-serif", background:"var(--bg)", color:"var(--text)", minHeight:"100vh", maxWidth:480, margin:"0 auto", position:"relative" }}>

        {/* TOPBAR */}
        <div style={{ background:"var(--surf)", borderBottom:"1px solid var(--border)", padding:"12px 16px", display:"flex", alignItems:"center", justifyContent:"space-between", position:"sticky", top:0, zIndex:50 }}>
          <div style={{ display:"flex", alignItems:"center", gap:10 }}>
            <div style={{ width:32, height:32, borderRadius:10, background:"linear-gradient(135deg,#4f8cff,#00e5c3)", display:"flex", alignItems:"center", justifyContent:"center", fontSize:16 }}>📋</div>
            <div>
              <div style={{ fontWeight:700, fontSize:15 }}>MeetBot</div>
              <div style={{ fontSize:10, color:"var(--muted)" }}>會議任務追蹤系統</div>
            </div>
          </div>
          <div style={{ display:"flex", flexDirection:"column", alignItems:"flex-end", gap:4 }}>
            <div style={{ display:"flex", gap:5 }}>
              {urgentCount>0 && <div style={{ background:"rgba(255,91,121,0.15)", border:"1px solid var(--red)", color:"var(--red)", fontSize:10, fontWeight:700, padding:"2px 7px", borderRadius:20 }}>⚡{urgentCount}</div>}
              <div style={{ background:"rgba(0,229,195,0.1)", border:"1px solid rgba(0,229,195,0.3)", color:"var(--green)", fontSize:10, fontWeight:700, padding:"2px 7px", borderRadius:20 }}>{pct}%</div>
            </div>
            <div style={{ display:"flex", alignItems:"center", gap:4, fontSize:10, color: syncing?"var(--accent)":"var(--muted)" }}>
              <div style={{ width:6, height:6, borderRadius:"50%", background: syncing?"var(--accent)":"var(--green)", animation: syncing?"pulse 1s infinite":"none" }}/>
              {syncing ? "同步中..." : syncLabel}
            </div>
          </div>
        </div>

        {/* TABS */}
        <div style={{ display:"flex", background:"var(--surf)", borderBottom:"1px solid var(--border)", overflowX:"auto", scrollbarWidth:"none" }}>
          {[["dashboard","📊","任務"],["upload","📄","上傳"],["team","👥","成員"],["reminders","⏰","提醒"]].map(([id,ic,lb]) => (
            <div key={id} onClick={() => setTab(id)} style={{
              flex:1, minWidth:64, textAlign:"center", padding:"10px 4px 8px", fontSize:11, cursor:"pointer",
              color: tab===id ? "var(--accent)" : "var(--muted)",
              borderBottom: tab===id ? "2px solid var(--accent)" : "2px solid transparent",
              fontWeight: tab===id ? 700 : 400, transition:"all 0.2s", whiteSpace:"nowrap"
            }}><div style={{ fontSize:18, marginBottom:2 }}>{ic}</div>{lb}</div>
          ))}
        </div>

        {/* ══ 儀表板 ══ */}
        {tab==="dashboard" && (
          <div style={{ padding:"14px 14px 100px" }}>
            <div style={{ background:"rgba(79,140,255,0.08)", border:"1px solid rgba(79,140,255,0.25)", borderRadius:12, padding:"10px 14px", marginBottom:12, display:"flex", alignItems:"center", gap:10 }}>
              <div style={{ fontSize:18 }}>🔗</div>
              <div>
                <div style={{ fontSize:12, fontWeight:600 }}>共用清單・即時同步</div>
                <div style={{ fontSize:11, color:"var(--muted)" }}>所有成員共用同一份資料，每 15 秒自動更新</div>
              </div>
            </div>

            <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr 1fr", gap:8, marginBottom:12 }}>
              {[{num:pendingCount,label:"待完成",color:"var(--accent)"},{num:doneCount,label:"已完成",color:"var(--green)"},{num:urgentCount,label:"緊急",color:"var(--red)"}].map(s=>(
                <div key={s.label} style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:12, padding:"12px 8px", textAlign:"center" }}>
                  <div style={{ fontSize:26, fontWeight:900, fontFamily:"'DM Mono',monospace", color:s.color, lineHeight:1 }}>{s.num}</div>
                  <div style={{ fontSize:10, color:"var(--muted)", marginTop:5 }}>{s.label}</div>
                </div>
              ))}
            </div>

            <div style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:12, padding:"12px 14px", marginBottom:12 }}>
              <div style={{ display:"flex", justifyContent:"space-between", fontSize:12, marginBottom:8 }}>
                <span style={{ color:"var(--muted)" }}>整體完成進度</span>
                <span style={{ fontWeight:700, color:"var(--green)", fontFamily:"'DM Mono',monospace" }}>{doneCount}/{tasks.length}</span>
              </div>
              <div style={{ height:6, background:"var(--border)", borderRadius:3, overflow:"hidden" }}>
                <div style={{ height:"100%", width:`${pct}%`, background:"linear-gradient(90deg,var(--accent),var(--green))", borderRadius:3, transition:"width 0.6s ease" }}/>
              </div>
            </div>

            {/* 即將到來的提醒預覽 */}
            {nextReminders.length>0 && (
              <div style={{ background:"rgba(255,159,67,0.06)", border:"1px solid rgba(255,159,67,0.2)", borderRadius:12, padding:"12px 14px", marginBottom:12 }}>
                <div style={{ fontSize:11, fontWeight:700, color:"var(--orange)", marginBottom:8, letterSpacing:0.5 }}>⏰ 即將觸發的提醒</div>
                {nextReminders.slice(0,3).map((r,i)=>(
                  <div key={i} style={{ display:"flex", justifyContent:"space-between", fontSize:11, color:"var(--muted)", paddingBottom: i<2?"6px 0":0, borderBottom: i<Math.min(nextReminders.length,3)-1?"1px solid var(--border)":0, marginBottom: i<2?6:0 }}>
                    <span style={{ overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap", maxWidth:"55%" }}>• {r.task.title}</span>
                    <span style={{ color:"var(--orange)", fontWeight:600, whiteSpace:"nowrap" }}>{r.type} · {`${pad2(r.at.getMonth()+1)}/${pad2(r.at.getDate())} ${pad2(r.at.getHours())}:00`}</span>
                  </div>
                ))}
              </div>
            )}

            {/* 篩選 */}
            <div style={{ display:"flex", gap:6, marginBottom:10, overflowX:"auto", paddingBottom:4, scrollbarWidth:"none" }}>
              {[["all","全部"],["pending","待辦"],["urgent","緊急"],["done","完成"]].map(([k,l])=>(
                <div key={k} onClick={()=>setFilter(k)} style={{ padding:"5px 12px", borderRadius:20, fontSize:12, fontWeight:600, cursor:"pointer", whiteSpace:"nowrap", background:filter===k?"var(--accent)":"var(--card)", color:filter===k?"#fff":"var(--muted)", border:`1px solid ${filter===k?"var(--accent)":"var(--border)"}`, transition:"all 0.2s" }}>{l}</div>
              ))}
              <div style={{ width:1, background:"var(--border)", margin:"0 2px", flexShrink:0 }}/>
              {["all",...TEAM].map(m=>(
                <div key={m} onClick={()=>setMemberFilter(m)} style={{ padding:"5px 12px", borderRadius:20, fontSize:12, cursor:"pointer", whiteSpace:"nowrap", background:memberFilter===m?memberColor(m):"var(--card)", color:memberFilter===m?"#fff":"var(--muted)", border:`1px solid ${memberFilter===m?memberColor(m):"var(--border)"}`, transition:"all 0.2s", fontWeight:memberFilter===m?700:400 }}>{m==="all"?"全員":m}</div>
              ))}
            </div>

            {filtered.length===0 && <div style={{ textAlign:"center", color:"var(--muted)", padding:"40px 0", fontSize:13 }}>沒有符合的任務</div>}
            {filtered.map(t=>(
              <div key={t.id} onClick={()=>toggleDone(t.id)} style={{ background:t.done?"rgba(24,29,42,0.5)":"var(--card)", border:`1px solid ${t.urgent&&!t.done?"rgba(255,91,121,0.3)":"var(--border)"}`, borderRadius:12, padding:"13px 14px", marginBottom:8, display:"flex", gap:12, alignItems:"flex-start", cursor:"pointer", opacity:t.done?0.55:1, transition:"all 0.2s" }}>
                <div style={{ width:22, height:22, borderRadius:"50%", flexShrink:0, marginTop:1, border:`2px solid ${t.done?"var(--green)":t.urgent?"var(--red)":"var(--border)"}`, background:t.done?"var(--green)":"transparent", display:"flex", alignItems:"center", justifyContent:"center", fontSize:11, color:"#fff", transition:"all 0.2s" }}>{t.done?"✓":""}</div>
                <div style={{ flex:1, minWidth:0 }}>
                  <div style={{ fontSize:14, fontWeight:500, lineHeight:1.5, marginBottom:6, textDecoration:t.done?"line-through":"none", color:t.done?"var(--muted)":"var(--text)" }}>{t.title}</div>
                  <div style={{ display:"flex", gap:6, flexWrap:"wrap", alignItems:"center" }}>
                    <div style={{ display:"flex", alignItems:"center", gap:4 }}><Avatar name={t.assignee} size={18}/><span style={{ fontSize:11, color:"var(--muted)" }}>{t.assignee}</span></div>
                    <DeadlineBadge deadline={t.deadline} done={t.done}/>
                    {t.urgent&&!t.done && <span style={bdg("var(--red)","rgba(255,91,121,0.1)")}>⚡ 緊急</span>}
                  </div>
                  <div style={{ fontSize:10, color:"var(--muted)", marginTop:5 }}>📋 {t.meeting}</div>
                </div>
              </div>
            ))}
            <div onClick={()=>fetchAll(true)} style={{ textAlign:"center", padding:"16px 0", fontSize:12, color:"var(--muted)", cursor:"pointer" }}>↻ 手動重新整理</div>
          </div>
        )}

        {/* ══ 上傳會議 ══ */}
        {tab==="upload" && (
          <div style={{ padding:"16px 14px 100px" }}>
            <div onClick={()=>!parsing&&fileRef.current.click()} style={{ border:`2px dashed ${parsing?"var(--accent)":"var(--border)"}`, borderRadius:14, padding:"32px 20px", textAlign:"center", cursor:"pointer", background:"var(--card)", marginBottom:14, transition:"border-color 0.2s" }}>
              <input ref={fileRef} type="file" accept=".docx" onChange={handleFile} style={{ display:"none" }}/>
              {parsing ? (<>
                <div style={{ fontSize:32, marginBottom:10 }}>⚙️</div>
                <div style={{ fontWeight:700, marginBottom:4 }}>AI 解析中...</div>
                <div style={{ fontSize:12, color:"var(--muted)" }}>正在從會議紀錄提取任務</div>
                <div style={{ marginTop:14, height:3, background:"var(--border)", borderRadius:2, overflow:"hidden" }}>
                  <div style={{ height:"100%", background:"linear-gradient(90deg,var(--accent),var(--green))", animation:"slide 1.2s infinite", width:"40%" }}/>
                </div>
              </>) : (<>
                <div style={{ fontSize:40, marginBottom:10 }}>📄</div>
                <div style={{ fontWeight:700, marginBottom:4 }}>{docName||"點擊上傳 .docx 會議紀錄"}</div>
                <div style={{ fontSize:12, color:"var(--muted)" }}>AI 自動解析任務、負責人、截止日期</div>
              </>)}
            </div>
            {parseResult && (
              <div style={{ animation:"fadeUp 0.4s ease" }}>
                <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:10, fontSize:13, color:"var(--green)", fontWeight:700 }}>✦ 找到 {parseResult.length} 項任務，確認後同步給全團隊</div>
                {parseResult.map((t,i)=>(
                  <div key={i} style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:12, padding:"12px 14px", marginBottom:8 }}>
                    <div style={{ fontSize:14, fontWeight:500, marginBottom:6 }}>{t.title}</div>
                    <div style={{ display:"flex", gap:8, flexWrap:"wrap" }}>
                      <div style={{ display:"flex", alignItems:"center", gap:4 }}><Avatar name={t.assignee} size={18}/><span style={{ fontSize:11, color:"var(--muted)" }}>{t.assignee}</span></div>
                      <span style={bdg("var(--orange)","rgba(255,159,67,0.1)")}>📅 {t.deadline}</span>
                    </div>
                  </div>
                ))}
                <button onClick={confirmTasks} style={{ width:"100%", padding:"14px", borderRadius:12, border:"none", background:"linear-gradient(135deg,var(--green),#00b89c)", color:"#fff", fontSize:14, fontWeight:700, cursor:"pointer", fontFamily:"inherit", boxShadow:"0 4px 20px rgba(0,229,195,0.3)", marginTop:4 }}>🔗 同步給全團隊</button>
              </div>
            )}
            {!parsing&&!parseResult && (
              <div style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:12, padding:"14px", fontSize:12, color:"var(--muted)", lineHeight:1.8 }}>
                <div style={{ fontWeight:700, color:"var(--text)", marginBottom:6 }}>📌 使用說明</div>
                上傳包含會議決議事項的 Word 文件<br/>AI 會自動辨識「負責人」「任務」「截止時間」<br/>確認後立即同步給所有團隊成員
              </div>
            )}
          </div>
        )}

        {/* ══ 成員 ══ */}
        {tab==="team" && (
          <div style={{ padding:"16px 14px 100px" }}>
            <div style={{ fontSize:11, color:"var(--muted)", fontWeight:700, letterSpacing:1.5, textTransform:"uppercase", marginBottom:12 }}>成員完成率（即時）</div>
            {memberStats.length===0 && <div style={{ color:"var(--muted)", fontSize:13, textAlign:"center", padding:30 }}>尚無任務資料</div>}
            {memberStats.map(m=>(
              <div key={m.name} style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:12, padding:"14px", marginBottom:8 }}>
                <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:10 }}>
                  <div style={{ display:"flex", alignItems:"center", gap:10 }}>
                    <Avatar name={m.name} size={36}/>
                    <div><div style={{ fontWeight:700, fontSize:14 }}>{m.name}</div><div style={{ fontSize:11, color:"var(--muted)" }}>{m.done}/{m.total} 項完成</div></div>
                  </div>
                  <div style={{ fontFamily:"'DM Mono',monospace", fontSize:22, fontWeight:700, color:m.pct===100?"var(--green)":m.pct>=50?"var(--accent)":"var(--orange)" }}>{m.pct}%</div>
                </div>
                <div style={{ height:5, background:"var(--border)", borderRadius:3, overflow:"hidden" }}>
                  <div style={{ height:"100%", width:`${m.pct}%`, borderRadius:3, background:`linear-gradient(90deg,${memberColor(m.name)},${memberColor(m.name)}aa)`, transition:"width 0.6s" }}/>
                </div>
                <div style={{ marginTop:10 }}>
                  {tasks.filter(t=>t.assignee===m.name&&!t.done).slice(0,2).map(t=>(
                    <div key={t.id} style={{ fontSize:11, color:"var(--muted)", padding:"5px 0", borderTop:"1px solid var(--border)", display:"flex", justifyContent:"space-between", gap:8 }}>
                      <span style={{ overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}>• {t.title}</span>
                      <DeadlineBadge deadline={t.deadline} done={false}/>
                    </div>
                  ))}
                </div>
              </div>
            ))}
            <div style={{ fontSize:11, color:"var(--muted)", fontWeight:700, letterSpacing:1.5, textTransform:"uppercase", margin:"20px 0 12px" }}>固定成員</div>
            <div style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:12, padding:"14px" }}>
              <div style={{ display:"flex", flexWrap:"wrap", gap:10 }}>
                {TEAM.map(name=>(
                  <div key={name} style={{ display:"flex", alignItems:"center", gap:6, background:"var(--surf)", borderRadius:20, padding:"5px 12px 5px 6px" }}>
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

            {/* 儲存指示 */}
            <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:14 }}>
              <div style={{ fontSize:11, color:"var(--muted)", fontWeight:700, letterSpacing:1.5, textTransform:"uppercase" }}>提醒規則設定</div>
              <div style={{ fontSize:11, color: savedPulse?"var(--green)":"var(--muted)", fontWeight:600, transition:"color 0.3s", animation: savedPulse?"savedPop 0.4s ease":undefined }}>
                {savedPulse ? "✓ 已儲存" : "修改後自動儲存"}
              </div>
            </div>

            {/* ─ 規則 1：截止前 N 天 */}
            <div style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:12, padding:"16px", marginBottom:10 }}>
              <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:reminders.dayBefore.on?14:0 }}>
                <div style={{ display:"flex", alignItems:"center", gap:10 }}>
                  <div style={{ width:36, height:36, borderRadius:10, background:"rgba(79,140,255,0.12)", display:"flex", alignItems:"center", justifyContent:"center", fontSize:18 }}>📅</div>
                  <div>
                    <div style={{ fontSize:14, fontWeight:600 }}>截止日前提醒</div>
                    <div style={{ fontSize:11, color:"var(--muted)" }}>在截止日的前幾天早上提醒</div>
                  </div>
                </div>
                <Toggle on={reminders.dayBefore.on} onChange={()=>updateReminder("dayBefore",{on:!reminders.dayBefore.on})}/>
              </div>
              {reminders.dayBefore.on && (
                <div style={{ display:"flex", flexDirection:"column", gap:12, paddingTop:14, borderTop:"1px solid var(--border)" }}>
                  <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between" }}>
                    <span style={{ fontSize:13, color:"var(--muted)" }}>提前幾天</span>
                    <Stepper value={reminders.dayBefore.days} min={1} max={7} suffix="天前" onChange={v=>updateReminder("dayBefore",{days:v})}/>
                  </div>
                  <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between" }}>
                    <span style={{ fontSize:13, color:"var(--muted)" }}>提醒時間</span>
                    <div style={{ display:"flex", gap:6, flexWrap:"wrap", justifyContent:"flex-end" }}>
                      {[7,8,9,10,12,14].map(h=>(
                        <div key={h} onClick={()=>updateReminder("dayBefore",{hour:h})} style={{ padding:"4px 10px", borderRadius:8, fontSize:12, cursor:"pointer", fontFamily:"'DM Mono',monospace", background:reminders.dayBefore.hour===h?"var(--accent)":"var(--surf)", color:reminders.dayBefore.hour===h?"#fff":"var(--muted)", border:`1px solid ${reminders.dayBefore.hour===h?"var(--accent)":"var(--border)"}`, transition:"all 0.2s" }}>{pad2(h)}:00</div>
                      ))}
                    </div>
                  </div>
                  <div style={{ background:"var(--surf)", borderRadius:8, padding:"10px 12px", fontSize:12, color:"var(--muted)" }}>
                    例：任務截止日為週五，將在<span style={{ color:"var(--accent)", fontWeight:600 }}>週{WEEKDAYS[(5-reminders.dayBefore.days+7)%7]} {pad2(reminders.dayBefore.hour)}:00</span> 提醒負責人
                  </div>
                </div>
              )}
            </div>

            {/* ─ 規則 2：截止前 N 小時 */}
            <div style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:12, padding:"16px", marginBottom:10 }}>
              <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:reminders.hourBefore.on?14:0 }}>
                <div style={{ display:"flex", alignItems:"center", gap:10 }}>
                  <div style={{ width:36, height:36, borderRadius:10, background:"rgba(255,159,67,0.12)", display:"flex", alignItems:"center", justifyContent:"center", fontSize:18 }}>⏰</div>
                  <div>
                    <div style={{ fontSize:14, fontWeight:600 }}>截止前緊急提醒</div>
                    <div style={{ fontSize:11, color:"var(--muted)" }}>截止前幾小時發出最後警示</div>
                  </div>
                </div>
                <Toggle on={reminders.hourBefore.on} onChange={()=>updateReminder("hourBefore",{on:!reminders.hourBefore.on})}/>
              </div>
              {reminders.hourBefore.on && (
                <div style={{ paddingTop:14, borderTop:"1px solid var(--border)" }}>
                  <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between" }}>
                    <span style={{ fontSize:13, color:"var(--muted)" }}>提前幾小時</span>
                    <Stepper value={reminders.hourBefore.hours} min={1} max={24} suffix="小時前" onChange={v=>updateReminder("hourBefore",{hours:v})}/>
                  </div>
                </div>
              )}
            </div>

            {/* ─ 規則 3：逾期提示 */}
            <div style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:12, padding:"16px", marginBottom:10 }}>
              <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between" }}>
                <div style={{ display:"flex", alignItems:"center", gap:10 }}>
                  <div style={{ width:36, height:36, borderRadius:10, background:"rgba(255,91,121,0.12)", display:"flex", alignItems:"center", justifyContent:"center", fontSize:18 }}>🚨</div>
                  <div>
                    <div style={{ fontSize:14, fontWeight:600 }}>逾期高亮提示</div>
                    <div style={{ fontSize:11, color:"var(--muted)" }}>逾期任務在儀表板醒目標示</div>
                  </div>
                </div>
                <Toggle on={reminders.overdueAlert.on} onChange={()=>updateReminder("overdueAlert",{on:!reminders.overdueAlert.on})}/>
              </div>
            </div>

            {/* ─ 規則 4：每週完成率報告 */}
            <div style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:12, padding:"16px", marginBottom:10 }}>
              <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:reminders.weeklyReport.on?14:0 }}>
                <div style={{ display:"flex", alignItems:"center", gap:10 }}>
                  <div style={{ width:36, height:36, borderRadius:10, background:"rgba(0,229,195,0.12)", display:"flex", alignItems:"center", justifyContent:"center", fontSize:18 }}>📊</div>
                  <div>
                    <div style={{ fontSize:14, fontWeight:600 }}>每週完成率報告</div>
                    <div style={{ fontSize:11, color:"var(--muted)" }}>固定時間推播團隊整體進度</div>
                  </div>
                </div>
                <Toggle on={reminders.weeklyReport.on} onChange={()=>updateReminder("weeklyReport",{on:!reminders.weeklyReport.on})}/>
              </div>
              {reminders.weeklyReport.on && (
                <div style={{ display:"flex", flexDirection:"column", gap:12, paddingTop:14, borderTop:"1px solid var(--border)" }}>
                  <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between" }}>
                    <span style={{ fontSize:13, color:"var(--muted)" }}>每週幾</span>
                    <div style={{ display:"flex", gap:5 }}>
                      {[1,2,3,4,5].map(d=>(
                        <div key={d} onClick={()=>updateReminder("weeklyReport",{weekday:d})} style={{ width:34, height:34, borderRadius:8, display:"flex", alignItems:"center", justifyContent:"center", fontSize:13, cursor:"pointer", background:reminders.weeklyReport.weekday===d?"var(--accent)":"var(--surf)", color:reminders.weeklyReport.weekday===d?"#fff":"var(--muted)", border:`1px solid ${reminders.weeklyReport.weekday===d?"var(--accent)":"var(--border)"}`, transition:"all 0.2s" }}>週{WEEKDAYS[d]}</div>
                      ))}
                    </div>
                  </div>
                  <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between" }}>
                    <span style={{ fontSize:13, color:"var(--muted)" }}>發送時間</span>
                    <div style={{ display:"flex", gap:6 }}>
                      {[9,12,14,16,17,18].map(h=>(
                        <div key={h} onClick={()=>updateReminder("weeklyReport",{hour:h})} style={{ padding:"4px 10px", borderRadius:8, fontSize:12, cursor:"pointer", fontFamily:"'DM Mono',monospace", background:reminders.weeklyReport.hour===h?"var(--green)":"var(--surf)", color:reminders.weeklyReport.hour===h?"#fff":"var(--muted)", border:`1px solid ${reminders.weeklyReport.hour===h?"var(--green)":"var(--border)"}`, transition:"all 0.2s" }}>{pad2(h)}:00</div>
                      ))}
                    </div>
                  </div>
                  <div style={{ background:"var(--surf)", borderRadius:8, padding:"10px 12px", fontSize:12, color:"var(--muted)" }}>
                    每週{WEEKDAYS[reminders.weeklyReport.weekday]} <span style={{ color:"var(--green)", fontWeight:600 }}>{pad2(reminders.weeklyReport.hour)}:00</span> 推播完成率摘要給全團隊
                  </div>
                </div>
              )}
            </div>

            {/* 下次提醒預覽 */}
            {nextReminders.length>0 && (
              <div style={{ marginTop:20 }}>
                <div style={{ fontSize:11, color:"var(--muted)", fontWeight:700, letterSpacing:1.5, textTransform:"uppercase", marginBottom:10 }}>依目前設定，即將提醒</div>
                {nextReminders.map((r,i)=>(
                  <div key={i} style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:10, padding:"11px 14px", marginBottom:6, display:"flex", alignItems:"center", justifyContent:"space-between", gap:10 }}>
                    <div style={{ flex:1, minWidth:0 }}>
                      <div style={{ fontSize:12, fontWeight:500, overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}>{r.task.title}</div>
                      <div style={{ fontSize:11, color:"var(--muted)", marginTop:3 }}>{r.task.assignee} · {r.type}</div>
                    </div>
                    <div style={{ fontSize:11, color:"var(--orange)", fontWeight:700, fontFamily:"'DM Mono',monospace", whiteSpace:"nowrap" }}>
                      {`${pad2(r.at.getMonth()+1)}/${pad2(r.at.getDate())} ${pad2(r.at.getHours())}:00`}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* 說明卡 */}
            <div style={{ background:"rgba(79,140,255,0.06)", border:"1px solid rgba(79,140,255,0.2)", borderRadius:12, padding:"14px", marginTop:16, fontSize:12, color:"var(--muted)", lineHeight:1.8 }}>
              <div style={{ fontWeight:700, color:"var(--text)", marginBottom:6 }}>💡 自動提醒說明</div>
              系統每小時整點自動檢查，符合條件時直接發 LINE 給負責人，不需要手動操作。
            </div>

            {/* 手動測試按鈕 */}
            <button onClick={async () => {
              showToast("發送中...","#6b7494");
              const sent = await checkAndNotify(tasks, reminders);
              if (sent > 0) {
                setLastNotify(new Date());
                showToast(`📨 已發送 ${sent} 則 LINE 提醒`,"#00e5c3");
              } else {
                showToast("目前沒有符合條件的提醒","#6b7494");
              }
            }} style={{ width:"100%", padding:"13px", borderRadius:12, border:"none", background:"var(--card)", color:"var(--text)", fontSize:13, fontWeight:600, cursor:"pointer", fontFamily:"inherit", border:"1px solid var(--border)", marginTop:10 }}>
              📨 立即檢查並發送 LINE 提醒
            </button>
            {lastNotify && <div style={{ textAlign:"center", fontSize:11, color:"var(--muted)", marginTop:8 }}>上次發送：{pad2(lastNotify.getHours())}:{pad2(lastNotify.getMinutes())}</div>}
          </div>
        )}

        {/* BOTTOM NAV */}
        <div style={{ position:"fixed", bottom:0, left:"50%", transform:"translateX(-50%)", width:"100%", maxWidth:480, background:"var(--surf)", borderTop:"1px solid var(--border)", padding:"8px 0 18px", display:"flex", zIndex:50 }}>
          {[["dashboard","📊","任務"],["upload","📄","上傳"],["team","👥","成員"],["reminders","⏰","提醒"]].map(([id,ic,lb])=>(
            <div key={id} onClick={()=>setTab(id)} style={{ flex:1, display:"flex", flexDirection:"column", alignItems:"center", gap:3, cursor:"pointer", padding:"6px 0" }}>
              <div style={{ fontSize:22 }}>{ic}</div>
              <div style={{ fontSize:10, color:tab===id?"var(--accent)":"var(--muted)", fontWeight:tab===id?700:400 }}>{lb}</div>
            </div>
          ))}
        </div>

        {/* TOAST */}
        {toast && (
          <div style={{ position:"fixed", bottom:90, left:"50%", transform:"translateX(-50%)", background:toast.color, color:"#fff", padding:"10px 20px", borderRadius:20, fontSize:13, fontWeight:600, zIndex:999, whiteSpace:"nowrap", boxShadow:"0 4px 20px rgba(0,0,0,0.4)", animation:"fadeUp 0.3s ease" }}>{toast.msg}</div>
        )}
      </div>
    </>
  );
}
