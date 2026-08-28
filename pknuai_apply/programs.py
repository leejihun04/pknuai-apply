"""The 비교과 programme list.

Each programme is rendered twice on the page (a card layout and a list
layout) with identical data attributes, so the same code appears twice and
has to be folded. The list is requested in 최신순 (order=3).
"""

from __future__ import annotations

import re

from . import config, htmltree, http_client, session

DATE_RE = re.compile(r"(\d{4})\.(\d{2})\.(\d{2})")


def program_url(yy: str, shtm: str, code: str, crs: str) -> str:
    return http_client.with_query(
        config.PROGRAM_DETAIL_URL,
        {"mId": "216", "yy": yy, "shtm": shtm, "nonsubjcCd": code, "nonsubjcCrsCd": crs},
    )


def parse_programs(html_text: str) -> list:
    """Programme cards, newest first, one entry per programme code."""
    document = htmltree.parse(html_text)
    found: dict = {}
    for card in document.find_all(cls="goViewPage", attr="data-nonsubjc-cd"):
        code = card.get("data-nonsubjc-cd").strip()
        if not code or code in found:
            continue
        # The visible <h5> is the programme's real, current name. The card's
        # title attribute can still hold a previous run's name, so it is only
        # a fallback.
        heading = ""
        title_box = card.find(cls="card-title")
        if title_box is not None:
            heading = title_box.text()
        if not heading:
            head = card.find("h5")
            heading = head.text() if head is not None else ""
        title = (heading or card.get("title")).strip()
        if not title:
            continue
        recruit = ""
        for paragraph in card.find_all("p"):
            text = paragraph.text()
            if text.startswith("모집기간"):
                recruit = text.replace("모집기간", "", 1).strip(" :：")
                break
        dates = DATE_RE.findall(recruit)
        organizer = ""
        cate = card.find(cls="name_of_class")
        if cate is not None:
            span = cate.find("span")
            organizer = (span.text() if span is not None else cate.text()).strip()
        found[code] = {
            "id": code,
            "title": f"{title} ({organizer})" if organizer and organizer not in title else title,
            "raw_title": title,
            "organizer": organizer,
            "date": "-".join(dates[0]) if dates else "",
            "recruit_text": " ~ ".join("-".join(d) for d in dates[:2]) if dates else recruit,
            "url": program_url(
                card.get("data-yy"), card.get("data-shtm"), code, card.get("data-nonsubjc-crs-cd")
            ),
        }
    return list(found.values())


def fetch_page(page: int = 1) -> str:
    url = http_client.with_query(
        config.PROGRAM_LIST_URL,
        {"mId": "216", "order": "3", "all": "1", "pageIndex": str(max(1, int(page or 1)))},
    )
    return session.fetch(url, timeout=20).text


def list_programs(pages: int = None) -> list:
    """Programmes across the first few pages, newest first, deduplicated.

    More than one page matters: a programme published today can open for
    applications three weeks from now, and by then it has scrolled off page 1.
    """
    wanted = config.LIST_PAGES if pages is None else max(1, int(pages))
    collected: dict = {}
    for page in range(1, wanted + 1):
        found = parse_programs(fetch_page(page))
        if not found:
            break
        for program in found:
            collected.setdefault(program["id"], program)
    return list(collected.values())


def search(programs: list, query: str) -> list:
    words = [word for word in str(query or "").split() if word]
    if not words:
        return list(programs)
    return [
        program for program in programs
        if all(word.lower() in str(program.get("title", "")).lower() for word in words)
    ]
