(() => {
  const nativeFetch = window.fetch.bind(window);
  const RAW = "https://raw.githubusercontent.com/kuefmz/research_artefacts_and_processes/demo";
  const MANIFEST = "static-manifest.json";
  const DATASET = RAW + "/src/research_process_steps/datasets/software_with_publications_v2.json";
  const FIRST10 = RAW + "/src/research_process_steps/datasets/first_10_papers.json";

  let statePromise;

  function response(payload, status = 200) {
    return Promise.resolve(new Response(JSON.stringify(payload), {
      status,
      headers: {"Content-Type": "application/json"}
    }));
  }
  function normRepo(url) {
    try {
      const u = new URL(url);
      const parts = u.pathname.split("/").filter(Boolean);
      return parts.length >= 2
        ? ("https://github.com/" + parts[0] + "/" + parts[1].replace(/\.git$/i, "")).toLowerCase()
        : String(url).toLowerCase();
    } catch {
      return String(url || "").toLowerCase().replace(/\/$/, "");
    }
  }
  async function json(url) {
    const r = await nativeFetch(url);
    if (!r.ok) throw new Error("Could not load static demo data: " + url);
    return r.json();
  }
  function buildCollectionPapers(dataset) {
    const papers = [];
    for (const record of dataset.results || []) {
      for (const source of record.related_to || []) {
        papers.push({
          paper_id: "C" + String(papers.length + 1).padStart(4, "0"),
          github_url: normRepo(record.github_url),
          title: source.title || "",
          doi: source.doi || null,
          paper_url: source.url || ""
        });
      }
    }
    return papers;
  }
  function fillPrompt(template, paper, ref, variant) {
    const values = {
      case_id: paper.paper_id,
      title: paper.title || "(title unavailable)",
      doi: paper.doi || "(DOI unavailable)",
      paper_url: paper.paper_url || "(paper source URL unavailable; use the attached PDF)",
      repo_url: paper.github_url,
      commit: ref || "(commit not established; use the supplied repository snapshot and report this limitation)"
    };
    let out = template || "";
    for (const [key, value] of Object.entries(values)) {
      out = out.split("{" + key + "}").join(value);
    }
    out += "\n\nINPUT NOTE: The paper PDF " + paper.paper_id + ".pdf is attached directly to this conversation. Treat that attached PDF as the paper input for this assessment.";
    if (variant === "c1") {
      out += " The research-process-step metadata file " + paper.paper_id + ".json is also attached directly to this conversation. Treat that JSON as the supplied additional metadata and verify it against the repository files.";
    }
    return out;
  }
  async function init() {
    const manifest = await json(MANIFEST);
    const [dataset, first10, ...metaRows] = await Promise.all([
      json(DATASET),
      json(FIRST10),
      ...manifest.result_meta_paths.map(path => json(RAW + "/" + path))
    ]);
    const executions = new Map(metaRows.map(meta => [normRepo(meta.repo_url), meta]));
    const resultPaths = manifest.result_paths || {};
    const conversations = {};
    await Promise.all((manifest.conversation_ids || []).map(async id => {
      try { conversations[id] = await json(RAW + "/data/reproducibility_conversations/" + id + ".json"); } catch {}
    }));
    const pdfIds = new Set(manifest.pdf_ids || []);
    const collectionPapers = buildCollectionPapers(dataset);

    function enrichPaper(paper, includeRepro = true) {
      const p = {...paper};
      const execution = executions.get(normRepo(p.github_url));
      p.pdf_url = pdfIds.has(p.paper_id)
        ? RAW + "/data/selected_papers/" + p.paper_id + ".pdf"
        : null;
      if (includeRepro) {
        p.reproducibility_conversations = conversations[p.paper_id] || {paper_id:p.paper_id, records:{c0:[],c1:[]}};
        p.research_step_metadata_url = execution
          ? "/api/publication-collection/papers/" + p.paper_id + "/research-step-metadata"
          : null;
        p.reproducibility_prompts = {};
        for (const variant of ["c0","c1"]) {
          p.reproducibility_prompts[variant] = fillPrompt(
            manifest.prompts?.[variant]?.prompt || "",
            p,
            execution?.ref || null,
            variant
          );
        }
      }
      return p;
    }
    const fullPapers = collectionPapers.map(p => enrichPaper(p, true));

    const firstPapers = (first10.papers || []).map((p, i) => {
      const q = {
        ...p,
        paper_id: p.paper_id || ("C" + String(i + 1).padStart(4, "0")),
        github_url: normRepo(p.github_url)
      };
      q.pdf_url = pdfIds.has(q.paper_id) ? RAW + "/data/selected_papers/" + q.paper_id + ".pdf" : null;
      return q;
    });

    function repoRows(papers) {
      const seen = new Set(), rows = [];
      for (const paper of papers) {
        const url = normRepo(paper.github_url);
        if (seen.has(url)) continue;
        seen.add(url);
        rows.push({repo_url:url, execution:executions.get(url) || null, conversations:{}});
      }
      return rows;
    }

    return {manifest, executions, resultPaths, conversations, fullPapers, firstPapers, repoRows};
  }
  statePromise = init();

  window.fetch = async function(input, options = {}) {
    const url = typeof input === "string" ? input : input.url;
    if (!url.startsWith("/api/")) return nativeFetch(input, options);

    const method = String(options.method || "GET").toUpperCase();
    if (method !== "GET") {
      return response({detail:"Read-only GitHub Pages demo: modifications and reruns are disabled."}, 405);
    }
    const s = await statePromise;

    if (url === "/api/reproducibility/prompts") {
      return response({prompts:s.manifest.prompts || {}});
    }
    if (url === "/api/publication-collection") {
      return response({papers:s.fullPapers, repositories:s.repoRows(s.fullPapers)});
    }
    if (url === "/api/selection") {
      return response({papers:s.firstPapers, repositories:s.repoRows(s.firstPapers)});
    }
    if (url === "/api/executed") {
      return response({
        count:s.executions.size,
        repositories:[...s.executions.values()].map(meta => ({...meta, conversations:{}}))
      });
    }

    let m = url.match(/^\/api\/executed\/([^/?#]+)$/);
    if (m) {
      const id = decodeURIComponent(m[1]);
      const path = s.resultPaths[id];
      if (!path) return response({detail:"Stored repository result not found."}, 404);
      try { return response(await json(RAW + "/" + path)); }
      catch (e) { return response({detail:e.message}, 500); }
    }

    m = url.match(/^\/api\/publication-collection\/papers\/(C\d{4})\/research-step-metadata$/);
    if (m) {
      const paper = s.fullPapers.find(p => p.paper_id === m[1]);
      if (!paper) return response({detail:"Unknown publication-collection paper."}, 404);
      const meta = s.executions.get(normRepo(paper.github_url));
      if (!meta) return response({detail:"No stored heuristic result exists for this repository."}, 404);
      const path = s.resultPaths[meta.id];
      if (!path) return response({detail:"Stored repository result not found."}, 404);
      const result = await json(RAW + "/" + path);
      const repository = result.repository || {};
      return response({
        schema_version:"1",
        paper_id:paper.paper_id,
        repository:{
          url:paper.github_url,
          ref:repository.ref || null,
          tree_sha:repository.commit_tree_sha || null
        },
        files:(result.files || []).map(item => ({
          path:item.path,
          blob_sha:item.blob_sha,
          artifact_kind:item.artifact_kind,
          research_process_steps:item.steps || [],
          evidence:item.evidence || []
        }))
      });
    }

    return response({detail:"This API action is not available in the read-only demo."}, 404);
  };
})();