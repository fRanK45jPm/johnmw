# GetPullRequestUnidiff

Fetches the unified diff (unidiff) of an Azure DevOps pull request, given the pull request's web URL, for example:

```
https://dev.azure.com/{org}/{project}/_git/{repo}/pullrequest/{id}
https://{org}.visualstudio.com/{project}/_git/{repo}/pullrequest/{id}
```

There are two equivalent implementations - use whichever suits your environment:

- **`GetPullRequestUnidiff.ts`** - Node/TypeScript, using the [`azure-devops-node-api`](https://www.npmjs.com/package/azure-devops-node-api) package and the [`diff`](https://www.npmjs.com/package/diff) package.
- **`get_pull_request_unidiff.py`** - Python 3, using [`requests`](https://pypi.org/project/requests/) directly against the Azure DevOps REST API and the standard library's `difflib`.

Both read the pull request's merge commits and changed files, then build a `git diff`-style unidiff.

Authenticate with a Personal Access Token (PAT) that has at least "Code (Read)" scope on the target project, supplied via the `AZURE_DEVOPS_PAT` (or `SYSTEM_ACCESSTOKEN`) environment variable. If run from within an Azure Pipelines job with `System.AccessToken` mapped to `SYSTEM_ACCESSTOKEN`, no PAT is required.

The unidiff is written to stdout by default in both versions. Pass a second argument to write it to a file instead.

## Node / TypeScript

```
npm install
npm run build

export AZURE_DEVOPS_PAT=<your PAT>
npm run app -- "https://dev.azure.com/myorg/MyProject/_git/MyRepo/pullrequest/123"
npm run app -- "https://dev.azure.com/myorg/MyProject/_git/MyRepo/pullrequest/123" pr-123.diff
```

## Python

```
pip install -r requirements.txt

export AZURE_DEVOPS_PAT=<your PAT>
python3 get_pull_request_unidiff.py "https://dev.azure.com/myorg/MyProject/_git/MyRepo/pullrequest/123"
python3 get_pull_request_unidiff.py "https://dev.azure.com/myorg/MyProject/_git/MyRepo/pullrequest/123" pr-123.diff
```
