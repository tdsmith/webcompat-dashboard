from datetime import datetime, timedelta
from functools import partial
import json
import random
from textwrap import dedent
from typing import List, Optional

import attr

WEBCOMPAT_BASE = "https://github.com/webcompat/web-bugs/issues/{}"


@attr.s
class BugzillaRow:
    id: int = attr.ib(factory=partial(random.getrandbits, 31))
    summary: str = attr.ib(default="Bug summary")
    product: str = attr.ib(default="Firefox")
    component: str = attr.ib(default="Component")
    votes: int = attr.ib(default=0)
    creation_time: str = attr.ib(default=(datetime.now() - timedelta(days=1)).isoformat())
    last_change_time: str = attr.ib(default=datetime.now().isoformat())
    status: str = attr.ib(default="NEW")
    resolution: str = attr.ib(default="")
    see_also: List[str] = attr.ib(factory=list)
    whiteboard: str = attr.ib(default="")

    @classmethod
    def dupe_of(cls, webcompat_numbers, **kwargs):
        see_also = [WEBCOMPAT_BASE.format(n) for n in webcompat_numbers]
        return cls(see_also=see_also, **kwargs)


@attr.s
class WebcompatIssue:
    body: str = attr.ib()
    number: int = attr.ib(factory=partial(random.getrandbits, 31))
    created_at: str = attr.ib(default=(datetime.now() - timedelta(days=1)).isoformat())
    closed_at: Optional[str] = attr.ib(default=None)
    state: str = attr.ib(default="open")

    @classmethod
    def for_url(cls, url, **kwargs):
        body = dedent(f"""\
        **URL**: {url}
        """)
        return cls(body=body, **kwargs)


def generate_bugzilla():
    rows = [
        BugzillaRow(),
    ]
    bugs = [attr.asdict(row) for row in rows]
    return {"bugs": bugs}


def generate_webcompat():
    issues = [
        WebcompatIssue.for_url("https://www.example.com"),
    ]
    # Add 10 old issues for old.example
    issues.extend([
        WebcompatIssue.for_url(
            "https://old.example/some/site",
            created_at=datetime(2010, 3, 4).isoformat())
        for _ in range(10)])
    # Add 5 new issues for recent.example
    issues.extend([
        WebcompatIssue.for_url("https://recent.example/wow.doge")
        for _ in range(10)])
    return [attr.asdict(issue) for issue in issues]


def main():
    with open("bugzilla.json", "w") as f:
        json.dump(generate_bugzilla(), f)

    with open("github.json", "w") as f:
        json.dump(generate_webcompat(), f)


if __name__ == "__main__":
    main()
