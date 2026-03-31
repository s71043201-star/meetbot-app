import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import * as mammoth from "mammoth";

// ── 固定團隊成員 ──────────────────────────────
const TEAM = ["黃琴茹","蔡蕙芳","吳承儒","張鈺微","吳亞璇","許雅淇","戴豐逸","陳佩研"];
const AVATAR_COLORS = ["#4f8cff","#00e5c3","#ff9f43","#ff5b79","#a78bfa","#34d399","#f97316","#06b6d4"];
const ADMINS = ["蔡蕙芳", "戴豐逸"];
const SPECIALISTS = ["許雅淇"];
const TEAM_LEADS = ["黃琴茹", "吳承儒"];
const OFFICERS = ["張鈺微", "陳佩研"];
const ADMIN_PASSWORDS = { "戴豐逸": "041222", "蔡蕙芳": "000000" };
const getUserRole = (name) => ADMINS.includes(name) ? "admin" : SPECIALISTS.includes(name) ? "specialist" : "member";
const getRoleLabel = (name) => ADMINS.includes(name) ? "管理者" : SPECIALISTS.includes(name) ? "工作派發者" : TEAM_LEADS.includes(name) ? "組長" : OFFICERS.includes(name) ? "專員" : "組員";

// ── 中會議室會前準備模板（分區） ─────────────────
const PREP_TEMPLATE = [
  { section:"電腦視訊設備架設及測試", icon:"🖥️", items:[
    "電腦連線正常","投影機開啟並連線至電腦","架設視訊鏡頭用腳架",
    "架設視訊鏡頭並測試連線正常","投影幕已開啟","視訊畫面導出外部測試正常",
    "電腦畫面連線至大會議室電視與主席桌螢幕"
  ]},
  { section:"音訊設備架設及測試", icon:"🔊", items:[
    "將喇叭連線至電腦並確認外部輸入音量正常","會議室麥克風皆裝好電池並可正常開啟",
    "確認會議室中現場麥克風音量","連線至WEBEX測試線上會議室音量"
  ]},
  { section:"確認與會人員出席狀況及聯絡", icon:"📞", items:[
    "印製簽到單（前一天準備好）","於會議期間於會議室待命",
    "會前10分鐘聯絡尚未到達的出席者","及時彙報名單變動狀況"
  ]},
  { section:"報到及引導與會人員入座＋議程準備", icon:"🚪", items:[
    "測試簽到處用筆正常","引導與會人員簽到並入座",
    "於會議室入口待命引導入場","印製當日會議議程並清點數量正確"
  ]},
  { section:"拍照記錄＋會議其他設備準備", icon:"📸", items:[
    "「健康台灣深耕計畫」布條懸掛與固定","錄音筆、簡報筆準備並測試正常",
    "桌牌準備（前一天準備好）","便當、餐巾紙等準備（如有需要）","會議中拍照記錄"
  ]},
  { section:"會後設備關閉", icon:"🔌", items:[
    "麥克風電池移除並歸位","投影幕已升起","喇叭已關閉並歸位",
    "投影機已關閉","空調開關已關閉","視訊機器、電腦已關閉並歸位"
  ]},
  { section:"儲存檔案＋設備收回＋場地復原", icon:"📦", items:[
    "會議電子檔下載至隨身碟留存","簡報筆、錄音筆關機並歸位",
    "桌牌、簽到單回收","腳架收好並歸位","場地復原，檢查遺落物品",
    "關電燈 + 確認會議室已淨空"
  ]},
];
const BACKEND_URL   = "https://meetbot-backend.onrender.com";
const FB_BASE       = "https://meetbot-ede53-default-rtdb.asia-southeast1.firebasedatabase.app/meetbot";
const MEETINGS_FB   = FB_BASE + "/meetings";
const SLACK_WEBHOOK_KEY = "meetbot-slack-webhook";

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
// 多人指派工具
const getAssignees = (t) => (t.assignee || "").split(",").map(s=>s.trim()).filter(Boolean);
const hasAssignee = (t, name) => getAssignees(t).includes(name);


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

// ── 優先等級設定 ─────────────────────────────
const PRIORITIES = [
  { key:"critical", label:"緊急", color:"#ff5b79", bg:"rgba(255,91,121,0.12)" },
  { key:"high",     label:"高",   color:"#ff9f43", bg:"rgba(255,159,67,0.12)" },
  { key:"medium",   label:"中",   color:"#4f8cff", bg:"rgba(79,140,255,0.12)" },
  { key:"low",      label:"低",   color:"#6b7494", bg:"rgba(107,116,148,0.12)" },
];
const PRIORITY_MAP = Object.fromEntries(PRIORITIES.map(p => [p.key, p]));
function PriorityBadge({ priority }) {
  const p = PRIORITY_MAP[priority];
  if (!p) return null;
  return <span style={bdg(p.color, p.bg)}>{p.label}</span>;
}
// 舊資料遷移：urgent → priority
function migrateTask(t) {
  if (t.priority) return t;
  return { ...t, priority: t.urgent ? "critical" : "medium", deletedAt: t.deletedAt || null };
}

// ── DeadlineBadge ─────────────────────────────
function DeadlineBadge({ deadline, done }) {
  if (done) return <span style={bdg("#00e5c3","rgba(0,229,195,0.12)")}>完成</span>;
  if (!deadline) return <span style={bdg("#6b7494","rgba(107,116,148,0.12)")}>例行任務</span>;
  const d = daysLeft(deadline);
  if (d < 0)   return <span style={bdg("#ff5b79","rgba(255,91,121,0.12)")}>逾期 {Math.abs(d)} 天</span>;
  if (d === 0) return <span style={bdg("#ff5b79","rgba(255,91,121,0.12)")}>今天截止</span>;
  if (d <= 2)  return <span style={bdg("#ff9f43","rgba(255,159,67,0.12)")}>剩 {d} 天</span>;
  return <span style={bdg("#6b7494","rgba(107,116,148,0.12)")}>{deadline.slice(5).replace("-","/")} 截止</span>;
}
const bdg = (c,bg) => ({ fontSize:14, padding:"2px 8px", borderRadius:20, background:bg, color:c, fontWeight:600, whiteSpace:"nowrap" });

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
        display:"flex", alignItems:"center", justifyContent:"center", cursor:"pointer", fontSize:18, userSelect:"none"
      }}>−</div>
      <span style={{ fontSize:18, fontWeight:700, minWidth:32, textAlign:"center", fontFamily:"'DM Mono',monospace" }}>{value}</span>
      <div onClick={() => onChange(Math.min(max, value+1))} style={{
        width:34, height:34, borderRadius:8, background:"var(--card)", border:"1px solid var(--border)",
        display:"flex", alignItems:"center", justifyContent:"center", cursor:"pointer", fontSize:18, userSelect:"none"
      }}>+</div>
      {suffix && <span style={{ fontSize:15, color:"var(--muted)" }}>{suffix}</span>}
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
        <div style={{ fontSize:22, fontWeight:700 }}>📝 工作進度備註</div>
        <div style={{
          background:"var(--surf)", borderRadius:10, padding:"12px 14px",
          fontSize:15, color:"var(--muted)", lineHeight:1.6
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
            color:"var(--text)", fontSize:18, lineHeight:1.7, padding:"14px",
            resize:"vertical", minHeight:120, fontFamily:"'Noto Sans TC',sans-serif",
            outline:"none"
          }}
        />
        {task.progressNoteTime && (
          <div style={{ fontSize:15, color:"var(--muted)" }}>
            上次備註時間：{task.progressNoteTime}
          </div>
        )}
        <div style={{ display:"flex", gap:10 }}>
          <button onClick={onClose} style={{
            flex:1, padding:"13px", borderRadius:10, border:"1px solid var(--border)",
            background:"var(--surf)", color:"var(--muted)", fontSize:15, fontWeight:600,
            cursor:"pointer", fontFamily:"inherit"
          }}>取消</button>
          <button onClick={() => onSave(note)} style={{
            flex:2, padding:"13px", borderRadius:10, border:"none",
            background:"linear-gradient(135deg,var(--accent),#00b89c)", color:"#fff",
            fontSize:15, fontWeight:700, cursor:"pointer", fontFamily:"inherit"
          }}>儲存備註</button>
        </div>
      </div>
    </div>
  );
}

// ── 任務編輯 Modal ───────────────────────────────
function TaskEditModal({ task, onSave, onDelete, onNotify, onClose, canSetPriority, currentUser, canEdit, allTasks, onConvertToRoutine }) {
  const [form, setForm] = useState({
    title: task.title || "",
    assignees: (task.assignee || "").split(",").map(s=>s.trim()).filter(Boolean),
    deadline: task.deadline || "",
    meeting: task.meeting || "",
    priority: task.priority || "medium",
    subtasks: task.subtasks || [],
    comments: task.comments || [],
    dependsOn: task.dependsOn || [],
  });
  const [newSubtask, setNewSubtask] = useState("");
  const [commentText, setCommentText] = useState("");
  const [editTab, setEditTab] = useState("info"); // "info" | "subtasks" | "comments"

  // 子任務操作
  const addSubtask = () => {
    if (!newSubtask.trim()) return;
    setForm(f => ({...f, subtasks: [...f.subtasks, { id: Date.now(), title: newSubtask.trim(), done: false }]}));
    setNewSubtask("");
  };
  const toggleSubtask = (id) => {
    setForm(f => ({...f, subtasks: f.subtasks.map(s => s.id === id ? {...s, done: !s.done} : s)}));
  };
  const removeSubtask = (id) => {
    setForm(f => ({...f, subtasks: f.subtasks.filter(s => s.id !== id)}));
  };
  // 留言操作
  const addComment = () => {
    if (!commentText.trim()) return;
    setForm(f => ({...f, comments: [...f.comments, { id: Date.now(), author: currentUser || "匿名", text: commentText.trim(), time: nowTW() }]}));
    setCommentText("");
  };

  // 依賴操作
  const addDependency = (taskId) => {
    if (form.dependsOn.includes(taskId) || taskId === task.id) return;
    setForm(f => ({...f, dependsOn: [...f.dependsOn, taskId]}));
  };
  const removeDependency = (taskId) => {
    setForm(f => ({...f, dependsOn: f.dependsOn.filter(id => id !== taskId)}));
  };
  const availableDeps = (allTasks || []).filter(t => t.id !== task.id && !t.deletedAt);

  const handleSave = () => {
    if (!form.title.trim()) return;
    onSave({ ...form, title: form.title.trim(), assignee: form.assignees.join(",") });
  };
  const subtaskDone = form.subtasks.filter(s => s.done).length;
  const subtaskTotal = form.subtasks.length;
  return (
    <div style={{
      position:"fixed", inset:0, background:"rgba(0,0,0,0.75)", zIndex:200,
      display:"flex", alignItems:"center", justifyContent:"center", padding:"20px"
    }}>
      <div style={{
        background:"var(--card)", border:"1px solid var(--border)", borderRadius:16,
        padding:"24px", width:"100%", maxWidth:560, display:"flex", flexDirection:"column", gap:14,
        maxHeight:"90vh", overflowY:"auto"
      }}>
        <div style={{ fontSize:22, fontWeight:700 }}>✏️ 編輯任務</div>

        {/* 頁籤切換 */}
        <div style={{ display:"flex", gap:6, borderBottom:"1px solid var(--border)", paddingBottom:10 }}>
          {[["info","📋 基本"],["subtasks",`✓ 子任務${subtaskTotal?` (${subtaskDone}/${subtaskTotal})`:""}`],["comments",`💬 留言${form.comments.length?` (${form.comments.length})`:""}`]].map(([k,l])=>(
            <div key={k} onClick={()=>setEditTab(k)} style={{
              padding:"7px 14px", borderRadius:10, fontSize:14, fontWeight: editTab===k ? 700 : 400,
              cursor:"pointer", background: editTab===k ? "rgba(79,140,255,0.12)" : "transparent",
              color: editTab===k ? "var(--accent)" : "var(--muted)",
              border: editTab===k ? "1px solid rgba(79,140,255,0.25)" : "1px solid transparent",
              transition:"all 0.2s", whiteSpace:"nowrap"
            }}>{l}</div>
          ))}
        </div>

        {/* ── 基本資訊頁籤 ── */}
        {editTab==="info" && (<>
          {!canEdit && (
            <div style={{ background:"rgba(255,159,67,0.08)", border:"1px solid rgba(255,159,67,0.25)", borderRadius:10, padding:"10px 14px", fontSize:13, color:"var(--orange)", lineHeight:1.6 }}>
              🔒 你不是此任務的負責人，僅可瀏覽和留言
            </div>
          )}
          <div>
            <div style={{ fontSize:14, color:"var(--muted)", marginBottom:4, fontWeight:600 }}>任務名稱</div>
            <input value={form.title} onChange={e => canEdit && setForm(f=>({...f,title:e.target.value}))} readOnly={!canEdit}
              style={{ width:"100%", background:"var(--surf)", border:"1px solid var(--border)", borderRadius:10, color:"var(--text)", fontSize:15, padding:"12px 14px", outline:"none", fontFamily:"inherit", boxSizing:"border-box", opacity: canEdit?1:0.6 }}/>
          </div>
          <div>
            <div style={{ fontSize:14, color:"var(--muted)", marginBottom:4, fontWeight:600 }}>負責人（可多選）</div>
            <div style={{ display:"flex", gap:5, flexWrap:"wrap", opacity: canEdit?1:0.6 }}>
              {TEAM.map(name => {
                const sel = form.assignees.includes(name);
                return (
                  <div key={name} onClick={()=> canEdit && setForm(f=>({...f,assignees: sel ? f.assignees.filter(n=>n!==name) : [...f.assignees, name]}))}
                    style={{ display:"flex", alignItems:"center", gap:4, padding:"5px 10px 5px 5px", borderRadius:18, cursor: canEdit?"pointer":"default",
                      background: sel ? "rgba(79,140,255,0.15)" : "var(--surf)",
                      border: `1.5px solid ${sel ? "var(--accent)" : "var(--border)"}`, transition:"all 0.2s" }}>
                    <Avatar name={name} size={20}/>
                    <span style={{ fontSize:13, fontWeight: sel?600:400, color: sel?"var(--accent)":"var(--muted)" }}>{name}</span>
                  </div>
                );
              })}
            </div>
          </div>
          <div>
            <div style={{ fontSize:14, color:"var(--muted)", marginBottom:4, fontWeight:600 }}>截止日期（例行任務可留空）</div>
            <input type="date" value={form.deadline} onChange={e => canEdit && setForm(f=>({...f,deadline:e.target.value}))} readOnly={!canEdit}
              style={{ width:"100%", background:"var(--surf)", border:"1px solid var(--border)", borderRadius:10, color:"var(--text)", fontSize:15, padding:"12px 14px", outline:"none", fontFamily:"inherit", boxSizing:"border-box", opacity: canEdit?1:0.6 }}/>
          </div>
          <div>
            <div style={{ fontSize:14, color:"var(--muted)", marginBottom:4, fontWeight:600 }}>來源會議</div>
            <input value={form.meeting} onChange={e => canEdit && setForm(f=>({...f,meeting:e.target.value}))} readOnly={!canEdit}
              style={{ width:"100%", background:"var(--surf)", border:"1px solid var(--border)", borderRadius:10, color:"var(--text)", fontSize:15, padding:"12px 14px", outline:"none", fontFamily:"inherit", boxSizing:"border-box", opacity: canEdit?1:0.6 }}/>
          </div>
          {canSetPriority && (
            <div>
              <div style={{ fontSize:14, color:"var(--muted)", marginBottom:6, fontWeight:600 }}>優先等級</div>
              <div style={{ display:"flex", gap:8, flexWrap:"wrap" }}>
                {PRIORITIES.map(p => (
                  <div key={p.key} onClick={() => setForm(f=>({...f,priority:p.key}))}
                    style={{
                      flex:1, padding:"9px 8px", borderRadius:10, cursor:"pointer", fontSize:14, fontWeight:600,
                      textAlign:"center", minWidth:60,
                      background: form.priority===p.key ? p.bg : "var(--surf)",
                      color: form.priority===p.key ? p.color : "var(--muted)",
                      border: `1.5px solid ${form.priority===p.key ? p.color : "var(--border)"}`,
                      transition:"all 0.2s"
                    }}>{p.label}</div>
                ))}
              </div>
            </div>
          )}
          {!canSetPriority && form.priority && form.priority !== "medium" && (
            <div style={{ display:"flex", alignItems:"center", gap:8, fontSize:14, color:"var(--muted)" }}>
              優先等級：<PriorityBadge priority={form.priority}/>
            </div>
          )}
          {/* 前置任務依賴 */}
          {canEdit && (
            <div>
              <div style={{ fontSize:14, color:"var(--muted)", marginBottom:6, fontWeight:600 }}>🔗 前置任務（完成後才能結案）</div>
              {form.dependsOn.length > 0 && form.dependsOn.map(depId => {
                const dep = availableDeps.find(d => d.id === depId);
                if (!dep) return null;
                return (
                  <div key={depId} style={{
                    display:"flex", alignItems:"center", gap:8, padding:"6px 10px",
                    background:"var(--surf)", borderRadius:8, marginBottom:4,
                    border:"1px solid var(--border)"
                  }}>
                    <span style={{
                      width:16, height:16, borderRadius:"50%", flexShrink:0,
                      border:`2px solid ${dep.done ? "var(--green)" : "var(--border)"}`,
                      background: dep.done ? "var(--green)" : "transparent",
                      display:"inline-flex", alignItems:"center", justifyContent:"center",
                      fontSize:10, color:"#fff"
                    }}>{dep.done ? "✓" : ""}</span>
                    <span style={{ flex:1, fontSize:13, color: dep.done ? "var(--muted)" : "var(--text)", textDecoration: dep.done ? "line-through" : "none" }}>{dep.title}</span>
                    <span style={{ fontSize:12, color:"var(--muted)" }}>{dep.assignee}</span>
                    <div onClick={() => removeDependency(depId)} style={{ cursor:"pointer", color:"var(--red)", fontSize:12, opacity:0.6 }}>✕</div>
                  </div>
                );
              })}
              <select onChange={e => { if(e.target.value) { addDependency(Number(e.target.value)); e.target.value=""; }}} defaultValue=""
                style={{ width:"100%", padding:"9px 12px", borderRadius:10, border:"1px solid var(--border)", background:"var(--surf)", color:"var(--text)", fontSize:13, fontFamily:"inherit", marginTop:4 }}>
                <option value="" disabled>選擇前置任務...</option>
                {availableDeps.filter(d => !form.dependsOn.includes(d.id)).slice(0,20).map(d => (
                  <option key={d.id} value={d.id}>{d.title} ({d.assignee})</option>
                ))}
              </select>
            </div>
          )}
          {!canEdit && form.dependsOn.length > 0 && (
            <div style={{ fontSize:13, color:"var(--muted)" }}>
              🔗 前置任務：{form.dependsOn.length} 項
            </div>
          )}
          {onNotify && <button onClick={onNotify} style={{
            width:"100%", padding:"13px", borderRadius:10, border:"1px solid var(--orange)",
            background:"rgba(255,159,67,0.1)", color:"var(--orange)", fontSize:15, fontWeight:700,
            cursor:"pointer", fontFamily:"inherit", marginTop:2
          }}>📨 立即發送 LINE 通知給 {form.assignees.join("、")}</button>}
          {onConvertToRoutine && canEdit && (
            <button onClick={() => {
              if (window.confirm(`確定將「${form.title}」轉為例行任務？\n將為 ${form.assignees.length > 0 ? form.assignees.join("、") : "未指派"} 各建立一條例行任務。`)) {
                onConvertToRoutine(form.title.trim(), form.assignees.length > 0 ? form.assignees : [task.assignee || ""]);
              }
            }} style={{
              width:"100%", padding:"13px", borderRadius:10, border:"1px solid #a78bfa",
              background:"rgba(167,139,250,0.1)", color:"#a78bfa", fontSize:15, fontWeight:700,
              cursor:"pointer", fontFamily:"inherit", marginTop:2
            }}>🔄 轉為例行任務</button>
          )}
        </>)}

        {/* ── 子任務頁籤 ── */}
        {editTab==="subtasks" && (<>
          {/* 子任務進度 */}
          {subtaskTotal > 0 && (
            <div>
              <div style={{ display:"flex", justifyContent:"space-between", fontSize:14, color:"var(--muted)", marginBottom:6 }}>
                <span>子任務進度</span>
                <span style={{ fontWeight:700, color:"var(--accent)", fontFamily:"'DM Mono',monospace" }}>{subtaskDone}/{subtaskTotal}</span>
              </div>
              <div style={{ height:6, background:"var(--border)", borderRadius:3, overflow:"hidden" }}>
                <div style={{ height:"100%", width:`${subtaskTotal?Math.round(subtaskDone/subtaskTotal*100):0}%`, background:"linear-gradient(90deg,var(--accent),var(--green))", borderRadius:3, transition:"width 0.4s" }}/>
              </div>
            </div>
          )}
          {/* 子任務列表 */}
          {form.subtasks.map(s => (
            <div key={s.id} style={{
              display:"flex", alignItems:"center", gap:10, padding:"10px 12px",
              background:"var(--surf)", borderRadius:10, border:"1px solid var(--border)"
            }}>
              <div onClick={() => toggleSubtask(s.id)} style={{
                width:22, height:22, borderRadius:"50%", flexShrink:0, cursor:"pointer",
                border:`2px solid ${s.done ? "var(--green)" : "var(--border)"}`,
                background: s.done ? "var(--green)" : "transparent",
                display:"flex", alignItems:"center", justifyContent:"center",
                fontSize:12, color:"#fff", transition:"all 0.2s"
              }}>{s.done ? "✓" : ""}</div>
              <span style={{
                flex:1, fontSize:15, lineHeight:1.4,
                textDecoration: s.done ? "line-through" : "none",
                color: s.done ? "var(--muted)" : "var(--text)",
                opacity: s.done ? 0.6 : 1
              }}>{s.title}</span>
              <div onClick={() => removeSubtask(s.id)} style={{
                padding:"2px 8px", cursor:"pointer", color:"var(--red)", fontSize:13, fontWeight:600, opacity:0.6, flexShrink:0
              }}>✕</div>
            </div>
          ))}
          {form.subtasks.length === 0 && (
            <div style={{ textAlign:"center", color:"var(--muted)", fontSize:14, padding:"16px 0" }}>尚無子任務，新增一個吧</div>
          )}
          {/* 新增子任務 */}
          <div style={{ display:"flex", gap:8 }}>
            <input
              value={newSubtask}
              onChange={e => setNewSubtask(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter") addSubtask(); }}
              placeholder="輸入子任務名稱..."
              style={{
                flex:1, padding:"10px 14px", borderRadius:10,
                border:"1px solid var(--border)", background:"var(--surf)",
                color:"var(--text)", fontSize:14, fontFamily:"inherit", outline:"none"
              }}
            />
            <button onClick={addSubtask} style={{
              padding:"10px 16px", borderRadius:10, border:"none",
              background:"var(--accent)", color:"#fff", fontSize:14, fontWeight:700,
              cursor:"pointer", fontFamily:"inherit", whiteSpace:"nowrap"
            }}>＋ 新增</button>
          </div>
        </>)}

        {/* ── 留言頁籤 ── */}
        {editTab==="comments" && (<>
          <div style={{ display:"flex", flexDirection:"column", gap:10, maxHeight:300, overflowY:"auto" }}>
            {form.comments.length === 0 && (
              <div style={{ textAlign:"center", color:"var(--muted)", fontSize:14, padding:"16px 0" }}>尚無留言</div>
            )}
            {form.comments.map(c => (
              <div key={c.id} style={{
                background:"var(--surf)", borderRadius:12, padding:"10px 14px",
                border:"1px solid var(--border)"
              }}>
                <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:4 }}>
                  <Avatar name={c.author} size={22}/>
                  <span style={{ fontSize:14, fontWeight:600, color:"var(--text)" }}>{c.author}</span>
                  <span style={{ fontSize:12, color:"var(--muted)", marginLeft:"auto" }}>{c.time}</span>
                </div>
                <div style={{ fontSize:15, color:"var(--text)", lineHeight:1.6, paddingLeft:30 }}>{c.text}</div>
              </div>
            ))}
          </div>
          {/* 新增留言 */}
          <div style={{ display:"flex", gap:8, alignItems:"flex-end" }}>
            <textarea
              value={commentText}
              onChange={e => setCommentText(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); addComment(); }}}
              placeholder={`以 ${currentUser || "匿名"} 的身份留言...`}
              style={{
                flex:1, padding:"10px 14px", borderRadius:10,
                border:"1px solid var(--border)", background:"var(--surf)",
                color:"var(--text)", fontSize:14, fontFamily:"inherit", outline:"none",
                resize:"none", minHeight:42, maxHeight:120, lineHeight:1.5
              }}
            />
            <button onClick={addComment} style={{
              padding:"10px 16px", borderRadius:10, border:"none",
              background:"var(--accent)", color:"#fff", fontSize:14, fontWeight:700,
              cursor:"pointer", fontFamily:"inherit", whiteSpace:"nowrap", alignSelf:"flex-end"
            }}>發送</button>
          </div>
        </>)}

        {/* 底部操作按鈕 */}
        <div style={{ display:"flex", gap:10, marginTop:4, borderTop:"1px solid var(--border)", paddingTop:14 }}>
          {onDelete && <button onClick={() => { if(window.confirm("確定刪除此任務？")) onDelete(); }} style={{
            padding:"13px 16px", borderRadius:10, border:"1px solid var(--red)",
            background:"rgba(255,91,121,0.1)", color:"var(--red)", fontSize:15, fontWeight:700,
            cursor:"pointer", fontFamily:"inherit"
          }}>🗑</button>}
          <button onClick={onClose} style={{
            flex:1, padding:"13px", borderRadius:10, border:"1px solid var(--border)",
            background:"var(--surf)", color:"var(--muted)", fontSize:15, fontWeight:600,
            cursor:"pointer", fontFamily:"inherit"
          }}>取消</button>
          {canEdit && <button onClick={handleSave} style={{
            flex:2, padding:"13px", borderRadius:10, border:"none",
            background:"linear-gradient(135deg,var(--accent),#00b89c)", color:"#fff",
            fontSize:15, fontWeight:700, cursor:"pointer", fontFamily:"inherit"
          }}>儲存修改</button>}
        </div>
      </div>
    </div>
  );
}

// ── 例行任務新增表單（獨立元件避免 IME 輸入中斷）──
function RoutineTaskForm({ onAdd, onCancel, currentUser, isAdmin }) {
  const [title, setTitle] = useState("");
  const [selectedAssignees, setSelectedAssignees] = useState(isAdmin ? [] : [currentUser]);
  const toggleAssignee = (name) => setSelectedAssignees(prev => prev.includes(name) ? prev.filter(n => n !== name) : [...prev, name]);
  const allSelected = selectedAssignees.length === TEAM.length;
  const toggleAll = () => setSelectedAssignees(allSelected ? [] : [...TEAM]);
  return (
    <div style={{ background:"var(--card)", border:"1px solid var(--accent)", borderRadius:14, padding:"16px" }}>
      <div style={{ fontSize:18, fontWeight:700, marginBottom:12 }}>🔄 新增例行任務</div>
      <input
        autoFocus
        placeholder="例行任務名稱"
        value={title}
        onChange={e => setTitle(e.target.value)}
        style={{ width:"100%", padding:"12px 14px", borderRadius:10, border:"1px solid var(--border)", background:"var(--bg)", color:"var(--text)", fontSize:15, fontFamily:"inherit", marginBottom:10, outline:"none", boxSizing:"border-box" }}
      />
      {isAdmin ? (
        <div style={{ marginBottom:12 }}>
          <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:8 }}>
            <div style={{ fontSize:14, color:"var(--muted)", fontWeight:600 }}>負責人（可多選，每人各一條）</div>
            <div onClick={toggleAll} style={{ fontSize:13, color:"var(--accent)", cursor:"pointer", fontWeight:600 }}>{allSelected ? "取消全選" : "全選"}</div>
          </div>
          <div style={{ display:"flex", flexWrap:"wrap", gap:8 }}>
            {TEAM.map(name => {
              const sel = selectedAssignees.includes(name);
              return (
                <div key={name} onClick={() => toggleAssignee(name)} style={{
                  padding:"8px 14px", borderRadius:20, cursor:"pointer", fontSize:14, fontWeight:600,
                  border: sel ? "2px solid var(--accent)" : "2px solid var(--border)",
                  background: sel ? "rgba(79,140,255,0.15)" : "var(--bg)",
                  color: sel ? "var(--accent)" : "var(--text)",
                  transition:"all 0.15s", userSelect:"none"
                }}>
                  {sel ? "✓ " : ""}{name}
                </div>
              );
            })}
          </div>
          {selectedAssignees.length > 0 && (
            <div style={{ fontSize:13, color:"var(--green)", marginTop:8 }}>
              已選 {selectedAssignees.length} 人：{selectedAssignees.join("、")}
            </div>
          )}
        </div>
      ) : (
        <div style={{ width:"100%", padding:"12px 14px", borderRadius:10, border:"1px solid var(--border)", background:"var(--bg)", color:"var(--text)", fontSize:15, fontFamily:"inherit", marginBottom:12, boxSizing:"border-box" }}>
          {currentUser}（自己）
        </div>
      )}
      <div style={{ display:"flex", gap:10 }}>
        <button onClick={onCancel} style={{
          flex:1, padding:"12px", borderRadius:10, border:"1px solid var(--border)",
          background:"var(--surf)", color:"var(--muted)", fontSize:15, fontWeight:600,
          cursor:"pointer", fontFamily:"inherit"
        }}>取消</button>
        <button onClick={() => { if(title.trim() && selectedAssignees.length > 0) onAdd(title.trim(), selectedAssignees); }} style={{
          flex:2, padding:"12px", borderRadius:10, border:"none",
          background: (title.trim() && selectedAssignees.length > 0) ? "linear-gradient(135deg,var(--accent),#00b89c)" : "var(--border)",
          color: (title.trim() && selectedAssignees.length > 0) ? "#fff" : "var(--muted)",
          fontSize:15, fontWeight:700, cursor:"pointer", fontFamily:"inherit"
        }}>新增{selectedAssignees.length > 1 ? `（${selectedAssignees.length} 條）` : ""}</button>
      </div>
    </div>
  );
}

// ── 會議詳情 Modal ────────────────────────────────
function MeetingDetailModal({ meeting, relatedTasks, onEdit, onDelete, onClose, onSavePrep }) {
  // prepSections: [{ id, section, icon, assignee, items:[{id, title, done}] }]
  const initSections = () => {
    const raw = meeting.prepChecklist || [];
    // 已經是新分區格式
    if (raw.length > 0 && raw[0].section) return raw;
    // 舊的平面格式：包在一個區裡
    if (raw.length > 0 && raw[0].title) return [{ id:1, section:"準備項目", icon:"📋", assignee:"", items: raw }];
    return [];
  };
  const [prepSections, setPrepSections] = useState(initSections);
  const [newItemText, setNewItemText] = useState({});  // keyed by section id
  const [showRandomPicker, setShowRandomPicker] = useState(false);
  const [randomSelected, setRandomSelected] = useState(() => new Set(
    meeting.participants?.length > 0 ? meeting.participants : TEAM
  ));

  const totalItems = prepSections.reduce((s, sec) => s + sec.items.length, 0);
  const totalDone = prepSections.reduce((s, sec) => s + sec.items.filter(i => i.done).length, 0);

  const saveSections = (next) => { setPrepSections(next); onSavePrep(next); };

  const toggleItem = (secId, itemId) => {
    saveSections(prepSections.map(sec => sec.id === secId
      ? { ...sec, items: sec.items.map(i => i.id === itemId ? { ...i, done: !i.done } : i) }
      : sec
    ));
  };
  const removeItem = (secId, itemId) => {
    saveSections(prepSections.map(sec => sec.id === secId
      ? { ...sec, items: sec.items.filter(i => i.id !== itemId) }
      : sec
    ));
  };
  const addItem = (secId) => {
    const text = (newItemText[secId] || "").trim();
    if (!text) return;
    saveSections(prepSections.map(sec => sec.id === secId
      ? { ...sec, items: [...sec.items, { id: Date.now(), title: text, done: false }] }
      : sec
    ));
    setNewItemText(prev => ({ ...prev, [secId]: "" }));
  };
  const changeSectionAssignee = (secId, assignee) => {
    saveSections(prepSections.map(sec => sec.id === secId ? { ...sec, assignee } : sec));
  };
  const removeSection = (secId) => {
    saveSections(prepSections.filter(sec => sec.id !== secId));
  };
  const loadTemplate = () => {
    const sections = PREP_TEMPLATE.map((tpl, si) => ({
      id: Date.now() + si,
      section: tpl.section,
      icon: tpl.icon,
      assignee: "",  // 空白讓使用者自己填
      items: tpl.items.map((title, ii) => ({ id: Date.now() + si * 100 + ii, title, done: false }))
    }));
    saveSections(sections);
  };
  // 亂數指派：勾選人員後隨機分配，人數不足時部分人做兩份
  const toggleRandomPerson = (name) => {
    setRandomSelected(prev => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name); else next.add(name);
      return next;
    });
  };
  const selectAllRandom = () => {
    const pool = meeting.participants?.length > 0 ? meeting.participants : TEAM;
    setRandomSelected(new Set(pool));
  };
  const deselectAllRandom = () => setRandomSelected(new Set());
  const doRandomAssign = () => {
    if (prepSections.length === 0 || randomSelected.size === 0) return;
    const pool = [...randomSelected];
    // Fisher-Yates 洗牌
    for (let i = pool.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [pool[i], pool[j]] = [pool[j], pool[i]];
    }
    const sectionCount = prepSections.length;
    const next = prepSections.map((sec, i) => ({
      ...sec,
      assignee: pool[i % pool.length]
    }));
    saveSections(next);
    setShowRandomPicker(false);
  };
  const dl = daysLeft(meeting.date);
  let statusText, statusColor;
  if (dl < 0)       { statusText = `已過期 ${Math.abs(dl)} 天`; statusColor = "var(--muted)"; }
  else if (dl === 0) { statusText = "今天"; statusColor = "var(--red)"; }
  else if (dl === 1) { statusText = "明天"; statusColor = "var(--red)"; }
  else if (dl <= 3)  { statusText = `${dl} 天後`; statusColor = "var(--orange)"; }
  else if (dl <= 7)  { statusText = `${dl} 天後`; statusColor = "var(--accent)"; }
  else               { statusText = `${dl} 天後`; statusColor = "var(--green)"; }

  return (
    <div style={{
      position:"fixed", inset:0, background:"rgba(0,0,0,0.75)", zIndex:200,
      display:"flex", alignItems:"center", justifyContent:"center", padding:"20px"
    }} onClick={onClose}>
      <div onClick={e => e.stopPropagation()} style={{
        background:"var(--card)", border:"1px solid var(--border)", borderRadius:16,
        padding:"24px", width:"100%", maxWidth:540, display:"flex", flexDirection:"column", gap:16,
        maxHeight:"90vh", overflowY:"auto"
      }}>
        {/* 標題 + 倒數 */}
        <div>
          <div style={{ display:"flex", alignItems:"center", gap:10, marginBottom:8 }}>
            <span style={{ fontSize:14, padding:"4px 12px", borderRadius:12, background:`${statusColor}18`, color:statusColor, fontWeight:700 }}>{statusText}</span>
          </div>
          <div style={{ fontSize:24, fontWeight:700 }}>{meeting.eventType==="event"?"🎯":"📋"} {meeting.title}</div>
        </div>

        {/* 詳細資訊 */}
        <div style={{ display:"flex", flexDirection:"column", gap:12, background:"var(--surf)", borderRadius:12, padding:"16px" }}>
          <div style={{ display:"flex", alignItems:"center", gap:10 }}>
            <span style={{ fontSize:18 }}>📆</span>
            <div>
              <div style={{ fontSize:13, color:"var(--muted)" }}>日期</div>
              <div style={{ fontSize:16, fontWeight:600 }}>{meeting.date.replace(/-/g, "/")}</div>
            </div>
          </div>
          <div style={{ display:"flex", alignItems:"center", gap:10 }}>
            <span style={{ fontSize:18 }}>⏰</span>
            <div>
              <div style={{ fontSize:13, color:"var(--muted)" }}>時間</div>
              <div style={{ fontSize:16, fontWeight:600 }}>{meeting.time || "未指定"}</div>
            </div>
          </div>
          <div style={{ display:"flex", alignItems:"center", gap:10 }}>
            <span style={{ fontSize:18 }}>📍</span>
            <div>
              <div style={{ fontSize:13, color:"var(--muted)" }}>地點</div>
              <div style={{ fontSize:16, fontWeight:600 }}>{meeting.location || "未指定"}</div>
            </div>
          </div>
        </div>

        {/* 說明 */}
        {meeting.description && (
          <div>
            <div style={{ fontSize:14, color:"var(--muted)", fontWeight:600, marginBottom:6 }}>說明</div>
            <div style={{ fontSize:15, color:"var(--text)", lineHeight:1.8, background:"var(--surf)", borderRadius:10, padding:"14px" }}>{meeting.description}</div>
          </div>
        )}

        {/* 參與人員 */}
        {meeting.participants?.length > 0 && (
          <div>
            <div style={{ fontSize:14, color:"var(--muted)", fontWeight:600, marginBottom:8 }}>參與人員（{meeting.participants.length} 人）</div>
            <div style={{ display:"flex", gap:8, flexWrap:"wrap" }}>
              {meeting.participants.map(p => (
                <div key={p} style={{ display:"flex", alignItems:"center", gap:6, background:"var(--surf)", borderRadius:24, padding:"6px 14px 6px 7px" }}>
                  <Avatar name={p} size={24}/><span style={{ fontSize:14 }}>{p}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Slack 提醒狀態 */}
        <div>
          <div style={{ fontSize:14, color:"var(--muted)", fontWeight:600, marginBottom:8 }}>Slack 提醒狀態</div>
          <div style={{ display:"flex", gap:10 }}>
            {[["day7","7 天前"],["day3","3 天前"],["day1","1 天前"]].map(([k,l])=>(
              <div key={k} style={{
                flex:1, textAlign:"center", padding:"10px 8px", borderRadius:10,
                background: meeting.slackSent?.[k] ? "rgba(0,229,195,0.1)" : "var(--surf)",
                border: `1px solid ${meeting.slackSent?.[k] ? "rgba(0,229,195,0.3)" : "var(--border)"}`,
              }}>
                <div style={{ fontSize:18, marginBottom:4 }}>{meeting.slackSent?.[k] ? "✅" : "⏳"}</div>
                <div style={{ fontSize:13, color: meeting.slackSent?.[k] ? "var(--green)" : "var(--muted)", fontWeight:600 }}>{l}</div>
              </div>
            ))}
          </div>
        </div>

        {/* 相關任務 */}
        {relatedTasks.length > 0 && (
          <div>
            <div style={{ fontSize:14, color:"var(--muted)", fontWeight:600, marginBottom:8 }}>相關任務（{relatedTasks.length} 項）</div>
            {relatedTasks.map(t => (
              <div key={t.id} style={{
                display:"flex", alignItems:"center", justifyContent:"space-between", gap:8,
                padding:"10px 14px", background:"var(--surf)", borderRadius:10, marginBottom:6
              }}>
                <div style={{ display:"flex", alignItems:"center", gap:8, flex:1, minWidth:0 }}>
                  <div style={{
                    width:20, height:20, borderRadius:"50%", flexShrink:0,
                    border:`2px solid ${t.done ? "var(--green)" : "var(--border)"}`,
                    background: t.done ? "var(--green)" : "transparent",
                    display:"flex", alignItems:"center", justifyContent:"center",
                    fontSize:11, color:"#fff"
                  }}>{t.done ? "✓" : ""}</div>
                  <div style={{ fontSize:14, overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap",
                    textDecoration: t.done ? "line-through" : "none",
                    color: t.done ? "var(--muted)" : "var(--text)"
                  }}>{t.title}</div>
                </div>
                <div style={{ fontSize:13, color:"var(--muted)", flexShrink:0 }}>{t.assignee}</div>
              </div>
            ))}
          </div>
        )}

        {/* 會前準備清單（分區） */}
        <div>
          <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:8, flexWrap:"wrap", gap:6 }}>
            <div style={{ fontSize:14, color:"var(--muted)", fontWeight:600 }}>
              📋 會前準備清單 {totalItems > 0 && <span style={{ color:"var(--accent)", fontFamily:"'DM Mono',monospace" }}>({totalDone}/{totalItems})</span>}
            </div>
            <div style={{ display:"flex", gap:6 }}>
              {prepSections.length === 0 && (
                <div onClick={loadTemplate} style={{
                  padding:"5px 12px", borderRadius:8, fontSize:12, fontWeight:600,
                  background:"rgba(79,140,255,0.1)", color:"var(--accent)",
                  border:"1px solid rgba(79,140,255,0.3)", cursor:"pointer"
                }}>📄 載入模板</div>
              )}
              {prepSections.length > 0 && (
                <div onClick={() => setShowRandomPicker(!showRandomPicker)} style={{
                  padding:"5px 12px", borderRadius:8, fontSize:12, fontWeight:600,
                  background: showRandomPicker ? "var(--orange)" : "rgba(255,159,67,0.1)",
                  color: showRandomPicker ? "#fff" : "var(--orange)",
                  border:"1px solid rgba(255,159,67,0.3)", cursor:"pointer"
                }}>🎲 亂數指派</div>
              )}
            </div>
          </div>
          {/* 亂數指派人員選擇面板 */}
          {showRandomPicker && (() => {
            const pool = meeting.participants?.length > 0 ? meeting.participants : TEAM;
            const dupPeople = randomSelected.size > 0 && randomSelected.size < prepSections.length
              ? prepSections.length - randomSelected.size : 0;
            return (
              <div style={{
                background:"var(--surf)", border:"1px solid rgba(255,159,67,0.3)", borderRadius:12,
                padding:"14px", marginBottom:10
              }}>
                <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:10 }}>
                  <div style={{ fontSize:13, fontWeight:700, color:"var(--orange)" }}>
                    選擇參與人員 <span style={{ fontWeight:400, color:"var(--muted)", fontSize:12 }}>（已選 {randomSelected.size}/{pool.length}）</span>
                  </div>
                  <div style={{ display:"flex", gap:6 }}>
                    <div onClick={selectAllRandom} style={{
                      padding:"3px 8px", borderRadius:6, fontSize:11, cursor:"pointer",
                      background:"rgba(79,140,255,0.1)", color:"var(--accent)", border:"1px solid rgba(79,140,255,0.2)"
                    }}>全選</div>
                    <div onClick={deselectAllRandom} style={{
                      padding:"3px 8px", borderRadius:6, fontSize:11, cursor:"pointer",
                      background:"rgba(255,91,121,0.1)", color:"var(--red)", border:"1px solid rgba(255,91,121,0.2)"
                    }}>清除</div>
                  </div>
                </div>
                <div style={{ display:"flex", flexWrap:"wrap", gap:6, marginBottom:10 }}>
                  {pool.map((name, idx) => {
                    const checked = randomSelected.has(name);
                    return (
                      <div key={name} onClick={() => toggleRandomPerson(name)} style={{
                        display:"flex", alignItems:"center", gap:6, padding:"6px 12px",
                        borderRadius:10, cursor:"pointer", fontSize:13, fontWeight:600,
                        background: checked ? "rgba(79,140,255,0.12)" : "var(--card)",
                        border: `1.5px solid ${checked ? "var(--accent)" : "var(--border)"}`,
                        color: checked ? "var(--accent)" : "var(--muted)",
                        transition:"all 0.15s"
                      }}>
                        <div style={{
                          width:18, height:18, borderRadius:5, flexShrink:0,
                          border: `2px solid ${checked ? "var(--accent)" : "var(--border)"}`,
                          background: checked ? "var(--accent)" : "transparent",
                          display:"flex", alignItems:"center", justifyContent:"center",
                          fontSize:11, color:"#fff", transition:"all 0.15s"
                        }}>{checked ? "✓" : ""}</div>
                        <div style={{
                          width:20, height:20, borderRadius:"50%", flexShrink:0,
                          background: AVATAR_COLORS[idx % AVATAR_COLORS.length],
                          display:"flex", alignItems:"center", justifyContent:"center",
                          fontSize:10, color:"#fff", fontWeight:700
                        }}>{name[0]}</div>
                        {name}
                      </div>
                    );
                  })}
                </div>
                {dupPeople > 0 && (
                  <div style={{
                    fontSize:12, color:"var(--orange)", background:"rgba(255,159,67,0.08)",
                    padding:"6px 10px", borderRadius:8, marginBottom:8
                  }}>
                    ⚠️ 共 {prepSections.length} 區但只選了 {randomSelected.size} 人，將有 {dupPeople} 人負責 2 區
                  </div>
                )}
                <button onClick={doRandomAssign} disabled={randomSelected.size === 0} style={{
                  width:"100%", padding:"10px", borderRadius:10, border:"none",
                  background: randomSelected.size > 0
                    ? "linear-gradient(135deg, var(--orange), #e08a28)"
                    : "var(--border)",
                  color: randomSelected.size > 0 ? "#fff" : "var(--muted)",
                  fontSize:14, fontWeight:700, cursor: randomSelected.size > 0 ? "pointer" : "default",
                  fontFamily:"inherit"
                }}>🎲 開始亂數指派（{randomSelected.size} 人 → {prepSections.length} 區）</button>
              </div>
            );
          })()}
          {/* 整體進度條 */}
          {totalItems > 0 && (
            <div style={{ height:5, background:"var(--border)", borderRadius:3, overflow:"hidden", marginBottom:12 }}>
              <div style={{ height:"100%", width:`${Math.round(totalDone/totalItems*100)}%`, background:"linear-gradient(90deg,var(--accent),var(--green))", borderRadius:3, transition:"width 0.4s" }}/>
            </div>
          )}
          {/* 各分區 */}
          {prepSections.map(sec => {
            const secDone = sec.items.filter(i=>i.done).length;
            const secTotal = sec.items.length;
            return (
              <div key={sec.id} style={{
                background:"var(--surf)", border:"1px solid var(--border)", borderRadius:12,
                marginBottom:10, overflow:"hidden"
              }}>
                {/* 區域標題列 */}
                <div style={{
                  display:"flex", alignItems:"center", gap:8, padding:"10px 14px",
                  background:"rgba(79,140,255,0.04)", borderBottom:"1px solid var(--border)"
                }}>
                  <span style={{ fontSize:16 }}>{sec.icon || "📋"}</span>
                  <div style={{ flex:1, minWidth:0 }}>
                    <div style={{ fontSize:14, fontWeight:700, lineHeight:1.3 }}>{sec.section}</div>
                    <div style={{ fontSize:12, color:"var(--muted)" }}>
                      {secDone}/{secTotal} 完成
                    </div>
                  </div>
                  {/* 負責人選擇 */}
                  <select value={sec.assignee || ""} onChange={e => changeSectionAssignee(sec.id, e.target.value)}
                    style={{
                      padding:"4px 8px", borderRadius:8, border:"1px solid var(--border)",
                      background:"var(--card)", color: sec.assignee ? "var(--text)" : "var(--muted)",
                      fontSize:12, fontFamily:"inherit", maxWidth:90
                    }}>
                    <option value="">指派人員</option>
                    {TEAM.map(n => <option key={n} value={n}>{n}</option>)}
                  </select>
                  <div onClick={() => { if(window.confirm(`刪除「${sec.section}」整區？`)) removeSection(sec.id); }}
                    style={{ cursor:"pointer", color:"var(--red)", fontSize:12, opacity:0.4, flexShrink:0, padding:"0 4px" }}>✕</div>
                </div>
                {/* 區域進度條 */}
                {secTotal > 0 && (
                  <div style={{ height:3, background:"var(--border)" }}>
                    <div style={{ height:"100%", width:`${Math.round(secDone/secTotal*100)}%`, background: secDone===secTotal ? "var(--green)" : "var(--accent)", transition:"width 0.4s" }}/>
                  </div>
                )}
                {/* 項目列表 */}
                <div style={{ padding:"6px 10px" }}>
                  {sec.items.map(item => (
                    <div key={item.id} style={{
                      display:"flex", alignItems:"center", gap:8, padding:"6px 4px",
                      borderBottom:"1px solid var(--border)"
                    }}>
                      <div onClick={() => toggleItem(sec.id, item.id)} style={{
                        width:20, height:20, borderRadius:"50%", flexShrink:0, cursor:"pointer",
                        border:`2px solid ${item.done ? "var(--green)" : "var(--border)"}`,
                        background: item.done ? "var(--green)" : "transparent",
                        display:"flex", alignItems:"center", justifyContent:"center",
                        fontSize:11, color:"#fff", transition:"all 0.2s"
                      }}>{item.done ? "✓" : ""}</div>
                      <span style={{
                        flex:1, fontSize:13, lineHeight:1.4,
                        textDecoration: item.done ? "line-through" : "none",
                        color: item.done ? "var(--muted)" : "var(--text)",
                        opacity: item.done ? 0.55 : 1
                      }}>{item.title}</span>
                      <div onClick={() => removeItem(sec.id, item.id)} style={{
                        cursor:"pointer", color:"var(--red)", fontSize:11, opacity:0.35, flexShrink:0
                      }}>✕</div>
                    </div>
                  ))}
                  {/* 新增項目 */}
                  <div style={{ display:"flex", gap:6, marginTop:6, marginBottom:4 }}>
                    <input
                      value={newItemText[sec.id] || ""}
                      onChange={e => setNewItemText(prev => ({...prev, [sec.id]: e.target.value}))}
                      onKeyDown={e => { if (e.key === "Enter") addItem(sec.id); }}
                      placeholder="新增項目..."
                      style={{ flex:1, padding:"6px 10px", borderRadius:8, border:"1px solid var(--border)", background:"var(--card)", color:"var(--text)", fontSize:12, fontFamily:"inherit", outline:"none" }}
                    />
                    <button onClick={() => addItem(sec.id)} style={{
                      padding:"6px 10px", borderRadius:8, border:"none", background:"var(--accent)",
                      color:"#fff", fontSize:11, fontWeight:700, cursor:"pointer", fontFamily:"inherit"
                    }}>＋</button>
                  </div>
                </div>
              </div>
            );
          })}
          {prepSections.length === 0 && (
            <div style={{ textAlign:"center", color:"var(--muted)", fontSize:13, padding:"16px 0" }}>
              點擊「載入中會議室模板」快速建立準備清單
            </div>
          )}
        </div>

        {/* 按鈕列 */}
        <div style={{ display:"flex", gap:10 }}>
          {onDelete && <button onClick={onDelete} style={{
            padding:"13px 16px", borderRadius:10, border:"1px solid var(--red)",
            background:"rgba(255,91,121,0.1)", color:"var(--red)", fontSize:15, fontWeight:700,
            cursor:"pointer", fontFamily:"inherit"
          }}>🗑 刪除</button>}
          <button onClick={onClose} style={{
            flex:1, padding:"13px", borderRadius:10, border:"1px solid var(--border)",
            background:"var(--surf)", color:"var(--muted)", fontSize:15, fontWeight:600,
            cursor:"pointer", fontFamily:"inherit"
          }}>關閉</button>
          {onEdit && <button onClick={onEdit} style={{
            flex:2, padding:"13px", borderRadius:10, border:"none",
            background:"linear-gradient(135deg,var(--accent),#00b89c)", color:"#fff",
            fontSize:15, fontWeight:700, cursor:"pointer", fontFamily:"inherit"
          }}>✏️ 編輯會議</button>}
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
  @page { margin: 2.54cm 1.91cm 2.54cm 1.91cm; }
  body { font-family: "Microsoft JhengHei","微軟正黑體",sans-serif; font-size: 12pt; margin:0; }
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
    const myTasks = tasks.filter(t => hasAssignee(t, name));
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
      const d = t.deadline ? daysLeft(t.deadline) : null;
      let cls, txt;
      if (t.done)           { cls="done";    txt="✓ 已完成"; }
      else if (d === null)  { cls="pending"; txt="例行任務"; }
      else if (d < 0)       { cls="overdue"; txt=`逾期 ${Math.abs(d)} 天`; }
      else if (d === 0)     { cls="overdue"; txt="今天截止"; }
      else if (d <= 2)      { cls="urgent";  txt=`剩 ${d} 天`; }
      else                  { cls="pending"; txt=t.deadline; }
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
  const pending = tasks.filter(t => !t.done && t.deadline);
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
每個任務需包含：負責人（可多人）、任務描述、截止日期。今天是 ${today_str}。
若日期只說「本週五」請換算成實際日期。若無法確定截止日期，設定為 7 天後。
負責人請從以下名單選最接近的：${TEAM.join("、")}。若無法對應，填「待指派」。
若任務有多位負責人，用逗號分隔（例："蔡蕙芳,戴豐逸"）。
請只回傳 JSON 陣列，格式如下，不要有任何說明文字：
[{"title":"任務描述","assignee":"負責人1,負責人2","deadline":"YYYY-MM-DD"}]
會議紀錄：\n${text}` })
  });
  const data = await res.json();
  return data.items || [];
}

// ── Firebase Storage ──────────────────────────
let _lastSaveError = 0;
async function loadTasks() {
  try {
    const res = await fetch(`${FB_BASE}/tasks.json`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (data) {
      let tasks = Object.values(data).map(migrateTask);
      // 自動清理 7 天前的垃圾桶項目
      const cutoff = Date.now() - 7 * 86400000;
      const before = tasks.length;
      tasks = tasks.filter(t => !t.deletedAt || t.deletedAt > cutoff);
      if (tasks.length < before) {
        const obj = Object.fromEntries(tasks.map(t => [t.id, t]));
        await fetch(`${FB_BASE}/tasks.json`, { method:"PUT", headers:{"Content-Type":"application/json"}, body:JSON.stringify(obj) }).catch(()=>{});
      }
      return tasks;
    }
    const obj = Object.fromEntries(DEMO_TASKS.map(t => [t.id, migrateTask(t)]));
    await fetch(`${FB_BASE}/tasks.json`, { method:"PUT", headers:{"Content-Type":"application/json"}, body:JSON.stringify(obj) });
    return DEMO_TASKS.map(migrateTask);
  } catch(e) {
    console.error("loadTasks failed:", e);
    // 離線時嘗試從 localStorage 讀取快取
    const cached = localStorage.getItem("meetbot-tasks-cache");
    if (cached) {
      try { return JSON.parse(cached).map(migrateTask); } catch {}
    }
    return DEMO_TASKS.map(migrateTask);
  }
}
async function saveTasks(tasks) {
  try {
    const obj = Object.fromEntries(tasks.map(t => [t.id, t]));
    const res = await fetch(`${FB_BASE}/tasks.json`, { method:"PUT", headers:{"Content-Type":"application/json"}, body:JSON.stringify(obj) });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    _lastSaveError = 0;
  } catch(e) {
    console.error("saveTasks failed:", e);
    _lastSaveError = Date.now();
    throw e; // 讓呼叫端知道儲存失敗
  }
}
async function loadReminders() {
  try {
    const res = await fetch(`${FB_BASE}/reminders.json`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    return data ? { ...DEFAULT_REMINDERS, ...data } : DEFAULT_REMINDERS;
  } catch(e) { console.error("loadReminders failed:", e); return DEFAULT_REMINDERS; }
}
async function saveReminders(r) {
  try {
    const res = await fetch(`${FB_BASE}/reminders.json`, { method:"PUT", headers:{"Content-Type":"application/json"}, body:JSON.stringify(r) });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
  } catch(e) { console.error("saveReminders failed:", e); }
}

// ── 例行任務 Firebase ─────────────────────────
function getWeekKey() {
  const d = new Date();
  // ISO 8601 週數：以最近的週四所在年份為基準
  const thu = new Date(d);
  thu.setDate(thu.getDate() + 3 - ((thu.getDay() + 6) % 7));
  const year = thu.getFullYear();
  const jan4 = new Date(year, 0, 4);
  const week = 1 + Math.round(((thu - jan4) / 86400000 - 3 + ((jan4.getDay() + 6) % 7)) / 7);
  return `${year}-W${String(week).padStart(2,'0')}`;
}
async function loadRoutineTasks() {
  try {
    const res = await fetch(`${FB_BASE}/routineTasks.json`);
    const data = await res.json();
    return data ? Object.values(data) : [];
  } catch { return []; }
}
async function saveRoutineTasks(list) {
  try {
    const obj = Object.fromEntries(list.map(t => [t.id, t]));
    await fetch(`${FB_BASE}/routineTasks.json`, { method:"PUT", headers:{"Content-Type":"application/json"}, body:JSON.stringify(obj) });
  } catch {}
}
async function loadRoutineChecks() {
  try {
    const res = await fetch(`${FB_BASE}/routineChecksGlobal.json`);
    const data = await res.json();
    return data || {};
  } catch { return {}; }
}
async function saveRoutineChecks(checks) {
  try {
    await fetch(`${FB_BASE}/routineChecksGlobal.json`, { method:"PUT", headers:{"Content-Type":"application/json"}, body:JSON.stringify(checks) });
  } catch {}
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

// ── 會議 Firebase CRUD ────────────────────────
async function loadMeetingsFromFB() {
  try {
    const res = await fetch(`${MEETINGS_FB}.json`);
    const data = await res.json();
    return data ? Object.values(data) : [];
  } catch { return []; }
}
async function saveMeetingToFB(meeting) {
  try {
    await fetch(`${MEETINGS_FB}/${meeting.id}.json`, {
      method:"PUT", headers:{"Content-Type":"application/json"},
      body: JSON.stringify(meeting)
    });
  } catch {}
}
async function deleteMeetingFromFB(id) {
  try { await fetch(`${MEETINGS_FB}/${id}.json`, { method:"DELETE" }); } catch {}
}

// ── Slack Webhook 儲存（Firebase 共用）──────────
async function loadSlackWebhook() {
  try {
    const res = await fetch(`${FB_BASE}/slackWebhook.json`);
    const data = await res.json();
    return data || "";
  } catch { return ""; }
}
async function saveSlackWebhookFB(url) {
  try {
    await fetch(`${FB_BASE}/slackWebhook.json`, { method:"PUT", headers:{"Content-Type":"application/json"}, body:JSON.stringify(url) });
  } catch {}
}

// ── 會議表單 Modal ─────────────────────────────
function MeetingFormModal({ meeting, onSave, onClose }) {
  const [form, setForm] = useState({
    title: meeting?.title || "",
    date: meeting?.date || "",
    time: meeting?.time || "",
    location: meeting?.location || "",
    participants: meeting?.participants || [],
    description: meeting?.description || "",
    eventType: meeting?.eventType || "meeting",
  });
  const toggleParticipant = (name) => {
    setForm(prev => ({
      ...prev,
      participants: prev.participants.includes(name)
        ? prev.participants.filter(n => n !== name)
        : [...prev.participants, name]
    }));
  };
  return (
    <div style={{ position:"fixed", inset:0, background:"rgba(0,0,0,0.75)", zIndex:200, display:"flex", alignItems:"center", justifyContent:"center", padding:"20px" }}>
      <div style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:16, padding:"24px", width:"100%", maxWidth:540, display:"flex", flexDirection:"column", gap:14, maxHeight:"90vh", overflowY:"auto" }}>
        <div style={{ fontSize:22, fontWeight:700 }}>{meeting ? "✏️ 編輯" : "📅 新增"}{form.eventType==="meeting"?"會議":"活動"}</div>
        <div>
          <div style={{ fontSize:14, color:"var(--muted)", marginBottom:6, fontWeight:600 }}>類型</div>
          <div style={{ display:"flex", gap:8, marginBottom:4 }}>
            {[["meeting","📋 會議"],["event","🎯 活動"]].map(([k,l])=>(
              <div key={k} onClick={()=>setForm(f=>({...f,eventType:k}))}
                style={{ flex:1, padding:"10px", borderRadius:10, textAlign:"center", cursor:"pointer", fontSize:15, fontWeight:600,
                  background: form.eventType===k ? (k==="meeting"?"rgba(79,140,255,0.15)":"rgba(0,229,195,0.15)") : "var(--surf)",
                  color: form.eventType===k ? (k==="meeting"?"var(--accent)":"var(--green)") : "var(--muted)",
                  border: `1.5px solid ${form.eventType===k ? (k==="meeting"?"var(--accent)":"var(--green)") : "var(--border)"}`,
                  transition:"all 0.2s" }}>{l}</div>
            ))}
          </div>
        </div>
        <div>
          <div style={{ fontSize:14, color:"var(--muted)", marginBottom:4, fontWeight:600 }}>{form.eventType==="meeting"?"會議":"活動"}名稱</div>
          <input value={form.title} onChange={e=>setForm({...form, title:e.target.value})} placeholder="例：Q2 預算審查會議"
            style={{ width:"100%", background:"var(--surf)", border:"1px solid var(--border)", borderRadius:10, color:"var(--text)", fontSize:15, padding:"12px 14px", outline:"none", fontFamily:"inherit", boxSizing:"border-box" }}/>
        </div>
        <div style={{ display:"flex", gap:10 }}>
          <div style={{ flex:1 }}>
            <div style={{ fontSize:14, color:"var(--muted)", marginBottom:4, fontWeight:600 }}>日期</div>
            <input type="date" value={form.date} onChange={e=>setForm({...form, date:e.target.value})}
              style={{ width:"100%", background:"var(--surf)", border:"1px solid var(--border)", borderRadius:10, color:"var(--text)", fontSize:15, padding:"12px 14px", outline:"none", fontFamily:"inherit", boxSizing:"border-box" }}/>
          </div>
          <div style={{ flex:1 }}>
            <div style={{ fontSize:14, color:"var(--muted)", marginBottom:4, fontWeight:600 }}>時間</div>
            <input type="time" value={form.time} onChange={e=>setForm({...form, time:e.target.value})}
              style={{ width:"100%", background:"var(--surf)", border:"1px solid var(--border)", borderRadius:10, color:"var(--text)", fontSize:15, padding:"12px 14px", outline:"none", fontFamily:"inherit", boxSizing:"border-box" }}/>
          </div>
        </div>
        <div>
          <div style={{ fontSize:14, color:"var(--muted)", marginBottom:4, fontWeight:600 }}>地點</div>
          <input value={form.location} onChange={e=>setForm({...form, location:e.target.value})} placeholder="例：3F 會議室"
            style={{ width:"100%", background:"var(--surf)", border:"1px solid var(--border)", borderRadius:10, color:"var(--text)", fontSize:15, padding:"12px 14px", outline:"none", fontFamily:"inherit", boxSizing:"border-box" }}/>
        </div>
        <div>
          <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:4 }}>
            <div style={{ fontSize:14, color:"var(--muted)", fontWeight:600 }}>參與人員</div>
            <div onClick={()=>setForm(f=>({...f, participants: f.participants.length===TEAM.length ? [] : [...TEAM]}))}
              style={{ fontSize:13, color:"var(--accent)", cursor:"pointer", fontWeight:600 }}>
              {form.participants.length===TEAM.length ? "取消全選" : "全選"}
            </div>
          </div>
          <div style={{ display:"flex", flexWrap:"wrap", gap:8 }}>
            {TEAM.map(name => {
              const sel = form.participants.includes(name);
              return (
                <div key={name} onClick={()=>toggleParticipant(name)} style={{
                  display:"flex", alignItems:"center", gap:6, padding:"6px 14px", borderRadius:20,
                  background: sel ? memberColor(name) : "var(--surf)",
                  border: sel ? `1px solid ${memberColor(name)}` : "1px solid var(--border)",
                  color: sel ? "#fff" : "var(--muted)", cursor:"pointer", fontSize:14, fontWeight: sel ? 700 : 400,
                  transition:"all 0.2s"
                }}>
                  <Avatar name={name} size={20}/>{name}
                </div>
              );
            })}
          </div>
        </div>
        <div>
          <div style={{ fontSize:14, color:"var(--muted)", marginBottom:4, fontWeight:600 }}>說明（選填）</div>
          <textarea value={form.description} onChange={e=>setForm({...form, description:e.target.value})} placeholder="會議討論重點..."
            style={{ width:"100%", background:"var(--surf)", border:"1px solid var(--border)", borderRadius:10, color:"var(--text)", fontSize:15, lineHeight:1.7, padding:"12px 14px", resize:"vertical", minHeight:80, fontFamily:"inherit", outline:"none", boxSizing:"border-box" }}/>
        </div>
        <div style={{ display:"flex", gap:10 }}>
          <button onClick={onClose} style={{ flex:1, padding:"13px", borderRadius:10, border:"1px solid var(--border)", background:"var(--surf)", color:"var(--muted)", fontSize:15, fontWeight:600, cursor:"pointer", fontFamily:"inherit" }}>取消</button>
          <button onClick={()=>{
            if (!form.title || !form.date || !form.time) return;
            onSave(form);
          }} style={{ flex:2, padding:"13px", borderRadius:10, border:"none", background:"linear-gradient(135deg,var(--accent),#00b89c)", color:"#fff", fontSize:15, fontWeight:700, cursor:"pointer", fontFamily:"inherit" }}>
            {meeting ? "儲存修改" : form.eventType==="meeting" ? "建立會議" : "建立活動"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── 月曆日期計算 ──────────────────────────────
function getCalendarDays(year, month) {
  const firstDay = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const prevDays = new Date(year, month, 0).getDate();
  const days = [];
  for (let i = firstDay - 1; i >= 0; i--) days.push({ day: prevDays - i, current: false });
  for (let i = 1; i <= daysInMonth; i++) days.push({ day: i, current: true });
  while (days.length < 42) days.push({ day: days.length - firstDay - daysInMonth + 1, current: false });
  return days;
}
const WEEKDAY_LABELS = ["日","一","二","三","四","五","六"];

// ── 主元件 ────────────────────────────────────
export default function MeetBot() {
  const [tasks,        setTasks]        = useState([]);
  const [reminders,    setReminders]    = useState(DEFAULT_REMINDERS);
  const [loading,      setLoading]      = useState(true);
  const [syncing,      setSyncing]      = useState(false);
  const [lastSync,     setLastSync]     = useState(null);
  const [lastNotify,   setLastNotify]   = useState(null);
  const [batchNotifyDate, setBatchNotifyDate] = useState(today());
  const [batchSending, setBatchSending] = useState(false);
  const [tab,          setTab]          = useState("dashboard");
  const [filter,       setFilter]       = useState("all");
  const [memberFilter, setMemberFilter] = useState("all");
  const [searchQuery,  setSearchQuery]  = useState("");
  const [searchDate,   setSearchDate]   = useState("");
  const [showTrash,    setShowTrash]    = useState(false);
  const [currentUser,  setCurrentUser]  = useState(() => {
    const saved = localStorage.getItem("meetbot-user") || "";
    // 管理者需驗證密碼才能恢復身份
    if (ADMINS.includes(saved) && localStorage.getItem("meetbot-admin-auth") !== saved) return "";
    return saved;
  });
  const [adminAuthPending, setAdminAuthPending] = useState(null); // 等待密碼輸入的管理者名稱
  const [adminPwInput, setAdminPwInput] = useState("");
  const [adminPwError, setAdminPwError] = useState("");
  const [batchMode,    setBatchMode]    = useState(false);
  const [selectedIds,  setSelectedIds]  = useState(new Set());
  const [theme,        setTheme]        = useState(() => localStorage.getItem("meetbot-theme") || "dark");
  const [browserNotif, setBrowserNotif] = useState(() => localStorage.getItem("meetbot-browser-notif") === "true");
  const [isOnline,     setIsOnline]     = useState(navigator.onLine);
  const [parsing,      setParsing]      = useState(false);
  const [parseResult,  setParseResult]  = useState(null);
  const [docName,      setDocName]      = useState("");
  const [manualForm,   setManualForm]   = useState({ title:"", assignees:[], deadline:"", meeting:"", priority:"medium" });
  const [toast,        setToast]        = useState(null);
  const [savedPulse,   setSavedPulse]   = useState(false);
  const [editingTask,  setEditingTask]  = useState(null); // 備註 modal
  const [editingTaskFull, setEditingTaskFull] = useState(null); // 編輯任務 modal

  // ── 行事曆狀態 ──
  const [meetings,        setMeetings]        = useState([]);
  const [calView,         setCalView]         = useState("month"); // "month" | "timeline"
  const [calMonth,        setCalMonth]        = useState(() => { const n=new Date(); return { year:n.getFullYear(), month:n.getMonth() }; });
  const [selectedDate,    setSelectedDate]    = useState(null);
  const [showMeetingModal,setShowMeetingModal]= useState(false);
  const [editingMeeting, setEditingMeeting]  = useState(null);
  const [slackWebhook,   setSlackWebhook]    = useState("");
  const [viewingMeeting, setViewingMeeting]  = useState(null); // 會議詳情 modal

  // ── 例行任務 ──
  const [routineTasks,   setRoutineTasks]   = useState([]);
  const [routineChecks,  setRoutineChecks]  = useState({});
  const [showAddRoutine, setShowAddRoutine] = useState(false);
  const [expandRoutine, setExpandRoutine] = useState(false);
  const [expandedComments, setExpandedComments] = useState(null); // task id or null
  // routineForm state removed — RoutineTaskForm 獨立管理自己的 state

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

  // ── 主題切換 ──
  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    localStorage.setItem("meetbot-theme", next);
  };

  // ── 瀏覽器通知 ──
  const toggleBrowserNotif = async () => {
    if (!browserNotif) {
      if (!("Notification" in window)) { showToast("此瀏覽器不支援通知","#ff5b79"); return; }
      const perm = await Notification.requestPermission();
      if (perm !== "granted") { showToast("通知權限被拒絕","#ff5b79"); return; }
      setBrowserNotif(true);
      localStorage.setItem("meetbot-browser-notif", "true");
      showToast("已開啟瀏覽器通知","#00e5c3");
    } else {
      setBrowserNotif(false);
      localStorage.setItem("meetbot-browser-notif", "false");
      showToast("已關閉瀏覽器通知","#6b7494");
    }
  };
  const sendBrowserNotif = useCallback((title, body) => {
    if (!browserNotif || Notification.permission !== "granted") return;
    try { new Notification(title, { body, icon:"📋" }); } catch {}
  }, [browserNotif]);

  useEffect(() => {
    if (tasks.length > 0) {
      try { localStorage.setItem("meetbot-tasks-cache", JSON.stringify(tasks)); } catch {}
    }
  }, [tasks]);

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
    const [t, r, m, wh, rt, rc] = await Promise.all([loadTasks(), loadReminders(), loadMeetingsFromFB(), loadSlackWebhook(), loadRoutineTasks(), loadRoutineChecks()]);
    setTasks(t); setReminders(r); setMeetings(m); setSlackWebhook(wh);
    setRoutineTasks(rt); setRoutineChecks(rc);
    tasksRef.current = t; remindersRef.current = r;
    setLastSync(new Date());
    if (!quiet) setLoading(false); else setSyncing(false);
  }, []);

  // ── 離線偵測 ──
  useEffect(() => {
    const goOnline = () => { setIsOnline(true); fetchAll(true); showToast("已恢復連線，同步中...","#00e5c3"); };
    const goOffline = () => { setIsOnline(false); showToast("⚠️ 離線模式 — 資料將在恢復連線後同步","#ff9f43"); };
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => { window.removeEventListener("online", goOnline); window.removeEventListener("offline", goOffline); };
  }, [fetchAll]);

  useEffect(() => {
    fetchAll(false);
    const poll = setInterval(() => { if (!isSaving.current) fetchAll(true); }, 15000);
    // 自動提醒已移除 — LINE / Slack 提醒僅透過手動按鈕發送，避免重複通知
    return () => { clearInterval(poll); };
  }, [fetchAll]);

  // ── 任務自動存（含超時保護 + 失敗提示）──
  useEffect(() => {
    if (isFirstRender.current) { isFirstRender.current = false; return; }
    if (loading) return;
    tasksRef.current = tasks;
    isSaving.current = true;
    const timeout = setTimeout(() => { isSaving.current = false; }, 10000); // 10秒超時保護
    saveTasks(tasks)
      .then(() => setLastSync(new Date()))
      .catch(() => showToast("⚠️ 儲存失敗，請檢查網路","#ff5b79"))
      .finally(() => { clearTimeout(timeout); isSaving.current = false; });
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
      priority: daysLeft(t.deadline)<=1 ? "critical" : "medium",
      deletedAt: null, createdAt: new Date().toISOString().slice(0,10),
      progressNote: "", progressNoteTime: "",
    }));
    setTasks(prev => [...newTasks,...prev]);
    setParseResult(null); setDocName(""); setTab("dashboard");
    showToast(`已同步 ${newTasks.length} 項任務給全團隊`);
  };

  const addManualTask = () => {
    if (!manualForm.title.trim()) {
      showToast("請填寫任務名稱","#ff5b79"); return;
    }
    const assignees = isAdmin ? manualForm.assignees : [currentUser];
    if (assignees.length === 0) {
      showToast("請選擇至少一位負責人","#ff5b79"); return;
    }
    const newTask = {
      id: Date.now(), title: manualForm.title.trim(),
      assignee: assignees.join(","), deadline: manualForm.deadline || "",
      meeting: manualForm.meeting.trim() || (manualForm.deadline ? "手動新增" : "例行任務"),
      done: false, priority: manualForm.priority || "medium",
      deletedAt: null, createdAt: new Date().toISOString().slice(0,10),
      progressNote: "", progressNoteTime: "",
    };
    setTasks(prev => [newTask, ...prev]);
    setManualForm({ title:"", assignees:[], deadline:"", meeting:"", priority:"medium" });
    showToast("已新增 1 項任務");
  };

  const toggleDone = (id) => {
    const task = tasks.find(t => t.id === id);
    if (!task) return;
    // RBAC 檢查
    if (!isAdmin && !hasAssignee(task, currentUser)) {
      showToast("只有負責人或管理員可以變更完成狀態","#ff5b79"); return;
    }
    // 依賴檢查：如果要標記完成，檢查前置任務
    if (!task.done) {
      const blocking = getBlockingDeps(task);
      if (blocking.length > 0) {
        showToast(`前置任務尚未完成：${blocking.map(b=>b.title).slice(0,2).join("、")}`, "#ff5b79");
        return;
      }
    }
    setTasks(prev => {
      const updated = prev.map(t => {
        if (t.id !== id) return t;
        const nowDone = !t.done;
        if (nowDone) {
          fetch(`${BACKEND_URL}/notify-task-done`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ task: { ...t, done: true } })
          }).catch(() => {});
        }
        return { ...t, done: nowDone, doneTime: nowDone ? new Date().toISOString() : null };
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

  // ── 例行任務操作 ──
  const toggleRoutineCheck = (id) => {
    setRoutineChecks(prev => {
      const next = { ...prev, [id]: !prev[id] };
      saveRoutineChecks(next);
      return next;
    });
  };
  const addRoutineTask = (title, assignees) => {
    // assignees 為陣列，每人各建一條
    const list = Array.isArray(assignees) ? assignees : [assignees];
    const newTasks = list.map((a, i) => ({ id: Date.now() + i, title, assignee: a }));
    const next = [...routineTasks, ...newTasks];
    setRoutineTasks(next);
    saveRoutineTasks(next);
    setShowAddRoutine(false);
    showToast(`已新增 ${newTasks.length} 條例行任務`);
  };
  const removeRoutineTask = (id) => {
    const next = routineTasks.filter(t => t.id !== id);
    setRoutineTasks(next);
    saveRoutineTasks(next);
    showToast("已刪除例行任務","#6b7494");
  };

  // ── 任務編輯 ──
  const saveTaskEdit = (form) => {
    if (!editingTaskFull) return;
    // 有真實成員時自動移除「待指派」
    const cleanAssignee = (a) => { const parts = (a||"").split(",").map(s=>s.trim()).filter(s=>s&&s!=="待指派"); return parts.length > 0 ? parts.join(",") : a; };
    setTasks(prev => prev.map(t =>
      t.id === editingTaskFull.id ? {
        ...t, title: form.title, assignee: cleanAssignee(form.assignee),
        deadline: form.deadline, meeting: form.meeting,
        priority: form.priority || t.priority || "medium",
        subtasks: form.subtasks || t.subtasks || [],
        comments: form.comments || t.comments || [],
        dependsOn: form.dependsOn || t.dependsOn || [],
      } : t
    ));
    setEditingTaskFull(null);
    showToast("任務已更新","#00e5c3");
  };
  // 軟刪除（移至垃圾桶，7 天後自動清除）
  const deleteTask = () => {
    if (!editingTaskFull) return;
    setTasks(prev => prev.map(t =>
      t.id === editingTaskFull.id ? { ...t, deletedAt: Date.now() } : t
    ));
    setEditingTaskFull(null);
    showToast("已移至垃圾桶（7 天後自動清除）","#6b7494");
  };
  // 從垃圾桶還原
  const restoreTask = (id) => {
    setTasks(prev => prev.map(t => t.id === id ? { ...t, deletedAt: null } : t));
    showToast("任務已還原","#00e5c3");
  };
  // 永久刪除
  const permanentDeleteTask = (id) => {
    setTasks(prev => prev.filter(t => t.id !== id));
    showToast("已永久刪除","#ff5b79");
  };
  // ── 批量操作 ──
  const toggleSelectTask = (id) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };
  const selectAllFiltered = () => {
    setSelectedIds(new Set(filtered.map(t => t.id)));
  };
  const clearSelection = () => {
    setSelectedIds(new Set());
  };
  const batchMarkDone = () => {
    if (selectedIds.size === 0) return;
    setTasks(prev => prev.map(t => selectedIds.has(t.id) ? { ...t, done: true } : t));
    showToast(`已將 ${selectedIds.size} 項任務標記完成`, "#00e5c3");
    clearSelection();
    setBatchMode(false);
  };
  const batchDelete = () => {
    if (selectedIds.size === 0) return;
    if (!window.confirm(`確定將 ${selectedIds.size} 項任務移至垃圾桶？`)) return;
    setTasks(prev => prev.map(t => selectedIds.has(t.id) ? { ...t, deletedAt: Date.now() } : t));
    showToast(`已將 ${selectedIds.size} 項任務移至垃圾桶`, "#6b7494");
    clearSelection();
    setBatchMode(false);
  };
  const batchReassign = (newAssignee) => {
    if (selectedIds.size === 0) return;
    const cleanAssignee = (a) => { const parts = (a||"").split(",").map(s=>s.trim()).filter(s=>s&&s!=="待指派"); return parts.length > 0 ? parts.join(",") : a; };
    setTasks(prev => prev.map(t => selectedIds.has(t.id) ? { ...t, assignee: cleanAssignee(newAssignee) } : t));
    showToast(`已將 ${selectedIds.size} 項任務指派給 ${newAssignee}`, "#00e5c3");
    clearSelection();
    setBatchMode(false);
  };
  const batchSetPriority = (priority) => {
    if (selectedIds.size === 0) return;
    setTasks(prev => prev.map(t => selectedIds.has(t.id) ? { ...t, priority } : t));
    const pLabel = PRIORITY_MAP[priority]?.label || priority;
    showToast(`已將 ${selectedIds.size} 項任務設為「${pLabel}」`, "#00e5c3");
    clearSelection();
    setBatchMode(false);
  };
  // ── RBAC 權限檢查 ──
  const userRole = getUserRole(currentUser);
  const isAdmin = userRole === "admin";
  const isSpecialist = userRole === "specialist";
  const canEditTask = (t) => isAdmin || isSpecialist;
  const canDeleteTask = (t) => isAdmin;
  const canCompleteTask = (t) => isAdmin || hasAssignee(t, currentUser);
  const canSendReminders = isAdmin;
  const canUpload = isAdmin || isSpecialist;
  const canCreateMeeting = isAdmin || isSpecialist;
  const canManageRoutine = isAdmin;
  const canBatchOp = isAdmin;
  const canManageTrash = isAdmin;
  const canModifyReminders = isAdmin;

  // ── 任務依賴檢查 ──
  const getBlockingDeps = (t) => {
    if (!t.dependsOn || t.dependsOn.length === 0) return [];
    return t.dependsOn.map(depId => activeTasks.find(d => d.id === depId)).filter(d => d && !d.done);
  };


  const notifyTask = async () => {
    if (!editingTaskFull) return;
    try {
      const res = await fetch(`${BACKEND_URL}/notify-task`, {
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({ task: editingTaskFull })
      });
      if (res.ok) {
        showToast(`已發送通知給 ${editingTaskFull.assignee}`,"#00e5c3");
      } else {
        showToast("發送失敗，請檢查後端設定","#ff5b79");
      }
    } catch {
      showToast("發送失敗，無法連接後端","#ff5b79");
    }
  };

  // ── 會議管理 ──
  const addOrUpdateMeeting = async (form) => {
    const isEdit = !!editingMeeting;
    const meeting = {
      ...(isEdit ? editingMeeting : {}),
      id: isEdit ? editingMeeting.id : Date.now(),
      ...form,
      slackSent: isEdit ? (editingMeeting.slackSent || { day7:false, day3:false, day1:false }) : { day7:false, day3:false, day1:false },
    };
    await saveMeetingToFB(meeting);
    setMeetings(prev => isEdit ? prev.map(m => m.id === meeting.id ? meeting : m) : [meeting, ...prev]);
    setShowMeetingModal(false);
    setEditingMeeting(null);
    showToast(isEdit ? "會議已更新" : "會議已建立", "#00e5c3");
  };
  const removeMeeting = async (id) => {
    await deleteMeetingFromFB(id);
    setMeetings(prev => prev.filter(m => m.id !== id));
    showToast("會議已刪除", "#6b7494");
  };
  const testSlack = async () => {
    if (!slackWebhook) return showToast("請先設定 Slack Webhook URL", "#ff5b79");
    try {
      const res = await fetch(`${BACKEND_URL}/send-slack`, {
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({ webhookUrl: slackWebhook, message: "✅ MeetBot Slack 連線測試成功！會議提醒將於會前 7、3、1 天自動推播。" })
      });
      const data = await res.json();
      if (data.ok) showToast("Slack 測試訊息已發送","#00e5c3");
      else showToast("發送失敗：" + (data.error||""), "#ff5b79");
    } catch { showToast("發送失敗，請檢查 Webhook URL", "#ff5b79"); }
  };

  // ── 衍生統計（排除垃圾桶）──
  const activeTasks = tasks.filter(t => !t.deletedAt);
  const trashedTasks = tasks.filter(t => t.deletedAt);
  // 完成超過 7 天自動隱藏
  const isAutoHidden = (t) => t.done && t.doneTime && (Date.now() - new Date(t.doneTime).getTime()) > 7 * 86400000;
  const hiddenCount = activeTasks.filter(isAutoHidden).length;
  const sq = searchQuery.toLowerCase().trim();
  const filtered = activeTasks.filter(t => {
    if (sq && !t.title.toLowerCase().includes(sq) && !(t.assignee||"").toLowerCase().includes(sq) && !(t.meeting||"").toLowerCase().includes(sq)) return false;
    if (searchDate) { const td = t.createdAt || (t.id ? new Date(t.id).toISOString().slice(0,10) : ""); if (td !== searchDate) return false; }
    if (memberFilter!=="all" && !hasAssignee(t, memberFilter)) return false;
    if (filter==="hidden") return isAutoHidden(t);
    if (isAutoHidden(t)) return false; // 非隱藏模式時排除已隱藏任務
    if (filter==="pending") return !t.done;
    if (filter==="unassigned") return !t.done && (!t.assignee || t.assignee==="待指派");
    if (filter==="critical") return !t.done && t.priority==="critical";
    if (filter==="urgent")  return !t.done && (t.priority==="critical" || t.priority==="high");
    if (filter==="done")    return t.done;
    return true;
  });
  const visibleTasks = activeTasks.filter(t => !isAutoHidden(t));
  const pendingCount = visibleTasks.filter(t=>!t.done).length;
  const doneCount    = visibleTasks.filter(t=>t.done).length;
  const urgentCount  = visibleTasks.filter(t=>!t.done && (t.priority==="critical" || t.priority==="high")).length;
  const pct = visibleTasks.length ? Math.round(doneCount/visibleTasks.length*100) : 0;
  const deadlineTasks = visibleTasks.filter(t => !!t.deadline);
  const routineOnlyTasks = visibleTasks.filter(t => !t.deadline);
  const deadlineDone = deadlineTasks.filter(t=>t.done).length;
  const routineDone = routineOnlyTasks.filter(t=>t.done).length;
  const deadlinePct = deadlineTasks.length ? Math.round(deadlineDone/deadlineTasks.length*100) : 0;
  const routinePct = routineOnlyTasks.length ? Math.round(routineDone/routineOnlyTasks.length*100) : 0;
  const nonRoutineTasks = activeTasks.filter(t => !!t.deadline);
  const memberStats = TEAM.map(name => {
    const mine = nonRoutineTasks.filter(t=>hasAssignee(t, name));
    const done = mine.filter(t=>t.done).length;
    return { name, total:mine.length, done, pct: mine.length ? Math.round(done/mine.length*100):0 };
  }).filter(m=>m.total>0);

  const nextReminders = calcNextReminder(tasks, reminders);
  const syncLabel = lastSync ? `${pad2(lastSync.getHours())}:${pad2(lastSync.getMinutes())} 同步` : "同步中...";
  const WEEKDAYS = ["日","一","二","三","四","五","六"];

  // ── 行事曆 useMemo（必須在 early return 之前，避免 hooks 數量不一致）──
  const calDays = useMemo(() => getCalendarDays(calMonth.year, calMonth.month), [calMonth.year, calMonth.month]);
  const meetingsByDate = useMemo(() => {
    const map = {};
    meetings.forEach(m => { if (!map[m.date]) map[m.date] = []; map[m.date].push(m); });
    return map;
  }, [meetings]);

  // ── Loading ──
  if (loading) return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;700&display=swap');
        *{box-sizing:border-box;margin:0;padding:0}
        @keyframes slide{0%{transform:translateX(-200%)}100%{transform:translateX(400%)}}
      `}</style>
      <div style={{ fontFamily:"'Noto Sans TC',sans-serif", background:"#080b12", color:"#e8eaf2", minHeight:"100vh", display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:18 }}>
        <div style={{ fontSize:24 }}>📋</div>
        <div style={{ fontWeight:700, fontSize:22 }}>載入共用清單中...</div>
        <div style={{ width:180, height:4, background:"#232840", borderRadius:2, overflow:"hidden" }}>
          <div style={{ height:"100%", background:"linear-gradient(90deg,#4f8cff,#00e5c3)", animation:"slide 1.2s infinite", width:"50%" }}/>
        </div>
        <div style={{ fontSize:15, color:"#5a6285" }}>所有成員共用同一份資料</div>
      </div>
    </>
  );

  // ── CSS 變數、動畫與響應式佈局 ──
  const styleBlock = `
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@300;400;500;700;900&family=DM+Mono:wght@400;500&display=swap');
    *{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent;-webkit-text-size-adjust:100%;text-size-adjust:100%}
    html,body{background:var(--bg);height:100%;-webkit-text-size-adjust:100%;text-size-adjust:100%}
    :root{
      --bg:#080b12;--surf:#10141e;--card:#181d2a;--border:#232840;
      --accent:#4f8cff;--green:#00e5c3;--orange:#ff9f43;--red:#ff5b79;
      --text:#e8eaf2;--muted:#6b7494;--done-bg:rgba(24,29,42,0.5);--done-text:#6b7494;
    }
    .theme-light{
      --bg:#f0f2f8;--surf:#ffffff;--card:#ffffff;--border:#dfe2ea;
      --accent:#3b7aed;--green:#00b89c;--orange:#e08a28;--red:#e04060;
      --text:#1a1e2e;--muted:#7a819a;--done-bg:rgba(230,232,240,0.7);--done-text:#5a6078;
    }
    .theme-light select,.theme-light input{ color-scheme:light; }
    .theme-light ::-webkit-scrollbar-thumb{ background:#ccc; }
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
  const TaskCard = ({ t }) => {
    const isSelected = selectedIds.has(t.id);
    return (
    <div style={{
      background: isSelected ? "rgba(79,140,255,0.08)" : t.done ? "var(--done-bg)" : "var(--card)",
      border: `1px solid ${isSelected ? "var(--accent)" : t.urgent&&!t.done ? "rgba(255,91,121,0.35)" : "var(--border)"}`,
      borderRadius:14, padding:"15px 16px", marginBottom:10,
      display:"flex", flexDirection:"column", gap:10,
      opacity: t.done ? 0.6 : 1, transition:"all 0.2s",
    }}>
      {/* 上排：勾選 + 內容 */}
      <div style={{ display:"flex", gap:14, alignItems:"flex-start" }}>
        {/* 批量模式：選取框 / 一般模式：完成勾選 */}
        {batchMode ? (
          <div
            onClick={() => toggleSelectTask(t.id)}
            style={{
              width:26, height:26, borderRadius:6, flexShrink:0, marginTop:2, cursor:"pointer",
              border:`2.5px solid ${isSelected?"var(--accent)":"var(--border)"}`,
              background:isSelected?"var(--accent)":"transparent",
              display:"flex", alignItems:"center", justifyContent:"center",
              fontSize:14, color:"#fff", transition:"all 0.2s"
            }}>{isSelected?"✓":""}</div>
        ) : (
          <div
            onClick={() => toggleDone(t.id)}
            style={{
              width:26, height:26, borderRadius:"50%", flexShrink:0, marginTop:2, cursor:"pointer",
              border:`2.5px solid ${t.done?"var(--green)":t.urgent?"var(--red)":"var(--border)"}`,
              background:t.done?"var(--green)":"transparent",
              display:"flex", alignItems:"center", justifyContent:"center",
              fontSize:15, color:"#fff", transition:"all 0.2s"
            }}>{t.done?"✓":""}</div>
        )}

        {/* 內容 */}
        <div style={{ flex:1, minWidth:0 }}>
          <div style={{
            fontSize:20, fontWeight:500, lineHeight:1.5, marginBottom:8,
            textDecoration:t.done?"line-through":"none",
            color:t.done?"var(--done-text)":"var(--text)"
          }}>{t.title}</div>
          <div style={{ display:"flex", gap:8, flexWrap:"wrap", alignItems:"center", marginBottom: t.progressNote ? 8 : 0 }}>
            <div style={{ display:"flex", alignItems:"center", gap:5 }}>
              {getAssignees(t).map((name,i) => <Avatar key={i} name={name} size={22}/>)}
              <span style={{ fontSize:15, color:"var(--muted)" }}>{getAssignees(t).join("、")}</span>
            </div>
            <DeadlineBadge deadline={t.deadline} done={t.done}/>
            {t.priority && t.priority!=="medium" && t.priority!=="low" && !t.done && <PriorityBadge priority={t.priority}/>}
            {t.subtasks?.length > 0 && (
              <span style={bdg("var(--accent)","rgba(79,140,255,0.12)")}>✓ {t.subtasks.filter(s=>s.done).length}/{t.subtasks.length}</span>
            )}
            {t.comments?.length > 0 && (
              <span onClick={(e) => { e.stopPropagation(); setExpandedComments(prev => prev === t.id ? null : t.id); }}
                style={{ fontSize:14, color: expandedComments===t.id ? "var(--accent)" : "var(--muted)", display:"flex", alignItems:"center", gap:3, cursor:"pointer", padding:"2px 8px", borderRadius:12, background: expandedComments===t.id ? "rgba(79,140,255,0.12)" : "transparent", transition:"all 0.2s" }}>💬 {t.comments.length}</span>
            )}
            {!t.done && getBlockingDeps(t).length > 0 && (
              <span style={bdg("var(--orange)","rgba(255,159,67,0.12)")}>🔗 前置未完成</span>
            )}
          </div>
          {/* 子任務快速預覽 */}
          {t.subtasks?.length > 0 && !t.done && (
            <div style={{ marginTop:4 }}>
              {t.subtasks.filter(s=>!s.done).slice(0,3).map(s => (
                <div key={s.id} style={{ fontSize:14, color:"var(--muted)", padding:"2px 0", display:"flex", alignItems:"center", gap:6 }}>
                  <span style={{ width:5, height:5, borderRadius:"50%", background:"var(--border)", flexShrink:0 }}/>
                  <span style={{ overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}>{s.title}</span>
                </div>
              ))}
              {t.subtasks.filter(s=>!s.done).length > 3 && (
                <div style={{ fontSize:13, color:"var(--muted)", paddingLeft:11 }}>...還有 {t.subtasks.filter(s=>!s.done).length - 3} 項</div>
              )}
            </div>
          )}
          {t.progressNote && (
            <div style={{ background:"rgba(79,140,255,0.07)", border:"1px solid rgba(79,140,255,0.2)", borderRadius:8, padding:"8px 12px", marginTop:4 }}>
              <div style={{ fontSize:15, color:"var(--accent)", fontWeight:600, marginBottom:3 }}>📝 進度備註</div>
              <div style={{ fontSize:15, color:"var(--text)", lineHeight:1.6 }}>{t.progressNote}</div>
              {t.progressNoteTime && <div style={{ fontSize:14, color:"var(--muted)", marginTop:4 }}>{t.progressNoteTime}</div>}
            </div>
          )}
          <div style={{ fontSize:15, color:"var(--muted)", marginTop:8 }}>來自：{t.meeting}</div>
          {/* 展開留言 */}
          {expandedComments === t.id && t.comments?.length > 0 && (
            <div style={{ marginTop:8, background:"rgba(79,140,255,0.05)", border:"1px solid rgba(79,140,255,0.15)", borderRadius:10, padding:"10px 12px" }}>
              <div style={{ fontSize:14, fontWeight:700, color:"var(--accent)", marginBottom:8 }}>💬 留言（{t.comments.length}）</div>
              {t.comments.map(c => (
                <div key={c.id} style={{ marginBottom:8, paddingBottom:8, borderBottom:"1px solid var(--border)" }}>
                  <div style={{ display:"flex", alignItems:"center", gap:6, marginBottom:3 }}>
                    <Avatar name={c.author} size={18}/>
                    <span style={{ fontSize:13, fontWeight:600, color:"var(--text)" }}>{c.author}</span>
                    <span style={{ fontSize:12, color:"var(--muted)", marginLeft:"auto" }}>{c.time}</span>
                  </div>
                  <div style={{ fontSize:14, color:"var(--text)", lineHeight:1.6, paddingLeft:24 }}>{c.text}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* 底部按鈕列 */}
      <div style={{ display:"flex", gap:8 }}>
        <div
          onClick={() => setEditingTaskFull(t)}
          style={{
            flex:1, padding:"12px 0", borderRadius:10, cursor:"pointer",
            background:"var(--surf)", border:"1.5px solid var(--border)",
            display:"flex", alignItems:"center", justifyContent:"center", gap:6,
            fontSize:14, fontWeight:600, color:"var(--muted)", transition:"all 0.2s"
          }}
        >✏️ 編輯任務</div>
        {(isAdmin || hasAssignee(t, currentUser)) && <div
          onClick={() => setEditingTask(t)}
          style={{
            flex:1, padding:"12px 0", borderRadius:10, cursor:"pointer",
            background: t.progressNote ? "rgba(79,140,255,0.13)" : "var(--surf)",
            border:`1.5px solid ${t.progressNote ? "rgba(79,140,255,0.4)" : "var(--border)"}`,
            display:"flex", alignItems:"center", justifyContent:"center", gap:6,
            fontSize:14, fontWeight:600, color: t.progressNote ? "var(--accent)" : "var(--muted)",
            transition:"all 0.2s"
          }}
        >📝 {t.progressNote ? "編輯備註" : "新增備註"}</div>}
      </div>
    </div>
  );};

  // ── 儀表板內容 ──
  const DashboardContent = (
    <div className="mb-content-pad">
      <div style={{ background:"rgba(79,140,255,0.08)", border:"1px solid rgba(79,140,255,0.25)", borderRadius:14, padding:"12px 16px", marginBottom:14, display:"flex", alignItems:"center", gap:12 }}>
        <div style={{ fontSize:24 }}>🔗</div>
        <div>
          <div style={{ fontSize:15, fontWeight:600 }}>共用清單・即時同步</div>
          <div style={{ fontSize:15, color:"var(--muted)" }}>所有成員共用同一份資料，每 15 秒自動更新</div>
        </div>
      </div>

      <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr 1fr", gap:10, marginBottom:14 }}>
        {[{num:pendingCount,label:"待完成",color:"var(--accent)"},{num:doneCount,label:"已完成",color:"var(--green)"},{num:urgentCount,label:"緊急",color:"var(--red)"}].map(s=>(
          <div key={s.label} style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:14, padding:"14px 8px", textAlign:"center" }}>
            <div style={{ fontSize:36, fontWeight:900, fontFamily:"'DM Mono',monospace", color:s.color, lineHeight:1 }}>{s.num}</div>
            <div style={{ fontSize:18, color:"var(--muted)", marginTop:8 }}>{s.label}</div>
          </div>
        ))}
      </div>

      <div style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:14, padding:"14px 16px", marginBottom:14 }}>
        {deadlineTasks.length > 0 && (<>
          <div style={{ display:"flex", justifyContent:"space-between", fontSize:15, marginBottom:6 }}>
            <span style={{ color:"var(--muted)" }}>📅 有期限任務</span>
            <span style={{ fontWeight:700, color:"var(--green)", fontFamily:"'DM Mono',monospace" }}>{deadlineDone}/{deadlineTasks.length}（{deadlinePct}%）</span>
          </div>
          <div style={{ height:8, background:"var(--border)", borderRadius:4, overflow:"hidden", marginBottom: routineOnlyTasks.length > 0 ? 12 : 0 }}>
            <div style={{ height:"100%", width:`${deadlinePct}%`, background:"linear-gradient(90deg,var(--accent),var(--green))", borderRadius:4, transition:"width 0.6s ease" }}/>
          </div>
        </>)}
        {routineOnlyTasks.length > 0 && (<>
          <div onClick={()=>setExpandRoutine(!expandRoutine)} style={{ display:"flex", justifyContent:"space-between", fontSize:15, marginBottom:6, cursor:"pointer" }}>
            <span style={{ color:"var(--muted)" }}>🔄 例行任務 <span style={{ fontSize:13 }}>{expandRoutine?"▲":"▼"}</span></span>
            <span style={{ fontWeight:700, color:"var(--accent)", fontFamily:"'DM Mono',monospace" }}>{routineDone}/{routineOnlyTasks.length}（{routinePct}%）</span>
          </div>
          <div style={{ height:8, background:"var(--border)", borderRadius:4, overflow:"hidden" }}>
            <div style={{ height:"100%", width:`${routinePct}%`, background:"linear-gradient(90deg,#a78bfa,var(--accent))", borderRadius:4, transition:"width 0.6s ease" }}/>
          </div>
          {expandRoutine && (
            <div style={{ marginTop:12 }}>
              {TEAM.map(name => {
                const myRoutine = routineOnlyTasks.filter(t => hasAssignee(t, name));
                if (myRoutine.length === 0) return null;
                const myDone = myRoutine.filter(t => t.done).length;
                return (
                  <div key={name} style={{ marginBottom:10 }}>
                    <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:6 }}>
                      <Avatar name={name} size={24}/>
                      <span style={{ fontSize:14, fontWeight:600 }}>{name}</span>
                      <span style={{ fontSize:13, color:"var(--muted)", marginLeft:"auto", fontFamily:"'DM Mono',monospace" }}>{myDone}/{myRoutine.length}</span>
                    </div>
                    {myRoutine.map(t => (
                      <div key={t.id} style={{ display:"flex", alignItems:"center", gap:8, padding:"6px 0 6px 32px" }}>
                        <div onClick={()=>toggleDone(t.id)} style={{
                          width:20, height:20, borderRadius:"50%", flexShrink:0, cursor:"pointer",
                          border:`2px solid ${t.done?"var(--green)":"var(--border)"}`,
                          background: t.done?"var(--green)":"transparent",
                          display:"flex", alignItems:"center", justifyContent:"center",
                          fontSize:12, color:"#fff", transition:"all 0.2s"
                        }}>{t.done?"✓":""}</div>
                        <span style={{ fontSize:14, color: t.done?"var(--muted)":"var(--text)", textDecoration: t.done?"line-through":"none", flex:1 }}>{t.title}</span>
                      </div>
                    ))}
                  </div>
                );
              })}
            </div>
          )}
        </>)}
      </div>

      {/* 離線提示 */}
      {!isOnline && (
        <div style={{ background:"rgba(255,159,67,0.1)", border:"1px solid rgba(255,159,67,0.3)", borderRadius:14, padding:"12px 16px", marginBottom:14, display:"flex", alignItems:"center", gap:10 }}>
          <span style={{ fontSize:20 }}>📡</span>
          <div>
            <div style={{ fontSize:15, fontWeight:600, color:"var(--orange)" }}>離線模式</div>
            <div style={{ fontSize:14, color:"var(--muted)" }}>使用本地快取，恢復連線後自動同步</div>
          </div>
        </div>
      )}

      {/* 例行任務清單 */}
      {routineTasks.length > 0 && (
        <div style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:14, padding:"14px 16px", marginBottom:14 }}>
          <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:10 }}>
            <div style={{ fontSize:18, fontWeight:700 }}>🔄 例行任務</div>
            <div style={{ fontSize:14, color:"var(--green)", fontWeight:700, fontFamily:"'DM Mono',monospace" }}>
              {routineTasks.filter(t => routineChecks[t.id]).length}/{routineTasks.length}
            </div>
          </div>
          <div style={{ height:6, background:"var(--border)", borderRadius:3, overflow:"hidden", marginBottom:12 }}>
            <div style={{ height:"100%", width:`${routineTasks.length ? Math.round(routineTasks.filter(t=>routineChecks[t.id]).length/routineTasks.length*100) : 0}%`, borderRadius:3, background:"linear-gradient(90deg,#00e5c3,#4f8cff)", transition:"width 0.6s" }}/>
          </div>
          {(() => {
            // 依負責人分組顯示
            const grouped = {};
            const noAssignee = [];
            routineTasks.forEach(t => {
              if (t.assignee) {
                if (!grouped[t.assignee]) grouped[t.assignee] = [];
                grouped[t.assignee].push(t);
              } else {
                noAssignee.push(t);
              }
            });
            const assigneeNames = TEAM.filter(n => grouped[n]);
            return (
              <>
                {assigneeNames.map(name => {
                  const tasks = grouped[name];
                  const done = tasks.filter(t => routineChecks[t.id]).length;
                  return (
                    <div key={name} style={{ borderTop:"1px solid var(--border)", paddingTop:10, marginBottom:6 }}>
                      <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:6 }}>
                        <span style={{ fontSize:15, fontWeight:700, color:"var(--text)" }}>{name}</span>
                        <span style={{ fontSize:13, color: done===tasks.length ? "var(--green)" : "var(--muted)", fontFamily:"'DM Mono',monospace", fontWeight:600 }}>{done}/{tasks.length}</span>
                      </div>
                      {tasks.map(t => (
                        <div key={t.id} style={{ display:"flex", alignItems:"center", gap:10, padding:"6px 0 6px 12px" }}>
                          <div onClick={() => toggleRoutineCheck(t.id)} style={{
                            width:24, height:24, borderRadius:"50%", flexShrink:0, cursor:"pointer",
                            border:`2px solid ${routineChecks[t.id] ? "var(--green)" : "var(--border)"}`,
                            background: routineChecks[t.id] ? "var(--green)" : "transparent",
                            display:"flex", alignItems:"center", justifyContent:"center",
                            fontSize:13, color:"#fff", transition:"all 0.2s"
                          }}>{routineChecks[t.id] ? "✓" : ""}</div>
                          <div style={{
                            flex:1, fontSize:15, lineHeight:1.4,
                            textDecoration: routineChecks[t.id] ? "line-through" : "none",
                            color: routineChecks[t.id] ? "var(--muted)" : "var(--text)",
                            opacity: routineChecks[t.id] ? 0.6 : 1
                          }}>{t.title}</div>
                          {canManageRoutine && <div onClick={() => removeRoutineTask(t.id)} style={{
                            padding:"4px 8px", cursor:"pointer", color:"var(--red)", fontSize:13, fontWeight:600, opacity:0.5
                          }}>✕</div>}
                        </div>
                      ))}
                    </div>
                  );
                })}
                {noAssignee.length > 0 && (
                  <div style={{ borderTop:"1px solid var(--border)", paddingTop:10, marginBottom:6 }}>
                    <div style={{ fontSize:15, fontWeight:700, color:"var(--muted)", marginBottom:6 }}>未指派</div>
                    {noAssignee.map(t => (
                      <div key={t.id} style={{ display:"flex", alignItems:"center", gap:10, padding:"6px 0 6px 12px" }}>
                        <div onClick={() => toggleRoutineCheck(t.id)} style={{
                          width:24, height:24, borderRadius:"50%", flexShrink:0, cursor:"pointer",
                          border:`2px solid ${routineChecks[t.id] ? "var(--green)" : "var(--border)"}`,
                          background: routineChecks[t.id] ? "var(--green)" : "transparent",
                          display:"flex", alignItems:"center", justifyContent:"center",
                          fontSize:13, color:"#fff", transition:"all 0.2s"
                        }}>{routineChecks[t.id] ? "✓" : ""}</div>
                        <div style={{
                          flex:1, fontSize:15, lineHeight:1.4,
                          textDecoration: routineChecks[t.id] ? "line-through" : "none",
                          color: routineChecks[t.id] ? "var(--muted)" : "var(--text)",
                          opacity: routineChecks[t.id] ? 0.6 : 1
                        }}>{t.title}</div>
                        {canManageRoutine && <div onClick={() => removeRoutineTask(t.id)} style={{
                          padding:"4px 8px", cursor:"pointer", color:"var(--red)", fontSize:13, fontWeight:600, opacity:0.5
                        }}>✕</div>}
                      </div>
                    ))}
                  </div>
                )}
              </>
            );
          })()}
        </div>
      )}

      {/* 新增例行任務 */}
      <div style={{ marginBottom:14 }}>
        {!showAddRoutine ? (
          <div onClick={() => setShowAddRoutine(true)} style={{
            background:"var(--card)", border:"1.5px dashed var(--border)", borderRadius:14,
            padding:"14px 16px", textAlign:"center", cursor:"pointer", fontSize:15,
            color:"var(--muted)", fontWeight:600, transition:"all 0.2s"
          }}>＋ 新增例行任務</div>
        ) : (
          <RoutineTaskForm onAdd={addRoutineTask} onCancel={() => setShowAddRoutine(false)} currentUser={currentUser} isAdmin={isAdmin} />
        )}
      </div>

      {nextReminders.length>0 && (
        <div style={{ background:"rgba(255,159,67,0.06)", border:"1px solid rgba(255,159,67,0.2)", borderRadius:14, padding:"12px 16px", marginBottom:14 }}>
          <div style={{ fontSize:15, fontWeight:700, color:"var(--orange)", marginBottom:8 }}>即將觸發的提醒</div>
          {nextReminders.slice(0,3).map((r,i)=>(
            <div key={i} style={{ display:"flex", justifyContent:"space-between", fontSize:15, color:"var(--muted)", paddingBottom:i<2?6:0, borderBottom:i<Math.min(nextReminders.length,3)-1?"1px solid var(--border)":"none", marginBottom:i<2?6:0 }}>
              <span style={{ overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap", maxWidth:"55%" }}>• {r.task.title}</span>
              <span style={{ color:"var(--orange)", fontWeight:600, whiteSpace:"nowrap" }}>{r.type} · {`${pad2(r.at.getMonth()+1)}/${pad2(r.at.getDate())} ${pad2(r.at.getHours())}:00`}</span>
            </div>
          ))}
        </div>
      )}

      {/* 搜尋列 + 日期篩選 + 批量模式 */}
      <div style={{ display:"flex", gap:8, marginBottom:12, alignItems:"center", flexWrap:"wrap" }}>
        <input
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          placeholder="🔍 搜尋任務、負責人、會議..."
          style={{
            flex:1, minWidth:140, padding:"11px 14px", borderRadius:12,
            border:"1px solid var(--border)", background:"var(--card)",
            color:"var(--text)", fontSize:15, fontFamily:"inherit", outline:"none",
            boxSizing:"border-box"
          }}
        />
        <div style={{ position:"relative", display:"flex", alignItems:"center" }}>
          <input
            type="date"
            value={searchDate}
            onChange={e => setSearchDate(e.target.value)}
            style={{
              padding:"11px 12px", borderRadius:12, width: searchDate ? 155 : 44,
              border: `1px solid ${searchDate ? "var(--accent)" : "var(--border)"}`,
              background: searchDate ? "rgba(79,140,255,0.1)" : "var(--card)",
              color:"var(--text)", fontSize:14, fontFamily:"inherit", outline:"none",
              boxSizing:"border-box", transition:"all 0.2s", cursor:"pointer"
            }}
            title="依建立日期篩選"
          />
          {searchDate && (
            <div onClick={() => setSearchDate("")} style={{
              position:"absolute", right:6, top:"50%", transform:"translateY(-50%)",
              width:20, height:20, borderRadius:"50%", background:"var(--accent)",
              color:"#fff", display:"flex", alignItems:"center", justifyContent:"center",
              fontSize:12, cursor:"pointer", fontWeight:700
            }}>✕</div>
          )}
        </div>
        {canBatchOp && <div onClick={() => { setBatchMode(!batchMode); if(batchMode) clearSelection(); }} style={{
          padding:"11px 14px", borderRadius:12, cursor:"pointer", whiteSpace:"nowrap",
          background: batchMode ? "var(--accent)" : "var(--card)",
          color: batchMode ? "#fff" : "var(--muted)",
          border: `1px solid ${batchMode ? "var(--accent)" : "var(--border)"}`,
          fontSize:14, fontWeight:600, transition:"all 0.2s"
        }}>{batchMode ? "✕ 取消" : "☐ 批量"}</div>}
      </div>
      {searchDate && (
        <div style={{ fontSize:13, color:"var(--accent)", marginBottom:8, fontWeight:600 }}>
          📅 篩選建立日期：{searchDate}（{filtered.length} 筆結果）
        </div>
      )}

      {/* 批量操作列 */}
      {batchMode && (
        <div style={{
          background:"rgba(79,140,255,0.08)", border:"1px solid rgba(79,140,255,0.25)",
          borderRadius:14, padding:"12px 14px", marginBottom:12, animation:"fadeUp 0.3s ease"
        }}>
          <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:10 }}>
            <span style={{ fontSize:14, fontWeight:600, color:"var(--accent)" }}>
              已選取 {selectedIds.size} 項
            </span>
            <div style={{ display:"flex", gap:6 }}>
              <div onClick={selectAllFiltered} style={{ fontSize:13, color:"var(--accent)", cursor:"pointer", fontWeight:600 }}>全選</div>
              <div onClick={clearSelection} style={{ fontSize:13, color:"var(--muted)", cursor:"pointer", fontWeight:600 }}>清除</div>
            </div>
          </div>
          {selectedIds.size > 0 && (
            <div style={{ display:"flex", gap:6, flexWrap:"wrap" }}>
              <button onClick={batchMarkDone} style={{
                padding:"8px 14px", borderRadius:10, border:"1px solid var(--green)",
                background:"rgba(0,229,195,0.08)", color:"var(--green)", fontSize:13,
                fontWeight:600, cursor:"pointer", fontFamily:"inherit"
              }}>✓ 標記完成</button>
              <button onClick={batchDelete} style={{
                padding:"8px 14px", borderRadius:10, border:"1px solid var(--red)",
                background:"rgba(255,91,121,0.08)", color:"var(--red)", fontSize:13,
                fontWeight:600, cursor:"pointer", fontFamily:"inherit"
              }}>🗑 批量刪除</button>
              {ADMINS.includes(currentUser) && (
                <select onChange={e => { if(e.target.value) batchSetPriority(e.target.value); e.target.value=""; }}
                  defaultValue=""
                  style={{
                    padding:"8px 12px", borderRadius:10, border:"1px solid var(--border)",
                    background:"var(--card)", color:"var(--text)", fontSize:13,
                    fontFamily:"inherit", cursor:"pointer"
                  }}>
                  <option value="" disabled>設定優先等級</option>
                  {PRIORITIES.map(p => <option key={p.key} value={p.key}>{p.label}</option>)}
                </select>
              )}
              <select onChange={e => { if(e.target.value) batchReassign(e.target.value); e.target.value=""; }}
                defaultValue=""
                style={{
                  padding:"8px 12px", borderRadius:10, border:"1px solid var(--border)",
                  background:"var(--card)", color:"var(--text)", fontSize:13,
                  fontFamily:"inherit", cursor:"pointer"
                }}>
                <option value="" disabled>重新指派</option>
                {TEAM.map(name => <option key={name} value={name}>{name}</option>)}
              </select>
            </div>
          )}
        </div>
      )}

      {/* 篩選列 */}
      <div style={{ display:"flex", gap:7, marginBottom:12, overflowX:"auto", paddingBottom:4, scrollbarWidth:"none" }}>
        {[["all","全部"],["pending","待辦"],["unassigned","待指派"],["urgent","緊急"],["done","完成"],["hidden",`隱藏${hiddenCount>0?" "+hiddenCount:""}`]].map(([k,l])=>(
          <div key={k} onClick={()=>setFilter(k)} style={{ padding:"7px 14px", borderRadius:20, fontSize:15, fontWeight:600, cursor:"pointer", whiteSpace:"nowrap", background:filter===k?(k==="hidden"?"var(--muted)":k==="unassigned"?"var(--orange)":"var(--accent)"):"var(--card)", color:filter===k?"#fff":"var(--muted)", border:`1px solid ${filter===k?(k==="hidden"?"var(--muted)":k==="unassigned"?"var(--orange)":"var(--accent)"):"var(--border)"}`, transition:"all 0.2s" }}>{l}</div>
        ))}
        <div style={{ width:1, background:"var(--border)", margin:"0 3px", flexShrink:0 }}/>
        {["all",...TEAM].map(m=>(
          <div key={m} onClick={()=>setMemberFilter(m)} style={{ padding:"7px 14px", borderRadius:20, fontSize:15, cursor:"pointer", whiteSpace:"nowrap", background:memberFilter===m?memberColor(m):"var(--card)", color:memberFilter===m?"#fff":"var(--muted)", border:`1px solid ${memberFilter===m?memberColor(m):"var(--border)"}`, transition:"all 0.2s", fontWeight:memberFilter===m?700:400 }}>{m==="all"?"全員":m}</div>
        ))}
      </div>

      {/* 任務清單 */}
      {filtered.length===0 && <div style={{ textAlign:"center", color:"var(--muted)", padding:"40px 0", fontSize:15 }}>沒有符合的任務</div>}
      <div className="mb-task-grid">
        {filtered.map(t => <TaskCard key={t.id} t={t}/>)}
      </div>

      {/* 垃圾桶（管理者限定） */}
      {canManageTrash && trashedTasks.length > 0 && (
        <div style={{ marginTop:8 }}>
          <div onClick={() => setShowTrash(!showTrash)} style={{
            display:"flex", alignItems:"center", justifyContent:"center", gap:8,
            padding:"12px", borderRadius:12, cursor:"pointer", fontSize:15, fontWeight:600,
            color:"var(--muted)", background:"var(--card)", border:"1px solid var(--border)",
            transition:"all 0.2s", marginBottom: showTrash ? 12 : 0
          }}>
            🗑 垃圾桶（{trashedTasks.length}）{showTrash ? "▲" : "▼"}
          </div>
          {showTrash && trashedTasks.map(t => (
            <div key={t.id} style={{
              background:"var(--card)", border:"1px solid var(--border)", borderRadius:14,
              padding:"14px 16px", marginBottom:8, opacity:0.7, animation:"fadeUp 0.3s ease"
            }}>
              <div style={{ fontSize:16, fontWeight:500, marginBottom:6, textDecoration:"line-through", color:"var(--muted)" }}>{t.title}</div>
              <div style={{ display:"flex", gap:8, alignItems:"center", marginBottom:10, flexWrap:"wrap" }}>
                <div style={{ display:"flex", alignItems:"center", gap:5 }}>
                  {getAssignees(t).map((n,i)=><Avatar key={i} name={n} size={20}/>)}
                  <span style={{ fontSize:14, color:"var(--muted)" }}>{getAssignees(t).join("、")}</span>
                </div>
                <span style={{ fontSize:13, color:"var(--muted)" }}>
                  刪除於 {new Date(t.deletedAt).toLocaleDateString("zh-TW")}
                </span>
                {t.deletedAt && <span style={{ fontSize:13, color:"var(--orange)" }}>
                  {Math.max(0, 7 - Math.floor((Date.now() - t.deletedAt) / 86400000))} 天後自動清除
                </span>}
              </div>
              <div style={{ display:"flex", gap:8 }}>
                <button onClick={() => restoreTask(t.id)} style={{
                  flex:1, padding:"10px", borderRadius:10, border:"1px solid var(--green)",
                  background:"rgba(0,229,195,0.08)", color:"var(--green)", fontSize:14,
                  fontWeight:600, cursor:"pointer", fontFamily:"inherit"
                }}>↩ 還原</button>
                <button onClick={() => { if(window.confirm("確定永久刪除？此操作無法還原。")) permanentDeleteTask(t.id); }} style={{
                  flex:1, padding:"10px", borderRadius:10, border:"1px solid var(--red)",
                  background:"rgba(255,91,121,0.08)", color:"var(--red)", fontSize:14,
                  fontWeight:600, cursor:"pointer", fontFamily:"inherit"
                }}>✕ 永久刪除</button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div onClick={()=>fetchAll(true)} style={{ textAlign:"center", padding:"18px 0", fontSize:15, color:"var(--muted)", cursor:"pointer" }}>↻ 手動重新整理</div>
    </div>
  );

  // ── 上傳內容 ──
  const UploadContent = () => (
    <div className="mb-content-pad">
      <div style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:14, padding:"16px", marginBottom:16 }}>
        <div style={{ fontWeight:700, color:"var(--text)", marginBottom:14, fontSize:22 }}>新增單筆任務</div>
        <input
          placeholder="任務名稱"
          value={manualForm.title}
          onChange={e=>setManualForm(f=>({...f,title:e.target.value}))}
          style={{ width:"100%", padding:"12px 14px", borderRadius:10, border:"1px solid var(--border)", background:"var(--bg)", color:"var(--text)", fontSize:15, fontFamily:"inherit", marginBottom:10, outline:"none" }}
        />
        {isAdmin ? (
          <div style={{ marginBottom:10 }}>
            <div style={{ fontSize:14, color:"var(--muted)", marginBottom:6, fontWeight:600 }}>負責人（可多選）</div>
            <div style={{ display:"flex", gap:6, flexWrap:"wrap" }}>
              {TEAM.map(name => {
                const sel = manualForm.assignees.includes(name);
                return (
                  <div key={name} onClick={()=>setManualForm(f=>({...f,assignees: sel ? f.assignees.filter(n=>n!==name) : [...f.assignees, name]}))}
                    style={{ display:"flex", alignItems:"center", gap:5, padding:"6px 12px 6px 6px", borderRadius:20, cursor:"pointer",
                      background: sel ? "rgba(79,140,255,0.15)" : "var(--surf)",
                      border: `1.5px solid ${sel ? "var(--accent)" : "var(--border)"}`, transition:"all 0.2s" }}>
                    <Avatar name={name} size={22}/>
                    <span style={{ fontSize:14, fontWeight: sel?600:400, color: sel?"var(--accent)":"var(--muted)" }}>{name}</span>
                  </div>
                );
              })}
            </div>
          </div>
        ) : (
          <div style={{ width:"100%", padding:"12px 14px", borderRadius:10, border:"1px solid var(--border)", background:"var(--bg)", color:"var(--text)", fontSize:15, fontFamily:"inherit", marginBottom:10, display:"flex", alignItems:"center", gap:8 }}>
            <Avatar name={currentUser} size={22}/> {currentUser}（自己）
          </div>
        )}
        <div style={{ fontSize:14, color:"var(--muted)", marginBottom:4 }}>截止日期（例行任務可留空）</div>
        <input
          type="date"
          value={manualForm.deadline}
          onChange={e=>setManualForm(f=>({...f,deadline:e.target.value}))}
          style={{ width:"100%", padding:"12px 14px", borderRadius:10, border:"1px solid var(--border)", background:"var(--bg)", color:"var(--text)", fontSize:15, fontFamily:"inherit", marginBottom:10, outline:"none" }}
        />
        <input
          placeholder="會議名稱（選填）"
          value={manualForm.meeting}
          onChange={e=>setManualForm(f=>({...f,meeting:e.target.value}))}
          style={{ width:"100%", padding:"12px 14px", borderRadius:10, border:"1px solid var(--border)", background:"var(--bg)", color:"var(--text)", fontSize:15, fontFamily:"inherit", marginBottom:14, outline:"none" }}
        />
        {ADMINS.includes(currentUser) && (
          <div style={{ marginBottom:14 }}>
            <div style={{ fontSize:14, color:"var(--muted)", marginBottom:6, fontWeight:600 }}>優先等級</div>
            <div style={{ display:"flex", gap:8, flexWrap:"wrap" }}>
              {PRIORITIES.map(p => (
                <div key={p.key} onClick={() => setManualForm(f=>({...f,priority:p.key}))}
                  style={{
                    flex:1, padding:"9px 8px", borderRadius:10, cursor:"pointer", fontSize:14, fontWeight:600,
                    textAlign:"center", minWidth:60,
                    background: manualForm.priority===p.key ? p.bg : "var(--surf)",
                    color: manualForm.priority===p.key ? p.color : "var(--muted)",
                    border: `1.5px solid ${manualForm.priority===p.key ? p.color : "var(--border)"}`,
                    transition:"all 0.2s"
                  }}>{p.label}</div>
              ))}
            </div>
          </div>
        )}
        <button onClick={addManualTask} style={{ width:"100%", padding:"14px", borderRadius:12, border:"none", background:"linear-gradient(135deg,var(--accent),#7c5fe6)", color:"#fff", fontSize:18, fontWeight:700, cursor:"pointer", fontFamily:"inherit" }}>新增任務</button>
      </div>
      {canUpload && <>
      <div onClick={()=>!parsing&&fileRef.current.click()} style={{ border:`2px dashed ${parsing?"var(--accent)":"var(--border)"}`, borderRadius:16, padding:"36px 20px", textAlign:"center", cursor:"pointer", background:"var(--card)", marginBottom:16, transition:"border-color 0.2s" }}>
        <input ref={fileRef} type="file" accept=".docx" onChange={handleFile} style={{ display:"none" }}/>
        {parsing ? (<>
          <div style={{ fontSize:13, marginBottom:12 }}>⚙️</div>
          <div style={{ fontWeight:700, fontSize:22, marginBottom:6 }}>AI 解析中...</div>
          <div style={{ fontSize:15, color:"var(--muted)" }}>正在從會議紀錄提取任務</div>
          <div style={{ marginTop:16, height:4, background:"var(--border)", borderRadius:2, overflow:"hidden" }}>
            <div style={{ height:"100%", background:"linear-gradient(90deg,var(--accent),var(--green))", animation:"slide 1.2s infinite", width:"40%" }}/>
          </div>
        </>) : (<>
          <div style={{ fontSize:16, marginBottom:12 }}>📄</div>
          <div style={{ fontWeight:700, fontSize:22, marginBottom:6 }}>{docName||"點擊上傳 .docx 會議紀錄"}</div>
          <div style={{ fontSize:15, color:"var(--muted)" }}>AI 自動解析任務、負責人、截止日期</div>
        </>)}
      </div>
      {parseResult && (
        <div style={{ animation:"fadeUp 0.4s ease" }}>
          <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:12, fontSize:15, color:"var(--green)", fontWeight:700 }}>找到 {parseResult.length} 項任務，確認後同步給全團隊</div>
          {parseResult.map((t,i)=>(
            <div key={i} style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:14, padding:"14px 16px", marginBottom:10 }}>
              <div style={{ fontSize:18, fontWeight:500, marginBottom:8 }}>{t.title}</div>
              <div style={{ display:"flex", gap:8, flexWrap:"wrap" }}>
                <div style={{ display:"flex", alignItems:"center", gap:5 }}>{getAssignees(t).map((n,i)=><Avatar key={i} name={n} size={22}/>)}<span style={{ fontSize:15, color:"var(--muted)" }}>{getAssignees(t).join("、")}</span></div>
                <span style={bdg("var(--orange)","rgba(255,159,67,0.1)")}>📅 {t.deadline}</span>
              </div>
            </div>
          ))}
          <button onClick={confirmTasks} style={{ width:"100%", padding:"16px", borderRadius:12, border:"none", background:"linear-gradient(135deg,var(--green),#00b89c)", color:"#fff", fontSize:18, fontWeight:700, cursor:"pointer", fontFamily:"inherit", boxShadow:"0 4px 20px rgba(0,229,195,0.3)", marginTop:4 }}>同步給全團隊</button>
        </div>
      )}
      {!parsing&&!parseResult && (
        <div style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:14, padding:"16px", fontSize:15, color:"var(--muted)", lineHeight:2 }}>
          <div style={{ fontWeight:700, color:"var(--text)", marginBottom:8, fontSize:22 }}>使用說明</div>
          上傳包含會議決議事項的 Word 文件<br/>
          AI 會自動辨識「負責人」「任務」「截止時間」<br/>
          確認後立即同步給所有團隊成員
        </div>
      )}
      </>}
    </div>
  );

  // ── 成員內容 ──
  const TeamContent = () => (
    <div className="mb-content-pad">
      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:14 }}>
        <div style={{ fontSize:15, color:"var(--muted)", fontWeight:700, letterSpacing:1.5, textTransform:"uppercase" }}>成員完成率（即時）</div>
        <button onClick={()=>exportToWord(tasks)} style={{
          padding:"9px 16px", borderRadius:10, border:"1px solid var(--border)",
          background:"var(--card)", color:"var(--text)", fontSize:15, fontWeight:600,
          cursor:"pointer", fontFamily:"inherit", display:"flex", alignItems:"center", gap:6
        }}>📄 匯出 Word</button>
      </div>
      {memberStats.length===0 && <div style={{ color:"var(--muted)", fontSize:15, textAlign:"center", padding:30 }}>尚無任務資料</div>}
      <div className="mb-member-grid">
        {memberStats.map(m=>(
          <div key={m.name} className="mb-member-card" style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:14, padding:"16px" }}>
            <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:12 }}>
              <div style={{ display:"flex", alignItems:"center", gap:12 }}>
                <Avatar name={m.name} size={42}/>
                <div><div style={{ fontWeight:700, fontSize:22 }}>{m.name}</div><div style={{ fontSize:15, color:"var(--muted)" }}>{m.done}/{m.total} 項完成</div></div>
              </div>
              <div style={{ fontFamily:"'DM Mono',monospace", fontSize:34, fontWeight:700, color:m.pct===100?"var(--green)":m.pct>=50?"var(--accent)":"var(--orange)" }}>{m.pct}%</div>
            </div>
            <div style={{ height:6, background:"var(--border)", borderRadius:3, overflow:"hidden", marginBottom:10 }}>
              <div style={{ height:"100%", width:`${m.pct}%`, borderRadius:3, background:`linear-gradient(90deg,${memberColor(m.name)},${memberColor(m.name)}aa)`, transition:"width 0.6s" }}/>
            </div>
            <div>
              {nonRoutineTasks.filter(t=>hasAssignee(t, m.name)&&!t.done).slice(0,3).map(t=>(
                <div key={t.id} style={{ fontSize:15, color:"var(--muted)", padding:"8px 0", borderTop:"1px solid var(--border)" }}>
                  <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom: t.progressNote ? 4 : 0 }}>
                    <div style={{ flex:1, minWidth:0, fontSize:15, overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}>• {t.title}</div>
                    <div style={{ flexShrink:0 }}><DeadlineBadge deadline={t.deadline} done={false}/></div>
                  </div>
                  {t.progressNote && <div style={{ fontSize:13, color:"var(--accent)", marginTop:2, overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}>📝 {t.progressNote.length>30?t.progressNote.slice(0,30)+"…":t.progressNote}</div>}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
      <div style={{ fontSize:15, color:"var(--muted)", fontWeight:700, letterSpacing:1.5, textTransform:"uppercase", margin:"22px 0 12px" }}>固定成員</div>
      <div style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:14, padding:"16px" }}>
        <div style={{ display:"flex", flexWrap:"wrap", gap:10 }}>
          {TEAM.map(name=>(
            <div key={name} style={{ display:"flex", alignItems:"center", gap:7, background:"var(--surf)", borderRadius:24, padding:"6px 14px 6px 7px" }}>
              <Avatar name={name} size={26}/><span style={{ fontSize:15 }}>{name}</span>
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
        <div style={{ fontSize:15, color:"var(--muted)", fontWeight:700, letterSpacing:1.5, textTransform:"uppercase" }}>提醒規則設定</div>
        <div style={{ fontSize:15, color: savedPulse?"var(--green)":"var(--muted)", fontWeight:600, transition:"color 0.3s", animation: savedPulse?"savedPop 0.4s ease":undefined }}>
          {savedPulse ? "✓ 已儲存" : "修改後自動儲存"}
        </div>
      </div>

      {/* 規則 1：截止前 N 天 */}
      <div style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:14, padding:"18px", marginBottom:12 }}>
        <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:reminders.dayBefore.on?16:0 }}>
          <div style={{ display:"flex", alignItems:"center", gap:12 }}>
            <div style={{ width:40, height:40, borderRadius:10, background:"rgba(79,140,255,0.12)", display:"flex", alignItems:"center", justifyContent:"center", fontSize:18 }}>📅</div>
            <div><div style={{ fontSize:20, fontWeight:600 }}>截止日前提醒</div><div style={{ fontSize:15, color:"var(--muted)" }}>在截止日的前幾天早上提醒</div></div>
          </div>
          <Toggle on={reminders.dayBefore.on} onChange={()=>updateReminder("dayBefore",{on:!reminders.dayBefore.on})}/>
        </div>
        {reminders.dayBefore.on && (
          <div style={{ display:"flex", flexDirection:"column", gap:14, paddingTop:16, borderTop:"1px solid var(--border)" }}>
            <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between" }}>
              <span style={{ fontSize:15, color:"var(--muted)" }}>提前幾天</span>
              <Stepper value={reminders.dayBefore.days} min={1} max={7} suffix="天前" onChange={v=>updateReminder("dayBefore",{days:v})}/>
            </div>
            <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", flexWrap:"wrap", gap:8 }}>
              <span style={{ fontSize:15, color:"var(--muted)" }}>提醒時間</span>
              <div style={{ display:"flex", gap:7, flexWrap:"wrap" }}>
                {[7,8,9,10,12,14].map(h=>(
                  <div key={h} onClick={()=>updateReminder("dayBefore",{hour:h})} style={{ padding:"5px 12px", borderRadius:8, fontSize:15, cursor:"pointer", fontFamily:"'DM Mono',monospace", background:reminders.dayBefore.hour===h?"var(--accent)":"var(--surf)", color:reminders.dayBefore.hour===h?"#fff":"var(--muted)", border:`1px solid ${reminders.dayBefore.hour===h?"var(--accent)":"var(--border)"}`, transition:"all 0.2s" }}>{pad2(h)}:00</div>
                ))}
              </div>
            </div>
            <div style={{ background:"var(--surf)", borderRadius:8, padding:"10px 14px", fontSize:15, color:"var(--muted)" }}>
              例：任務截止日為週五，將在<span style={{ color:"var(--accent)", fontWeight:600 }}>週{WEEKDAYS[(5-reminders.dayBefore.days+7)%7]} {pad2(reminders.dayBefore.hour)}:00</span> 提醒負責人
            </div>
          </div>
        )}
      </div>

      {/* 規則 2：截止前 N 小時 */}
      <div style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:14, padding:"18px", marginBottom:12 }}>
        <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:reminders.hourBefore.on?16:0 }}>
          <div style={{ display:"flex", alignItems:"center", gap:12 }}>
            <div style={{ width:40, height:40, borderRadius:10, background:"rgba(255,159,67,0.12)", display:"flex", alignItems:"center", justifyContent:"center", fontSize:18 }}>⏰</div>
            <div><div style={{ fontSize:20, fontWeight:600 }}>截止前緊急提醒</div><div style={{ fontSize:15, color:"var(--muted)" }}>截止前幾小時發出最後警示</div></div>
          </div>
          <Toggle on={reminders.hourBefore.on} onChange={()=>updateReminder("hourBefore",{on:!reminders.hourBefore.on})}/>
        </div>
        {reminders.hourBefore.on && (
          <div style={{ paddingTop:16, borderTop:"1px solid var(--border)" }}>
            <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between" }}>
              <span style={{ fontSize:15, color:"var(--muted)" }}>提前幾小時</span>
              <Stepper value={reminders.hourBefore.hours} min={1} max={24} suffix="小時前" onChange={v=>updateReminder("hourBefore",{hours:v})}/>
            </div>
          </div>
        )}
      </div>

      {/* 規則 3：逾期提示 */}
      <div style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:14, padding:"18px", marginBottom:12 }}>
        <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between" }}>
          <div style={{ display:"flex", alignItems:"center", gap:12 }}>
            <div style={{ width:40, height:40, borderRadius:10, background:"rgba(255,91,121,0.12)", display:"flex", alignItems:"center", justifyContent:"center", fontSize:18 }}>🚨</div>
            <div><div style={{ fontSize:20, fontWeight:600 }}>逾期高亮提示</div><div style={{ fontSize:15, color:"var(--muted)" }}>逾期任務在儀表板醒目標示</div></div>
          </div>
          <Toggle on={reminders.overdueAlert.on} onChange={()=>updateReminder("overdueAlert",{on:!reminders.overdueAlert.on})}/>
        </div>
      </div>

      {/* 瀏覽器推播通知 */}
      <div style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:14, padding:"18px", marginBottom:12 }}>
        <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between" }}>
          <div style={{ display:"flex", alignItems:"center", gap:12 }}>
            <div style={{ width:40, height:40, borderRadius:10, background:"rgba(79,140,255,0.12)", display:"flex", alignItems:"center", justifyContent:"center", fontSize:18 }}>🔔</div>
            <div><div style={{ fontSize:20, fontWeight:600 }}>瀏覽器推播通知</div><div style={{ fontSize:15, color:"var(--muted)" }}>任務到期時在瀏覽器顯示通知</div></div>
          </div>
          <Toggle on={browserNotif} onChange={toggleBrowserNotif}/>
        </div>
        {browserNotif && (
          <div style={{ marginTop:12, paddingTop:12, borderTop:"1px solid var(--border)", fontSize:14, color:"var(--muted)", lineHeight:1.7 }}>
            ✓ 每 30 分鐘自動檢查即將到期任務<br/>
            ✓ 今天/明天截止的任務會觸發瀏覽器通知<br/>
            ⚠️ 需保持此頁面開啟才能收到通知
          </div>
        )}
      </div>

      {/* 規則 4：每週報告 */}
      <div style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:14, padding:"18px", marginBottom:12 }}>
        <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:reminders.weeklyReport.on?16:0 }}>
          <div style={{ display:"flex", alignItems:"center", gap:12 }}>
            <div style={{ width:40, height:40, borderRadius:10, background:"rgba(0,229,195,0.12)", display:"flex", alignItems:"center", justifyContent:"center", fontSize:18 }}>📊</div>
            <div><div style={{ fontSize:20, fontWeight:600 }}>每週完成率報告</div><div style={{ fontSize:15, color:"var(--muted)" }}>固定時間推播團隊整體進度</div></div>
          </div>
          <Toggle on={reminders.weeklyReport.on} onChange={()=>updateReminder("weeklyReport",{on:!reminders.weeklyReport.on})}/>
        </div>
        {reminders.weeklyReport.on && (
          <div style={{ display:"flex", flexDirection:"column", gap:14, paddingTop:16, borderTop:"1px solid var(--border)" }}>
            <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between" }}>
              <span style={{ fontSize:15, color:"var(--muted)" }}>每週幾</span>
              <div style={{ display:"flex", gap:6 }}>
                {[1,2,3,4,5].map(d=>(
                  <div key={d} onClick={()=>updateReminder("weeklyReport",{weekday:d})} style={{ width:38, height:38, borderRadius:8, display:"flex", alignItems:"center", justifyContent:"center", fontSize:15, cursor:"pointer", background:reminders.weeklyReport.weekday===d?"var(--accent)":"var(--surf)", color:reminders.weeklyReport.weekday===d?"#fff":"var(--muted)", border:`1px solid ${reminders.weeklyReport.weekday===d?"var(--accent)":"var(--border)"}`, transition:"all 0.2s" }}>週{WEEKDAYS[d]}</div>
                ))}
              </div>
            </div>
            <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", flexWrap:"wrap", gap:8 }}>
              <span style={{ fontSize:15, color:"var(--muted)" }}>發送時間</span>
              <div style={{ display:"flex", gap:7 }}>
                {[9,12,14,16,17,18].map(h=>(
                  <div key={h} onClick={()=>updateReminder("weeklyReport",{hour:h})} style={{ padding:"5px 12px", borderRadius:8, fontSize:15, cursor:"pointer", fontFamily:"'DM Mono',monospace", background:reminders.weeklyReport.hour===h?"var(--green)":"var(--surf)", color:reminders.weeklyReport.hour===h?"#fff":"var(--muted)", border:`1px solid ${reminders.weeklyReport.hour===h?"var(--green)":"var(--border)"}`, transition:"all 0.2s" }}>{pad2(h)}:00</div>
                ))}
              </div>
            </div>
            <div style={{ background:"var(--surf)", borderRadius:8, padding:"10px 14px", fontSize:15, color:"var(--muted)" }}>
              每週{WEEKDAYS[reminders.weeklyReport.weekday]} <span style={{ color:"var(--green)", fontWeight:600 }}>{pad2(reminders.weeklyReport.hour)}:00</span> 推播完成率摘要給全團隊
            </div>
          </div>
        )}
      </div>

      {nextReminders.length>0 && (
        <div style={{ marginTop:22 }}>
          <div style={{ fontSize:15, color:"var(--muted)", fontWeight:700, letterSpacing:1.5, textTransform:"uppercase", marginBottom:12 }}>依目前設定，即將提醒</div>
          {nextReminders.map((r,i)=>(
            <div key={i} style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:10, padding:"13px 16px", marginBottom:7, display:"flex", alignItems:"center", justifyContent:"space-between", gap:12 }}>
              <div style={{ flex:1, minWidth:0 }}>
                <div style={{ fontSize:15, fontWeight:500, overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}>{r.task.title}</div>
                <div style={{ fontSize:15, color:"var(--muted)", marginTop:3 }}>{r.task.assignee} · {r.type}</div>
              </div>
              <div style={{ fontSize:15, color:"var(--orange)", fontWeight:700, fontFamily:"'DM Mono',monospace", whiteSpace:"nowrap" }}>
                {`${pad2(r.at.getMonth()+1)}/${pad2(r.at.getDate())} ${pad2(r.at.getHours())}:00`}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 依建立日期批次通知 */}
      <div style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:14, padding:"18px", marginBottom:12 }}>
        <div style={{ display:"flex", alignItems:"center", gap:12, marginBottom:14 }}>
          <div style={{ width:40, height:40, borderRadius:10, background:"rgba(167,139,250,0.12)", display:"flex", alignItems:"center", justifyContent:"center", fontSize:18 }}>📨</div>
          <div><div style={{ fontSize:20, fontWeight:600 }}>依建立日期批次通知</div><div style={{ fontSize:15, color:"var(--muted)" }}>選擇日期，一次發送該日建立的所有任務通知</div></div>
        </div>
        <div style={{ display:"flex", gap:10, marginBottom:12, alignItems:"center" }}>
          <input type="date" value={batchNotifyDate} onChange={e=>setBatchNotifyDate(e.target.value)}
            style={{ flex:1, padding:"11px 14px", borderRadius:10, border:"1px solid var(--border)", background:"var(--surf)", color:"var(--text)", fontSize:15, fontFamily:"inherit", outline:"none" }}/>
        </div>
        {(() => {
          const matched = activeTasks.filter(t => !t.done && !t.deletedAt && (t.createdAt === batchNotifyDate || (!t.createdAt && new Date(t.id).toISOString().slice(0,10) === batchNotifyDate)));
          return (<>
            {matched.length > 0 ? (
              <div style={{ marginBottom:12 }}>
                <div style={{ fontSize:14, color:"var(--muted)", marginBottom:8 }}>找到 <span style={{ color:"var(--accent)", fontWeight:700 }}>{matched.length}</span> 項未完成任務：</div>
                <div style={{ maxHeight:200, overflowY:"auto", display:"flex", flexDirection:"column", gap:6 }}>
                  {matched.map(t => (
                    <div key={t.id} style={{ display:"flex", alignItems:"center", gap:8, padding:"8px 12px", background:"var(--surf)", borderRadius:10, fontSize:14 }}>
                      <span style={{ flex:1, overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}>{t.title}</span>
                      <span style={{ color:"var(--muted)", fontSize:13, flexShrink:0 }}>{getAssignees(t).join("、")}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div style={{ textAlign:"center", color:"var(--muted)", fontSize:14, padding:"12px 0", marginBottom:12 }}>該日期沒有未完成的任務</div>
            )}
            <button disabled={matched.length===0 || batchSending} onClick={async () => {
              setBatchSending(true);
              showToast(`正在發送 ${matched.length} 則通知...`,"#6b7494");
              let sent = 0;
              for (const t of matched) {
                try {
                  const res = await fetch(`${BACKEND_URL}/notify-task`, {
                    method:"POST", headers:{"Content-Type":"application/json"},
                    body: JSON.stringify({ task: t })
                  });
                  if (res.ok) sent++;
                } catch {}
              }
              setBatchSending(false);
              if (sent > 0) showToast(`已發送 ${sent} 則任務通知`,"#00e5c3");
              else showToast("發送失敗，請檢查後端設定","#ff5b79");
            }} style={{
              width:"100%", padding:"14px", borderRadius:12, border:"none",
              background: matched.length>0 && !batchSending ? "linear-gradient(135deg,#a78bfa,var(--accent))" : "var(--border)",
              color: matched.length>0 && !batchSending ? "#fff" : "var(--muted)",
              fontSize:16, fontWeight:700, cursor: matched.length>0 && !batchSending ? "pointer" : "default",
              fontFamily:"inherit", transition:"all 0.2s"
            }}>{batchSending ? "發送中..." : `📨 批次發送 ${matched.length} 則通知`}</button>
          </>);
        })()}
      </div>

      <div style={{ background:"rgba(79,140,255,0.06)", border:"1px solid rgba(79,140,255,0.2)", borderRadius:14, padding:"16px", marginTop:18, fontSize:15, color:"var(--muted)", lineHeight:1.9 }}>
        <div style={{ fontWeight:700, color:"var(--text)", marginBottom:8, fontSize:22 }}>提醒說明</div>
        LINE / Slack 提醒僅透過手動按鈕發送，不會自動觸發。
      </div>

      <button onClick={async () => {
        showToast("發送中...","#6b7494");
        const sent = await checkAndNotify(tasks, reminders);
        if (sent > 0) { setLastNotify(new Date()); showToast(`已發送 ${sent} 則 LINE 提醒`,"#00e5c3"); }
        else showToast("目前沒有符合條件的提醒","#6b7494");
      }} style={{ width:"100%", padding:"15px", borderRadius:12, border:"1px solid var(--border)", background:"var(--card)", color:"var(--text)", fontSize:15, fontWeight:600, cursor:"pointer", fontFamily:"inherit", marginTop:12 }}>
        立即檢查並發送 LINE 提醒
      </button>
      {lastNotify && <div style={{ textAlign:"center", fontSize:15, color:"var(--muted)", marginTop:10 }}>上次發送：{pad2(lastNotify.getHours())}:{pad2(lastNotify.getMinutes())}</div>}
    </div>
  );

  // ── 行事曆內容 ──────────────────────────────
  const prevMonth = () => setCalMonth(p => p.month === 0 ? { year: p.year-1, month: 11 } : { year: p.year, month: p.month-1 });
  const nextMonth = () => setCalMonth(p => p.month === 11 ? { year: p.year+1, month: 0 } : { year: p.year, month: p.month+1 });

  const CalendarContent = (
    <div className="mb-content-pad">
      {/* 視圖切換 + 新增按鈕 */}
      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:14 }}>
        <div style={{ display:"flex", gap:6 }}>
          {[["month","月曆"],["timeline","時間軸"]].map(([v,l])=>(
            <button key={v} onClick={()=>setCalView(v)} style={{
              padding:"7px 18px", borderRadius:20, fontSize:14, fontWeight: calView===v ? 700 : 400,
              background: calView===v ? "var(--accent)" : "var(--card)",
              color: calView===v ? "#fff" : "var(--muted)",
              border: calView===v ? "1px solid var(--accent)" : "1px solid var(--border)",
              cursor:"pointer", fontFamily:"inherit"
            }}>{l}</button>
          ))}
        </div>
        {canCreateMeeting && <button onClick={()=>{ setEditingMeeting(null); setShowMeetingModal(true); }} style={{
          padding:"7px 18px", borderRadius:20, fontSize:14, fontWeight:700,
          background:"linear-gradient(135deg,var(--accent),#00b89c)", color:"#fff",
          border:"none", cursor:"pointer", fontFamily:"inherit"
        }}>＋ 新增會議 / 活動</button>}
      </div>

      {/* 月曆視圖 */}
      {calView==="month" && (<>
        {/* 月份導航 */}
        <div style={{ display:"flex", alignItems:"center", justifyContent:"center", gap:20, marginBottom:14 }}>
          <div onClick={prevMonth} style={{ width:36, height:36, borderRadius:10, background:"var(--card)", border:"1px solid var(--border)", display:"flex", alignItems:"center", justifyContent:"center", cursor:"pointer", fontSize:15 }}>‹</div>
          <div style={{ fontSize:22, fontWeight:700, minWidth:160, textAlign:"center" }}>{calMonth.year} 年 {calMonth.month+1} 月</div>
          <div onClick={nextMonth} style={{ width:36, height:36, borderRadius:10, background:"var(--card)", border:"1px solid var(--border)", display:"flex", alignItems:"center", justifyContent:"center", cursor:"pointer", fontSize:15 }}>›</div>
        </div>

        {/* 星期標頭 */}
        <div style={{ display:"grid", gridTemplateColumns:"repeat(7, 1fr)", gap:2, marginBottom:4 }}>
          {WEEKDAY_LABELS.map(w => (
            <div key={w} style={{ textAlign:"center", fontSize:13, color:"var(--muted)", fontWeight:700, padding:"6px 0" }}>{w}</div>
          ))}
        </div>

        {/* 日期格子 */}
        <div style={{ display:"grid", gridTemplateColumns:"repeat(7, 1fr)", gap:3 }}>
          {calDays.map((d, i) => {
            const dateStr = d.current ? `${calMonth.year}-${pad2(calMonth.month+1)}-${pad2(d.day)}` : null;
            const isToday = dateStr === today();
            const isSelected = dateStr === selectedDate;
            const hasMeeting = dateStr && meetingsByDate[dateStr];
            const tasksDue = dateStr ? tasks.filter(t => t.deadline === dateStr && !t.done).length : 0;
            return (
              <div key={i} onClick={() => dateStr && setSelectedDate(isSelected ? null : dateStr)} style={{
                aspectRatio:"1", display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center",
                borderRadius:10, cursor: d.current ? "pointer" : "default", position:"relative",
                background: isSelected ? "var(--accent)" : isToday ? "rgba(79,140,255,0.12)" : "var(--card)",
                border: isToday && !isSelected ? "2px solid var(--accent)" : "1px solid var(--border)",
                color: isSelected ? "#fff" : d.current ? "var(--text)" : "var(--muted)",
                opacity: d.current ? 1 : 0.35, transition:"all 0.15s",
                fontSize:15, fontWeight: isToday||isSelected ? 700 : 400
              }}>
                {d.day}
                {/* 會議 + 任務指示點 */}
                <div style={{ display:"flex", gap:3, position:"absolute", bottom:4 }}>
                  {hasMeeting && <div style={{ width:6, height:6, borderRadius:"50%", background: isSelected ? "#fff" : "var(--accent)" }}/>}
                  {tasksDue > 0 && <div style={{ width:6, height:6, borderRadius:"50%", background: isSelected ? "#fff" : "var(--orange)" }}/>}
                </div>
              </div>
            );
          })}
        </div>

        {/* 選定日期的會議 + 任務 */}
        {selectedDate && (
          <div style={{ marginTop:14, animation:"fadeUp 0.3s ease" }}>
            <div style={{ fontSize:15, fontWeight:700, marginBottom:10, color:"var(--accent)" }}>
              {selectedDate.replace(/-/g,"/")} 的行程
            </div>
            {(meetingsByDate[selectedDate]||[]).map(m => (
              <div key={m.id} onClick={() => setViewingMeeting(m)} style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:14, padding:"14px 16px", marginBottom:8, cursor:"pointer", transition:"border-color 0.2s" }}>
                <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start" }}>
                  <div>
                    <div style={{ fontSize:16, fontWeight:600, marginBottom:4 }}>{m.eventType==="event"?"🎯":"📋"} {m.title}</div>
                    <div style={{ fontSize:14, color:"var(--muted)" }}>⏰ {m.time} &nbsp; 📍 {m.location||"未指定"}</div>
                  </div>
                  <div style={{ fontSize:14, color:"var(--accent)", fontWeight:600 }}>詳情 ›</div>
                </div>
                {m.participants?.length > 0 && (
                  <div style={{ display:"flex", gap:6, marginTop:8, flexWrap:"wrap" }}>
                    {m.participants.map(p => (
                      <div key={p} style={{ display:"flex", alignItems:"center", gap:4, fontSize:13, color:"var(--muted)" }}>
                        <Avatar name={p} size={20}/>{p}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
            {/* 當天到期任務 */}
            {tasks.filter(t => t.deadline === selectedDate && !t.done).map(t => (
              <div key={t.id} style={{ background:"var(--card)", border:"1px solid rgba(255,159,67,0.3)", borderRadius:14, padding:"12px 16px", marginBottom:8 }}>
                <div style={{ fontSize:14, color:"var(--orange)", fontWeight:600, marginBottom:2 }}>📋 任務截止</div>
                <div style={{ fontSize:15, fontWeight:500 }}>{t.title}</div>
                <div style={{ fontSize:13, color:"var(--muted)", marginTop:4 }}>{getAssignees(t).join("、")}</div>
              </div>
            ))}
            {!(meetingsByDate[selectedDate]||[]).length && !tasks.filter(t=>t.deadline===selectedDate&&!t.done).length && (
              <div style={{ textAlign:"center", color:"var(--muted)", padding:"20px 0", fontSize:15 }}>這天沒有行程</div>
            )}
          </div>
        )}
      </>)}

      {/* 時間軸視圖 */}
      {calView==="timeline" && (
        <div>
          <div style={{ fontSize:15, color:"var(--muted)", fontWeight:700, letterSpacing:1.5, marginBottom:14 }}>近期會議與活動</div>
          {meetings.filter(m => m.date >= today()).sort((a,b) => a.date.localeCompare(b.date) || (a.time||"").localeCompare(b.time||"")).length === 0 && (
            <div style={{ textAlign:"center", color:"var(--muted)", padding:"40px 0", fontSize:15 }}>尚無近期會議與活動</div>
          )}
          <div style={{ position:"relative", paddingLeft:28 }}>
            {meetings.filter(m => m.date >= today()).sort((a,b) => a.date.localeCompare(b.date) || (a.time||"").localeCompare(b.time||"")).length > 0 && (
              <div style={{ position:"absolute", left:9, top:8, bottom:8, width:2, background:"var(--border)" }}/>
            )}
            {meetings.filter(m => m.date >= today()).sort((a,b) => a.date.localeCompare(b.date) || (a.time||"").localeCompare(b.time||"")).map((m, i) => {
              const dl = daysLeft(m.date);
              let countdownText, countdownColor;
              if (dl === 0)      { countdownText = "今天"; countdownColor = "var(--red)"; }
              else if (dl === 1) { countdownText = "明天"; countdownColor = "var(--red)"; }
              else if (dl <= 3)  { countdownText = `${dl} 天後`; countdownColor = "var(--orange)"; }
              else if (dl <= 7)  { countdownText = `${dl} 天後`; countdownColor = "var(--accent)"; }
              else               { countdownText = `${dl} 天後`; countdownColor = "var(--muted)"; }
              const dotColor = dl <= 1 ? "var(--red)" : dl <= 3 ? "var(--orange)" : dl <= 7 ? "var(--accent)" : "var(--muted)";
              return (
                <div key={m.id} style={{ position:"relative", marginBottom:16, animation:"fadeUp 0.4s ease", animationDelay:`${i*0.05}s`, animationFillMode:"backwards" }}>
                  {/* 時間軸圓點 */}
                  <div style={{ position:"absolute", left:-24, top:16, width:12, height:12, borderRadius:"50%", background:dotColor, border:"2px solid var(--bg)", boxShadow:`0 0 0 3px ${dotColor}22` }}/>
                  {/* 卡片 */}
                  <div onClick={() => setViewingMeeting(m)} style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:14, padding:"16px", marginLeft:6, cursor:"pointer", transition:"border-color 0.2s" }}>
                    <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start" }}>
                      <div style={{ flex:1, minWidth:0 }}>
                        <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:6 }}>
                          <span style={{ fontSize:13, padding:"3px 10px", borderRadius:12, background:`${countdownColor}18`, color:countdownColor, fontWeight:700 }}>{countdownText}</span>
                          <span style={{ fontSize:13, color:"var(--muted)" }}>{m.date.slice(5).replace("-","/")} {m.time}</span>
                        </div>
                        <div style={{ fontSize:20, fontWeight:600, marginBottom:4 }}>{m.eventType==="event"?"🎯":"📋"} {m.title}</div>
                        <div style={{ fontSize:14, color:"var(--muted)" }}>📍 {m.location||"未指定地點"}</div>
                        {m.description && <div style={{ fontSize:13, color:"var(--muted)", marginTop:4, lineHeight:1.6, display:"-webkit-box", WebkitLineClamp:2, WebkitBoxOrient:"vertical", overflow:"hidden" }}>{m.description}</div>}
                      </div>
                      <div style={{ fontSize:14, color:"var(--accent)", fontWeight:600, flexShrink:0 }}>詳情 ›</div>
                    </div>
                    {m.participants?.length > 0 && (
                      <div style={{ display:"flex", gap:6, marginTop:8, flexWrap:"wrap" }}>
                        {m.participants.map(p => <div key={p} style={{ display:"flex", alignItems:"center", gap:4, fontSize:13, color:"var(--muted)" }}><Avatar name={p} size={18}/>{p}</div>)}
                      </div>
                    )}
                    {/* Slack 提醒狀態 */}
                    <div style={{ display:"flex", gap:8, marginTop:8, flexWrap:"wrap" }}>
                      {[["day7","7天前"],["day3","3天前"],["day1","1天前"]].map(([k,l])=>(
                        <span key={k} style={{ fontSize:12, padding:"2px 8px", borderRadius:10, background: m.slackSent?.[k] ? "rgba(0,229,195,0.12)" : "rgba(107,116,148,0.08)", color: m.slackSent?.[k] ? "var(--green)" : "var(--muted)" }}>
                          {m.slackSent?.[k] ? "✓" : "○"} {l}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* 已過期的會議 */}
          {meetings.filter(m => m.date < today()).length > 0 && (
            <div style={{ marginTop:20 }}>
              <div style={{ fontSize:15, color:"var(--muted)", fontWeight:700, letterSpacing:1.5, marginBottom:14 }}>已過期會議</div>
              {meetings.filter(m => m.date < today()).sort((a,b) => b.date.localeCompare(a.date)).slice(0,5).map(m => (
                <div key={m.id} onClick={() => setViewingMeeting(m)} style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:14, padding:"14px 16px", marginBottom:8, opacity:0.5, cursor:"pointer" }}>
                  <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center" }}>
                    <div>
                      <div style={{ fontSize:15, fontWeight:500 }}>{m.eventType==="event"?"🎯":"📋"} {m.title}</div>
                      <div style={{ fontSize:13, color:"var(--muted)" }}>{m.date} {m.time} · {m.location||""}</div>
                    </div>
                    <div style={{ fontSize:14, color:"var(--accent)", fontWeight:600 }}>詳情 ›</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Slack 設定 */}
      <div style={{ background:"var(--card)", border:"1px solid var(--border)", borderRadius:14, padding:"16px", marginTop:20 }}>
        <div style={{ fontSize:15, fontWeight:700, marginBottom:10, display:"flex", alignItems:"center", gap:8 }}>
          <span style={{ fontSize:22 }}>💬</span> Slack 會議提醒設定
        </div>
        <div style={{ fontSize:14, color:"var(--muted)", marginBottom:10, lineHeight:1.7 }}>
          設定 Slack Incoming Webhook URL 後，系統會在會議前 <strong style={{color:"var(--text)"}}>7 天、3 天、1 天</strong> 自動發送提醒至指定頻道。
        </div>
        <input
          value={slackWebhook}
          onChange={e => { setSlackWebhook(e.target.value); saveSlackWebhookFB(e.target.value); }}
          placeholder="https://hooks.slack.com/services/..."
          style={{ width:"100%", background:"var(--surf)", border:"1px solid var(--border)", borderRadius:10, color:"var(--text)", fontSize:14, padding:"12px 14px", outline:"none", fontFamily:"inherit", marginBottom:10, boxSizing:"border-box" }}
        />
        <div style={{ display:"flex", gap:8 }}>
          <button onClick={testSlack} style={{
            flex:1, padding:"11px", borderRadius:10, border:"1px solid var(--border)",
            background:"var(--surf)", color:"var(--text)", fontSize:14, fontWeight:600,
            cursor:"pointer", fontFamily:"inherit"
          }}>🔔 測試發送</button>
          <button onClick={async () => {
            if (!slackWebhook) return showToast("請先設定 Webhook","#ff5b79");
            showToast("檢查中...","#6b7494");
            try {
              const res = await fetch(`${BACKEND_URL}/check-meeting-reminders`, {
                method:"POST", headers:{"Content-Type":"application/json"},
                body: JSON.stringify({ webhookUrl: slackWebhook })
              });
              const data = await res.json();
              if (data.sent > 0) showToast(`已發送 ${data.sent} 則提醒`,"#00e5c3");
              else showToast("目前沒有需要發送的提醒","#6b7494");
            } catch { showToast("檢查失敗","#ff5b79"); }
          }} style={{
            flex:1, padding:"11px", borderRadius:10, border:"none",
            background:"linear-gradient(135deg,var(--accent),#00b89c)", color:"#fff", fontSize:14, fontWeight:700,
            cursor:"pointer", fontFamily:"inherit"
          }}>📨 立即檢查提醒</button>
        </div>
      </div>
    </div>
  );

  const baseTabs = [["dashboard","📊","任務"],["calendar","📅","行事曆"]];
  baseTabs.push(["upload","📄","上傳"]);
  baseTabs.push(["team","👥","成員"]);
  if (isAdmin) baseTabs.push(["reminders","⏰","提醒"]);
  const TABS = baseTabs;

  // ══════════════════════════════════════════════
  // ── 單一佈局（CSS media query 切換桌機/手機）──
  // ══════════════════════════════════════════════
  return (
    <>
      <style>{styleBlock}</style>
      <div ref={rootRef} className={`${isWide ? "mb-root mb-wide" : "mb-root"}${theme==="light"?" theme-light":""}`} style={{ fontFamily:"'Noto Sans TC',sans-serif", background:"var(--bg)", color:"var(--text)" }}>

        {/* 頂部欄 */}
        <div className="mb-topbar-inner" style={{ background:"var(--surf)", borderBottom:"1px solid var(--border)", padding:"13px 16px", display:"flex", alignItems:"center", justifyContent:"space-between", position:"sticky", top:0, zIndex:50 }}>
          <div style={{ display:"flex", alignItems:"center", gap:12 }}>
            <div className="mb-topbar-logo" style={{ width:36, height:36, borderRadius:10, background:"linear-gradient(135deg,#4f8cff,#00e5c3)", display:"flex", alignItems:"center", justifyContent:"center", fontSize:16 }}>📋</div>
            <div>
              <div className="mb-topbar-title" style={{ fontWeight:700, fontSize:24 }}>MeetBot</div>
              <div className="mb-topbar-sub" style={{ fontSize:14, color:"var(--muted)" }}>會議任務追蹤系統</div>
            </div>
          </div>
          <div style={{ display:"flex", alignItems:"center", gap:10, flexWrap:"wrap", justifyContent:"flex-end" }}>
            <div onClick={toggleTheme} style={{
              width:36, height:36, borderRadius:10, cursor:"pointer",
              background:"var(--card)", border:"1px solid var(--border)",
              display:"flex", alignItems:"center", justifyContent:"center",
              fontSize:18, transition:"all 0.2s"
            }}>{theme==="dark"?"☀️":"🌙"}</div>
            {currentUser && (
              <div onClick={() => { if(window.confirm("要切換使用者嗎？")) { setCurrentUser(""); localStorage.removeItem("meetbot-user"); localStorage.removeItem("meetbot-admin-auth"); }}} style={{
                display:"flex", alignItems:"center", gap:6, cursor:"pointer", padding:"3px 12px",
                borderRadius:20, background:"rgba(79,140,255,0.1)", border:"1px solid rgba(79,140,255,0.3)"
              }}>
                <Avatar name={currentUser} size={20}/>
                <span style={{ fontSize:14, fontWeight:600, color:"var(--accent)" }}>{currentUser}</span>
              </div>
            )}
            {urgentCount>0 && <div style={{ background:"rgba(255,91,121,0.15)", border:"1px solid var(--red)", color:"var(--red)", fontSize:14, fontWeight:700, padding:"3px 12px", borderRadius:20 }}>緊急 {urgentCount} 項</div>}
            <div style={{ background:"rgba(0,229,195,0.1)", border:"1px solid rgba(0,229,195,0.3)", color:"var(--green)", fontSize:14, fontWeight:700, padding:"3px 12px", borderRadius:20 }}>{pct}% 完成</div>
            <button onClick={()=>exportToWord(tasks)} style={{
              padding:"5px 14px", borderRadius:10, border:"1px solid var(--border)",
              background:"var(--card)", color:"var(--text)", fontSize:14, fontWeight:600,
              cursor:"pointer", fontFamily:"inherit", display:"flex", alignItems:"center", gap:5
            }}>📄 匯出 Word</button>
            <div style={{ display:"flex", alignItems:"center", gap:5, fontSize:14, color: !isOnline?"var(--orange)":syncing?"var(--accent)":"var(--muted)" }}>
              <div style={{ width:8, height:8, borderRadius:"50%", background: !isOnline?"var(--orange)":syncing?"var(--accent)":"var(--green)", animation: syncing?"pulse 1s infinite":"none" }}/>
              {!isOnline ? "離線" : syncing ? "同步中..." : syncLabel}
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
                cursor:"pointer", fontSize:15, fontWeight: tab===id ? 700 : 400,
                background: tab===id ? "rgba(79,140,255,0.12)" : "transparent",
                color: tab===id ? "var(--accent)" : "var(--muted)",
                border: tab===id ? "1px solid rgba(79,140,255,0.25)" : "1px solid transparent",
                transition:"all 0.2s"
              }}>
                <span style={{ fontSize:18 }}>{ic}</span>{lb}
              </div>
            ))}
          </div>

          {/* 內容區 */}
          <div className="mb-content-area" style={{ flex:1, minWidth:0 }}>

            {/* 頁籤列（手機才顯示，CSS 控制） */}
            <div className="mb-tabs">
              {TABS.map(([id,ic,lb])=>(
                <div key={id} onClick={()=>setTab(id)} style={{
                  flex:1, minWidth:68, textAlign:"center", padding:"10px 4px 8px", fontSize:14, cursor:"pointer",
                  color: tab===id ? "var(--accent)" : "var(--muted)",
                  borderBottom: tab===id ? "2.5px solid var(--accent)" : "2.5px solid transparent",
                  fontWeight: tab===id ? 700 : 400, transition:"all 0.2s", whiteSpace:"nowrap"
                }}><div style={{ fontSize:18, marginBottom:2 }}>{ic}</div>{lb}</div>
              ))}
            </div>

            {/* 頁面內容 */}
            {tab==="dashboard" && DashboardContent}
            {tab==="calendar"  && CalendarContent}
            {tab==="upload"    && <UploadContent/>}
            {tab==="team"      && <TeamContent/>}
            {tab==="reminders" && <RemindersContent/>}
          </div>
        </div>

        {/* 會議表單 Modal */}
        {showMeetingModal && <MeetingFormModal meeting={editingMeeting} onSave={addOrUpdateMeeting} onClose={()=>{ setShowMeetingModal(false); setEditingMeeting(null); }}/>}

        {/* 備註 Modal */}
        {editingTask && <NoteModal task={editingTask} onSave={saveNote} onClose={()=>setEditingTask(null)}/>}

        {/* 任務編輯 Modal */}
        {editingTaskFull && <TaskEditModal task={editingTaskFull} onSave={saveTaskEdit} onDelete={isAdmin ? deleteTask : null} onNotify={canSendReminders ? notifyTask : null} onClose={()=>setEditingTaskFull(null)} canSetPriority={isAdmin} currentUser={currentUser} canEdit={canEditTask(editingTaskFull)} allTasks={activeTasks}
          onConvertToRoutine={canManageRoutine ? (title, assignees) => {
            const list = Array.isArray(assignees) ? assignees.filter(Boolean) : [assignees].filter(Boolean);
            if (list.length === 0) list.push("");
            const newTasks = list.map((a, i) => ({ id: Date.now() + i, title, assignee: a }));
            const next = [...routineTasks, ...newTasks];
            setRoutineTasks(next);
            saveRoutineTasks(next);
            setEditingTaskFull(null);
            showToast(`已轉為例行任務（${newTasks.length} 條）`, "#a78bfa");
          } : null}
        />}

        {/* 會議詳情 Modal */}
        {viewingMeeting && <MeetingDetailModal
          meeting={viewingMeeting}
          relatedTasks={tasks.filter(t => t.meeting === viewingMeeting.title)}
          onEdit={canCreateMeeting ? () => { setViewingMeeting(null); setEditingMeeting(viewingMeeting); setShowMeetingModal(true); } : null}
          onDelete={canCreateMeeting ? () => { if(window.confirm("確定刪除此會議？")) { removeMeeting(viewingMeeting.id); setViewingMeeting(null); } } : null}
          onClose={() => setViewingMeeting(null)}
          onSavePrep={async (prep) => {
            const updated = {...viewingMeeting, prepChecklist: prep};
            setViewingMeeting(updated);
            setMeetings(prev => prev.map(m => m.id === viewingMeeting.id ? updated : m));
            await saveMeetingToFB(updated);
          }}
        />}

        {/* Toast */}
        {toast && (
          <div style={{ position:"fixed", bottom:28, left:"50%", transform:"translateX(-50%)", background:toast.color, color:"#fff", padding:"12px 24px", borderRadius:24, fontSize:15, fontWeight:600, zIndex:999, whiteSpace:"nowrap", boxShadow:"0 4px 20px rgba(0,0,0,0.4)", animation:"fadeUp 0.3s ease" }}>{toast.msg}</div>
        )}

        {/* 使用者身份選擇（首次進入） */}
        {!currentUser && (
          <div style={{
            position:"fixed", inset:0, background:"rgba(0,0,0,0.85)", zIndex:300,
            display:"flex", alignItems:"center", justifyContent:"center", padding:"20px"
          }}>
            <div style={{
              background:"var(--card)", border:"1px solid var(--border)", borderRadius:16,
              padding:"24px", width:"100%", maxWidth:400, display:"flex", flexDirection:"column", gap:16,
              maxHeight:"90vh", overflowY:"auto"
            }}>
              <div style={{ fontSize:24, fontWeight:700, textAlign:"center" }}>👋 歡迎使用 MeetBot</div>
              <div style={{ fontSize:15, color:"var(--muted)", textAlign:"center", lineHeight:1.6 }}>請選擇你的身份<br/>（用於權限識別與操作記錄）</div>

              {/* 密碼輸入面板 */}
              {adminAuthPending ? (
                <div style={{ display:"flex", flexDirection:"column", gap:12 }}>
                  <div style={{ display:"flex", alignItems:"center", gap:10 }}>
                    <Avatar name={adminAuthPending} size={34}/>
                    <div>
                      <div style={{ fontSize:16, fontWeight:700 }}>{adminAuthPending}</div>
                      <div style={{ fontSize:12, color:"var(--orange)" }}>管理者驗證</div>
                    </div>
                  </div>
                  <input
                    type="password" maxLength={6} autoFocus
                    placeholder="請輸入 6 位數密碼"
                    value={adminPwInput}
                    onChange={e => { setAdminPwInput(e.target.value.replace(/\D/g,"")); setAdminPwError(""); }}
                    onKeyDown={e => {
                      if (e.key === "Enter" && adminPwInput.length === 6) {
                        if (adminPwInput === ADMIN_PASSWORDS[adminAuthPending]) {
                          setCurrentUser(adminAuthPending);
                          localStorage.setItem("meetbot-user", adminAuthPending);
                          localStorage.setItem("meetbot-admin-auth", adminAuthPending);
                          setAdminAuthPending(null); setAdminPwInput(""); setAdminPwError("");
                        } else {
                          setAdminPwError("密碼錯誤");
                        }
                      }
                    }}
                    style={{
                      width:"100%", padding:"14px", borderRadius:12, fontSize:24, fontWeight:700,
                      textAlign:"center", letterSpacing:12, fontFamily:"'DM Mono',monospace",
                      border: `2px solid ${adminPwError ? "var(--red)" : "var(--accent)"}`,
                      background:"var(--bg)", color:"var(--text)", outline:"none", boxSizing:"border-box"
                    }}
                  />
                  {adminPwError && <div style={{ color:"var(--red)", fontSize:14, fontWeight:600, textAlign:"center" }}>{adminPwError}</div>}
                  <div style={{ display:"flex", gap:10 }}>
                    <button onClick={() => { setAdminAuthPending(null); setAdminPwInput(""); setAdminPwError(""); }} style={{
                      flex:1, padding:"12px", borderRadius:10, border:"1px solid var(--border)",
                      background:"var(--surf)", color:"var(--muted)", fontSize:15, fontWeight:600,
                      cursor:"pointer", fontFamily:"inherit"
                    }}>返回</button>
                    <button onClick={() => {
                      if (adminPwInput === ADMIN_PASSWORDS[adminAuthPending]) {
                        setCurrentUser(adminAuthPending);
                        localStorage.setItem("meetbot-user", adminAuthPending);
                        localStorage.setItem("meetbot-admin-auth", adminAuthPending);
                        setAdminAuthPending(null); setAdminPwInput(""); setAdminPwError("");
                      } else {
                        setAdminPwError("密碼錯誤");
                      }
                    }} disabled={adminPwInput.length !== 6} style={{
                      flex:2, padding:"12px", borderRadius:10, border:"none",
                      background: adminPwInput.length === 6 ? "linear-gradient(135deg,var(--accent),#00b89c)" : "var(--border)",
                      color: adminPwInput.length === 6 ? "#fff" : "var(--muted)",
                      fontSize:15, fontWeight:700, cursor: adminPwInput.length === 6 ? "pointer" : "default",
                      fontFamily:"inherit"
                    }}>確認登入</button>
                  </div>
                </div>
              ) : (
                <div style={{ display:"flex", flexDirection:"column", gap:8 }}>
                  {["蔡蕙芳","黃琴茹","吳承儒","張鈺微","陳佩研","吳亞璇","戴豐逸","許雅淇"].map(name => {
                    const roleLabel = getRoleLabel(name);
                    const roleColor = ADMINS.includes(name) ? "#ff9f43" : SPECIALISTS.includes(name) ? "#4f8cff" : TEAM_LEADS.includes(name) ? "#00e5c3" : OFFICERS.includes(name) ? "#a78bfa" : "#6b7494";
                    const roleBg = ADMINS.includes(name) ? "rgba(255,159,67,0.12)" : SPECIALISTS.includes(name) ? "rgba(79,140,255,0.12)" : TEAM_LEADS.includes(name) ? "rgba(0,229,195,0.12)" : OFFICERS.includes(name) ? "rgba(167,139,250,0.12)" : "rgba(107,116,148,0.10)";
                    const borderColor = ADMINS.includes(name) ? "rgba(255,159,67,0.35)" : SPECIALISTS.includes(name) ? "rgba(79,140,255,0.35)" : TEAM_LEADS.includes(name) ? "rgba(0,229,195,0.35)" : OFFICERS.includes(name) ? "rgba(167,139,250,0.35)" : "var(--border)";
                    return (
                      <div key={name} onClick={() => {
                        if (ADMINS.includes(name)) {
                          setAdminAuthPending(name); setAdminPwInput(""); setAdminPwError("");
                        } else {
                          setCurrentUser(name); localStorage.setItem("meetbot-user", name);
                        }
                      }} style={{
                        display:"flex", alignItems:"center", gap:12, padding:"13px 16px",
                        borderRadius:12, cursor:"pointer", background:"var(--surf)",
                        border:`1.5px solid ${borderColor}`, transition:"all 0.2s",
                        fontSize:16, fontWeight:500
                      }}>
                        <Avatar name={name} size={34}/>
                        <span>{name}</span>
                        <span style={{ marginLeft:"auto", fontSize:12, padding:"2px 8px", borderRadius:10, background:roleBg, color:roleColor, fontWeight:600 }}>{roleLabel}</span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </>
  );
}
