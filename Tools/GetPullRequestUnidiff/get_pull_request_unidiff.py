#!/usr/bin/env python3
"""
Fetches the unified diff (unidiff) of an Azure DevOps pull request, given the
pull request's web URL, for example:

  https://dev.azure.com/{org}/{project}/_git/{repo}/pullrequest/{id}
  https://{org}.visualstudio.com/{project}/_git/{repo}/pullrequest/{id}

Authentication is via a Personal Access Token (PAT) provided in the
AZURE_DEVOPS_PAT (or SYSTEM_ACCESSTOKEN) environment variable. The PAT needs
at least "Code (Read)" scope on the target project.

Usage:
    python get_pull_request_unidiff.py <pull-request-url> [output-file]
"""

import argparse
import difflib
import os
import sys
from urllib.parse import unquote, urlsplit

import requests

API_VERSION = "7.1"


class PullRequestUrlError(ValueError):
    pass


def parse_pull_request_url(pr_url):
    parts = urlsplit(pr_url)
    segments = [unquote(s) for s in parts.path.split("/") if s]

    if "_git" not in segments:
        raise PullRequestUrlError(f"Unable to find a '_git/{{repo}}' segment in the pull request URL '{pr_url}'")
    git_index = segments.index("_git")
    if len(segments) < git_index + 2:
        raise PullRequestUrlError(f"Unable to find a '_git/{{repo}}' segment in the pull request URL '{pr_url}'")

    pr_segment_index = None
    for i in range(git_index + 1, len(segments)):
        if segments[i].lower() in ("pullrequest", "pullrequests"):
            pr_segment_index = i
            break
    if pr_segment_index is None or len(segments) < pr_segment_index + 2:
        raise PullRequestUrlError(f"Unable to find a 'pullrequest/{{id}}' segment in the pull request URL '{pr_url}'")

    id_segment = segments[pr_segment_index + 1]
    try:
        pull_request_id = int(id_segment)
    except ValueError:
        raise PullRequestUrlError(f"'{id_segment}' is not a valid pull request id in the URL '{pr_url}'")

    hostname = parts.hostname.lower() if parts.hostname else ""

    if hostname == "dev.azure.com":
        # https://dev.azure.com/{org}/{project}/_git/{repo}/pullrequest/{id}
        org_url = f"https://dev.azure.com/{segments[0]}"
        project_segments = segments[1:git_index]
    elif ".visualstudio.com" in hostname:
        # https://{org}.visualstudio.com/{project}/_git/{repo}/pullrequest/{id}
        # (also copes with the legacy .../DefaultCollection/{project}/_git/... form)
        org_url = f"https://{parts.hostname}"
        project_segments = [s for s in segments[:git_index] if s.lower() != "defaultcollection"]
    else:
        raise PullRequestUrlError(
            f"Unrecognised Azure DevOps host '{parts.hostname}'. Expected 'dev.azure.com' or '{{org}}.visualstudio.com'")

    project = "/".join(project_segments)
    if not project:
        raise PullRequestUrlError(f"Unable to determine the project from the pull request URL '{pr_url}'")

    return org_url, project, pull_request_id


class AzureDevOpsClient:
    def __init__(self, org_url, pat):
        self.org_url = org_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = ("", pat)
        # Without this header, Azure DevOps responds to an unauthenticated/invalid
        # REST call with a 302 to an interactive sign-in page instead of a 401/403.
        self.session.headers["X-TFS-FedAuthRedirect"] = "Suppress"

    def _get(self, url, extra_params=None, accept="application/json"):
        params = {"api-version": API_VERSION}
        if extra_params:
            params.update(extra_params)
        response = self.session.get(url, params=params, headers={"Accept": accept})
        if not response.ok:
            message = response.text
            try:
                message = response.json().get("message", message)
            except ValueError:
                pass
            raise RuntimeError(f"Request to '{url}' failed with {response.status_code}: {message}")
        return response

    def get_pull_request(self, project, pull_request_id):
        url = f"{self.org_url}/{project}/_apis/git/pullrequests/{pull_request_id}"
        return self._get(url).json()

    def get_commit_diffs(self, project, repository_id, base_commit, target_commit):
        url = f"{self.org_url}/{project}/_apis/git/repositories/{repository_id}/diffs/commits"
        params = {
            "baseVersion": base_commit,
            "baseVersionType": "commit",
            "targetVersion": target_commit,
            "targetVersionType": "commit",
        }
        return self._get(url, extra_params=params).json()

    def get_blob_bytes(self, project, repository_id, sha1):
        url = f"{self.org_url}/{project}/_apis/git/repositories/{repository_id}/blobs/{sha1}"
        return self._get(url, accept="text/plain").content


def is_likely_binary(content_bytes):
    # Mirrors git's own heuristic: a NUL byte means the content isn't text
    return b"\x00" in content_bytes


def decode_text(content_bytes):
    return content_bytes.decode("utf-8", errors="replace")


def build_unidiff(client, project, repository_id, changes):
    patches = []

    for change in changes:
        item = change.get("item") or {}
        path = item.get("path")
        if not path or item.get("gitObjectType") == "tree":
            continue

        change_type_parts = [p.strip().lower() for p in (change.get("changeType") or "").split(",")]
        is_add = "add" in change_type_parts
        is_delete = "delete" in change_type_parts
        old_path = change.get("originalPath") or path

        print(f"   {change.get('changeType')}: {path}", file=sys.stderr)

        old_bytes = b""
        new_bytes = b""
        try:
            if not is_add and item.get("originalObjectId"):
                old_bytes = client.get_blob_bytes(project, repository_id, item["originalObjectId"])
            if not is_delete and item.get("objectId"):
                new_bytes = client.get_blob_bytes(project, repository_id, item["objectId"])
        except RuntimeError as err:
            print(f"      Warning: could not read content for '{path}': {err}", file=sys.stderr)
            continue

        header = f"diff --git a/{old_path} b/{path}"

        if is_likely_binary(old_bytes) or is_likely_binary(new_bytes):
            patches.append(f"{header}\nBinary files a/{old_path} and b/{path} differ\n")
            continue

        old_lines = decode_text(old_bytes).splitlines(keepends=True)
        new_lines = decode_text(new_bytes).splitlines(keepends=True)

        diff_lines = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile="/dev/null" if is_add else f"a/{old_path}",
            tofile="/dev/null" if is_delete else f"b/{path}",
            lineterm="\n")

        patches.append(header + "\n" + "".join(diff_lines))

    return "\n".join(patches)


def main():
    parser = argparse.ArgumentParser(description="Fetch the unidiff for an Azure DevOps pull request")
    parser.add_argument("pull_request_url", help="The pull request's web URL")
    parser.add_argument("output_file", nargs="?", help="Optional file to write the unidiff to (defaults to stdout)")
    args = parser.parse_args()

    pat = os.environ.get("AZURE_DEVOPS_PAT") or os.environ.get("SYSTEM_ACCESSTOKEN") or ""
    if not pat:
        print("Warning: no AZURE_DEVOPS_PAT (or SYSTEM_ACCESSTOKEN) set - only public projects will work", file=sys.stderr)

    org_url, project, pull_request_id = parse_pull_request_url(args.pull_request_url)

    print(f"Connecting to '{org_url}'", file=sys.stderr)
    client = AzureDevOpsClient(org_url, pat)

    print(f"Getting pull request {pull_request_id} in project '{project}'", file=sys.stderr)
    pr = client.get_pull_request(project, pull_request_id)

    repository = pr.get("repository") or {}
    repository_id = repository.get("id")
    if not repository_id:
        raise RuntimeError(f"Could not find pull request {pull_request_id} in project '{project}'")

    target_commit = (pr.get("lastMergeTargetCommit") or {}).get("commitId")
    source_commit = (pr.get("lastMergeSourceCommit") or {}).get("commitId")
    if not target_commit or not source_commit:
        raise RuntimeError("The pull request has no merge commit information yet - it may still be evaluating")

    print(f"Diffing target commit {target_commit} against source commit {source_commit}", file=sys.stderr)
    diffs = client.get_commit_diffs(project, repository_id, target_commit, source_commit)

    unidiff = build_unidiff(client, project, repository_id, diffs.get("changes") or [])

    if args.output_file:
        with open(args.output_file, "w", encoding="utf-8") as f:
            f.write(unidiff)
        print(f"Unified diff written to '{args.output_file}'", file=sys.stderr)
    else:
        sys.stdout.write(unidiff)


if __name__ == "__main__":
    try:
        main()
    except (PullRequestUrlError, RuntimeError) as err:
        print(str(err), file=sys.stderr)
        sys.exit(1)
