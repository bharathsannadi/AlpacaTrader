#!/usr/bin/env python3.11
"""
book_dig.py — problem-targeted reader for the options-trading library.

The 27 books are already distilled in knowledge_base.md. This does NOT
re-summarize them; it surgically pulls the passages that bear on the
ONE live problem: a small directional edge (~+0.6 ATR/60min, 52-56% hit)
that dies after costs. Prints matching pages + tight context windows so
we read evidence, not whole books.

Usage:
  venv/bin/python3.11 scripts/book_dig.py "Natenberg" "theoretical edge|transaction cost|bid-ask"
  venv/bin/python3.11 scripts/book_dig.py --list
"""
from __future__ import annotations
import sys, re
from pathlib import Path
from pypdf import PdfReader

BOOK_ROOTS = [
    Path("/Users/bsannadi/Desktop/books/Trading/Options Trading"),
    Path("/Users/bsannadi/Desktop/books/Volatility and VIX Collection"),
    Path("/Users/bsannadi/Desktop/books/options"),
    Path("/Users/bsannadi/Desktop/books/Trading/Day Trading"),
    Path("/Users/bsannadi/Desktop/books/Trading/@Gurgavin ‘s  Bull and Bear Market Collection"),
    Path("/Users/bsannadi/Desktop/books/Trading 2/@Gurgavin ‘s Risk Management Collection"),
]
CTX = 480   # chars of context around each hit


def _all_pdfs() -> list[Path]:
    out: list[Path] = []
    for r in BOOK_ROOTS:
        if r.is_dir():
            out += sorted(r.glob("*.pdf"))
    return out


def find_book(frag: str) -> Path | None:
    frag = frag.lower()
    for p in _all_pdfs():
        if frag in p.name.lower():
            return p
    return None


def dig(book: Path, pattern: str, max_hits: int = 40) -> None:
    rx = re.compile(pattern, re.I)
    reader = PdfReader(str(book))
    n = len(reader.pages)
    print(f"\n=== {book.name}  ({n} pages) ===")
    print(f"query: /{pattern}/i\n")
    hits = 0
    for i, page in enumerate(reader.pages):
        if hits >= max_hits:
            print(f"... (stopped at {max_hits} hits)")
            break
        try:
            txt = page.extract_text() or ""
        except Exception:
            continue
        txt = re.sub(r"\s+", " ", txt).strip()
        if not txt:
            continue
        for m in rx.finditer(txt):
            a = max(0, m.start() - CTX // 2)
            b = min(len(txt), m.end() + CTX // 2)
            snippet = txt[a:b]
            print(f"[p.{i+1}] …{snippet}…\n")
            hits += 1
            break   # one window per page is enough to locate it
    if hits == 0:
        print("(no matches — try broader terms)")
    else:
        print(f"--- {hits} page(s) matched ---")


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "--list":
        for p in _all_pdfs():
            print(p.name)
        return
    if len(sys.argv) < 3:
        print(__doc__)
        return
    book = find_book(sys.argv[1])
    if not book:
        print(f"no book matching '{sys.argv[1]}'")
        return
    dig(book, sys.argv[2])


if __name__ == "__main__":
    main()
