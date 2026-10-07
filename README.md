# Research Process Steps Experiments

For the separate **documentation-only** six-criterion assessment (including
**Method**, rather than Implementation), see
[documentation heuristics](docs/documentation_heuristics.md). Run
`research-documentation-steps --repos-file annotations/documentation_repositories.txt`
to produce the seven-column score table.

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

Optional fields are `ref` and `max_content_bytes`.

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

Repository analyses are now **write-once by repository URL**. Before any manual or batch execution, the application checks the persistent result store. If that repository already has a result, the stored JSON is returned and GitHub is not scanned again.

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


## Three-mode lifecycle assessment

The `research-lifecycle-assess` command performs a deterministic, static review using exactly six criteria in this order: Collection, Processing, Method, Experimentation, Evaluation, and Dissemination. It supports documentation-only, code-only, and combined modes. Combined scores are the logical OR of the separately computed documentation and code scores.

The analyzer uses the GitHub REST API. It resolves each repository to one commit SHA, obtains a complete tree (falling back to recursive tree walking when GitHub truncates the recursive response), downloads each eligible file once, and reuses that snapshot for all requested modes. Set `GITHUB_TOKEN` for authenticated API access. Downloaded repository code is never executed.

Supported documentation includes README/manual/guide formats handled by the documentation analyzer plus notebook Markdown cells. Supported executable code extensions are Python, R, Julia, MATLAB, Java, JavaScript/TypeScript, Go, Rust, C/C++, shell, and notebook code cells. Python receives syntax-aware statement/docstring handling; other languages use conservative line-oriented comment exclusion. Vendored/generated directories and irrelevant binaries are excluded. Unsupported relevant formats, unreadable files, size-limit skips, API failures, and analysis failures make review coverage incomplete and prevent score-CSV export; details are written to `review_status.json`.

A score of 1 means a stable heuristic rule found supporting evidence, not that support is complete or high quality. A 0 is emitted only into final CSVs after supported-scope review completes. Heuristics are approximations of human review and are not validation against human assessments.

Install and authenticate:

```bash
python -m pip install -e .
export GITHUB_TOKEN="YOUR_GITHUB_TOKEN"
```

Run the bundled ordered 100-repository corpus and create all three CSVs:

```bash
research-lifecycle-assess --bundled --out-dir lifecycle_output
```

Outputs are `lifecycle_output/documentation_scores.csv`, `lifecycle_output/code_scores.csv`, `lifecycle_output/combined_scores.csv`, and `lifecycle_output/review_status.json`. Add `--evidence` for `lifecycle_output/evidence.json`. Evidence records include repository commit SHA, stable rule ID, source kind, path, exact physical line(s), matched operation/passage, commit-pinned GitHub link, and coverage status at repository level.

Individual modes and a custom ordered URL file are supported:

```bash
research-lifecycle-assess --bundled --mode documentation --out-dir lifecycle_output
research-lifecycle-assess --bundled --mode code --out-dir lifecycle_output
research-lifecycle-assess --bundled --mode combined --out-dir lifecycle_output
research-lifecycle-assess --repos-file repositories.txt --mode all --evidence --out-dir lifecycle_output
research-lifecycle-assess --repos-file repositories.txt --mode all --markdown --out-dir lifecycle_output
```

The cache key includes repository URL, resolved commit SHA, heuristic version, and content-size setting. `progress.json` is saved after every successfully analyzed repository so completed work survives later failures; reruns reuse cached completed repository assessments.
