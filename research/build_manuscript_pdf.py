"""Render the editable English manuscript as a clearly marked review PDF.

Run with the Codex bundled Python (ReportLab). This is a review layout, not
an ACM submission template. The Markdown manuscript remains the source.
"""
from __future__ import annotations
import hashlib
import json
import re
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT.parent / "output" / "pdf"


def clean(value):
    return (value.replace("\u2013", "-").replace("\u2014", "-").replace("\u2011", "-")
            .replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"'))


def markup(value):
    value = escape(clean(value))
    value = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", value)
    value = re.sub(r"`([^`]+)`", r'<font name="Courier" size="9">\1</font>', value)
    value = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<link href="\2" color="#254766">\1</link>', value)
    return value


def build():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    source = ROOT / "manuscript.md"
    target = OUTPUT / "cybersickness_forecasting_draft.pdf"
    doc = SimpleDocTemplate(str(target), pagesize=A4, rightMargin=21*mm, leftMargin=21*mm,
                            topMargin=20*mm, bottomMargin=20*mm,
                            title="When Does a Cybersickness Forecast Become an Actionable Warning?",
                            author="Research working draft - authors to be supplied",
                            subject="Retrospective feasibility; no human mitigation experiment")
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("PaperTitle", fontName="Times-Bold", fontSize=19, leading=22, spaceAfter=12))
    styles.add(ParagraphStyle("PaperBody", fontName="Times-Roman", fontSize=10.5, leading=14,
                              spaceAfter=7, allowWidows=0, allowOrphans=0, splitLongWords=True))
    styles.add(ParagraphStyle("PaperH2", fontName="Times-Bold", fontSize=13, leading=16,
                              spaceBefore=13, spaceAfter=7, keepWithNext=True))
    styles.add(ParagraphStyle("PaperH3", fontName="Times-Bold", fontSize=11, leading=14,
                              spaceBefore=8, spaceAfter=5, keepWithNext=True))
    styles.add(ParagraphStyle("PaperCaption", fontName="Times-Italic", fontSize=9, leading=11,
                              alignment=TA_CENTER, spaceAfter=10))
    styles.add(ParagraphStyle("PaperCell", fontName="Times-Roman", fontSize=9.5, leading=12))
    styles.add(ParagraphStyle("PaperRef", parent=styles["PaperBody"], fontSize=9.5, leading=12,
                              leftIndent=13, firstLineIndent=-13, spaceAfter=8))
    story, paragraph, image_number, table_number = [], [], 0, 0
    lines = source.read_text(encoding="utf-8").splitlines()
    references = False

    def flush():
        if paragraph:
            story.append(Paragraph(markup(" ".join(paragraph)), styles["PaperRef" if references else "PaperBody"]))
            paragraph.clear()

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            flush()
        elif line.startswith("# "):
            flush()
            story.append(Paragraph(markup(line[2:]), styles["PaperTitle"]))
        elif line.startswith("## "):
            flush()
            if line[3:] == "References":
                references = True
                story.append(PageBreak())
            story.append(Paragraph(markup(line[3:]), styles["PaperH2"]))
        elif line.startswith("### "):
            flush()
            story.append(Paragraph(markup(line[4:]), styles["PaperH3"]))
        elif line.startswith("| "):
            flush()
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                cells = [cell.strip() for cell in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r"[-: ]+", cell) for cell in cells):
                    rows.append([Paragraph(markup(cell), styles["PaperCell"]) for cell in cells])
                i += 1
            n = len(rows[0])
            widths = [doc.width*.48] + [doc.width*.52/(n-1)]*(n-1)
            first_header = rows[0][0].getPlainText()
            if first_header == "Horizon":
                widths = [doc.width*f for f in (.12, .28, .20, .20, .20)]
            table = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
            table.setStyle(TableStyle([("LINEABOVE",(0,0),(-1,0),.8,colors.black),
                                       ("LINEBELOW",(0,0),(-1,0),.5,colors.black),
                                       ("LINEBELOW",(0,-1),(-1,-1),.8,colors.black),
                                       ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#eff2f4")),
                                       ("VALIGN",(0,0),(-1,-1),"TOP"),
                                       ("TOPPADDING",(0,0),(-1,-1),6),
                                       ("BOTTOMPADDING",(0,0),(-1,-1),6)]))
            table_number += 1
            table_titles = {"Model": "Future-peak forecasts and sensor comparators",
                            "Horizon": "Secondary horizon analysis; retained cohorts differ",
                            "Policy": "Exploratory calibration-budget warning policies"}
            title = Paragraph(f"Table {table_number}. {table_titles.get(first_header, 'Participant macro results')}", styles["PaperCaption"])
            story.append(KeepTogether([Spacer(1,4), title, table, Spacer(1,10)]))
            continue
        elif line.startswith("!["):
            flush()
            match = re.fullmatch(r"!\[(.+)\]\((.+)\)", line)
            if not match:
                raise ValueError("Unsupported image markup")
            path = ROOT / match[2]
            figure = Image(str(path))
            scale = min(doc.width/figure.imageWidth, 83*mm/figure.imageHeight)
            figure.drawWidth, figure.drawHeight = figure.imageWidth*scale, figure.imageHeight*scale
            image_number += 1
            caption = Paragraph(markup(f"Figure {image_number}. {match[1]}"), styles["PaperCaption"])
            story.append(KeepTogether([Spacer(1,7), figure, Spacer(1,5), caption]))
        elif references and re.match(r"^\d+\.\s", line):
            flush()
            paragraph.append(line)
            flush()
        else:
            paragraph.append(line)
        i += 1
    flush()

    def furniture(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#4c5660"))
        canvas.drawString(doc.leftMargin, A4[1]-13*mm, "CYBERSICKNESS FORECASTING | RESEARCH WORKING DRAFT")
        canvas.drawRightString(A4[0]-doc.rightMargin, 12*mm, str(document.page))
        canvas.drawString(doc.leftMargin, 12*mm, "2026-10-15 | Retrospective evidence; mitigation efficacy untested")
        canvas.restoreState()

    doc.build(story, onFirstPage=furniture, onLaterPages=furniture)
    (OUTPUT / "build.json").write_text(json.dumps({"source": str(source),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "pdf_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "layout": "Review manuscript, not an ACM submission template"}, indent=2), encoding="utf-8")
    print(target)


if __name__ == "__main__":
    build()
