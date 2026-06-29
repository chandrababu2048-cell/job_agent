"""
PDFAgent — converts tailored markdown resume to clean ATS-friendly PDF.
"""

import os
import re
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable
)
from reportlab.lib.enums import TA_CENTER


class PDFAgent:

    def generate(self, tailored_resume_md: str, output_path: str) -> str:
        """Convert markdown resume to PDF. Returns output_path."""
        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

        # Fix header and HTML entities before rendering
        tailored_resume_md = self._preprocess(tailored_resume_md)

        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            rightMargin=0.65 * inch,
            leftMargin=0.65 * inch,
            topMargin=0.60 * inch,
            bottomMargin=0.60 * inch,
        )

        # ── Styles ─────────────────────────────────────────────────────────────
        dark  = colors.HexColor("#1a1a2e")
        mid   = colors.HexColor("#444444")
        light = colors.HexColor("#666666")

        name_style = ParagraphStyle("Name", fontName="Helvetica-Bold",
                                    fontSize=18, textColor=dark,
                                    spaceAfter=2, alignment=TA_CENTER)
        contact_style = ParagraphStyle("Contact", fontName="Helvetica",
                                       fontSize=9, textColor=light,
                                       spaceAfter=6, alignment=TA_CENTER)
        h1_style = ParagraphStyle("H1", fontName="Helvetica-Bold",
                                  fontSize=11, textColor=dark,
                                  spaceBefore=8, spaceAfter=2)
        h2_style = ParagraphStyle("H2", fontName="Helvetica-Bold",
                                  fontSize=10, textColor=dark,
                                  spaceBefore=5, spaceAfter=1)
        h3_style = ParagraphStyle("H3", fontName="Helvetica-BoldOblique",
                                  fontSize=9.5, textColor=mid,
                                  spaceBefore=3, spaceAfter=1)
        body_style = ParagraphStyle("Body", fontName="Helvetica",
                                    fontSize=9.5, textColor=mid,
                                    spaceAfter=2, leading=13)
        bullet_style = ParagraphStyle("Bullet", fontName="Helvetica",
                                      fontSize=9.5, textColor=mid,
                                      leftIndent=12, spaceAfter=1, leading=13)
        divider_color = colors.HexColor("#cccccc")

        story = []
        lines = tailored_resume_md.strip().splitlines()
        i = 0
        first_h1 = True

        while i < len(lines):
            line = lines[i].rstrip()

            # Name (first # heading)
            if line.startswith("# ") and first_h1:
                name = line[2:].strip()
                story.append(Paragraph(name, name_style))
                first_h1 = False
                i += 1
                # Collect contact line(s) immediately after name
                contact_parts = []
                while i < len(lines) and not lines[i].startswith("#") and lines[i].strip():
                    part = lines[i].strip().lstrip(">").strip()
                    if part != "---":
                        contact_parts.append(part)
                    i += 1
                if contact_parts:
                    contact_text = "  ·  ".join(contact_parts)
                    contact_text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', contact_text)
                    story.append(Paragraph(contact_text, contact_style))
                story.append(HRFlowable(width="100%", thickness=1.5,
                                        color=dark, spaceAfter=4))
                continue

            # Section heading (##)
            if line.startswith("## "):
                text = line[3:].strip().upper()
                story.append(Spacer(1, 4))
                story.append(Paragraph(text, h1_style))
                story.append(HRFlowable(width="100%", thickness=0.5,
                                        color=divider_color, spaceAfter=3))
                i += 1
                continue

            # Sub-heading (###)
            if line.startswith("### "):
                text = line[4:].strip()
                text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
                story.append(Paragraph(text, h2_style))
                i += 1
                continue

            # Bullet point
            if line.startswith("- ") or line.startswith("* "):
                text = line[2:].strip()
                text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
                text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
                story.append(Paragraph(f"• {text}", bullet_style))
                i += 1
                continue

            # Bold line (job title / company)
            if line.startswith("**") and line.endswith("**"):
                text = line[2:-2].strip()
                story.append(Paragraph(text, h3_style))
                i += 1
                continue

            # Horizontal rule
            if line.strip() in ("---", "***", "___"):
                story.append(HRFlowable(width="100%", thickness=0.3,
                                        color=divider_color, spaceAfter=2))
                i += 1
                continue

            # Empty line
            if not line.strip():
                story.append(Spacer(1, 3))
                i += 1
                continue

            # Regular paragraph
            text = line.strip()
            text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
            text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
            if text:
                story.append(Paragraph(text, body_style))
            i += 1

        doc.build(story)
        return output_path

    def _preprocess(self, md: str) -> str:
        """Convert YAML frontmatter header to clean markdown; fix HTML entities."""
        lines = md.splitlines()

        yaml_keys = {"name", "location", "phone", "email", "linkedin", "github"}
        header    = {}
        body_start = 0

        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("#"):
                body_start = i
                break
            if ":" in stripped:
                key, _, val = stripped.partition(":")
                k = key.strip().lower()
                if k in yaml_keys:
                    header[k] = val.strip()
                    body_start = i + 1

        if header:
            name     = header.get("name", "")
            location = header.get("location", "")
            phone    = header.get("phone", "")
            email    = header.get("email", "")
            linkedin = header.get("linkedin", "")
            github   = header.get("github", "")

            contact_parts = [p for p in [location, phone, email, linkedin, github] if p]
            contact_line  = "  ·  ".join(contact_parts)

            new_header = f"# {name}\n{contact_line}\n\n---\n"
            body = "\n".join(lines[body_start:])
            md = new_header + body

        # Fix HTML entities and AT&T; bug
        md = (md.replace("&amp;", "&")
                .replace("&lt;", "<")
                .replace("&gt;", ">")
                .replace("&#39;", "'")
                .replace("&quot;", '"'))
        md = re.sub(r'AT&T;', 'AT&T', md)

        return md
