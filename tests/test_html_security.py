import html
import os
import subprocess
import sys
import pytest
from app import format_report_html, build_html_template, save_report_to_html, server, get_db, set_db
from modules.database import EconomyDatabase


# ==============================================================================
# FIXTURE: IZOLACJA GLOBALNEJ INSTANCJI BAZY
# ==============================================================================

@pytest.fixture(autouse=True)
def reset_app_database():
    """Ensure app._db is restored to its initial state before and after each test

    so tests never pollute each other through the module-level database reference.
    """
    import app
    old_db = app._db
    app.set_db(None)
    try:
        yield
    finally:
        app.set_db(old_db)


# ==============================================================================
# TESTY BEZPIECZEŃSTWA PRODUKCYJNYCH FUNKCJI RENDEROWANIA HTML
# ==============================================================================

def test_script_tag_sanitized():
    """Verify that format_report_html and build_html_template neutralize <script> tags."""
    xss_payload = "<script>alert('XSS-ATTACK')</script>"
    rendered = format_report_html(xss_payload)

    assert "<script>" not in rendered
    assert "</script>" not in rendered
    assert "&lt;script&gt;alert(&#x27;XSS-ATTACK&#x27;)&lt;/script&gt;" in rendered

    full_html = build_html_template(xss_payload, country="Polska")
    assert "<script>" not in full_html
    assert "&lt;script&gt;" in full_html


def test_event_handlers_sanitized():
    """Verify that event handlers (e.g. onerror, onload) are neutralized and cannot execute."""
    payloads = [
        '<img src="x" onerror="alert(\'XSS\')">',
        '<svg onload="alert(\'SVG-XSS\')">',
        '<body onload="alert(1)">',
    ]
    for p in payloads:
        rendered = format_report_html(p)
        assert "<img" not in rendered
        assert "<svg" not in rendered
        assert "<body" not in rendered
        assert "&lt;" in rendered


def test_dangerous_tags_sanitized():
    """Verify that tags like <iframe>, <style>, <object>, <embed> are safely escaped."""
    iframe_payload = '<iframe src="/local/payload"></iframe>'
    rendered_iframe = format_report_html(iframe_payload)
    assert "<iframe" not in rendered_iframe
    assert "&lt;iframe" in rendered_iframe

    style_payload = "<style>body { display: none !important; }</style>"
    rendered_style = format_report_html(style_payload)
    assert "<style" not in rendered_style
    assert "&lt;style&gt;" in rendered_style


def test_javascript_pseudo_protocol_rejected_as_link():
    """Verify that javascript: or data: URIs are never converted into clickable <a> tags."""
    dangerous_uris = [
        "javascript:alert('XSS')",
        "JAVASCRIPT:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox(1)",
    ]
    for uri in dangerous_uris:
        rendered = format_report_html(uri)
        assert "<a href" not in rendered


def test_malicious_urls_with_attribute_breakout():
    """Verify that attempts to break out of href attributes via quotes are prevented."""
    breakout_attempt = 'https://example.com/" onclick="alert(1)'
    rendered = format_report_html(breakout_attempt)

    # Quotes must be escaped as entities, preventing attribute breakout
    assert 'onclick="alert(1)' not in rendered
    assert 'onclick=' not in rendered or '&quot;' in rendered


def test_country_parameter_escaping():
    """Verify that the country parameter in build_html_template is safely escaped."""
    malicious_country = "Polska<script>alert('Country-XSS')</script>"
    full_html = build_html_template("Tekst", country=malicious_country)

    assert "<script>" not in full_html
    assert "Polska&lt;script&gt;alert(&#x27;Country-XSS&#x27;)&lt;/script&gt;" in full_html
    assert "<title>Raport Kondycji Gospodarczej: Polska&lt;script&gt;" in full_html


def test_html_entities_and_quotes_handling():
    """Verify proper handling of quotes and ampersands without breaking text."""
    text_with_entities = 'Wskaźnik "PKB" & \'Inflacja\' < 5% > 2%'
    rendered = format_report_html(text_with_entities)

    assert "&quot;PKB&quot;" in rendered
    assert "&amp;" in rendered
    assert "&lt; 5%" in rendered
    assert "&gt; 2%" in rendered


def test_urls_with_ampersands_and_params():
    """Verify that valid URLs containing query parameters with & are converted into safe links."""
    url = "https://stat.gov.pl/obszary-tematyczne/rynek-pracy/?page=1&limit=10"
    rendered = format_report_html(f"Źródło: {url}")

    assert '<a href="https://stat.gov.pl/obszary-tematyczne/rynek-pracy/?page=1&amp;limit=10"' in rendered
    assert 'target="_blank"' in rendered
    assert 'rel="noopener noreferrer"' in rendered


def test_unicode_and_polish_characters():
    """Verify that Polish diacritics are preserved intact."""
    polish_text = "# Koniunktura gospodarcza w Polsce: zażółć gęślą jaźń\n**Wskaźnik cen towarów i usług konsumpcyjnych**"
    rendered = format_report_html(polish_text)

    assert "<h1>Koniunktura gospodarcza w Polsce: zażółć gęślą jaźń</h1>" in rendered
    assert "<strong>Wskaźnik cen towarów i usług konsumpcyjnych</strong>" in rendered


def test_none_and_empty_content_handling():
    """Verify that None, empty string, or whitespace are handled safely without exceptions."""
    assert format_report_html("") == ""
    assert format_report_html(None) == ""

    template_empty = build_html_template("", country="")
    assert '<div class="report-content"></div>' in template_empty
    assert '<div class="footer">\n            Raport wygenerowany dla kraju: \n        </div>' in template_empty

    template_none = build_html_template(None, country=None)
    assert '<div class="report-content"></div>' in template_none


def test_valid_markdown_and_citations_preserved():
    """Verify that valid markdown headers, bold, citations, and URLs render properly."""
    raw_markdown = (
        "# Tytuł Raportu\n"
        "## Podrozdział\n"
        "### Sekcja\n"
        "PKB wzrósł o **3.9%** r/r [1] oraz [2].\n"
        "Źródło: https://stat.gov.pl/pkb."
    )
    rendered = format_report_html(raw_markdown)

    assert "<h1>Tytuł Raportu</h1>" in rendered
    assert "<h2>Podrozdział</h2>" in rendered
    assert "### Sekcja" not in rendered
    assert "<h3>Sekcja</h3>" in rendered
    assert "<strong>3.9%</strong>" in rendered
    assert "<sup style='color:#2980b9; font-weight:bold;'>[\1]</sup>" not in rendered
    assert "<sup style='color:#2980b9; font-weight:bold;'>[1]</sup>" in rendered
    assert "<sup style='color:#2980b9; font-weight:bold;'>[2]</sup>" in rendered
    assert '<a href="https://stat.gov.pl/pkb"' in rendered
    assert 'https://stat.gov.pl/pkb</a>.' in rendered


def test_flask_endpoint_serves_sanitized_content(isolated_db):
    """Verify that the Flask server route serves sanitized HTML from the database."""
    # Seed isolated database with a report containing malicious payload
    malicious_report = "# Raport Bezpieczeństwa\n<script>alert('Endpoint-XSS')</script>\n**Wartość** [1]"
    isolated_db.save_generated_report(
        country="Polska",
        report_date="02.11.2026",
        periods_summary="Okres testowy",
        markdown_text=malicious_report,
    )

    # Inject isolated_db into app
    set_db(isolated_db)

    with server.test_client() as client:
        response = client.get("/")
        assert response.status_code == 200
        html_data = response.get_data(as_text=True)

        assert "<script>" not in html_data
        assert "&lt;script&gt;alert(&#x27;Endpoint-XSS&#x27;)&lt;/script&gt;" in html_data
        assert "<h1>Raport Bezpieczeństwa</h1>" in html_data
        assert "<strong>Wartość</strong>" in html_data


# ==============================================================================
# TESTY BEZPIECZEŃSTWA FALLBACKU DO PLIKU report.html
# ==============================================================================

def test_flask_endpoint_fallback_to_file_when_db_has_no_report(isolated_db):
    """Verify that when database has no reports, serve_report falls back to the static report.html on disk."""
    # isolated_db has no generated reports
    set_db(isolated_db)

    with server.test_client() as client:
        response = client.get("/")
        assert response.status_code == 200
        content = response.get_data(as_text=True)
        assert "<!DOCTYPE html>" in content
        assert "Raport" in content


def test_flask_endpoint_404_when_db_and_file_missing(isolated_db, monkeypatch):
    """Verify that when neither database report nor report.html file exists, a clean 404 is returned."""
    set_db(isolated_db)

    # Mock os.path.exists to return False specifically for report.html
    original_exists = os.path.exists
    monkeypatch.setattr(os.path, "exists", lambda p: False if str(p).endswith("report.html") else original_exists(p))

    with server.test_client() as client:
        response = client.get("/")
        assert response.status_code == 404
        assert "Brak wygenerowanego raportu w bazie ani na dysku." in response.get_data(as_text=True)


def test_save_report_to_html_produces_sanitized_file(tmp_path, monkeypatch):
    """Verify that save_report_to_html writes sanitized HTML to disk, preventing XSS in static exports."""
    test_report_file = tmp_path / "test_report.html"

    # Safely redirect report_path in save_report_to_html without recursive os.path.join patching
    orig_open = open
    def mock_open(file, *args, **kwargs):
        if str(file).endswith("report.html"):
            return orig_open(test_report_file, *args, **kwargs)
        return orig_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", mock_open)

    malicious_input = "# Raport Export\n<script>alert('Export-XSS')</script>\n<img src=x onerror=alert(1)>"
    save_report_to_html(malicious_input)

    assert test_report_file.exists()
    content = test_report_file.read_text(encoding="utf-8")

    assert "<script>" not in content
    assert "<img" not in content
    assert "&lt;script&gt;alert(&#x27;Export-XSS&#x27;)&lt;/script&gt;" in content
    assert "&lt;img" in content
    assert "<h1>Raport Export</h1>" in content


# ==============================================================================
# TESTY LENIWEJ INICJALIZACJI BAZY (BRAK ZAPISU / POŁĄCZENIA PRZY IMPORCIE)
# ==============================================================================

def test_import_and_rendering_does_not_instantiate_or_touch_database(monkeypatch):
    """Verify in-process with a spy that calling format_report_html and build_html_template

    never instantiates EconomyDatabase and keeps _db as None.
    """
    import app
    app.set_db(None)

    db_init_calls = []

    def spy_init(self, *args, **kwargs):
        db_init_calls.append(args)
        raise RuntimeError("EconomyDatabase.__init__ should NEVER be called by HTML rendering functions!")

    monkeypatch.setattr(EconomyDatabase, "__init__", spy_init)

    # Calling HTML rendering functions must NOT trigger EconomyDatabase instantiation
    res1 = format_report_html("# Test\n<script>alert(1)</script>")
    res2 = build_html_template("# Test", country="Polska")

    assert "<h1>Test</h1>" in res1
    assert "<h1>Test</h1>" in res2
    assert len(db_init_calls) == 0, f"Expected 0 calls to EconomyDatabase.__init__, got {len(db_init_calls)}"
    assert app._db is None


def test_isolated_process_import_app_does_not_create_db_connection():
    """Verify in an isolated Python process that importing app and rendering HTML

    maintains _db as None and executes 0 sqlite3.connect calls.
    """
    code = """
import sys, os
os.environ['OPENAI_API_KEY'] = 'mock'
os.environ['TAVILY_API_KEY'] = 'mock'

import sqlite3
connect_calls = []
original_connect = sqlite3.connect

def monitored_connect(*args, **kwargs):
    connect_calls.append(args)
    return original_connect(*args, **kwargs)

sqlite3.connect = monitored_connect

import app

# Verify _db is None upon importing the module
if app._db is not None:
    sys.exit(f"FAIL: app._db was initialized upon import: {app._db}")

# Verify rendering functions do not trigger database connections
out1 = app.format_report_html("# Header\\n<script>alert(1)</script>")
out2 = app.build_html_template("# Header", country="Polska")

if app._db is not None:
    sys.exit(f"FAIL: app._db was initialized during HTML rendering: {app._db}")

if len(connect_calls) > 0:
    sys.exit(f"FAIL: sqlite3.connect was called {len(connect_calls)} times: {connect_calls}")

if "<script>" in out1 or "<script>" in out2:
    sys.exit("FAIL: <script> was not sanitized!")

print("OK")
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    assert "OK" in result.stdout
