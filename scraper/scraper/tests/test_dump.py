import pandas as pd
import pytest

import generate_fixtures
import scraper.dump as dump


class FakeCache:
    def __init__(self):
        self._issues = generate_fixtures.generate_webcompat()
        for field in ("body", "created_at", "closed_at", "state"):
            for issue in self._issues:
                if issue[field] is None:
                    continue
                issue[field] = issue[field].encode("utf-8")

    def issues(self):
        return self._issues


@pytest.fixture
def issue_cache():
    return FakeCache()


class TestDump:
    def test_loads_issues(self, issue_cache):
        issues = dump.load_issues(issue_cache)
        assert type(issues) == pd.DataFrame
        assert "example.com" in issues.hostname.values

    def test_dump(self, monkeypatch, issue_cache):
        def bugzilla_stub():
            return generate_fixtures.generate_bugzilla()["bugs"]

        def partner_rel_stub():
            return generate_fixtures.generate_platform_rel()["bugs"]

        monkeypatch.delattr("requests.sessions.Session.request")
        monkeypatch.setattr(dump, "fetch_bugzilla_webcompat_bugs", bugzilla_stub)
        monkeypatch.setattr(dump, "fetch_bugzilla_partner_rel_bugs", partner_rel_stub)
        result = dump.dump(issue_cache)
        assert "recent.example" in result["last30"].keys()
        assert "old.example" not in result["last30"].keys()
        assert "recent.example" in result["open"].keys()
        assert "old.example" in result["open"].keys()
