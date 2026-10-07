import csv, io, json
import pytest
from research_process_steps.lifecycle import (
    CRITERIA, CSV_COLUMNS, analyze_code, assess_snapshot, _write_csv, _notebook_cells
)

def scores(text,path="analysis.py"):
    ev=analyze_code(path,text)
    return {c:int(any(e["criterion"]==c for e in ev)) for c in CRITERIA}

def test_all_six_code_criteria():
    text="""import pandas as pd
x = pd.read_csv("identified_input.csv")
x = x.dropna()
loss = np.log(x).sum()
run_experiment(x)
score = accuracy_score(y, pred)
results_table.to_latex("results.tex")
"""
    assert scores(text)==dict.fromkeys(CRITERIA,1)

def test_comments_docstrings_and_unused_imports_do_not_score():
    text='''"""accuracy_score(y,p); download(data); savefig("x")"""
# read_csv("data.csv")
import sklearn.metrics
x = 1
'''
    assert not any(scores(text).values())

def test_software_tests_do_not_establish_evaluation():
    assert scores("score = accuracy_score(y,p)","tests/test_model.py")["evaluation"]==0

def test_generic_logging_is_not_dissemination():
    assert scores('print("results")')["dissemination"]==0

def test_notebook_code_only_and_physical_lines():
    nb=json.dumps({"cells":[
      {"cell_type":"markdown","source":["accuracy_score(y,p)"]},
      {"cell_type":"code","source":["score = accuracy_score(y,p)"]}
    ]},indent=2)
    ev=analyze_code("analysis.ipynb",nb)
    assert len([e for e in ev if e["criterion"]=="evaluation"])==1
    e=next(e for e in ev if e["criterion"]=="evaluation")
    assert e["cell"]==1 and "accuracy_score" in nb.splitlines()[e["line"]-1]

def test_combined_is_exact_or_and_sources_separate():
    snap={"url":"https://github.com/x/y","commit":"a"*40,"ref":"main","tree_count":2,"files":[
      {"path":"README.md","status":"reviewed","documentation":True,"code":False,"size":20,"text":"Download the dataset."},
      {"path":"analysis.py","status":"reviewed","documentation":False,"code":True,"size":20,"text":"score = accuracy_score(y,p)"}
    ]}
    r=assess_snapshot(snap)
    for c in CRITERIA:
        assert r["scores"]["combined"][c] == int(r["scores"]["documentation"][c] or r["scores"]["code"][c])
    assert {e["source"] for e in r["evidence"]}=={"documentation","code"}
    assert all("/blob/"+"a"*40+"/" in e["url"] for e in r["evidence"])

def test_incomplete_coverage_is_separate_from_binary_scores():
    snap={"url":"https://github.com/x/y","commit":"b"*40,"ref":"main","tree_count":1,"files":[
      {"path":"README.md","status":"failed","documentation":True,"code":False,"size":20,"text":None,"error":"boom"}
    ]}
    r=assess_snapshot(snap)
    assert not r["coverage"]["complete"]
    assert set(r["scores"]["documentation"].values())=={0}

def test_csv_exact_columns_and_order(tmp_path):
    rs=[{"repository":{"url":"https://github.com/b/2"},"scores":{"documentation":dict.fromkeys(CRITERIA,0)}},
        {"repository":{"url":"https://github.com/a/1"},"scores":{"documentation":dict.fromkeys(CRITERIA,1)}}]
    p=tmp_path/"x.csv"; _write_csv(p,rs,"documentation")
    rows=list(csv.reader(p.open()))
    assert rows[0]==CSV_COLUMNS
    assert [r[0] for r in rows[1:]]==["https://github.com/b/2","https://github.com/a/1"]
    assert set(rows[1][1:])=={"0"} and set(rows[2][1:])=={"1"}

def test_bundled_list_exactly_100_unique():
    from research_process_steps import lifecycle
    p=__import__("pathlib").Path(lifecycle.__file__).with_name("repositories_100.txt")
    urls=[x for x in p.read_text().splitlines() if x]
    assert len(urls)==100 and len(set(urls))==100
    assert urls[0]=="https://github.com/mspeich/forhytm"
    assert urls[-1]=="https://github.com/maidens/ACC-2016"
