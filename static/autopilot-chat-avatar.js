(()=>{
  const PHOTO_KEY='viralizer.userPhotoId';
  function removeDuplicateActions(){
    const messages=document.querySelector('#messages');
    const storyboards=[...(messages?.querySelectorAll('.storyboard-card')||[])];
    const storyboard=storyboards.at(-1);
    if(!storyboard)return;
    const replies=messages?.querySelector('.quick-replies');
    if(!replies)return;
    let node=storyboard.parentElement?.nextElementSibling;
    let laterOutput=false;
    while(node&&node!==replies){
      if(node.matches?.('.chat-media,.action-card,.final-review,.publication-card,.generation-clock')||node.querySelector?.('.chat-media,.action-card,.final-review,.publication-card,.generation-clock')){laterOutput=true;break}
      node=node.nextElementSibling;
    }
    if(!laterOutput)replies.remove();
  }

  function identityPanel(){
    const saved=localStorage.getItem(PHOTO_KEY)||'';
    const panel=document.createElement('section');
    panel.className='identity-panel';
    panel.innerHTML=`<div><span class="eyebrow">PERSON IN THE IMAGES · OPTIONAL</span><h4>${saved?'Your saved photo will be used':'Use your own photo or avatar'}</h4><p>${saved?'Every generated scene will preserve your identity.':'Upload a clear photo if you want to appear consistently in every generated scene.'}</p></div><img data-avatar-preview alt="Selected avatar preview" hidden><input type="file" accept="image/jpeg,image/png,image/webp" data-avatar-file hidden><label><input type="checkbox" data-avatar-consent ${saved?'checked':''}> I have permission to use this photo</label><div class="media-actions"><button type="button" data-upload-avatar>${saved?'Replace photo':'Upload my photo/avatar'}</button>${saved?'<button type="button" class="secondary" data-remove-avatar>Use an AI-created person</button>':''}</div><small data-avatar-status>${saved?'Identity photo ready ✓':'No photo uploaded—Viralizer will create an original person.'}</small>`;
    const file=panel.querySelector('[data-avatar-file]'),consent=panel.querySelector('[data-avatar-consent]'),status=panel.querySelector('[data-avatar-status]'),upload=panel.querySelector('[data-upload-avatar]'),preview=panel.querySelector('[data-avatar-preview]');
    upload.onclick=()=>{if(!consent.checked){status.textContent='Confirm that you have permission to use the photo first.';return}file.click()};
    file.onchange=async()=>{const selected=file.files?.[0];if(!selected)return;preview.src=URL.createObjectURL(selected);preview.hidden=false;upload.disabled=true;status.textContent='Uploading your private identity photo…';try{const form=new FormData;form.append('photo',selected,selected.name);form.append('consent_confirmed','true');const response=await fetch('/api/autopilot/user-photos',{method:'POST',body:form}),data=await response.json().catch(()=>({}));if(!response.ok)throw new Error(data.detail||`Upload failed (${response.status})`);localStorage.setItem(PHOTO_KEY,data.photo_id);status.textContent='Photo ready ✓ It will be used for every storyboard image.';upload.textContent='Replace photo'}catch(error){status.textContent=error.message}finally{upload.disabled=false}};
    panel.querySelector('[data-remove-avatar]')?.addEventListener('click',()=>{localStorage.removeItem(PHOTO_KEY);panel.replaceWith(identityPanel())});
    return panel;
  }

  function decorate(){
    removeDuplicateActions();
    document.querySelectorAll('.storyboard-card').forEach(card=>{
      if(card.querySelector('.identity-panel'))return;
      const actions=card.querySelector('.card-actions');
      if(actions)actions.before(identityPanel());
    });
  }

  const nativeFetch=window.fetch.bind(window);
  window.fetch=(input,init={})=>{
    const url=typeof input==='string'?input:String(input?.url||'');
    if(/\/api\/conversations\/[^/]+\/tool-executions\/[^/]+\/confirm$/.test(url)&&init.method==='POST'){
      try{
        const body=JSON.parse(init.body||'{}'),photoId=localStorage.getItem(PHOTO_KEY)||'';
        if(photoId)body.user_photo_id=photoId;
        init={...init,body:JSON.stringify(body)};
      }catch{}
    }
    return nativeFetch(input,init);
  };

  new MutationObserver(decorate).observe(document.documentElement,{childList:true,subtree:true});
  decorate();
})();
