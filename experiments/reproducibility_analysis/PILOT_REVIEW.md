# Collection pilot: observed evidence, not reproducibility verdicts

Five first-listed repositories / six linked publication entities were retrieved. This is a convenience engineering pilot, not the scientific sample. Zero reproduction attempts have been executed.

| Repository | Observed evidence | Consequence |
|---|---|---|
| DanSBS/NGSPower | Retrieved README describes sample-size estimation for NGS; associated paper title is “PEPR: Pipelines for evaluating prokaryotic references.” PDF candidate returned 403. | Potential relation issue; do not infer a wrong link from titles alone. Verify paper context and original graph relation before inclusion. |
| avian2/spectrum-sensing-methods | PDF first-page title/DOI agree with the linked record; Data Availability Statement explicitly points to this repository. README identifies acquisition, simulation and analysis entry points; acquisition uses physical receivers/signal generators. | Good candidate for relation validation. Separate original measurement acquisition, simulation and analysis of stored measurements. No target/result/version validated yet. |
| PanDAWMS/dkb | Both downloaded paper texts name the repository; README describes a database/ETL system and external services. | Relevant links have supporting evidence, but assess whether papers contain a target computational result and whether services/data are accessible. |
| abezuglov/ANN | Downloaded arXiv paper includes the repository URL in references. README endpoint returns 404 while repository/commit/tree succeed. Crossref 404 is followed by successful DataCite retrieval. | A reference supports association, not yet experiment-specific execution relevance. Missing default-root README does not mean no documentation elsewhere. |
| rakitko/NoStRa | Retrieved README describes an earlier/differently titled model paper; the linked paper PDF points to github.com/cyrulnic/NoStRa instead. | Check authors' upstream repository, shared history/version and actual experiment source before choosing this repository. |

Files contain full provider responses, hashes/retrieval timestamps, README text, current commit/file inventories, PDF candidates and five downloaded PDFs with text extraction. Current snapshot commits are not established paper-era versions. Recursive-tree completeness is recorded per repo. Source code archives and data have not been downloaded.

Request results: OpenAIRE 11 successes (five software + six publication records); OpenAlex six successes; Crossref five successes and one 404; DataCite one success; GitHub 19 successes and one README 404; PDF downloads five successes and one 403. The source graph relation type is not present in the uploaded JSON; it remains unspecified.

A PDF header was checked for all successful downloads. The spectrum-sensing PDF's first page was visually checked and its title/DOI/data-availability link confirmed. Other PDFs have extracted text and repository-link evidence but need publication-version and identity review. A successful download does not establish matching scientific results or redistribution rights.
