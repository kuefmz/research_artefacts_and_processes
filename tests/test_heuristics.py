from research_process_steps.analyzer import analyze_file


def steps(path: str, content: str = "") -> set[str]:
    return set(analyze_file(path, content)["steps"])


def test_collection_file():
    assert "collection" in steps("scripts/download_dataset.py")


def test_processing_file():
    assert "processing" in steps("preprocessing/clean_records.py")


def test_source_code_is_implementation():
    assert "implementation" in steps("src/somef/cli.py")


def test_tests_are_implementation_not_evaluation():
    result = steps("tests/test_parser.py", "def test_parser(): pass")
    assert "implementation" in result
    assert "evaluation" not in result


def test_experiment_directory():
    assert "experimentation" in steps("experiments/create_models.py")


def test_scientific_evaluation():
    assert "evaluation" in steps("evaluation/benchmark.py", "f1_score = 0.91")


def test_documentation():
    assert "dissemination" in steps("docs/index.md")


def test_citation_file_is_excluded_structured_metadata():
    assert steps("CITATION.cff") == set()


def test_generic_file_can_remain_unclassified():
    assert steps("assets/logo.png") == set()


def test_file_can_have_multiple_steps():
    result = steps(
        "experiments/evaluate_model.py",
        "random_seed = 42\nprint('f1_score')",
    )
    assert "experimentation" in result
    assert "evaluation" in result


def test_preserves_multiple_unique_content_matches():
    result = analyze_file(
        "analysis.py",
        "precision = 0.8\nrecall = 0.7\nprecision = 0.8\nf1_score = 0.75",
    )
    metric_evidence = next(
        evidence
        for evidence in result["evidence"]
        if evidence["rule_id"] == "EVA_CONTENT_METRIC"
    )
    assert metric_evidence["matched_texts"] == [
        "precision",
        "recall",
        "f1_score",
    ]
    assert metric_evidence["matches"] == [
        {"text": "precision", "line": 1},
        {"text": "recall", "line": 2},
        {"text": "f1_score", "line": 4},
    ]


def test_ttl_test_fixture_is_globally_excluded():
    result = analyze_file("test/business.ttl")
    assert result["artifact_kind"] == "data"
    assert result["steps"] == []
    assert result["suppressed_evidence"][0]["rule_id"] == (
        "GLOBAL_STRUCTURED_DATA_EXCLUSION"
    )


def test_data_file_under_src_is_globally_excluded():
    result = analyze_file("src/resources/example.csv")
    assert result["artifact_kind"] == "data"
    assert result["steps"] == []
    assert result["suppressed_evidence"][0]["rule_id"] == (
        "GLOBAL_STRUCTURED_DATA_EXCLUSION"
    )


def test_source_code_under_tests_remains_implementation():
    result = analyze_file("tests/test_parser.py")
    assert result["artifact_kind"] == "source_code"
    assert "implementation" in result["steps"]


def test_markdown_under_src_is_documentation_not_implementation():
    result = analyze_file("src/README.md")
    assert result["artifact_kind"] == "documentation"
    assert "implementation" not in result["steps"]


def test_structured_data_and_config_files_are_never_classified():
    cases = {
        "experiments/sweep.yml": "random_seed: 42",
        "experiments/run.json": '{"accuracy": 0.99}',
        "evaluation/metrics.csv": "precision,recall,f1_score",
        "processing/records.ttl": "@prefix ex: <https://example.org/> .",
        "collection/source.xml": "<download_dataset>true</download_dataset>",
        "docs/codemeta.json": '{"citation": "doi:10.1234/example"}',
        "src/settings.toml": 'mode = "experiment"',
        "tests/fixture.rdf": "<rdf:RDF></rdf:RDF>",
    }

    for path, content in cases.items():
        result = analyze_file(path, content)
        assert result["steps"] == []
        assert result["unclassified"] is True
        assert result["scores"] == {}
        assert result["evidence"] == []
        assert result["suppressed_evidence"][0]["rule_id"] == (
            "GLOBAL_STRUCTURED_DATA_EXCLUSION"
        )


def test_json_is_recognized_as_data():
    result = analyze_file("evaluation/results.json", '{"f1_score": 0.95}')
    assert result["artifact_kind"] == "data"
    assert result["steps"] == []
