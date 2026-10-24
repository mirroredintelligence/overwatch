#!/usr/bin/env python3
"""Turn a Claude Docs read result into Markdown.

A long `read` of a doc node is too big to show, so the tool saves it to a file and prints that file's path.
Pass that path here:

    python docs_to_md.py <saved-result-file> [--out file.md]

It also reports the doc revision (compare with `snapshot_rev` in docs/spec/sources.json) and whether the read was cut
short (`complete: false`). If it was cut short, read the rest with the `from` id printed under "gaps" and convert that too.
"""
from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _find_body(raw: str) -> dict:
    data = json.loads(raw)
    if isinstance(data, dict):
        return data
    for block in data:  # the saved result is a list of text blocks; the doc is in the one that has "xml"
        text = block.get("text", "") if isinstance(block, dict) else ""
        if '"xml"' in text:
            return json.loads(text)
    raise ValueError("No doc content (an \"xml\" field) found in that file.")


def _inline(el) -> str:
    out = []
    for c in el.iter():
        if c is el:
            continue
        if c.tag == "text":
            t = "".join(c.itertext())
            if c.find("code") is not None:
                t = f"`{t}`"
            elif c.find("bold") is not None:
                t = f"**{t}**"
            elif c.find("italic") is not None:
                t = f"*{t}*"
            out.append(t)
        elif c.tag == "mention":
            out.append("@" + c.get("name", ""))
        elif c.tag == "date":
            out.append(c.get("value", ""))
        elif c.tag == "link":
            out.append(c.get("href", ""))
    return "".join(out)


def convert(raw: str) -> tuple[str, dict]:
    body = _find_body(raw)
    data = body.get("data", body)
    root = ET.fromstring(data["xml"])
    lines: list[str] = []
    gaps: list[str] = []

    def walk(el, depth=0):
        for c in el:
            tag = c.tag
            if tag == "paragraph":
                h = c.get("heading")
                lines.append(("#" * int(h) + " " if h else "") + _inline(c))
            elif tag in ("list", "bulletList", "orderedList"):
                walk(c, depth + 1)
            elif tag == "listItem":
                paras = [_inline(p) for p in c if p.tag == "paragraph"]
                lines.append("  " * max(depth - 1, 0) + "- " + " ".join(paras))
                for p in c:
                    if p.tag != "paragraph":
                        wrapper = ET.Element("w")
                        wrapper.append(p)
                        walk(wrapper, depth + 1)
            elif tag == "table":
                for i, row in enumerate(c):
                    cells = [" ".join(_inline(p) for p in cell if p.tag == "paragraph") for cell in row]
                    lines.append("| " + " | ".join(cells) + " |")
                    if i == 0:
                        lines.append("|" + "---|" * len(cells))
                lines.append("")
            elif tag in ("code", "codeBlock"):
                lines.append("```\n" + "".join(c.itertext()) + "\n```")
            elif tag == "embed":
                lines.append(f"[embed: {c.get('caption', '')}]")
            elif tag == "gap":
                gaps.append(c.get("from", ""))
            elif tag == "horizontalRule":
                lines.append("---")
            elif len(c):
                walk(c, depth)

    walk(root)
    info = {"rev": data.get("rev", body.get("rev")), "complete": body.get("complete", True) is not False and not gaps, "gaps": gaps}
    return "\n".join(lines), info


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("file")
    p.add_argument("--out")
    a = p.parse_args(argv)
    md, info = convert(Path(a.file).read_text(encoding="utf-8"))
    if a.out:
        Path(a.out).write_text(md, encoding="utf-8", newline="\n")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(md)
    print(f"rev={info['rev']} complete={info['complete']} gaps={info['gaps']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
