#!/usr/bin/env python3
"""Resumable provenance-preserving collector. Python standard library only.
Never executes downloaded repository code. See README.md for scope/limitations.
"""
import argparse, base64, concurrent.futures, datetime, hashlib, json, os, pathlib, re, subprocess, time, urllib.error, urllib.parse, urllib.request

def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def uid(s): return hashlib.sha256(s.encode()).hexdigest()[:20]
def write(p,d):
 p=pathlib.Path(p);p.parent.mkdir(parents=True,exist_ok=True)
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(d,indent=2,ensure_ascii=False));t.replace(p)
def doi(p):
 s=p.get('doi') or ''
 if not s and 'doi.org/' in (p.get('url') or ''):s=p['url'].split('doi.org/',1)[1]
 return re.sub(r'^https?://(?:dx\.)?doi\.org/','',s.strip(),flags=re.I).lower() or None

def fetch(url,path,provider,binary=False,retry_errors=False):
 path=pathlib.Path(path)
 if path.exists():
  old=json.loads(path.read_text())
  if old['status']=='ok' or not retry_errors:return old
 headers={'User-Agent':'ResearchReproducibilityCollector/0.1','Accept':'application/json' if not binary else 'application/pdf'}
 host=urllib.parse.urlparse(url).hostname
 if host=='api.github.com' and os.getenv('GITHUB_TOKEN'):headers['Authorization']='Bearer '+os.environ['GITHUB_TOKEN']
 if host=='api.openaire.eu' and os.getenv('OPENAIRE_TOKEN'):headers['Authorization']='Bearer '+os.environ['OPENAIRE_TOKEN']
 rec={'provider':provider,'requested_url':url,'retrieved_at':now(),'status':'error'}
 for attempt in range(3):
  try:
   with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=35) as r:
    b=r.read(50*1024*1024+1)
    if len(b)>50*1024*1024:raise ValueError('response exceeds 50 MiB cap')
    rec.update(http_status=r.status,final_url=r.url,sha256=hashlib.sha256(b).hexdigest(),content_type=r.headers.get('Content-Type'))
   if binary:
    if not b.startswith(b'%PDF-'):raise ValueError('response is not a PDF')
    dst=path.with_suffix('.pdf');dst.write_bytes(b);rec['local_file']=str(dst);rec['bytes']=len(b)
    if __import__('shutil').which('pdftotext'):
     out=dst.with_suffix('.txt');cp=subprocess.run(['pdftotext','-layout',str(dst),str(out)],capture_output=True)
     rec['text_extraction']={'exit_code':cp.returncode,'local_file':str(out) if cp.returncode==0 else None,'tool':'pdftotext -layout'}
   else:rec['data']=json.loads(b)
   rec['status']='ok';break
  except urllib.error.HTTPError as e:
   rec.update(http_status=e.code,error=str(e))
   if e.code not in (429,500,502,503,504) or attempt==2:break
   delay=min(float(e.headers.get('Retry-After','2')) if e.headers.get('Retry-After','2').isdigit() else 2,30);time.sleep(delay*(attempt+1))
  except Exception as e:
   rec['error']=str(e)
   if attempt==2:break
   time.sleep(attempt+1)
 write(path,rec);return rec

def normalize(source,out):
 source=pathlib.Path(source);rows=json.loads(source.read_text())['results'];repos=[];papers={};pairs=[]
 for i,r in enumerate(rows):
  u=urllib.parse.urlparse(r['github_url']);parts=u.path.strip('/').split('/')
  if u.hostname not in ('github.com','www.github.com') or len(parts)<2:raise ValueError('unexpected repository URL')
  name='/'.join(parts[:2]);rid=uid(name.lower())
  repos.append({'repo_id':rid,'full_name':name,'canonical_url':'https://github.com/'+name,'original_url':r['github_url'],'original_url_suffix':'/'.join(parts[2:]) or None,'source_row':i,'openaire_id':r.get('openaire_id'),'keywords':r.get('keywords',[]),'eligibility_status':'unreviewed','paper_commit_sha':None})
  for p in r.get('related_to',[]):
   d=doi(p);key='doi:'+d if d else 'openaire:'+str(p.get('openaire_id') or p.get('url'));pid=uid(key)
   paper=papers.setdefault(pid,{'paper_id':pid,'doi':d,'title':p.get('title'),'url':p.get('url'),'openaire_ids':[],'source_records':[],'pdf_identity_status':'unreviewed'})
   if p.get('openaire_id') not in paper['openaire_ids']:paper['openaire_ids'].append(p.get('openaire_id'))
   if p not in paper['source_records']:paper['source_records'].append(p)
   pairs.append({'pair_id':uid(rid+'|'+pid),'repo_id':rid,'paper_id':pid,'relation_source':'uploaded related_to','relation_type':'unspecified','relation_validation':'unreviewed','relation_evidence':[],'exclusion_reason':None,'target_results':[]})
 audit={'input_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'created_at':now(),'repository_rows':len(rows),'unique_canonical_repositories':len(set(r['full_name'].lower() for r in repos)),'publication_link_rows':len(pairs),'unique_paper_entities_by_doi_or_openaire_id':len(papers),'distinct_explicit_dois':len(set(p['doi'].lower() for r in rows for p in r['related_to'] if p.get('doi'))),'doi_missing_in_source_link_rows':sum(not p.get('doi') for r in rows for p in r['related_to']),'non_root_repository_urls':sum(bool(r['original_url_suffix']) for r in repos),'repositories_with_multiple_paper_links':sum(len(r.get('related_to',[]))>1 for r in rows),'note':'DOI inferred from doi.org URL only; no title-based merges or link validation.'}
 write(out/'manifest.json',{'schema_version':'0.1','audit':audit,'repositories':repos,'papers':list(papers.values()),'pairs':pairs});write(out/'audit.json',audit)
 return repos,list(papers.values()),pairs

def pdf_urls(p,records):
 candidates=[];d=p['doi'] or ''
 if d.startswith('10.1371/journal.pone.'):
  candidates.append(('publisher', 'https://journals.plos.org/plosone/article/file?'+urllib.parse.urlencode({'id':d,'type':'printable'})))
 if d.startswith('10.48550/arxiv.'):
  candidates.append(('arxiv','https://arxiv.org/pdf/'+d.split('arxiv.',1)[1]))
 oa=records.get('openalex',{}).get('data',{})
 for loc in [oa.get('best_oa_location'),*(oa.get('locations') or [])]:
  if loc and loc.get('is_oa') and loc.get('pdf_url'):candidates.append(('openalex_oa_location',loc['pdf_url']))
 for link in records.get('crossref',{}).get('data',{}).get('message',{}).get('link',[]):
  if link.get('content-type')=='application/pdf':candidates.append(('crossref_pdf_link_access_unverified',link['URL']))
 seen=set();return [(s,u) for s,u in candidates if not (u in seen or seen.add(u))]

def collect_repo(r,out,retry):
 folder=out/'repos'/r['repo_id'];root='https://api.github.com/repos/'+r['full_name'];records={}
 records['github']=fetch(root,folder/'github.json','github',retry_errors=retry)
 if r.get('openaire_id'):records['openaire']=fetch('https://api.openaire.eu/graph/v2/researchProducts/'+urllib.parse.quote(r['openaire_id'],safe=':'),folder/'openaire.json','openaire_graph_v2',retry_errors=retry)
 meta=records['github'].get('data',{});branch=meta.get('default_branch')
 if branch:
  commit=fetch(root+'/commits/'+urllib.parse.quote(branch,safe=''),folder/'commit.json','github',retry_errors=retry);sha=commit.get('data',{}).get('sha')
  if sha:
   tree=fetch(root+'/git/trees/'+sha+'?recursive=1',folder/'tree.json','github',retry_errors=retry)
   readme=fetch(root+'/readme?ref='+sha,folder/'readme.json','github',retry_errors=retry)
   if readme.get('status')=='ok':
    try:(folder/'README.txt').write_bytes(base64.b64decode(readme['data']['content']))
    except Exception:pass
   files=[{'path':x['path'],'blob_sha':x['sha'],'size':x.get('size'),'artefact_types':[],'research_process_steps':[],'annotation_status':'unannotated','evidence':[]} for x in tree.get('data',{}).get('tree',[]) if x.get('type')=='blob']
   write(folder/'snapshot.json',{'repo_id':r['repo_id'],'snapshot_commit_sha':sha,'snapshot_role':'current_default_branch_not_verified_paper_version','paper_commit_sha':None,'tree_truncated':tree.get('data',{}).get('truncated'),'files':files,'somef_status':'not_run','note':'No source archive collected. Tree paths and blob hashes are an index, not runnable source.'})
 return r['repo_id']

def collect_paper(p,out,retry,pdfs):
 folder=out/'papers'/p['paper_id'];records={};d=p.get('doi')
 if d:
  for provider,root in [('crossref','https://api.crossref.org/works/'),('openalex','https://api.openalex.org/works/https://doi.org/')]:
   records[provider]=fetch(root+urllib.parse.quote(d,safe='/'),folder/(provider+'.json'),provider,retry_errors=retry)
  if records['crossref'].get('http_status')==404:records['datacite']=fetch('https://api.datacite.org/dois/'+urllib.parse.quote(d,safe='/'),folder/'datacite.json','datacite',retry_errors=retry)
 for j,oid in enumerate(p['openaire_ids']):
  if oid:records['openaire_'+str(j)]=fetch('https://api.openaire.eu/graph/v2/researchProducts/'+urllib.parse.quote(oid,safe=':'),folder/('openaire_'+str(j)+'.json'),'openaire_graph_v2',retry_errors=retry)
 candidates=pdf_urls(p,records);write(folder/'pdf_candidates.json',{'paper_id':p['paper_id'],'candidates':[{'source':s,'url':u} for s,u in candidates],'identity_status':'unreviewed','note':'Discovery is incomplete; no full-text landing-page crawler. Downloads do not establish redistribution permission.'})
 if pdfs:
  for i,(s,u) in enumerate(candidates):
   res=fetch(u,folder/('pdf_'+str(i)+'.json'),s,binary=True,retry_errors=retry)
   if res['status']=='ok':break
 return p['paper_id']

def main():
 a=argparse.ArgumentParser();a.add_argument('source');a.add_argument('--out',default='collected');a.add_argument('--limit',type=int,default=5,help='first N source repositories; 0=all, not random sampling');a.add_argument('--workers',type=int,default=2);a.add_argument('--download-pdfs',action='store_true');a.add_argument('--retry-errors',action='store_true');a.add_argument('--normalize-only',action='store_true');args=a.parse_args()
 out=pathlib.Path(args.out);rs,ps,links=normalize(args.source,out)
 if args.normalize_only:return
 rs=rs[:args.limit] if args.limit else rs;ids={r['repo_id'] for r in rs};pids={l['paper_id'] for l in links if l['repo_id'] in ids};ps=[p for p in ps if p['paper_id'] in pids]
 with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
  tasks=[ex.submit(collect_repo,r,out,args.retry_errors) for r in rs]+[ex.submit(collect_paper,p,out,args.retry_errors,args.download_pdfs) for p in ps]
  for f in concurrent.futures.as_completed(tasks):
   try:print('collected',f.result(),flush=True)
   except Exception as e:print('task_error',repr(e),flush=True)
 statuses={}
 for f in out.rglob('*.json'):
  rec=json.loads(f.read_text())
  if 'provider' in rec:statuses.setdefault(rec['provider'],{});key=rec['status'];statuses[rec['provider']][key]=statuses[rec['provider']].get(key,0)+1
 write(out/'collection_summary.json',{'created_at':now(),'selected_repository_count':len(rs),'selected_paper_count':len(ps),'selection':'first N source rows; engineering pilot, not representative sample','request_statuses':statuses,'somef':'not installed/run','experiments_executed':0})
if __name__=='__main__':main()
