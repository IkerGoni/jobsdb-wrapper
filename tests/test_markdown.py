import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jobsdb_wrapper import JobDetail, html_to_markdown, job_to_markdown  # noqa: E402


def _job(**kw):
    base = dict(
        id="94162495",
        title="Developer (Python & Vue.js)",
        company="ATHENA-AI CO., LTD.",
        advertiser_id="62536658",
        location="Taling Chan, Bangkok, TH",
        salary_label="THB 25,000 – 35,000 per month",
        salary_min=25000,
        salary_max=35000,
        salary_currency="THB",
        salary_period="monthly",
        categories=["Developers/Programmers (ICT)"],
        work_arrangements=["On-site"],
        listed_at="2026-08-24T04:15:31.387Z",
        abstract="Junior dev role.",
        content_html="<p>body</p>",
    )
    base.update(kw)
    return JobDetail(**base)


def test_html_to_markdown_basics():
    md = html_to_markdown("<p><strong>Bold</strong> and <em>italic</em></p>")
    assert "**Bold**" in md
    assert "_italic_" in md


def test_html_lists():
    md = html_to_markdown("<ul><li>one</li><li>two</li></ul>")
    assert "- one" in md
    assert "- two" in md


def test_html_links():
    md = html_to_markdown('<p>see <a href="https://x.co">site</a></p>')
    assert "[site](https://x.co)" in md


def test_heading_promotion():
    md = html_to_markdown("<p>Responsibilities</p><ul><li>x</li></ul>")
    assert "### Responsibilities" in md


def test_empty_content():
    assert html_to_markdown("") == ""
    assert html_to_markdown(None) == ""


def test_job_to_markdown_document():
    md = job_to_markdown(_job())
    assert "# Developer (Python & Vue.js)" in md
    assert "**Company:** ATHENA-AI CO., LTD." in md
    assert "**Salary:** THB 25,000 – 35,000 per month" in md
    assert "https://th.jobsdb.com/th/job/94162495" in md
    assert "> Junior dev role." in md
    assert "body" in md
