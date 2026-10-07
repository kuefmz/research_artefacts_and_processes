"""Deterministic, commit-pinned three-mode research lifecycle assessment."""
from __future__ import annotations
import argparse, ast, base64, csv, hashlib, io, json, os, re, time, tokenize
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from .documentation import CRITERIA, VERSION as DOC_VERSION, analyze_document, is_documentation
from .analyzer import _parse_github_url, DEFAULT_CONTENT_LIMIT

HEURISTIC_VERSION = "2.0.0"
CSV_COLUMNS = ["GitHub URL", "Collection", "Processing", "Method", "Experimentation", "Evaluation", "Dissemination"]
CODE_EXTENSIONS = {".py",".r",".jl",".m",".java",".js",".ts",".go",".rs",".c",".cc",".cpp",".h",".hpp",".sh",".bash",".ipynb"}
EXCLUDED_PARTS = {".git","node_modules","vendor","vendors","third_party","third-party","dist","build","target","__pycache__",".ipynb_checkpoints"}
UNSUPPORTED_CODE_EXTENSIONS = {".rb",".php",".pl",".pm",".lua",".scala",".sc",".kt",".kts",".swift",".f",".f90",".f95",".fs",".fsx",".groovy",".sas",".do"}
RULES = {
"collection":[("CODE_COLLECTION_1",r"\b(?:requests?\.(?:get|post)|urlopen|wget|curl|download(?:_file)?|fetch)\s*\("),("CODE_COLLECTION_2",r"\b(?:read_csv|read_table|read_json|read_parquet|loadtxt|genfromtxt|open_dataset|load_dataset)\s*\("),("CODE_COLLECTION_3",r"\b(?:random|randn|simulate|synthetic|generate_samples?)\s*\([^\n]*")],
"processing":[("CODE_PROCESSING_1",r"\b(?:normalize|standardize|preprocess|tokenize|clean|filter|transform|convert|resample|impute|extract_features?)\s*\("),("CODE_PROCESSING_2",r"\.(?:dropna|fillna|replace|astype|reshape|transpose|groupby|merge|join|pivot|scale|fit_transform)\s*\(")],
"method":[("CODE_METHOD_1",r"\b(?:fit|predict|forward|backward|optimi[sz]e|minimi[sz]e|maximi[sz]e|solve|sample)\s*\("),("CODE_METHOD_2",r"\b(?:loss|objective|likelihood|gradient|kernel|posterior|prior)\s*=.+"),("CODE_METHOD_3",r"\b(?:np\.|numpy\.|math\.|torch\.|tf\.|jax\.)?(?:exp|log|sqrt|dot|matmul|einsum|softmax|sigmoid)\s*\(")],
"experimentation":[("CODE_EXPERIMENTATION_1",r"\b(?:main|run_experiment|train|run_analysis|experiment)\s*\("),("CODE_EXPERIMENTATION_2",r"\bfor\s+\w+\s+in\s+(?:product|ParameterGrid|grid|seeds?|alphas?|lambdas?|epochs?)\b")],
"evaluation":[("CODE_EVALUATION_1",r"\b(?:accuracy_score|precision_score|recall_score|f1_score|roc_auc_score|mean_squared_error|mean_absolute_error|r2_score|perplexity|confusion_matrix)\s*\("),("CODE_EVALUATION_2",r"\b(?:cross_val_score|bootstrap|ttest|t_test|anova|confidence_interval|credible_interval|compare_models?|evaluate_model)\s*\(")],
"dissemination":[("CODE_DISSEMINATION_1",r"\b(?:savefig|figsave|ggsave|write_html|to_latex|to_markdown|export_graphics)\s*\("),("CODE_DISSEMINATION_2",r"\b(?:to_csv|to_excel|write_csv|writetable)\s*\([^\n]*(?:result|metric|score|summary|table|report)"),("CODE_DISSEMINATION_3",r"\b(?:report|results?_table|summary_table)\s*\.(?:to_csv|to_excel|to_latex|to_markdown)\s*\(")]
}
COMPILED={c:[(i,re.compile(p,re.I)) for i,p in rs] for c,rs in RULES.items()}
SOFTWARE_TEST=re.compile(r"(^|/)(tests?|specs?)/|(^|/)(test_|.*_test\.)",re.I)
GENERIC_LOG=re.compile(r"\b(?:print|logging\.|logger\.|console\.log)\s*\(",re.I)

def _headers(token=None):
    h={"Accept":"application/vnd.github+json","User-Agent":"research-lifecycle/2.0","X-GitHub-Api-Version":"2022-11-28"}
    if token: h["Authorization"]=f"Bearer {token}"
    return h

def _request_json(url, token=None, retries=2):
    for attempt in range(retries+1):
        try:
            with urlopen(Request(url,headers=_headers(token)),timeout=15) as r:
                return json.loads(r.read().decode("utf-8"))
        except HTTPError as e:
            retry=e.code in {429,500,502,503,504} or e.code==403 and e.headers.get("X-RateLimit-Remaining")=="0"
            if not retry or attempt==retries:
                detail=e.read().decode("utf-8",errors="replace")
                raise RuntimeError(f"GitHub request failed ({e.code}): {detail}") from e
            reset=e.headers.get("X-RateLimit-Reset")
            delay=max(1,min(60,int(reset)-int(time.time()))) if reset and reset.isdigit() else min(2**attempt,30)
            time.sleep(delay)
        except (URLError,TimeoutError) as e:
            if attempt==retries: raise RuntimeError(f"GitHub request failed: {e}") from e
            time.sleep(min(2**attempt,30))

def _complete_tree(api, commit, token):
    root=_request_json(f"{api}/git/trees/{commit}?recursive=1",token)
    if not root.get("truncated"): return root.get("tree",[])
    out=[]
    def walk(sha,prefix=""):
        tree=_request_json(f"{api}/git/trees/{sha}",token)
        for item in tree.get("tree",[]):
            path=f"{prefix}/{item['path']}" if prefix else item["path"]
            if item.get("type")=="tree": walk(item["sha"],path)
            else: out.append({**item,"path":path})
    root_commit=_request_json(f"{api}/git/commits/{commit}",token)
    walk(root_commit["tree"]["sha"])
    return out

def _eligible_code(path):
    p=PurePosixPath(path.lower())
    return not any(x in EXCLUDED_PARTS for x in p.parts) and p.suffix in CODE_EXTENSIONS

def _python_executable(text):
    try: tree=ast.parse(text)
    except SyntaxError: return None
    doc_ranges=set()
    for node in ast.walk(tree):
        body=getattr(node,"body",None)
        if body and isinstance(body,list) and isinstance(body[0],ast.Expr) and isinstance(getattr(body[0],"value",None),ast.Constant) and isinstance(body[0].value.value,str):
            for n in range(body[0].lineno,getattr(body[0],"end_lineno",body[0].lineno)+1): doc_ranges.add(n)
    lines=text.splitlines()
    kept=["" if i+1 in doc_ranges else line for i,line in enumerate(lines)]
    # tokenize-like comment removal while preserving executable strings: AST ranges are authoritative;
    # regexes run on source with full-line comments removed, and matches must overlap an AST statement.
    stmt_ranges=[]
    for n in ast.walk(tree):
        if isinstance(n,ast.stmt) and not isinstance(n,(ast.Import,ast.ImportFrom)):
            stmt_ranges.append((n.lineno,getattr(n,"end_lineno",n.lineno)))
    return "\n".join(kept),stmt_ranges

def _notebook_cells(text, kind):
    nb=json.loads(text); matches=list(re.finditer(r'"source"\s*:\s*(\[(?:[^\]"\\]|\\.|"(?:[^"\\]|\\.)*")*\]|"(?:[^"\\]|\\.)*")',text,re.S))
    if len(matches)!=len(nb.get("cells",[])): raise ValueError("Cannot map notebook cells to physical JSON lines")
    out=[]
    for idx,(cell,m) in enumerate(zip(nb["cells"],matches)):
        if cell.get("cell_type")!=kind: continue
        src=cell.get("source",[]); src=src if isinstance(src,str) else "".join(src)
        strings=list(re.finditer(r'"(?:[^"\\]|\\.)*"',m.group(1))); mapping=[]
        for s in strings:
            val=json.loads(s.group()); physical=text.count("\n",0,m.start(1)+s.start())+1
            mapping.extend([physical]*max(1,len(val.splitlines())))
        out.append((idx,src,mapping))
    return out

def analyze_code(path,text):
    evidence=[]
    chunks=[]
    if path.lower().endswith(".ipynb"):
        for cell,src,mapping in _notebook_cells(text,"code"): chunks.append((src,mapping,cell))
    else: chunks=[(text,list(range(1,len(text.splitlines())+1)),None)]
    for src,mapping,cell in chunks:
        ranges=None
        if path.lower().endswith(".py"):
            parsed=_python_executable(src)
            if parsed is None: continue
            src,ranges=parsed
        else:
            src="\n".join("" if re.match(r"^\s*(?:#|//|%|;)",x) else x for x in src.splitlines())
        for criterion,rules in COMPILED.items():
            if criterion=="evaluation" and SOFTWARE_TEST.search(path): continue
            for rule_id,pattern in rules:
                for m in pattern.finditer(src):
                    line=src.count("\n",0,m.start())+1
                    if ranges and not any(a<=line<=b for a,b in ranges): continue
                    if criterion=="dissemination" and GENERIC_LOG.search(m.group(0)): continue
                    physical=mapping[line-1] if line-1<len(mapping) else line
                    evidence.append({"criterion":criterion,"rule_id":rule_id,"source":"code","path":path,"line":physical,"line_end":physical,"cell":cell,"matched_text":m.group(0)[:240]})
                    break
    return evidence

def _fetch_snapshot(repository_url,token,max_content_bytes):
    owner,repo=_parse_github_url(repository_url); url=f"https://github.com/{owner}/{repo}"; api=f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}"
    meta=_request_json(api,token); ref=meta["default_branch"]; commit=_request_json(f"{api}/commits/{quote(ref,safe='')}",token)["sha"]
    tree=_complete_tree(api,commit,token); candidates=[]; unsupported=[]
    for item in tree:
        if item.get("type")!="blob": continue
        path=item["path"]
        p=PurePosixPath(path.lower())
        excluded=any(x in EXCLUDED_PARTS for x in p.parts)
        if not excluded and p.suffix in UNSUPPORTED_CODE_EXTENSIONS: unsupported.append({"path":path,"status":"unsupported_format","size":int(item.get("size") or 0)})
        if is_documentation(path) or _eligible_code(path): candidates.append(item)
    def fetch(item):
        path=item["path"]; status={"path":path,"size":int(item.get("size") or 0),"documentation":is_documentation(path),"code":_eligible_code(path)}
        if status["size"]>max_content_bytes: return status|{"status":"skipped_size_limit","text":None}
        try:
            enc=quote(path,safe="/"); p=_request_json(f"{api}/contents/{enc}?ref={commit}",token)
            if p.get("encoding")!="base64": raise ValueError("non-base64 content")
            return status|{"status":"reviewed","text":base64.b64decode(p["content"]).decode("utf-8")}
        except Exception as e: return status|{"status":"failed","error":str(e),"text":None}
    with ThreadPoolExecutor(max_workers=8) as pool: files=list(pool.map(fetch,candidates))
    return {"url":url,"owner":owner,"repo":repo,"ref":ref,"commit":commit,"tree_count":len(tree),"files":files,"unsupported":unsupported}

def assess_snapshot(snapshot):
    doc_ev=[]; code_ev=[]; statuses=[]
    for f in snapshot["files"]:
        statuses.append({k:v for k,v in f.items() if k!="text"})
        if f["status"]!="reviewed": continue
        if f["documentation"]:
            try:
                for e in analyze_document(f["path"],f["text"])["evidence"]: doc_ev.append(e|{"source":"documentation"})
            except Exception as e: statuses.append({"path":f["path"],"status":"analysis_failed","source":"documentation","error":str(e)})
        if f["code"]:
            try: code_ev.extend(analyze_code(f["path"],f["text"]))
            except Exception as e: statuses.append({"path":f["path"],"status":"analysis_failed","source":"code","error":str(e)})
    statuses.extend(snapshot.get("unsupported",[]))
    incomplete=any(s["status"]!="reviewed" for s in statuses)
    def scores(ev): return {c:int(any(x["criterion"]==c for x in ev)) for c in CRITERIA}
    ds,cs=scores(doc_ev),scores(code_ev); comb={c:int(ds[c] or cs[c]) for c in CRITERIA}
    for e in doc_ev+code_ev:
        enc=quote(e["path"],safe="/"); e["url"]=f"{snapshot['url']}/blob/{snapshot['commit']}/{enc}#L{e['line']}" + (f"-L{e['line_end']}" if e["line_end"]!=e["line"] else "")
    return {"repository":{"url":snapshot["url"],"commit":snapshot["commit"],"ref":snapshot["ref"]},"scores":{"documentation":ds,"code":cs,"combined":comb},"evidence":doc_ev+code_ev,"coverage":{"complete":not incomplete,"files":statuses,"tree_entries":snapshot["tree_count"]},"method":{"version":HEURISTIC_VERSION,"documentation_version":DOC_VERSION,"uses_ai":False}}

def _cache_key(url,commit,max_bytes):
    return hashlib.sha256(f"{url}\0{commit}\0{HEURISTIC_VERSION}\0{max_bytes}".encode()).hexdigest()

def analyze_repository(url,token=None,max_content_bytes=DEFAULT_CONTENT_LIMIT,cache_dir=None):
    snapshot=_fetch_snapshot(url,token,max_content_bytes)
    if cache_dir:
        p=Path(cache_dir); p.mkdir(parents=True,exist_ok=True); f=p/f"{_cache_key(snapshot['url'],snapshot['commit'],max_content_bytes)}.json"
        if f.exists(): return json.loads(f.read_text())
    result=assess_snapshot(snapshot)
    if cache_dir: f.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n")
    return result

def _write_csv(path,results,mode):
    with Path(path).open("w",newline="",encoding="utf-8") as fh:
        w=csv.writer(fh); w.writerow(CSV_COLUMNS)
        for r in results: w.writerow([r["repository"]["url"],*[r["scores"][mode][c] for c in CRITERIA]])

def markdown_table(results,mode):
    rows=["| "+" | ".join(CSV_COLUMNS)+" |","|---|---:|---:|---:|---:|---:|---:|"]
    for r in results:
        u=r["repository"]["url"]; rows.append(f"| [{u}]({u}) | "+" | ".join(str(r["scores"][mode][c]) for c in CRITERIA)+" |")
    return "\n".join(rows)

def run(urls,out_dir,token=None,max_content_bytes=DEFAULT_CONTENT_LIMIT,mode="all",evidence=False,cache_dir=None):
    out=Path(out_dir); out.mkdir(parents=True,exist_ok=True); failures=[]
    progress=out/"progress.json"
    results=[]
    if progress.exists():
        try:
            saved=json.loads(progress.read_text())
            if isinstance(saved,list): results=[r for r in saved if r.get("repository",{}).get("url") in urls]
        except (json.JSONDecodeError,OSError):
            results=[]
    completed={r["repository"]["url"] for r in results}
    total=len(urls)
    for index,url in enumerate(urls,1):
        if url in completed:
            print(f"[{index}/{total}] already complete: {url}",flush=True)
            continue
        print(f"[{index}/{total}] assessing: {url}",flush=True)
        try:
            r=analyze_repository(url,token,max_content_bytes,cache_dir or out/".cache")
            if not r["coverage"]["complete"]: failures.append({"url":url,"reason":"incomplete review","coverage":r["coverage"]})
            results.append(r); completed.add(url)
            progress.write_text(json.dumps(results,indent=2)+"\n")
            print(f"[{index}/{total}] complete: {url}",flush=True)
        except Exception as e:
            failures.append({"url":url,"reason":str(e)})
            print(f"[{index}/{total}] failed: {url}: {e}",file=sys.stderr,flush=True)
    order={url:i for i,url in enumerate(urls)}
    results.sort(key=lambda r: order[r["repository"]["url"]])
    progress.write_text(json.dumps(results,indent=2)+"\n")
    (out/"review_status.json").write_text(json.dumps({"failures":failures,"repositories":[r["coverage"]|{"url":r["repository"]["url"],"commit":r["repository"]["commit"]} for r in results]},indent=2)+"\n")
    if failures or len(results)!=len(urls): raise RuntimeError(f"Review incomplete for {len(failures)} repositories; score CSV export stopped. See review_status.json")
    modes=["documentation","code","combined"] if mode=="all" else [mode]
    for m in modes: _write_csv(out/f"{m}_scores.csv",results,m)
    if evidence: (out/"evidence.json").write_text(json.dumps(results,indent=2,ensure_ascii=False)+"\n")
    return results

def main():
    p=argparse.ArgumentParser(description="Commit-pinned deterministic documentation/code/combined lifecycle assessment.")
    p.add_argument("repositories",nargs="*"); p.add_argument("--repos-file",type=Path); p.add_argument("--bundled",action="store_true")
    p.add_argument("--mode",choices=["all","documentation","code","combined"],default="all"); p.add_argument("--out-dir",type=Path,default=Path("lifecycle_output"))
    p.add_argument("--evidence",action="store_true"); p.add_argument("--markdown",action="store_true"); p.add_argument("--token",default=os.getenv("GITHUB_TOKEN"))
    p.add_argument("--max-content-bytes",type=int,default=DEFAULT_CONTENT_LIMIT); p.add_argument("--cache-dir",type=Path)
    a=p.parse_args(); urls=list(a.repositories)
    if a.bundled: urls += [x.strip() for x in (Path(__file__).with_name("repositories_100.txt")).read_text().splitlines() if x.strip()]
    if a.repos_file: urls += [x.strip() for x in a.repos_file.read_text().splitlines() if x.strip() and not x.lstrip().startswith("#")]
    if not urls: p.error("Supply repositories, --repos-file, or --bundled")
    if len(urls)!=len(set(urls)): p.error("Duplicate repository URL")
    try: results=run(urls,a.out_dir,a.token,a.max_content_bytes,a.mode,a.evidence,a.cache_dir)
    except RuntimeError as e: p.exit(2,f"error: {e}\n")
    if a.markdown:
        for m in (["documentation","code","combined"] if a.mode=="all" else [a.mode]): print(f"\n## {m.title()}\n\n{markdown_table(results,m)}")

if __name__=="__main__": main()
