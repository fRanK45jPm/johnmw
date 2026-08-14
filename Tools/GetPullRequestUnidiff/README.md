# GetPullRequestUnidiff

A Python 3 script that fetches the unified diff (unidiff) of an Azure DevOps pull request, given the pull request's web URL, for example:

```
https://dev.azure.com/{org}/{project}/_git/{repo}/pullrequest/{id}
https://{org}.visualstudio.com/{project}/_git/{repo}/pullrequest/{id}
```

It uses [`requests`](https://pypi.org/project/requests/) directly against the Azure DevOps REST API to read the pull request's merge commits and changed files, then builds a `git diff`-style unidiff with the standard library's `difflib`.

## Setup

```
pip install -r requirements.txt
```

## Usage

Authenticate with a Personal Access Token (PAT) that has at least "Code (Read)" scope on the target project, supplied via the `AZURE_DEVOPS_PAT` (or `SYSTEM_ACCESSTOKEN`) environment variable:

```
export AZURE_DEVOPS_PAT=<your PAT>
python3 get_pull_request_unidiff.py "https://dev.azure.com/myorg/MyProject/_git/MyRepo/pullrequest/123"
```

The unidiff is written to stdout by default. Optionally pass a second argument to write it to a file instead:

```
python3 get_pull_request_unidiff.py "https://dev.azure.com/myorg/MyProject/_git/MyRepo/pullrequest/123" pr-123.diff
```

If run from within an Azure Pipelines job with `System.AccessToken` mapped to `SYSTEM_ACCESSTOKEN`, no PAT is required.
