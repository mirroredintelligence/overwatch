#!/usr/bin/env python3
"""Turn design-canvas artboards (*.dc.html) into readable text: headings, buttons, fields, copy and sample data.

    python canvas_to_text.py <folder-with-dc-html-files> <output-folder>

Get the artboard files with the Artifact tool: `read` the canvas url with `paths` (all project/*.dc.html files) and use
the folder it reports. Compare the version it reports with `snapshot_version` in docs/spec/sources.json to see whether
docs/spec/ui-screens.md is stale. Only changed artboards need re-reading.
"""
from __future__ import annotations

import argparse
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

BLOCK = {"div", "section", "h1", "h2", "h3", "h4", "p", "li", "tr", "button", "label", "table", "ul", "ol", "br", "header", "footer", "article", "aside", "nav", "main"}


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out: list[str] = []
        self.skip = 0
        self.script: list[str] = []
        self.in_script = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("style", "helmet", "svg"):
            self.skip += 1
        if tag == "script":
            self.in_script = a.get("type") == "text/x-dc"
            self.skip += 1
        if tag in BLOCK:
            self.out.append("\n")
        if tag in ("h1", "h2", "h3"):
            self.out.append("## ")
        if tag == "button":
            self.out.append("[btn] ")
        if tag == "input":
            self.out.append(f"[input {a.get('type', '')} value={a.get('value', '')!r} placeholder={a.get('placeholder', '')!r}]")
        if "aria-label" in a and tag != "svg":
            self.out.append(f"[{a['aria-label']}] ")

    def handle_endtag(self, tag):
        if tag in ("style", "helmet", "svg", "script"):
            self.skip = max(0, self.skip - 1)
        if tag == "script":
            self.in_script = False
        if tag in ("td", "th"):
            self.out.append(" | ")

    def handle_data(self, data):
        if self.in_script:
            self.script.append(data)
        elif not self.skip:
            self.out.append(data)


def convert_text(html: str) -> str:
    p = _Parser()
    p.feed(html)
    text = re.sub(r"[ \t]+", " ", "".join(p.out))
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    script = "".join(p.script).strip()
    if len(script) > 120 and "renderVals() {\n    return {};" not in script:
        text += "\n\n--- script (sample data) ---\n" + script
    return text


def convert_dir(src: Path, out: Path) -> list[str]:
    out.mkdir(parents=True, exist_ok=True)
    done = []
    for f in sorted(Path(src).glob("*.dc.html")):
        (out / f.name.replace(".dc.html", ".txt")).write_text(convert_text(f.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
        done.append(f.name)
    return done


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("src")
    p.add_argument("out")
    a = p.parse_args(argv)
    done = convert_dir(Path(a.src), Path(a.out))
    print(f"Converted {len(done)} artboards to {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
