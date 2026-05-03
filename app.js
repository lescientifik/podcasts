/* Carnets de recherche — front-end vanilla : fetch feed.xml, render cards,
   localStorage pour la position de lecture, la vitesse, et l'indicateur "écouté". */
(() => {
  'use strict';

  const ITUNES_NS = 'http://www.itunes.com/dtds/podcast-1.0.dtd';
  const FEED_URL = 'feed.xml';
  const REPO_URL = 'https://github.com/lescientifik/podcasts';
  const SPEEDS = [1, 1.25, 1.5, 2];
  const DATE_FMT = new Intl.DateTimeFormat('fr-FR', { dateStyle: 'long' });

  const $episodes = document.getElementById('episodes');
  const $empty = document.getElementById('empty-state');
  const $search = document.getElementById('search');

  // -- localStorage helpers (graceful no-op si bloqué)

  function lsGet(key, fallback) {
    try {
      const v = localStorage.getItem(key);
      return v === null ? fallback : v;
    } catch (_) {
      return fallback;
    }
  }

  function lsSet(key, value) {
    try { localStorage.setItem(key, value); } catch (_) { /* ignore */ }
  }

  // -- helpers

  function fmtDate(rfc822) {
    const d = new Date(rfc822);
    return isNaN(d.getTime()) ? rfc822 : DATE_FMT.format(d);
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function getText(el, name) {
    const e = el.getElementsByTagName(name)[0];
    return e ? (e.textContent || '').trim() : '';
  }

  function getNSText(el, ns, name) {
    const e = el.getElementsByTagNameNS(ns, name)[0];
    return e ? (e.textContent || '').trim() : '';
  }

  function getNSAttr(el, ns, name, attr) {
    const e = el.getElementsByTagNameNS(ns, name)[0];
    return e ? e.getAttribute(attr) || '' : '';
  }

  // -- parsing

  function parseEpisode(item) {
    const enclosure = item.getElementsByTagName('enclosure')[0];
    return {
      guid: getText(item, 'guid'),
      title: getText(item, 'title'),
      description: getText(item, 'description'),
      pubDate: getText(item, 'pubDate'),
      duration: getNSText(item, ITUNES_NS, 'duration'),
      cover: getNSAttr(item, ITUNES_NS, 'image', 'href'),
      mp3: enclosure ? enclosure.getAttribute('url') : '',
    };
  }

  // -- rendering

  function buildCard(ep) {
    const li = document.createElement('li');
    li.className = 'episode';
    li.dataset.guid = ep.guid;
    li.dataset.title = ep.title.toLowerCase();

    const isListened = lsGet('listened:' + ep.guid, '0') === '1';
    if (isListened) li.classList.add('listened');

    const notesUrl = `${REPO_URL}/blob/main/episodes/${ep.guid}.md`;
    const transcriptUrl = `${REPO_URL}/blob/main/episodes/${ep.guid}.transcript.md`;

    li.innerHTML = `
      <div class="episode-head">
        <img class="episode-cover" src="${ep.cover}" alt="" loading="lazy" width="120" height="120" />
        <div class="episode-meta">
          <h2 class="episode-title">
            <a href="#${ep.guid}" id="${ep.guid}">${escapeHtml(ep.title)}</a>
          </h2>
          <p class="episode-sub">
            <span class="ep-date">${escapeHtml(fmtDate(ep.pubDate))}</span>
            ${ep.duration ? `<span aria-hidden="true">·</span><span class="ep-duration">${escapeHtml(ep.duration)}</span>` : ''}
            <span class="listened-badge" ${isListened ? '' : 'hidden'}>· écouté ✓</span>
          </p>
        </div>
      </div>
      <p class="episode-description">${escapeHtml(ep.description)}</p>
      <div class="episode-player">
        <audio controls preload="none" src="${ep.mp3}"></audio>
      </div>
      <div class="episode-controls">
        <label class="speed-control">
          Vitesse
          <select aria-label="Vitesse de lecture">
            ${SPEEDS.map(s => `<option value="${s}">${s}×</option>`).join('')}
          </select>
        </label>
        <span class="episode-links">
          <a href="${ep.mp3}" download>⬇ MP3</a>
          <a href="${transcriptUrl}" target="_blank" rel="noopener noreferrer">📝 Transcript</a>
          <a href="${notesUrl}" target="_blank" rel="noopener noreferrer">📄 Notes</a>
        </span>
      </div>
    `;

    wireCard(li, ep);
    return li;
  }

  function wireCard(li, ep) {
    const audio = li.querySelector('audio');
    const select = li.querySelector('select');
    const badge = li.querySelector('.listened-badge');
    const positionKey = 'pos:' + ep.guid;
    const speedKey = 'speed:' + ep.guid;
    const listenedKey = 'listened:' + ep.guid;

    // Vitesse : restaure ou défaut 1×
    const savedSpeed = parseFloat(lsGet(speedKey, '1'));
    const speed = SPEEDS.includes(savedSpeed) ? savedSpeed : 1;
    select.value = String(speed);
    audio.playbackRate = speed;
    select.addEventListener('change', () => {
      const v = parseFloat(select.value) || 1;
      audio.playbackRate = v;
      lsSet(speedKey, String(v));
    });

    // Reprise de position : on n'applique qu'au premier `play` pour éviter
    // d'écraser un seek manuel ou de courir avant que `duration` soit connue.
    let restored = false;
    audio.addEventListener('play', () => {
      if (restored) return;
      const pos = parseFloat(lsGet(positionKey, '0')) || 0;
      const dur = audio.duration;
      if (pos > 5 && (!isFinite(dur) || pos < dur - 5)) {
        audio.currentTime = pos;
      }
      restored = true;
    });
    audio.addEventListener('timeupdate', () => {
      lsSet(positionKey, String(audio.currentTime));
    });

    // Indicateur "écouté" : se déclenche à la fin du fichier.
    audio.addEventListener('ended', () => {
      lsSet(listenedKey, '1');
      lsSet(positionKey, '0');
      li.classList.add('listened');
      if (badge) badge.removeAttribute('hidden');
    });
  }

  // -- search

  function applyFilter() {
    const q = ($search.value || '').trim().toLowerCase();
    let visible = 0;
    for (const li of $episodes.children) {
      if (!(li instanceof HTMLElement)) continue;
      const t = li.dataset.title || '';
      const match = !q || t.includes(q);
      li.hidden = !match;
      if (match) visible++;
    }
    $empty.hidden = visible !== 0;
  }

  // -- entrypoint

  async function loadFeed() {
    let xml;
    try {
      const r = await fetch(FEED_URL, { cache: 'no-store' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const txt = await r.text();
      xml = new DOMParser().parseFromString(txt, 'application/xml');
      if (xml.querySelector('parsererror')) throw new Error('XML invalide');
    } catch (err) {
      $episodes.innerHTML = '';
      const li = document.createElement('li');
      li.className = 'placeholder';
      li.textContent = `Impossible de charger le flux : ${err.message}`;
      $episodes.appendChild(li);
      return;
    }

    const items = Array.from(xml.querySelectorAll('channel > item'));
    $episodes.innerHTML = '';

    if (items.length === 0) {
      const li = document.createElement('li');
      li.className = 'placeholder';
      li.textContent = 'Aucun épisode pour le moment. Le premier arrive bientôt.';
      $episodes.appendChild(li);
      return;
    }

    for (const item of items) {
      $episodes.appendChild(buildCard(parseEpisode(item)));
    }
    applyFilter();

    // Scroll vers l'ancre une fois les cartes rendues
    if (location.hash) {
      const target = document.getElementById(location.hash.slice(1));
      if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }

  $search.addEventListener('input', applyFilter);
  loadFeed();
})();
