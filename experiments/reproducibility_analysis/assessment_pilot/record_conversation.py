#!/usr/bin/env python3
"""Archive a completed visible conversation and update its CSV record. No network access."""
import argparse,csv,datetime,hashlib,json,pathlib,re

def main():
 p=argparse.ArgumentParser();p.add_argument('--root',type=pathlib.Path,default=pathlib.Path(__file__).resolve().parent);p.add_argument('--run-id',required=True);p.add_argument('--transcript',type=pathlib.Path,required=True);p.add_argument('--model',required=True);p.add_argument('--platform',default='ChatGPT');p.add_argument('--shared-url',default='');p.add_argument('--started-at-utc',default='');p.add_argument('--settings',default='');p.add_argument('--response-json',type=pathlib.Path);a=p.parse_args()
 if not re.fullmatch(r'P0[1-5]_A_r[0-9]{2,}',a.run_id):p.error('Use e.g. P01_A_r01 or P01_A_r02')
 if a.shared_url and not a.shared_url.startswith('https://chatgpt.com/share/'):p.error('Shared URL must begin https://chatgpt.com/share/')
 path=a.root/'conversation_runs.csv'
 with path.open(newline='',encoding='utf-8') as f:reader=csv.DictReader(f);fields=reader.fieldnames;rows=list(reader)
 row=next((r for r in rows if r['run_id']==a.run_id),None)
 if row and row['status']!='not_started':p.error('Already archived. Use a new replicate ID; do not overwrite raw conversations.')
 if row is None:
  case=a.run_id.split('_')[0];template=next((r for r in rows if r['case_id']==case),None)
  if not template:p.error('Unknown case')
  row={k:'' for k in fields}
  for k in ['case_id','condition','paper_title','doi','paper_source_url','paper_sha256','paper_identity_review','repo_snapshot_url','repo_commit_sha','prompt_path','prompt_sha256','prompt_text']:row[k]=template[k]
  row.update(run_id=a.run_id,replicate=a.run_id.rsplit('r',1)[1],review_status='not_reviewed');rows.append(row)
 raw=a.transcript.read_bytes();text=raw.decode('utf-8')
 if not text.strip():p.error('Transcript is empty')
 response=''
 if a.response_json:
  response=a.response_json.read_text(encoding='utf-8');json.loads(response)
 rel=pathlib.Path('conversations')/(a.run_id+'.md');dest=a.root/rel
 if dest.exists():p.error('Transcript destination already exists')
 dest.parent.mkdir(exist_ok=True);dest.write_bytes(raw)
 row.update(status='conversation_archived',started_at_utc=a.started_at_utc,completed_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),platform=a.platform,model_display_name=a.model,memory_and_custom_instructions_setting=a.settings,shared_conversation_url=a.shared_url,shared_link_access_status='not_checked' if a.shared_url else 'not_created',transcript_path=str(rel),transcript_sha256=hashlib.sha256(raw).hexdigest(),transcript_text=text,response_json=response)
 tmp=path.with_suffix('.csv.tmp')
 with tmp.open('w',newline='',encoding='utf-8') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
 tmp.replace(path);print('Archived:',a.run_id,'Transcript SHA-256:',row['transcript_sha256'])
if __name__=='__main__':main()
