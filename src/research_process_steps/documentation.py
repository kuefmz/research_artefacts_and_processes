"""Conservative, deterministic documentation-only lifecycle heuristics.

These rules approximate a manual documentation review; they do not establish
semantic completeness. File names select eligible inputs but never assign scores.
"""

from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
from html.parser import HTMLParser

CRITERIA = (
    "collection",
    "processing",
    "method",
    "experimentation",
    "evaluation",
    "dissemination",
)
VERSION = "1.0.0"


def is_documentation(path: str) -> bool:
    p = PurePosixPath(path.lower())
    if any(
        part
        in {
            ".git",
            "node_modules",
            ".venv",
            "venv",
            "__pycache__",
            ".ipynb_checkpoints",
        }
        for part in p.parts
    ):
        return False
    if p.name.startswith(("license", "copying", "changelog", "news")):
        return False
    return (
        p.suffix
        in {".md", ".markdown", ".rst", ".adoc", ".rd", ".rmd", ".qmd", ".ipynb"}
        or bool(re.fullmatch(r"readme(?:\.[\w]+)?", p.name))
        or (
            p.suffix in {".html", ".htm", ".txt"}
            and any(
                x
                in {
                    "doc",
                    "docs",
                    "documentation",
                    "man",
                    "manual",
                    "tutorials",
                    "guides",
                    "html",
                    "vignettes",
                }
                for x in p.parts[:-1]
            )
        )
    )


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "pre", "code"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "pre", "code"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append((self.getpos()[0], data))


def documentation_lines(path: str, text: str) -> list[tuple[int, str]]:
    """Extract prose with original source lines; never classify notebook code."""
    if not is_documentation(path):
        return []
    suffix = PurePosixPath(path.lower()).suffix
    if suffix == ".ipynb":
        notebook = json.loads(text)
        # Locate each JSON source array sequentially, preserving physical lines.
        source_arrays = list(
            re.finditer(
                r'"source"\s*:\s*(\[(?:[^\]"\\]|\\.|"(?:[^"\\]|\\.)*")*\]|"(?:[^"\\]|\\.)*")',
                text,
                re.S,
            )
        )
        if len(source_arrays) != len(notebook.get("cells", [])):
            raise ValueError("Cannot map notebook cells to source lines safely")
        out = []
        for cell, match in zip(notebook["cells"], source_arrays):
            if cell.get("cell_type") != "markdown":
                continue
            source = cell.get("source", [])
            prose = source if isinstance(source, str) else "".join(source)
            extracted = documentation_lines("cell.md", prose)
            strings = list(re.finditer(r'"(?:[^"\\]|\\.)*"', match.group(1)))
            mapped = []
            for string in strings:
                value = json.loads(string.group())
                original = text.count("\n", 0, match.start(1) + string.start()) + 1
                mapped.extend([original] * max(1, len(value.splitlines())))
            for line, value in extracted:
                if line <= len(mapped):
                    out.append((mapped[line - 1], value))
        return out
    if suffix in {".html", ".htm"}:
        parser = _HTMLText()
        parser.feed(text)
        grouped = {}
        for start, fragment in parser.parts:
            for offset, value in enumerate(fragment.splitlines()):
                if value.strip():
                    grouped.setdefault(start + offset, []).append(value.strip())
        return [(line, " ".join(values)) for line, values in sorted(grouped.items())]
    out = []
    fence = None
    fence_kind = ""
    rst_code = False
    rd_code = False
    balance = 0
    comment = False
    frontmatter = text.splitlines()[:1] == ["---"]
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if frontmatter:
            if number > 1 and stripped in {"---", "..."}:
                frontmatter = False
            continue
        if "<!--" in line:
            comment = True
        if comment:
            if "-->" in line:
                comment = False
            continue
        marker = re.match(r"^\s*(`{3,}|~{3,})(.*)$", line)
        if marker:
            if fence is None:
                fence = marker.group(1)[0]
                fence_kind = marker.group(2).strip().lower()
            elif marker.group(1)[0] == fence:
                fence = None
            continue
        if fence:
            if fence_kind in {"bibtex", "bib"} and re.match(
                r"\s*@(?:article|inproceedings|book|misc|phdthesis|techreport)\s*\{",
                line,
                re.I,
            ):
                out.append((number, "Publication citation: " + stripped))
            # Only explicit invocation syntax is retained; never program logic.
            if re.match(
                r"^\s*(?:\$\s*)?(?:python(?:3)?|Rscript|julia|matlab|bash|sh|\.\/\S+|make)\s+[\w./-]",
                line,
            ):
                out.append((number, "Documented command: " + stripped))
            continue
        if re.match(r"^\s*\.\.\s+(?:code|code-block|literalinclude|include)::", line):
            rst_code = True
            continue
        if rst_code:
            if not stripped or line.startswith((" ", "\t")):
                continue
            rst_code = False
        if suffix == ".rd":
            if re.match(r"^\s*\\(?:examples|usage)\{", line):
                rd_code = True
                balance = line.count("{") - line.count("}")
                continue
            if rd_code:
                balance += line.count("{") - line.count("}")
                if balance <= 0:
                    rd_code = False
                continue
            if stripped.startswith("%"):
                continue
        if line.startswith(("    ", "\t")):
            if re.match(
                r"^\s*(?:\$\s*)?(?:python(?:3)?|Rscript|julia|matlab|bash|sh|\.\/\S+)\s+[\w./-]",
                line,
            ):
                out.append((number, "Documented command: " + stripped))
            continue
        if stripped:
            out.append((number, stripped))
    return out


# Each rule requires an action/relationship, not an isolated lifecycle keyword.
RULES = {
    "collection": (
        r"\b(?:data(?:set)?s?|corpus|observations|samples)\b.{0,100}\b(?:obtained|collected|acquired|downloaded|retrieved|mined|recorded|sourced)\b",
        r"\b(?:download|fetch|retrieve|collect|generate|simulate)\b.{0,80}\b(?:data(?:set)?s?|corpus|samples|observations|responses)\b",
        r"\b(?:data source|dataset source|corpus source)\b.{0,120}(?:https?://|\bfrom\b)",
    ),
    "processing": (
        r"\b(?:preprocess(?:ing)?|clean(?:ing)?|normaliz(?:e|ation)|standardiz(?:e|ation)|tokeniz(?:e|ation)|filter(?:ing)?|convert(?:ing)?|transform(?:ation)?)\b.{0,90}\b(?:data|inputs?|corpus|images?|reads|features?|files?|values|samples)\b",
        r"\b(?:data|inputs?|corpus|images?|reads|features?|files?|values|samples)\b.{0,90}\b(?:preprocessed|cleaned|normalized|standardized|tokenized|filtered|converted|transformed)\b",
        r"\b(?:input|data|dataset|file|matrix|table)\b.{0,70}\b(?:format|columns?|dimensions?|must contain|should contain|required fields)\b",
    ),
    "method": (
        r"\b(?:model|algorithm|method|approach|estimator|network)\b.{0,100}\b(?:uses?|combines?|computes?|estimates?|minimizes?|maximizes?|optimizes?|samples?|consists|based on|learns?|maps?)\b.{5,150}",
        r"\b(?:parameter|hyperparameter|prior|kernel|learning rate|regularization)\b.{0,100}\b(?:controls?|determines?|sets?|variance|distribution|default|shape|scale|strength|probability)\b",
    ),
    "experimentation": (
        r"\b(?:run|execute|launch|reproduce)\b.{0,100}\b(?:experiment|analysis|simulation|training|notebook|pipeline)\b",
        r"\b(?:experiment|analysis|simulation|training)\b.{0,80}\b(?:command|configuration|invoke|run|execute)\b",
        r"Documented command:.{0,140}\b(?:train|experiment|simulate|simulation|analy[sz]e|analysis|reproduce|run)[\w.-]*",
    ),
    "evaluation": (
        r"\b(?:accuracy|precision|recall|f1|auc|rmse|mse|mae|perplexity)\b.{0,80}\b(?:metric|measure|computed|reported|evaluat(?:e|ion)|validat(?:e|ion))\b",
        r"\b(?:evaluate|evaluated|evaluation|validate|validated|validation|measure|report|compute)\b.{0,110}\b(?:accuracy|precision|recall|f1|auc|rmse|mse|mae|perplexity|error rate|performance|p-values?|confidence intervals?|credible intervals?)\b",
        r"\b(?:compare|compared|comparison|benchmark|benchmarked)\b.{0,110}\b(?:baseline|ground truth|experimental measurements|theoretical|competing|methods|models)\b",
        r"\b(?:cross-validation|cross validation|bootstrap|t-test|anova|credible interval|confidence interval|parameter recovery)\b.{0,100}\b(?:results?|estimates?|uncertainty|folds?|parameters?|significance|validation|test)\b",
        r"\b(?:run|execute|invoke)\b.{0,80}\b(?:evaluation|validation)\b",
        r"Documented command:.{0,140}\b(?:evaluate|evaluation|validate|benchmark)[\w.-]*",
    ),
    "dissemination": (
        r"\b(?:paper|publication|article|manuscript|preprint|thesis)\b.{0,150}(?:https?://|doi\b|\b(?:published|accepted|submitted|entitled|titled|by)\b)",
        r"\b(?:cite|citation|bibtex)\b.{0,150}(?:https?://|doi\b|@(?:article|inproceedings|book|misc|phdthesis|techreport)|\b(?:paper|publication|software)\b)",
        r"\b(?:results?|outputs?)\b.{0,100}\b(?:figures?|tables?|plots?|reports?|published|presented|saved|exported)\b",
        r"\b(?:reproduce|generate|plot)\b.{0,60}\b(?:figure|table)\s*\d",
    ),
}
COMPILED = {
    key: [re.compile(p, re.I) for p in patterns] for key, patterns in RULES.items()
}
NEGATIVE = re.compile(
    r"\b(?:not (?:yet )?(?:available|implemented|documented|provided)|no (?:data|evaluation|validation|experiments?|results?)|todo|coming soon|will be added|does not|do not)\b",
    re.I,
)
SOFTWARE_TEST = re.compile(
    r"\b(?:unit tests?|integration tests?|software tests?|pytest|lint(?:ing)?)\b", re.I
)


def analyze_document(path: str, text: str) -> dict:
    lines = documentation_lines(path, text)
    evidence = []
    seen = set()
    for position, (line, value) in enumerate(lines):
        windows = [(line, value)]
        combined = value
        for offset in (1, 2):
            if re.search(r"[.!?]\s*$", combined):
                break
            if position + offset >= len(lines):
                break
            next_line, next_value = lines[position + offset]
            previous = lines[position + offset - 1][0]
            if (
                next_line != previous + 1
                or next_value.startswith(("#", "Documented command:"))
                or value.startswith("#")
            ):
                break
            combined += " " + next_value
            windows.append((next_line, combined))
        # Scope negation to sentences, preventing unrelated negative clauses
        # from silencing evidence elsewhere on a long HTML line.
        for end_line, window in windows:
            for sentence in re.split(r"(?<=[.!?])\s+", window):
                if NEGATIVE.search(sentence):
                    continue
                for criterion, patterns in COMPILED.items():
                    if (criterion, line) in seen:
                        continue
                    if criterion == "evaluation" and SOFTWARE_TEST.search(sentence):
                        continue
                    for index, pattern in enumerate(patterns, 1):
                        match = pattern.search(sentence)
                        if match and (end_line == line or match.start() < len(value)):
                            evidence.append(
                                {
                                    "criterion": criterion,
                                    "rule_id": f"DOC_{criterion.upper()}_{index}",
                                    "path": path,
                                    "line": line,
                                    "line_end": end_line,
                                    "matched_text": match.group(0),
                                }
                            )
                            seen.add((criterion, line))
                            break
    return {
        "path": path,
        "eligible": is_documentation(path),
        "evidence": evidence,
        "scores": {
            c: int(any(e["criterion"] == c for e in evidence)) for c in CRITERIA
        },
    }
