"""Pac-Man 進度動畫元件 — 顯示「吃 Word、吐 PDF」的工作樣態。

設計:
  ┌──── 進度面板 ─────────────────────────────────────────┐
  │                                                       │
  │  📘 王大明_領據     🟡    📕 周建青_明細             │
  │  📘 王大明_明細    Pac    📕 周建青_領據             │
  │  📘 (待轉)          ▶▶    📕 (已轉)                   │
  │                                                       │
  │  正在處理: 王大明_領據.docx → 王大明_領據.pdf        │
  │  進度 12/24 (50%)                                     │
  └───────────────────────────────────────────────────────┘

主要 API:
  PacManAnimator(parent)
  .start(total)                         開始一輪,總共 total 個檔案
  .feed(filename, output_filename=None) 推進一格(會閃光、嘴巴張合)
  .set_label(text)                      下方狀態文字
  .stop()                               結束循環(嘴巴停在閉合)
"""
from __future__ import annotations

import os
import sys
import tkinter as tk
from collections import deque
from PIL import Image, ImageTk


def _find_assets_dir() -> str | None:
    """支援 PyInstaller 打包後的 assets 路徑。"""
    candidates = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(os.path.join(meipass, "assets"))
        candidates.append(os.path.join(
            os.path.dirname(sys.executable), "assets"))
    candidates.append(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "assets"))
    for p in candidates:
        if os.path.isdir(p):
            return p
    return None


class PacManAnimator(tk.Frame):
    """嵌入到 CTkFrame 的純 tkinter 動畫面板。

    容器用 tk.Frame(不是 CTkFrame),因為 Canvas 要直接畫 PhotoImage,
    搭配 tk.Frame 行為比較單純。
    """

    BG = "#0f1419"           # 主背景(跟 dark theme 一致)
    PANEL_BG = "#1a2332"     # 內框背景
    BORDER = "#2c3e50"

    PACMAN_SIZE = 88
    DOC_SIZE = 60
    DOC_SPACING = 88        # 加大讓檔名(姓名)能完整顯示
    SPARKLE_SIZE = 60

    HEIGHT = 260             # 整個面板高(加大讓字夠空間)
    LANE_Y_OFFSET = 76       # 兩條跑道距頂端
    PACMAN_X = 0             # 由 _layout() 計算

    MAX_QUEUE_VISIBLE = 5    # 左右各最多顯示幾個檔案(配合放大字體)

    def __init__(self, master, **kwargs):
        super().__init__(master, bg=self.BG, **kwargs)

        # 內框(深色面板感)
        self.panel = tk.Frame(self, bg=self.PANEL_BG, bd=1,
                              relief="solid",
                              highlightbackground=self.BORDER,
                              highlightthickness=1)
        self.panel.pack(fill="x", padx=4, pady=4)

        self.canvas = tk.Canvas(
            self.panel, height=self.HEIGHT, bg=self.PANEL_BG,
            highlightthickness=0, bd=0)
        self.canvas.pack(fill="x", padx=8, pady=(8, 4))
        self.canvas.bind("<Configure>", lambda _e: self._render())

        # 下方狀態列
        self.status_var = tk.StringVar(value="待機中")
        self.progress_var = tk.StringVar(value="")
        bottom = tk.Frame(self.panel, bg=self.PANEL_BG)
        bottom.pack(fill="x", padx=12, pady=(2, 10))
        tk.Label(bottom, textvariable=self.status_var,
                 bg=self.PANEL_BG, fg="#52b3e2",
                 font=("Microsoft JhengHei UI", 14, "bold"),
                 anchor="w").pack(side="left")
        tk.Label(bottom, textvariable=self.progress_var,
                 bg=self.PANEL_BG, fg="#a0aec0",
                 font=("Microsoft JhengHei UI", 13),
                 anchor="e").pack(side="right")

        # 載入素材
        self._assets: dict[str, ImageTk.PhotoImage] = {}
        self._asset_dir = _find_assets_dir()
        self._load_assets()

        # 狀態
        self.total = 0
        self.done = 0
        self.queue_in: deque[str] = deque()    # 待處理(Word)
        self.queue_out: deque[str] = deque()   # 已產出(PDF)
        self._mouth_open = True
        self._sparkle_phase = 0   # 0=隱藏、1~3 漸漸消失
        self._anim_id: str | None = None
        self._sparkle_id: str | None = None

        # 啟動嘴巴循環(在沒在跑時也讓它一開一合,顯示「待命」)
        self._tick_mouth()

    # ─── 載入素材 ───
    def _load_assets(self):
        if not self._asset_dir:
            return
        files = {
            "pacman_open": ("pacman_open.png", self.PACMAN_SIZE),
            "pacman_close": ("pacman_close.png", self.PACMAN_SIZE),
            "icon_word": ("icon_word.png", self.DOC_SIZE),
            "icon_pdf": ("icon_pdf.png", self.DOC_SIZE),
            "sparkle": ("sparkle.png", self.SPARKLE_SIZE),
            "ghost_red": ("ghost_red.png", self.DOC_SIZE),
            "ghost_blue": ("ghost_blue.png", self.DOC_SIZE),
            "ghost_white": ("ghost_white.png", self.DOC_SIZE),
        }
        for key, (fname, size) in files.items():
            path = os.path.join(self._asset_dir, fname)
            if not os.path.exists(path):
                continue
            try:
                img = Image.open(path).convert("RGBA")
                # 為了等比例顯示,resize 成正方形大小
                img = img.resize((size, size), Image.LANCZOS)
                self._assets[key] = ImageTk.PhotoImage(img)
            except Exception as e:
                print(f"[PacManAnimator] 載入 {fname} 失敗: {e}")

    # ─── 公開 API ───
    def start(self, total: int, todo_filenames: list[str] | None = None):
        """重設,開始一輪。

        total: 預期會推進的次數
        todo_filenames: 可選,給定後右側 in-queue 會用實際檔名顯示。
            沒給就用「(待轉)」佔位。
        """
        self.total = max(1, total)
        self.done = 0
        self.queue_in.clear()
        self.queue_out.clear()
        if todo_filenames:
            for f in todo_filenames:
                self.queue_in.append(f)
        else:
            for _ in range(min(total, self.MAX_QUEUE_VISIBLE)):
                self.queue_in.append("")
        self._update_progress_var()
        self.status_var.set("開始處理…")
        self._render()

    def feed(self, in_name: str = "", out_name: str = ""):
        """推進一格 — Pac-Man 吃掉 in_name、吐出 out_name。

        會觸發閃光特效。in_name/out_name 給空字串會用佔位顯示。
        """
        self.done += 1
        # 從待處理拿掉一個(若 queue_in 還有元素,優先用它);
        # 用 in_name 取代,確保下次 render 該位置不再出現
        if self.queue_in:
            self.queue_in.popleft()
        # 推進到 queue_out 最前(最新出現在最靠近 Pac-Man)
        self.queue_out.appendleft(out_name)
        # 維持顯示數量
        while len(self.queue_out) > self.MAX_QUEUE_VISIBLE:
            self.queue_out.pop()

        # 觸發閃光
        self._sparkle_phase = 3
        if self._sparkle_id:
            self.after_cancel(self._sparkle_id)
        self._sparkle_id = self.after(80, self._tick_sparkle)

        self._update_progress_var()
        self.status_var.set(self._format_status(in_name, out_name))
        self._render()

    def set_label(self, text: str):
        self.status_var.set(text)

    def stop(self, finished: bool = True):
        """結束。finished=True 顯示完成、False 顯示中止。"""
        if self._anim_id:
            self.after_cancel(self._anim_id)
            self._anim_id = None
        if self._sparkle_id:
            self.after_cancel(self._sparkle_id)
            self._sparkle_id = None
        self._sparkle_phase = 0
        self._mouth_open = False
        if finished:
            self.status_var.set(f"✓ 全部完成 ({self.done}/{self.total})")
        self._render()

    # ─── 內部:嘴巴循環 + 閃光 ───
    def _tick_mouth(self):
        self._mouth_open = not self._mouth_open
        self._render()
        self._anim_id = self.after(160, self._tick_mouth)

    def _tick_sparkle(self):
        self._sparkle_phase -= 1
        if self._sparkle_phase < 0:
            self._sparkle_phase = 0
        self._render()
        if self._sparkle_phase > 0:
            self._sparkle_id = self.after(100, self._tick_sparkle)
        else:
            self._sparkle_id = None

    # ─── 渲染 ───
    def _render(self):
        c = self.canvas
        c.delete("all")
        w = c.winfo_width()
        h = self.HEIGHT
        if w <= 1:
            return

        cx = w // 2
        cy = self.LANE_Y_OFFSET + self.PACMAN_SIZE // 2

        # 中央 Pac-Man
        pac_key = "pacman_open" if self._mouth_open else "pacman_close"
        if pac_key in self._assets:
            c.create_image(cx, cy, image=self._assets[pac_key])
        else:
            # fallback 黃色圓
            r = self.PACMAN_SIZE // 2
            c.create_oval(cx - r, cy - r, cx + r, cy + r,
                          fill="#FFEB3B", outline="")

        # 左側待處理(Word)— 從 Pac-Man 往左排
        self._render_queue_left(cx, cy)
        # 右側已轉換(PDF)— 從 Pac-Man 往右排
        self._render_queue_right(cx, cy)

        # 閃光(在 Pac-Man 嘴巴位置)
        if self._sparkle_phase > 0 and "sparkle" in self._assets:
            sx = cx + self.PACMAN_SIZE // 2 - 8  # 偏右側嘴巴
            sy = cy
            c.create_image(sx, sy, image=self._assets["sparkle"])

        # 中央下方:檔名 / 進度的另一種顯示(在 canvas 內,會被 status_var 蓋掉)
        # 直接畫一條微亮的橫線當「跑道」感
        line_y = cy + self.PACMAN_SIZE // 2 + 10
        c.create_line(20, line_y, w - 20, line_y,
                      fill="#2c3e50", width=1)

        # 標題:左「待轉 Word」、右「已轉 PDF」
        c.create_text(20, 18,
                      text="📥 待處理",
                      anchor="w", fill="#7fc4e6",
                      font=("Microsoft JhengHei UI", 13, "bold"))
        c.create_text(w - 20, 18,
                      text="📤 已完成",
                      anchor="e", fill="#e88989",
                      font=("Microsoft JhengHei UI", 13, "bold"))

    def _render_queue_left(self, cx: int, cy: int):
        """左側 Word 隊列。最近的(下一個被吃)貼近 Pac-Man。"""
        c = self.canvas
        word_img = self._assets.get("icon_word")
        gap = self.PACMAN_SIZE // 2 + 26
        for i, name in enumerate(self.queue_in):
            x = cx - gap - i * self.DOC_SPACING
            if x < 30:
                break
            if word_img:
                c.create_image(x, cy, image=word_img)
            else:
                c.create_rectangle(x - 22, cy - 22, x + 22, cy + 22,
                                   fill="#2B579A", outline="#52b3e2")
                c.create_text(x, cy, text="W", fill="#fff",
                              font=("Microsoft JhengHei UI", 12, "bold"))
            self._draw_filename(x, cy + self.DOC_SIZE // 2 + 12, name,
                                anchor="n")

    def _render_queue_right(self, cx: int, cy: int):
        """右側 PDF 隊列。剛吐出的貼近 Pac-Man。"""
        c = self.canvas
        pdf_img = self._assets.get("icon_pdf")
        gap = self.PACMAN_SIZE // 2 + 26
        for i, name in enumerate(self.queue_out):
            x = cx + gap + i * self.DOC_SPACING
            w = c.winfo_width()
            if x > w - 30:
                break
            if pdf_img:
                c.create_image(x, cy, image=pdf_img)
            else:
                c.create_rectangle(x - 22, cy - 22, x + 22, cy + 22,
                                   fill="#E53935", outline="#ff6e6e")
                c.create_text(x, cy, text="PDF", fill="#fff",
                              font=("Microsoft JhengHei UI", 9, "bold"))
            self._draw_filename(x, cy + self.DOC_SIZE // 2 + 12, name,
                                anchor="n")

    def _draw_filename(self, x: int, y: int, name: str, anchor: str = "n"):
        if not name:
            return
        # 圖示下方只顯示「姓名」(檔名通常是 {姓名}_明細領據_{類別}.pdf,
        # 取第一段就好,完整檔名留給底部狀態列)
        stem = os.path.splitext(name)[0]
        display = stem.split("_")[0] if "_" in stem else stem
        if len(display) > 6:
            display = display[:5] + "…"
        self.canvas.create_text(
            x, y, text=display, anchor=anchor,
            fill="#dde6ed",
            font=("Microsoft JhengHei UI", 12, "bold"))

    # ─── 狀態文字 ───
    def _format_status(self, in_name: str, out_name: str) -> str:
        if in_name and out_name:
            return f"處理中:{in_name} → {out_name}"
        if out_name:
            return f"剛產出:{out_name}"
        if in_name:
            return f"處理中:{in_name}"
        return "處理中…"

    def _update_progress_var(self):
        if self.total <= 0:
            self.progress_var.set("")
            return
        pct = int(round(100 * self.done / self.total))
        self.progress_var.set(f"{self.done}/{self.total}  ({pct}%)")
