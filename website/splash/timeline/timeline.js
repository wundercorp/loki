(() => {
  const repository = 'wundercorp/loki';
  const timelineList = document.getElementById('timeline-list');
  const timelineEmpty = document.getElementById('timeline-empty');
  const statusElement = document.querySelector('[data-timeline-status]');
  const rangeElement = document.querySelector('[data-timeline-range]');
  const liveElement = document.querySelector('.timeline-live');
  const cacheKey = 'loki-timeline-commits-v1';
  const windowDays = 14;
  const refreshInterval = 10 * 60 * 1000;
  let lastUpdatedAt = 0;
  let refreshTimer = 0;

  const escapeHtml = value => String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');

  const startOfWindow = () => new Date(Date.now() - windowDays * 24 * 60 * 60 * 1000);

  const formatDay = value => new Intl.DateTimeFormat(undefined, {
    weekday: 'long',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  }).format(value);

  const formatTime = value => new Intl.DateTimeFormat(undefined, {
    hour: 'numeric',
    minute: '2-digit',
  }).format(value);

  const dateKey = value => {
    const year = value.getFullYear();
    const month = String(value.getMonth() + 1).padStart(2, '0');
    const day = String(value.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  };

  const normalizeCommit = commit => {
    const committedAt = commit?.commit?.committer?.date || commit?.commit?.author?.date;
    const authorName = commit?.author?.login || commit?.commit?.author?.name || 'Contributor';
    const message = String(commit?.commit?.message || '').split('\n')[0].trim();
    if (!commit?.sha || !committedAt || !message) return null;
    return {
      sha: commit.sha,
      message,
      committedAt,
      authorName,
      url: commit.html_url || `https://github.com/${repository}/commit/${commit.sha}`,
    };
  };

  const renderTimeline = commits => {
    if (!timelineList) return;
    const cutoff = startOfWindow();
    const normalized = commits
      .map(normalizeCommit)
      .filter(Boolean)
      .filter(commit => new Date(commit.committedAt) >= cutoff)
      .sort((left, right) => new Date(right.committedAt) - new Date(left.committedAt));

    if (!normalized.length) {
      timelineList.innerHTML = '';
      timelineList.setAttribute('aria-busy', 'false');
      if (timelineEmpty) timelineEmpty.hidden = false;
      return;
    }

    if (timelineEmpty) timelineEmpty.hidden = true;
    const groups = new Map();
    normalized.forEach(commit => {
      const date = new Date(commit.committedAt);
      const key = dateKey(date);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(commit);
    });

    timelineList.innerHTML = Array.from(groups.entries()).map(([, group]) => {
      const firstDate = new Date(group[0].committedAt);
      const commitMarkup = group.map(commit => {
        const date = new Date(commit.committedAt);
        return `<article class="timeline-commit">
          <time class="timeline-time" datetime="${escapeHtml(commit.committedAt)}">${escapeHtml(formatTime(date))}</time>
          <div class="timeline-commit-main">
            <a class="timeline-commit-title" href="${escapeHtml(commit.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(commit.message)}</a>
            <div class="timeline-commit-meta">
              <span>${escapeHtml(commit.authorName)}</span>
              <span class="timeline-separator" aria-hidden="true">·</span>
              <a class="timeline-sha" href="${escapeHtml(commit.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(commit.sha.slice(0, 7))}</a>
            </div>
          </div>
        </article>`;
      }).join('');
      return `<section class="timeline-day">
        <h2 class="timeline-date">${escapeHtml(formatDay(firstDate))}</h2>
        ${commitMarkup}
      </section>`;
    }).join('');
    timelineList.setAttribute('aria-busy', 'false');
  };

  const setStatus = (label, cached = false) => {
    if (statusElement) statusElement.textContent = label;
    liveElement?.classList.toggle('is-cached', cached);
  };

  const readCache = () => {
    try {
      const cached = JSON.parse(localStorage.getItem(cacheKey) || 'null');
      if (!cached || !Array.isArray(cached.commits) || !Number.isFinite(cached.updatedAt)) return null;
      return cached;
    } catch {
      return null;
    }
  };

  const writeCache = commits => {
    try {
      localStorage.setItem(cacheKey, JSON.stringify({ commits, updatedAt: Date.now() }));
    } catch {
    }
  };

  const refreshTimeline = async ({ force = false } = {}) => {
    const now = Date.now();
    if (!force && lastUpdatedAt && now - lastUpdatedAt < refreshInterval) return;
    const since = startOfWindow().toISOString();
    const endpoint = `https://api.github.com/repos/${repository}/commits?sha=main&per_page=100&since=${encodeURIComponent(since)}`;

    try {
      const response = await fetch(endpoint, {
        cache: 'no-store',
        headers: { Accept: 'application/vnd.github+json' },
      });
      if (!response.ok) throw new Error(`GitHub returned ${response.status}`);
      const commits = await response.json();
      if (!Array.isArray(commits)) throw new Error('Unexpected GitHub response');
      renderTimeline(commits);
      writeCache(commits);
      lastUpdatedAt = Date.now();
      setStatus('Live');
    } catch {
      const cached = readCache();
      if (cached) {
        renderTimeline(cached.commits);
        lastUpdatedAt = cached.updatedAt;
        setStatus('Cached', true);
      } else {
        setStatus('GitHub unavailable', true);
        timelineList?.setAttribute('aria-busy', 'false');
        if (timelineList) timelineList.innerHTML = '<div class="timeline-loading"><span class="timeline-loading-dot" aria-hidden="true"></span><span>Unable to load repository history right now.</span></div>';
      }
    }
  };

  const initialize = () => {
    if (rangeElement) rangeElement.textContent = `Past ${windowDays} days`;
    const cached = readCache();
    if (cached) {
      renderTimeline(cached.commits);
      lastUpdatedAt = cached.updatedAt;
      setStatus('Cached', true);
    }
    refreshTimeline({ force: true });
    refreshTimer = window.setInterval(() => {
      if (document.visibilityState === 'visible') refreshTimeline({ force: true });
    }, refreshInterval);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible' && Date.now() - lastUpdatedAt >= refreshInterval) {
        refreshTimeline({ force: true });
      }
    });
    window.addEventListener('pagehide', () => {
      if (refreshTimer) window.clearInterval(refreshTimer);
    }, { once: true });
  };

  initialize();
})();
