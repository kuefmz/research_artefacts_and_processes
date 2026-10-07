# Three-mode lifecycle heuristic methodology

## Scope and non-AI guarantee

`research-lifecycle-assess` is a deterministic static-analysis pipeline. Assessment-time classification uses **no AI**: no LLM or generative-model calls, embeddings, vector search, machine-learning classifiers, model inference, probabilistic scoring, or external semantic-analysis service. The only remote service used by the lifecycle runner is the GitHub REST API, solely to resolve a repository to a commit and retrieve its tree/file blobs.

Repository code is never executed, imported, installed, compiled, or invoked. Files are decoded as text and inspected using regular expressions, Python's standard-library AST parser for Python source, and JSON parsing for notebooks.

The six criteria, always in this order, are **Collection, Processing, Method, Experimentation, Evaluation, Dissemination**. Each mode produces binary values. A 1 means at least one documented static rule supplied evidence. A 0 means no such rule supplied evidence after complete supported-scope review.

## Shared commit-pinned snapshot

For each repository, the runner resolves the default branch to one commit SHA and uses that same commit for documentation-only, code-only, and combined results. Eligible Git blobs are retrieved by SHA and may be persisted in the local cache. Evidence links are commit-pinned. No mode observes a different repository revision within one stored result.

Excluded generated/vendor directories include `.git`, `node_modules`, `vendor`/`vendors`, `third_party`/`third-party`, `dist`, `build`, `target`, `__pycache__`, and `.ipynb_checkpoints`.

## Mode 1: documentation-only

Documentation eligibility is determined by the documentation analyzer. File names select inputs but do not themselves assign lifecycle scores. Notebook Markdown cells are documentation; notebook code cells are not documentation evidence.

Documentation text is normalized into physical-line-preserving review units. Rules are case-insensitive regular expressions requiring an action or relationship rather than an isolated lifecycle word. Negated statements such as unavailable/not implemented/no evaluation/TODO are excluded. Ordinary software-test language does not establish scientific Evaluation.

The rule families are:

| Criterion | Static documentation evidence |
| --- | --- |
| Collection | Data/corpus/observations/samples explicitly obtained, collected, acquired, downloaded, retrieved, mined, recorded or sourced; explicit download/fetch/retrieve/collect/generate/simulate of research data; explicit dataset/source relationship. |
| Processing | Explicit preprocessing, cleaning, normalization, standardization, tokenization, filtering, conversion or transformation of data/inputs/files/features; or documented input/data format, columns, dimensions or required fields. |
| Method | A model/algorithm/method/approach/estimator/network described through what it uses, computes, estimates, optimizes, samples, learns or maps; or parameter/hyperparameter/prior/kernel descriptions that state their role/default/distribution. |
| Experimentation | Instructions to run/execute/launch/reproduce an experiment, analysis, simulation, training, notebook or pipeline; documented commands whose executable name signals those operations. |
| Evaluation | Explicit research metrics and evaluation/validation/reporting; comparison/benchmarking against baselines, ground truth, measurements, methods or models; cross-validation/bootstrap/statistical intervals/tests/parameter recovery; documented evaluation/validation commands. |
| Dissemination | Explicit paper/publication/article/manuscript/preprint/thesis references with URL/DOI/publication relation; citation/BibTeX instructions; results/outputs saved or presented as figures/tables/plots/reports; reproduction/generation of numbered figures/tables. |

Stable evidence IDs are `DOC_<CRITERION>_<RULE_NUMBER>`. A documentation criterion is 1 iff at least one corresponding documentation rule matches admissible evidence.

## Mode 2: code-only

Supported code extensions are `.py`, `.r`, `.jl`, `.m`, `.java`, `.js`, `.ts`, `.go`, `.rs`, `.c`, `.cc`, `.cpp`, `.h`, `.hpp`, `.sh`, `.bash`, and notebook code cells.

Python is parsed with the standard-library `ast` module. Module/function/class docstrings are removed from executable evidence, and a regex hit must overlap an AST statement. Other supported languages use conservative line-oriented removal of full-line comments. Notebook code and Markdown cells are kept separate.

The stable code rules are:

| ID | Criterion | Static code signal |
| --- | --- | --- |
| CODE_COLLECTION_1 | Collection | Network/download/fetch-style calls such as requests, urlopen, wget, curl, download or fetch. |
| CODE_COLLECTION_2 | Collection | Data-loading calls such as read_csv/read_table/read_json/read_parquet/loadtxt/genfromtxt/open_dataset/load_dataset. |
| CODE_COLLECTION_3 | Collection | Random/simulation/synthetic/sample-generation calls. |
| CODE_PROCESSING_1 | Processing | Explicit normalize/standardize/preprocess/tokenize/clean/filter/transform/convert/resample/impute/feature-extraction calls. |
| CODE_PROCESSING_2 | Processing | Dataframe/array-style dropna/fillna/replace/astype/reshape/transpose/groupby/merge/join/pivot/scale/fit_transform calls. |
| CODE_METHOD_1 | Method | fit/predict/forward/backward/optimize/minimize/maximize/solve/sample calls. |
| CODE_METHOD_2 | Method | Assignments to loss/objective/likelihood/gradient/kernel/posterior/prior. |
| CODE_METHOD_3 | Method | Mathematical operations such as exp/log/sqrt/dot/matmul/einsum/softmax/sigmoid, optionally through common numerical namespaces. |
| CODE_EXPERIMENTATION_1 | Experimentation | main/run_experiment/train/run_analysis/experiment calls. |
| CODE_EXPERIMENTATION_2 | Experimentation | Parameter/seed/grid-style loops captured by the static rule. |
| CODE_EVALUATION_1 | Evaluation | Explicit scientific/ML metrics such as accuracy, precision, recall, F1, AUC, MSE/MAE/R2, perplexity, confusion matrix. |
| CODE_EVALUATION_2 | Evaluation | Cross-validation, bootstrap, statistical tests/intervals, model comparison or evaluate_model calls. |
| CODE_DISSEMINATION_1 | Dissemination | Figure/HTML/LaTeX/Markdown export calls. |
| CODE_DISSEMINATION_2 | Dissemination | CSV/Excel/table writes whose call text indicates result/metric/score/summary/table/report output. |
| CODE_DISSEMINATION_3 | Dissemination | report/results_table/summary_table export methods. |

Paths recognized as ordinary software tests do not establish Evaluation. Generic print/logging/console logging does not establish Dissemination. A code criterion is 1 iff at least one admissible code rule matches.

## Mode 3: documentation + code

Combined mode introduces **no additional heuristic, weighting, model, interpretation, or inference**. It is computed independently for each criterion as:

`combined[criterion] = int(documentation[criterion] OR code[criterion])`

Therefore, for every repository and criterion, combined can be reproduced exactly from the two component score tables.

## Evidence, failures, and reproducibility

Every positive result retains source type, stable rule ID, path, physical line(s), matched text, repository commit SHA, and a commit-pinned GitHub evidence URL.

A retrieval failure, unsupported relevant source format, size-limit skip, or analysis failure is not converted into a zero. It makes coverage incomplete and blocks final score-CSV export. This separates “reviewed and no rule matched” from “not fully reviewed.”

Completed repository results, commit-keyed assessment results, and successfully fetched Git blobs are persisted under the output cache. `progress.json` is written after each completed repository. Restarts reuse stored completed results and stored blobs rather than intentionally executing the same completed assessment twice.

The method version is recorded in each result together with `uses_ai: false`. Changes to heuristic behavior must change the method version so cached results from different methodologies are not silently mixed.
