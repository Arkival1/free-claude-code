"""try_page in a real hidden browser finds what reading the code missed.

The page below has the bug a local model's Tip Calculator really had: typing
a custom tip changes nothing until another box is touched."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from free_claude_code.studio.page_try import parse_steps, try_page

TIP_PAGE = """<!doctype html><title>Tips</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<label for="bill">Bill Amount ($)</label><input id="bill" type="number">
<label for="pct">Tip Percent</label>
<select id="pct"><option value="20">20%</option><option value="custom">Custom</option></select>
<label for="custom">Custom Tip (%)</label><input id="custom" type="number">
<p>Tip: <span id="tip">$0.00</span></p>
<script>
const bill = document.getElementById("bill"), pct = document.getElementById("pct");
const custom = document.getElementById("custom"), tip = document.getElementById("tip");
function show() {
  const rate = pct.value === "custom" ? Number(custom.value) || 0 : Number(pct.value);
  tip.textContent = "$" + ((Number(bill.value) || 0) * rate / 100).toFixed(2);
}
bill.addEventListener("input", show);
pct.addEventListener("change", show);
</script>"""


def run(folder: Path, steps: list[dict[str, str]], page: str = "index.html"):
    # The browser tests' own event loop runs on this thread; use another.
    with ThreadPoolExecutor(1) as pool:
        return pool.submit(
            asyncio.run, try_page(folder, page, parse_steps(steps))
        ).result()


def test_it_catches_a_box_that_does_nothing(tmp_path: Path):
    (tmp_path / "index.html").write_text(TIP_PAGE)
    report = run(
        tmp_path,
        [
            {"do": "fill", "target": "Bill Amount", "value": "50"},
            {"do": "read", "target": "#tip", "expect": "$10.00"},
            {"do": "select", "target": "Tip Percent", "value": "Custom"},
            {"do": "fill", "target": "Custom Tip", "value": "18"},
            {"do": "read", "target": "#tip", "expect": "$9.00"},
        ],
    )
    assert report.read == {"#tip": "$0.00"}
    assert report.problems == ["Step 5: #tip shows '$0.00', expected '$9.00'."]
    assert "2. #tip shows '$10.00' (as expected)" in report.lines
    assert "Tip: $0.00" in report.text

    fixed = TIP_PAGE.replace(
        'pct.addEventListener("change", show);',
        'pct.addEventListener("change", show); custom.addEventListener("input", show);',
    )
    (tmp_path / "index.html").write_text(fixed)
    again = run(
        tmp_path,
        [
            # A bare id, as small models write it, works too.
            {"do": "fill", "target": "bill", "value": "50"},
            {"do": "select", "target": "#pct", "value": "custom"},
            {"do": "fill", "target": "#custom", "value": "18"},
            {"do": "read", "target": "Tip:", "expect": "$9.00"},
        ],
    )
    assert again.passed, again.render()


def test_it_reports_pop_ups_errors_missing_files_and_a_too_wide_page(tmp_path: Path):
    (tmp_path / "index.html").write_text(
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<link rel="stylesheet" href="gone.css">'
        "<div style='width:900px'>wide</div>"
        "<button onclick=\"alert('Saved!')\">Save</button>"
        "<script>missingFunction()</script>"
    )
    report = run(
        tmp_path,
        [{"do": "click", "target": "Save"}, {"do": "click", "target": "#nothing"}],
    )
    text = "\n".join(report.problems)
    assert "pop-up alert box opened: 'Saved!'" in text
    assert "missingFunction" in text
    assert "Missing file: gone.css" in text
    assert "Step 2 (click #nothing) couldn't be done" in text
    assert 'The page has: button "Save"' in text
    assert "wider than a phone screen" in text
    assert not report.passed
