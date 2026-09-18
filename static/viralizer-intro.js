(() => {
  const INTRO_CONFIG = Object.freeze({
    VIRALIZER_INTRO_ENABLED: true,
    VIRALIZER_INTRO_DURATION: 15000,
    VIRALIZER_INTRO_SKIP_ENABLED: true,
    REDUCED_MOTION_DURATION: 450,
    LOGIN_TRANSITION_DURATION: 800,
    TIMELINE: Object.freeze({
      idea:[0,1000], core:[1000,2000], signal:[2000,3000], creation:[3000,4000],
      formats:[4000,5000], distribution:[5000,6000], audience:[6000,7000], global:[7000,8000],
      useCases:[8000,9000], results:[9000,10000], momentum:[10000,11000], convergence:[11000,12000],
      brand:[12000,13000], portal:[13000,15000]
    })
  });
  const {VIRALIZER_INTRO_ENABLED,VIRALIZER_INTRO_DURATION,VIRALIZER_INTRO_SKIP_ENABLED,REDUCED_MOTION_DURATION,LOGIN_TRANSITION_DURATION,TIMELINE}=INTRO_CONFIG;
  if (!VIRALIZER_INTRO_ENABLED || !document.body.classList.contains('intro-active')) return;

  const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
  const root=document.createElement('div');
  root.className='viralizer-intro';root.setAttribute('role','presentation');
  root.innerHTML='<canvas class="viralizer-intro-canvas"></canvas><div class="viralizer-intro-depth"></div><div class="viralizer-intro-glow"></div><div class="viralizer-intro-idea"><span>A single idea...</span><i></i></div><div class="viralizer-intro-brand"><img src="/static/viralizer-original-logo.png" alt="Viralizer"><p>Create Smarter. Grow Faster.</p></div><div class="viralizer-intro-arrow"><img src="/static/viralizer-original-logo.png" alt=""></div><button class="viralizer-intro-skip" type="button" aria-label="Skip Viralizer introduction">Skip</button>';
  document.body.prepend(root);
  const canvas=root.querySelector('canvas'),context=canvas.getContext('2d',{alpha:true,desynchronized:true}),skip=root.querySelector('.viralizer-intro-skip'),login=document.querySelector('main.card');
  const logo=root.querySelector('.viralizer-intro-brand img');
  let width=0,height=0,dpr=1,start=performance.now(),frame=0,finished=false,skipTimer=0,scene='';
  const mobile=matchMedia('(max-width: 700px)').matches,lowPower=(navigator.hardwareConcurrency||4)<=4;
  const quality=mobile||lowPower?.62:1,nodeCount=Math.round(58*quality),cardCount=Math.max(6,Math.round(12*quality)),particleCount=Math.round(90*quality);
  const nodes=Array.from({length:nodeCount},(_,i)=>({angle:(i/nodeCount)*Math.PI*2+(i%7)*.13,radius:.16+((i*37)%100)/118,depth:.28+((i*29)%70)/100,drift:(i%2?1:-1)*(.025+(i%9)*.004)}));
  const cards=Array.from({length:cardCount},(_,i)=>({angle:(i/cardCount)*Math.PI*2+.3,radius:.24+(i%5)*.105,depth:.58+(i%4)*.13,kind:i%6,ratio:[.58,1,1.72,.76,1.35][i%5]}));
  const particles=Array.from({length:particleCount},(_,i)=>({a:i*2.399,r:.08+((i*43)%100)/110,s:.4+(i%7)*.1,z:.25+((i*31)%75)/100}));
  const clamp=v=>Math.max(0,Math.min(1,v));
  const smooth=v=>{v=clamp(v);return v*v*(3-2*v)};
  const progress=(name,time)=>{const [a,b]=TIMELINE[name];return smooth((time-a)/(b-a))};
  function resize(){dpr=Math.min(devicePixelRatio||1,mobile?1.35:2);width=innerWidth;height=innerHeight;canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);canvas.style.width=width+'px';canvas.style.height=height+'px';context.setTransform(dpr,0,0,dpr,0,0)}
  function glowLine(x1,y1,x2,y2,alpha,size=1){const g=context.createLinearGradient(x1,y1,x2,y2);g.addColorStop(0,'rgba(139,0,232,0)');g.addColorStop(.45,`rgba(192,132,252,${alpha})`);g.addColorStop(1,'rgba(155,0,255,0)');context.strokeStyle=g;context.lineWidth=size;context.beginPath();context.moveTo(x1,y1);context.lineTo(x2,y2);context.stroke()}
  function dot(x,y,r,a=1,white=false){context.globalAlpha=a;context.shadowBlur=r*5;context.shadowColor=white?'#fff':'#9b00ff';context.fillStyle=white?'#fff':'#a855f7';context.beginPath();context.arc(x,y,r,0,Math.PI*2);context.fill();context.shadowBlur=0;context.globalAlpha=1}
  function networkPoint(n,time,pull=0,zoom=1){const base=Math.min(width,height)*.47*n.radius*zoom*(1-pull*.93),a=n.angle+time*n.drift;return{x:width/2+Math.cos(a)*base,y:height/2+Math.sin(a)*base*.68,z:n.depth}}
  function drawNetwork(time,alpha,pull=0,zoom=1){const ps=nodes.map(n=>networkPoint(n,time,pull,zoom));ps.forEach((p,i)=>{const q=ps[(i+7)%ps.length],r=ps[(i+15)%ps.length];if(Math.hypot(p.x-q.x,p.y-q.y)<Math.min(width,height)*.4)glowLine(p.x,p.y,q.x,q.y,.12*alpha*(1-pull),.7);if(i%3===0&&Math.hypot(p.x-r.x,p.y-r.y)<Math.min(width,height)*.3)glowLine(p.x,p.y,r.x,r.y,.07*alpha*(1-pull),.55);dot(p.x,p.y,i%7?1.3:2.1,alpha*p.z,i%7===0)});return ps}
  function drawCard(c,time,alpha,tunnel=0,transform=0,pull=0){const radius=Math.min(width,height)*c.radius*(1+Math.sin(time*.4+c.angle)*.03)*(1-pull*.9);const perspective=1+tunnel*(c.depth*1.6-.35),x=width/2+Math.cos(c.angle+time*.035)*radius*perspective,y=height/2+Math.sin(c.angle+time*.035)*radius*.62*perspective;const base=(mobile?.72:1)*c.depth,wide=76*base*(c.ratio+(transform&&c.kind%2?(.58-c.ratio)*transform:0)),h=76*base;
    context.save();context.translate(x,y);context.rotate(Math.sin(c.angle)*.055);context.globalAlpha=alpha*(1-pull);context.fillStyle='rgba(15,13,31,.9)';context.strokeStyle='rgba(192,132,252,.48)';context.lineWidth=1;context.shadowBlur=18;context.shadowColor='rgba(139,0,232,.2)';context.beginPath();context.roundRect(-wide/2,-h/2,wide,h,8);context.fill();context.stroke();context.shadowBlur=0;
    const ix=-wide*.34,iy=-h*.26,iw=wide*.68,ih=h*.5;context.fillStyle='rgba(139,0,232,.2)';context.fillRect(ix,iy,iw,ih);
    if(c.kind===0){context.fillStyle='#c084fc';context.beginPath();context.moveTo(-4,-10);context.lineTo(10,0);context.lineTo(-4,10);context.fill()}
    else if(c.kind===1){context.strokeStyle='#a855f7';context.lineWidth=2;context.beginPath();for(let j=0;j<8;j++){const px=ix+j*iw/7,py=iy+ih*.55+Math.sin(j*1.3+c.angle)*ih*.28;j?context.lineTo(px,py):context.moveTo(px,py)}context.stroke()}
    else if(c.kind===2){for(let j=0;j<4;j++){context.fillStyle=`rgba(192,132,252,${.25+j*.12})`;context.fillRect(ix+j*iw*.23,iy+ih-(j+1)*ih*.18,iw*.13,(j+1)*ih*.18)}}
    else if(c.kind===3){context.strokeStyle='#c084fc';context.lineWidth=2;context.beginPath();for(let j=0;j<14;j++){const px=ix+j*iw/13,py=Math.sin(j*1.8)*ih*.18;j?context.lineTo(px,py):context.moveTo(px,py)}context.stroke()}
    else if(c.kind===4){context.fillStyle='#a855f7';context.beginPath();context.arc(0,-3,9,0,Math.PI*2);context.fill();context.fillStyle='rgba(192,132,252,.28)';context.beginPath();context.arc(0,18,17,Math.PI,0);context.fill()}
    else{context.strokeStyle='#a855f7';context.lineWidth=2;context.beginPath();context.moveTo(ix,iy+ih);context.lineTo(ix+iw*.35,iy+ih*.68);context.lineTo(ix+iw*.58,iy+ih*.78);context.lineTo(ix+iw,iy+ih*.18);context.stroke()}
    context.restore()}
  function drawIdeaCore(time,p){const cx=width/2,cy=height/2;for(let i=0;i<particles.length;i++){const q=particles[i],r=Math.min(width,height)*(.025+q.r*.085)*p,x=cx+Math.cos(q.a+time*.45*q.s)*r,y=cy+Math.sin(q.a+time*.45*q.s)*r*.68;dot(x,y,1.1*q.z,p*.55)}const halo=context.createRadialGradient(cx,cy,0,cx,cy,Math.min(width,height)*.16);halo.addColorStop(0,`rgba(255,255,255,${.92*p})`);halo.addColorStop(.08,`rgba(192,132,252,${.72*p})`);halo.addColorStop(.35,`rgba(155,0,255,${.2*p})`);halo.addColorStop(1,'rgba(139,0,232,0)');context.fillStyle=halo;context.beginPath();context.arc(cx,cy,Math.min(width,height)*.16,0,Math.PI*2);context.fill();dot(cx,cy,3+4*p,p,true)}
  function drawSignal(time,p){const cx=width/2,cy=height/2,s=Math.min(width,height)/620;const path=new Path2D('M -112 -35 C -88 -35 -80 -7 -62 13 C -44 33 -20 42 2 28 C 23 15 34 -20 45 -52 L 67 -75');context.save();context.translate(cx-5*s,cy+8*s);context.scale(s,s);context.strokeStyle=`rgba(168,85,247,${.72*p})`;context.lineWidth=7;context.lineCap='round';context.shadowBlur=18;context.shadowColor='#9b00ff';context.setLineDash([330,330]);context.lineDashOffset=330*(1-p);context.stroke(path);context.restore()}
  function drawAudience(time,p){const cx=width/2,cy=height/2,clusters=[[-.32,-.12,.85],[.3,-.2,1],[.18,.24,.7],[-.24,.25,.48]];clusters.forEach((c,i)=>{const x=cx+c[0]*width,y=cy+c[1]*height,strength=c[2]*p;for(let j=0;j<7;j++){const a=j*.9+i,r=(18+j%3*11)*(mobile?.7:1);dot(x+Math.cos(a)*r,y+Math.sin(a)*r,1.5+j%3*.4,strength*.75,j===0)}if(i<3)glowLine(cx,cy,x,y,strength*.34,1.3)});dot(cx,cy,4,p,true)}
  function drawGlobe(time,p){const cx=width/2,cy=height/2,R=Math.min(width,height)*.28;context.save();context.globalAlpha=p;context.strokeStyle='rgba(168,85,247,.25)';context.lineWidth=1;context.beginPath();context.arc(cx,cy,R,0,Math.PI*2);context.stroke();for(let i=-2;i<=2;i++){context.beginPath();context.ellipse(cx,cy,R*Math.cos(i*.23),R,i*.28,0,Math.PI*2);context.stroke()}for(let i=-2;i<=2;i++){context.beginPath();context.ellipse(cx,cy,R,R*Math.cos(i*.23),0,0,Math.PI*2);context.stroke()}for(let i=0;i<20;i++){const a=i*2.399+time*.08,b=Math.sin(i*1.7)*.75,x=cx+Math.cos(a)*Math.cos(b)*R,y=cy+Math.sin(b)*R;dot(x,y,i%5?1.3:2.3,.7*p,i%5===0)}context.restore()}
  function drawAnalytics(time,p){const left=width*.25,right=width*.75,bottom=height*.67,top=height*.31;context.save();context.globalAlpha=p;context.strokeStyle='rgba(168,85,247,.13)';for(let i=0;i<5;i++){const y=top+(bottom-top)*i/4;glowLine(left,y,right,y,.12,1)}context.strokeStyle='#a855f7';context.lineWidth=3;context.shadowBlur=14;context.shadowColor='#8b00e8';context.beginPath();for(let i=0;i<10;i++){const x=left+(right-left)*i/9,y=bottom-(bottom-top)*(.12+i*.075+Math.sin(i*1.7+time)*.07);i?context.lineTo(x,y):context.moveTo(x,y)}context.stroke();for(let i=0;i<10;i++){const x=left+(right-left)*i/9,y=bottom-(bottom-top)*(.12+i*.075+Math.sin(i*1.7+time)*.07);dot(x,y,2,.75,i===9)}context.restore()}
  function drawConvergence(time,p){drawNetwork(time,1-p,p,1);cards.forEach(c=>drawCard(c,time,1,0,0,p));const cx=width/2,cy=height/2,s=Math.min(width,height)/620,path=new Path2D('M -112 -35 C -88 -35 -80 -7 -62 13 C -44 33 -20 42 2 28 C 23 15 34 -20 45 -52 L 67 -75 M 43 -73 L 71 -80 L 76 -51');context.save();context.translate(cx-72*s,cy+8*s);context.scale(s,s);context.strokeStyle=`rgba(192,132,252,${p})`;context.lineWidth=10;context.lineCap='round';context.lineJoin='round';context.shadowBlur=25;context.shadowColor='#9b00ff';context.setLineDash([360,360]);context.lineDashOffset=360*(1-p);context.stroke(path);context.setLineDash([]);[[-112,-35],[-62,13],[2,28]].forEach((q,i)=>{context.globalAlpha=clamp(p*1.8-i*.2);context.fillStyle='#070711';context.strokeStyle='#a855f7';context.lineWidth=7;context.beginPath();context.arc(q[0],q[1],8,0,Math.PI*2);context.fill();context.stroke()});context.restore()}
  function updateScene(name){if(scene===name)return;scene=name;root.dataset.scene=name;if(name!=='idea')root.classList.add('idea-dissolve');if(name==='brand')root.classList.add('is-branding');if(name==='portal')root.classList.add('is-portal')}
  function draw(now){if(finished)return;const elapsed=now-start,time=elapsed/1000,cx=width/2,cy=height/2;context.clearRect(0,0,width,height);
    if(elapsed<1000){updateScene('idea');const p=progress('idea',elapsed);for(let i=0;i<particles.length/3;i++){const q=particles[i],r=16+q.r*70;dot(cx+Math.cos(q.a)*r,cy+Math.sin(q.a)*r*.35,1,p*.3)}}
    else if(elapsed<2000){updateScene('core');drawIdeaCore(time,progress('core',elapsed))}
    else if(elapsed<3000){updateScene('signal');drawIdeaCore(time,1-progress('signal',elapsed));drawSignal(time,progress('signal',elapsed))}
    else if(elapsed<4000){updateScene('creation');const p=progress('creation',elapsed);drawNetwork(time,p*.45);cards.slice(0,Math.ceil(cardCount*.55)).forEach(c=>drawCard(c,time,p));drawSignal(time,1-p)}
    else if(elapsed<5000){updateScene('formats');const p=progress('formats',elapsed);drawNetwork(time,.5+p*.25);cards.forEach(c=>drawCard(c,time,clamp(p*1.6),0,p))}
    else if(elapsed<6000){updateScene('distribution');const p=progress('distribution',elapsed);drawNetwork(time,.8,0,1+p*.28);cards.forEach(c=>drawCard(c,time,1,p,1));for(let i=0;i<12;i++){const a=i*.7+time*.25,r=Math.min(width,height)*(.12+(i%6)*.07);glowLine(cx+Math.cos(a)*r*.3,cy+Math.sin(a)*r*.2,cx+Math.cos(a)*r,cy+Math.sin(a)*r*.65,.25*p,1.2)}}
    else if(elapsed<7000){updateScene('audience');const p=progress('audience',elapsed);drawNetwork(time,.38*(1-p));cards.slice(0,5).forEach(c=>drawCard(c,time,1-p*.35));drawAudience(time,p)}
    else if(elapsed<8000){updateScene('global');const p=progress('global',elapsed);drawAudience(time,1-p);drawGlobe(time,p)}
    else if(elapsed<9000){updateScene('useCases');const p=progress('useCases',elapsed);drawGlobe(time,1-p*.6);cards.forEach((c,i)=>drawCard({...c,radius:.2+(i%4)*.115},time,clamp(p*1.5),0,0));drawNetwork(time,p*.35)}
    else if(elapsed<10000){updateScene('results');const p=progress('results',elapsed);cards.forEach(c=>drawCard(c,time,1-p));drawAnalytics(time,p)}
    else if(elapsed<11000){updateScene('momentum');const p=progress('momentum',elapsed);drawAnalytics(time,1-p);drawNetwork(time,1,0,1+p*1.5);cards.forEach(c=>drawCard(c,time,1,p*1.8));for(let i=0;i<24;i++){const a=i*.87,r=Math.min(width,height)*(.12+(i%9)*.07);glowLine(cx+Math.cos(a)*r,cy+Math.sin(a)*r*.66,cx+Math.cos(a)*r*.18,cy+Math.sin(a)*r*.12,.35*p,1.5)}}
    else if(elapsed<12000){updateScene('convergence');drawConvergence(time,progress('convergence',elapsed))}
    else if(elapsed<13000){updateScene('brand');const p=progress('brand',elapsed);for(let i=0;i<particles.length/3;i++){const q=particles[i],r=Math.min(width,height)*(.3+q.r*.35);dot(cx+Math.cos(q.a+time*.03)*r,cy+Math.sin(q.a+time*.03)*r*.4,1,q.z*.16*(1-p*.5))}}
    else{updateScene('portal');const p=progress('portal',elapsed),g=context.createRadialGradient(cx,cy,0,cx,cy,Math.max(width,height)*.7);g.addColorStop(0,`rgba(192,132,252,${.2+p*.65})`);g.addColorStop(.28,`rgba(139,0,232,${.18+p*.34})`);g.addColorStop(1,'rgba(3,3,8,0)');context.fillStyle=g;context.fillRect(0,0,width,height)}
    if(elapsed>=VIRALIZER_INTRO_DURATION-LOGIN_TRANSITION_DURATION)finish(false);else frame=requestAnimationFrame(draw)}
  function revealLogin(){document.body.classList.remove('intro-active');if(login){login.style.opacity='1';login.style.transform='scale(1)';login.style.filter='blur(0)'}}
  function finish(skipped){if(finished)return;finished=true;cancelAnimationFrame(frame);clearTimeout(skipTimer);root.classList.add('idea-dissolve','is-branding','is-portal');const duration=skipped?520:LOGIN_TRANSITION_DURATION;setTimeout(()=>{revealLogin();root.classList.add('is-exiting')},skipped?70:0);setTimeout(()=>{removeEventListener('resize',resize);root.remove()},duration)}
  resize();addEventListener('resize',resize,{passive:true});logo.decode?.().catch(()=>{});
  if(VIRALIZER_INTRO_SKIP_ENABLED)skip.addEventListener('click',()=>finish(true));else skip.remove();
  if(reduced){root.classList.add('idea-dissolve','is-branding');setTimeout(()=>finish(true),REDUCED_MOTION_DURATION)}else{if(VIRALIZER_INTRO_SKIP_ENABLED)skipTimer=setTimeout(()=>skip.classList.add('is-visible'),2000);frame=requestAnimationFrame(draw)}
})();
