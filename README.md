# Research Process Steps Experiments

Deterministic, explainable heuristics for identifying which **research process step(s)** individual files in a GitHub repository support.

The implementation uses **no AI**: no LLMs, embeddings, machine-learning models, or probabilistic classifiers. Labels are produced only from explicit, auditable path/filename rules and regular-expression content rules.

## Research process steps

The detector is multi-label and supports six steps:

- **Collection** — acquisition or generation of raw research data.
- **Processing** — parsing, cleaning, transformation, extraction, or preparation.
- **Implementation** — implementation, packaging, execution, or software verification.
- **Experimentation** — scripts/configuration/artifacts used to run research experiments.
- **Evaluation** — scientific benchmarking, metrics, comparisons, or ablations.
- **Dissemination** — documentation, citation metadata, publications, or distribution.

A file may support more than one step. If no rule provides sufficient evidence, the file is deliberately returned as `unclassified`.

## Python usage

```python
from research_process_steps import analyze_github_repository

result = analyze_github_repository(
    "https://github.com/KnowledgeCaptureAndDiscovery/somef"
)

for file in result["files"]:
    print(file["path"], file["steps"])
```

Each file keeps the exact evidence that caused a label:

```python
file = result["files"][0]
print(file["steps"])
print(file["scores"])
print(file["evidence"])
```

Example shape:

```json
{
  "path": "experiments/evaluate_model.py",
  "steps": ["experimentation", "evaluation"],
  "unclassified": false,
  "scores": {
    "experimentation": 3,
    "evaluation": 3
  },
  "evidence": [
    {
      "rule_id": "EXP_PATH_EXPERIMENT_DIR",
      "step": "experimentation",
      "source": "path",
      "weight": 3
    },
    {
      "rule_id": "EVA_PATH_EVAL_FILE",
      "step": "evaluation",
      "source": "path",
      "weight": 3
    }
  ]
}
```

## Available command-line scripts

After installing the project in editable mode:

```bash
python -m pip install -e .
```

the following commands are available.

### Repository execution and inspection

| Command | Purpose |
| --- | --- |
| `research-process-steps <repo-url>` | Analyze one GitHub repository with the deterministic heuristics. |
| `research-process-steps-web` | Start the FastAPI/web interface. |
| `research-process-steps-precache` | Pre-cache the configured demo repositories. |
| `research-process-steps-random [N]` | Analyze a random batch of unseen repositories. |
| `research-process-steps-all` | Process the complete repository CSV with caching, resumability, parallel workers, timeouts, and rate-limit handling. |

### Independent analysis scripts

Each analysis command can be run independently against whatever completed results
currently exist in `data/heuristic_results/`.

| Command | Purpose | Default output |
| --- | --- | --- |
| `research-process-steps-analyze` | Overall partial-corpus summary: repositories, files, classification counts, process-step counts, artifact kinds, extensions, and evidence rules. | `data/analysis/` |
| `research-process-steps-profile` | Analyze what a typical repository looks like: mean/median size, unclassified share, content-scanned files, and per-step repository prevalence/composition. | `data/analysis_repository_profile/` |
| `research-process-steps-unclassified` | Analyze only unclassified files: extensions, artifact kinds, source-code extensions, excluded-by-design files, and still-eligible unclassified files. | `data/analysis_unclassified/` |
| `research-process-steps-coverage` | Analyze classification coverage and heuristic behavior: extension-level classification rates, eligible vs excluded coverage, source-like coverage, and heuristic rule drivers. | `data/analysis_coverage/` |\n| `research-process-steps-unclassified-content` | Inspect cached contents of unclassified source files: filenames, directories, imports, symbols, keywords, LOC, near-miss scores/rules, and representative samples. Makes no GitHub requests. | `data/analysis_unclassified_content/` |\n| `research-process-steps-analyze-all` | Run all five analyses in sequence and collect a meeting-ready snapshot plus all detailed outputs in one folder. | `data/analysis_meeting/` |

Typical usage:

```bash
research-process-steps-analyze
research-process-steps-profile
research-process-steps-unclassified
research-process-steps-coverage
```

All four analysis commands are read-only with respect to the stored repository
results. They can be rerun while the crawler is running; each command regenerates
only its own aggregate analysis output directory.

## CLI

Install locally:

```bash
python -m pip install -e .
```

Analyze a repository:

```bash
research-process-steps https://github.com/KnowledgeCaptureAndDiscovery/somef
```

Write the complete per-file result to JSON:

```bash
research-process-steps \
  https://github.com/KnowledgeCaptureAndDiscovery/somef \
  -o somef_steps.json
```

An optional GitHub token can be supplied through `GITHUB_TOKEN` or `--token`.

## Heuristic design

Rules have a stable ID, a process step, an evidence source, and a weight.

- **3 — strong evidence:** explicit structural/file signal such as `experiments/` or `evaluation/benchmark.py`.
- **2 — medium evidence:** conventional but less specific signal such as a README.
- **1 — weak evidence:** deterministic content regex.

The current detection threshold is **2**, so a single incidental content keyword cannot assign a process step.

Path and filename evidence is primary. Content inspection is secondary and is performed only on likely text/source files below a configurable size threshold.

Every recognized source-code extension provides Implementation evidence through
`IMP_SOURCE_CODE_FILE`, regardless of directory (including repository-root files,
R package directories, documentation examples, and vendor directories). All
recognized source-code extensions are eligible for content scanning. Other
process-step rules still apply, so a source file can receive multiple labels.
Existing stored analyses are reused; regenerate them with the CLI to see updated
heuristics in previously analyzed repositories.

### Evaluation vs software tests

Ordinary software tests (`tests/`, `test_*.py`, etc.) are classified as **Implementation**, not scientific **Evaluation**. Evaluation requires evidence such as explicit benchmark/evaluation/metric/ablation artifacts.

## Output structure

The returned JSON contains:

- `repository`: repository/ref and file count.
- `method`: method metadata, including `uses_ai: false`.
- `summary`: number of files detected for each step and number unclassified.
- `files`: one record for **every repository file**, including labels, score, matched rule IDs, and evidence.

This evidence-preserving output is intended for later validation against a manually annotated corpus.

## Tests

```bash
python -m pip install pytest
pytest
```

The initial tests cover all six process steps, multi-label behavior, unclassified files, and the distinction between scientific evaluation and software unit tests.


## Experiment web interface and API

A small FastAPI application is included for interactive experimentation.

Install the project and start the interface:

```bash
python -m pip install -e .
research-process-steps-web
```

Then open:

```text
http://127.0.0.1:8000
```

The interface lets you paste a GitHub repository URL and inspect every file. For each file it shows:

- detected research process step(s);
- heuristic score per step;
- the exact rule(s) that fired;
- why each rule maps to that research process step;
- the exact matched keyword/text found in the path or file contents;
- files for which no heuristic produced enough evidence.

Results can be filtered by research process step or searched by path, rule, or matched term.

### API

The same functionality is available as an HTTP endpoint:

```http
POST /api/analyze
Content-Type: application/json
```

Request:

```json
{
  "repo_url": "https://github.com/KnowledgeCaptureAndDiscovery/somef"
}
```

Optional fields are `ref`, `max_content_bytes`, and `force` (default `false`).
Set `force: true` to rerun heuristics using the current rules and replace the stored
result. The web interface does not expose forced reruns. Failed reruns preserve the
previous result.

A file-level response contains evidence such as:

```json
{
  "path": "experiments/evaluate_model.py",
  "steps": ["experimentation", "evaluation"],
  "scores": {
    "experimentation": 3,
    "evaluation": 3
  },
  "evidence": [
    {
      "rule_id": "EXP_PATH_EXPERIMENT_DIR",
      "step": "experimentation",
      "source": "path",
      "weight": 3,
      "matched_text": "experiments/",
      "matched_texts": ["experiments/"],
      "description": "File belongs to an explicitly named experimental directory."
    }
  ]
}
```

FastAPI's automatically generated API documentation is available at `/docs`.

For larger experiments, set a `GITHUB_TOKEN` environment variable before starting the server to increase the GitHub API rate limit. The token is read only by the backend and is never sent to the browser.


### Demo preparation

SoMEF and WIDOCO are configured as persistent demo examples. Their results are stored under the local cache directory and reused across server restarts.

Before a presentation, populate both caches once:

```bash
research-process-steps-precache
```

After this command completes, selecting SoMEF or WIDOCO in the interface uses the cached JSON instead of scanning GitHub again. The interface displays a **cached result** badge when a cached response is used.

Repository file names in the result table link directly to the corresponding GitHub file. Content-based heuristic matches also include their exact line number and link directly to that line on GitHub, making it easier to manually check whether an assignment is correct. Path-based heuristics link to the file because they do not originate from a particular source-code line.


## Persistent random corpus experiments

Repository analyses are **cached by repository URL**. Normal requests reuse stored results. Explicit reruns (`force: true` on `POST /api/analyze`) bypass repository and demo caches, scan the default branch again, and replace the stored result. Random batches continue to select never-executed repositories.

By default, results are written under:

```text
data/heuristic_results/
```

Each repository gets:

- a complete JSON result containing every file and heuristic evidence;
- a lightweight `.meta.json` record used by the frontend history table.

The directory is intentionally gitignored because complete per-file results can become large. Set `RPS_RESULTS_DIR` to place the persistent store elsewhere.

### Run 100 random repositories from the command line

The repository-level OpenAIRE corpus at `data/openaire_zenodo_12819872/github_repositories.csv` is the default sampling population.

After installing the project:

```bash
research-process-steps-random
```

The default is 100 repositories. Explicit supported sizes are:

```bash
research-process-steps-random 10
research-process-steps-random 20
research-process-steps-random 25
research-process-steps-random 50
research-process-steps-random 100
```

Sampling is performed only from repositories that do **not** already have a stored result. Every successful repository is saved immediately before the next repository is started, so completed work is retained even if a later repository fails.

### Frontend batch execution and history

The web interface includes buttons for **10, 20, 25, 50, and 100** random unseen repositories. It also shows an **Executed repositories** table containing every locally stored repository. Select **View output** to reopen the complete file-level result without rerunning the repository.

The corresponding API endpoints are:

```text
GET  /api/executed
GET  /api/executed/{execution_id}
POST /api/random
```

Example random request:

```json
{
  "count": 100
}
```

The single-repository `POST /api/analyze` endpoint uses the same permanent result store, so a repository analyzed manually cannot later be selected by a random batch and vice versa.


## Run the complete CSV safely and resumably

The `research-process-steps-all` command executes every unique
`github_repository_url` in the repository-level CSV. It is designed for long
runs:

- requires authenticated GitHub access;
- checks the authenticated core API quota before each unseen repository;
- keeps a configurable reserve (100 requests by default);
- sleeps until the reset window instead of intentionally exhausting the quota;
- retries transient and secondary rate-limit failures with backoff;
- processes repositories sequentially to avoid aggressive API concurrency;
- saves every completed heuristic result immediately;
- skips completed repositories on future runs;
- stores GitHub repository metadata, recursive tree data, and every fetched
  text/source file in a reusable raw cache;
- stores persistent JSONL logs, errors, and a progress checkpoint.

Default local output locations:

```text
data/heuristic_results/   # complete per-repository heuristic outputs
data/github_cache/        # reusable GitHub metadata/tree/fetched source cache
data/batch_runs/
  run_all.jsonl           # append-only execution log
  errors.jsonl            # repositories that still failed after retries
  progress.json           # current/resumable batch status
```

### GitHub authentication

Authenticated REST API requests normally have a core limit of 5,000 requests
per hour, compared with 60 requests per hour for unauthenticated requests.

A convenient local setup is GitHub CLI:

```bash
gh auth login
export GITHUB_TOKEN="$(gh auth token)"
```

Verify that the environment variable is available without printing the token:

```bash
python -c "import os; print('GITHUB_TOKEN set:', bool(os.getenv('GITHUB_TOKEN')))"
```

You can also create a personal access token in GitHub and export it directly:

```bash
export GITHUB_TOKEN="YOUR_TOKEN"
```

Do not commit the token to this repository and do not put it in a tracked
`.env` file.

### Recommended first run

After checking out `dev`, install the project in editable mode:

```bash
git checkout dev
git pull origin dev
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python -m pip install pytest
pytest
```

Then test only three CSV repositories:

```bash
research-process-steps-all --limit 3
```

Inspect:

```bash
cat data/batch_runs/progress.json
tail -n 20 data/batch_runs/run_all.jsonl
```

If that looks correct, run the complete repository CSV:

```bash
research-process-steps-all
```

The default CSV is:

```text
data/openaire_zenodo_12819872/github_repositories.csv
```

To use another CSV:

```bash
research-process-steps-all --dataset /path/to/github_repositories.csv
```

If the process is stopped, run the same command again. Repositories with a
stored result are skipped, and cached raw GitHub inputs remain available.

The runner intentionally leaves the final 100 core API requests unused. Change
the reserve only if needed:

```bash
research-process-steps-all --rate-limit-reserve 200
```


### Parallel full-corpus execution

The full CSV runner now processes repositories concurrently. The default is four
repository workers:

```bash
research-process-steps-all --workers 4
```

For this workload, a conservative range is 2-6 workers. More workers can increase
throughput, but GitHub secondary rate limits and local disk/network contention can
reduce the benefit of aggressive concurrency.

Recommended overnight command:

```bash
research-process-steps-all --workers 4
```

If the run remains stable and you want to push harder:

```bash
research-process-steps-all --workers 6
```

Avoid very high worker counts. Each repository is still persisted independently,
so stopping and restarting remains safe.


### Fast pass: skip slow repositories

The full-corpus runner has a per-repository timeout. By default, any repository
that takes longer than 60 seconds is aborted, logged, and left without a final
result so it can be revisited later:

```bash
research-process-steps-all --workers 16 --repo-timeout-seconds 60
```

Timed-out repositories emit a `repository_timeout` event in
`data/batch_runs/run_all.jsonl` and are also recorded as failed for the run.
Any raw metadata/tree/content already cached before the timeout remains reusable.

Disable the timeout for a later slow-repository pass with:

```bash
research-process-steps-all --workers 4 --repo-timeout-seconds 0
```


### Analyze the completed subset while the crawl is still running

You do not need to wait for the full repository corpus. Analyze every successfully
stored result currently present in `data/heuristic_results/` with:

```bash
research-process-steps-analyze
```

The command writes aggregate outputs to `data/analysis/`:

- `overall_summary.json` — corpus-level counts and repository-size statistics
- `repository_summary.csv` — one row per completed repository
- `step_summary.csv` — file- and repository-level frequencies for each research-process step
- `artifact_kind_summary.csv` — artifact-kind distribution
- `extension_summary.csv` — file-extension distribution
- `evidence_rule_summary.csv` — frequency of heuristic evidence rules

The analysis is safe to rerun at any time. It only reads completed result JSON files
and overwrites the aggregate analysis outputs with a fresh snapshot.


### Failed repository handling

The full-corpus runner does **not** retry repositories that previously ended in
`repository_error`. On restart it reads `data/batch_runs/errors.jsonl` and
skips those repository URLs, just as it skips repositories that already have a
successful stored result.

This prevents inaccessible, forbidden, missing, or otherwise failing
repositories from repeatedly consuming GitHub requests.

The default is also one repository attempt per run:

```bash
research-process-steps-all --workers 16 --repo-timeout-seconds 60
```

If you intentionally want to revisit the historical failures later, use:

```bash
research-process-steps-all --retry-failed --max-retries 1
```

A non-rate-limit HTTP 403 is recorded as a repository failure and skipped on
subsequent runs. Only 403/429 responses that actually indicate a GitHub rate
limit trigger the global rate-limit pause.


### Result-preserving large-repository optimization

Large repositories can cause GitHub's recursive tree endpoint to return
`truncated: true`. Previously the runner then walked every sub-tree through the
REST API, which could consume many API requests for a single repository.

The optimized runner now first uses a single non-REST GitHub codeload archive for
those truncated repositories. It reconstructs Git blob SHAs and Git tree SHAs
locally and accepts the optimized snapshot **only if the reconstructed root tree
SHA exactly matches the root tree SHA returned by GitHub**.

If that SHA validation fails for any reason (for example, an unusual repository
layout such as submodules), the runner automatically falls back to the original
non-recursive REST tree walk.

The scientific classification path is unchanged: the same file paths, same
content-size limit, same content decoding, same heuristic rules, same rule
weights, same threshold, same evidence construction, and same result schema are
used. Unit tests also compare heuristic output from archive-derived content with
the original content path.


### REST-free Git acquisition for the full corpus

The full-corpus runner now defaults to an exact shallow Git snapshot instead of
GitHub REST repository/tree requests:

```bash
research-process-steps-all --workers 8 --repo-timeout-seconds 60
```

This default `git` acquisition mode uses Git's smart HTTP transport to resolve
the default branch and exact HEAD commit, shallow-clones that snapshot, reads the
Git tree/blob metadata locally, and feeds the unchanged heuristic analyzer the
same path/content inputs. It does not consume the GitHub REST core 5,000/hour
quota.

The result stores both the resolved commit SHA and tree SHA for reproducibility.

The historical API acquisition path remains available explicitly:

```bash
research-process-steps-all --acquisition-mode api
```

Existing successful result JSON files are still skipped and are never overwritten
by the full-corpus runner.

The Git acquisition tests construct local Git repositories and verify that blob
contents and heuristic outputs are identical to direct analyzer inputs.


### Hardened full-corpus runner

For long production runs, use the default Git acquisition mode. It preserves the
same heuristic rules and result schema while avoiding the GitHub REST core quota.

The runner now includes the following safeguards:

- one shallow clone per unseen repository (no separate `git ls-remote` request);
- batched `git cat-file --batch` reads instead of one subprocess per source file;
- bounded blob batches to avoid large-repository memory spikes;
- Git HTTP low-speed timeouts so stalled transfers fail instead of occupying a worker indefinitely;
- a bounded future queue (at most roughly twice the active worker count), rather
  than submitting the remaining ~100k repositories at once;
- a Git-mode concurrency safety cap of 16 workers, even if a larger value is requested;
- metadata-only resume checks, so completed result JSONs are not reparsed just to
  determine whether a repository is already finished;
- successful repositories are saved immediately;
- previously failed repositories remain skipped unless `--retry-failed` is explicitly used.

Before a long run, a useful production smoke test is:

```bash
research-process-steps-all --workers 16 --repo-timeout-seconds 60 --max-new 200
```

If that completes normally, resume the full corpus with:

```bash
research-process-steps-all --workers 16 --repo-timeout-seconds 60
```

Passing `--workers 32` in Git mode is accepted but intentionally capped to 16
concurrent workers for stability.


## First-ten-paper manual review

The first-ten-paper view contains the first **10 papers** in source dataset order,
linked to **8 distinct repositories**. The fixed selection and source provenance live
in `src/research_process_steps/datasets/first_10_papers.json`. These are recorded
OpenAIRE associations; paper/repository relevance remains unreviewed. Use the
view selector to switch back to the full repository explorer.

Install and run from the repository root:

```bash
pip install -e .
python scripts/run_selected_heuristics.py --list
python scripts/run_selected_heuristics.py
research-process-steps-web
```

The equivalent installed runner is `research-process-steps-selected`. It runs
only the existing deterministic file heuristics on the selected eight repos,
reuses results already in `RPS_RESULTS_DIR` (default `data/heuristic_results`),
continues after individual retrieval failures, and exits nonzero if any fail.
It does not execute repository code or download papers. Set `GITHUB_TOKEN` if
needed for GitHub API access. Results use the existing analyzer's current-source
collection behavior; they are not automatically pinned to publication versions.

Open http://127.0.0.1:8000 to browse the selection. Each paper has an initially
empty PDF slot, its original paper link, and an upload control (maximum 25 MB).
Uploaded PDFs persist in `data/selected_papers/D01.pdf` through `D10.pdf`, or in
`RPS_PAPERS_DIR` if set. You can also copy PDFs to those paths manually. Uploading
again replaces that paper's PDF. No PDFs are bundled or fetched automatically.
Keep the server local; uploads and stored outputs use the existing unauthenticated
local interface.

## Full software-with-publications collection

The complete uploaded collection is bundled unchanged at
`src/research_process_steps/datasets/software_with_publications_v2.json`:
386 software/repository records and 1,732 paper associations. Paper associations
are not necessarily unique publications or verified experiment packages.

```bash
pip install -e .
python scripts/run_publication_dataset_heuristics.py --list
python scripts/run_publication_dataset_heuristics.py
python scripts/run_publication_dataset_heuristics.py --force
python scripts/run_publication_dataset_heuristics.py --analytics-only
research-process-steps-web
```

The installed equivalent is `research-process-steps-publications`. The runner
normalizes nested GitHub file/tree URLs to their owner/repository root and
processes only this bundled collection, once per repository. Existing persisted
results are reused by default; pass `--force` to rerun all dataset repositories
with the current heuristics and replace stored results. Forced runs reuse the
persistent raw GitHub cache in `data/github_cache` when metadata, trees, or source
files are already cached, so a forced heuristic rerun can be much faster than a
fresh GitHub acquisition. Per-repository logs report the total file count, counts
for all six research-process steps, and unclassified files. Failures are reported
and produce a nonzero exit code. It never runs repository code or automatically
downloads papers.

The frontend defaults to **Full publication dataset**. Filter by repository or
paper title, and by presence of stored heuristic results. The execution history
is restricted to the dataset in this view. **Run dataset heuristics** starts a
background job with progress; **Run complete dataset analytics** runs all five
existing analytics on a fresh snapshot containing only this dataset's stored
results. The displayed summary reports completed/missing repositories; partial
coverage is not presented as a complete dataset run. Reports are written to
`data/publication_collection_analysis` (CLI override: `--output-dir`). Source
content analytics use only available cached source files and report missing
cache coverage; they do not fetch additional content.

Full-collection PDF slots start empty and are saved as `C0001.pdf` through
`C1732.pdf` in `RPS_PAPERS_DIR` (default `data/selected_papers`). First-ten-paper
slots keep their existing D01–D10 IDs. Use the view selector to access those
slots or the general explorer. Server jobs are tracked in memory; stopping the
server stops its jobs, while completed heuristic results and reports remain
on disk. Restart the runner to reuse completed results and attempt remaining
repositories.

### Rerun all stored repositories via API

The frontend does not expose a rerun action. To refresh every stored repository
with the current rules, use the API. Each successful result replaces its stored
output; a failed repository keeps its previous result and does not stop the
remaining reruns. The scope is all stored repositories.

API: `POST /api/publication-collection/jobs` with `{"action":"rerun_all"}`.
Poll `GET /api/publication-collection/jobs/{id}` for progress and results.

### Reproducibility conversations: C0 and C1

The full publication-dataset table has paper-level **C0** and **C1** columns:

- **C0** — conversation using the repository URL and uploaded paper PDF only.
- **C1** — conversation using the same repository URL and paper PDF plus the
  stored file-level research-process-step metadata.

The fixed prompt templates are visible from the frontend, and every full-dataset
paper row has **Copy prefilled C0 prompt** and **Copy prefilled C1 prompt** buttons.
The copied prompt automatically fills the case/paper ID, paper title, DOI, paper
source URL, repository URL, and stored repository ref when available. It also
states that the paper PDF is attached directly to the conversation, so no local
PDF URL needs to be pasted manually.

C0 is copied from
`dev_experiment_analysis/experiments/reproducibility_analysis/assessment_pilot/BASELINE_PROMPT_TEMPLATE.txt`.
C1 preserves the same static-assessment task while explicitly allowing the
supplied research-process-step metadata as fallible navigation evidence.

Each paper can store any number of C0 and C1 conversation URLs. **Add new**
creates another timestamped record; **Edit / overwrite** updates one existing
record while preserving its original creation timestamp and recording an updated
timestamp. Records persist under `data/reproducibility_conversations/` by
default; override with `RPS_REPRO_CONVERSATIONS_DIR`.

When heuristics exist for the repository, the C1 cell also exposes the generated
research-step metadata JSON payload containing file paths, blob identities,
artifact kinds, research-process-step labels, and heuristic evidence. Use
**Download JSON** to save it with the same case-ID convention as the paper PDF:
for example, `C0001.pdf` pairs with `C0001.json`. The prefilled C1 prompt
explicitly names both attachments.

Dataset heuristic runs pause and retry the same repository when GitHub reports
a rate limit instead of marking every remaining repository as failed. Set
`GITHUB_TOKEN` for a substantially larger authenticated GitHub API allowance.

Relevant API endpoints:

```text
GET  /api/reproducibility/prompts
POST /api/publication-collection/papers/{paper_id}/conversations
PUT  /api/publication-collection/papers/{paper_id}/conversations/{record_id}
GET  /api/publication-collection/papers/{paper_id}/research-step-metadata
```

The older repository-level conversation-link API remains available for existing
stored links and the executed-repositories view.
