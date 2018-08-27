import os
import sqlite3
import warnings

from github3 import GitHub


class GithubCache:
    def __init__(self, path: str, github_session: GitHub):
        self.gh = github_session
        if not os.path.exists(path):
            warnings.warn("Creating database %s" % path)
        self.db = sqlite3.connect(path)
        with self.db:
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS issues (
                    number INTEGER PRIMARY KEY,
                    updated TEXT,
                    content TEXT
                )
                """)
        self.db.row_factory = sqlite3.Row
        self.db.text_factory = bytes

    def update(self):
        last_updated = self.db.execute("SELECT max(updated) FROM issues").fetchone()
        last_updated = last_updated[0] if last_updated else None

        issue_iter = self.gh.issues_on("webcompat", "web-bugs", state="all", since=last_updated)
        with self.db:
            for issue in issue_iter:
                self.db.execute("INSERT OR REPLACE INTO issues VALUES (?, ?, ?)",
                                (issue.number,
                                 issue.updated_at.isoformat(),
                                 issue.as_json()))

    def issues(self):
        sql = """
            SELECT
                number,
                json_extract(content, "$.created_at") AS created_at,
                json_extract(content, "$.closed_at") AS closed_at,
                json_extract(content, "$.state") AS state,
                json_extract(content, "$.body") AS body
            FROM issues
            """
        issues = self.db.execute(sql).fetchall()
        return issues
