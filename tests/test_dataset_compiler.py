from scripts.compile_openaire_github_dataset import normalize_github_repo_url


def test_normalize_http_repository():
    assert (
        normalize_github_repo_url("https://github.com/openai/openai")
        == "https://github.com/openai/openai"
    )


def test_normalize_git_suffix_and_deep_link():
    assert (
        normalize_github_repo_url(
            "https://github.com/owner/repo.git/tree/main/src"
        )
        == "https://github.com/owner/repo"
    )


def test_normalize_ssh_repository():
    assert (
        normalize_github_repo_url("git@github.com:owner/repo.git")
        == "https://github.com/owner/repo"
    )


def test_reject_non_github():
    assert normalize_github_repo_url("https://gitlab.com/owner/repo") is None


def test_reject_github_non_repository_page():
    assert normalize_github_repo_url("https://github.com/topics/python") is None
