# GitHub Pages demo

This folder is a static, read-only presentation of the current research-process-step work.

It intentionally does not depend on the FastAPI backend. The page reads the publication dataset,
analytics snapshot, selected PDFs, and shareable reproducibility conversations directly from the
public `demo` branch on GitHub.

## Deploy

Use `demo/index.html` as the site entry point in your GitHub Pages deployment workflow.

If you deploy the repository root instead, the demo is available under `/demo/`.

The demo does not expose write operations, repository reruns, PDF uploads, or conversation editing.
