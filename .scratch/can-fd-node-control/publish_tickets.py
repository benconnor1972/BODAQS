"""Publish only the approved ten-ticket set, retaining a resumable journal."""
from pathlib import Path
import json
import os
import re
import shutil
import subprocess

REPO = "benconnor1972/BODAQS"
ROOT = Path(__file__).resolve().parent
JOURNAL = ROOT / "publication.json"
BODY_DIR = ROOT / "publish-bodies"
GH = shutil.which("gh")
if not GH:
    candidates = [
        Path("C:/Program Files/GitHub CLI/gh.exe"),
        Path("C:/Program Files (x86)/GitHub CLI/gh.exe"),
        Path(os.environ["LOCALAPPDATA"]) / "Programs/GitHub CLI/gh.exe",
        Path(os.environ["LOCALAPPDATA"]) / "Microsoft/WinGet/Links/gh.exe",
    ]
    GH = next((str(path) for path in candidates if path.is_file()), None)
if not GH:
    raise SystemExit("GitHub CLI not found")


def gh(*args):
    result = subprocess.run(
        [GH, *args], capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=90,
    )
    if result.returncode:
        raise RuntimeError(f"gh {args[0]} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def api(path, *args):
    return json.loads(gh(
        "api", path, "-H", "Accept: application/vnd.github+json",
        "-H", "X-GitHub-Api-Version: 2026-03-10", *args,
    ))


state = json.loads(JOURNAL.read_text(encoding="utf-8")) if JOURNAL.exists() else {
    "repository": REPO, "native_dependencies": None,
    "labels": ["enhancement"], "omitted_labels": ["ready-for-agent"],
    "issues": {},
}
assert state["repository"] == REPO


def save():
    staging = JOURNAL.with_suffix(".tmp")
    staging.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    staging.replace(JOURNAL)


files = sorted((ROOT / "issues").glob("*.md"))
assert len(files) == 10, "Only the ten approved previews may be published"
plans = []
for path in files:
    source = path.read_text(encoding="utf-8")
    match = re.match(r"# (\d+): ([^\n]+)\n", source)
    assert match, path.name
    number, title = int(match[1]), match[2]
    blockers = [int(value) for value in re.findall(r"^- Preview (\d+):", source, re.M)]
    assert all(blocker < number for blocker in blockers)
    assert len(re.findall(r"^- \[ \]", source, re.M)) == 5
    content = source[match.end():].split("## Publication preview", 1)[0].strip()
    plans.append((number, title, blockers, content))
assert [plan[0] for plan in plans] == list(range(1, 11))
BODY_DIR.mkdir(exist_ok=True)

existing = json.loads(gh(
    "issue", "list", "--repo", REPO, "--state", "all", "--limit", "100",
    "--json", "number,title,url",
))
for number, title, blockers, content in plans:
    key = str(number)
    if key not in state["issues"]:
        if any(item["title"] == title for item in existing):
            raise RuntimeError(f"Matching existing title without journal: {title}")
        if blockers:
            assert all(str(blocker) in state["issues"] for blocker in blockers)
            content = content.split("## Blocked by", 1)[0].rstrip()
            if state["native_dependencies"] is not True:
                refs = [state["issues"][str(blocker)]["url"] for blocker in blockers]
                content += "\n\n## Blocked by\n\n" + "\n".join(f"- {url}" for url in refs)
        body_path = BODY_DIR / f"{number:02d}.md"
        body_path.write_text(content + "\n", encoding="utf-8")
        url = gh(
            "issue", "create", "--repo", REPO, "--title", title,
            "--body-file", str(body_path), "--label", "enhancement",
        ).splitlines()[-1].strip()
        issue_number = int(url.rstrip("/").rsplit("/", 1)[1])
        state["issues"][key] = {
            "number": issue_number, "url": url, "title": title,
            "preview": number, "blockers": blockers, "linked_blockers": [],
        }
        save()
        print(f"Created #{issue_number}: {title}", flush=True)
    issue = state["issues"][key]
    if "id" not in issue:
        issue["id"] = api(f"repos/{REPO}/issues/{issue['number']}")["id"]
        save()
    dependency_path = f"repos/{REPO}/issues/{issue['number']}/dependencies/blocked_by"
    if state["native_dependencies"] is None:
        try:
            api(dependency_path)
        except RuntimeError as error:
            if "HTTP 404" not in str(error) and "HTTP 410" not in str(error):
                raise
            state["native_dependencies"] = False
            print("Native dependencies unavailable; using explicit issue references.", flush=True)
        else:
            state["native_dependencies"] = True
        save()
    if state["native_dependencies"]:
        linked = {item["id"] for item in api(dependency_path)}
        for blocker in blockers:
            blocking_issue = state["issues"][str(blocker)]
            if blocking_issue["id"] not in linked:
                api(dependency_path, "--method", "POST", "-F", f"issue_id={blocking_issue['id']}")
            if blocker not in issue["linked_blockers"]:
                issue["linked_blockers"].append(blocker)
                save()
            print(f"Linked #{issue['number']} blocked by #{blocking_issue['number']}", flush=True)

for number, title, blockers, _ in plans:
    issue = state["issues"][str(number)]
    remote = api(f"repos/{REPO}/issues/{issue['number']}")
    assert remote["title"] == title
    assert remote["state"] == "open"
    assert {label["name"] for label in remote["labels"]} == {"enhancement"}
    assert len(re.findall(r"^- \[ \]", remote["body"], re.M)) == 5
    assert "Publication preview" not in remote["body"]
    assert "Preview 0" not in remote["body"]
    if state["native_dependencies"]:
        observed = {item["id"] for item in api(
            f"repos/{REPO}/issues/{issue['number']}/dependencies/blocked_by"
        )}
        expected = {state["issues"][str(blocker)]["id"] for blocker in blockers}
        assert observed == expected, (number, observed, expected)
    else:
        assert all(state["issues"][str(blocker)]["url"] in remote["body"] for blocker in blockers)
state["verified"] = True
save()
print("Verified all 10 issues, 50 acceptance criteria, enhancement labels and dependency edges.", flush=True)
