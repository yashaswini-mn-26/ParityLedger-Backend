import io

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill(start_color="222833", end_color="222833", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=10)
WRAP = Alignment(wrap_text=True, vertical="top")

STATUS_FILL = {
    "verified": PatternFill(start_color="D8F5E3", end_color="D8F5E3", fill_type="solid"),
    "mismatch": PatternFill(start_color="FBD9DC", end_color="FBD9DC", fill_type="solid"),
    "pending": PatternFill(start_color="E8DCFB", end_color="E8DCFB", fill_type="solid"),
}


def _autosize(ws, widths):
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _header_row(ws, row_idx, headers):
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=row_idx, column=col, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT


def build_page_excel(page: dict) -> bytes:
    wb = Workbook()

    ws = wb.active
    ws.title = "Overview"
    ws.append(["Field", "Value"])
    _header_row(ws, 1, ["Field", "Value"])
    rows = [
        ("Page name", page.get("name", "")),
        ("Path", page.get("path", "")),
        ("Status", page.get("status", "")),
        ("Verdict", page.get("verdict", "")),
        ("Reviewed by", page.get("reviewed_by_name", "")),
        ("Reviewed date", (page.get("reviewed_date") or "")[:19]),
        ("Approved by", page.get("approved_by_name", "")),
        ("Approved date", (page.get("approved_date") or "")[:19]),
        ("Assigned to", page.get("assigned_to_name", "")),
    ]
    for r in rows:
        ws.append(r)
    for r in range(2, ws.max_row + 1):
        ws.cell(row=r, column=2).alignment = WRAP
    _autosize(ws, [18, 70])

    ws2 = wb.create_sheet("Queries")
    headers = ["API", "Type", "SQL", "Tables", "Columns set", "Max rows", "Notes"]
    _header_row(ws2, 1, headers)
    r = 2
    for a in page.get("apis", []):
        for q in a.get("queries", []):
            ws2.cell(row=r, column=1, value=a.get("name", ""))
            ws2.cell(row=r, column=2, value=q.get("type", ""))
            ws2.cell(row=r, column=3, value=q.get("sql", ""))
            ws2.cell(row=r, column=4, value=", ".join(q.get("tables", [])))
            ws2.cell(row=r, column=5, value=", ".join(q.get("columns", [])))
            ws2.cell(row=r, column=6, value=q.get("maxRows", ""))
            ws2.cell(row=r, column=7, value=q.get("notes", ""))
            for c in range(1, 8):
                ws2.cell(row=r, column=c).alignment = WRAP
            r += 1
    _autosize(ws2, [26, 10, 55, 22, 22, 22, 30])

    ws3 = wb.create_sheet("Workflow")
    _header_row(ws3, 1, ["Step #", "Description"])
    for i, step in enumerate(page.get("workflow", []), 1):
        ws3.append([i, step])
        ws3.cell(row=i + 1, column=2).alignment = WRAP
    _autosize(ws3, [8, 90])

    ws4 = wb.create_sheet("Comments")
    _header_row(ws4, 1, ["Author", "Role", "Date", "Text", "Has image"])
    for c in page.get("comments", []):
        ws4.append(
            [
                c.get("author_name", ""),
                c.get("author_role", ""),
                (c.get("created_at") or "")[:19],
                c.get("text", ""),
                "Yes" if c.get("image") else "No",
            ]
        )
    _autosize(ws4, [20, 12, 20, 60, 10])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_project_excel(project_name: str, pages: list) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Pages"
    headers = [
        "Page", "Path", "Status", "APIs", "Queries", "Tables",
        "Reviewed by", "Reviewed date", "Approved by", "Approved date", "Assigned to", "Verdict",
    ]
    _header_row(ws, 1, headers)
    for i, p in enumerate(pages, 2):
        apis = p.get("apis", [])
        total_q = sum(len(a.get("queries", [])) for a in apis)
        tables = set()
        for a in apis:
            for q in a.get("queries", []):
                tables.update(q.get("tables", []))
        row = [
            p.get("name", ""), p.get("path", ""), p.get("status", ""),
            len(apis), total_q, len(tables),
            p.get("reviewed_by_name", ""), (p.get("reviewed_date") or "")[:19],
            p.get("approved_by_name", ""), (p.get("approved_date") or "")[:19],
            p.get("assigned_to_name", ""), p.get("verdict", ""),
        ]
        for col, val in enumerate(row, 1):
            cell = ws.cell(row=i, column=col, value=val)
            cell.alignment = WRAP
            fill = STATUS_FILL.get(p.get("status"))
            if fill and col == 3:
                cell.fill = fill
    _autosize(ws, [30, 40, 12, 8, 9, 9, 18, 18, 18, 18, 18, 40])
    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
