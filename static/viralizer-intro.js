(() => {
  if (!document.body.classList.contains('intro-active')) return;
  const login = document.querySelector('main.card');
  const revealLogin = () => {
    document.body.classList.remove('intro-active');
    if (login) {
      login.style.opacity = '1';
      login.style.transform = 'scale(1)';
      login.style.filter = 'blur(0)';
    }
  };
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
    revealLogin();
    return;
  }
  let finished = false, fallbackTimer = 0, skipTimer = 0;
  const root = document.createElement('div');
  root.className = 'viralizer-intro';
  root.setAttribute('role', 'presentation');
  root.innerHTML = `<video class="viralizer-intro-video" muted playsinline preload="auto" aria-hidden="true"><source src="/static/viralizer-login-intro.mp4?v=1" type="video/mp4"></video><div class="viralizer-intro-shade" aria-hidden="true"></div><div class="viralizer-intro-loader" aria-hidden="true"><span></span></div><button class="viralizer-intro-sound" type="button" aria-label="Turn intro sound on">🔊 Sound on</button><button class="viralizer-intro-skip" type="button" aria-label="Skip Viralizer introduction">Skip intro</button>`;
  document.body.prepend(root);
  const video = root.querySelector('.viralizer-intro-video');
  const skip = root.querySelector('.viralizer-intro-skip');
  const sound = root.querySelector('.viralizer-intro-sound');
  const loader = root.querySelector('.viralizer-intro-loader');
  const finish = (quick = false) => {
    if (finished) return;
    finished = true;
    clearTimeout(fallbackTimer);
    clearTimeout(skipTimer);
    video.pause();
    root.classList.add('is-exiting');
    setTimeout(revealLogin, quick ? 80 : 260);
    setTimeout(() => root.remove(), quick ? 520 : 850);
  };
  const showVideo = () => {
    loader.classList.add('is-hidden');
    video.classList.add('is-ready');
  };
  video.addEventListener('playing', showVideo, { once: true });
  video.addEventListener('canplay', showVideo, { once: true });
  video.addEventListener('ended', () => finish(false), { once: true });
  video.addEventListener('error', () => finish(true), { once: true });
  sound.addEventListener('click', () => {
    video.muted = !video.muted;
    sound.textContent = video.muted ? '🔊 Sound on' : '🔇 Sound off';
    sound.setAttribute('aria-label', video.muted ? 'Turn intro sound on' : 'Turn intro sound off');
    if (video.paused) video.play().catch(() => {});
  });
  skip.addEventListener('click', () => finish(true));  skipTimer = setTimeout(() => skip.classList.add('is-visible'), 2000);
  fallbackTimer = setTimeout(() => finish(true), 14000);
  const playback = video.play();
  if (playback && typeof playback.catch === 'function') playback.catch(() => finish(true));
})();