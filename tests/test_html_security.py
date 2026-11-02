import html
import re
import pytest
from app import format_report_html, build_html_template


# ==============================================================================
# 1. TESTY WYKAZUJĄCE PROBLEM Z NIEOCZYSZCZONĄ TREŚCIĄ W ISTNIEJĄCYM KODZIE
# ==============================================================================

def test_baseline_vulnerability_allows_raw_script_tag_injection():
    """Demonstrates vulnerability in current app.py:

    format_report_html and build_html_template fail to sanitize <script> tags,
    allowing arbitrary JavaScript execution (Stored / Reflected XSS).
    """
    xss_payload = "<script>alert('XSS-ATTACK')</script>"
    rendered_content = format_report_html(xss_payload)

    # Vulnerability demonstration: raw <script> tag passes through completely unaltered
    assert "<script>alert('XSS-ATTACK')</script>" in rendered_content
    assert "&lt;script&gt;" not in rendered_content

    full_html = build_html_template(xss_payload, country="Polska")
    assert "<script>alert('XSS-ATTACK')</script>" in full_html


def test_baseline_vulnerability_allows_img_onerror_injection():
    """Demonstrates vulnerability with event handlers:

    e.g. <img src=x onerror=alert(1)> passes through unescaped.
    """
    img_payload = '<img src="invalid_image.png" onerror="alert(\'XSS\')">'
    rendered = format_report_html(img_payload)

    assert img_payload in rendered
    assert "&lt;img" not in rendered


def test_baseline_vulnerability_allows_style_and_iframe_injection():
    """Demonstrates vulnerability with dangerous HTML tags like <style> and <iframe>."""
    style_payload = "<style>body { display: none !important; }</style>"
    rendered_style = format_report_html(style_payload)
    assert style_payload in rendered_style

    iframe_payload = '<iframe src="/local/payload"></iframe>'
    rendered_iframe = format_report_html(iframe_payload)
    assert iframe_payload in rendered_iframe


def test_baseline_vulnerability_in_country_parameter():
    """Demonstrates vulnerability where country parameter is inserted into HTML

    template without escaping in <title> and .footer.
    """
    malicious_country = "Polska<script>alert('Country-XSS')</script>"
    full_html = build_html_template("Raport testowy", country=malicious_country)

    assert "<script>alert('Country-XSS')</script>" in full_html


# ==============================================================================
# 2. PROPOZYCJA MINIMALNEJ POPRAWKI I JEJ WERYFIKACJA TESTOWA
# ==============================================================================

def proposed_format_report_html(text: str) -> str:
    """PROPOSED MINIMAL FIX for app.format_report_html:

    1. html.escape(text, quote=True) first to neutralize all raw HTML tags/entities.
    2. Then apply the safe Markdown and citation regular expressions.
    """
    if not text:
        return ""

    # Krok 1: Sanityzacja / ucieczka niebezpiecznych znaków HTML
    text = html.escape(text, quote=True)

    # Krok 2: Bezpieczne formatowanie nagłówków i akcentów Markdown
    text = re.sub(r"^###\s+(.+)$", r"<h3>\1</h3>", text, flags=re.MULTILINE)
    text = re.sub(r"^##\s+(.+)$", r"<h2>\1</h2>", text, flags=re.MULTILINE)
    text = re.sub(r"^#\s+(.+)$", r"<h1>\1</h1>", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", text)

    # Zamiana przypisów [1], [2] na indeks górny
    text = re.sub(
        r"\[(\d+)\]",
        r"<sup style='color:#2980b9; font-weight:bold;'>[\1]</sup>",
        text,
    )

    # Zamiana bezpiecznych linków URL (wyłącznie http:// i https://) na hiperłącza
    text = re.sub(
        r'(https?://[^\s\)<>"]+)',
        r'<a href="\1" target="_blank" rel="noopener noreferrer" style="color: #3498db; text-decoration: underline;">\1</a>',
        text,
    )

    return text


def proposed_build_html_template(report_text: str, country: str) -> str:
    """PROPOSED MINIMAL FIX for app.build_html_template:

    Escapes country parameter in addition to using proposed_format_report_html.
    """
    safe_country = html.escape(country, quote=True)
    formatted_content = proposed_format_report_html(report_text)
    return f"""<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <title>Raport Kondycji Gospodarczej: {safe_country}</title>
</head>
<body>
    <div class="report-content">{formatted_content}</div>
    <div class="footer">Raport wygenerowany dla kraju: {safe_country}</div>
</body>
</html>"""


def test_proposed_fix_neutralizes_script_tag():
    """Verify proposed fix neutralizes <script> tags."""
    xss_payload = "<script>alert('XSS')</script>"
    safe_output = proposed_format_report_html(xss_payload)

    assert "<script>" not in safe_output
    assert "&lt;script&gt;alert(&#x27;XSS&#x27;)&lt;/script&gt;" in safe_output


def test_proposed_fix_neutralizes_event_handlers():
    """Verify proposed fix neutralizes <img> with onerror."""
    img_payload = '<img src="x" onerror="alert(1)">'
    safe_output = proposed_format_report_html(img_payload)

    assert "<img" not in safe_output
    assert "&lt;img" in safe_output


def test_proposed_fix_neutralizes_malicious_country():
    """Verify proposed fix escapes malicious country parameter."""
    malicious_country = "Polska<script>alert(1)</script>"
    full_html = proposed_build_html_template("Tekst", country=malicious_country)

    assert "<script>" not in full_html
    assert "Polska&lt;script&gt;alert(1)&lt;/script&gt;" in full_html


def test_proposed_fix_preserves_valid_markdown_and_links():
    """Verify proposed fix preserves legitimate Markdown, citations, and URLs."""
    raw_markdown = (
        "# Tytuł Raportu\n"
        "## Podrozdział\n"
        "### Sekcja\n"
        "PKB wzrósł o **3.9%** r/r [1].\n"
        "Źródło: https://stat.gov.pl/pkb"
    )
    safe_output = proposed_format_report_html(raw_markdown)

    assert "<h1>Tytuł Raportu</h1>" in safe_output
    assert "<h2>Podrozdział</h2>" in safe_output
    assert "<h3>Sekcja</h3>" in safe_output
    assert "<strong>3.9%</strong>" in safe_output
    assert "<sup style='color:#2980b9; font-weight:bold;'>[1]</sup>" in safe_output
    assert '<a href="https://stat.gov.pl/pkb"' in safe_output
