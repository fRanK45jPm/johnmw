import * as webApi from "azure-devops-node-api/WebApi";
import { IGitApi } from "azure-devops-node-api/GitApi";
import * as GitInterfaces from "azure-devops-node-api/interfaces/GitInterfaces";
import * as fs from "fs";
import { createTwoFilesPatch } from "diff";

// A tool to fetch the unified diff (unidiff) of an Azure DevOps pull request
// given the pull request's web URL, for example:
//   https://dev.azure.com/{org}/{project}/_git/{repo}/pullrequest/{id}
//   https://{org}.visualstudio.com/{project}/_git/{repo}/pullrequest/{id}
//
// Authentication is via a Personal Access Token (PAT) provided in the
// AZURE_DEVOPS_PAT (or SYSTEM_ACCESSTOKEN) environment variable. The PAT
// needs at least "Code (Read)" scope on the target project.

interface ParsedPullRequestUrl {
    orgUrl: string;
    project: string;
    pullRequestId: number;
}

function parsePullRequestUrl(prUrl: string): ParsedPullRequestUrl {
    const url = new URL(prUrl);
    const segments = url.pathname.split("/").filter((s) => s.length > 0).map((s) => decodeURIComponent(s));

    const gitIndex = segments.indexOf("_git");
    if (gitIndex === -1 || segments.length < gitIndex + 2) {
        throw new Error(`Unable to find a '_git/{repo}' segment in the pull request URL '${prUrl}'`);
    }

    let prSegmentIndex = -1;
    for (let i = gitIndex + 1; i < segments.length; i++) {
        const lower = segments[i].toLowerCase();
        if (lower === "pullrequest" || lower === "pullrequests") {
            prSegmentIndex = i;
            break;
        }
    }
    if (prSegmentIndex === -1 || segments.length < prSegmentIndex + 2) {
        throw new Error(`Unable to find a 'pullrequest/{id}' segment in the pull request URL '${prUrl}'`);
    }

    const pullRequestId = parseInt(segments[prSegmentIndex + 1], 10);
    if (isNaN(pullRequestId)) {
        throw new Error(`'${segments[prSegmentIndex + 1]}' is not a valid pull request id in the URL '${prUrl}'`);
    }

    const hostname = url.hostname.toLowerCase();
    let orgUrl: string;
    let projectSegments: string[];

    if (hostname === "dev.azure.com") {
        // https://dev.azure.com/{org}/{project}/_git/{repo}/pullrequest/{id}
        orgUrl = `https://dev.azure.com/${segments[0]}`;
        projectSegments = segments.slice(1, gitIndex);
    } else if (hostname.indexOf(".visualstudio.com") !== -1) {
        // https://{org}.visualstudio.com/{project}/_git/{repo}/pullrequest/{id}
        // (also copes with the legacy .../DefaultCollection/{project}/_git/... form)
        orgUrl = `https://${url.hostname}`;
        projectSegments = segments.slice(0, gitIndex).filter((s) => s.toLowerCase() !== "defaultcollection");
    } else {
        throw new Error(`Unrecognised Azure DevOps host '${url.hostname}'. Expected 'dev.azure.com' or '{org}.visualstudio.com'`);
    }

    const project = projectSegments.join("/");
    if (!project) {
        throw new Error(`Unable to determine the project from the pull request URL '${prUrl}'`);
    }

    return { orgUrl, project, pullRequestId };
}

function streamToString(stream: NodeJS.ReadableStream): Promise<string> {
    return new Promise<string>((resolve, reject) => {
        const chunks: Buffer[] = [];
        stream.on("data", (chunk: Buffer | string) => {
            chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
        });
        stream.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
        stream.on("error", (err: Error) => reject(err));
    });
}

function isLikelyBinary(content: string): boolean {
    // Mirrors git's own heuristic: a NUL byte means the content isn't text
    return content.indexOf("\u0000") !== -1;
}

async function getBlobText(gitApi: IGitApi, repositoryId: string, sha1: string, project: string): Promise<string> {
    const stream = await gitApi.getBlobContent(repositoryId, sha1, project);
    return streamToString(stream);
}

async function run(): Promise<void> {
    const args = process.argv.slice(2);
    if (args.length < 1) {
        console.error("Usage: npm run app -- <pull-request-url> [output-file]");
        console.error("");
        console.error("Set the AZURE_DEVOPS_PAT (or SYSTEM_ACCESSTOKEN) environment variable to a");
        console.error("Personal Access Token with 'Code (Read)' scope to authenticate.");
        process.exitCode = 1;
        return;
    }

    const prUrl = args[0];
    const outFile = args[1];
    const pat = process.env.AZURE_DEVOPS_PAT || process.env.SYSTEM_ACCESSTOKEN || "";

    const { orgUrl, project, pullRequestId } = parsePullRequestUrl(prUrl);

    console.error(`Connecting to '${orgUrl}'`);
    const credHandler = webApi.getHandlerFromToken(pat);
    const vsts = new webApi.WebApi(orgUrl, credHandler);
    const gitApi: IGitApi = await vsts.getGitApi();

    console.error(`Getting pull request ${pullRequestId} in project '${project}'`);
    const pr = await gitApi.getPullRequestById(pullRequestId, project);
    if (!pr || !pr.repository || !pr.repository.id) {
        throw new Error(`Could not find pull request ${pullRequestId} in project '${project}'`);
    }

    const repositoryId = pr.repository.id;
    const targetCommit = pr.lastMergeTargetCommit && pr.lastMergeTargetCommit.commitId;
    const sourceCommit = pr.lastMergeSourceCommit && pr.lastMergeSourceCommit.commitId;

    if (!targetCommit || !sourceCommit) {
        throw new Error("The pull request has no merge commit information yet - it may still be evaluating");
    }

    console.error(`Diffing target commit ${targetCommit} against source commit ${sourceCommit}`);
    const diffs = await gitApi.getCommitDiffs(
        repositoryId,
        project,
        true,
        undefined,
        undefined,
        { baseVersion: targetCommit, baseVersionType: GitInterfaces.GitVersionType.Commit },
        { targetVersion: sourceCommit, targetVersionType: GitInterfaces.GitVersionType.Commit });

    const changes = (diffs.changes || []).filter((c) =>
        c.item && c.item.path && c.item.gitObjectType !== GitInterfaces.GitObjectType.Tree);

    const patches: string[] = [];

    for (const change of changes) {
        const item = change.item as GitInterfaces.GitItem;
        const path = item.path as string;
        const changeType = change.changeType || GitInterfaces.VersionControlChangeType.None;
        const isAdd = (changeType & GitInterfaces.VersionControlChangeType.Add) !== 0;
        const isDelete = (changeType & GitInterfaces.VersionControlChangeType.Delete) !== 0;
        const oldPath = change.originalPath || path;

        console.error(`   ${GitInterfaces.VersionControlChangeType[changeType] || changeType}: ${path}`);

        let oldText = "";
        let newText = "";
        try {
            if (!isAdd && item.originalObjectId) {
                oldText = await getBlobText(gitApi, repositoryId, item.originalObjectId, project);
            }
            if (!isDelete && item.objectId) {
                newText = await getBlobText(gitApi, repositoryId, item.objectId, project);
            }
        } catch (err) {
            console.error(`      Warning: could not read content for '${path}': ${(err as Error).message}`);
            continue;
        }

        const header = `diff --git a/${oldPath} b/${path}`;

        if (isLikelyBinary(oldText) || isLikelyBinary(newText)) {
            patches.push(`${header}\nBinary files a/${oldPath} and b/${path} differ\n`);
            continue;
        }

        const patch = createTwoFilesPatch(
            isAdd ? "/dev/null" : `a/${oldPath}`,
            isDelete ? "/dev/null" : `b/${path}`,
            oldText,
            newText,
            "",
            "");

        patches.push(`${header}\n${patch}`);
    }

    const unidiff = patches.join("\n");

    if (outFile) {
        fs.writeFileSync(outFile, unidiff);
        console.error(`Unified diff written to '${outFile}'`);
    } else {
        process.stdout.write(unidiff);
    }
}

run().catch((err: Error) => {
    console.error(err.message || err);
    process.exitCode = 1;
});
