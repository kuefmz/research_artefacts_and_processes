import json
import pytest
from research_process_steps.documentation import (
    analyze_document,
    is_documentation,
    CRITERIA,
)
from research_process_steps import documentation_analyzer as analyzer


def test_six_documented_relationships():
    text = """Download the dataset from the university archive.
Normalize input data before training.
The model combines two encoders to estimate similarity.
Run the experiment using the supplied notebook.
Evaluation reports accuracy on held-out samples.
The paper is published at https://example.org/paper."""
    result = analyze_document("README.md", text)
    assert result["scores"] == dict.fromkeys(CRITERIA, 1)
    assert [e["line"] for e in result["evidence"]] == list(range(1, 7))


@pytest.mark.parametrize(
    "path",
    [
        "src/train.py",
        "tests/test_eval.py",
        "data/metrics.csv",
        "config.yaml",
        "LICENSE",
        "docs/config.json",
    ],
)
def test_excluded_files_cannot_score(path):
    assert not is_documentation(path)
    assert not any(
        analyze_document(
            path, "Download data; run experiments; evaluation reports accuracy."
        )["scores"].values()
    )


def test_filenames_and_keywords_alone_are_not_evidence():
    assert not any(
        analyze_document(
            "experiments/evaluation/README.md",
            "# Collection\nProcessing\nTransformer\nEvaluation\nREADME",
        )["scores"].values()
    )


def test_negations_and_installation_do_not_score():
    text = "No evaluation reports accuracy.\nRun pip install package.\nThe algorithm is Transformer.\nTODO: download the dataset."
    assert not any(analyze_document("README.md", text)["scores"].values())


def test_software_verification_is_not_research_evaluation():
    result = analyze_document(
        "README.md",
        "Run validation with unit tests. Evaluation reports accuracy of software tests.",
    )
    assert result["scores"]["evaluation"] == 0


def test_notebook_code_is_excluded_and_markdown_keeps_source_line():
    text = json.dumps(
        {
            "cells": [
                {"cell_type": "code", "source": ["Download the dataset."]},
                {"cell_type": "markdown", "source": ["Normalize input data."]},
            ]
        },
        indent=2,
    )
    result = analyze_document("Tutorial.ipynb", text)
    assert result["scores"]["collection"] == 0
    assert result["scores"]["processing"] == 1
    line = result["evidence"][0]["line"]
    assert "Normalize input data." in text.splitlines()[line - 1]


def test_vignette_code_and_html_scripts_are_excluded():
    assert not any(
        analyze_document(
            "guide.Rmd", "```{r}\nmodel uses data to estimate similarity\n```"
        )["scores"].values()
    )
    assert not any(
        analyze_document("docs/index.html", "<script>Download the dataset.</script>")[
            "scores"
        ].values()
    )
    assert (
        analyze_document("docs/index.html", "<p>Download the dataset.</p>")["scores"][
            "collection"
        ]
        == 1
    )


def test_html_markup_and_frontmatter():
    assert (
        analyze_document(
            "docs/index.html", "<p>Download the <strong>dataset</strong>.</p>"
        )["scores"]["collection"]
        == 1
    )
    assert not any(
        analyze_document(
            "guide.Rmd", "---\ntitle: Download the dataset.\n---\n# Introduction"
        )["scores"].values()
    )
    text = "<p>\n\nDownload the dataset.\n</p>"
    assert analyze_document("docs/index.html", text)["evidence"][0]["line"] == 3


def test_documented_shell_invocation_can_score():
    assert (
        analyze_document("README.md", "```bash\npython train.py --epochs 10\n```")[
            "scores"
        ]["experimentation"]
        == 1
    )


def test_api_fetches_only_docs_and_preserves_partial_status(monkeypatch):
    def request(url, token=None):
        if "/commits/" in url:
            return {"sha": "a" * 40}
        if "/git/trees/" in url:
            return {
                "tree": [
                    {"type": "blob", "path": "README.md", "size": 100},
                    {"type": "blob", "path": "src/model.py", "size": 50},
                    {"type": "blob", "path": "docs/large.md", "size": 999},
                ]
            }
        return {"default_branch": "main"}

    fetched = []

    def text(url, token=None):
        fetched.append(url)
        return "Download the dataset."

    monkeypatch.setattr(analyzer, "_request_json", request)
    monkeypatch.setattr(analyzer, "_request_text", text)
    result = analyzer.analyze_documentation_repository(
        "https://github.com/example/repo", max_content_bytes=200
    )
    assert len(fetched) == 1 and "README.md" in fetched[0] and "a" * 40 in fetched[0]
    assert (
        result["scores"]["collection"] == 1
        and result["scores"]["evaluation"] == "Unverified"
    )
    assert result["coverage"] == "partial"
    assert result["documents"][0]["evidence"][0]["url"].endswith("?plain=1#L1")


def test_score_table_has_exact_column_order():
    result = {
        "repository": {"url": "https://github.com/example/repo"},
        "scores": dict(zip(CRITERIA, [1, 0, 1, 0, 1, 0])),
    }
    assert (
        analyzer.markdown_table([result]).splitlines()[2]
        == "| [https://github.com/example/repo](https://github.com/example/repo) | 1 | 0 | 1 | 0 | 1 | 0 |"
    )


def test_wrapped_prose_and_bibtex_citations():
    result = analyze_document(
        "README.md",
        "Download the\ndataset from the archive.\n\n```bibtex\n@article{smith2020,\n title={A model},\n}\n```",
    )
    assert result["scores"]["collection"] == 1
    assert result["scores"]["dissemination"] == 1
    assert result["scores"]["method"] == 0
    collection = next(e for e in result["evidence"] if e["criterion"] == "collection")
    assert (collection["line"], collection["line_end"]) == (1, 2)


def test_unreadable_document_does_not_become_zero(monkeypatch):
    monkeypatch.setattr(
        analyzer,
        "_request_json",
        lambda url, token=None: (
            {"sha": "b" * 40}
            if "/commits/" in url
            else {"tree": [{"type": "blob", "path": "README.md", "size": 1}]}
            if "/git/trees/" in url
            else {"default_branch": "main"}
        ),
    )

    def fail(url, token=None):
        raise OSError("unavailable")

    monkeypatch.setattr(analyzer, "_request_text", fail)
    result = analyzer.analyze_documentation_repository(
        "https://github.com/example/repo"
    )
    assert set(result["scores"].values()) == {"Unverified"}
