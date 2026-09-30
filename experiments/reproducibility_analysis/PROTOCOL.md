# Reproducing published computational results with research software

Draft protocol for Jenifer and Esteban. Prepared 30 September 2026.
This document distinguishes verified input facts, literature-supported principles, and proposed design decisions. No reproduction experiments have been executed.

## 1. Research questions and scope

Suggested primary RQ: “To what extent can selected computational results reported in publications linked to publicly available research software be reproduced using the associated code and data under a predefined execution budget?”

Suggested intervention RQ: “Does providing file-level research-process-step and artefact-type metadata improve LLM-assisted reproduction success, compared with access to the same publication, repository, and documentation without those additional annotations?”

The first measures outcomes in a defined sampling frame. The second measures the effect of an information intervention on a specific agent. Do not infer that software is intrinsically unreproducible when one agent fails. Use “LLM-assisted reproduction under our protocol” unless a separate expert assessment supports a broader conclusion. Metadata availability is a diagnostic predictor, not evidence that results were reproduced. Adoption of original code/data is computational reproduction; rebuilding an implementation from the paper is a different experiment. Define terminology explicitly because historical conventions differ.

Unit of assessment: (repository snapshot, publication version, target computational result). Unit of sampling and statistical clustering may be a connected component of the repository–paper graph, because one repository can have multiple papers and one paper can have multiple repositories. Multiple results from a paper are correlated, not independent observations.

## 2. What the uploaded dataset establishes

The source has 386 repository rows, 386 distinct canonical owner/repository names, 1,732 related_to links, 1,581 distinct explicit DOIs, 133 links without an explicit DOI, 152 repositories with multiple paper links, and 20 URLs pointing below a repository root. See data/audit.json for independently computed counts and the source SHA-256.

It contains only repository OpenAIRE ID, GitHub URL, keywords, and linked publication ID/title/DOI/URL. It does not include the descriptions or screening evidence supporting the “experiment” designation, typed relation evidence, original commits, experiment inputs, or result targets. Retain the original description, screening rule, search query, graph release and selection date as sampling provenance. The normalized manifest recovers a DOI only where a missing DOI is directly present in a doi.org URL. It does not merge preprints with journal versions by title.

Do not treat all 1,732 links as author artefact links. Possible meanings include author implementation, experiment driver, cited dependency, reused dataset, or incidental relation. A high number of associated papers may reflect general-tool reuse and must be investigated, not automatically rejected. Current HEAD is a collection snapshot, not a verified historical paper version. The 20 nested URLs may encode essential branches or notebooks; preserve them before normalizing roots.

## 3. Required evidence and where to collect it

| Evidence group | Fields and artefacts | Purpose / source |
|---|---|---|
| Selection provenance | Original description, query/filter, date, graph release, inclusion decision and reason, reviewer | Defines sampling frame; original harvesting/screening records |
| Relation | Typed repo–paper relation, quotations with locations, authors' links, dependency role, confidence and reviewers | Validate executable artefact relevance; paper, README, CITATION.cff, archived releases, OpenAIRE relations |
| Publication identity | DOI, OpenAIRE ID, title, authors/ORCID, dates, venue, type, preprint/version links, corrections/retractions | Disambiguate results; OpenAIRE, DOI registration agency, publisher |
| Full text | PDF, supplement, machine-readable text, page boundaries, resolved URL, licence/access status, version and SHA-256 | Establish methods/results; publisher or legitimate open repository |
| Repository identity | Original and resolved URL, stable GitHub ID, collection time, default branch, archived/fork status, licence | Track moves and availability; GitHub |
| Frozen source | Paper-linked tag/release/commit, evidence for selection, source archive SHA-256, recursive manifest, submodules and Git LFS objects | Execute a definite version; Git, release archive, Software Heritage where available |
| Documentation | README, installation and usage guides, notebooks, scripts, CI workflow, CITATION.cff, codemeta.json | Identify entry points and environment; frozen repository, SoMEF |
| Environment | OS, language/runtime versions, dependency lockfiles, container recipe/digest, compilers, external tools, hardware/RAM/GPU/VRAM | Reconstruct execution environment; repository and paper |
| Inputs | Dataset identifiers and versions, accessible files and SHA-256, licences, restricted/private inputs, preprocessing, splits | Match experiment conditions; repository, paper, linked data archives |
| Parameters | Complete configs, random seeds, number of runs, checkpoints, training vs inference, stopping rules | Control stochastic and experimental variation |
| Result specification | Figure/table/cell, metric definition, aggregation, dataset/split, expected published value, units, rounding, tolerance and rationale | Preregister grading before execution; human-validated paper extraction |
| File semantics | Frozen relative path, blob SHA-256, one or more artefact types and process steps, evidence span, extractor/version/confidence | Intervention from your heuristic pipeline; SoMEF serves complementary documentation metadata |
| Execution record | Model/agent version, prompt hash, arm, replicate ID, runtime limits, commands, exit codes, stdout/stderr, patches, environment digest, tool/network interactions | Audit agent behaviour and cost; harness |
| Outputs and verdict | Newly generated outputs and hashes, numeric comparisons, pass/partial/fail/not-assessed per target, blockers, independent reviewer | Measured reproduction evidence, not agent self-report |

Preserve complete raw provider records with retrieval time, endpoint, response status and hashes. Maintain field-level source pointers when reconciling values. Keep absent, not queried, retrieval error, conflicting, inferred and manually verified values distinct. Counts of stars/citations and author attributes are optional descriptive covariates; they are not required for execution. Avoid collecting unrelated personal data.

OpenAIRE provides graph context and candidate links. Crossref/DataCite provide bibliographic records for their registered DOIs. OpenAlex may expose open locations. SoMEF extracts documentation and supported metadata files, not verified experiment results or a complete per-file process ontology. Do not call a SoMEF confidence score proof of correctness. Its failure to extract a field does not establish that the information is absent. Check installation/usage/data/environment fields against their original source.

## 4. Collection workflow

1. Normalize and deduplicate identities; preserve original URLs, provenance and every relation. Handle preprint/final versions explicitly. Do not merge papers by similar title alone.
2. Enrich repository and publication records, including software and publication OpenAIRE records. Retrieve relation type, direction and construction provenance if the available graph release/API exposes them; otherwise retain “unspecified” and assess manually.
3. Resolve legitimate full-text versions and supplements. Verify PDF title/DOI/version; a PDF header only verifies file format. Log paywall/not found/network failure separately. Retain metadata for unavailable papers rather than silently deleting them.
4. Validate eligibility before execution. Two reviewers independently assess a shared subset, record agreement and adjudicate disagreements. Freeze inclusion rules before the main sample. Determine whether the relation is an experiment-specific author artefact or a general dependency.
5. Identify paper-era version using explicit paper/README/release evidence. If no version is identifiable, record the ambiguity and run current snapshot only as a separately labelled analysis. “Latest commit before publication” is a heuristic, not proof of original version.
6. Collect a source archive plus LFS/submodules and linked data where permitted. Static tree/README collection alone is insufficient. Run metadata extractors on these frozen bytes; version every extractor and annotation policy. Join your existing per-file heuristic results by path AND blob/commit identity, never by repo name alone.
7. Build target specifications and a human-validated grader. Freeze them before agent attempts; separate gold annotations from automatically predicted annotations.
8. Pilot diverse cases, finalize budgets and exclusions, then execute an independently selected sample. Preserve non-completion reasons and selection flow counts.

Collector scope: collect.py normalizes the entire uploaded dataset and collects public GitHub metadata/current commit/file tree/README, OpenAIRE software and paper records, Crossref with DataCite fallback, and OpenAlex records. It discovers PDFs via PLOS, arXiv, OpenAlex open locations and Crossref PDF links. It records HTTP and network failures and successful responses, caches them, and caps response size at 50 MiB. It does not crawl all landing pages, fetch supplements, archive source/data, resolve historical versions, retrieve graph relation edges, run SoMEF, or validate relation/PDF identity. All these remain explicit next stages. Missing DOIs with no doi.org URL are not guessed; OpenAIRE records are still queried.

## 5. Study design

Two linked parts are preferable:

A. Descriptive audit across all 386 repositories: eligibility, relation validity, code/data/full-text access, environment documentation, explicit paper version, file semantics coverage. Report field coverage with denominators and provenance. These are reproducibility prerequisites, not result-reproduction outcomes.

B. Controlled execution experiment in a prespecified sample of eligible computational cases. Stratify sampling by domain, age, language, hardware demands and documentation quality where feasible. Start with 10–15 heterogeneous cases to estimate feasibility, then choose the main sample size from pilot variance, plausible effect size, power/cost constraints and clustering. Do not choose an arbitrary sample size and claim statistical adequacy. CPU-only cases are a defensible pilot stratum, but do not support conclusions about all GPU/hardware-intensive cases. Include inaccessible or infeasible cases in the audit; prespecify whether they enter the primary end-to-end success denominator or a separate execution-feasible denominator. Always report both selection and attrition.

Recommended primary paired comparison:
- Control: publication + identical frozen repository + original docs/data + neutral file index (path, size, hash).
- Treatment: exactly the same material + automatically predicted file-level process-step and artefact-type labels with source evidence.

Use fresh isolated sessions and environments for each arm/replicate. Fix model snapshot when available, agent harness, system prompt, tool access, tokens, timeout, hardware and network policy. Randomize case/arm execution order; do not transfer conversation state or plans. Equal token limits control budget but annotation reading consumes some of that budget, so measure this overhead.

Optional ablations if affordable: process labels only, artefact labels only, combined labels; bibliographic/SoMEF metadata as a separate factor; and adjudicated human labels as an upper-bound intervention. Adding all metadata only in treatment prevents attributing improvements to your file labels. If both arms get structured SoMEF results, the study estimates file-semantics effects conditional on that shared information. If SoMEF is treatment-only, name the intervention accordingly.

All labels must be generated before experimental outcomes and without access to evaluator-only outputs. Artifact-type labels can describe existing result files but must not include expected values or instructions to copy them. Gold labels are not the same as automatic labels. Stored outputs/checkpoints may be allowed as original artefacts for both arms, but specify whether the target is retraining, recomputing evaluation from a checkpoint, or regenerating a plot. These are different claims. Require provenance showing that assessed outputs were freshly generated rather than copied or renamed.

Keep the prompt fixed across arms, changing only the injected metadata block. A treatment with extra instructions, expert hints or entry-point commands tests a bundled assistance intervention. A same-size neutral-information control can probe annotation-volume effects but must be defined carefully rather than using arbitrary misleading labels.

Because the agent can infer file roles from code in the control arm, this tests the utility of explicitly supplied annotations, not the absolute absence of semantic information. Public repository/paper content may have been seen in model training; do not claim independence from training data. Freeze network access or log every allowed lookup and prohibit benchmark answer/solution retrieval equally in both arms.

## 6. Outcomes and grading

Use separate binary/continuous dimensions: inputs accessible, environment established, target workflow executed, valid new outputs produced, target results matched, and effort/cost. These are not necessarily a single ordinal scale; plotting an existing file may bypass training, for example. Avoid a “0–5 reproducibility score” unless its construct validity and aggregation are justified.

Primary outcome proposal: fraction of preselected target results reproduced within budget, summarized first within each case, then across cases. Also report case success (all required targets pass), partial success, blocks and budget exhaustion. Report original-as-documented execution separately from recovery after patches; log each dependency adjustment/source change and classify whether it could change the scientific method. Do not treat a modernized implementation as unchanged original-code execution.

For deterministic scalars, predeclare an absolute/relative tolerance and rounding policy; one possible comparator is |obtained − published| ≤ max(abs_tol, rel_tol × |published|). No universal tolerance is scientifically valid. For stochastic outputs, choose a scientifically justified equivalence margin and compare uncertainty across enough independent runs; matching a single seed or a nonsignificant difference does not establish equivalence. Use method-specific criteria for distributions, rankings, plots and scientific conclusions. An LLM assessment is supporting evidence; a frozen numeric comparator and blinded expert adjudication govern the final verdict. Validate automated graders against independently assessed examples.

Analysis: paired within-case differences in success/target coverage and cost, confidence intervals resampling independent repo–paper components (or case units only when independent), and descriptive blocker distributions. McNemar’s test is suitable for one paired binary outcome per independent unit, not pooled correlated results or repeated agent runs. Repeated runs need a prespecified aggregation or clustered/hierarchical model. Define treatment effect estimand and primary outcome before collection; adjust/label multiple ablations and subgroup tests as exploratory. Metadata–success correlations alone are observational, whereas controlled paired comparisons support a causal interpretation of the supplied annotation intervention under the harness assumptions.

## 7. Practical starting plan

Use the collection pilot only to verify retrieval, not to estimate reproducibility. Review the spectrum-sensing case first as a candidate: it has an associated PLOS paper and an accessible PDF, but verify relation, targets and hardware requirements before declaring it suitable. Select a heterogeneous feasibility pilot after eligibility review. Build a task packet with frozen code, verified paper/supplements, data/environment manifest, human-approved result targets and your labels. Execute paired runs and inspect evidence. Use those results to set budgets and the main sampling/power plan.

The conversational interface is useful for designing and reviewing pilot tasks. For the paper's repeated experiment, prefer a logged programmatic harness with a fixed model identifier and isolated execution over manually reusing this conversation. Do not delegate final scientific grading to the same agent that attempted reproduction.

## 8. Sources and novelty

- CORE-Bench: Siegel et al., “CORE-Bench: Fostering the Credibility of Published Research Through a Computational Reproducibility Agent Benchmark,” https://arxiv.org/abs/2409.11363 (version used must be recorded). Existing code/data-based agent reproducibility evaluation; inspect its protocol, selection and grader when positioning this study.
- PaperBench: Starace et al., “PaperBench: Evaluating AI’s Ability to Replicate AI Research,” https://openreview.net/pdf?id=xF5PuTLPbn. Paper-to-implementation research replication is adjacent but differs from reusing original repositories.
- OpenAIRE single-entity API: https://graph.openaire.eu/docs/apis/graph-api/getting-a-single-entity/ and https://graph.openaire.eu/docs/apis/graph-api/making-requests/. The collector uses the tested v2 endpoint, not unverified beta parameters.
- Crossref REST API: https://www.crossref.org/documentation/retrieve-metadata/rest-api/.
- SoMEF usage: https://somef.readthedocs.io/en/latest/usage/ and https://github.com/KnowledgeCaptureAndDiscovery/somef/blob/master/README.md.

This targeted search establishes prior related work, not exhaustive novelty. A systematic search is still needed before claiming that file-level semantic metadata has not been evaluated for this task. Any eventual reproducibility rate applies to the study's sampling frame, artefacts, publication versions, chosen targets and execution budget.
