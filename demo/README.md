# GitHub Pages demo

This folder mirrors the current Research Process Steps Explorer UI as a **read-only static demo**.

It uses the data committed on the `demo` branch:
- publication dataset and first-ten-paper selection,
- committed heuristic results,
- committed paper PDFs,
- C0/C1 reproducibility conversation records,
- C0/C1 prompt templates.

The browser-side `static-api.js` emulates the GET endpoints used by the normal FastAPI UI. Write operations, uploads, heuristic runs, random batches, and conversation editing are disabled.

## GitHub Pages

Publish the `demo` branch and open the site under `/demo/`, or use a Pages workflow that publishes the contents of this folder directly.
