# GetPullRequestUnidiff

A small Node/TypeScript tool that fetches the unified diff (unidiff) of an Azure DevOps pull request, given the pull request's web URL, for example:

```
https://dev.azure.com/{org}/{project}/_git/{repo}/pullrequest/{id}
https://{org}.visualstudio.com/{project}/_git/{repo}/pullrequest/{id}
```

It uses the [`azure-devops-node-api`](https://www.npmjs.com/package/azure-devops-node-api) package to read the pull request's merge commits and file changes, then builds a `git diff`-style unidiff with the [`diff`](https://www.npmjs.com/package/diff) package.

## Setup

```
npm install
npm run build
```

## Usage

Authenticate with a Personal Access Token (PAT) that has at least "Code (Read)" scope on the target project, supplied via the `AZURE_DEVOPS_PAT` (or `SYSTEM_ACCESSTOKEN`) environment variable:

```
export AZURE_DEVOPS_PAT=<your PAT>
npm run app -- "https://dev.azure.com/myorg/MyProject/_git/MyRepo/pullrequest/123"
```

The unidiff is written to stdout by default. Optionally pass a second argument to write it to a file instead:

```
npm run app -- "https://dev.azure.com/myorg/MyProject/_git/MyRepo/pullrequest/123" pr-123.diff
```

If run from within an Azure Pipelines job with `System.AccessToken` mapped to `SYSTEM_ACCESSTOKEN`, no PAT is required.
