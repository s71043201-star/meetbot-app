"""Stepper 容器 + 中強度動畫工具

純 UI 元件，不碰任何業務邏輯。

提供：
- StepperHeader：頂部「[1·匯入] [2·申報] [3·文件]…」橫向標籤
- StepperContainer：管理 N 個步驟 frame，切換時做滑動 + 漸入
- AnimUtils：手動補幀的工具（顏色漸變、座標補間、寬度動畫）
"""

import customtkinter as ctk

# ── 設計常數 ──
STEP_DURATION_MS = 250          # 中速
ANIM_FRAMES = 14                # 350ms ÷ 16 ≈ 22ms/frame，順
STEP_SLIDE_PX = 40              # 滑動距離

# 顏色語義（白底版 v40）
COLORS = {
    "bg":          "#f7f7f5",
    "bg_card":     "#ffffff",
    "bg_card_hi":  "#f0f0ee",
    "border":      "#e5e5e3",
    "border_hi":   "#1a1a1a",
    "text":        "#1a1a1a",
    "text_dim":    "#6b6b6b",
    "text_muted":  "#999999",
    "accent":      "#1a1a1a",
    "accent_hi":   "#404040",
    "success":     "#16a34a",
    "danger":      "#dc2626",
    "warn":        "#d97706",
}


def _ease_out_cubic(t: float) -> float:
    return 1 - (1 - t) ** 3


def _lerp_color(c1: str, c2: str, t: float) -> str:
    """ '#RRGGBB' 線性插值 """
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


# ──────────────────────────────────────────────────────────
# Stepper Header（數字 + 標籤橫排）
# ──────────────────────────────────────────────────────────
class StepperHeader(ctk.CTkFrame):
    """頂部步驟指示器：[1·匯入] [2·申報] [3·文件]…

    每個 step 是一顆藥丸狀按鈕，可點擊（會回呼 on_step_click）。
    狀態：
      - active：藍底白字
      - done：綠邊白字
      - pending：透明灰邊
      - error（保留）：紅邊
    """

    def __init__(self, master, steps: list[str], on_step_click=None):
        super().__init__(master, fg_color="transparent")
        self.steps = steps
        self.on_step_click = on_step_click
        self._current = 0
        self._buttons: list[ctk.CTkButton] = []
        self._connectors: list[ctk.CTkFrame] = []
        self._step_status: list[str] = ["pending"] * len(steps)
        self._build()

    def _build(self):
        for idx, label in enumerate(self.steps):
            btn = ctk.CTkButton(
                self,
                text=f"{idx + 1}·{label}",
                height=34, width=110,
                corner_radius=17,
                fg_color="transparent",
                hover_color=COLORS["bg_card_hi"],
                text_color=COLORS["text_dim"],
                border_width=1,
                border_color=COLORS["border"],
                font=ctk.CTkFont(size=12, weight="bold"),
                command=(lambda i=idx: self._on_click(i))
                       if self.on_step_click else None,
            )
            btn.pack(side="left", padx=2)
            self._buttons.append(btn)

            if idx < len(self.steps) - 1:
                connector = ctk.CTkFrame(
                    self, fg_color=COLORS["border"],
                    width=14, height=2)
                connector.pack(side="left", padx=2)
                self._connectors.append(connector)

    def _on_click(self, idx: int):
        if self.on_step_click:
            self.on_step_click(idx)

    def set_current(self, idx: int):
        """跳到第 idx 步：之前的標 done、目前的標 active、之後的 pending。"""
        self._current = idx
        for i, btn in enumerate(self._buttons):
            if i < idx:
                self._step_status[i] = "done"
                btn.configure(
                    fg_color="transparent",
                    text_color=COLORS["success"],
                    border_color=COLORS["success"],
                    border_width=1,
                )
                # 連接線變綠
                if i < len(self._connectors):
                    self._connectors[i].configure(fg_color=COLORS["success"])
            elif i == idx:
                self._step_status[i] = "active"
                btn.configure(
                    fg_color=COLORS["accent"],
                    text_color="white",
                    border_color=COLORS["accent"],
                    border_width=1,
                )
                # 進入時做一次「邊框漸亮」脈衝
                self._pulse_button(btn)
            else:
                self._step_status[i] = "pending"
                btn.configure(
                    fg_color="transparent",
                    text_color=COLORS["text_dim"],
                    border_color=COLORS["border"],
                    border_width=1,
                )
                if i - 1 < len(self._connectors) and i - 1 >= idx:
                    self._connectors[i - 1].configure(
                        fg_color=COLORS["border"])

    def _pulse_button(self, btn: ctk.CTkButton):
        """active 按鈕做一次 brief 邊框光暈（顏色漸變模擬）。"""
        try:
            base = COLORS["accent"]
            hi = COLORS["accent_hi"]
            steps = 8

            def frame(i: int):
                if i > steps:
                    btn.configure(border_color=base)
                    return
                t = i / steps
                # 來回：0 → 1 → 0
                tt = t * 2 if t < 0.5 else (1 - t) * 2
                color = _lerp_color(base, hi, tt)
                btn.configure(border_color=color)
                btn.after(16, lambda: frame(i + 1))

            frame(0)
        except Exception:
            pass


# ──────────────────────────────────────────────────────────
# StepperContainer（步驟內容容器，管理 N 個 page frame）
# ──────────────────────────────────────────────────────────
class StepperContainer(ctk.CTkFrame):
    """N 個步驟內容 frame 的容器，切換時做滑動 + 顏色漸變。

    用法：
        container = StepperContainer(master, n_steps=6)
        page0 = container.page(0)   # 取得第 0 步的 frame，把 widget 塞進去
        page1 = container.page(1)
        ...
        container.show(0)           # 顯示第 0 步
        container.go(2, direction="forward")   # 動畫切到第 2 步
    """

    def __init__(self, master, n_steps: int, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.n_steps = n_steps
        self._pages: list[ctk.CTkScrollableFrame] = []
        self._current_idx = 0
        self._animating = False

        # 用 place 控制位置以便做滑動動畫
        for i in range(n_steps):
            page = ctk.CTkScrollableFrame(
                self, fg_color="transparent",
                scrollbar_button_color=COLORS["bg_card_hi"],
                scrollbar_button_hover_color=COLORS["accent"],
            )
            self._pages.append(page)
        # 預設只 place 第 0 頁
        if n_steps > 0:
            self._pages[0].place(relx=0, rely=0, relwidth=1, relheight=1)

    def page(self, idx: int) -> ctk.CTkScrollableFrame:
        return self._pages[idx]

    def current(self) -> int:
        return self._current_idx

    def show(self, idx: int):
        """無動畫切到第 idx 步。"""
        for i, p in enumerate(self._pages):
            if i == idx:
                p.place(relx=0, rely=0, relwidth=1, relheight=1)
            else:
                p.place_forget()
        self._current_idx = idx

    def go(self, idx: int, direction: str = "forward"):
        """動畫切到第 idx 步：
          - direction="forward"：舊頁向左滑出，新頁從右滑入
          - direction="backward"：相反
        """
        if self._animating or idx == self._current_idx:
            return
        if idx < 0 or idx >= self.n_steps:
            return

        self._animating = True
        old_page = self._pages[self._current_idx]
        new_page = self._pages[idx]

        # 計算容器寬度
        self.update_idletasks()
        w = self.winfo_width() or 800

        # 安置新頁到「畫面外」
        if direction == "forward":
            new_start_x = w
            old_end_x = -w
        else:
            new_start_x = -w
            old_end_x = w

        new_page.place(x=new_start_x, y=0, relwidth=1, relheight=1)

        frames = ANIM_FRAMES
        delay = STEP_DURATION_MS // frames

        def animate(i: int):
            if i > frames:
                # 收尾
                old_page.place_forget()
                new_page.place(relx=0, rely=0, relwidth=1, relheight=1)
                self._current_idx = idx
                self._animating = False
                return
            t = _ease_out_cubic(i / frames)
            # 新頁從 new_start_x → 0
            nx = int(new_start_x * (1 - t))
            # 舊頁從 0 → old_end_x
            ox = int(old_end_x * t)
            new_page.place(x=nx, y=0, relwidth=1, relheight=1)
            old_page.place(x=ox, y=0, relwidth=1, relheight=1)
            self.after(delay, lambda: animate(i + 1))

        animate(1)


# ──────────────────────────────────────────────────────────
# 數字 rolling 動畫（給進度百分比用）
# ──────────────────────────────────────────────────────────
def roll_number(label: ctk.CTkLabel, from_v: int, to_v: int,
                fmt: str = "{}%", duration_ms: int = 350):
    """把 label 的文字從 from_v rolling 到 to_v。"""
    if from_v == to_v:
        label.configure(text=fmt.format(to_v))
        return
    frames = max(6, abs(to_v - from_v))
    if frames > 24:
        frames = 24
    delay = max(15, duration_ms // frames)

    def step(i: int):
        if i > frames:
            label.configure(text=fmt.format(to_v))
            return
        t = _ease_out_cubic(i / frames)
        v = int(from_v + (to_v - from_v) * t)
        try:
            label.configure(text=fmt.format(v))
        except Exception:
            return
        label.after(delay, lambda: step(i + 1))

    step(1)


# ──────────────────────────────────────────────────────────
# log 展開/收起動畫（高度 0 ↔ target）
# ──────────────────────────────────────────────────────────
def animate_height(widget, target_h: int, duration_ms: int = 280,
                   on_done=None):
    """動畫改變 widget 的 height（給 CTkTextbox / CTkFrame 用）。"""
    try:
        cur = widget.winfo_height()
    except Exception:
        cur = 0
    if cur == target_h:
        if on_done:
            on_done()
        return
    frames = 12
    delay = duration_ms // frames

    def step(i: int):
        if i > frames:
            try:
                widget.configure(height=target_h)
            except Exception:
                pass
            if on_done:
                on_done()
            return
        t = _ease_out_cubic(i / frames)
        h = int(cur + (target_h - cur) * t)
        try:
            widget.configure(height=max(1, h))
        except Exception:
            return
        widget.after(delay, lambda: step(i + 1))

    step(1)
