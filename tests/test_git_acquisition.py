import subprocess
from pathlib import Path

from research_process_steps import analyzer
from research_process_steps import git_acquisition


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_local_git_blob_produces_same_heuristic_result(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")

    source = repo / "src" / "preprocess_data.py"
    source.parent.mkdir()
    content = (
        "import pandas as pd\n"
        "def preprocess(df):\n"
        "    return df.dropna()\n"
    )
    source.write_text(content, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")

    tree_raw = subprocess.run(
        ["git", "ls-tree", "-r", "-t", "-l", "-z", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
    ).stdout
    items = git_acquisition._parse_ls_tree(tree_raw)
    blob = next(item for item in items if item.get("path") == "src/preprocess_data.py")

    raw = git_acquisition._read_blob(repo, blob["sha"], None)
    from_git = analyzer.analyze_file(blob["path"], raw.decode("utf-8", errors="replace"))
    direct = analyzer.analyze_file("src/preprocess_data.py", content)

    assert raw.decode("utf-8", errors="replace") == content
    assert from_git == direct


def test_git_tree_metadata_matches_git_objects(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")

    p = repo / "README.md"
    p.write_text("# Demo\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")

    expected_tree = _git(repo, "rev-parse", "HEAD^{tree}")
    tree_raw = subprocess.run(
        ["git", "ls-tree", "-r", "-t", "-l", "-z", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
    ).stdout
    items = git_acquisition._parse_ls_tree(tree_raw)
    readme = next(item for item in items if item.get("path") == "README.md")

    assert expected_tree
    assert readme["type"] == "blob"
    assert readme["size"] == len(b"# Demo\n")
    assert git_acquisition._read_blob(repo, readme["sha"], None) == b"# Demo\n"
