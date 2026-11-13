"""Generate the demo AP dataset: a mock ERP database and a batch of supplier invoices.

Usage:
    python3 generate.py --out DIR [--expected FILE]

Writes DIR/erp.db (SQLite) and DIR/inbox/<intake-no>.{txt,csv,json}.
With --expected, also writes the answer key (which invoices should be approved
or flagged, and why). The answer key is for checking the agent's work and must
stay off the worker host.

Everything is fixed data, so every run produces the same dataset.
"""

import argparse
import csv
import io
import json
import sqlite3
from pathlib import Path

BUYER = "喬許科技股份有限公司"
BUYER_TAX_ID = "90123456"
TAX_RATE = 0.05

SUPPLIERS = {
    "S01": ("宏遠電子材料股份有限公司", "24567810", "月結 30 天"),
    "S02": ("大同精密五金有限公司", "53218846", "月結 45 天"),
    "S03": ("新竹包裝工業股份有限公司", "70413392", "月結 30 天"),
    "S04": ("台中化工原料行", "16820457", "貨到 15 天"),
    "S05": ("高雄物流設備股份有限公司", "84309921", "月結 60 天"),
    "S06": ("北辰辦公用品有限公司", "38175260", "月結 30 天"),
}

# po_no: (supplier, order_date, status, [(sku, description, qty, unit_price)])
PURCHASE_ORDERS = {
    "PO-2610-031": ("S03", "2026-10-08", "open", [("PK-1001", "瓦楞紙箱 40x30x30", 500, 28.0)]),
    "PO-2611-001": ("S01", "2026-11-02", "open", [("EC-2201", "電容 100uF 25V", 2000, 3.5), ("EC-3310", "電阻 10K 1%", 5000, 0.4)]),
    "PO-2611-002": ("S02", "2026-11-02", "open", [("HW-0450", "不鏽鋼螺絲 M4x12", 10000, 0.85)]),
    "PO-2611-003": ("S03", "2026-11-03", "open", [("PK-1001", "瓦楞紙箱 40x30x30", 800, 28.0), ("PK-2005", "氣泡布 1.2m x 50m", 20, 450.0)]),
    "PO-2611-004": ("S01", "2026-11-03", "open", [("EC-5102", "連接器 2.54mm 8P", 3000, 6.2), ("EC-2201", "電容 100uF 25V", 1000, 3.5)]),
    "PO-2611-005": ("S04", "2026-11-04", "open", [("CH-0080", "異丙醇 20L", 100, 1280.0)]),
    "PO-2611-006": ("S02", "2026-11-04", "open", [("HW-0712", "鋁擠型 2020 1m", 100, 185.0)]),
    "PO-2611-007": ("S06", "2026-11-05", "open", [("OF-3001", "A4 影印紙 80g (箱)", 40, 620.0)]),
    "PO-2611-008": ("S04", "2026-11-05", "open", [("CH-0125", "工業酒精 18L", 50, 960.0)]),
    "PO-2611-009": ("S05", "2026-11-05", "open", [("LG-7700", "塑膠棧板 1100x1100", 60, 890.0)]),
    "PO-2611-010": ("S06", "2026-11-06", "open", [("OF-4410", "碳粉匣 CF226X", 12, 3450.0)]),
    "PO-2611-011": ("S01", "2026-11-06", "open", [("EC-8800", "電源模組 12V 5A", 200, 415.0)]),
    "PO-2611-012": ("S02", "2026-11-06", "open", [("HW-0933", "墊片 M6 (包)", 7, 142.86)]),
    "PO-2611-013": ("S03", "2026-11-07", "cancelled", [("PK-3300", "封箱膠帶 48mm (箱)", 30, 720.0)]),
    "PO-2611-014": ("S04", "2026-11-07", "open", [("CH-0200", "切削油 200L", 4, 18500.0)]),
    "PO-2611-015": ("S05", "2026-11-09", "open", [("LG-7700", "塑膠棧板 1100x1100", 40, 890.0), ("LG-8120", "手推車 300kg", 6, 4200.0), ("LG-8300", "束帶 5m (條)", 100, 95.0)]),
    "PO-2611-016": ("S06", "2026-11-09", "open", [("OF-5005", "標籤貼紙 100x150 (捲)", 100, 210.0)]),
    "PO-2611-017": ("S02", "2026-11-10", "open", [("HW-0450", "不鏽鋼螺絲 M4x12", 5000, 0.85)]),
}

# (gr_no, po_no, line_no, received_qty, received_date)
GOODS_RECEIPTS = [
    ("GR-10301", "PO-2610-031", 1, 500, "2026-10-15"),
    ("GR-11001", "PO-2611-001", 1, 2000, "2026-11-06"),
    ("GR-11002", "PO-2611-001", 2, 5000, "2026-11-06"),
    ("GR-11003", "PO-2611-002", 1, 10000, "2026-11-06"),
    ("GR-11004", "PO-2611-003", 1, 800, "2026-11-07"),
    ("GR-11005", "PO-2611-003", 2, 20, "2026-11-07"),
    ("GR-11006", "PO-2611-004", 1, 3000, "2026-11-07"),
    ("GR-11007", "PO-2611-004", 2, 1000, "2026-11-07"),
    ("GR-11008", "PO-2611-005", 1, 60, "2026-11-09"),
    ("GR-11009", "PO-2611-006", 1, 80, "2026-11-09"),
    ("GR-11010", "PO-2611-007", 1, 40, "2026-11-09"),
    ("GR-11011", "PO-2611-008", 1, 50, "2026-11-10"),
    ("GR-11012", "PO-2611-009", 1, 60, "2026-11-10"),
    ("GR-11013", "PO-2611-010", 1, 12, "2026-11-10"),
    ("GR-11014", "PO-2611-012", 1, 7, "2026-11-10"),
    ("GR-11015", "PO-2611-013", 1, 30, "2026-11-10"),
    ("GR-11016", "PO-2611-014", 1, 4, "2026-11-11"),
    ("GR-11017", "PO-2611-015", 1, 40, "2026-11-11"),
    ("GR-11018", "PO-2611-015", 2, 6, "2026-11-11"),
    ("GR-11019", "PO-2611-015", 3, 100, "2026-11-11"),
    ("GR-11020", "PO-2611-016", 1, 50, "2026-11-11"),
    ("GR-11021", "PO-2611-016", 1, 50, "2026-11-12"),
    ("GR-11022", "PO-2611-017", 1, 5000, "2026-11-12"),
]

# Invoices that were already paid before this batch arrived.
PAYMENTS = [("KT30518842", "S03", "2026-10-30", 14700)]


def inv(file, number, supplier, po_no, date, lines, decision, reason=None, note="", **override):
    return {"file": file, "invoice_no": number, "supplier": supplier, "po_no": po_no, "date": date,
            "lines": lines, "decision": decision, "reason": reason, "note": note, **override}


# lines: (sku, description, qty, unit_price). Optional overrides: seller_tax_id, tax, line_amounts.
INVOICES = [
    inv("0001.txt", "AB20611001", "S01", "PO-2611-001", "2026-11-07",
        [("EC-2201", "電容 100uF 25V", 2000, 3.5), ("EC-3310", "電阻 10K 1%", 5000, 0.4)], "approve"),
    inv("0002.csv", "CD40611207", "S02", "PO-2611-002", "2026-11-07",
        [("HW-0450", "不鏽鋼螺絲 M4x12", 10000, 0.85)], "approve"),
    inv("0003.json", "KT30611455", "S03", "PO-2611-003", "2026-11-08",
        [("PK-1001", "瓦楞紙箱 40x30x30", 800, 28.0), ("PK-2005", "氣泡布 1.2m x 50m", 20, 450.0)], "approve"),
    inv("0004.txt", "AB20611019", "S01", "PO-2611-004", "2026-11-08",
        [("EC-5102", "連接器 2.54mm 8P", 3000, 6.39), ("EC-2201", "電容 100uF 25V", 1000, 3.5)],
        "exception", "PRICE_MISMATCH", "EC-5102 請款單價 6.39，採購單為 6.20"),
    inv("0005.csv", "MN70611302", "S04", "PO-2611-005", "2026-11-10",
        [("CH-0080", "異丙醇 20L", 60, 1280.0)], "approve",
        note="分批交貨：採購 100、已收 60、請款 60，應通過"),
    inv("0006.txt", "CD40611233", "S02", "PO-2611-006", "2026-11-10",
        [("HW-0712", "鋁擠型 2020 1m", 100, 185.0)],
        "exception", "QTY_EXCEEDS_RECEIPT", "請款 100，實收 80"),
    inv("0007.json", "QR50611078", "S05", "PO-2611-099", "2026-11-10",
        [("LG-9000", "堆高機電池 48V", 2, 68000.0)],
        "exception", "PO_NOT_FOUND", "系統中沒有 PO-2611-099"),
    inv("0008.txt", "KT30518842", "S03", "PO-2610-031", "2026-10-16",
        [("PK-1001", "瓦楞紙箱 40x30x30", 500, 28.0)],
        "exception", "DUPLICATE_INVOICE", "此發票號碼已於 2026-10-30 付款"),
    inv("0009.csv", "XY80611620", "S06", "PO-2611-007", "2026-11-10",
        [("OF-3001", "A4 影印紙 80g (箱)", 40, 620.0)], "approve"),
    inv("0010.txt", "MN70611318", "S04", "PO-2611-008", "2026-11-11",
        [("CH-0125", "工業酒精 18L", 50, 960.0)],
        "exception", "TAX_ERROR", "銷售額 48,000 的稅額應為 2,400，發票列 2,900", tax=2900),
    inv("0011.json", "QR50611085", "S05", "PO-2611-009", "2026-11-11",
        [("LG-7700", "塑膠棧板 1100x1100", 60, 890.0)], "approve"),
    inv("0012.txt", "XY80611634", "S06", "PO-2611-010", "2026-11-11",
        [("OF-4410", "碳粉匣 CF226X", 12, 3450.0)],
        "exception", "SUPPLIER_MISMATCH", "發票統編 38175620 與供應商主檔 38175260 不符",
        seller_tax_id="38175620"),
    inv("0013.csv", "AB20611040", "S01", "PO-2611-011", "2026-11-11",
        [("EC-8800", "電源模組 12V 5A", 200, 415.0)],
        "exception", "NOT_RECEIVED", "採購單存在但沒有任何收貨紀錄"),
    inv("0014.txt", "CD40611251", "S02", "PO-2611-012", "2026-11-11",
        [("HW-0933", "墊片 M6 (包)", 7, 142.86)], "approve",
        note="7 x 142.86 = 1000.02，發票列 1000，差額在 1 元容許範圍內，應通過",
        line_amounts=[1000]),
    inv("0015.json", "KT30611502", "S03", "PO-2611-013", "2026-11-11",
        [("PK-3300", "封箱膠帶 48mm (箱)", 30, 720.0)],
        "exception", "PO_NOT_OPEN", "採購單狀態為 cancelled"),
    inv("0016.csv", "AB20611001", "S01", "PO-2611-001", "2026-11-07",
        [("EC-2201", "電容 100uF 25V", 2000, 3.5), ("EC-3310", "電阻 10K 1%", 5000, 0.4)],
        "exception", "DUPLICATE_INVOICE", "與本批 0001.txt 發票號碼相同（重複送件）"),
    inv("0017.txt", "MN70611344", "S04", "PO-2611-014", "2026-11-12",
        [("CH-0200", "切削油 200L", 4, 18500.0)], "approve"),
    inv("0018.csv", "QR50611102", "S05", "PO-2611-015", "2026-11-12",
        [("LG-7700", "塑膠棧板 1100x1100", 40, 890.0), ("LG-8120", "手推車 300kg", 6, 4200.0), ("LG-8300", "束帶 5m (條)", 100, 95.0)],
        "approve"),
    inv("0019.txt", "XY80611655", "S06", "PO-2611-016", "2026-11-12",
        [("OF-5005", "標籤貼紙 100x150 (捲)", 100, 210.0)], "approve",
        note="分兩次收貨 50 + 50，合計 100，應通過"),
    inv("0020.json", "CD40611270", "S02", "PO-2611-017", "2026-11-12",
        [("HW-0460", "不鏽鋼螺絲 M4x16", 5000, 0.85)],
        "exception", "PO_LINE_NOT_FOUND", "採購單上是 HW-0450，發票請款的是 HW-0460"),
]


def money(invoice):
    amounts = invoice.get("line_amounts") or [round(q * p) for _, _, q, p in invoice["lines"]]
    subtotal = sum(amounts)
    tax = invoice.get("tax", round(subtotal * TAX_RATE))
    return amounts, subtotal, tax, subtotal + tax


def render_txt(i):
    name, tax_id, _ = SUPPLIERS[i["supplier"]]
    amounts, subtotal, tax, total = money(i)
    rows = "\n".join(
        f"  {sku:<10}{desc:<22}{qty:>8}{price:>12}{amt:>12,}"
        for (sku, desc, qty, price), amt in zip(i["lines"], amounts))
    return f"""統一發票（請款用）
發票號碼：{i['invoice_no']}
發票日期：{i['date']}
賣方：{name}
賣方統一編號：{i.get('seller_tax_id', tax_id)}
買方：{BUYER}
買方統一編號：{BUYER_TAX_ID}
採購單號：{i['po_no']}

  料號      品名                      數量        單價        金額
{rows}

銷售額合計：{subtotal:,}
營業稅 (5%)：{tax:,}
總計：{total:,}
"""


def render_csv(i):
    name, tax_id, _ = SUPPLIERS[i["supplier"]]
    amounts, subtotal, tax, total = money(i)
    buf = io.StringIO()
    w = csv.writer(buf)
    for key, value in [("invoice_no", i["invoice_no"]), ("invoice_date", i["date"]), ("seller", name),
                       ("seller_tax_id", i.get("seller_tax_id", tax_id)), ("buyer", BUYER),
                       ("po_no", i["po_no"]), ("subtotal", subtotal), ("tax", tax), ("total", total)]:
        w.writerow([key, value])
    w.writerow([])
    w.writerow(["sku", "description", "qty", "unit_price", "amount"])
    for (sku, desc, qty, price), amt in zip(i["lines"], amounts):
        w.writerow([sku, desc, qty, price, amt])
    return buf.getvalue()


def render_json(i):
    name, tax_id, _ = SUPPLIERS[i["supplier"]]
    amounts, subtotal, tax, total = money(i)
    doc = {
        "invoice_no": i["invoice_no"], "invoice_date": i["date"],
        "seller": {"name": name, "tax_id": i.get("seller_tax_id", tax_id)},
        "buyer": {"name": BUYER, "tax_id": BUYER_TAX_ID},
        "po_no": i["po_no"],
        "lines": [{"sku": sku, "description": desc, "qty": qty, "unit_price": price, "amount": amt}
                  for (sku, desc, qty, price), amt in zip(i["lines"], amounts)],
        "subtotal": subtotal, "tax": tax, "total": total,
    }
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


RENDERERS = {".txt": render_txt, ".csv": render_csv, ".json": render_json}


def build_db(path):
    path.unlink(missing_ok=True)
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE suppliers (supplier_id TEXT PRIMARY KEY, name TEXT, tax_id TEXT, payment_terms TEXT);
        CREATE TABLE purchase_orders (po_no TEXT PRIMARY KEY, supplier_id TEXT, order_date TEXT, status TEXT);
        CREATE TABLE po_lines (po_no TEXT, line_no INTEGER, sku TEXT, description TEXT, qty INTEGER,
                               unit_price REAL, PRIMARY KEY (po_no, line_no));
        CREATE TABLE goods_receipts (gr_no TEXT PRIMARY KEY, po_no TEXT, line_no INTEGER,
                                     received_qty INTEGER, received_date TEXT);
        CREATE TABLE payments (invoice_no TEXT PRIMARY KEY, supplier_id TEXT, paid_date TEXT, amount INTEGER);
    """)
    db.executemany("INSERT INTO suppliers VALUES (?,?,?,?)", [(k, *v) for k, v in SUPPLIERS.items()])
    for po_no, (supplier, date, status, lines) in PURCHASE_ORDERS.items():
        db.execute("INSERT INTO purchase_orders VALUES (?,?,?,?)", (po_no, supplier, date, status))
        db.executemany("INSERT INTO po_lines VALUES (?,?,?,?,?,?)",
                       [(po_no, n, *line) for n, line in enumerate(lines, 1)])
    db.executemany("INSERT INTO goods_receipts VALUES (?,?,?,?,?)", GOODS_RECEIPTS)
    db.executemany("INSERT INTO payments VALUES (?,?,?,?)", PAYMENTS)
    db.commit()
    db.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--expected", type=Path)
    args = parser.parse_args()

    inbox = args.out / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    for old in inbox.iterdir():
        old.unlink()
    build_db(args.out / "erp.db")
    for i in INVOICES:
        (inbox / i["file"]).write_text(RENDERERS[Path(i["file"]).suffix](i), encoding="utf-8")

    if args.expected:
        key = [{"file": i["file"], "invoice_no": i["invoice_no"], "decision": i["decision"],
                "reason": i["reason"], "note": i["note"], "total": money(i)[3]} for i in INVOICES]
        args.expected.parent.mkdir(parents=True, exist_ok=True)
        args.expected.write_text(json.dumps(key, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"wrote {args.out / 'erp.db'} and {len(INVOICES)} invoices to {inbox}")


if __name__ == "__main__":
    main()
