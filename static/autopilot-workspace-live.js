(() => {
  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => [...document.querySelectorAll(selector)];
  const state = { profile: null, accountProfile: {}, opportunities: [], topic: null, concepts: [], concept: null, workflow: null, asset: null, accounts: [], conversationId: '', current: 'today', inspirationMode: '', topicRefreshSeq: 0, productionRunning: false, keyframesApproved: false, imageTimer: null, imageStartedAt: 0, productionTimer: null, productionStartedAt: 0, topicLoadingTimer: null, onboardingType: 'business', onboardingStep: 0, creationMode: '', brandAnalysisDraft: {}, userPhotoId: '', userPhotoDirty: false, forceRegenerateKeyframes: false };

  async function api(url, options = {}) {
    const response = await fetch(url, { headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }, ...options });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = Array.isArray(payload.detail)
        ? payload.detail.map(item => item.msg || item.message || JSON.stringify(item)).join('; ')
        : (typeof payload.detail === 'object' && payload.detail ? JSON.stringify(payload.detail) : payload.detail);
      throw new Error(detail || payload.error || payload.message || `Request failed (${response.status})`);
    }
    return payload;
  }
  const esc = (value = '') => String(value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const list = (value = '') => String(value).split(/[,\n]/).map(item => item.trim()).filter(Boolean);
  const parse = value => { try { return typeof value === 'string' ? JSON.parse(value || '{}') : (value || {}); } catch { return {}; } };
  const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
  const userMenuToggle = $('#userMenuToggle'), userMenu = $('#userMenu');
  if (userMenuToggle && userMenu) {
    userMenuToggle.addEventListener('click', event => {
      event.stopPropagation();
      const opening = userMenu.hidden;
      userMenu.hidden = !opening;
      userMenuToggle.setAttribute('aria-expanded', String(opening));
    });
    document.addEventListener('click', event => {
      if (!userMenu.hidden && !userMenu.contains(event.target)) {
        userMenu.hidden = true;
        userMenuToggle.setAttribute('aria-expanded', 'false');
      }
    });
  }
  async function prepareUserPhoto() {
    if (!$('#useUserPhoto')?.checked) return '';
    if (state.userPhotoId) return state.userPhotoId;
    const file = $('#userPhotoInput')?.files?.[0];
    if (!file) throw new Error('Choose your avatar or portrait photo first.');
    const status = $('#userPhotoStatus'); status.textContent = 'Uploading private identity reference…';
    const form = new FormData(); form.append('photo', file); form.append('consent_confirmed', 'true');
    const response = await fetch('/api/autopilot/user-photos', { method: 'POST', body: form });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || `Photo upload failed (${response.status})`);
    state.userPhotoId = result.photo_id; status.textContent = `Ready · ${file.name} will guide all three scenes`;
    return state.userPhotoId;
  }
  function updatePhotoAction() {
    const button = $('#startRealProduction'); if (!button) return;
    if ($('#useUserPhoto')?.checked && state.userPhotoDirty) button.innerHTML = 'Regenerate all three with my photo <span>→</span>';
    else {
      const imagesReady = [0, 1, 2].every(index => currentKeyframe(index));
      button.innerHTML = imagesReady ? 'Review generated images <span>↓</span>' : 'Generate three keyframe images <span>→</span>';
    }
  }
  function toast(message) { const node = $('#toast'); node.textContent = message; node.classList.add('show'); clearTimeout(toast.timer); toast.timer = setTimeout(() => node.classList.remove('show'), 3800); }

  const screenContext = {
    today: ['Topic advisor', "Today's opportunities", ['Why is the first topic best?', 'Compare these opportunities']],
    create: ['Creative editor', 'Current storyboard', ['Make scene three stronger', 'Explain this creative direction']],
    produce: ['Production helper', 'Current production', ['What is happening now?', 'Why does video generation take time?']],
    approve: ['Approval guide', 'Exact publication', ['Check this caption', 'What exactly will be published?']],
    results: ['Growth analyst', 'Provider-reported results', ['What did we learn?', 'Recommend the next topic']],
    brand: ['Brand advisor', 'Confirmed brand profile', ['What do you know about my brand?', 'How does this affect my topics?']],
    connections: ['Connection guide', 'Provider connections', ['How do I connect Instagram?', 'What data does Viralizer store?']]
    ,projects: ['Project guide', 'Your projects', ['Open my active project', 'Start from a new topic']]
  };
  function showScreen(name, { historyMode = 'push' } = {}) {
    if (!screenContext[name]) name = 'today';
    state.current = name;
    $$('.screen').forEach(node => node.classList.toggle('active', node.id === `screen-${name}`));
    $$('#primaryNav [data-screen]').forEach(node => node.classList.toggle('active', node.dataset.screen === name));
    $$('.mobile-nav [data-screen]').forEach(node => node.classList.toggle('active', node.dataset.screen === name));
    const stages = ['today', 'create', 'produce', 'approve', 'results'];
    $$('#journey [data-screen]').forEach(node => {
      const currentIndex = stages.indexOf(name), nodeIndex = stages.indexOf(node.dataset.screen);
      node.classList.toggle('active', nodeIndex === currentIndex);
      node.classList.toggle('complete', nodeIndex >= 0 && currentIndex > nodeIndex);
    });
    const [label, context, prompts] = screenContext[name] || screenContext.today;
    $('#assistantContext').textContent = label;
    $('#contextChip b').textContent = context;
    $('#quickPrompts').innerHTML = prompts.map(prompt => `<button type="button">${esc(prompt)}</button>`).join('');
    $$('#quickPrompts button').forEach(button => button.onclick = () => sendAssistant(button.textContent));
    if (name === 'results') loadResults();
    if (name === 'projects') loadProjects();
    if (name === 'connections') loadConnections();
    if (name === 'approve' && state.asset) renderApproval(postFromAsset());
    if (name === 'produce' && state.asset && !state.productionRunning) renderRestoredProduction();
    if (historyMode !== 'none') {
      const url = new URL(location.href);
      const previous = url.searchParams.get('view');
      url.searchParams.set('view', name);
      if (historyMode === 'replace' || previous === name) history.replaceState({ view: name }, '', url);
      else history.pushState({ view: name }, '', url);
    }
  }

  const inspirationCopy = {
    upload: ['YOUR IMAGE', 'Transform a visual into a campaign.', 'Upload a JPG, PNG, or WebP. AI will analyze the real image before building the brief.'],
    url: ['SOURCE TO CONTENT', 'Turn a link into an original story.', 'Paste a public page and tell Viralizer what the content should achieve.'],
    business: ['BUSINESS CAMPAIGN', 'What should we promote?', 'Describe the product, service, offer, review, or customer outcome you want to feature.'],
    idea: ['ORIGINAL IDEA', 'Start with one thought.', 'A rough idea is enough. Viralizer will shape the hook, audience, and three creative directions.']
  };
  function openInspiration(mode) {
    if (mode === 'trend') {
      $('#trendOpportunitySection').scrollIntoView({ behavior: 'smooth', block: 'start' });
      if (!state.opportunities.length) refreshTopics(true);
      return;
    }
    state.inspirationMode = mode;
    const copy = inspirationCopy[mode] || inspirationCopy.idea;
    $('#inspirationEyebrow').textContent = copy[0]; $('#inspirationTitle').textContent = copy[1]; $('#inspirationHelp').textContent = copy[2];
    $('#inspirationUrlWrap').hidden = mode !== 'url'; $('#inspirationFileWrap').hidden = mode !== 'upload';
    $('#inspirationPrompt').placeholder = mode === 'business' ? 'Example: Promote our weekend family brunch to local parents with a warm, premium 15-second Reel.' : 'Example: Create a 15-second Instagram video with a strong opening and practical call to action.';
    $('#inspirationComposer').hidden = false;
    $('#inspirationComposer').scrollIntoView({ behavior: 'smooth', block: 'center' });
    setTimeout(() => (mode === 'url' ? $('#inspirationUrl') : $('#inspirationPrompt')).focus(), 350);
  }
  function closeInspiration() { $('#inspirationComposer').hidden = true; state.inspirationMode = ''; }
  async function continueInspiration() {
    const mode = state.inspirationMode || 'idea', prompt = $('#inspirationPrompt').value.trim();
    const url = $('#inspirationUrl').value.trim(), file = $('#inspirationFile').files?.[0];
    if (!prompt) return toast('Tell Viralizer what this content should achieve.');
    if (mode === 'url' && !/^https:\/\//i.test(url)) return toast('Paste a complete public HTTPS URL.');
    if (mode === 'upload' && !file) return toast('Choose a JPG, PNG, or WebP image first.');
    const button = $('#continueInspiration'); button.disabled = true; button.innerHTML = 'Building opportunity <b>✦</b>';
    try {
      state.topicRefreshSeq += 1;
      let groundedTitle = prompt, sourceUrl = url, sourceLabel = mode === 'url' ? url : (mode === 'upload' ? file.name : mode === 'business' ? 'Business brief' : 'Original idea');
      let sourceEvidence = '';
      if (mode === 'url') {
        button.innerHTML = 'Reading source <b>✦</b>';
        const analyzed = await api('/api/site-url/analyze', { method: 'POST', body: JSON.stringify({ url, duration: 15, aspect_ratio: '9:16' }) });
        const content = analyzed.content || {};
        sourceUrl = content.source_url || analyzed.source_url || url;
        sourceLabel = content.source_site || analyzed.site_name || sourceLabel;
        sourceEvidence = content.summary || content.why_it_matters || '';
        groundedTitle = `${content.topic || content.suggested_title || 'Source story'} — ${prompt}`;
      } else if (mode === 'upload') {
        button.innerHTML = 'Analyzing image <b>✦</b>';
        const form = new FormData();
        form.append('content_json', JSON.stringify({ topic: prompt, video_idea: prompt }));
        form.append('use_topic_context', 'true'); form.append('duration', '15'); form.append('image', file);
        const response = await fetch('/api/thumbnail/prompts', { method: 'POST', body: form });
        const analyzed = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(analyzed.detail || `Image analysis failed (${response.status})`);
        sourceEvidence = analyzed.analysis || '';
        groundedTitle = `${prompt} — Visual reference: ${sourceEvidence}`;
      }
      button.innerHTML = 'Matching your brand <b>✦</b>';
      const result = await api('/api/autopilot/opportunities/rank', { method: 'POST', body: JSON.stringify({ topics: [{
        topic: groundedTitle.slice(0, 480), title: groundedTitle.slice(0, 280), summary: sourceEvidence.slice(0, 1000), why_it_matters: prompt,
        category: mode === 'business' ? 'Business campaign' : mode === 'url' ? 'Source transformation' : mode === 'upload' ? 'Visual inspiration' : 'Original concept',
        source_type: mode, source_url: sourceUrl, source_name: sourceLabel, reference_description: sourceEvidence, user_directed: true
      }], limit: 1 }) });
      state.opportunities = result.opportunities || [];
      if (!state.opportunities.length) throw new Error('This brief could not be matched to your confirmed profile. Add a specific subject, audience, or product and try again.');
      stopTopicLoading(); renderTopics(); closeInspiration();
      $('#trendOpportunitySection').scrollIntoView({ behavior: 'smooth', block: 'start' });
      toast('Your opportunity is ready. Review it and choose Create.');
    } catch (error) { toast(error.message); }
    finally { button.disabled = false; button.innerHTML = 'Create opportunity <b>→</b>'; }
  }

  async function loadProjects() {
    const gallery = $('#projectGallery');
    if (!gallery) return;
    gallery.innerHTML = '<article><div><b>Loading your projects…</b><small>Checking saved videos and publication history.</small></div></article>';
    try {
      const projects = (await api('/api/autopilot/projects')).projects || [];
      if (!projects.length) {
        gallery.innerHTML = '<article><div><b>No saved videos yet</b><small>Select a topic to create your first project.</small><button class="secondary" data-go="today">Choose a topic →</button></div></article>';
      } else {
        gallery.innerHTML = projects.map(project => {
          const label = project.is_published ? 'Published on social' : (project.provider_submitted ? 'Submitted · social post not confirmed' : 'Not published');
          const media = project.media_url ? `<video class="project-video" src="${esc(project.media_url)}" preload="metadata" controls playsinline></video>` : '<div class="project-thumb"><span>VIDEO</span></div>';
          const action = project.is_published
            ? `<button class="secondary" type="button" data-project-results="${esc(project.asset_id)}">View publishing results →</button>`
            : `<button class="primary" type="button" data-publish-project="${esc(project.asset_id)}" data-concept-id="${esc(project.concept_id)}" data-workflow-id="${esc(project.workflow_run_id)}">${project.provider_submitted ? 'Retry publishing' : 'Publish this video'} →</button>`;
          return `<article>${media}<div><b>${esc(project.title || project.opportunity_title || 'Untitled video')}</b><small>${esc(label)} · Version ${esc(project.version || 1)}</small>${action}</div></article>`;
        }).join('');
        $$('[data-project-results]').forEach(button => button.onclick = () => showScreen('results'));
        $$('[data-publish-project]').forEach(button => button.onclick = async () => {
          const original = button.textContent; button.disabled = true; button.textContent = 'Preparing approval…';
          try {
            const prepared = await api(`/api/autopilot/projects/${encodeURIComponent(button.dataset.publishProject)}/prepare-publication`, { method: 'POST' });
            state.asset = prepared.asset;
            state.workflow = { id: button.dataset.workflowId };
            state.concept = { id: button.dataset.conceptId };
            state.topic = { title: prepared.asset.title || 'Saved video' };
            await renderApproval(postFromAsset()); showScreen('approve');
            toast('Review and approve this exact video before publishing.');
          } catch (error) { button.disabled = false; button.textContent = original; toast(error.message); }
        });
      }
      $$('[data-go]', gallery).forEach(button => button.onclick = () => showScreen(button.dataset.go));
    } catch (error) {
      gallery.innerHTML = `<article><div><b>Projects could not be loaded</b><small>${esc(error.message)}</small><button class="secondary" type="button" id="retryProjects">Retry</button></div></article>`;
      $('#retryProjects').onclick = loadProjects;
    }
  }

  function profileData() { return state.profile?.profile || state.profile || {}; }
  function renderBrand() {
    const profile = profileData();
    const rows = [
      ['Audience', (profile.audiences || []).join(', ') || 'Not confirmed'],
      ['Offer', (profile.products_services || []).join(', ') || profile.positioning || 'Not confirmed'],
      ['Voice', (profile.voice || []).join(', ') || 'Not confirmed'],
      ['Goal', (profile.goals || []).join(', ') || 'Not confirmed'],
      ['Keywords', (profile.keywords || []).join(', ') || 'Learned from confirmed sources'],
      ['Visual style', (profile.visual_style || []).join(', ') || 'Cinematic realism']
    ];
    $('#brandGrid').innerHTML = rows.map(([label, value]) => `<article><small>${esc(label)}</small><b>${esc(value)}</b></article>`).join('');
    const audiences = (profile.audiences || []).slice(0, 2).join(' + ');
    $('.sidebar-bottom small').textContent = audiences || 'Personal workspace';
  }

  const onboardingQuestions = [
    { field: 'onboardName', prompt: 'What should I call you?' },
    { field: 'onboardWebsite', prompt: 'Share your main website or public profile. I’ll use real public evidence to understand your brand.' },
    { field: 'onboardSocial', prompt: 'Add one social profile too, or type “skip”. It is optional.' }
  ];
  function addOnboardingMessage(text, role = 'ai') {
    const host = $('#onboardingMessages');
    const message = document.createElement('div'); message.className = `onboarding-message ${role}`;
    message.innerHTML = role === 'ai' ? `<b>Viralizer</b><p>${esc(text)}</p>` : `<p>${esc(text)}</p>`;
    host.appendChild(message); host.scrollTop = host.scrollHeight;
  }
  function updateOnboardingReadiness() {
    const required = ['onboardName', 'onboardWebsite', 'onboardOffer', 'onboardAudience'];
    const filled = required.filter(id => $(`#${id}`).value.trim()).length;
    const confirmed = $('#confirmOnboarding').checked;
    const score = Math.min(100, 20 + filled * 15 + (state.brandAnalysisDraft.confidence ? 10 : 0) + (confirmed ? 10 : 0));
    $('#onboardingReadiness').textContent = `${score}%`;
    $('#onboardingCreationModes').hidden = !confirmed;
    const ready = confirmed && Boolean(state.creationMode) && filled === required.length;
    $('#finishWorkspaceOnboarding').disabled = !ready;
    $('#finishWorkspaceOnboarding').textContent = ready ? `Continue with ${creationModeLabel(state.creationMode)} →` : confirmed ? 'Choose how you want to create' : 'Confirm profile to continue';
  }
  function creationModeLabel(mode) { return ({ quick: 'Quick Create', guided: 'Guided Create', advanced: 'Advanced Studio' })[mode] || 'Viralizer'; }
  function showOnboarding() {
    const profile = profileData();
    state.onboardingType = state.profile?.customer_type || 'business'; state.creationMode = '';
    $('#onboardingMessages').innerHTML = '<div class="onboarding-message ai"><b>Viralizer</b><p>Welcome. I only need the essentials to personalize your content.</p></div>';
    $$('[data-customer-type]').forEach(button => button.classList.toggle('selected', button.dataset.customerType === state.onboardingType));
    $('#onboardName').value = state.accountProfile.name || state.profile?.brand_name || '';
    $('#onboardEmail').value = state.accountProfile.email || '';
    $('#onboardWebsite').value = state.profile?.website_url || profile.website_url || '';
    $('#onboardSocial').value = (state.profile?.social_urls || profile.social_urls || [])[0] || '';
    $('#onboardOffer').value = (profile.products_services || []).join(', ') || profile.positioning || '';
    $('#onboardAudience').value = (profile.audiences || []).join(', ');
    $('#onboardVoice').value = (profile.voice || []).join(', ');
    $('#onboardGoal').value = (profile.goals || [])[0] || 'Grow audience';
    $('#confirmOnboarding').checked = false; $('#onboardingCreationModes').hidden = true;
    state.onboardingStep = $('#onboardName').value ? 1 : 0;
    addOnboardingMessage(onboardingQuestions[state.onboardingStep]?.prompt || 'Review your profile, then analyze the public brand source.');
    updateOnboardingReadiness(); $('#workspaceOnboarding').hidden = false;
  }
  async function analyzeBrand() {
    const button = $('#analyzeOnboardBrand'), status = $('#onboardingStatus');
    button.disabled = true; status.textContent = 'Analyzing public brand evidence…';
    try {
      const website = $('#onboardWebsite').value.trim();
      if (!website) throw new Error('Add a public website or profile first.');
      const social = $('#onboardSocial').value.trim();
      const data = await api('/api/autopilot/brand-profile/analyze', { method: 'POST', body: JSON.stringify({ website_url: website, social_urls: social ? [social] : [] }) });
      const draft = data.draft || {};
      state.brandAnalysisDraft = draft;
      if (draft.positioning) $('#onboardOffer').value = draft.positioning;
      if (draft.voice?.length) $('#onboardVoice').value = draft.voice.join(', ');
      if (draft.audiences?.length) $('#onboardAudience').value = draft.audiences.join(', ');
      else if (draft.areas_of_interest?.length && !$('#onboardAudience').value) $('#onboardAudience').value = draft.areas_of_interest.join(', ');
      if (draft.identity_type === 'creator') {
        state.onboardingType = 'creator';
        $$('[data-customer-type]').forEach(item => item.classList.toggle('selected', item.dataset.customerType === 'creator'));
      }
      const analyzed = (data.sources || []).filter(source => source.status === 'analyzed').length;
      const identity = [draft.brand_name, draft.category].filter(Boolean).join(' · ');
      const themes = (draft.content_themes || []).slice(0, 5).join(', ');
      status.textContent = analyzed
        ? `Found ${identity || 'public brand'} from ${analyzed} public source${analyzed === 1 ? '' : 's'}. ${themes ? `Content themes: ${themes}. ` : ''}Confidence: ${draft.confidence || 'medium'}. Review and confirm.`
        : `This profile could not be read publicly. Connect the social account or enter the brand details manually.`;
      addOnboardingMessage(status.textContent); updateOnboardingReadiness();
    } catch (error) { status.textContent = error.message; }
    finally { button.disabled = false; }
  }
  async function finishOnboarding() {
    const button = $('#finishWorkspaceOnboarding'), status = $('#onboardingStatus');
    button.disabled = true; button.textContent = 'Personalizing opportunities…';
    try {
      if (!$('#onboardOffer').value.trim() || !$('#onboardAudience').value.trim()) throw new Error('Add what you offer and who you want to reach.');
      const data = await api('/api/autopilot/brand-profile', { method: 'PUT', body: JSON.stringify({
        customer_type: state.onboardingType, brand_name: state.brandAnalysisDraft.brand_name || $('#onboardName').value.trim(), category: state.brandAnalysisDraft.category || '', website_url: $('#onboardWebsite').value.trim(), social_urls: $('#onboardSocial').value.trim() ? [$('#onboardSocial').value.trim()] : [],
        voice: list($('#onboardVoice').value), positioning: $('#onboardOffer').value.trim(),
        audiences: list($('#onboardAudience').value), goals: [$('#onboardGoal').value],
        products_services: list($('#onboardOffer').value), keywords: state.brandAnalysisDraft.keywords || [], hashtags: state.brandAnalysisDraft.hashtags || [], content_themes: state.brandAnalysisDraft.content_themes || [], recent_content: state.brandAnalysisDraft.recent_content || [], analysis_confidence: state.brandAnalysisDraft.confidence || '', competitor_urls: [], inspiration_urls: [], inspiration_notes: '',
        visual_style: ['cinematic', 'realistic'], constraints: ['Never publish without exact-content approval.'], confirmed: true
      }) });
      state.profile = data.brand_profile; localStorage.setItem('viralizer_creation_mode', state.creationMode);
      renderBrand(); $('#workspaceOnboarding').hidden = true;
      const cleanUrl = new URL(location.href); cleanUrl.searchParams.delete('onboarding'); cleanUrl.searchParams.set('view', 'today');
      history.replaceState({ view: 'today' }, '', cleanUrl);
      await refreshTopics(true);
      if (state.creationMode === 'quick' && state.opportunities[0]) {
        toast('Quick Create is preparing your strongest opportunity.');
        await selectTopic(state.opportunities[0].id);
      } else {
        showScreen('today');
        if (state.creationMode === 'guided') { $('#assistantDrawer').classList.add('open'); $('#assistantMessages').insertAdjacentHTML('beforeend', '<div class="ai-message"><span>✦</span><p>Your profile is ready. Choose an opportunity and I’ll guide each important decision.</p></div>'); }
        toast(state.creationMode === 'advanced' ? 'Advanced Studio is ready. Choose a topic to use the full controls.' : 'Your guided workspace is ready.');
      }
    } catch (error) { status.textContent = error.message; button.disabled = false; updateOnboardingReadiness(); }
  }

  function scoreFor(item) { return Math.round(Number(item.score ?? item.viral_score ?? item.source?.viral_rank ?? 0)); }
  function viralRankFor(item) {
    const value = item.source?.viral_rank ?? item.source?.viral_score ?? item.viral_rank;
    const number = Number(String(value ?? '').replace(/[^0-9.]/g, ''));
    return Number.isFinite(number) && String(value ?? '').trim() ? Math.round(number) : null;
  }
  function topicFallbackImage(topic) {
    const value = `${topic.category || ''} ${topic.title || ''}`.toLowerCase();
    const categories = [
      ['food', /food|cook|kitchen|restaurant|recipe|meal|cuisine/],
      ['ai', /\bai\b|artificial intelligence|anthropic|openai|machine learning|robot/],
      ['finance', /finance|stock|dividend|bank|invest|market|sales|money/],
      ['technology', /tech|software|app|device|digital|startup|internet/],
      ['business', /business|founder|company|entrepreneur|workplace|employee/],
      ['health', /health|fitness|wellness|medical/],
      ['travel', /travel|tourism|hotel|flight|destination/],
      ['fashion', /fashion|style|clothing|beauty/],
      ['entertainment', /music|film|movie|celebrity|entertainment/],
      ['sports', /sport|football|cricket|basketball|game/],
      ['education', /education|school|student|learning/],
      ['home', /home|interior|house|decor|garden/]
    ];
    const match = categories.find(([, pattern]) => pattern.test(value));
    return `/static/category-images/${match ? match[0] : 'realtime'}.webp`;
  }
  function renderTopics() {
    const host = $('#topicGrid');
    if (!state.opportunities.length) { host.innerHTML = '<div class="empty-opportunities"><span>✦</span><div><b>No verified trend matches your brand right now.</b><p>Viralizer rejected unrelated topics instead of filling your feed with noise. Start from your idea, image, URL, or business above—or refresh later.</p></div><button type="button" data-empty-idea>Start with an idea →</button></div>'; $('[data-empty-idea]').onclick = () => openInspiration('idea'); return; }
    host.innerHTML = state.opportunities.map((topic, index) => {
      const score = scoreFor(topic), viralRank = viralRankFor(topic), why = topic.reason || topic.explanation || topic.brand_match_reason || 'Matched against your confirmed audience, offer, and goal.', image = topic.source?.image || topic.source?.thumbnail_url || topic.image || topic.thumbnail_url || topicFallbackImage(topic);
      return `<article class="topic-card ${index === 0 ? 'recommended' : ''}" data-topic="${esc(topic.id)}"><div class="topic-image"><img src="${esc(image)}" alt="${esc(topic.title)}" loading="lazy"><b>${score || '—'}</b><span>${index === 0 ? 'BEST MATCH' : esc(topic.category || 'OPPORTUNITY')}</span></div><h2>${esc(topic.title)}</h2><p>${esc(why)}</p><div class="topic-footer"><span>Viral Rank: ${viralRank ?? 'not available'}</span><button>Select topic →</button></div></article>`;
    }).join('');
    $$('[data-topic]').forEach(card => card.onclick = () => selectTopic(card.dataset.topic));
    const best = state.opportunities[0];
    $('#briefTitle').textContent = `${best.title} is your strongest current opportunity`;
    $('#briefCopy').textContent = 'Ranked from Viralizer topic evidence and your confirmed brand profile—not a random worldwide feed.';
  }
  function startTopicLoading(force) {
    clearInterval(state.topicLoadingTimer);
    const stages = ['Reading your confirmed brand profile', 'Fetching worldwide hot topics from Viralizer MCP', 'Matching topics to your audience and content themes', 'Verifying Viral Rank evidence', 'Preparing your best opportunities'];
    let elapsed = 0, stage = 0;
    $('#topicGrid').innerHTML = `<div class="topic-discovery-loader"><div class="discovery-orbit"><i></i><i></i><i></i><b>V.</b></div><div><span>AI TOPIC DISCOVERY</span><h2>${force ? 'Finding fresh opportunities for your brand' : 'Loading your opportunities'}</h2><p id="topicLoadingStage">${stages[0]}</p><strong id="topicLoadingTime">0s elapsed</strong><div class="discovery-progress"><i></i></div><small>Real MCP analysis may take a few moments. You can leave this screen open.</small></div></div>`;
    state.topicLoadingTimer = setInterval(() => {
      elapsed += 1;
      if (elapsed % 3 === 0 && stage < stages.length - 1) stage += 1;
      const stageNode = $('#topicLoadingStage'), timeNode = $('#topicLoadingTime');
      if (stageNode) stageNode.textContent = stages[stage];
      if (timeNode) timeNode.textContent = `${elapsed}s elapsed`;
    }, 1000);
  }
  function stopTopicLoading() { clearInterval(state.topicLoadingTimer); state.topicLoadingTimer = null; }
  async function refreshTopics(force = false) {
    const requestSeq = ++state.topicRefreshSeq;
    $('#briefTitle').textContent = force ? 'Matching worldwide trends to your brand…' : 'Loading saved opportunities…';
    startTopicLoading(force);
    try {
      let data = await api('/api/autopilot/opportunities?limit=5');
      if (force || !(data.opportunities || []).length) data = await api('/api/autopilot/topics/refresh', { method: 'POST' });
      if (requestSeq !== state.topicRefreshSeq) return;
      state.opportunities = data.opportunities || [];
      stopTopicLoading();
      renderTopics();
      if (!state.opportunities.length && data.message) $('#briefTitle').textContent = data.message;
      if (data.source) {
        $('#briefCopy').textContent = data.source.includes('MCP temporarily unavailable')
          ? 'Showing real worldwide public trend evidence while the Viralizer MCP account mapping is repaired. Unverified Viral Rank is shown as unavailable.'
          : 'Ranked from Viralizer topic evidence and your confirmed brand profile—not a random worldwide feed.';
      }
    } catch (error) { if (requestSeq === state.topicRefreshSeq) { stopTopicLoading(); $('#topicGrid').innerHTML = `<div class="production-error">${esc(error.message)}</div>`; } }
  }

  function sceneItems() {
    const content = state.concept?.content || {};
    const storyboard = content.storyboard || content.scenes || [];
    if (storyboard.length) return storyboard.slice(0, 3);
    return [
      { title: 'Hook', visual: content.hook, copy: content.hook },
      { title: 'Value', visual: content.narrative, copy: content.narrative },
      { title: 'Action', visual: content.cta, copy: content.cta }
    ];
  }
  function currentKeyframe(sceneIndex) {
    const keyframes = state.concept?.content?.keyframes || state.concept?.keyframes || {};
    if (Array.isArray(keyframes)) return keyframes.filter(frame => Number(frame.scene_index) === sceneIndex).sort((a, b) => Number(b.version || 0) - Number(a.version || 0))[0];
    const versions = keyframes[String(sceneIndex)] || [];
    return versions[versions.length - 1];
  }
  function renderConcept() {
    const content = state.concept?.content || {};
    $('#projectName').textContent = state.topic?.title || 'Growth cycle';
    const projectCardTitle = $('#projectCardTitle'); if (projectCardTitle) projectCardTitle.textContent = state.topic?.title || 'Current growth cycle';
    $('#createTitle').textContent = state.topic?.title || 'Your video is taking shape.';
    $('.concept-strip h2').textContent = state.concept?.name || content.hook || 'Recommended creative direction';
    $('#conceptReason').textContent = state.concept?.rationale || content.narrative || 'A practical 15-second story built for your audience.';
    $('#storyboard').innerHTML = sceneItems().map((scene, index) => {
      const frame = currentKeyframe(index), image = frame?.image_url || frame?.url || '';
      return `<article class="scene-card" data-scene="${index}"><div class="scene-number">${index + 1}</div><div class="scene-visual ${image ? 'has-image' : ''}">${image ? `<img src="${esc(image)}" alt="Scene ${index + 1} keyframe">` : ''}<span>${esc(scene.title || `Scene ${index + 1}`)}</span><strong>${esc(scene.visual || scene.image_prompt || scene.description || '')}</strong></div><div class="scene-copy"><small>${index * 5}–${index * 5 + 5} SEC</small><b>${esc(scene.copy || scene.voiceover || scene.text || '')}</b><span class="scene-status">${frame ? 'Real keyframe ready' : 'Keyframe will be created after cost confirmation'}</span></div></article>`;
    }).join('');
    $('#createBadge').textContent = '1';
    const imagesReady = [0, 1, 2].every(index => currentKeyframe(index));
    updatePhotoAction();
    if (imagesReady) renderProductionKeyframes();
  }
  async function selectTopic(id) {
    const card = $(`[data-topic="${CSS.escape(id)}"]`); if (card) card.classList.add('loading');
    try {
      state.topic = state.opportunities.find(item => String(item.id) === String(id));
      let data = await api(`/api/autopilot/opportunities/${encodeURIComponent(id)}/concepts`);
      if (!(data.concepts || []).length) data = await api('/api/autopilot/concepts/generate', { method: 'POST', body: JSON.stringify({ opportunity_id: id, platform: 'instagram', goal: (profileData().goals || [])[0] || 'Grow audience' }) });
      state.concepts = data.concepts || []; state.concept = state.concepts[0];
      if (!state.concept) throw new Error('The Creative Director did not return a concept.');
      renderConcept(); showScreen('create');
    } catch (error) { toast(error.message); }
    finally { if (card) card.classList.remove('loading'); }
  }

  function updateProgress(percent, title, copy, scene = 1) {
    $('#progressBar').style.width = `${percent}%`; $('#productionTitle').textContent = title; $('#progressCopy').textContent = copy; $('#productionScene').textContent = scene;
    $$('#productionSceneStrip span').forEach((item, index) => { item.classList.toggle('active', index === scene - 1); item.classList.toggle('done', index < scene - 1); });
  }
  function formatElapsed(seconds) { const minutes = Math.floor(seconds / 60), remainder = seconds % 60; return `${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`; }
  function startProductionTimer() {
    if (!state.productionStartedAt) state.productionStartedAt = Date.now();
    clearInterval(state.productionTimer);
    const paint = () => { $('#productionElapsed').textContent = formatElapsed(Math.floor((Date.now() - state.productionStartedAt) / 1000)); };
    paint(); state.productionTimer = setInterval(paint, 1000);
  }
  function stopProductionTimer() { clearInterval(state.productionTimer); state.productionTimer = null; }
  function renderRestoredProduction() {
    const video = state.asset?.media_url || state.asset?.video_url || state.asset?.url || '';
    if (!video) return;
    $('#productionVisual').innerHTML = `<video controls playsinline preload="metadata" src="${esc(video)}" aria-label="Saved final video"></video>`;
    updateProgress(100, 'Your real video is ready', 'Saved final video restored · review the exact asset before publishing', 3);
    markTask('#taskOne', 'complete', 'Approved'); markTask('#taskTwo', 'complete', 'Complete'); markTask('#taskThree', 'complete', 'Complete');
  }
  function startImageTimer() {
    clearInterval(state.imageTimer); state.imageStartedAt = Date.now(); $('#imageGenerationStatus').hidden = false; $('#imageGenerationBar').style.width = '5%'; $('#imageElapsed').textContent = '00:00';
    state.imageTimer = setInterval(() => { $('#imageElapsed').textContent = formatElapsed(Math.floor((Date.now() - state.imageStartedAt) / 1000)); }, 1000);
    $('#imageGenerationStatus').scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
  function updateImageTimer(scene, phase = 'creating') {
    const percent = Math.min(95, 8 + scene * 29); $('#imageGenerationBar').style.width = `${percent}%`; $('#imageGenerationTitle').textContent = phase === 'complete' ? 'All three images are ready' : `Creating keyframe ${scene + 1} of 3`; $('#imageGenerationCopy').textContent = phase === 'complete' ? 'Opening the image review workspace…' : `OpenAI is generating Scene ${scene + 1}. Typical time per image is 20–60 seconds.`;
  }
  function stopImageTimer(success = true) {
    clearInterval(state.imageTimer); state.imageTimer = null; $('#imageGenerationBar').style.width = success ? '100%' : '0%'; if (success) updateImageTimer(2, 'complete');
    setTimeout(() => { $('#imageGenerationStatus').hidden = true; }, success ? 900 : 0);
  }
  function markTask(id, status, text) { const node = $(id).closest('div'); node.classList.remove('active', 'complete', 'failed'); node.classList.add(status); $(id).textContent = text; }
  function showProductionError(error) {
    let node = $('.production-error', $('#screen-produce'));
    if (!node) { node = document.createElement('div'); node.className = 'production-error'; $('.production-status').append(node); }
    node.textContent = error.message || String(error);
  }
  async function reloadConcept() {
    const data = await api(`/api/autopilot/opportunities/${encodeURIComponent(state.topic.id)}/concepts`);
    state.concepts = data.concepts || state.concepts;
    state.concept = state.concepts.find(item => String(item.id) === String(state.concept.id)) || state.concepts[0];
  }
  function renderProductionKeyframes() {
    $('#productionKeyframes').innerHTML = [0, 1, 2].map(scene => {
      const frame = currentKeyframe(scene), image = frame?.image_url || frame?.url || '';
      return `<article class="production-keyframe"><a href="${esc(image)}" target="_blank" aria-label="Open scene ${scene + 1} image full size"><img src="${esc(image)}" alt="Generated keyframe for scene ${scene + 1}"></a><div class="production-keyframe-body"><b>Scene ${scene + 1} · ${scene * 5}–${scene * 5 + 5} sec</b><input data-keyframe-direction="${scene}" placeholder="Describe what you want changed"><div class="production-keyframe-actions"><button type="button" data-regenerate-keyframe="${scene}">Regenerate scene</button><a href="${esc(image)}" target="_blank">View full image</a></div><small class="scene-status" data-keyframe-status="${scene}">Real OpenAI keyframe</small></div></article>`;
    }).join('');
    $$('[data-regenerate-keyframe]').forEach(button => button.onclick = () => regenerateKeyframe(Number(button.dataset.regenerateKeyframe)));
    $('#keyframeReview').hidden = false;
  }
  async function regenerateKeyframe(scene) {
    const button = $(`[data-regenerate-keyframe="${scene}"]`), status = $(`[data-keyframe-status="${scene}"]`), direction = $(`[data-keyframe-direction="${scene}"]`).value.trim();
    if (!direction && !$('#useUserPhoto')?.checked) return toast('Describe the change you want for this scene.');
    button.disabled = true; status.textContent = 'Regenerating with your direction…';
    try {
      startImageTimer(); updateImageTimer(scene);
      const user_photo_id = await prepareUserPhoto();
      await api(`/api/autopilot/concepts/${encodeURIComponent(state.concept.id)}/keyframes/generate`, { method: 'POST', body: JSON.stringify({ scene_index: scene, preserve_identity: true, user_photo_id, user_direction: direction, avoid: '' }) });
      state.keyframesApproved = false; state.userPhotoDirty = false; await reloadConcept(); renderProductionKeyframes(); updatePhotoAction(); stopImageTimer(true); toast(`Scene ${scene + 1} regenerated. Review it before animation.`);
    } catch (error) { if (state.imageTimer) stopImageTimer(false); status.textContent = error.message; button.disabled = false; }
  }
  async function runProduction() {
    if (state.productionRunning) return;
    state.productionRunning = true; showScreen(state.keyframesApproved ? 'produce' : 'create'); $('.production-error')?.remove();
    $('#resumeProduction').disabled = true;
    try {
      if (!state.workflow) state.workflow = (await api(`/api/autopilot/workflows/start/${encodeURIComponent(state.concept.id)}`, { method: 'POST' })).workflow;
      await reloadConcept();
      const forceRegeneration = state.forceRegenerateKeyframes;
      const needsImages = forceRegeneration || [0, 1, 2].some(index => !currentKeyframe(index));
      if (needsImages && !state.keyframesApproved) startImageTimer();
      markTask('#taskOne', 'active', 'In progress');
      const user_photo_id = await prepareUserPhoto();
      for (let scene = 0; scene < 3; scene++) {
        let frame = forceRegeneration ? null : currentKeyframe(scene);
        if (!frame) updateImageTimer(scene);
        updateProgress(5 + scene * 10, 'Creating three visual scenes', `Scene ${scene + 1} of 3 · Creating the approved image`, scene + 1);
        if (!frame) frame = (await api(`/api/autopilot/concepts/${encodeURIComponent(state.concept.id)}/keyframes/generate`, { method: 'POST', body: JSON.stringify({ scene_index: scene, preserve_identity: true, user_photo_id, user_direction: '', avoid: '' }) })).keyframe;
        const image = frame?.image_url || frame?.url;
        if (image) $('#productionVisual').innerHTML = `<img src="${esc(image)}" alt="Generated scene ${scene + 1}">`;
        await reloadConcept();
      }
      markTask('#taskOne', 'complete', 'Ready for review');
      if (forceRegeneration) { state.forceRegenerateKeyframes = false; state.userPhotoDirty = false; updatePhotoAction(); }
      if (!state.keyframesApproved) {
        updateProgress(35, 'Images ready for review', 'Edit or regenerate any scene in Create before PixVerse animation', 3);
        renderProductionKeyframes();
        if (needsImages) stopImageTimer(true);
        $('#keyframeReview').scrollIntoView({ behavior: 'smooth', block: 'start' });
        return;
      }
      startProductionTimer();
      $('#keyframeReview').hidden = true; markTask('#taskOne', 'complete', 'Approved'); markTask('#taskTwo', 'active', 'In progress');
      for (let scene = 0; scene < 3; scene++) {
        updateProgress(40 + scene * 16, 'Animating scenes with PixVerse', `Scene ${scene + 1} of 3 · Image-to-video generation`, scene + 1);
        let status;
        try { status = await api(`/api/autopilot/concepts/${encodeURIComponent(state.concept.id)}/animations/${scene}/status`); } catch { status = {}; }
        if (status.status !== 'complete') {
          if (!['queued', 'processing'].includes(status.status)) await api(`/api/autopilot/concepts/${encodeURIComponent(state.concept.id)}/keyframes/animate`, { method: 'POST', body: JSON.stringify({ scene_index: scene }) });
          for (let attempt = 0; attempt < 72; attempt++) {
            if (attempt) await delay(5000);
            status = await api(`/api/autopilot/concepts/${encodeURIComponent(state.concept.id)}/animations/${scene}/status`);
            $('#progressCopy').textContent = `Scene ${scene + 1} of 3 · PixVerse ${status.status || 'processing'} · ${attempt * 5}s elapsed`;
            if (status.status === 'complete') break;
            if (status.status === 'failed') throw new Error(status.error || `Scene ${scene + 1} animation failed.`);
          }
          if (status.status !== 'complete') throw new Error(`Scene ${scene + 1} is still processing. Resume production to check it again.`);
        }
      }
      markTask('#taskTwo', 'complete', 'Complete'); markTask('#taskThree', 'active', 'Assembling'); updateProgress(92, 'Assembling final video', 'Combining the three approved five-second scenes', 3);
      const content = state.concept.content || {}, post = {
        workflow_run_id: state.workflow.id, concept_id: state.concept.id,
        title: state.topic.title, caption: [content.narrative, content.cta].filter(Boolean).join('\n\n'),
        hashtags: (profileData().hashtags || []).length ? profileData().hashtags : ['#Viralizer']
      };
      state.asset = (await api(`/api/autopilot/concepts/${encodeURIComponent(state.concept.id)}/finalize`, { method: 'POST', body: JSON.stringify(post) })).asset;
      markTask('#taskThree', 'complete', 'Complete'); updateProgress(100, 'Your real video is ready', 'Review the exact asset before anything is published', 3);
      stopProductionTimer();
      await renderApproval(post); showScreen('approve'); toast('Real video ready for your approval.');
    } catch (error) { if (state.imageTimer) stopImageTimer(false); stopProductionTimer(); showProductionError(error); toast(error.message); }
    finally { state.productionRunning = false; $('#resumeProduction').disabled = false; }
  }

  async function providerState() {
    const readiness = await api('/api/autopilot/provider-readiness');
    let accounts = [];
    if (readiness.post_for_me?.configured && readiness.live_calls_enabled) accounts = (await api('/api/autopilot/post-for-me/accounts')).accounts || [];
    state.accounts = accounts; return readiness;
  }
  async function renderApproval(post) {
    $('#finalVideo').src = state.asset.media_url || state.asset.video_url || state.asset.url || '';
    $('#approvalTitle').value = post.title; $('#approvalCaption').value = post.caption; $('#approvalHashtags').value = post.hashtags.join(', ');
    const host = $('#publishDestinations');
    try {
      const readiness = await providerState();
      host.innerHTML = `<b>Publish to</b>${state.accounts.length ? state.accounts.map(account => `<label><input type="checkbox" data-account value="${esc(account.id || account.account_id)}"><span><b>${esc(account.username || account.name || 'Connected account')}</b><small>${esc(account.platform || 'social')} · connected</small></span></label>`).join('') : `<p>${readiness.post_for_me?.configured ? 'No connected Instagram or YouTube account was returned.' : 'Post for Me needs server configuration before publishing.'}</p><button class="secondary" type="button" data-go="connections">Open connections</button>`}`;
      $$('[data-go="connections"]', host).forEach(button => button.onclick = () => showScreen('connections'));
    } catch (error) { host.innerHTML = `<b>Publish to</b><p>${esc(error.message)}</p>`; }
    $('#exactApproval').checked = false; $('#publishApproved').disabled = true;
  }
  function postFromAsset() {
    const asset = state.asset || {};
    return { title: asset.title || state.topic?.title || '', caption: asset.caption || '', hashtags: asset.hashtags || parse(asset.hashtags_json || '[]') };
  }
  function assetMatchesPost(asset, post) {
    if (!asset?.id) return false;
    const existingTags = asset.hashtags || parse(asset.hashtags_json || '[]');
    return String(asset.title || '').trim() === post.title
      && String(asset.caption || '').trim() === post.caption
      && JSON.stringify(existingTags) === JSON.stringify(post.hashtags);
  }
  function invalidateApproval() { $('#exactApproval').checked = false; $('#publishApproved').disabled = true; }
  async function publishApproved() {
    const button = $('#publishApproved'), destinations = $$('[data-account]:checked').map(node => node.value);
    if (!destinations.length) return toast('Select at least one connected destination.');
    button.disabled = true; button.textContent = 'Recording exact approval…';
    const post = { title: $('#approvalTitle').value.trim(), caption: $('#approvalCaption').value.trim(), hashtags: list($('#approvalHashtags').value) };
    try {
      let asset = state.asset;
      if (!assetMatchesPost(asset, post)) {
        const exactAsset = await api(`/api/autopilot/concepts/${encodeURIComponent(state.concept.id)}/finalize`, { method: 'POST', body: JSON.stringify({ workflow_run_id: state.workflow.id, concept_id: state.concept.id, ...post }) });
        asset = exactAsset.asset; state.asset = asset;
      }
      for (const destination_id of destinations) {
        const approved = await api('/api/autopilot/publications/approve', { method: 'POST', body: JSON.stringify({ workflow_run_id: state.workflow.id, asset_version_id: asset.id, destination_id, scheduled_at: 0, ...post }) });
        button.textContent = 'Submitting to Post for Me…';
        await api(`/api/autopilot/publications/${encodeURIComponent(approved.publication.id)}/submit`, { method: 'POST' });
      }
      button.textContent = 'Submitted for publishing ✓'; toast('Post for Me accepted the approved publication. Platform confirmation is pending.');
      setTimeout(() => showScreen('results'), 900);
    } catch (error) { button.disabled = false; button.textContent = 'Retry approved publication'; toast(error.message); }
  }

  async function loadResults() {
    try {
      const data = await api('/api/autopilot/growth-dashboard'), metrics = data.metrics || [], publications = data.publications || [], recommendations = data.recommendations || [];
      const publication = publications[0], metric = metrics.find(item => item.publication_id === publication?.id) || metrics[0], values = parse(metric?.metrics_json || metric?.payload_json);
      const simulated = Boolean(data.provenance?.contains_simulated_data || publication?.provenance?.is_simulated || metric?.provenance?.is_simulated);
      $('#resultsDisclosure').innerHTML = simulated ? '<b>SIMULATED DATA — NOT SOCIAL PERFORMANCE.</b> Demo values are never presented as real results.' : (metric ? '<b>PROVIDER-REPORTED DATA.</b> Values below came from the connected publishing provider.' : 'No provider-reported performance yet. Results appear only after a platform confirms the live post and metrics are collected.');
      $('#metricGrid').innerHTML = [['Views', values.views], ['Likes', values.likes], ['Comments', values.comments], ['Shares', values.shares]].map(([label, value]) => `<div><span>${label}</span><b>${value ?? '—'}</b></div>`).join('');
      const chart = $('.chart-card');
      chart.innerHTML = `<div class="card-head"><div><b>Performance evidence</b><small>${metric ? 'Latest provider snapshot' : 'Waiting for platform data'}</small></div><span>${esc(publication?.status || 'No live post')}</span></div><div class="empty-evidence">${metric ? `Metrics captured at ${esc(metric.captured_at || 'provider sync')}.` : 'The three-hour monitor begins after a real publication is confirmed.'}</div>`;
      const recommendation = recommendations.find(item => item.status === 'active') || recommendations[0];
      $('.learning-card h2').textContent = recommendation ? 'Your next evidence-based action' : 'Learning starts after publication.';
      $('.learning-card > p').textContent = recommendation?.recommendation || 'Viralizer will compare predicted performance with provider-reported results before recommending the next video.';
      $('.learning-card .insight span').textContent = recommendation?.recommendation || 'No recommendation is available without real evidence.';
    } catch (error) { $('#resultsDisclosure').textContent = error.message; }
  }

  async function loadConnections() {
    const host = $('#connectionList'); host.innerHTML = '<article><div><b>Checking provider readiness…</b></div></article>';
    try {
      const readiness = await providerState();
      const accounts = state.accounts.map(account => `<article><div><b>${esc(account.username || account.name || 'Connected account')}</b><small>${esc(account.platform || 'social')} · connected</small></div><span class="provider-label live">CONNECTED</span></article>`).join('');
      host.innerHTML = `${accounts || '<article><div><b>No social accounts connected</b><small>Connect Instagram or YouTube through Post for Me.</small></div></article>'}<article><div><b>Post for Me</b><small>${readiness.post_for_me?.configured ? 'Server configured' : 'Server setup required'}</small></div><span class="provider-label ${readiness.post_for_me?.configured ? 'live' : 'simulated'}">${readiness.post_for_me?.configured ? 'READY' : 'NOT READY'}</span></article><article><div><b>PixVerse</b><small>Image-to-video generation</small></div><span class="provider-label ${readiness.pixverse?.configured ? 'live' : 'simulated'}">${readiness.pixverse?.configured ? 'READY' : 'NOT READY'}</span></article>${['instagram', 'youtube'].map(platform => `<article><div><b>Connect ${platform[0].toUpperCase() + platform.slice(1)}</b><small>Secure authorization through Post for Me</small></div><button class="secondary" data-connect="${platform}" ${readiness.post_for_me?.configured && readiness.live_calls_enabled ? '' : 'disabled'}>Connect</button></article>`).join('')}`;
      $$('[data-connect]').forEach(button => button.onclick = () => connectAccount(button.dataset.connect));
    } catch (error) { host.innerHTML = `<article><div><b>Connections unavailable</b><small>${esc(error.message)}</small></div></article>`; }
  }
  async function connectAccount(platform) {
    try {
      const redirect = `${location.origin}${location.pathname}?view=connections&connected=${encodeURIComponent(platform)}`;
      const data = await api('/api/autopilot/post-for-me/connection-url', { method: 'POST', body: JSON.stringify({ platform, redirect_url: redirect }) });
      const url = data.connection?.url || data.connection?.auth_url || data.connection?.connection_url;
      if (!url) throw new Error('Post for Me did not return a connection URL.'); location.assign(url);
    } catch (error) { toast(error.message); }
  }

  async function sendAssistant(text) {
    const value = String(text || '').trim(); if (!value) return;
    const host = $('#assistantMessages'); host.insertAdjacentHTML('beforeend', `<div class="user-message"><p>${esc(value)}</p></div><div class="assistant-loading">Viralizer is thinking with this screen’s context…</div>`); host.scrollTop = host.scrollHeight;
    try {
      const context = { active_screen: state.current, opportunity_id: state.topic?.id, concept_id: state.concept?.id, workflow_run_id: state.workflow?.id };
      if (!state.conversationId) {
        const created = await api('/api/conversations', { method: 'POST', body: JSON.stringify({ title: state.topic?.title || 'Viralizer growth workspace', active_project_context_id: '' }) });
        state.conversationId = created.conversation.id;
      }
      const stored = await api(`/api/conversations/${encodeURIComponent(state.conversationId)}/messages`, { method: 'POST', body: JSON.stringify({ content: { type: 'text', text: value, ...context }, correlation_id: crypto.randomUUID() }) });
      const data = await api(`/api/conversations/${encodeURIComponent(state.conversationId)}/respond`, { method: 'POST', body: JSON.stringify({ message_id: stored.message.id, cost_confirmed: false }) });
      $('.assistant-loading')?.remove();
      host.insertAdjacentHTML('beforeend', `<div class="ai-message"><span>✦</span><p>${esc(data.message?.content?.text || data.text || 'I completed the request. Review the active workspace for changes.')}</p></div>`);
    } catch (error) { $('.assistant-loading')?.remove(); host.insertAdjacentHTML('beforeend', `<div class="ai-message"><span>!</span><p>${esc(error.message)} The visual workflow remains available.</p></div>`); }
    host.scrollTop = host.scrollHeight;
  }

  function bind() {
    $$('[data-screen]').forEach(button => button.onclick = () => showScreen(button.dataset.screen));
    $$('[data-go]').forEach(button => button.onclick = () => showScreen(button.dataset.go));
    $('#trendOpportunitySection .secondary').onclick = () => refreshTopics(true);
    $$('[data-inspiration]').forEach(button => button.onclick = () => openInspiration(button.dataset.inspiration));
    $('#closeInspiration').onclick = closeInspiration; $('#continueInspiration').onclick = continueInspiration;
    $('#explainTopics').onclick = () => { $('#assistantDrawer').classList.add('open'); sendAssistant('Explain why these opportunities match my confirmed profile.'); };
    $('#openAssistant').onclick = () => $('#assistantDrawer').classList.add('open'); $('#closeAssistant').onclick = () => $('#assistantDrawer').classList.remove('open');
    $('#openAssistantNav').onclick = () => $('#assistantDrawer').classList.add('open');
    $('#openAssistantMobile').onclick = () => $('#assistantDrawer').classList.add('open');
    $('#assistantForm').onsubmit = event => { event.preventDefault(); const input = $('#assistantForm textarea'); sendAssistant(input.value); input.value = ''; };
    $$('[data-customer-type]').forEach(button => button.onclick = () => { state.onboardingType = button.dataset.customerType; $$('[data-customer-type]').forEach(item => item.classList.toggle('selected', item === button)); updateOnboardingReadiness(); });
    ['onboardName', 'onboardWebsite', 'onboardSocial', 'onboardOffer', 'onboardAudience', 'onboardVoice'].forEach(id => $(`#${id}`).addEventListener('input', updateOnboardingReadiness));
    $('#onboardingChatForm').onsubmit = event => {
      event.preventDefault(); const input = $('#onboardingChatInput'); const value = input.value.trim(); if (!value) return;
      const question = onboardingQuestions[state.onboardingStep]; addOnboardingMessage(value, 'user');
      if (question?.field) $(`#${question.field}`).value = value.toLowerCase() === 'skip' ? '' : value;
      state.onboardingStep += 1; input.value = ''; updateOnboardingReadiness();
      const next = onboardingQuestions[state.onboardingStep]; addOnboardingMessage(next?.prompt || 'Great. Analyze your public brand source, review the suggestions, then confirm the profile.');
    };
    $$('[data-creation-mode]').forEach(button => button.onclick = () => {
      state.creationMode = button.dataset.creationMode; $$('[data-creation-mode]').forEach(item => item.classList.toggle('selected', item === button));
      toast(`${creationModeLabel(state.creationMode)} selected.`); updateOnboardingReadiness();
    });
    $('#analyzeOnboardBrand').onclick = analyzeBrand; $('#confirmOnboarding').onchange = updateOnboardingReadiness; $('#finishWorkspaceOnboarding').onclick = finishOnboarding;
    $('#startRealProduction').onclick = () => {
      if ($('#useUserPhoto')?.checked && state.userPhotoDirty) { state.forceRegenerateKeyframes = true; state.keyframesApproved = false; $('#costConfirmation').hidden = false; return; }
      if ([0, 1, 2].every(index => currentKeyframe(index))) {
        renderProductionKeyframes(); $('#keyframeReview').scrollIntoView({ behavior: 'smooth', block: 'start' }); toast('Your three images are already ready below.');
      } else $('#costConfirmation').hidden = false;
    }; $('#cancelProduction').onclick = () => $('#costConfirmation').hidden = true; $('#confirmProduction').onclick = () => { $('#costConfirmation').hidden = true; runProduction(); }; $('#resumeProduction').onclick = runProduction;
    $('#approveKeyframes').onclick = () => { state.keyframesApproved = true; $('#keyframeReview').hidden = true; showScreen('produce'); runProduction(); };
    $('#userPhotoInput').onchange = () => { state.userPhotoId = ''; state.userPhotoDirty = Boolean($('#userPhotoInput').files?.[0]); $('#userPhotoStatus').textContent = state.userPhotoDirty ? 'Selected · confirm permission below to use it' : 'Optional · kept private in your workspace'; updatePhotoAction(); };
    $('#useUserPhoto').onchange = event => { if (!event.target.checked) $('#userPhotoStatus').textContent = 'Photo will not be used'; else { state.userPhotoDirty = Boolean(state.userPhotoId || $('#userPhotoInput').files?.[0]); $('#userPhotoStatus').textContent = state.userPhotoId ? 'Ready · your photo will guide all three scenes' : 'Selected · click regenerate to upload and use it'; } updatePhotoAction(); };
    $('#changeDirection').onclick = () => { if (state.concepts.length < 2) return toast('Only one saved direction is available.'); const index = state.concepts.findIndex(item => item.id === state.concept.id); state.concept = state.concepts[(index + 1) % state.concepts.length]; renderConcept(); };
    $('#exactApproval').onchange = event => { $('#publishApproved').disabled = !event.target.checked; };
    ['#approvalTitle', '#approvalCaption', '#approvalHashtags'].forEach(selector => $(selector).addEventListener('input', invalidateApproval));
    $('#publishApproved').onclick = publishApproved; $('#editBrand').onclick = showOnboarding;
    window.addEventListener('popstate', () => {
      showScreen(new URLSearchParams(location.search).get('view') || 'today', { historyMode: 'none' });
    });
  }
  async function init() {
    bind(); showScreen(new URLSearchParams(location.search).get('view') || 'today', { historyMode: 'replace' });
    const data = await api('/api/autopilot/brand-profile'); state.profile = data.brand_profile; state.accountProfile = data.account_profile || {}; renderBrand();
    const forceOnboarding = new URLSearchParams(window.location.search).get('onboarding') === '1';
    const confirmed = Boolean(
      state.profile?.status === 'confirmed' ||
      Number(state.profile?.confirmed_at || 0) > 0 ||
      state.profile?.confirmed === true ||
      profileData().confirmed === true
    );
    if (forceOnboarding || !state.profile || !confirmed) showOnboarding();
    else {
      await refreshTopics(false);
      const restored = (await api('/api/autopilot/projects/current')).project;
      if (restored) {
        state.topic = restored.opportunity; state.concepts = restored.concepts || [];
        state.concept = restored.concept || state.concepts[0]; state.workflow = restored.workflow; state.asset = restored.asset;
        renderConcept();
        if ([0, 1, 2].every(index => currentKeyframe(index))) renderProductionKeyframes();
        if (state.asset) {
          renderRestoredProduction();
          if (state.current === 'approve') renderApproval(postFromAsset());
        }
        toast('Your saved project has been restored.');
      }
    }
    if (new URLSearchParams(location.search).has('connected')) toast('Connection returned. Refreshing provider accounts…');
  }
  init().catch(error => { toast(error.message); showOnboarding(); });
})();
