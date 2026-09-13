(() => {
  'use strict';
  const slides = [...document.querySelectorAll('.slide')];
  const start = document.querySelector('.presentation-start');
  const controls = document.querySelector('.presentation-controls');
  const previous = document.querySelector('.slide-prev');
  const next = document.querySelector('.slide-next');
  const close = document.querySelector('.presentation-exit');
  const counter = document.querySelector('.slide-counter');
  const status = document.querySelector('.slide-status');
  const progress = document.querySelector('.reading-progress');
  let presenting = false;
  let current = 0;
  let savedScroll = 0;
  let savedHash = '';
  let returnFocus = null;

  function showSlide(index) {
    current = Math.min(Math.max(index, 0), slides.length - 1);
    slides.forEach((slide, i) => {
      const active = i === current;
      slide.classList.toggle('is-active', active);
      slide.inert = !active;
      if (active) slide.removeAttribute('aria-hidden');
      else slide.setAttribute('aria-hidden', 'true');
    });
    const slide = slides[current];
    slide.scrollTop = 0;
    counter.textContent = `${String(current + 1).padStart(2, '0')} / ${slides.length}`;
    status.textContent = slide.dataset.title;
    previous.disabled = current === 0;
    next.disabled = current === slides.length - 1;
    const heading = slide.querySelector('h1, h2');
    heading.setAttribute('tabindex', '-1');
    heading.focus({ preventScroll: true });
  }

  function enterPresentation() {
    savedScroll = window.scrollY;
    savedHash = location.hash;
    returnFocus = document.activeElement;
    presenting = true;
    document.body.classList.add('is-presenting');
    controls.hidden = false;
    window.scrollTo({ top: 0, behavior: 'instant' });
    showSlide(0);
  }

  function exitPresentation() {
    if (!presenting) return;
    presenting = false;
    document.body.classList.remove('is-presenting');
    controls.hidden = true;
    slides.forEach(slide => {
      slide.classList.remove('is-active');
      slide.inert = false;
      slide.removeAttribute('aria-hidden');
      slide.querySelector('h1, h2').removeAttribute('tabindex');
    });
    if (location.hash !== savedHash) history.replaceState(null, '', location.pathname + location.search + savedHash);
    window.scrollTo({ top: savedScroll, behavior: 'instant' });
    returnFocus?.focus({ preventScroll: true });
  }

  document.querySelector('.direction-grid').addEventListener('click', event => {
    const link = event.target.closest('a[href^="#"]');
    if (!presenting || !link) return;
    const index = slides.findIndex(slide => `#${slide.id}` === link.getAttribute('href'));
    if (index >= 0) {
      event.preventDefault();
      showSlide(index);
    }
  });

  start.hidden = false;
  start.addEventListener('click', enterPresentation);
  close.addEventListener('click', exitPresentation);
  previous.addEventListener('click', () => showSlide(current - 1));
  next.addEventListener('click', () => showSlide(current + 1));
  document.addEventListener('keydown', event => {
    if (!presenting || event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      exitPresentation();
      return;
    }
    const interactive = event.target.closest('a, button, input, select, textarea, [contenteditable="true"]');
    if (interactive && (event.key === ' ' || event.key === 'Enter')) return;
    const moves = { ArrowRight: 1, PageDown: 1, ArrowLeft: -1, PageUp: -1, ' ': event.shiftKey ? -1 : 1 };
    if (event.key in moves) {
      event.preventDefault();
      showSlide(current + moves[event.key]);
    } else if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault();
      showSlide(event.key === 'Home' ? 0 : slides.length - 1);
    }
  });

  let pending = false;
  function updateProgress() {
    const height = document.documentElement.scrollHeight - window.innerHeight;
    progress.style.width = `${height > 0 ? Math.min(100, Math.max(0, window.scrollY / height * 100)) : 0}%`;
    pending = false;
  }
  window.addEventListener('scroll', () => {
    if (!pending) { requestAnimationFrame(updateProgress); pending = true; }
  }, { passive: true });
  window.addEventListener('resize', updateProgress);
  updateProgress();
})();
