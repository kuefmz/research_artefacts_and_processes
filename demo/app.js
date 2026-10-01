const RAW = "https://raw.githubusercontent.com/kuefmz/research_artefacts_and_processes/demo";
const REPO = "https://github.com/kuefmz/research_artefacts_and_processes/blob/demo";
const DATASET_URL = `${RAW}/src/research_process_steps/datasets/software_with_publications_v2.json`;
const ANALYTICS_URL = `${RAW}/data/publication_collection_analysis/meeting_summary.json`;
const PAPER_BASE = `${RAW}/data/selected_papers`;

const knownPdfIds = new Set(["C0001","C0002","C0003","C0004","C0005","C0006","C0007","C0008","C0009","C0010"]);
const assessmentIds = ["C0001","C0002","C0003"];
let papers = [];
let conversations = {};

function esc(v){return String(v ?? "").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[m]));}
function repoIdentity(url){
  try{
    const u=new URL(url); const parts=u.pathname.split("/").filter(Boolean);
    return parts.length>=2 ? `https://github.com/${parts[0]}/${parts[1].replace(/\.git$/,"")}`.toLowerCase() : url;
  }catch{return url;}
}
function buildPapers(dataset){
  const out=[];
  for(const record of dataset.results || []){
    for(const source of record.related_to || []){
      out.push({
        paper_id:`C${String(out.length+1).padStart(4,"0")}`,
        github_url:repoIdentity(record.github_url),
        title:source.title || "",
        doi:source.doi || "",
        paper_url:source.url || ""
      });
    }
  }
  return out;
}
async function loadConversation(id){
  try{
    const r=await fetch(`${RAW}/data/reproducibility_conversations/${id}.json`);
    if(!r.ok) return;
    conversations[id]=await r.json();
  }catch{}
}
function shareable(record){return record?.url?.includes("/share/");}
function assessmentHtml(id){
  const rec=conversations[id]?.records || {};
  const parts=[];
  for(const variant of ["c0","c1"]){
    const item=(rec[variant]||[]).find(shareable);
    if(item) parts.push(`<a class="pill" href="${esc(item.url)}" target="_blank" rel="noopener">${variant.toUpperCase()} conversation</a>`);
  }
  return parts.length ? `<div class="assessment">${parts.join("")}</div>` : '<span class="none">—</span>';
}
function pdfHtml(id){
  if(!knownPdfIds.has(id)) return '<span class="none">—</span>';
  return `<a href="${PAPER_BASE}/${encodeURIComponent(id)}.pdf" target="_blank" rel="noopener">Open PDF</a>`;
}
function render(){
  const q=document.getElementById("search").value.trim().toLowerCase();
  const f=document.getElementById("filter").value;
  const visible=papers.filter(p=>{
    const searchable=`${p.paper_id} ${p.title} ${p.doi} ${p.github_url}`.toLowerCase();
    const hasAssessment=assessmentHtml(p.paper_id).includes("conversation");
    return (!q||searchable.includes(q)) && (!f||(f==="pdf"?knownPdfIds.has(p.paper_id):hasAssessment));
  });
  document.getElementById("status").textContent=`${visible.length.toLocaleString()} of ${papers.length.toLocaleString()} paper–repository associations`;
  document.getElementById("rows").innerHTML=visible.map(p=>`<tr>
    <td><span class="meta">${esc(p.paper_id)}</span></td>
    <td><a href="${esc(p.paper_url)}" target="_blank" rel="noopener">${esc(p.title||"(untitled)")}</a><br><span class="meta">${esc(p.doi||"")}</span></td>
    <td><a href="${esc(p.github_url)}" target="_blank" rel="noopener">${esc(p.github_url.replace("https://github.com/",""))}</a></td>
    <td>${pdfHtml(p.paper_id)}</td>
    <td>${assessmentHtml(p.paper_id)}</td>
  </tr>`).join("");
}
async function main(){
  try{
    const [datasetRes, analyticsRes] = await Promise.all([fetch(DATASET_URL),fetch(ANALYTICS_URL)]);
    if(!datasetRes.ok) throw new Error("Could not load publication dataset.");
    const dataset=await datasetRes.json();
    const analytics=analyticsRes.ok ? await analyticsRes.json() : {};
    papers=buildPapers(dataset);

    await Promise.all(assessmentIds.map(loadConversation));

    const uniqueRepos=new Set(papers.map(p=>p.github_url));
    const scope=analytics.dataset_scope||{};
    const summary=[
      [uniqueRepos.size.toLocaleString(),"repositories in collection"],
      [papers.length.toLocaleString(),"paper associations"],
      [(scope.completed_count ?? analytics.completed_repositories ?? 0).toLocaleString(),"repositories analyzed"],
      [(analytics.total_files ?? 0).toLocaleString(),"files inspected"],
      [`${Number(analytics.unclassified_pct ?? 0).toFixed(1)}%`,"files unclassified"]
    ];
    document.getElementById("summary").innerHTML=summary.map(([v,l])=>`<div class="metric"><div class="value">${v}</div><div class="label">${l}</div></div>`).join("");

    const per=analytics.files_per_step||{};
    const order=["collection","processing","implementation","experimentation","evaluation","dissemination"];
    document.getElementById("steps").innerHTML=order.map(step=>`<div class="step"><strong>${Number(per[step]||0).toLocaleString()}</strong><span>${step}</span></div>`).join("");
    render();
  }catch(err){
    document.getElementById("status").textContent=err.message;
    document.getElementById("status").style.color="#a52a2a";
  }
}
document.getElementById("search").addEventListener("input",render);
document.getElementById("filter").addEventListener("change",render);
main();
