# Research Artefacts Benchmark

This branch contains only the benchmark dataset used for the manual evaluation of research-software repositories.

## Dataset

`software_with_publications_benchmark_100.json` contains 100 selected GitHub repositories and their associated research publications.

The repositories were selected from the larger OpenAIRE-derived repository/publication dataset for use in the reproducibility study. Selection favored repositories that:

- have substantive documentation;
- provide identifiable usage, experiment, or analysis instructions;
- have a reasonably clear relationship to a research publication;
- contain research code or analysis artifacts rather than only a citation or empty repository; and
- appear suitable for reproduction on a normal laptop without mandatory HPC or specialized experimental hardware.

Each repository record preserves the original OpenAIRE identifiers, GitHub URL, related publication metadata, and the short `selection_reasoning` used during benchmark screening.

## Manual evaluation

The JSON also contains an `evaluation_schema` and empty `evaluation_results` fields for two independent evaluators:

- `kuefmz`
- `esteban`

The allowed status values are:

- `yes`
- `partial`
- `no`
- `not_applicable`

Each judgment can include exact evidence and notes.

The criteria cover:

1. Generic repository documentation
   - README availability
   - usage instructions
2. Documentation evidence for
   - collection
   - processing
   - implementation
   - experimentation
   - evaluation
   - dissemination
3. Code evidence for the same six research-process steps

The evaluator fields are intentionally empty so that both reviewers can annotate the benchmark independently.

## Purpose

The benchmark is intended for comparing:

1. manual evidence identification;
2. deterministic heuristic evidence identification;
3. LLM-based evidence identification; and, in a later phase,
4. manual versus LLM-assisted reproduction of selected experiments.

The benchmark selection itself should remain fixed while evaluator judgments are added independently.
