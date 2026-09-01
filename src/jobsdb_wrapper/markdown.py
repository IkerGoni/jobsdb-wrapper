"""HTML-to-Markdown conversion for job descriptions (stdlib only)."""

from __future__ import annotations

import re
from html.parser import HTMLParser

_BLOCK_TAGS = {
    "p",
    "div",
    "section",
    "article",
    "br",
    "li",
    "ul",
    "ol",
    "tr",
    "table",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
}


class _HTML2MD(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._list_stack: list[str] = []
        self._li_index = 0
        self._href: str | None = None

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if tag in ("ul", "ol"):
            self._list_stack.append(tag)
            self._li_index = 0
        elif tag == "li":
            self._li_index += 1
            indent = "  " * (len(self._list_stack) - 1)
            marker = (
                f"{self._li_index}. " if self._list_stack and self._list_stack[-1] == "ol" else "- "
            )
            self.out.append(f"\n{indent}{marker}")
        elif tag == "br":
            self.out.append("\n")
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("_")
        elif tag == "a":
            self._href = attrs_d.get("href")
            self.out.append("[")
        elif tag in _BLOCK_TAGS and tag not in ("li",):
            self.out.append("\n\n" if tag != "tr" else "\n")

    def handle_endtag(self, tag):
        if tag in ("ul", "ol"):
            if self._list_stack:
                self._list_stack.pop()
            self.out.append("\n")
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("_")
        elif tag == "a":
            if self._href:
                self.out.append(f"]({self._href})")
                self._href = None
            else:
                self.out.append("]")
        elif tag in _BLOCK_TAGS and tag not in ("li", "br"):
            self.out.append("\n")

    def handle_data(self, data):
        if data.strip() or (self.out and self.out[-1].endswith((" ", "_", "*", "]")) is False):
            self.out.append(data)

    def text(self) -> str:
        raw = "".join(self.out)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def html_to_markdown(html: str) -> str:
    """Convert job-description HTML to readable Markdown."""
    if not html:
        return ""
    parser = _HTML2MD()
    try:
        parser.feed(html)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", html)
        return re.sub(r"\s{2,}", " ", text).strip()
    md = parser.text()
    # heading promotion for common section titles
    for kw in (
        "About the role",
        "About us",
        "Responsibilities",
        "Requirements",
        "Qualifications",
        "Benefits",
        "Key Responsibilities",
        "What you'll do",
        "Why join us",
        "Job Description",
        "Skills and experience",
    ):
        pattern = re.compile(rf"^({re.escape(kw)})\s*:?\s*$", re.IGNORECASE | re.MULTILINE)
        md = pattern.sub(r"### \1", md)
    return md


def job_to_markdown(job) -> str:
    """Render a JobDetail as a complete Markdown document."""
    lines: list[str] = [f"# {job.title}", ""]
    meta = []
    if job.company:
        meta.append(f"**Company:** {job.company}")
    if job.location:
        meta.append(f"**Location:** {job.location}")
    if job.salary_label or (job.salary_min or job.salary_max):
        sal = job.salary_label or (
            f"{job.salary_currency} {job.salary_min:,}–{job.salary_max:,} / {job.salary_period}"
            if job.salary_min and job.salary_max and job.salary_currency
            else None
        )
        if sal:
            meta.append(f"**Salary:** {sal}")
    if job.categories:
        meta.append(
            f"**Classification:** {' > '.join(reversed(job.categories)) if len(job.categories) > 1 else ', '.join(job.categories)}"
        )
    if job.work_arrangements:
        meta.append(f"**Work arrangement:** {', '.join(job.work_arrangements)}")
    if job.listed_at:
        meta.append(f"**Listed:** {job.listed_at[:10]}")
    lines.extend(meta)
    lines += ["", f"**Source:** {job.web_url}", "", "---", ""]
    if job.abstract:
        lines += [f"> {job.abstract}", ""]
    body = html_to_markdown(job.content_html or "")
    lines.append(body or "(no description content)")
    lines.append("")
    return "\n".join(lines)
