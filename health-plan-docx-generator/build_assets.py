"""把 assets_raw/ 裡的原始 PNG 處理成程式要載入的最終素材。

處理項目:
  1. 去黑底:Pac-Man / Word 等帶深色背景的圖,用色階閾值 alpha key 成透明,
     保留外圍光暈漸層
  2. 裁掉透明邊距,讓圖貼齊內容邊界
  3. 統一尺寸:Pac-Man / Word / PDF / Ghost = 128x128,sparkle = 96x96
  4. 寫入 assets/ 給程式載入

跑法:python build_assets.py
"""
from __future__ import annotations

import os
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "assets_raw")
DST = os.path.join(ROOT, "assets")


def alpha_key_dark(img: Image.Image, threshold: int = 28,
                    soft_band: int = 24) -> Image.Image:
    """把暗色背景(亮度低於 threshold 的像素)alpha 化為透明。

    soft_band 內(threshold ~ threshold+soft_band)做漸進透明度,
    避免硬邊產生鋸齒,讓光暈邊緣自然漸層。
    """
    img = img.convert("RGBA")
    px = img.load()
    w, h = img.size
    high = threshold + soft_band
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            lum = (r * 299 + g * 587 + b * 114) // 1000  # ITU-R BT.601
            if lum <= threshold:
                px[x, y] = (r, g, b, 0)
            elif lum < high:
                # 漸進透明
                ratio = (lum - threshold) / soft_band
                new_a = int(a * ratio)
                px[x, y] = (r, g, b, new_a)
    return img


def alpha_key_white(img: Image.Image, threshold: int = 235,
                     soft_band: int = 20) -> Image.Image:
    """把白底/淺色背景的像素 alpha 化為透明。

    判斷準則:R/G/B 三色都高於 threshold (灰白色)就視為背景。
    threshold ~ threshold-soft_band 之間做漸進透明,讓邊緣不留鋸齒。
    用於處理 ChatGPT 把透明 checker pattern 烘焙成不透明白色像素的圖。
    """
    img = img.convert("RGBA")
    px = img.load()
    w, h = img.size
    low = threshold - soft_band
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            min_rgb = min(r, g, b)
            max_rgb = max(r, g, b)
            # 必須是「高亮度且接近灰色」(飽和度低)才當背景
            if min_rgb >= threshold and (max_rgb - min_rgb) < 25:
                px[x, y] = (r, g, b, 0)
            elif min_rgb >= low and (max_rgb - min_rgb) < 25:
                # 漸進透明
                ratio = 1.0 - (min_rgb - low) / soft_band
                new_a = int(a * ratio)
                px[x, y] = (r, g, b, new_a)
    return img


def trim_transparent(img: Image.Image, padding: int = 4) -> Image.Image:
    """裁掉四周完全透明的邊距,留 padding 像素的緩衝。"""
    img = img.convert("RGBA")
    bbox = img.getbbox()
    if bbox is None:
        return img
    left, top, right, bottom = bbox
    left = max(0, left - padding)
    top = max(0, top - padding)
    right = min(img.width, right + padding)
    bottom = min(img.height, bottom + padding)
    return img.crop((left, top, right, bottom))


def fit_square(img: Image.Image, size: int) -> Image.Image:
    """把圖縮到 size×size,保持長寬比,邊距用透明補齊。"""
    img = img.convert("RGBA")
    w, h = img.size
    scale = min(size / w, size / h)
    new_w, new_h = int(w * scale), int(h * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(img, ((size - new_w) // 2, (size - new_h) // 2), img)
    return canvas


def process(src_name: str, dst_name: str, *,
             remove_dark: bool = False,
             remove_white: bool = False,
             size: int = 128,
             dark_threshold: int = 28,
             dark_soft: int = 24,
             white_threshold: int = 235,
             white_soft: int = 20) -> None:
    src_path = os.path.join(SRC, src_name)
    dst_path = os.path.join(DST, dst_name)
    if not os.path.exists(src_path):
        print(f"  [skip] {src_name} 不存在")
        return
    img = Image.open(src_path)
    if remove_dark:
        img = alpha_key_dark(img, threshold=dark_threshold,
                             soft_band=dark_soft)
    if remove_white:
        img = alpha_key_white(img, threshold=white_threshold,
                              soft_band=white_soft)
    img = trim_transparent(img, padding=2)
    img = fit_square(img, size)
    img.save(dst_path, "PNG")
    flags = []
    if remove_dark:
        flags.append("去黑")
    if remove_white:
        flags.append("去白")
    flag_str = f" [{'+'.join(flags)}]" if flags else ""
    print(f"  [OK] {src_name} → {dst_name} ({size}x{size}){flag_str}")


def crop_ghost_blue_from_trio() -> None:
    """從三鬼合圖切藍鬼(紅鬼用單獨那張更乾淨,白鬼跟白底分不開放棄)。"""
    src_path = os.path.join(SRC, "ghosts_trio_raw.png")
    if not os.path.exists(src_path):
        print(f"  [skip] ghosts_trio_raw.png 不存在")
        return
    img = Image.open(src_path).convert("RGBA")
    w, h = img.size
    # 藍鬼在下半左
    blue_box = (0, h // 2 - 20, w // 2 + 10, h)
    sub = img.crop(blue_box)
    sub = alpha_key_white(sub, threshold=235, soft_band=20)
    sub = trim_transparent(sub, padding=4)
    sub = fit_square(sub, 128)
    sub.save(os.path.join(DST, "ghost_blue.png"), "PNG")
    print(f"  [OK] ghosts_trio_raw.png → ghost_blue.png (128x128) [去白+裁]")


def main():
    os.makedirs(DST, exist_ok=True)
    print(f"處理目錄:{SRC}")
    print(f"輸出目錄:{DST}")
    print()

    print("Pac-Man (去黑底)")
    process("pacman_open_raw.png", "pacman_open.png",
            remove_dark=True, size=128, dark_threshold=22, dark_soft=20)
    process("pacman_close_raw.png", "pacman_close.png",
            remove_dark=True, size=128, dark_threshold=22, dark_soft=20)

    print("\n圖示 (Word 去黑底、PDF 去白底 ChatGPT checker)")
    process("icon_word_raw.png", "icon_word.png",
            remove_dark=True, size=96, dark_threshold=22, dark_soft=20)
    process("icon_pdf_raw.png", "icon_pdf.png",
            remove_white=True, size=96)

    print("\n鬼魂 (紅鬼用獨立那張、藍鬼從三鬼切+去白底,白鬼放棄)")
    process("ghost_red_raw.png", "ghost_red.png",
            remove_white=True, size=128)
    crop_ghost_blue_from_trio()

    print("\n閃光特效 (去黑底)")
    process("sparkle_raw.png", "sparkle.png",
            remove_dark=True, size=96, dark_threshold=28, dark_soft=20)

    # 確認沒留下舊的 ghost_white
    old = os.path.join(DST, "ghost_white.png")
    if os.path.exists(old):
        os.remove(old)
        print(f"  [刪除] 舊的 ghost_white.png(白鬼跟白底分不開,放棄)")

    print("\n全部完成")


if __name__ == "__main__":
    main()
