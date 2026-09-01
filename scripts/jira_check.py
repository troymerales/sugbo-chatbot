"""
Standalone Jira connectivity + field check.

Reads JIRA_* from .env (same vars app.py uses), then:
  1. verifies the credentials work
  2. verifies the project + issue type exist
  3. prints every field you can pass when creating an issue, flagging which are
     REQUIRED and which have a default

Run:
    python -m scripts.jira_check
    python -m scripts.jira_check --all-types      # fields for every issue type
    python -m scripts.jira_check --create-test    # actually create a throwaway issue
"""

from __future__ import annotations

import os
import sys

import requests
from dotenv import load_dotenv

try:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
except Exception:
    pass

load_dotenv(override=True)

BASE = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
EMAIL = os.environ.get("JIRA_EMAIL", "")
TOKEN = os.environ.get("JIRA_API_TOKEN", "")
PROJECT = os.environ.get("JIRA_PROJECT_KEY", "")
ISSUE_TYPE = os.environ.get("JIRA_ISSUE_TYPE", "Task")

AUTH = (EMAIL, TOKEN)
HEADERS = {"Accept": "application/json"}
OK, BAD = "[OK]", "[!!]"


def die(msg: str) -> None:
    print(f"{BAD} {msg}")
    sys.exit(1)


def get(path: str, **params):
    url = f"{BASE}{path}"
    try:
        r = requests.get(url, auth=AUTH, headers=HEADERS, params=params, timeout=20)
    except requests.RequestException as exc:
        die(f"Could not reach {url}\n     {exc}")
    return r


def check_env() -> None:
    missing = [
        name for name, val in (
            ("JIRA_BASE_URL", BASE), ("JIRA_EMAIL", EMAIL),
            ("JIRA_API_TOKEN", TOKEN), ("JIRA_PROJECT_KEY", PROJECT),
        ) if not val
    ]
    if missing:
        die("Missing in .env: " + ", ".join(missing))
    print(f"{OK} .env loaded  (base={BASE}  project={PROJECT}  type={ISSUE_TYPE})")


def check_auth() -> None:
    r = get("/rest/api/3/myself")
    if r.status_code == 401:
        die("401 Unauthorized — wrong JIRA_EMAIL or JIRA_API_TOKEN.")
    if r.status_code == 404:
        die("404 — JIRA_BASE_URL is probably wrong (should be https://SITE.atlassian.net).")
    if r.status_code != 200:
        die(f"{r.status_code} on /myself\n     {r.text[:400]}")
    me = r.json()
    print(f"{OK} authenticated as {me.get('displayName')} <{me.get('emailAddress', EMAIL)}>")


def list_projects() -> list[dict]:
    r = get("/rest/api/3/project/search", maxResults=100)
    if r.status_code != 200:
        return []
    return r.json().get("values", [])


def check_project() -> dict:
    r = get(f"/rest/api/3/project/{PROJECT}")
    if r.status_code == 404:
        avail = list_projects()
        if avail:
            print(f"{BAD} Project '{PROJECT}' not found. Projects you can access:")
            for p in avail:
                print(f"       {p['key']:<12} {p['name']}")
            die("Set JIRA_PROJECT_KEY in .env to one of the keys above.")
        die(f"Project '{PROJECT}' not found and no projects are visible to this account. "
            "Create a project in Jira first.")
    if r.status_code != 200:
        die(f"{r.status_code} on /project/{PROJECT}\n     {r.text[:400]}")
    p = r.json()
    print(f"{OK} project: {p.get('name')} ({p.get('key')})  style={p.get('style', '?')}")
    return p


def issue_types() -> list[dict]:
    """[{id, name}] creatable in the project, with fallbacks + diagnostics."""
    r = get(f"/rest/api/3/issue/createmeta/{PROJECT}/issuetypes")
    if r.status_code == 200:
        vals = r.json().get("values", [])
        if vals:
            return vals
        print(f"     createmeta/issuetypes returned 0 values — trying fallbacks…")
    else:
        print(f"     createmeta/issuetypes -> {r.status_code}: {r.text[:200]}")

    # legacy createmeta with expand
    r = get("/rest/api/3/issue/createmeta", projectKeys=PROJECT,
            expand="projects.issuetypes")
    if r.status_code == 200:
        projs = r.json().get("projects", [])
        if projs and projs[0].get("issuetypes"):
            return projs[0]["issuetypes"]
    else:
        print(f"     legacy createmeta -> {r.status_code}: {r.text[:200]}")

    # last resort: the project record lists its issue types (no 'creatable' filter)
    r = get(f"/rest/api/3/project/{PROJECT}")
    if r.status_code == 200:
        its = [t for t in r.json().get("issueTypes", []) if not t.get("subtask")]
        if its:
            print(f"{BAD} createmeta returned nothing — usually means this account "
                  "lacks the 'Create issues' permission in this project, or the "
                  "project has no create screen configured.")
            print("     Falling back to the issue types on the project record:")
            return [{"id": t["id"], "name": t["name"]} for t in its]
    return []


def fields_for(issue_type_id: str) -> list[dict]:
    out, start = [], 0
    while True:
        r = get(f"/rest/api/3/issue/createmeta/{PROJECT}/issuetypes/{issue_type_id}",
                startAt=start, maxResults=100)
        if r.status_code != 200:
            # fallback: old expand form
            r2 = get("/rest/api/3/issue/createmeta", projectKeys=PROJECT,
                     issuetypeIds=issue_type_id,
                     expand="projects.issuetypes.fields")
            if r2.status_code != 200:
                die(f"{r.status_code} fetching fields\n     {r.text[:400]}")
            projs = r2.json().get("projects", [])
            its = projs[0].get("issuetypes", []) if projs else []
            fmap = its[0].get("fields", {}) if its else {}
            return list(fmap.values())
        body = r.json()
        out.extend(body.get("fields", body.get("values", [])))
        if body.get("isLast", True) or not body.get("values", body.get("fields")):
            break
        start += len(body.get("fields", body.get("values", [])))
    return out


def describe_allowed(field: dict) -> str:
    vals = field.get("allowedValues") or []
    if not vals:
        return ""
    names = []
    for v in vals[:6]:
        names.append(str(v.get("name") or v.get("value") or v.get("id") or "?"))
    more = "" if len(vals) <= 6 else f" (+{len(vals) - 6} more)"
    return "allowed: " + ", ".join(names) + more


def print_fields(type_name: str, fields: list[dict]) -> None:
    print(f"\n=== fields for issue type: {type_name} ===")
    fields = sorted(fields, key=lambda f: (not f.get("required"), f.get("key", "")))
    req, opt = [], []
    for f in fields:
        key = f.get("key") or f.get("fieldId") or "?"
        name = f.get("name", "")
        typ = (f.get("schema") or {}).get("type", "?")
        item = (f.get("schema") or {}).get("items")
        typ = f"{typ}[{item}]" if item else typ
        default = " default" if f.get("hasDefaultValue") else ""
        allowed = describe_allowed(f)
        line = f"  {key:<24} {typ:<14} {name}"
        if allowed:
            line += f"\n      {allowed}"
        (req if f.get("required") else opt).append((line, default, f))

    print(f"\n  REQUIRED ({len(req)}):")
    for line, default, _ in req:
        print(line + (f"   [{default.strip()}]" if default else "   [NO default — you must send this]"))

    print(f"\n  OPTIONAL ({len(opt)}):")
    for line, _, _ in opt:
        print(line)

    must_send = [f for _ln, _df, f in req if not f.get("hasDefaultValue")]
    if must_send:
        print("\n  Minimal `fields` payload for this type:")
        print("  {")
        for f in must_send:
            key = f.get("key") or f.get("fieldId")
            typ = (f.get("schema") or {}).get("type")
            if key == "project":
                sample = f'{{"key": "{PROJECT}"}}'
            elif key == "issuetype":
                sample = f'{{"name": "{type_name}"}}'
            elif key == "summary":
                sample = '"short one-line summary"'
            elif key == "description":
                sample = '{ ADF document }'
            elif typ in ("option", "priority", "resolution"):
                sample = '{"name": "..."}'
            elif typ == "user":
                sample = '{"id": "<accountId>"}'
            elif typ == "array":
                sample = '[ ... ]'
            else:
                sample = '"..."'
            print(f'    "{key}": {sample},')
        print("  }")


def create_test_issue() -> None:
    """POST a throwaway issue to confirm the write path end-to-end."""
    payload = {
        "fields": {
            "project": {"key": PROJECT},
            "summary": "[jira_check] connectivity test — safe to delete",
            "issuetype": {"name": ISSUE_TYPE},
            "description": {
                "type": "doc", "version": 1,
                "content": [{"type": "paragraph", "content": [
                    {"type": "text", "text": "Created by jira_check.py to verify the "
                     "SugboDoc assistant can file tickets. Delete me."}]}],
            },
            "labels": ["sugbodoc-assistant", "connectivity-test"],
        }
    }
    r = requests.post(f"{BASE}/rest/api/3/issue", json=payload, auth=AUTH,
                      headers={**HEADERS, "Content-Type": "application/json"}, timeout=20)
    if r.status_code >= 300:
        die(f"create failed {r.status_code}: {r.text[:500]}")
    key = r.json()["key"]
    print(f"{OK} created {key}  ->  {BASE}/browse/{key}")
    print("     (delete it in Jira when you're done)")


def main() -> None:
    show_all = "--all-types" in sys.argv
    do_create = "--create-test" in sys.argv
    print("Checking Jira connection...\n")
    check_env()
    check_auth()
    check_project()

    types = issue_types()
    if not types:
        die("No creatable issue types returned for this project.")
    names = ", ".join(t["name"] for t in types)
    print(f"{OK} creatable issue types: {names}")

    if ISSUE_TYPE.lower() in (t["name"].lower() for t in types):
        print(f"{OK} JIRA_ISSUE_TYPE='{ISSUE_TYPE}' is valid for this project")
    else:
        print(f"{BAD} JIRA_ISSUE_TYPE='{ISSUE_TYPE}' is NOT one of the types above")

    targets = types if show_all else [
        t for t in types if t["name"].lower() == ISSUE_TYPE.lower()
    ] or types

    for t in targets:
        print_fields(t["name"], fields_for(t["id"]))

    if do_create:
        print()
        create_test_issue()
    else:
        print("\nDone. Run with --create-test to actually file a throwaway issue.")


if __name__ == "__main__":
    main()
