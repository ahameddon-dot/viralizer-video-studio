import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parent
PDF_DIR = Path(os.getenv("APP_DATA_DIR", str(ROOT / "output"))) / "pdf"
PDF_DIR.mkdir(parents=True, exist_ok=True)


def _label(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", " ", value).replace("_", " ").strip().title()


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def build_viralizer_pdf(topic: str, payload: dict[str, Any]) -> Path:
    safe_name = re.sub(r"[^a-zA-Z0-9]+", "-", topic).strip("-")[:60] or "viralizer-report"
    path = PDF_DIR / f"{safe_name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.pdf"
    styles = getSampleStyleSheet()
    title = ParagraphStyle("Title", parent=styles["Title"], textColor=colors.HexColor("#5B21B6"), alignment=TA_CENTER, spaceAfter=10)
    heading = ParagraphStyle("Heading", parent=styles["Heading2"], textColor=colors.HexColor("#6D28D9"), spaceBefore=10, spaceAfter=6)
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=9.5, leading=13, spaceAfter=5)
    small = ParagraphStyle("Small", parent=body, fontSize=8, textColor=colors.HexColor("#666666"))
    story = [Paragraph("Viralizer Full Topic Report", title), Paragraph(escape(topic), styles["Heading1"]), Paragraph(f"Generated from Viralizer MCP on {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')}", small), Spacer(1, 8)]

    def add_value(key: str, value: Any, depth: int = 0) -> None:
        if value in (None, "", [], {}):
            return
        label = _label(str(key))
        if isinstance(value, dict):
            story.append(Paragraph(escape(label), heading if depth < 2 else styles["Heading3"]))
            for child_key, child_value in value.items():
                add_value(str(child_key), child_value, depth + 1)
        elif isinstance(value, list):
            story.append(Paragraph(escape(label), heading if depth < 2 else styles["Heading3"]))
            for index, item in enumerate(value, 1):
                if isinstance(item, dict):
                    if len(value) > 1:
                        story.append(Paragraph(f"<b>Item {index}</b>", body))
                    for child_key, child_value in item.items():
                        add_value(str(child_key), child_value, depth + 1)
                else:
                    story.append(Paragraph(f"- {escape(_text(item))}", body))
        else:
            text = escape(_text(value)).replace("\n", "<br/>")
            report_table = Table(
                [[Paragraph(f"<b>{escape(label)}</b>", body), Paragraph(text, body)]],
                colWidths=[43 * mm, 132 * mm],
            )
            report_table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#F3E8FF")),
                ("BOX", (0, 0), (-1, -1), 0.25, colors.HexColor("#D8B4FE")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E9D5FF")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(report_table)
            story.append(Spacer(1, 3))

    for key, value in payload.items():
        add_value(str(key), value)

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawString(18 * mm, 12 * mm, "Source: Viralizer MCP")
        canvas.drawRightString(192 * mm, 12 * mm, f"Page {document.page}")
        canvas.restoreState()

    SimpleDocTemplate(str(path), pagesize=A4, rightMargin=17 * mm, leftMargin=17 * mm, topMargin=17 * mm, bottomMargin=20 * mm, title=f"Viralizer Report - {topic}").build(story, onFirstPage=footer, onLaterPages=footer)
    return path
