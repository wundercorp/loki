(() => {
  const root = document.documentElement;
  const banner = document.getElementById('cookie-banner');
  const dismiss = document.getElementById('cookie-dismiss');
  const consentKey = 'loki-cookie-banner-v1';
  const githubStatsBanner = document.querySelector('.github-stats-banner');
  const githubStatsStatus = document.querySelector('[data-github-status]');
  const githubStatElements = {
    stars: document.querySelector('[data-github-stat="stars"]'),
    forks: document.querySelector('[data-github-stat="forks"]'),
    watchers: document.querySelector('[data-github-stat="watchers"]'),
  };
  const githubStatsEndpoint = 'https://api.github.com/repos/wundercorp/loki';
  const githubStatsCacheKey = 'loki-github-stats-v1';
  const githubStatsRefreshInterval = 5 * 60 * 1000;
  let githubStatsLastUpdatedAt = 0;
  let githubStatsRefreshTimer = null;
  const npmStatsBanner = document.querySelector('.npm-stats-banner');
  const npmStatElements = {
    version: document.querySelector('[data-npm-stat="version"]'),
    weekly: document.querySelector('[data-npm-stat="weekly"]'),
    total: document.querySelector('[data-npm-stat="total"]'),
  };
  const npmVersionEndpoint = 'https://registry.npmjs.org/%40wundercorp%2Floki/latest';
  const npmWeeklyDownloadsEndpoint = 'https://api.npmjs.org/downloads/point/last-week/%40wundercorp%2Floki';
  const npmTotalDownloadsEndpoint = 'https://img.shields.io/npm/dt/%40wundercorp%2Floki.json';
  const npmStatsCacheKey = 'loki-npm-stats-v1';
  const npmStatsRefreshInterval = 5 * 60 * 1000;
  let npmStatsLastUpdatedAt = 0;
  let npmStatsRefreshTimer = null;
  const installCommands = {
    curl: { value: 'curl -fsSL https://loki.computer/install.sh | bash', link: false },
    npm: { value: 'npm install -g @wundercorp/loki', link: false },
    github: { value: 'https://github.com/wundercorp/loki', link: true },
  };
  const taglineActions = [
    'evolves with you',
    'works across your tools',
    'automates recurring work',
    'persists session memory',
    'turns intent into action',
  ];
  const installTabs = [...document.querySelectorAll('.install-tab')];
  const installCode = document.querySelector('.install-command-code');
  const installLink = document.querySelector('.install-command-link');
  const tagline = document.querySelector('.tagline');
  const taglineAction = document.getElementById('tagline-action');
  const copyCommand = document.querySelector('.copy-command');
  const copyStatus = document.querySelector('.copy-status');
  const miniInstallCopy = document.querySelector('.mini-install-copy');
  const workflowStages = [...document.querySelectorAll('[data-workflow-stage]')];
  const workflowLogs = [...document.querySelectorAll('[data-workflow-log]')];
  const desktopMock = document.querySelector('.desktop-mock');
  const terminalDemo = document.querySelector('[data-terminal-demo]');
  const scheduleCard = document.querySelector('.schedule-card');
  const workflowConsole = document.querySelector('.workflow-console');
  const footerAsciiArt = document.querySelector('.footer-ascii-art');
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const wait = delay => new Promise(resolve => window.setTimeout(resolve, delay));
  const formatGithubStat = value => new Intl.NumberFormat(undefined, { notation: value >= 10000 ? 'compact' : 'standard', maximumFractionDigits: 1 }).format(value);
  const renderGithubStats = stats => {
    const values = {
      stars: stats.stargazers_count,
      forks: stats.forks_count,
      watchers: stats.subscribers_count,
    };
    for (const [key, value] of Object.entries(values)) {
      if (Number.isFinite(value) && githubStatElements[key]) {
        githubStatElements[key].textContent = formatGithubStat(value);
      }
    }
  };
  const readGithubStatsCache = () => {
    try {
      const cached = JSON.parse(localStorage.getItem(githubStatsCacheKey) || 'null');
      if (!cached || !cached.data || !Number.isFinite(cached.updatedAt)) return null;
      return cached;
    } catch {
      return null;
    }
  };
  const refreshGithubStats = async ({ force = false } = {}) => {
    if (!githubStatsBanner) return;
    const now = Date.now();
    if (!force && githubStatsLastUpdatedAt && now - githubStatsLastUpdatedAt < githubStatsRefreshInterval) return;

    try {
      const response = await fetch(githubStatsEndpoint, {
        headers: { Accept: 'application/vnd.github+json' },
        cache: 'no-store',
      });
      if (!response.ok) throw new Error(`GitHub API returned ${response.status}`);
      const data = await response.json();
      renderGithubStats(data);
      githubStatsLastUpdatedAt = Date.now();
      githubStatsBanner.classList.remove('is-stale');
      if (githubStatsStatus) githubStatsStatus.textContent = 'Live';
      try {
        localStorage.setItem(githubStatsCacheKey, JSON.stringify({ data, updatedAt: githubStatsLastUpdatedAt }));
      } catch {
      }
    } catch {
      githubStatsBanner.classList.add('is-stale');
      if (githubStatsStatus) githubStatsStatus.textContent = 'Cached';
    }
  };
  const initializeGithubStats = () => {
    if (!githubStatsBanner) return;
    const cached = readGithubStatsCache();
    if (cached) {
      renderGithubStats(cached.data);
      githubStatsLastUpdatedAt = cached.updatedAt;
      if (Date.now() - cached.updatedAt >= githubStatsRefreshInterval) {
        githubStatsBanner.classList.add('is-stale');
      }
    }

    refreshGithubStats({ force: true });
    githubStatsRefreshTimer = window.setInterval(() => {
      if (document.visibilityState === 'visible') refreshGithubStats({ force: true });
    }, githubStatsRefreshInterval);

    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible' && Date.now() - githubStatsLastUpdatedAt >= githubStatsRefreshInterval) {
        refreshGithubStats({ force: true });
      }
    });

    window.addEventListener('pagehide', () => {
      if (githubStatsRefreshTimer) window.clearInterval(githubStatsRefreshTimer);
    }, { once: true });
  };
  const formatNpmDownloads = value => new Intl.NumberFormat(undefined, { notation: value >= 1000 ? 'compact' : 'standard', maximumFractionDigits: 1 }).format(value);
  const renderNpmStats = stats => {
    if (npmStatElements.version && stats.version) npmStatElements.version.textContent = `v${String(stats.version).replace(/^v/, '')}`;
    if (npmStatElements.weekly && Number.isFinite(stats.weekly)) npmStatElements.weekly.textContent = `${formatNpmDownloads(stats.weekly)}/week`;
    if (npmStatElements.total && stats.total) npmStatElements.total.textContent = stats.total;
  };
  const readNpmStatsCache = () => {
    try {
      const cached = JSON.parse(localStorage.getItem(npmStatsCacheKey) || 'null');
      if (!cached || !cached.data || !Number.isFinite(cached.updatedAt)) return null;
      return cached;
    } catch {
      return null;
    }
  };
  const refreshNpmStats = async ({ force = false } = {}) => {
    if (!npmStatsBanner) return;
    const now = Date.now();
    if (!force && npmStatsLastUpdatedAt && now - npmStatsLastUpdatedAt < npmStatsRefreshInterval) return;

    try {
      const [versionResponse, weeklyResponse, totalResponse] = await Promise.all([
        fetch(npmVersionEndpoint, { cache: 'no-store' }),
        fetch(npmWeeklyDownloadsEndpoint, { cache: 'no-store' }),
        fetch(npmTotalDownloadsEndpoint, { cache: 'no-store' }),
      ]);
      if (!versionResponse.ok || !weeklyResponse.ok || !totalResponse.ok) throw new Error('NPM stats request failed');
      const [versionData, weeklyData, totalData] = await Promise.all([
        versionResponse.json(),
        weeklyResponse.json(),
        totalResponse.json(),
      ]);
      const data = {
        version: versionData.version,
        weekly: weeklyData.downloads,
        total: totalData.message,
      };
      renderNpmStats(data);
      npmStatsLastUpdatedAt = Date.now();
      npmStatsBanner.classList.remove('is-stale');
      try {
        localStorage.setItem(npmStatsCacheKey, JSON.stringify({ data, updatedAt: npmStatsLastUpdatedAt }));
      } catch {
      }
    } catch {
      npmStatsBanner.classList.add('is-stale');
    }
  };
  const initializeNpmStats = () => {
    if (!npmStatsBanner) return;
    const cached = readNpmStatsCache();
    if (cached) {
      renderNpmStats(cached.data);
      npmStatsLastUpdatedAt = cached.updatedAt;
      if (Date.now() - cached.updatedAt >= npmStatsRefreshInterval) npmStatsBanner.classList.add('is-stale');
    }

    refreshNpmStats({ force: true });
    npmStatsRefreshTimer = window.setInterval(() => {
      if (document.visibilityState === 'visible') refreshNpmStats({ force: true });
    }, npmStatsRefreshInterval);

    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible' && Date.now() - npmStatsLastUpdatedAt >= npmStatsRefreshInterval) {
        refreshNpmStats({ force: true });
      }
    });

    window.addEventListener('pagehide', () => {
      if (npmStatsRefreshTimer) window.clearInterval(npmStatsRefreshTimer);
    }, { once: true });
  };
  const copyText = async value => {
    if (navigator.clipboard?.writeText && window.isSecureContext) {
      await navigator.clipboard.writeText(value);
      return;
    }

    const textarea = document.createElement('textarea');
    textarea.value = value;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    const copied = document.execCommand('copy');
    textarea.remove();
    if (!copied) throw new Error('Copy failed');
  };

  initializeGithubStats();
  initializeNpmStats();

  copyCommand?.addEventListener('click', async () => {
    const activeTab = installTabs.find(tab => tab.classList.contains('is-active'));
    const activeKey = activeTab?.dataset.install ?? 'curl';
    const value = installCommands[activeKey]?.value ?? '';
    const tooltip = copyCommand.querySelector('.copy-tooltip');
    if (!value) return;
    try {
      await copyText(value);
      copyCommand.classList.remove('is-copy-error');
      copyCommand.classList.add('is-copied');
      copyCommand.setAttribute('aria-label', 'Copied');
      copyCommand.setAttribute('title', 'Copied');
      if (tooltip) tooltip.textContent = 'Copied';
      if (copyStatus) copyStatus.textContent = 'Copied to clipboard';
      window.setTimeout(() => {
        copyCommand.classList.remove('is-copied');
        copyCommand.setAttribute('aria-label', 'Copy install command');
        copyCommand.setAttribute('title', 'Copy');
        if (copyStatus) copyStatus.textContent = '';
      }, 1400);
    } catch {
      copyCommand.classList.remove('is-copied');
      copyCommand.classList.add('is-copy-error');
      copyCommand.setAttribute('aria-label', 'Copy failed');
      copyCommand.setAttribute('title', 'Copy failed');
      if (tooltip) tooltip.textContent = 'Copy failed';
      if (copyStatus) copyStatus.textContent = 'Could not copy to clipboard';
      window.setTimeout(() => {
        copyCommand.classList.remove('is-copy-error');
        copyCommand.setAttribute('aria-label', 'Copy install command');
        copyCommand.setAttribute('title', 'Copy');
        if (tooltip) tooltip.textContent = 'Copied';
        if (copyStatus) copyStatus.textContent = '';
      }, 1800);
    }
  });

  miniInstallCopy?.addEventListener('click', async () => {
    const value = miniInstallCopy.dataset.copyValue ?? '';
    const tooltip = miniInstallCopy.querySelector('.copy-tooltip');
    if (!value) return;
    try {
      await copyText(value);
      miniInstallCopy.classList.remove('is-copy-error');
      miniInstallCopy.classList.add('is-copied');
      miniInstallCopy.setAttribute('aria-label', 'Copied install command');
      const icon = miniInstallCopy.querySelector('i');
      icon?.classList.remove('ph-copy');
      icon?.classList.add('ph-check');
      if (tooltip) tooltip.textContent = 'Copied';
      window.setTimeout(() => {
        miniInstallCopy.classList.remove('is-copied');
        miniInstallCopy.setAttribute('aria-label', 'Copy install command');
        icon?.classList.remove('ph-check');
        icon?.classList.add('ph-copy');
      }, 1500);
    } catch {
      miniInstallCopy.classList.remove('is-copied');
      miniInstallCopy.classList.add('is-copy-error');
      miniInstallCopy.setAttribute('aria-label', 'Copy failed');
      if (tooltip) tooltip.textContent = 'Copy failed';
      window.setTimeout(() => {
        miniInstallCopy.classList.remove('is-copy-error');
        miniInstallCopy.setAttribute('aria-label', 'Copy install command');
        if (tooltip) tooltip.textContent = 'Copied';
      }, 1800);
    }
  });

  let workflowManualSelection = false;
  let workflowVisible = false;
  let desktopDemoVisible = false;
  let terminalDemoVisible = false;

  const selectWorkflowStage = (selectedStage, executing = false) => {
    if (!selectedStage) return;
    workflowStages.forEach(item => {
      const isActive = item.dataset.workflowStage === selectedStage;
      item.classList.toggle('is-active', isActive);
      item.setAttribute('aria-pressed', isActive ? 'true' : 'false');
    });
    workflowLogs.forEach(log => {
      const matches = log.dataset.workflowLog === selectedStage;
      log.classList.toggle('is-stage-highlighted', matches);
      log.classList.toggle('is-executing', matches && executing);
    });
  };

  workflowStages.forEach(stage => {
    stage.addEventListener('click', () => {
      workflowManualSelection = true;
      workflowConsole?.classList.remove('is-running');
      workflowConsole?.classList.add('is-complete');
      selectWorkflowStage(stage.dataset.workflowStage, false);
    });
  });

  installTabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const key = tab.dataset.install;
      const config = key ? installCommands[key] : null;
      if (!config || !installCode || !installLink) return;
      installTabs.forEach(item => {
        const active = item === tab;
        item.classList.toggle('is-active', active);
        item.setAttribute('aria-selected', active ? 'true' : 'false');
      });
      installCode.textContent = config.value;
      installCode.hidden = config.link;
      installLink.hidden = !config.link;
      if (config.link) {
        installLink.href = config.value;
        installLink.textContent = config.value;
      }
    });
  });

  if (tagline && taglineAction && !reduceMotion.matches) {
    const typeDelay = 58;
    const eraseDelay = 30;
    const holdDelay = 1800;
    const restartDelay = 260;
    let taglineIndex = 0;

    const sleep = delay => new Promise(resolve => window.setTimeout(resolve, delay));

    const typeAction = async action => {
      taglineAction.textContent = '';
      for (const character of action) {
        taglineAction.textContent += character;
        await sleep(typeDelay);
      }
      tagline.setAttribute('aria-label', `The agent that ${action}`);
    };

    const eraseAction = async () => {
      while (taglineAction.textContent) {
        taglineAction.textContent = taglineAction.textContent.slice(0, -1);
        await sleep(eraseDelay);
      }
    };

    const runTypewriter = async () => {
      while (true) {
        const action = taglineActions[taglineIndex];
        await typeAction(action);
        await sleep(holdDelay);
        await eraseAction();
        await sleep(restartDelay);
        taglineIndex = (taglineIndex + 1) % taglineActions.length;
      }
    };

    runTypewriter();
  }

  const typeWidgetText = async (element, speed = 24) => {
    if (!element) return;
    const finalText = element.dataset.typeText ?? element.textContent ?? '';
    const caret = element.parentElement?.querySelector('.widget-caret');
    element.textContent = '';
    caret?.classList.add('is-active');
    for (const character of finalText) {
      element.textContent += character;
      await wait(speed);
    }
    caret?.classList.remove('is-active');
  };

  const revealElement = element => {
    element?.classList.add('is-visible');
  };

  const runDesktopDemo = async () => {
    if (!desktopMock || reduceMotion.matches) return;
    const userStep = desktopMock.querySelector('[data-desktop-step="user"]');
    const agentStep = desktopMock.querySelector('[data-desktop-step="agent"]');
    const terminalStep = desktopMock.querySelector('[data-desktop-step="terminal"]');
    const userText = userStep?.querySelector('[data-type-text]');
    const agentText = agentStep?.querySelector('[data-type-text]');
    const commandText = terminalStep?.querySelector('[data-type-text]');
    const process = desktopMock.querySelector('[data-desktop-process]');
    const output = desktopMock.querySelector('[data-desktop-output]');
    const review = desktopMock.querySelector('[data-desktop-review]');

    while (desktopMock.isConnected) {
      if (!desktopDemoVisible) {
        await wait(500);
        continue;
      }
      [agentStep, terminalStep, process, output, review].forEach(element => element?.classList.remove('is-visible', 'is-running'));
      if (userText) userText.textContent = '';
      if (agentText) agentText.textContent = agentText.dataset.typeText ?? '';
      if (commandText) commandText.textContent = commandText.dataset.typeText ?? '';
      await wait(420);
      await typeWidgetText(userText, 24);
      await wait(420);
      revealElement(agentStep);
      await typeWidgetText(agentText, 18);
      await wait(480);
      revealElement(terminalStep);
      await typeWidgetText(commandText, 34);
      await wait(220);
      revealElement(process);
      process?.classList.add('is-running');
      await wait(1250);
      process?.classList.remove('is-running');
      revealElement(output);
      await wait(500);
      revealElement(review);
      review?.classList.add('is-running');
      await wait(1450);
      review?.classList.remove('is-running');
      if (review) review.textContent = '✓ diff reviewed · release notes next';
      await wait(3600);
      if (review) review.textContent = 'reviewing diff for risky changes...';
    }
  };

  const runTerminalDemo = async () => {
    if (!terminalDemo || reduceMotion.matches) return;
    const commands = [...terminalDemo.querySelectorAll('[data-type-text]')];
    const ready = terminalDemo.querySelector('[data-terminal-step="ready"]');
    const context = terminalDemo.querySelector('[data-terminal-step="context"]');
    const tests = terminalDemo.querySelector('[data-terminal-step="tests"]');
    const result = terminalDemo.querySelector('[data-terminal-step="result"]');

    while (terminalDemo.isConnected) {
      if (!terminalDemoVisible) {
        await wait(500);
        continue;
      }
      [ready, context, tests, result].forEach(element => element?.classList.remove('is-visible', 'is-running'));
      commands.forEach(element => { element.textContent = element.dataset.typeText ?? ''; });
      await wait(620);
      await typeWidgetText(commands[0], 65);
      await wait(260);
      revealElement(ready);
      await wait(720);
      await typeWidgetText(commands[1], 29);
      await wait(360);
      revealElement(context);
      context?.classList.add('is-running');
      await wait(1350);
      context?.classList.remove('is-running');
      revealElement(tests);
      tests?.classList.add('is-running');
      await wait(1500);
      tests?.classList.remove('is-running');
      revealElement(result);
      await wait(3700);
    }
  };

  const scrambleCharacters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789░▒▓<>/\\';

  const scrambleElement = async (element, duration = 620) => {
    const finalText = element.dataset.scrambleText ?? element.textContent ?? '';
    element.dataset.scrambleText = finalText;
    const startedAt = performance.now();

    while (true) {
      const elapsed = performance.now() - startedAt;
      const progress = Math.min(elapsed / duration, 1);
      const revealedCharacters = Math.floor(finalText.length * progress);
      element.textContent = [...finalText].map((character, index) => {
        if (/\s/.test(character) || index < revealedCharacters) return character;
        return scrambleCharacters[Math.floor(Math.random() * scrambleCharacters.length)];
      }).join('');
      if (progress >= 1) break;
      await wait(32);
    }
    element.textContent = finalText;
  };

  const decodeSchedule = async () => {
    if (!scheduleCard || scheduleCard.classList.contains('is-decoded')) return;
    const rows = [...scheduleCard.querySelectorAll('.schedule-row')];
    for (const row of rows) {
      row.classList.add('is-decoding');
      await Promise.all([...row.querySelectorAll('[data-scramble]')].map(element => scrambleElement(element)));
      row.classList.remove('is-decoding');
      await wait(110);
    }
    scheduleCard.classList.add('is-decoded');
  };

  const runWorkflowDemo = async () => {
    if (!workflowConsole || reduceMotion.matches) return;
    const stages = ['understand', 'operate', 'delegate', 'deliver'];
    while (!workflowManualSelection && workflowConsole.isConnected) {
      if (!workflowVisible) {
        await wait(500);
        continue;
      }
      workflowConsole.classList.remove('is-complete');
      workflowConsole.classList.add('is-running');
      for (const stage of stages) {
        if (workflowManualSelection || !workflowVisible) break;
        selectWorkflowStage(stage, true);
        await wait(stage === 'delegate' ? 1750 : 1450);
      }
      if (workflowManualSelection) break;
      workflowLogs.forEach(log => log.classList.remove('is-executing'));
      workflowConsole.classList.remove('is-running');
      workflowConsole.classList.add('is-complete');
      await wait(3300);
    }
  };

  if (!reduceMotion.matches) {
    root.classList.add('motion-ready');
    desktopMock?.querySelectorAll('[data-type-text]').forEach(element => { element.textContent = ''; });
    terminalDemo?.querySelectorAll('[data-type-text]').forEach(element => { element.textContent = ''; });
    scheduleCard?.querySelectorAll('[data-scramble]').forEach(element => {
      const finalText = element.textContent ?? '';
      element.dataset.scrambleText = finalText;
      element.textContent = [...finalText].map(character => {
        if (/\s/.test(character)) return character;
        return scrambleCharacters[Math.floor(Math.random() * scrambleCharacters.length)];
      }).join('');
    });

    if (scheduleCard || workflowConsole || desktopMock || terminalDemo || footerAsciiArt) {
      const contentObserver = new IntersectionObserver(entries => {
        entries.forEach(entry => {
          if (entry.target === scheduleCard && entry.isIntersecting) {
            decodeSchedule();
            contentObserver.unobserve(scheduleCard);
          }
          if (entry.target === workflowConsole) {
            workflowVisible = entry.isIntersecting;
          }
          if (entry.target === desktopMock) {
            desktopDemoVisible = entry.isIntersecting;
          }
          if (entry.target === terminalDemo) {
            terminalDemoVisible = entry.isIntersecting;
          }
          if (entry.target === footerAsciiArt) {
            footerAsciiArt.classList.toggle('is-mesh-active', entry.isIntersecting);
          }
        });
      }, { threshold: 0.18, rootMargin: '120px 0px' });
      if (scheduleCard) contentObserver.observe(scheduleCard);
      if (workflowConsole) contentObserver.observe(workflowConsole);
      if (desktopMock) contentObserver.observe(desktopMock);
      if (terminalDemo) contentObserver.observe(terminalDemo);
      if (footerAsciiArt) contentObserver.observe(footerAsciiArt);
    }

    runDesktopDemo();
    runTerminalDemo();
    runWorkflowDemo();
  } else {
    scheduleCard?.classList.add('is-decoded');
    workflowConsole?.classList.add('is-complete');
  }

  try {
    if (banner && localStorage.getItem(consentKey) !== 'dismissed') {
      banner.hidden = false;
    }
    dismiss?.addEventListener('click', () => {
      localStorage.setItem(consentKey, 'dismissed');
      banner.hidden = true;
    });
  } catch {
    if (banner) {
      banner.hidden = false;
    }
    dismiss?.addEventListener('click', () => {
      banner.hidden = true;
    });
  }
})();
