import assert from 'node:assert/strict';

const {GITHUB_SHA: sha, GITHUB_REPOSITORY: repository, GH_TOKEN: token} = process.env;
assert(repository === 'jongko54/feature-standards' && /^[a-f0-9]{40}$/.test(sha ?? '') && token, 'Missing trusted release context');
const response = await fetch(`https://api.github.com/repos/${repository}/actions/workflows/ci.yml/runs?head_sha=${sha}&per_page=100`, {
  headers: {Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'},
});
assert(response.ok, 'Could not verify source CI');
const runs = (await response.json()).workflow_runs;
assert(runs.some(run => run.head_sha === sha && run.head_branch === 'main' && run.event === 'push' && run.conclusion === 'success'),
  'Full CI for this main source commit must succeed before publishing the release tag');
console.log(`Verified full source CI for ${sha}`);
