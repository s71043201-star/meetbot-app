"""快速 smoke test:跑 PacManAnimator 模擬 30 個檔案的轉換進度。"""
import customtkinter as ctk
from pacman_animator import PacManAnimator

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

app = ctk.CTk()
app.title("PacMan Test")
app.geometry("900x340")
app.configure(fg_color="#0f1419")

frame = ctk.CTkFrame(app, fg_color="#0f1419")
frame.pack(fill="both", expand=True, padx=20, pady=20)

pac = PacManAnimator(frame)
pac.pack(fill="x")

# 模擬 30 個檔案的轉換
todo = [f"{name}_明細領據.docx"
        for name in ("王大明", "李美英", "周建青", "張容榕",
                     "陳雅婷", "黃慧寧", "邱曉淳", "楊靜",
                     "鄭之雅", "魏與慧", "黃翠玉", "黃鈺雯")]
todo += [f"test_doc_{i}.docx" for i in range(18)]

pac.start(len(todo), todo)

idx = 0
def feed_one():
    global idx
    if idx >= len(todo):
        pac.stop(finished=True)
        return
    in_name = todo[idx]
    out_name = in_name.replace(".docx", ".pdf")
    pac.feed(in_name, out_name)
    idx += 1
    app.after(700, feed_one)

app.after(1000, feed_one)
app.mainloop()
