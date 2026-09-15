#!/usr/bin/env python3
"""Rewrite the "Open Source Contributions" block in README.md.

Lists pull requests authored by USER that were merged into other people's public
repositories, grouped by repository and sorted by star count. Only the text
between the two markers is replaced.

Usage: GITHUB_TOKEN=... python3 scripts/update_contributions.py [username]
Standard library only, so the workflow needs no dependency install step.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

README = Path(__file__).resolve().parent.parent / "README.md"
START = "<!-- contributions:start -->"
END = "<!-- contributions:end -->"

# Practice or throwaway repositories that should not be shown as contributions.
EXCLUDED_REPOS = {"ituring/first-pr"}

QUERY = """
query($q: String!, $cursor: String) {
  search(query: $q, type: ISSUE, first: 100, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on PullRequest {
        number
        title
        url
        mergedAt
        repository { nameWithOwner url stargazerCount isPrivate }
      }
    }
  }
}
"""


def graphql(token: str, variables: dict) -> dict:
    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if payload.get("errors"):
        raise RuntimeError(payload["errors"])
    return payload["data"]["search"]


def merged_prs(token: str, user: str) -> list[dict]:
    prs: list[dict] = []
    cursor = None
    while True:
        page = graphql(token, {"q": f"is:pr is:merged author:{user} -user:{user}", "cursor": cursor})
        prs.extend(node for node in page["nodes"] if node)
        if not page["pageInfo"]["hasNextPage"]:
            return prs
        cursor = page["pageInfo"]["endCursor"]


def stars(count: int) -> str:
    return f"{count / 1000:.1f}k" if count >= 1000 else str(count)


def cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def render(prs: list[dict]) -> str:
    by_repo: dict[str, list[dict]] = defaultdict(list)
    for pr in prs:
        repo = pr["repository"]
        # A local run may use a token that can see private repositories; never publish those.
        if repo["isPrivate"] or repo["nameWithOwner"] in EXCLUDED_REPOS:
            continue
        by_repo[repo["nameWithOwner"]].append(pr)

    if not by_repo:
        return "_No merged pull requests yet._"

    repos = sorted(by_repo.values(), key=lambda group: -group[0]["repository"]["stargazerCount"])
    total = sum(len(group) for group in repos)
    lines = [
        f"**{total}** merged pull requests across **{len(repos)}** repositories.",
        "",
        "| Repository | ⭐ | Merged pull requests |",
        "| --- | ---: | --- |",
    ]
    for group in repos:
        repo = group[0]["repository"]
        items = "<br>".join(
            f"[#{pr['number']}]({pr['url']}) {cell(pr['title'])}"
            for pr in sorted(group, key=lambda pr: pr["mergedAt"], reverse=True)
        )
        lines.append(
            f"| [{repo['nameWithOwner']}]({repo['url']}) | {stars(repo['stargazerCount'])} | {items} |"
        )
    return "\n".join(lines)


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN is not set", file=sys.stderr)
        return 1
    user = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GITHUB_REPOSITORY_OWNER", "lyfuci")

    text = README.read_text(encoding="utf-8")
    if text.count(START) != 1 or text.count(END) != 1 or text.index(START) > text.index(END):
        print(f"README.md must contain {START} followed by {END} exactly once", file=sys.stderr)
        return 1

    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    README.write_text(f"{head}{START}\n{render(merged_prs(token, user))}\n{END}{tail}", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
