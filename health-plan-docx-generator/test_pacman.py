"""PacMan 動畫測試 — 模擬真實核銷文件產生器的兩階段流程。

跑法:
    python test_pacman.py

會跳出一個視窗顯示 Pac-Man 動畫,自動跑兩階段:
  Step 1/2:產生 Word 文件中…  (5 階段,模擬 step_cb)
  Step 2/2:Word → PDF 轉檔中… (24 個檔,逐檔餵真實檔名)

按右上角 X 結束。也可以調 SPEED 變數改快慢(毫秒)。
"""
import customtkinter as ctk
from pacman_animator import PacManAnimator

# 動畫節奏(毫秒)
PHASE1_INTERVAL = 800   # Step 1 Word 產生階段每步間隔
PHASE2_INTERVAL = 500   # Step 2 PDF 轉檔每檔間隔
PHASE_GAP = 1500        # Step 1 → Step 2 的轉場延遲

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

app = ctk.CTk()
app.title("Pac-Man 動畫測試 — 模擬產生器兩階段流程")
app.geometry("1100x420")
app.configure(fg_color="#0f1419")

frame = ctk.CTkFrame(app, fg_color="#0f1419")
frame.pack(fill="both", expand=True, padx=20, pady=20)

# 一行說明
ctk.CTkLabel(
    frame,
    text="模擬:Step 1 產生 5 階段 Word → Step 2 轉 24 份 PDF",
    text_color="#a0aec0",
).pack(anchor="w", pady=(0, 8))

pac = PacManAnimator(frame)
pac.pack(fill="x")

# ── Step 1:Word 產生階段(對應 step_cb,沒具體檔名,只有階段數) ──
PHASE1_LABELS = [
    "處方費領據",
    "處方執行費領據",
    "處方處方費與處方執行費領據",
    "健康管理費領據",
    "處方處置費領據",
]

# ── Step 2:PDF 批次轉檔(逐檔餵真實檔名) ──
PEOPLE = ["王大明", "李美英", "周建青", "張容榕", "陳雅婷", "黃慧寧",
          "邱曉淳", "楊靜", "鄭之雅", "魏與慧", "黃翠玉", "黃鈺雯"]
CATEGORIES = ["處方處方費與處方執行費領據", "健康管理費領據"]
PHASE2_DOCX = []
for p in PEOPLE:
    for cat in CATEGORIES:
        PHASE2_DOCX.append(f"{p}_明細領據_{cat}.docx")


# ── Phase 1 ──
def start_phase1():
    # output_icon='word':此階段產生的也是 Word docx,所以右側用 Word 圖示
    pac.start(len(PHASE1_LABELS), PHASE1_LABELS, output_icon="word")
    pac.set_label("Step 1/2:產生 Word 文件中…")
    app.after(PHASE1_INTERVAL, feed_phase1, 0)


def feed_phase1(idx):
    if idx >= len(PHASE1_LABELS):
        # Phase 1 完,休息一下進 Phase 2
        pac.set_label("Step 1 完成,準備 PDF 轉檔…")
        app.after(PHASE_GAP, start_phase2)
        return
    label = PHASE1_LABELS[idx]
    # 直接用階段名稱當「檔名」(沒副檔名,_draw_filename 會直接顯示)
    pac.feed(in_name=label, out_name=label)
    app.after(PHASE1_INTERVAL, feed_phase1, idx + 1)


# ── Phase 2 ──
def start_phase2():
    # output_icon='pdf'(預設):右側用紅色 PDF 圖示
    pac.start(len(PHASE2_DOCX), PHASE2_DOCX, output_icon="pdf")
    pac.set_label("Step 2/2:Word → PDF 轉檔中…")
    app.after(PHASE2_INTERVAL, feed_phase2, 0)


def feed_phase2(idx):
    if idx >= len(PHASE2_DOCX):
        pac.stop(finished=True)
        return
    in_name = PHASE2_DOCX[idx]
    out_name = in_name.replace(".docx", ".pdf")
    pac.feed(in_name, out_name)
    app.after(PHASE2_INTERVAL, feed_phase2, idx + 1)


# 啟動
app.after(800, start_phase1)
app.mainloop()
