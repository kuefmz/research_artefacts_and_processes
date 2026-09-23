"""Generate precomputed demo results for SoMEF and WIDOCO."""

from __future__ import annotations

import json
import os
from pathlib import Path

from research_process_steps.analyzer import analyze_github_repository

TARGETS = {
    "somef": "https://github.com/KnowledgeCaptureAndDiscovery/somef",
    "widoco": "https://github.com/dgarijo/Widoco",
}


def main() -> None:
    output_dir = Path("src/research_process_steps/demo_cache")
    output_dir.mkdir(parents=True, exist_ok=True)
    token = os.getenv("GITHUB_TOKEN")

    for name, repo_url in TARGETS.items():
        print(f"Analyzing {name}: {repo_url}", flush=True)
        result = analyze_github_repository(repo_url, token=token)
        result["cache"] = {
            "hit": True,
            "persistent": True,
            "precomputed": True,
            "path": f"bundled:{name}.json",
        }
        output_path = output_dir / f"{name}.json"
        output_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(
            f"Wrote {output_path} ({result['repository']['file_count']} files)",
            flush=True,
        )


if __name__ == "__main__":
    main()
