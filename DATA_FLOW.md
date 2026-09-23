# Data Flow and Provenance

This project keeps source data, derived shared datasets, experiment outputs, and manual annotations separate.

## Source

The shared dataset starts from the OpenAIRE software export published on Zenodo:

- Zenodo record: `12819872`
- Archive: `software.tar`
- Source URL: `https://zenodo.org/records/12819872/files/software.tar?download=1`

The raw archive is kept locally at `data/raw/software.tar`. The `data/raw/` directory is ignored by Git, so the large archive stays inside the project folder without being committed.

## Shared-data pipeline

```text
Zenodo software.tar
    |
    | 1. stream OpenAIRE software records
    v
all software records
    |
    | 2. inspect codeRepositoryUrl
    v
records with a source-code repository URL
    |
    | 3. keep valid github.com repository references
    v
GitHub-linked OpenAIRE software records
    |
    | 4. normalize repository URLs
    |    - remove .git
    |    - remove /tree/..., /blob/..., etc.
    |    - canonical form: https://github.com/OWNER/REPO
    v
data/openaire_zenodo_12819872/github_software_records.csv
    |
    | 5. case-insensitive deduplication by normalized GitHub URL
    v
data/openaire_zenodo_12819872/github_repositories.csv
```

The pipeline is implemented by:

`scripts/compile_openaire_github_dataset.py`

Run it from a locally downloaded archive:

```bash
python scripts/compile_openaire_github_dataset.py
```

## Shared outputs

### github_software_records.csv

Record-level data. A GitHub repository may appear more than once when multiple OpenAIRE software records refer to it.

This is the richest reusable table and preserves OpenAIRE metadata and the original repository URL.

### github_repositories.csv

Repository-level data. One row per normalized GitHub repository.

This is the main reusable population for repository-level experiments.

### summary.json

Human- and machine-readable counts, source provenance, compiler version, and input/output checksums.

### data_flow.json

Machine-readable lineage describing every transformation stage, counts before/after each stage, SHA-256 checksums, and the exact reproduction command.

## Annotation separation

Manual labels do **not** belong in the shared data tables.

```text
data/
  openaire_zenodo_12819872/
    github_software_records.csv
    github_repositories.csv
    summary.json
    data_flow.json

annotations/
  README.md
  ...future validation samples and manual labels...
```

Any validation set should be sampled from `github_repositories.csv` and written under `annotations/`.

This ensures Esteban and other experiments can reuse the same source data without inheriting labels or experiment-specific decisions.

## Future derived datasets

Any additional filtering stage should create a new file rather than overwrite the previous one. For example:

```text
github_repositories.csv
    |
    | verify repository availability
    v
github_repositories_available.csv
    |
    | optional experiment-specific eligibility criteria
    v
github_repositories_eligible.csv
```

Each new stage should be added to the lineage manifest with:

- input file and SHA-256;
- transformation script/version;
- selection rules;
- input/output counts;
- output file and SHA-256.

This keeps every experimental corpus traceable back to the original Zenodo archive.
