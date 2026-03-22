const express = require("express");
const axios = require("axios");

const app = express();
app.use(express.json({ limit: "10mb" }));

// ── CORS ──────────────────────────────────────
app.use((req, res, next) => {
  res.header("Access-Control-Allow-Origin", "*");
  res.header("Access-Control-Allow-Headers", "Content-Type");
  res.header("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
  if (req.method === "OPTIONS") return res.sendStatus(200);
  next();
});

const TOKEN = process.env.LINE_TOKEN;
const TEAM  = ["黃琴茹","蔡蕙芳","吳承儒","張鈺微","吳亞璇","許雅淇","戴豐逸","陳佩研"];

const MEMBERS = {
  "黃琴茹": "U858b6b722d9a01e1a927d07f8ffc65ed",
  "蔡蕙芳": "Uc05e7076d830f4f75ecc14a07b697e5c",
  "吳承儒": "U1307dd217e15b4ef777f8f0561c2e589",
  "張鈺微": "U7c71775e251051b61994eda22ddc2bec",
  "吳亞璇": "Ue69dbd040159f69636c08dfd9568aa63",
  "許雅淇": "U87efc2433f2ab838929cbfbdb2851748",
  "戴豐逸": "Uece4baaf97cfab39ad79c6ed0ee55d03",
  "陳佩研": "Uc8e074d50b3b20581945f5c6aca80d1d",
};

// ── 工具函式 ──────────────────────────────────
async function sendLine(userId, message) {
  if (!userId) return;
  await axios.post("https://api.line.me/v2/bot/message/push", {
    to: userId,
    messages: [{ type: "text", text: message }]
  }, { headers: { Authorization: `Bearer ${TOKEN}` } });
}

function daysLeft(deadline) {
  const today = new Date().toISOString().slice(0, 10);
  return Math.ceil((new Date(deadline) - new Date(today)) / 86400000);
}

// ── Webhook ───────────────────────────────────
app.post("/webhook", (req, res) => {
  const events = req.body.events || [];
  events.forEach(event => {
    if (event.type === "message") {
      console.log(`👤 User ID: ${event.source.userId} 說：${event.message.text}`);
    }
  });
  res.sendStatus(200);
});

// ── AI 解析代理（解決 CORS）────────────────────
app.post("/parse-meeting", async (req, res) => {
  const { text } = req.body;
  if (!text) return res.status(400).json({ error: "缺少 text" });

  const today_str = new Date().toISOString().slice(0, 10);
  try {
    const response = await axios.post("https://api.anthropic.com/v1/messages", {
      model: "claude-sonnet-4-20250514",
      max_tokens: 1000,
      messages: [{
        role: "user",
        content: `你是會議記錄分析助理。從以下會議紀錄中，找出所有「任務/行動項目」。
每個任務需包含：負責人、任務描述、截止日期。今天是 ${today_str}。
若日期只說「本週五」請換算成實際日期。若無法確定截止日期，設定為 7 天後。
負責人請從以下名單選最接近的：${TEAM.join("、")}。若無法對應，填「待指派」。

請只回傳 JSON 陣列，格式如下，不要有任何說明文字：
[{"title":"任務描述","assignee":"負責人","deadline":"YYYY-MM-DD"}]

會議紀錄：
${text}`
      }]
    }, {
      headers: {
        "Content-Type": "application/json",
        "x-api-key": process.env.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01"
      }
    });

    const raw = response.data.content?.find(b => b.type === "text")?.text || "[]";
    const items = JSON.parse(raw.replace(/```json|```/g, "").trim());
    res.json({ items });
  } catch (e) {
    console.error("AI 解析失敗:", e.message);
    res.status(500).json({ error: e.message });
  }
});

// ── LINE 提醒 ─────────────────────────────────
app.post("/check-reminders", async (req, res) => {
  const { tasks, reminders } = req.body;
  if (!tasks || !reminders) return res.status(400).json({ error: "缺少參數" });

  const hour = new Date().getHours();
  let sent = 0;

  for (const task of tasks) {
    if (task.done) continue;
    const dl = daysLeft(task.deadline);
    const userId = MEMBERS[task.assignee];
    if (!userId) continue;

    if (reminders.dayBefore?.on && dl === reminders.dayBefore.days && hour === reminders.dayBefore.hour) {
      await sendLine(userId,
        `📋 任務提醒 - MeetBot\n\n「${task.title}」\n\n負責人：${task.assignee}\n截止日期：${task.deadline}（剩 ${dl} 天）\n\n請記得完成 ✓`
      );
      sent++;
    }

    if (reminders.hourBefore?.on && dl === 0 && hour === (23 - reminders.hourBefore.hours)) {
      await sendLine(userId,
        `⚡ 緊急提醒 - MeetBot\n\n「${task.title}」\n\n負責人：${task.assignee}\n今天截止！剩約 ${reminders.hourBefore.hours} 小時\n\n請盡快完成 🔥`
      );
      sent++;
    }

    if (reminders.overdueAlert?.on && dl < 0) {
      await sendLine(userId,
        `🚨 逾期警示 - MeetBot\n\n「${task.title}」\n\n負責人：${task.assignee}\n已逾期 ${Math.abs(dl)} 天！\n\n請盡快處理 ⚠️`
      );
      sent++;
    }
  }

  res.json({ ok: true, sent });
});

// ── 測試 ──────────────────────────────────────
app.get("/test-me", async (req, res) => {
  try {
    await sendLine("Uece4baaf97cfab39ad79c6ed0ee55d03", "📋 MeetBot 測試成功！LINE Bot 已正常連線 🎉");
    res.send("訊息已發送，請查看你的 LINE ✅");
  } catch (e) {
    res.status(500).send("發送失敗：" + e.message);
  }
});

app.get("/", (req, res) => res.send("MeetBot 後端運作中 ✅"));

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`MeetBot 後端啟動，port ${PORT}`));
