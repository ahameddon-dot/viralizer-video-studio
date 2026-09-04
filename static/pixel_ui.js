const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];let report={},topics=[],current={};const esc=v=>String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));async function api(url,opt={}){const r=await fetch(url,{headers:{'Content-Type':'application/json',...(opt.headers||{})},...opt});if(!r.ok){let d={};try{d=await r.json()}catch{}throw new Error(d.detail||'Request failed ('+r.status+')')}return r}function toast(s,bad=false){const e=$('#toast');e.textContent=s;e.style.borderColor=bad?'#71313a':'#353c53';e.classList.remove('hidden');setTimeout(()=>e.classList.add('hidden'),5000)}function heat(t){return String(t.discovery_heat||t.heat||'HOT').replaceAll('_',' ')}function score(t){let v=Number(t.viralizer?.viral_score||t.viral_score||0);return Math.min(99,Math.round(v||({EXPLODING:94,'VERY HOT':89,HOT:83,WATCH:74}[heat(t)]||80)))}function conv(t){const n=Number(t.mentions||t.cross_source_signals||t.source_urls?.length||0);return n>999999?(n/1e6).toFixed(1)+'M':n>999?(n/1e3).toFixed(1)+'K':n||'—'}function initials(t){return String(t.category||'Trend').split(/\s+/).slice(0,2).map(x=>x[0]).join('').toUpperCase()}function image(t){const direct=t.thumbnail_url||t.thumbnail||t.image_url||t.image;if(direct)return direct;const name=String(t.topic||t.category||'').toLowerCase(),file=name.includes('iphone')?'topic-iphone.png':name.includes('space')?'topic-spacex.png':name.includes('fitness')?'topic-fitness.png':name.includes('polit')?'topic-politics.png':'topic-nvidia.png';return '/static/master/thumbnails/'+file}function date(v){if(!v)return['Recent',''];const d=new Date(v);return isNaN(d)?[String(v),'']:[d.toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'}),d.toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit'})]}
function render(data){report=data||{};topics=Array.isArray(report.topics)?report.topics:[];const cats=[...new Set(topics.map(t=>t.category).filter(Boolean))].sort(),sel=$('#category').value;$('#category').innerHTML='<option value="ALL">All categories</option>'+cats.map(c=>'<option>'+esc(c)+'</option>').join('');if(cats.includes(sel))$('#category').value=sel;$('#generatedAt').textContent=report.generated_at?'Updated '+new Date(report.generated_at).toLocaleString():'';filterRender()}function filterRender(){const q=$('#globalSearch').value.toLowerCase(),c=$('#category').value,shown=topics.filter(t=>(c==='ALL'||t.category===c)&&(!q||JSON.stringify(t).toLowerCase().includes(q)));$('#empty').classList.toggle('hidden',!!shown.length);$('#topicRows').innerHTML=shown.map((t,i)=>{const d=date(t.published_at),im=image(t);return '<tr><td>'+(i+1)+'</td><td><div class="topic-cell"><div class="thumb">'+(im?'<img src="'+esc(im)+'" onerror="this.remove()">':esc(initials(t)))+'</div><div style="min-width:0"><div class="topic-name">'+esc(t.topic)+'</div><div class="topic-alt">'+esc(t.youtube_search_topic||t.alternate_topics?.[0]||'Worldwide trend')+'</div></div></div></td><td><span class="pill">'+esc(t.category||'General')+'</span></td><td>'+esc(t.source_platforms?.[0]||t.source||'Public sources')+'</td><td class="score">'+score(t)+'%</td><td>'+conv(t)+'</td><td>'+esc(d[0])+'<br><small style="color:var(--muted)">'+esc(d[1])+'</small></td><td><button class="action" data-i="'+topics.indexOf(t)+'">View insight</button></td></tr>'}).join('');$('#opportunities').innerHTML=shown.slice(0,5).map((t,i)=>'<article class="opp"><div class="opp-media"><span class="rank">#'+(i+1)+'</span><span class="heat">'+esc(heat(t))+'</span></div><div class="opp-body"><h3>'+esc(t.topic)+'</h3><div class="opp-meta"><span>'+esc(t.category||'General')+'</span><b style="color:var(--green)">'+score(t)+'%</b></div></div></article>').join('')}
function render(data){report=data||{};topics=Array.isArray(report.topics)?report.topics:[];const cats=[...new Set(topics.map(t=>t.category).filter(Boolean))].sort(),sel=$('#category').value;$('#category').innerHTML='<option value="ALL">All categories</option>'+cats.map(c=>'<option>'+esc(c)+'</option>').join('');if(cats.includes(sel))$('#category').value=sel;else $('#category').value='ALL';$('#generatedAt').textContent=report.generated_at?'Updated '+new Date(report.generated_at).toLocaleString():'';renderCategoryChips();filterRender()}
async function loadLatest(){try{render(await(await api('/api/daily/latest')).json());$('#runStatus').textContent=topics.length+' cached topics ready'}catch{render({topics:[]});$('#runStatus').textContent='Ready to discover'}}async function run(){const b=$('#runBtn');b.disabled=true;b.textContent='Discovering…';try{await api('/api/daily/run',{method:'POST',body:JSON.stringify({category:$('#category').value,keyword:$('#keyword').value.trim(),description:$('#description').value.trim()})});for(let i=0;i<120;i++){await new Promise(r=>setTimeout(r,2500));const s=await(await api('/api/daily/status')).json();$('#runStatus').textContent=s.message||s.stage||'Building topic list…';if(!s.running)break}await loadLatest();toast('Discovery results refreshed.')}catch(e){toast(e.message,true)}finally{b.disabled=false;b.textContent='✦ Run Discovery'}}
async function insight(t){current=t;$('#modalBack').classList.remove('hidden');$('#modalTitle').textContent=t.topic;$('#modalBody').innerHTML='<p>Loading the complete Viralizer report…</p>';try{const d=await(await api('/api/daily/report',{method:'POST',body:JSON.stringify({topic:t.topic})})).json();current={...t,...d};$('#modalBody').innerHTML='<p>'+esc(d.why_it_matters||d.overview||d.summary||t.best_content_angle||'The full report is ready.')+'</p><div class="modal-actions"><button class="btn secondary" id="pdfBtn">Get PDF</button><button class="btn" id="prepareBtn">Prepare video prompt</button></div>'}catch(e){$('#modalBody').innerHTML='<p>'+esc(e.message)+'</p>'}}async function prepare(){const d=await(await api('/api/video/prompt',{method:'POST',body:JSON.stringify({content:current,provider:'pixverse',duration:5,quality:'540p'})})).json();$('#modalBody').innerHTML='<p>Review and edit the prompt. Nothing is generated until you confirm.</p><textarea id="videoPrompt">'+esc(d.prompt)+'</textarea><div class="modal-controls"><select class="select" id="duration"><option value="5">5 seconds</option><option value="10">10 seconds</option></select><select class="select" id="quality"><option value="540p">540p</option><option value="720p">720p</option></select></div><div class="modal-actions"><button class="btn" id="generateBtn">Confirm & generate video</button></div>'}async function generate(){try{const d=await(await api('/api/video/generate',{method:'POST',body:JSON.stringify({content:current,prompt:$('#videoPrompt').value,provider:'pixverse',duration:+$('#duration').value,quality:$('#quality').value})})).json();$('#modalBody').innerHTML='<p>Video generation started.</p><p>Job: '+esc(d.job_id)+'</p>';toast('Video generation started.')}catch(e){toast(e.message,true)}}async function pdf(){const r=await fetch('/api/daily/pdf',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({topic:current.topic})});if(!r.ok)return toast('PDF could not be prepared.',true);const a=document.createElement('a');a.href=URL.createObjectURL(await r.blob());a.download='viralizer-report.pdf';a.click()}
$('#runBtn').onclick=run;$('#globalSearch').oninput=filterRender;$('#category').onchange=filterRender;$('#descToggle').onclick=e=>{e.currentTarget.classList.toggle('on');$('#descriptionRow').style.display=e.currentTarget.classList.contains('on')?'block':'none'};$('#closeModal').onclick=()=>$('#modalBack').classList.add('hidden');document.addEventListener('click',e=>{if(e.target.matches('.action'))insight(topics[+e.target.dataset.i]);if(e.target.id==='prepareBtn')prepare();if(e.target.id==='generateBtn')generate();if(e.target.id==='pdfBtn')pdf();if(e.target.matches('.tab')&&!['For You','Hot Topics'].includes(e.target.textContent))location.href='/studio'});loadViralizerTopics();

async function loadViralizerTopics(){
  $('#runStatus').textContent='Loading Viralizer topics…';setFeedLoading('Viralizer topics',true);
  try{
    const payload=await(await api('/api/topics/hot')).json();
    const normalized=(payload.topics||[]).map((item,index)=>({
      ...item,
      topic:item.topic||item.title||item.name||item.keyword||`Viralizer topic ${index+1}`,
      category:item.category||(Array.isArray(item.categories)?item.categories[0]:item.categories)||'Viralizer',
      source_platforms:item.source_platforms||['Viralizer'],
      thumbnail_url:item.thumbnail_url||item.thumbnail||item.image_url||item.image,
      discovery_heat:item.discovery_heat||item.heat||'HOT',
      viral_score:item.viral_score||item.score||item.resonance,
      published_at:item.published_at||item.date||item.created_at,
      youtube_search_topic:item.youtube_search_topic||item.search_topic||item.topic||item.title
    }));
    render({topics:normalized,generated_at:new Date().toISOString()});
    $('#runStatus').textContent=`${normalized.length} Viralizer topics ready`;
  }catch(error){
    $('#runStatus').textContent='Could not load Viralizer topics';
    toast(error.message,true);
  }finally{setFeedLoading('',false)}
}

document.addEventListener('click',event=>{
  const tab=event.target.closest('.tab[data-feed]');
  if(!tab)return;
  event.preventDefault();
  event.stopImmediatePropagation();
  $$('.tab').forEach(item=>item.classList.toggle('active',item===tab));
  loadFeed(tab.dataset.feed);
},true);

function finalAsset(topic,large=false,index=0){
  const direct=topic.thumbnail_url||topic.thumbnail||topic.image_url||topic.image||topic.post_image||topic.media?.image||topic.media?.thumbnail;
  if(direct)return direct;
  const sequence=large?['fitness','nvidia','iphone','spacex','politics']:['fitness','iphone','music','nvidia','politics','saudi','spacex','startup'];
  return '/static/final/thumbnails/'+(large?'opportunity':'table')+'-'+sequence[index%sequence.length]+'.png';
}
function filterRender(){
  const query=[$('#globalSearch').value,$('#tableSearch')?.value||''].join(' ').trim().toLowerCase(),selectedCategory=$('#category').value;
  const shown=topics.filter(topic=>(selectedCategory==='ALL'||topic.category===selectedCategory)&&(!query||JSON.stringify(topic).toLowerCase().includes(query)));
  $('#empty').classList.toggle('hidden',shown.length>0);
  $('#topicRows').innerHTML=shown.map((topic,index)=>{const published=date(topic.published_at),source=topic.source_platforms?.[0]||topic.source||'Public sources',topicIndex=topics.indexOf(topic);return '<tr><td>'+(index+1)+'</td><td><div class="topic-cell"><div class="thumb"><img src="'+esc(finalAsset(topic,false,index))+'" onerror="this.onerror=null;this.src=\'/static/final/thumbnails/table-iphone.png\'"></div><div style="min-width:0"><div class="topic-name">'+esc(topic.topic)+'</div><div class="topic-alt">'+esc(topic.youtube_search_topic||topic.alternate_topics?.[0]||'Worldwide trend')+'</div></div></div></td><td><span class="pill">'+esc(topic.category||'General')+'</span></td><td>'+esc(source)+'</td><td class="score">'+score(topic)+'%</td><td>'+conv(topic)+'</td><td>'+esc(published[0])+'<br><small style="color:var(--muted)">'+esc(published[1])+'</small></td><td><div class="row-actions"><button class="action" data-i="'+topicIndex+'">View</button><button class="action video-action" data-i="'+topicIndex+'">Create video</button><button class="action pdf-action" data-i="'+topicIndex+'">PDF</button><button class="action more-action" data-i="'+topicIndex+'">•••</button></div></td></tr>'}).join('');
  $('#opportunities').innerHTML=shown.slice(0,5).map((topic,index)=>'<article class="opp"><div class="opp-media" style="background-image:linear-gradient(180deg,transparent,#060a14bb),url(\''+esc(finalAsset(topic,true,index))+'\')"><span class="rank">#'+(index+1)+'</span><span class="heat">'+esc(heat(topic))+'</span></div><div class="opp-body"><h3>'+esc(topic.topic)+'</h3><div class="opp-meta"><span>'+esc(topic.category||'General')+'</span><b style="color:var(--green)">'+score(topic)+'%</b></div><button class="action quick-insight" data-i="'+topics.indexOf(topic)+'">View insight</button></div></article>').join('');
  const stats=$$('.hero-stat strong');if(stats.length===3){stats[0].textContent=shown.reduce((sum,item)=>sum+(Number(item.mentions)||0),0).toLocaleString();stats[1].textContent=shown.length;stats[2].textContent=(shown.length?Math.max(...shown.map(score)):0)+'%'}
  renderCategoryChips();
}
$('#tableSearch').oninput=filterRender;$('#heroDiscover').onclick=()=>$('#runBtn').click();$('#heroBrowse').onclick=()=>document.querySelector('.opportunities').scrollIntoView({behavior:'smooth'});$('#filterBtn').onclick=()=>$('#category').focus();$('#columnsBtn').onclick=()=>toast('All approved columns are visible.');
$('#exportBtn').onclick=()=>{const rows=[['Topic','Category','Source','Viral score','Conversations','Published'],...topics.map(topic=>[topic.topic,topic.category||'General',topic.source_platforms?.[0]||topic.source||'',score(topic)+'%',conv(topic),topic.published_at||''])],blob=new Blob([rows.map(row=>row.map(value=>JSON.stringify(String(value??''))).join(',')).join('\n')],{type:'text/csv'}),link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download='viralizer-topics.csv';link.click()};
document.addEventListener('click',event=>{const button=event.target.closest('.video-action,.pdf-action,.more-action');if(!button)return;const topic=topics[Number(button.dataset.i)];if(!topic)return;if(button.classList.contains('video-action'))insight(topic);else if(button.classList.contains('pdf-action')){current=topic;pdf()}else toast('Open View to inspect the full topic report.')});

function setupExactHero(){
  const search=$('.topbar .search');
  if(search&&!search.querySelector('kbd'))search.insertAdjacentHTML('beforeend','<kbd>Ctrl K</kbd>');
  const headerAvatar=$('.top-actions .avatar');if(headerAvatar)headerAvatar.textContent='IN';
  const actions=$('.hero-actions');if(actions)actions.remove();
  const stats=$('.hero-stats');if(stats)stats.innerHTML='<div class="trend-card"><div class="trend-label">GLOBAL TRENDS<br><b>REAL OPPORTUNITIES</b></div><div class="trend-chart"><i style="height:25%"></i><i style="height:42%"></i><i style="height:32%"></i><i style="height:55%"></i><i style="height:46%"></i><i style="height:68%"></i><i style="height:51%"></i><i style="height:76%"></i><i style="height:61%"></i><i style="height:88%"></i><i style="height:72%"></i><i style="height:100%"></i></div><div class="trend-metrics"><span><strong>12.4M</strong><small>Topics Tracked</small></span><span><strong>240+</strong><small>Sources</small></span><span><strong>95%</strong><small>Trend Accuracy</small></span></div></div>';
  const tabs=$('.tabs');if(tabs)tabs.innerHTML='<button class="tab active" data-feed="viralizer"><i>★</i> Viralizer Topics</button><button class="tab" data-feed="hot"><i>🔥</i> Hot Topics</button><button class="tab" data-feed="topic-intelligence"><i>▥</i> Topic Intelligence</button><button class="tab" data-feed="idea-smith"><i>💡</i> Idea Smith</button><button class="tab" data-feed="saudi"><i>🌐</i> Saudi & Arabic Topics</button><button class="tab" data-feed="betting"><i>▣</i> Betting Topics</button>';
}
setupExactHero();

function topicList(value){
  if(Array.isArray(value))return value;
  if(!value||typeof value!=='object')return [];
  if(value.topic||value.title||value.name||value.idea)return [value];
  for(const key of ['topics','ideas','content','results','items']){const found=topicList(value[key]);if(found.length)return found}
  const nested=Object.values(value).filter(item=>item&&typeof item==='object');
  if(nested.some(item=>item.topic||item.title||item.name||item.idea))return nested;
  return Object.entries(value).filter(([key,item])=>typeof item==='string'&&/(idea|title|hook|topic)/i.test(key)).map(([,item])=>({topic:item}));
}
function normalizeFeed(payload,label){
  return topicList(payload).map((item,index)=>typeof item==='string'?{topic:item,category:label,source_platforms:[label]}:{...item,
    topic:item.topic||item.title||item.suggested_title||item.name||item.idea||`${label} topic ${index+1}`,
    category:item.category||item.section||label,
    source_platforms:item.source_platforms||[item.source||label],
    thumbnail_url:item.thumbnail_url||item.thumbnail||item.image_url||item.image||item.post_image,
    discovery_heat:item.discovery_heat||item.trend_status||item.heat||'HOT',
    viral_score:item.viral_score||item.score||item.resonance||(item.viralizer||{}).score,
    mentions:item.mentions||item.global_mentions||item.volume,
    published_at:item.published_at||item.created_at||item.event_date,
    youtube_search_topic:item.youtube_search_topic||item.search_topic||item.topic||item.title
  });
}
async function loadFeed(feed){
  const names={viralizer:'Viralizer Topics',hot:'Hot Topics','topic-intelligence':'Topic Intelligence','idea-smith':'Idea Smith',saudi:'Saudi & Arabic Topics',betting:'Betting Topics'},label=names[feed]||'Topics';
  $('#runStatus').textContent=`Loading ${label}…`;setFeedLoading(label,true);const advanced=$('#advancedTools');if(advanced)advanced.href=({viralizer:'/studio#viralizerView',hot:'/studio#hotView','topic-intelligence':'/studio#topicIntelligenceView','idea-smith':'/studio#ideaSmithView',saudi:'/studio#regionalView',betting:'/studio#bettingView'}[feed]||'/studio');
  try{
    let payload;const query=$('#keyword').value.trim();
    if(feed==='viralizer')payload=await(await api('/api/topics/hot')).json();
    else if(feed==='hot')payload=await(await api('/api/daily/latest')).json();
    else if(feed==='saudi')payload=await(await api('/api/regional/topics?query='+encodeURIComponent(query))).json();
    else if(feed==='betting')payload=await(await api('/api/betting/topics?query='+encodeURIComponent(query))).json();
    else if(feed==='idea-smith')payload=await(await api('/api/ideas/smith',{method:'POST',body:JSON.stringify({topic:query||'current trending content opportunities'})})).json();
    else payload=await(await api('/api/category/topics',{method:'POST',body:JSON.stringify({category:$('#category').value!=='ALL'?$('#category').value:'Technology',keyword:query,lens:'Everything',reputation:'All reputation'})})).json();
    const normalized=normalizeFeed(payload,label);render({topics:normalized,generated_at:payload.generated_at||new Date().toISOString()});
    $('#runStatus').textContent=`${normalized.length} ${label} ready`;toast(`${label} loaded.`);
  }catch(error){$('#runStatus').textContent=`Could not load ${label}`;toast(error.message,true)}finally{setFeedLoading('',false)}
}

function setFeedLoading(label,on){const box=$('#feedLoading');if(!box)return;box.hidden=!on;box.querySelector('strong').textContent=`Fetching ${label}…`;$('.opportunities')?.classList.toggle('is-fetching',on);$('.table-card')?.classList.toggle('is-fetching',on)}
function renderCategoryChips(){const holder=$('#feedCategoryChips');if(!holder)return;const current=$('#category').value,counts=topics.reduce((map,item)=>{const key=item.category||'General';map[key]=(map[key]||0)+1;return map},{});holder.innerHTML=['ALL',...Object.keys(counts).sort()].map(key=>`<button class="category-chip${current===key?' active':''}" data-category="${esc(key)}">${key==='ALL'?'All':esc(key)} <span>${key==='ALL'?topics.length:counts[key]}</span></button>`).join('');holder.hidden=!topics.length}

function setupExactSidebar(){
  const logo=$('.logo');
  if(logo)logo.innerHTML='<img src="/static/final/viralizer-logo-mark.svg" alt="Viralizer"><span class="brand-copy"><b>VIRALIZER</b><small>Video Studio</small></span>';
  const workspaceAvatar=$('.workspace .avatar');if(workspaceAvatar)workspaceAvatar.textContent='IN';
  const promo=$('.side-promo');
  if(promo)promo.innerHTML='<div class="impact-mark">◆</div><div><small>Turn ideas</small><strong>into impact.</strong><p>AI-powered video ideas<br>for every creator.</p></div>';
  const destinations={'Video Studio':'/studio#studio','Projects':'/studio#studio','Assets':'/studio#referenceAssetsPanel','History':'/studio#growthStudioPanel','Settings':'/admin'};
  $$('.side .nav a').forEach(link=>{const href=destinations[link.textContent.trim()];if(href)link.href=href});
  const tableTools=$('.table-tools');if(tableTools&&!$('#advancedTools'))tableTools.insertAdjacentHTML('afterbegin','<a class="advanced-tools" id="advancedTools" href="/studio#viralizerView">Full tools</a>');
}
setupExactSidebar();

const filtersRow=$('.filters');if(filtersRow&&!$('#feedCategoryChips'))filtersRow.insertAdjacentHTML('afterend','<div class="feed-loading" id="feedLoading" hidden><span class="feed-spinner"></span><div><strong>Fetching topics…</strong><small>Connecting to live sources and preparing the latest results.</small></div><i></i></div><div class="feed-category-chips" id="feedCategoryChips" hidden></div>');
document.addEventListener('click',event=>{const chip=event.target.closest('.category-chip');if(!chip)return;$('#category').value=chip.dataset.category;filterRender()},true);

const sideFeeds={'Discover':'viralizer','Topic Intelligence':'topic-intelligence','Idea Smith':'idea-smith'};
document.addEventListener('click',event=>{const link=event.target.closest('.side .nav a');if(!link)return;const feed=sideFeeds[link.textContent.trim()];if(!feed)return;event.preventDefault();event.stopImmediatePropagation();$$('.side .nav a').forEach(item=>item.classList.toggle('active',item===link));const tab=$(`.tab[data-feed="${feed}"]`);if(tab){$$('.tab').forEach(item=>item.classList.toggle('active',item===tab));tab.scrollIntoView({behavior:'smooth',block:'nearest',inline:'center'})}loadFeed(feed)},true);
