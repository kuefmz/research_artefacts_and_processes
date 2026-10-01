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

## Evaluation criteria

### Generic

- **Has a README file?**
- **Has usage instructions?**

The benchmark is evaluated using two complementary approaches: **documentation** and **code**.

### Documentation

#### Collection

**Question:** Does documentation explain how the research inputs/data were obtained?  
**Evidence:** data sources, download instructions, API description

#### Processing

**Question:** Does it describe how inputs must be prepared/transformed?  
**Evidence:** preprocessing steps, formats, cleaning procedure

#### Method

**Question:** Does it describe the method/model/algorithm implemented by the repository?  
**Evidence:** model description, algorithm, parameters

#### Experimentation

**Question:** Does it explain how to execute the experiment/analysis?  
**Evidence:** commands, experiment sequence, configurations

#### Evaluation

**Question:** Does it explain how results are evaluated/validated?  
**Evidence:** metrics, evaluation commands, baselines

#### Dissemination

**Question:** Does it explain or identify the resulting research outputs/publication?  
**Evidence:** paper citation, figures, tables, result descriptions

### Code

#### Collection

**Question:** Does the code obtain or generate research input data/resources?  
**Evidence:** API calls, downloads, database queries, crawlers, synthetic data generation

#### Processing

**Question:** Does the code transform input data into data used by the method/experiment?  
**Evidence:** cleaning, normalization, filtering, tokenization

#### Method

**Question:** Does the code implement the research method/model/algorithm?  
**Evidence:** models, algorithms, architectures

#### Experimentation

**Question:** Does the code execute experiments or analyses using the method?  
**Evidence:** training, inference, experiment runners, analysis scripts

#### Evaluation

**Question:** Does the code measure or validate experimental outputs?  
**Evidence:** metrics, comparisons, statistical tests, validation, error analysis

#### Dissemination

**Question:** Does the code generate artifacts specifically intended to communicate research results?  
**Evidence:** publications, repositories

