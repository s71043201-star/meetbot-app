"""健康台灣深耕計畫 — Word/PDF 核銷文件產生器

輸出結構：
    output/115年04月/
    ├── 處方費/          (Word + Excel)
    ├── 健康管理費/      (Word + Excel)
    ├── 處方處置費/      (每人合併 Word)
    └── PDF/
        ├── 處方費/
        ├── 健康管理費/
        └── 處方處置費/
            ├── 社會處方/
            │   └── 侯務葵.pdf
            ├── 營養處方/
            └── ...
"""

import argparse
import os
import sys
import glob

from reader import read_prescription_report
from templates.clone_fill import (
    generate_prescription_fee_from_template,
    generate_execution_fee_from_template,
)
from templates.clinic import (
    generate_prescription_fee_doc,
    generate_execution_fee_doc,
    generate_health_mgmt_doc,
)
from templates.executor import generate_executor_merged_docs
from receipt_reader import load_receipts_from_dir
from excel_writer import (
    read_raw_records,
    generate_prescription_fee_excel,
    generate_execution_fee_excel,
    generate_health_mgmt_excel,
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(SCRIPT_DIR, "word_templates")

DEFAULT_TEMPLATES = {
    "prescription": os.path.join(TEMPLATE_DIR, "處方費_template.docx"),
    "execution": os.path.join(TEMPLATE_DIR, "處方執行費_template.docx"),
}


def convert_to_pdf(docx_path, pdf_path):
    """Word 轉 PDF（使用絕對路徑避免 COM 錯誤）"""
    try:
        from docx2pdf import convert
        convert(os.path.abspath(docx_path), os.path.abspath(pdf_path))
        return True
    except Exception as e:
        print(f"  [WARN] PDF 轉換失敗: {os.path.basename(docx_path)} - {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="健康台灣深耕計畫 — Word/PDF 核銷文件產生器"
    )
    parser.add_argument("excel", help="處方紀錄 Excel 檔案路徑")
    parser.add_argument("--year", "-y", type=int, default=115,
                        help="申報年度（民國年，預設 115）")
    parser.add_argument("--month", "-m", type=int, default=4,
                        help="申報月份（預設 4）")
    parser.add_argument("--min-prescriptions", type=int, default=0,
                        help="健康管理費最低處方份數門檻（預設 0 = 全部）")
    parser.add_argument("--output", "-o", default="./output",
                        help="輸出目錄（預設: ./output）")
    parser.add_argument("--no-pdf", action="store_true",
                        help="不產生 PDF")
    parser.add_argument("--receipts-dir", default="",
                        help="舊領據資料夾路徑，自動帶入個人資料（如 D:/115年3月-領據/）")
    args = parser.parse_args()

    if not os.path.exists(args.excel):
        print(f"錯誤：找不到 Excel 檔案: {args.excel}")
        sys.exit(1)

    os.makedirs(args.output, exist_ok=True)

    print(f"讀取 Excel: {args.excel}")
    data = read_prescription_report(
        args.excel,
        report_year=args.year,
        report_month=args.month,
        min_prescriptions=args.min_prescriptions,
    )

    print(f"  醫師: {len(data.doctors)} | 診所: {len(data.health_mgmts)} | "
          f"執行人員: {len(data.executors)}")

    prefix = f"{data.report_year}年{data.report_month:02d}月"

    # 月份主資料夾
    month_dir = os.path.join(args.output, prefix)
    os.makedirs(month_dir, exist_ok=True)

    def subdir(name):
        d = os.path.join(month_dir, name)
        os.makedirs(d, exist_ok=True)
        return d

    def pdf_subdir(name):
        d = os.path.join(month_dir, "PDF", name)
        os.makedirs(d, exist_ok=True)
        return d

    gen_pdf = not args.no_pdf

    # 讀取舊領據個人資料
    receipt_lookup = {}
    if args.receipts_dir:
        print(f"讀取舊領據資料夾: {args.receipts_dir}")
        receipt_lookup = load_receipts_from_dir(args.receipts_dir)
        print(f"  找到 {len(receipt_lookup)} 筆舊領據記錄")

    # === Excel 統計檔 ===
    raw_records = read_raw_records(args.excel)
    presc_dir = subdir("處方費")

    generate_prescription_fee_excel(raw_records, prefix, presc_dir)
    generate_execution_fee_excel(raw_records, prefix, presc_dir)
    print(f"[OK] 處方費 Excel (2 份)")

    hm_dir = subdir("健康管理費")
    generate_health_mgmt_excel(raw_records, prefix, hm_dir)
    print(f"[OK] 健康管理費 Excel")

    # === 子資料夾 1: 處方費 Word ===
    if data.doctors:
        d = subdir("處方費")

        path1 = os.path.join(d, f"健康台灣深耕計畫_處方費-總表-{prefix}.docx")
        tmpl = DEFAULT_TEMPLATES["prescription"]
        if os.path.exists(tmpl):
            generate_prescription_fee_from_template(tmpl, data, path1)
        else:
            generate_prescription_fee_doc(data, path1)
        print(f"[OK] 處方費核銷總表")

        path2 = os.path.join(d, f"健康台灣深耕計畫_處方執行費核銷總表-{prefix}.docx")
        tmpl = DEFAULT_TEMPLATES["execution"]
        if os.path.exists(tmpl):
            generate_execution_fee_from_template(tmpl, data, path2)
        else:
            generate_execution_fee_doc(data, path2)
        print(f"[OK] 處方執行費核銷總表")

        if gen_pdf:
            pd = pdf_subdir("處方費")
            convert_to_pdf(path1, os.path.join(
                pd, f"健康台灣深耕計畫_處方費-總表-{prefix}.pdf"))
            convert_to_pdf(path2, os.path.join(
                pd, f"健康台灣深耕計畫_處方執行費核銷總表-{prefix}.pdf"))
            print(f"[OK] 處方費 PDF")

    # === 子資料夾 2: 健康管理費 Word ===
    if data.health_mgmts:
        d = subdir("健康管理費")
        path = os.path.join(d, f"健康台灣深耕計畫_健康管理費總表-{prefix}.docx")
        generate_health_mgmt_doc(data, path)
        print(f"[OK] 健康管理費總表")

        if gen_pdf:
            pd = pdf_subdir("健康管理費")
            convert_to_pdf(path, os.path.join(
                pd, f"健康台灣深耕計畫_健康管理費總表-{prefix}.pdf"))
            print(f"[OK] 健康管理費 PDF")

    # === 子資料夾 3: 處方處置費（每人合併 PDF）===
    if data.executors:
        d = subdir("處方處置費")
        generate_executor_merged_docs(data, d, also_pdf=gen_pdf,
                                      receipt_lookup=receipt_lookup)
        count = sum(1 for ex in data.executors
                    if ex.receipt and ex.receipt.amount > 0)
        print(f"[OK] 執行人員合併 PDF ({count} 份，按處方類型分類)")

    print(f"\n完成！輸出至: {month_dir}")


if __name__ == "__main__":
    main()
