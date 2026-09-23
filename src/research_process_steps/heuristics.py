"""Deterministic heuristics for research process step detection.

No machine learning, embeddings, language models, or probabilistic classifiers are
used here. Every emitted label is backed by one or more explicit rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Pattern


RESEARCH_PROCESS_STEPS = (
    "collection",
    "processing",
    "implementation",
    "experimentation",
    "evaluation",
    "dissemination",
)


# File-type information is used as a compatibility constraint on broad path
# heuristics. It is not itself a research-process-step prediction.
DATA_EXTENSIONS = {
    ".ttl", ".rdf", ".owl", ".nt", ".nq", ".trig",
    ".csv", ".tsv", ".jsonl", ".ndjson",
    ".parquet", ".feather", ".arrow",
    ".h5", ".hdf5", ".npy", ".npz", ".arff",
}
SOURCE_CODE_EXTENSIONS = {
    ".py", ".r", ".jl", ".js", ".ts", ".java", ".go", ".rs",
    ".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".sh", ".bash",
    ".scala", ".kt", ".m", ".swift", ".php", ".rb", ".pl",
}
NOTEBOOK_EXTENSIONS = {".ipynb", ".rmd", ".qmd"}
DOCUMENTATION_EXTENSIONS = {".md", ".rst", ".adoc"}
CONFIGURATION_EXTENSIONS = {".yaml", ".yml", ".toml", ".ini", ".cfg"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".tif", ".tiff"}
ARCHIVE_EXTENSIONS = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z"}

IMPLEMENTATION_GENERIC_RULES = {
    "IMP_PATH_SOURCE_DIR",
    "IMP_PATH_TESTS",
}
IMPLEMENTATION_COMPATIBLE_ARTIFACT_KINDS = {
    "source_code",
    "notebook",
}


def infer_artifact_kind(path: str) -> str:
    """Infer a coarse, deterministic file kind from name and extension."""
    file_path = Path(path)
    name = file_path.name.lower()
    suffix = file_path.suffix.lower()

    if suffix in DATA_EXTENSIONS:
        return "data"
    if suffix in SOURCE_CODE_EXTENSIONS:
        return "source_code"
    if suffix in NOTEBOOK_EXTENSIONS:
        return "notebook"
    if suffix in DOCUMENTATION_EXTENSIONS:
        return "documentation"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in ARCHIVE_EXTENSIONS:
        return "archive"

    if name in {
        "dockerfile", "makefile", "pyproject.toml", "setup.cfg", "setup.py",
        "package.json", "cargo.toml", "go.mod", "pom.xml", "build.gradle",
        "citation.cff", "codemeta.json",
    }:
        return "configuration"
    if suffix in CONFIGURATION_EXTENSIONS:
        return "configuration"

    return "other"


@dataclass(frozen=True)
class Rule:
    id: str
    step: str
    weight: int
    source: str  # "path" or "content"
    pattern: Pattern[str]
    description: str


def _r(
    rule_id: str,
    step: str,
    weight: int,
    source: str,
    pattern: str,
    description: str,
) -> Rule:
    return Rule(
        id=rule_id,
        step=step,
        weight=weight,
        source=source,
        pattern=re.compile(pattern, re.IGNORECASE),
        description=description,
    )


# Strong path rules are deliberately specific. Generic words such as "model",
# "data", or "result" are not enough on their own.
RULES = (
    # COLLECTION
    _r("COL_PATH_ACQUIRE_DIR", "collection", 3, "path",
       r"(^|/)(collect(ion)?|acquisition|scrap(e|ing|er|ers)|crawl(er|ing)?|harvest(ing)?|download(s)?|raw[_-]?data)(/|$)",
       "File is located in a directory explicitly associated with data acquisition."),
    _r("COL_PATH_ACQUIRE_FILE", "collection", 3, "path",
       r"(^|/)(collect|download|fetch|scrape|crawl|harvest)[_-][^/]+\.(py|r|sh|bash|ipynb|jl)$",
       "Filename explicitly denotes data acquisition."),
    _r("COL_CONTENT_ACQUIRE", "collection", 1, "content",
       r"\b(requests\.get|urllib\.request|wget\b|curl\b|scrapy\b|beautifulsoup\b|selenium\b|download[_ ]?dataset|fetch[_ ]?data|collect[_ ]?data)\b",
       "File contains deterministic indicators of external data acquisition."),

    # PROCESSING
    _r("PRO_PATH_PROCESS_DIR", "processing", 3, "path",
       r"(^|/)(preprocess(ing)?|process(ing)?|transform(ation)?|etl|clean(ing)?|normaliz(e|ation)|convert(ers?|ing)?|parsers?)(/|$)",
       "File is located in a directory explicitly associated with data transformation."),
    _r("PRO_PATH_PROCESS_FILE", "processing", 3, "path",
       r"(^|/)(preprocess|process|transform|clean|normalize|convert|parse|extract)[_-][^/]+\.(py|r|sh|bash|ipynb|jl)$",
       "Filename explicitly denotes data transformation or extraction."),
    _r("PRO_CONTENT_PROCESS", "processing", 1, "content",
       r"\b(dropna|fillna|normalize|standardize|tokenize|parse[_ ]|extract[_ ]|transform[_ ]|clean[_ ]?data|preprocess)\b",
       "File contains deterministic indicators of data preparation or transformation."),

    # IMPLEMENTATION
    _r("IMP_PATH_SOURCE_DIR", "implementation", 3, "path",
       r"(^|/)(src|lib|app|pkg|package|packages)(/|$)",
       "File is part of an implementation source tree."),
    _r("IMP_PATH_TESTS", "implementation", 2, "path",
       r"(^|/)(tests?|testing)(/|$)|(^|/)(test_[^/]+|[^/]+_test)\.(py|js|ts|java|cpp|c|rs|go)$",
       "Software tests are treated as implementation/verification, not scientific evaluation."),
    _r("IMP_PACKAGE_FILE", "implementation", 3, "path",
       r"(^|/)(pyproject\.toml|setup\.py|setup\.cfg|package\.json|cargo\.toml|go\.mod|pom\.xml|build\.gradle|requirements[^/]*\.txt|environment\.ya?ml|dockerfile|compose\.ya?ml)$",
       "File configures packaging, dependencies, build, runtime, or deployment."),
    _r("IMP_CLI_FILE", "implementation", 2, "path",
       r"(^|/)(cli|main|app|server)\.(py|js|ts|go|rs|java)$",
       "Filename is a conventional executable/application entry point."),
    _r("IMP_CONTENT_ENTRYPOINT", "implementation", 1, "content",
       r'\\b(if __name__\\s*==\\s*["\\\']__main__["\\\']|argparse\\.|click\\.(command|group)|typer\\.Typer|console_scripts)\\b',
       "File contains an executable or CLI entry-point pattern."),

    # EXPERIMENTATION
    _r("EXP_PATH_EXPERIMENT_DIR", "experimentation", 3, "path",
       r"(^|/)(experiments?|experimental|runs?|trials?|sweeps?)(/|$)",
       "File belongs to an explicitly named experimental directory."),
    _r("EXP_PATH_EXPERIMENT_FILE", "experimentation", 3, "path",
       r"(^|/)(run[_-])?(experiment|trial|sweep)[^/]*\.(py|r|sh|bash|ipynb|jl|ya?ml|json|toml)$",
       "Filename explicitly denotes an experiment, trial, or sweep."),
    _r("EXP_CONFIG_FILE", "experimentation", 2, "path",
       r"(^|/)(configs?|configurations?)/[^/]*(experiment|sweep|trial|train)[^/]*\.(ya?ml|json|toml)$",
       "Configuration file explicitly controls an experiment/training run."),
    _r("EXP_CONTENT_RUN", "experimentation", 1, "content",
       r"\b(random[_-]?seed|hyperparam(eter)?s?|parameter[_-]?grid|grid[_-]?search|sweep|num[_-]?runs|n[_-]?trials)\b",
       "File contains deterministic indicators of repeated/configured experimental runs."),

    # EVALUATION
    _r("EVA_PATH_EVAL_DIR", "evaluation", 3, "path",
       r"(^|/)(evaluation|eval|benchmark(s|ing)?|metrics?|ablations?|comparisons?)(/|$)",
       "File belongs to an explicitly named scientific evaluation directory."),
    _r("EVA_PATH_EVAL_FILE", "evaluation", 3, "path",
       r"(^|/)(evaluate|evaluation|benchmark|ablation|compare|metrics?)[_-]?[^/]*\.(py|r|sh|bash|ipynb|jl|csv|tsv|json)$",
       "Filename explicitly denotes scientific evaluation or benchmarking."),
    _r("EVA_CONTENT_METRIC", "evaluation", 1, "content",
       r"\b(precision|recall|f1([_-]?score)?|roc[_-]?auc|accuracy|rmse|mae|bleu|rouge|baseline comparison|ablation study)\b",
       "File contains explicit scientific performance metrics or comparison terminology."),

    # DISSEMINATION
    _r("DIS_PATH_DOC_DIR", "dissemination", 3, "path",
       r"(^|/)(docs?|documentation|paper|papers|publication|publications|manuscript|website|site)(/|$)",
       "File belongs to documentation, publication, or website material."),
    _r("DIS_CITATION_FILE", "dissemination", 3, "path",
       r"(^|/)(citation\.cff|codemeta\.json|zenodo\.json|\.zenodo\.json|references?\.bib)$",
       "File provides citation/publication metadata."),
    _r("DIS_README", "dissemination", 2, "path",
       r"(^|/)(readme|changelog|authors?|contributors?)\.(md|rst|txt)$",
       "Project-facing documentation supports dissemination."),
    _r("DIS_DOC_BUILD", "dissemination", 2, "path",
       r"(^|/)(mkdocs\.ya?ml|conf\.py|_config\.ya?ml|docusaurus\.config\.[jt]s)$",
       "File configures a documentation/publication site."),
    _r("DIS_CONTENT_CITATION", "dissemination", 1, "content",
       r"\b(doi:\s*10\.|doi\.org/10\.|zenodo|how to cite|citation|bibtex|published in|publication)\b",
       "File contains explicit citation or publication information."),
)


# Content is scanned only for likely human-readable/source files.
CONTENT_EXTENSIONS = {
    ".py", ".r", ".sh", ".bash", ".ipynb", ".jl", ".md", ".rst", ".txt",
    ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg", ".csv", ".tsv",
    ".jsonl", ".ndjson", ".ttl", ".rdf", ".owl", ".nt", ".nq", ".trig",
    ".js", ".ts", ".java", ".go", ".rs", ".cpp", ".c", ".h",
}
