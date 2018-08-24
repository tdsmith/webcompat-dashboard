from collections import Counter
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import warnings

import click
import github3
import pandas as pd
import requests


def update_issues(cache, github_token):
    gh = github3.login(token=github_token)
    if not os.path.exists(cache):
        warnings.warn("Creating database %s" % cache)
    db = sqlite3.connect(cache)
    with db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS issues (
                number INTEGER PRIMARY KEY,
                updated TEXT,
                content TEXT
            )
            """)

    last_updated = db.execute("SELECT max(updated) FROM issues").fetchone()
    last_updated = last_updated[0] if last_updated else None

    issue_iter = gh.issues_on("webcompat", "web-bugs", state="all", since=last_updated)
    with db:
        for issue in issue_iter:
            db.execute("INSERT OR REPLACE INTO issues VALUES (?, ?, ?)",
                       (issue.number,
                        issue.updated_at.isoformat(),
                        issue.as_json()))


def load_issues(dbfile):
    db = sqlite3.connect(dbfile)
    db.row_factory = sqlite3.Row
    db.text_factory = bytes

    sql = """
        SELECT
            number,
            json_extract(content, "$.created_at") AS created_at,
            json_extract(content, "$.closed_at") AS closed_at,
            json_extract(content, "$.state") AS state,
            json_extract(content, "$.body") AS body
        FROM issues
        """
    issues = db.execute(sql).fetchall()

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

    return pd.DataFrame(bugs).set_index("id")


def dump(cache, output):
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

    bz = fetch_bugzilla_webcompat_bugs()

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
    join_table = pd.DataFrame(join_table_rows).drop_duplicates()

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

    with open(output, "w") as f:
        json.dump(result, f)


@click.command()
@click.option("--refresh/--no-refresh", default=False)
@click.option("--verbose", "-v", is_flag=True)
@click.option("--github-token", envvar="GITHUB_TOKEN")
@click.argument("cache", required=False)
@click.argument("output", required=False)
def cli(refresh, verbose, github_token, cache, output):
    cache = cache or "issues.db"
    output = output or "webcompat.json"

    if not github_token:
        try:
            with open(".token", "r") as f:
                github_token = f.read().strip()
        except Exception:
            click.echo("Couldn't open .token; please specify a --github-token "
                       "or set GITHUB_TOKEN.", err=True)
            sys.exit(1)

    if refresh:
        if verbose:
            click.echo("Updating issue cache...")
        update_issues(cache, github_token)

    if verbose:
        click.echo("Summarizing bugs...")
    dump(cache, output)


if __name__ == "__main__":
    cli()
