# Documentation-only lifecycle assessment

This separate analyzer evaluates repository documentation against Collection,
Processing, Method, Experimentation, Evaluation and Dissemination. It does not
replace the existing artifact classifier or reuse its write-once result cache.

## Run

```bash
python -m pip install -e .
research-documentation-steps https://github.com/liusi2019/ocd
research-documentation-steps --repos-file annotations/documentation_repositories.txt -o scores.md
research-documentation-steps --repos-file annotations/documentation_repositories.txt --format json -o documentation_results.json
```

Markdown output has exactly seven columns: GitHub URL and the six criteria above.
JSON retains rules, matched passages, reviewed files and commit-pinned line links.
Use `GITHUB_TOKEN` for authenticated requests. `--ref` selects a revision;
`--max-content-bytes` changes the per-file size limit (default 250000 bytes).

## Rules and scope

File names only select eligible documentation; they never imply a lifecycle label.
Eligible inputs include README, Markdown, RST, AsciiDoc, R package manuals,
vignettes, notebook Markdown and HTML/text files in documentation directories.
Notebook code cells, source files, code comments, data, configuration, licenses
and changelogs are excluded. HTML script/style/code content and fenced program
logic are removed. Explicit shell invocations in documentation remain eligible.
External linked papers are not fetched.

Each positive requires an explicit relationship in prose: acquisition of data,
preparation of inputs, a model mechanism/parameter, experiment execution,
scientific validation, or a publication/research-output description. Algorithm
names, section headings, installation alone and generic README existence do not
qualify. Basic negation and TODO statements are suppressed.

Scores are 1 for matched documentation, 0 for no match after complete eligible
text coverage, and Unverified when a potentially relevant document was unreadable
or skipped. A positive remains 1 even if other documents could not be read.
Repository/tree request failures also become Unverified in batch output.

## Limits and validation

Deterministic regex rules approximate the manual rubric, not human understanding.
They can miss synonymous, multilingual or long cross-line explanations and can match
contextually irrelevant prose. Zero means no heuristic match, not proof of absent
documentation. PDF/binary manuals and external sites are outside supported text
coverage. Notebook links refer to Markdown strings in the JSON source. Manually
inspect JSON evidence and compare against independent annotations before using
these heuristics as research measurements. The bundled URL list has no labels.

```bash
pytest tests/test_documentation.py
```
