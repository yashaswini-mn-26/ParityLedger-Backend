import base64
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image as RLImage,
    PageBreak,
)

STATUS_COLORS = {
    "verified": colors.HexColor("#1f9d58"),
    "mismatch": colors.HexColor("#d93025"),
    "pending": colors.HexColor("#7b3fe4"),
}


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle(name="H1", fontSize=18, spaceAfter=4, fontName="Helvetica-Bold"))
    ss.add(ParagraphStyle(name="Mono", fontName="Courier", fontSize=8.5, leading=11))
    ss.add(ParagraphStyle(name="SectionHead", fontSize=12.5, spaceBefore=14, spaceAfter=6, fontName="Helvetica-Bold"))
    ss.add(ParagraphStyle(name="Small", fontSize=9, textColor=colors.HexColor("#555555")))
    return ss


def _decode_image(data_url: str):
    try:
        if not data_url or "," not in data_url:
            return None
        header, b64 = data_url.split(",", 1)
        raw = base64.b64decode(b64)
        img = RLImage(io.BytesIO(raw))
        max_w = 240
        ratio = img.imageHeight / float(img.imageWidth)
        img.drawWidth = max_w
        img.drawHeight = max_w * ratio
        return img
    except Exception:
        return None


def build_page_pdf(page: dict, project_name: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=18 * mm, bottomMargin=18 * mm, leftMargin=16 * mm, rightMargin=16 * mm,
    )
    ss = _styles()
    story = []

    story.append(Paragraph(f"Parity Ledger — {project_name}", ss["Small"]))
    story.append(Paragraph(page.get("name", "Untitled page"), ss["H1"]))
    story.append(Paragraph(page.get("path", ""), ss["Mono"]))

    status = page.get("status", "pending")
    status_table = Table(
        [[status.upper()]],
        colWidths=[80],
    )
    status_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), STATUS_COLORS.get(status, colors.grey)),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(Spacer(1, 6))
    story.append(status_table)

    # Review / approval meta
    story.append(Paragraph("Review status", ss["SectionHead"]))
    meta_rows = [
        ["Reviewed by", page.get("reviewed_by_name") or "—", "Reviewed date", (page.get("reviewed_date") or "—")[:19]],
        ["Approved by", page.get("approved_by_name") or "—", "Approved date", (page.get("approved_date") or "—")[:19]],
        ["Assigned to", page.get("assigned_to_name") or "Unassigned", "", ""],
    ]
    meta_table = Table(meta_rows, colWidths=[80, 150, 80, 150])
    meta_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dddddd")),
            ]
        )
    )
    story.append(meta_table)

    story.append(Paragraph("Verdict", ss["SectionHead"]))
    story.append(Paragraph(page.get("verdict") or "No verdict written yet.", ss["Normal"]))

    # Workflow
    workflow = page.get("workflow") or []
    if workflow:
        story.append(Paragraph("Workflow", ss["SectionHead"]))
        for i, step in enumerate(workflow, 1):
            story.append(Paragraph(f"{i}. {step}", ss["Normal"]))

    # Tables touched
    apis = page.get("apis") or []
    tables = {}
    for a in apis:
        for q in a.get("queries", []):
            for t in q.get("tables", []):
                d = tables.setdefault(t, {"cols": set(), "S": 0, "I": 0, "U": 0, "D": 0})
                d["cols"].update(q.get("columns", []))
                d[q["type"][0]] += 1
    if tables:
        story.append(Paragraph("Tables touched", ss["SectionHead"]))
        rows = [["Table", "Columns updated", "S/I/U/D"]]
        for t, d in tables.items():
            rows.append([t, ", ".join(sorted(d["cols"])) or "read only", f"{d['S']}/{d['I']}/{d['U']}/{d['D']}"])
        t = Table(rows, colWidths=[130, 250, 80])
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#222833")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dddddd")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story.append(t)

    # APIs & queries
    if apis:
        story.append(Paragraph("APIs & queries", ss["SectionHead"]))
        for a in apis:
            story.append(Paragraph(a.get("name", ""), ss["Small"]))
            for q in a.get("queries", []):
                story.append(Paragraph(f"[{q['type']}]", ss["Small"]))
                story.append(Paragraph(q.get("sql", "").replace("\n", "<br/>"), ss["Mono"]))
                if q.get("notes"):
                    story.append(Paragraph(f"Note: {q['notes']}", ss["Small"]))
                story.append(Spacer(1, 6))

    # Comparison
    comp = page.get("comparison") or {}
    if comp.get("vbNotes") or comp.get("migNotes") or comp.get("vbImage") or comp.get("migImage"):
        story.append(PageBreak())
        story.append(Paragraph("VB original vs. migrated", ss["SectionHead"]))
        story.append(Paragraph("VB.NET original", ss["Small"]))
        story.append(Paragraph(comp.get("vbNotes") or "No notes.", ss["Normal"]))
        vb_img = _decode_image(comp.get("vbImage"))
        if vb_img:
            story.append(vb_img)
        story.append(Spacer(1, 10))
        story.append(Paragraph("Migrated (React/Django)", ss["Small"]))
        story.append(Paragraph(comp.get("migNotes") or "No notes.", ss["Normal"]))
        mig_img = _decode_image(comp.get("migImage"))
        if mig_img:
            story.append(mig_img)

    # Comments
    comments = page.get("comments") or []
    if comments:
        story.append(PageBreak())
        story.append(Paragraph("Review comments", ss["SectionHead"]))
        for c in comments:
            story.append(
                Paragraph(
                    f"<b>{c.get('author_name')}</b> ({c.get('author_role')}) — {(c.get('created_at') or '')[:19]}",
                    ss["Small"],
                )
            )
            if c.get("text"):
                story.append(Paragraph(c["text"], ss["Normal"]))
            img = _decode_image(c.get("image"))
            if img:
                story.append(img)
            story.append(Spacer(1, 8))

    doc.build(story)
    return buf.getvalue()
