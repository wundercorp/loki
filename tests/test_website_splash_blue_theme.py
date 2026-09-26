from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPLASH = ROOT / "website" / "splash"


def test_splash_uses_blue_brand_theme_and_action_pitch():
    html = (SPLASH / "index.html").read_text()
    css = (SPLASH / "site.css").read_text()
    javascript = (SPLASH / "site.js").read_text()

    assert 'content="#030b1a"' in html
    assert 'The agent that&nbsp;</span><strong class="tagline-action"' in html
    assert 'data-install="github">github</button>' in html
    assert '>evolves with you</strong>' in html
    assert "--blue-3: #60a5fa" in css
    assert "--green-" not in css
    assert "'works across your tools'" in javascript
    assert "'automates recurring work'" in javascript
    assert "'persists session memory'" in javascript
    assert "'turns intent into action'" in javascript
    assert 'const typeDelay = 58' in javascript
    assert 'const eraseDelay = 30' in javascript
    assert 'runTypewriter();' in javascript
    assert 'repeating-linear-gradient' in css


def test_github_install_tab_exposes_a_real_link():
    html = (SPLASH / "index.html").read_text()
    javascript = (SPLASH / "site.js").read_text()

    assert 'class="install-command-link"' in html
    assert 'href="https://github.com/wundercorp/loki"' in html
    assert 'target="_blank"' in html
    assert "github: { value: 'https://github.com/wundercorp/loki', link: true }" in javascript
    assert "installLink.hidden = !config.link" in javascript


def test_splash_has_repo_cta_live_github_stats_and_agent_alignment_fix():
    html = (SPLASH / "index.html").read_text()
    css = (SPLASH / "site.css").read_text()
    javascript = (SPLASH / "site.js").read_text()

    assert 'class="github-stats-banner"' in html
    assert '>wundercorp/loki</strong>' in html
    assert 'data-github-stat="stars"' in html
    assert 'data-github-stat="forks"' in html
    assert 'data-github-stat="watchers"' in html
    assert "https://api.github.com/repos/wundercorp/loki" in javascript
    assert "githubStatsRefreshInterval = 5 * 60 * 1000" in javascript
    assert 'subscribers_count' in javascript
    assert 'class="repo-button"' in html
    assert '<span>View Repo</span>' in html
    assert '<span>Join Discord</span>' in html
    assert '█████╗  ██████╗  ███████╗███╗   ██╗████████╗' in html
    assert '.github-stats-banner {' in css
    assert '.hero-actions {' in css


def test_splash_has_live_npm_stats_banner_below_hero():
    html = (SPLASH / "index.html").read_text()
    css = (SPLASH / "site.css").read_text()
    javascript = (SPLASH / "site.js").read_text()

    assert 'class="npm-stats-banner"' in html
    assert 'href="https://www.npmjs.com/package/@wundercorp/loki"' in html
    assert 'data-npm-stat="version"' in html
    assert 'data-npm-stat="weekly"' in html
    assert 'data-npm-stat="total"' in html
    assert 'hello@wundercorp.co' not in html
    assert 'Using Loki Agent at your company?' not in html
    assert 'https://registry.npmjs.org/%40wundercorp%2Floki/latest' in javascript
    assert 'https://api.npmjs.org/downloads/point/last-week/%40wundercorp%2Floki' in javascript
    assert 'https://img.shields.io/npm/dt/%40wundercorp%2Floki.json' in javascript
    assert 'npmStatsRefreshInterval = 5 * 60 * 1000' in javascript
    assert '.npm-stats-banner {' in css
