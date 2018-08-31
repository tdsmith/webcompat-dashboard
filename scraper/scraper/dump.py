from collections import Counter
import datetime as dt
from dateutil.rrule import rrule, DAILY
import json
import re
import sys
from typing import List
from urllib.parse import urlencode

import attr
import click
import dateutil
import github3
import pandas as pd
import requests

from .cache import GithubCache


def load_issues(cache):
    issues = cache.issues()
    rows = []
    for i in issues:
        match = re.search(b"(\\*\\*)?URL(\\*\\*)?:\\s+([^\r\n]+)\r?\n", i["body"])
        domain = match and match.group(3).decode("utf-8")
        d = {
            "number": i["number"],
            "created_at": i["created_at"].decode("ascii"),
            "closed_at": i["closed_at"] and i["closed_at"].decode("ascii"),
            "domain": domain,
            "state": i["state"].decode("ascii"),
        }
        rows.append(d)

    df = pd.DataFrame(rows)
    df.closed_at = pd.to_datetime(df.closed_at)
    df.created_at = pd.to_datetime(df.created_at)
    hostname_re = r"(.*://)?(www\.)?([^:/]+)[:/]?.*"
    df["hostname"] = df.domain.str.extract(hostname_re)[2]
    return df


def fetch_bugzilla_webcompat_bugs():
    bugs = requests.get(
        "https://bugzilla.mozilla.org/rest/bug",
        params={
            "o1": "regexp",
            "v1": ".*webcompat.*",
            "f1": "see_also",
            "limit": 0,
            "include_fields": [
                "id",
                "summary",
                "product",
                "component",
                "votes",
                "creation_time",
                "last_change_time",
                "status",
                "resolution",
                "see_also"]
        }).json()["bugs"]
    return bugs


def fetch_bugzilla_partner_rel_bugs():
    return requests.get(
        "https://bugzilla.mozilla.org/rest/bug",
        {
            "status_whiteboard_type": "substring",
            "status_whiteboard": "[platform-rel",
        }).json()["bugs"]


@attr.s
class PlatformRelSpec:
    _SEARCH_URL = "https://bugzilla.mozilla.org/buglist.cgi"

    include: List[str] = attr.ib(factory=list)
    exclude: List[str] = attr.ib(factory=list)

    def prefixed_include(self):
        yield from ("platform-rel-{}".format(tag) for tag in self.include)

    def prefixed_exclude(self):
        yield from ("platform-rel-{}".format(tag) for tag in self.exclude)

    def sitewait_query_url(self):
        clauses = {
            "f1": "status_whiteboard",
            "o1": "substring",
            "v1": "[sitewait]",
        }
        clauses.update(self._bugzilla_clauses(2))
        return self._SEARCH_URL + "?" + urlencode(clauses)

    def regression_query_url(self):
        clauses = {
            "keywords": "regression",
            "keywords_type": "allwords",
        }
        clauses.update(self._bugzilla_clauses(1))
        return self._SEARCH_URL + "?" + urlencode(clauses)

    def open_query_url(self):
        return self._SEARCH_URL + "?" + urlencode(self._bugzilla_clauses(1))

    def _bugzilla_clauses(self, field_start):
        field = field_start
        clauses = {
            "resolution": "---",
            "query_format": "advanced",
            "f%d" % field: "OP",
            "j%d" % field: "OR",
        }
        field += 1
        for tag in self.prefixed_include():
            clauses["f%d" % field] = "status_whiteboard"
            clauses["o%d" % field] = "substring"
            clauses["v%d" % field] = "[%s]" % tag
            field += 1
        clauses["f%d" % field] = "CP"
        field += 1
        if len(self.exclude) == 0:
            return clauses
        clauses["f%d" % field] = "OP"
        clauses["n%d" % field] = 1
        field += 1
        for tag in self.prefixed_exclude():
            clauses["f%d" % field] = "status_whiteboard"
            clauses["o%d" % field] = "substring"
            clauses["v%d" % field] = "[%s]" % tag
            field += 1
        return clauses


SITE_TO_TAGS = {
    "youtube.com": PlatformRelSpec(["youtube"]),
    "baidu.com": PlatformRelSpec(["baidu"]),
    "wikipedia.org": PlatformRelSpec(["wikipedia", "wikimedia"]),
    "yahoo.com": PlatformRelSpec(["yahoo!"]),
    "reddit.com": PlatformRelSpec(["reddit"]),
    "amazon.com": PlatformRelSpec(["amazon", "amazonmusic", "amazonshopping", "amazonvideo"]),
    "twitter.com": PlatformRelSpec(["twitter"]),
    "live.com": PlatformRelSpec(["microsoft"]),
    "yandex.ru": PlatformRelSpec(["yandex"]),
    "google.com": PlatformRelSpec(
        include=[
            "google", "googlecalendar", "googledocs", "googlehangouts", "googlemaps",
            "googlesheets", "googleslides", "googlesuite",
        ],
        exclude=["youtube"],
    ),
    "whatsapp.com": PlatformRelSpec(["whatsappweb"]),
    "facebook.com": PlatformRelSpec(
        include=["facebook"],
        exclude=["whatsappweb", "instagram"],
    )
}


def sort_partner_rel_bugs(bugs):
    by_partner = {}
    for bug in bugs:
        tags = re.findall(r"\[([^\]]+)\]", bug["whiteboard"].lower())
        for partner, spec in SITE_TO_TAGS.items():
            if any(tag in spec.prefixed_exclude() for tag in tags):
                continue
            if any(tag in spec.prefixed_include() for tag in tags):
                by_partner.setdefault(partner, []).append(bug)
    return by_partner


def dump(cache):
    df = load_issues(cache)

    result = {
        "last_updated": dt.datetime.now().isoformat(),
    }

    # Top open domains
    result["open"] = (
        df
        .loc[
            (df.state == "open") &
            ~df.hostname.isnull() &
            (df.hostname != "None"), :]
        .groupby("hostname")["number"]
        .count()
        .sort_values(ascending=False)
        [:10]
        .to_dict())

    # Top domains, last 30 days
    result["last30"] = (
        df
        .loc[
            (df.created_at >= dt.datetime.now() - dt.timedelta(days=30)) &
            ~df.hostname.isnull() &
            (df.hostname != "None"), :]
        .groupby("hostname")
        ["number"]
        .count()
        .sort_values(ascending=False)
        [:10]
        .to_dict())

    bugzilla_see_also = fetch_bugzilla_webcompat_bugs()
    bz = pd.DataFrame(bugzilla_see_also).set_index("id")

    # Make a mapping of bugzilla ID <-see also-> webcompat bugs
    join_table_rows = []
    for key, urls in bz["see_also"].items():
        for url in urls:
            if "webcompat" not in url:
                continue
            m = re.search(r"\d{2,}", url)
            if not m:
                continue
            webcompat_id = int(m[0])
            join_table_rows.append({
                "bugzilla_id": key,
                "webcompat_id": webcompat_id,
            })
    join_table = (
        pd.DataFrame(join_table_rows, columns=["bugzilla_id", "webcompat_id"])
        .drop_duplicates()
    )

    wc_dupes = (
        join_table
        .merge(
            # fetch indices of open bugs
            bz.query(
                "status == 'UNCONFIRMED' or status == 'NEW' "
                "or status == 'ASSIGNED' or status == 'REOPENED'")[[]],
            how="inner",
            left_on="bugzilla_id",
            right_index=True)
        .merge(
            df[["number", "hostname"]],
            how="left",
            left_on="webcompat_id",
            right_on="number")
    )

    n_dupes = wc_dupes.groupby("bugzilla_id")["webcompat_id"].count()
    most_duped = (
        wc_dupes
        .groupby("bugzilla_id")
        ["webcompat_id"]
        .count()
        .sort_values(ascending=False)
        [:10])

    def most_common(col):
        c = Counter(col)
        return ", ".join("%s (%d)" % (x, n) for x, n in c.most_common(3))

    domains_per_bz_issue = (
        wc_dupes
        .groupby("bugzilla_id")
        ["hostname"]
        .agg(most_common)
    )

    annotated = bz.copy()
    annotated["most_reported"] = domains_per_bz_issue
    annotated["wc_dupes"] = n_dupes

    result["bugzilla"] = (
        annotated
        .loc[most_duped.index, ["wc_dupes", "component", "summary", "most_reported"]]
        .reset_index()
        .to_dict(orient="records"))

    # Assemble per-partner results
    partner_rel_bugs = fetch_bugzilla_partner_rel_bugs()
    by_partner = sort_partner_rel_bugs(partner_rel_bugs)

    dates_x = [x.date() for x in rrule(DAILY, dtstart=dt.date(2016, 1, 1), until=dt.date.today())]
    result["dates_x"] = [d.isoformat() for d in dates_x]

    retain_keys = ["id", "summary", "resolution"]
    subset = {}
    for partner, bugs in by_partner.items():
        regression_bugs = []
        open_bugs = [0] * len(dates_x)
        n_open = 0
        n_sitewait = 0
        n_regression = 0
        bugs = sorted(
            bugs,
            key=lambda bug: dateutil.parser.parse(bug["creation_time"]),
            reverse=True)
        for bug in bugs:
            if bug["resolution"] == "":
                n_open += 1
                if "regression" in bug["keywords"]:
                    regression_bugs.append({k: bug[k] for k in retain_keys})
                    n_regression += 1
                n_sitewait += 1 if "sitewait" in bug["whiteboard"].lower() else 0
            created = dateutil.parser.parse(bug["creation_time"]).date()
            if bug["cf_last_resolved"]:
                last_resolved = dateutil.parser.parse(bug["cf_last_resolved"]).date()
            else:
                last_resolved = dt.date.max
            for j, d in enumerate(dates_x):
                if created <= d <= last_resolved:
                    open_bugs[j] += 1
        d = {
            "summary": {
                "n_open": n_open,
                "open_url": SITE_TO_TAGS[partner].open_query_url(),
                "n_sitewait": n_sitewait,
                "sitewait_url": SITE_TO_TAGS[partner].sitewait_query_url(),
                "n_regression": n_regression,
                "regression_url": SITE_TO_TAGS[partner].regression_query_url(),
                "open_bugs_y": open_bugs,
            },
            "regression_bugs": regression_bugs,
        }
        subset[partner] = d
    result["by_partner"] = subset

    return result


@click.command()
@click.option("--refresh/--no-refresh", default=False)
@click.option("--verbose", "-v", is_flag=True)
@click.option("--github-token", envvar="GITHUB_TOKEN")
@click.argument("cache", required=False)
@click.argument("output", required=False)
def cli(refresh, verbose, github_token, cache, output):
    if not github_token:
        try:
            with open(".token", "r") as f:
                github_token = f.read().strip()
        except Exception:
            click.echo("Couldn't open .token; please specify a --github-token "
                       "or set GITHUB_TOKEN.", err=True)
            sys.exit(1)

    github_session = github3.login(token=github_token)
    cache = GithubCache(cache or "issues.db", github_session)
    output = output or "webcompat.json"

    if refresh:
        if verbose:
            click.echo("Updating issue cache...")
        cache.update()

    if verbose:
        click.echo("Summarizing bugs...")
    body = dump(cache)
    with open(output, "w") as f:
        json.dump(body, f)


if __name__ == "__main__":
    cli()
