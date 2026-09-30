# Research software reproducibility study starter

Contents:
- PROTOCOL.md: proposed research questions, required evidence, eligibility, controlled experiment, grading and analysis.
- PROMPTS.md: fixed agent prompt, task/metadata/output contracts, evaluator and extraction prompts.
- collect.py: standard-library resumable collection script, no repository code execution.
- data/manifest.json: full normalized source dataset; preserves unreviewed relation status.
- data/audit.json: source counts and hash.
- data/repos and data/papers: pilot provider responses, source evidence and PDF/text downloads where successful.
- data/collection_summary.json: exact collection successes/failures and scope.

Run from the unzipped project folder:

```bash
python3 collect.py software_with_publications_v2.json --out data --normalize-only
python3 collect.py software_with_publications_v2.json --out data --limit 5 --workers 2 --download-pdfs
# Full collection; optionally configure provider tokens in your environment first.
python3 collect.py software_with_publications_v2.json --out data --limit 0 --workers 2 --download-pdfs
# Retry cached errors; successful retrievals remain frozen.
python3 collect.py software_with_publications_v2.json --out data --limit 0 --workers 2 --download-pdfs --retry-errors
```

Optional environment variables: GITHUB_TOKEN and OPENAIRE_TOKEN. Do not put credentials in the dataset or logs. Unauthenticated provider limits may interrupt collection; error envelopes remain in the output. This script uses tested public endpoints. API access policies may change; inspect error records before interpreting absence. The selected first-five pilot is an engineering check, not a probability sample. Normalization rewrites manifest/audit, so preserve human-reviewed annotations separately and version them before rerunning. Different execution machines may generate different local paths in provenance.

SoMEF has not been installed or run for this delivery. After installing a pinned version and recording its configuration/model versions, the documented README-only command is:

```bash
somef describe -d data/repos/REPO_ID/README.txt -o data/repos/REPO_ID/somef_readme.json -t 0.8
```

Replace REPO_ID with an actual ID. This processes frozen README text, but does not replace full repository extraction of package/configuration metadata. Verify installed CLI support for extraction from a frozen local source checkout before running that broader stage. Running `somef describe -r https://github.com/OWNER/REPO -o output.json -t 0.8` is supported, but targets the live repo; it must not silently substitute a different snapshot in the experiment.

Your existing per-file artefact/process heuristics are an additional data source. Join them to snapshot files only when commit and file hashes match. The collector leaves label arrays empty and annotation_status=unannotated; it does not invent labels.

Still required before any result claim: relation/PDF identity validation, historical version selection, source/data archives, supplements, environment reconstruction, target specification, semantic annotation extraction, isolated execution, and independent grading. Public PDF retrieval does not imply permission to redistribute every PDF. Check licences before publishing the dataset; publish URLs/hashes and redistributable artefacts as appropriate.

## Restore the two large files after cloning

The largest PDF and original ZIP are stored in numbered parts to fit the upload connection limit. Their exact original sizes and SHA-256 hashes are recorded in CHUNKED_FILES.json. Reconstruct both with:

```bash
python3 experiments/reproducibility_analysis/restore_large_files.py
```

All other files are directly usable. The original ZIP contains the complete starter package; later discussion refined the study to baseline, OpenAIRE/SoMEF, and added file-semantics conditions. The original protocol/prompt documents have been preserved as initially created.
