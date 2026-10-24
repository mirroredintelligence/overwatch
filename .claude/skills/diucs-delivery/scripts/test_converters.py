"""Tests for docs_to_md.py and canvas_to_text.py."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import canvas_to_text  # noqa: E402
import docs_to_md  # noqa: E402

XML = (
    "<doc node='n1' rev='7'>"
    "<paragraph id='a' heading='1'><text id='a1'>Title</text></paragraph>"
    "<paragraph id='b'><text id='b1'>Plain </text><text id='b2'><bold>bold</bold></text><text id='b3'><code>code</code></text></paragraph>"
    "<list id='l'><listItem id='li1'><paragraph id='p1'><text id='t1'>one</text></paragraph></listItem>"
    "<listItem id='li2'><paragraph id='p2'><text id='t2'>two</text></paragraph></listItem></list>"
    "<table id='t'><row id='r1'><cell id='c1' header='true'><paragraph id='x1'><text id='x2'>A</text></paragraph></cell>"
    "<cell id='c2' header='true'><paragraph id='y1'><text id='y2'>B</text></paragraph></cell></row>"
    "<row id='r2'><cell id='c3'><paragraph id='z1'><text id='z2'>1</text></paragraph></cell>"
    "<cell id='c4'><paragraph id='w1'><text id='w2'>2</text></paragraph></cell></row></table>"
    "<codeBlock id='cb'><text id='cb1'>SELECT 1</text></codeBlock>"
    "</doc>"
)


def saved_result(xml, complete=True):
    body = {"verdict": "allow", "rev": 7, "data": {"rev": 7, "xml": xml}}
    if not complete:
        body["complete"] = False
    return json.dumps([{"type": "text", "text": "header"}, {"type": "text", "text": json.dumps(body)}])


def test_docs_to_md_converts_headings_lists_tables_and_code():
    md, info = docs_to_md.convert(saved_result(XML))
    assert "# Title" in md
    assert "Plain **bold**`code`" in md
    assert "- one" in md and "- two" in md
    assert "| A | B |" in md and "|---|---|" in md and "| 1 | 2 |" in md
    assert "```\nSELECT 1\n```" in md
    assert info["rev"] == 7 and info["complete"] is True


def test_docs_to_md_reports_when_the_read_was_cut_short():
    xml = XML.replace("</doc>", "<gap blocks='246' cap='true' from='m3.202306'/></doc>")
    md, info = docs_to_md.convert(saved_result(xml, complete=False))
    assert info["complete"] is False and info["gaps"] == ["m3.202306"]


def test_docs_to_md_accepts_the_inner_json_directly():
    inner = json.dumps({"data": {"rev": 3, "xml": XML}})
    md, info = docs_to_md.convert(inner)
    assert md.startswith("# Title") and info["rev"] == 3


def test_canvas_to_text_keeps_visible_text_and_buttons_and_drops_styles(tmp_path):
    html = (
        "<html><head><title>t</title></head><body><x-dc><helmet><style>.a{color:red}</style></helmet>"
        "<div><h2>Sign in</h2><button type='button'>Send code</button>"
        "<label for='n'>Mobile number</label><input id='n' type='text' value='07xxx'></div></x-dc>"
        "<script type='text/x-dc' data-dc-script>class Component extends DCLogic { renderVals() { const rows = [{ name: 'UCR West', status: 'Accepting' }]; return { rows }; } }</script>"
        "</body></html>"
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "Main.dc.html").write_text(html, encoding="utf-8")
    out = tmp_path / "out"
    canvas_to_text.convert_dir(src, out)
    text = (out / "Main.txt").read_text(encoding="utf-8")
    assert "## Sign in" in text and "[btn] Send code" in text and "Mobile number" in text
    assert "color:red" not in text
    assert "UCR West" in text  # sample data from the script block is kept
