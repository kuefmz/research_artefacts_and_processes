import hashlib
import io
import tarfile
from pathlib import Path

from research_process_steps import analyzer


def _tree_sha(entries):
    body = bytearray()
    for sort_key, mode, name, sha in sorted(entries, key=lambda x: x[0]):
        body.extend(f"{mode} {name}\0".encode("utf-8"))
        body.extend(bytes.fromhex(sha))
    digest = hashlib.sha1()
    digest.update(f"tree {len(body)}\0".encode("ascii"))
    digest.update(body)
    return digest.hexdigest()


def test_archive_tree_snapshot_is_git_sha_equivalent(monkeypatch, tmp_path: Path):
    files = {
        "src/main.py": b'import pandas\n\nif __name__ == "__main__":\n    print("ok")\n',
        "README.md": b"# Demo\n",
        "data.bin": b"\x00\x01\x02",
    }

    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as tar:
        for path, data in files.items():
            info = tarfile.TarInfo(f"demo-main/{path}")
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))

    main_sha = analyzer._git_blob_sha(files["src/main.py"])
    readme_sha = analyzer._git_blob_sha(files["README.md"])
    data_sha = analyzer._git_blob_sha(files["data.bin"])

    src_tree_sha = _tree_sha([
        (b"main.py", "100644", "main.py", main_sha),
    ])
    root_sha = _tree_sha([
        (b"README.md", "100644", "README.md", readme_sha),
        (b"data.bin", "100644", "data.bin", data_sha),
        (b"src/", "40000", "src", src_tree_sha),
    ])

    monkeypatch.setattr(
        analyzer,
        "_request_bytes",
        lambda *args, **kwargs: archive.getvalue(),
    )

    tree, content = analyzer._archive_tree_snapshot(
        owner="example",
        repo="demo",
        ref="main",
        expected_root_tree_sha=root_sha,
        snapshot_cache=tmp_path / "cache",
        max_content_bytes=250_000,
        token="token",
        deadline=None,
    )

    assert tree["sha"] == root_sha
    assert tree["archive_reconstructed"] is True

    blobs = {
        item["path"]: item
        for item in tree["tree"]
        if item["type"] == "blob"
    }
    assert set(blobs) == set(files)
    assert blobs["src/main.py"]["sha"] == main_sha
    assert blobs["README.md"]["sha"] == readme_sha
    assert blobs["data.bin"]["sha"] == data_sha

    assert content["src/main.py"][0] == files["src/main.py"].decode("utf-8")
    assert content["README.md"][0] == files["README.md"].decode("utf-8")
    assert "data.bin" not in content


def test_archive_snapshot_rejected_if_tree_sha_differs(monkeypatch, tmp_path: Path):
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as tar:
        data = b"print('different')\n"
        info = tarfile.TarInfo("demo-main/main.py")
        info.size = len(data)
        info.mode = 0o644
        tar.addfile(info, io.BytesIO(data))

    monkeypatch.setattr(
        analyzer,
        "_request_bytes",
        lambda *args, **kwargs: archive.getvalue(),
    )

    try:
        analyzer._archive_tree_snapshot(
            owner="example",
            repo="demo",
            ref="main",
            expected_root_tree_sha="0" * 40,
            snapshot_cache=tmp_path / "cache",
            max_content_bytes=250_000,
            token="token",
            deadline=None,
        )
    except RuntimeError as exc:
        assert "did not reconstruct the exact Git tree" in str(exc)
    else:
        raise AssertionError("mismatched archive must not be accepted")


def test_archive_content_produces_identical_heuristic_result(monkeypatch, tmp_path: Path):
    path = "src/preprocess_data.py"
    raw_content = (
        b"import pandas as pd\n"
        b"def preprocess(df):\n"
        b"    return df.dropna()\n"
    )

    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as tar:
        info = tarfile.TarInfo(f"demo-main/{path}")
        info.size = len(raw_content)
        info.mode = 0o644
        tar.addfile(info, io.BytesIO(raw_content))

    blob_sha = analyzer._git_blob_sha(raw_content)
    src_tree_sha = _tree_sha([
        (b"preprocess_data.py", "100644", "preprocess_data.py", blob_sha),
    ])
    root_sha = _tree_sha([
        (b"src/", "40000", "src", src_tree_sha),
    ])

    monkeypatch.setattr(
        analyzer,
        "_request_bytes",
        lambda *args, **kwargs: archive.getvalue(),
    )

    _, content = analyzer._archive_tree_snapshot(
        owner="example",
        repo="demo",
        ref="main",
        expected_root_tree_sha=root_sha,
        snapshot_cache=tmp_path / "cache",
        max_content_bytes=250_000,
        token="token",
        deadline=None,
    )

    old_path_result = analyzer.analyze_file(path, raw_content.decode("utf-8"))
    optimized_path_result = analyzer.analyze_file(path, content[path][0])

    assert optimized_path_result == old_path_result
