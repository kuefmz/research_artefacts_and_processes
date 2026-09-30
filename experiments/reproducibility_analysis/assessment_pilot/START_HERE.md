# Five-case static reproducibility assessment pilot

This pilot assesses documented computational prerequisites and the quality of an LLM's source-based judgments. No installation, training, simulation or reproduction is attempted. It cannot establish a measured reproducibility rate or validate predicted success probabilities. Human source-based review provides a reference for assessment quality, not ground truth about execution success.

## Cases and scope

P01: QTB-HHU/integraseModel with “The mechanism of ϕC31 integrase directionality: experimental analysis and computational modelling” (10.1093/nar/gkw616). The original README explicitly maps this paper to fullModel. Assess the computational modelling separately from wet-lab measurements.

P02: avian2/spectrum-sensing-methods with “A methodology for experimental evaluation of signal detection methods in spectrum sensing” (10.1371/journal.pone.0199550). The paper explicitly links the repository. Distinguish reanalysis/simulation from physical data acquisition. Large repository: log partial inspection rather than claiming exhaustive coverage.

P03: abezuglov/ANN with “Multi-Output Artificial Neural Network for Storm Surge Prediction in North Carolina” (10.48550/arxiv.1609.07378). The paper includes the repository in its references. Root README retrieval returned 404 during collection, but that does not imply no instructions elsewhere. Paper-specific completeness remains to be assessed.

P04: mspeich/forhytm with “Testing an optimality-based model of rooting zone water storage capacity in temperate forests” (10.5194/hess-22-4097-2018). The paper identifies the model repository. The included example data and the paper's study data require careful distinction.

P05: BioMachinesLab/jbotevolver with “Evolution of Collective Behaviors for a Real Swarm of Aquatic Surface Robots” (10.1371/journal.pone.0151834). The README lists this study, but a shared simulator is not necessarily the complete experiment package. Paper-specific controllers/configurations and physical validation require separate assessment.

These five are purposively selected exploratory candidates from the uploaded dataset. They span model-specific and platform-level associations. They are not random, representative or all confirmed to be complete experiment artefacts. Humans must approve relation relevance and paper identity before treating them as eligible main-study cases. Do not exclude a valid case merely because the LLM predicts it is difficult.

All repository links in cases.json and the five prompts are pinned to collected commits. Those commits have not been established as original paper-era versions. Supplied PDFs are the exact downloaded bytes with SHA-256 recorded; human publication/version checks remain pending. P01 uses an institutional-repository PDF. P02's largest PDF can be restored using the parent folder's restore_large_files.py. P03's PDF is already in the parent data/papers folder. P04/P05 PDFs are included here.

## Run one baseline case

1. Use a new, ordinary conversation for each case/replicate. Do not use this planning conversation or feed the agent these selection notes, provider records or prior responses. Use the same model and tool settings across the pilot. Turn off personalization/memory and custom instructions where possible; record the actual setting and any uncertainty. Do not assume a fresh chat guarantees a completely independent experimental environment.
2. Attach only the selected PDF and original source material, or provide the pinned repository link. Original README/config/docs and paper supplements are allowed baseline material. Do not upload the overall starter ZIP: it contains external metadata and planning notes. Administrative IDs/hashes identify the inputs; they are not semantic enrichment.
3. Paste the complete corresponding prompts/P01_baseline.txt (or another case) as the first user message. Save the exact submitted text if anything differs. First verify that the model has access to read the sources; a link alone may not give access. Any attachment-size or retrieval restrictions must be recorded.
4. Keep the raw first assessment unchanged. If you must supply inaccessible source files, save every follow-up and record the added inputs/hashes. Substantive hints/corrections create a revised or assisted assessment and should not replace the primary response. This is an exploratory inspection pilot with recorded coverage, not a controlled fixed retrieval-budget experiment.
5. Save the complete visible conversation as UTF-8 Markdown/text: every user and assistant turn, attachment filenames, tool actions/results visible in the interface, failures and follow-ups. Do not request or fabricate hidden chain-of-thought. Record which internal/tool details the interface does not expose. Retain a platform export when available.
6. Create a shared conversation link using Share, review the full preview, and store it in the CSV. Check that a collaborator can open it and that it includes the intended whole conversation, not only one response. Record verification time and access status. Personal-account shared links are snapshots when created/updated; later messages do not appear automatically. Workspace links can have restricted access. Do not treat a share link as a permanent archival copy. Reference: https://help.openai.com/en/articles/7925741-chatgpt-shared-links-faq (checked 30 September 2026).
7. Archive using the helper below, or fill the CSV manually with a CSV-aware editor. Keep the raw transcript file and its full text in the CSV. The model/date, exact prompt, inputs and source versions are required for interpretability. Unknown backend model snapshot IDs remain blank; do not invent them.

```bash
python3 experiments/reproducibility_analysis/assessment_pilot/record_conversation.py \
  --run-id P01_A_r01 \
  --transcript /absolute/path/to/complete_conversation.md \
  --model 'exact model label shown in the interface' \
  --shared-url 'https://chatgpt.com/share/ACTUAL_LINK' \
  --settings 'record actual memory/custom-instruction settings' \
  --started-at-utc '2026-09-30T00:00:00+00:00'
```

Replace the example timestamp with the real time. Optionally use --response-json to preserve the assistant's JSON output separately in the CSV. Shared URLs remain blank until a real conversation has been shared. Five initial rows are marked not_started; no conversations or results have been invented. The helper archives bytes verbatim, preserves multiline CSV content and rejects overwriting already archived runs. New replicates use P01_A_r02 etc. It does not upload to GitHub or create share links automatically.

Commit conversation_runs.csv, new conversations/*.md and claim_reviews.csv to dev_experiment_analysis after each run. To have the assistant do that, provide the experiment transcript/export and its actual shared URL; the assistant cannot automatically observe other chats.

## Human review

Use claim_reviews.csv, one row per substantive assertion/checklist entry, with run_id as the join key. Review a shared subset independently before discussing judgments. Prefer blinding reviewers to metadata condition/model where feasible. Use review_verdict values supported, partially_supported, contradicted, or not_verifiable. Cite the exact paper/repository evidence. Reviewer inference is distinct from source evidence. Resolve disagreements and retain both original judgments.

Evaluate factual support, evidence-citation accuracy, completeness against a human-defined checklist and calibration of expressed uncertainty. If you want completeness/recall measures, humans need to construct the reference checklist before using the model's output to guide inspection; otherwise apparent agreement can be circular. Runtime feasibility and numeric matching remain unverified without execution. Do not validate predictions against the same agent's later opinion.

Metadata conditions B/C can later repeat the static assessment with the same sources and explicitly defined extra inputs in fresh sessions. Compare supported assertions, relevant prerequisites discovered, unsupported claims and review effort. This tests assessment quality rather than improvement in actual reproduction success. Automatically extracted metadata is fallible evidence. Select/approve common targets before any formal cross-condition comparison.

Keep the original PROTOCOL.md and PROMPTS.md as historical execution-study drafts. This assessment_pilot folder documents the current no-execution scope.
