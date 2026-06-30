"""
PDFAgent — converts tailored markdown resume to ATS-clean PDF.
"""

import os
import re
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_LEFT


class PDFAgent:

    def generate(self, tailored_resume_md: str, output_path: str) -> str:
        """Convert markdown resume to PDF. Returns output_path."""
        os.makedirs(
            os.path.dirname(output_path) if os.path.dirname(output_path) else ".",
            exist_ok=True,
        )

        tailored_resume_md = self._preprocess(tailored_resume_md)

        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            rightMargin=0.65 * inch,
            leftMargin=0.65 * inch,
            topMargin=0.55 * inch,
            bottomMargin=0.55 * inch,
        )

        # ── Styles ────────────────────────────────────────────────────────────
        dark  = colors.HexColor("#1a1a2e")
        mid   = colors.HexColor("#333333")
        light = colors.HexColor("#555555")

        name_style = ParagraphStyle(
            "Name", fontName="Helvetica-Bold", fontSize=17,
            textColor=dark, spaceAfter=1, alignment=TA_CENTER,
        )
        contact_style = ParagraphStyle(
            "Contact", fontName="Helvetica", fontSize=8,
            textColor=light, spaceAfter=1, alignment=TA_CENTER, leading=11,
        )
        h1_style = ParagraphStyle(
            "H1", fontName="Helvetica-Bold", fontSize=10.5,
            textColor=dark, spaceBefore=7, spaceAfter=2, alignment=TA_LEFT,
        )
        h2_style = ParagraphStyle(
            "H2", fontName="Helvetica-Bold", fontSize=10,
            textColor=dark, spaceBefore=4, spaceAfter=0,
        )
        date_style = ParagraphStyle(
            "Date", fontName="Helvetica", fontSize=9,
            textColor=light, spaceBefore=0, spaceAfter=1,
        )
        body_style = ParagraphStyle(
            "Body", fontName="Helvetica", fontSize=9,
            textColor=mid, spaceAfter=1, leading=12,
        )
        bullet_style = ParagraphStyle(
            "Bullet", fontName="Helvetica", fontSize=9,
            textColor=mid, leftIndent=10, spaceAfter=1, leading=12,
        )
        divider_color = colors.HexColor("#cccccc")

        story    = []
        lines    = tailored_resume_md.strip().splitlines()
        i        = 0
        first_h1 = True
        in_education = False   # tracks whether we're inside the EDUCATION section

        while i < len(lines):
            line = lines[i].rstrip()

            # ── Name heading (first # line) ───────────────────────────────────
            if line.startswith("# ") and first_h1:
                name = line[2:].strip()
                story.append(Paragraph(self._xml(name), name_style))
                first_h1 = False
                i += 1

                # Collect contact fields immediately after name
                contact_fields = []
                while i < len(lines) and not lines[i].startswith("#") and lines[i].strip():
                    part = lines[i].strip().lstrip(">").strip()
                    if part not in ("---", "***"):
                        contact_fields.append(self._xml(part))
                    i += 1

                # Split into 2 lines so it never overflows
                if contact_fields:
                    mid_pt = (len(contact_fields) + 1) // 2
                    line1  = " · ".join(contact_fields[:mid_pt])
                    line2  = " · ".join(contact_fields[mid_pt:])
                    story.append(Paragraph(line1, contact_style))
                    if line2:
                        story.append(Paragraph(line2, contact_style))

                story.append(Spacer(1, 3))
                story.append(HRFlowable(width="100%", thickness=1.5,
                                        color=dark, spaceAfter=3))
                continue

            # ── Section heading ##  ────────────────────────────────────────────
            if line.startswith("## "):
                section_name = line[3:].strip().upper()
                in_education = "EDUCATION" in section_name
                text = self._xml(section_name)
                story.append(Spacer(1, 3))
                story.append(Paragraph(text, h1_style))
                story.append(HRFlowable(width="100%", thickness=0.5,
                                        color=divider_color, spaceAfter=2))
                i += 1
                continue

            # ── Sub-heading ###  (company name — only in non-education sections) ─
            if line.startswith("### ") and not in_education:
                text = self._fmt(line[4:].strip())
                story.append(Spacer(1, 3))
                story.append(Paragraph(text, h2_style))
                i += 1
                continue

            # ── Bold line  **Title | Dates**  ─────────────────────────────────
            if line.startswith("**") and line.endswith("**") and not in_education:
                text = self._fmt(line[2:-2].strip())
                story.append(Paragraph(text, date_style))
                i += 1
                continue

            # ── Pipe-separated experience line  Company | Title | Date  ───────
            # Only in non-education sections (avoid mis-parsing "Sacred Heart | GPA: 3.3")
            if "|" in line and not line.startswith("-") and not line.startswith("*") and not in_education:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 2:
                    company_text = self._fmt(parts[0])
                    rest         = " | ".join(parts[1:])
                    story.append(Spacer(1, 3))
                    story.append(Paragraph(company_text, h2_style))
                    story.append(Paragraph(self._xml(rest), date_style))
                    i += 1
                    continue

            # ── Bullet ────────────────────────────────────────────────────────
            if line.startswith("- ") or line.startswith("* "):
                text = self._fmt(line[2:].strip())
                story.append(Paragraph(f"• {text}", bullet_style))
                i += 1
                continue

            # ── HR ────────────────────────────────────────────────────────────
            if line.strip() in ("---", "***", "___"):
                story.append(HRFlowable(width="100%", thickness=0.3,
                                        color=divider_color, spaceAfter=2))
                i += 1
                continue

            # ── Empty line ────────────────────────────────────────────────────
            if not line.strip():
                story.append(Spacer(1, 2))
                i += 1
                continue

            # ── Regular paragraph ─────────────────────────────────────────────
            text = self._fmt(line.strip())
            if text:
                story.append(Paragraph(text, body_style))
            i += 1

        doc.build(story)
        return output_path

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _xml(self, text: str) -> str:
        """Escape text for reportlab's XML parser."""
        # Expand safe HTML entities first, then re-escape all bare & for XML
        text = (text.replace("&amp;", "&")
                    .replace("&lt;", "<")
                    .replace("&gt;", ">")
                    .replace("&#39;", "'")
                    .replace("&quot;", '"'))
        # Re-escape: & not already part of a valid XML entity → &amp;
        text = re.sub(r'&(?!(amp|lt|gt|quot|apos|#\d+);)', '&amp;', text)
        return text

    def _fmt(self, text: str) -> str:
        """Escape + convert **bold** and *italic* markdown to reportlab XML tags."""
        text = self._xml(text)
        text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'\*(.*?)\*',     r'<i>\1</i>', text)
        return text

    def _preprocess(self, md: str) -> str:
        """Convert YAML frontmatter to markdown heading + split contact into fields."""
        lines     = md.splitlines()
        yaml_keys = {"name", "location", "phone", "email", "linkedin", "github"}
        header    = {}
        body_start = 0

        for idx, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("#"):
                body_start = idx
                break
            if ":" in stripped:
                key, _, val = stripped.partition(":")
                k = key.strip().lower()
                if k in yaml_keys:
                    header[k] = val.strip()
                    body_start = idx + 1

        if not header:
            return md  # already in heading format

        name     = header.get("name", "")
        location = header.get("location", "")
        phone    = header.get("phone", "")
        email    = header.get("email", "")
        linkedin = header.get("linkedin", "")
        github   = header.get("github", "")

        # Each contact field on its own line — PDF renderer splits them into 2 rows
        contact_lines = "\n".join(p for p in [location, phone, email, linkedin, github] if p)
        body = "\n".join(lines[body_start:])
        return f"# {name}\n{contact_lines}\n\n---\n{body}"
