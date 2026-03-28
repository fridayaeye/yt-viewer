#!/usr/bin/env node
/**
 * YouTube Viewer Dashboard
 * Single-file Express server with inline HTML
 * Dark theme, mobile responsive, auto-refresh every 30s
 */

const express = require('express');
const https = require('https');
const http = require('http');
const crypto = require('crypto');

const app = express();
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// ── Config ──────────────────────────────────────────────────────────────
const PORT = process.env.PORT || 3000;
const RAILWAY_TOKEN = process.env.RAILWAY_TOKEN || '';
const GH_TOKEN = process.env.GH_TOKEN || '';
const DASHBOARD_PASS = process.env.DASHBOARD_PASS || 'stark369';
const RAILWAY_PROJECT_ID = process.env.RAILWAY_PROJECT_ID || 'fb557282-4585-4e58-9856-584b783fa593';
const RAILWAY_SERVICE_ID = process.env.RAILWAY_SERVICE_ID || '5e96b607-29b4-4025-a148-2c6b3eb59899';
const RAILWAY_ENV_ID = process.env.RAILWAY_ENV_ID || 'e3b643e5-4811-4797-8cf0-86df8633efeb';
const GH_REPO = process.env.GH_REPO || 'fridayaeye/yt-viewer';
const GH_WORKFLOW = process.env.GH_WORKFLOW || 'viewer.yml';

// ── Simple session store ─────────────────────────────────────────────────
const sessions = new Map();

function createSession() {
  const token = crypto.randomBytes(32).toString('hex');
  sessions.set(token, Date.now());
  return token;
}

function isValidSession(token) {
  if (!token || !sessions.has(token)) return false;
  const created = sessions.get(token);
  if (Date.now() - created > 24 * 60 * 60 * 1000) {
    sessions.delete(token);
    return false;
  }
  return true;
}

// ── HTTP helpers ──────────────────────────────────────────────────────────
function httpsRequest(options, body = null) {
  return new Promise((resolve, reject) => {
    const req = https.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => (data += chunk));
      res.on('end', () => {
        try {
          resolve({ status: res.statusCode, body: JSON.parse(data), headers: res.headers });
        } catch {
          resolve({ status: res.statusCode, body: data, headers: res.headers });
        }
      });
    });
    req.on('error', reject);
    req.setTimeout(10000, () => { req.destroy(); reject(new Error('timeout')); });
    if (body) req.write(body);
    req.end();
  });
}

// ── Railway GraphQL ───────────────────────────────────────────────────────
async function railwayGQL(query, variables = {}) {
  const body = JSON.stringify({ query, variables });
  const res = await httpsRequest({
    hostname: 'backboard.railway.app',
    path: '/graphql/v2',
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${RAILWAY_TOKEN}`,
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(body),
    }
  }, body);
  if (res.body && res.body.errors) {
    console.error('[Railway GQL error]', JSON.stringify(res.body.errors));
  }
  return res.body;
}

// ── GitHub API ────────────────────────────────────────────────────────────
async function githubGet(path) {
  const res = await httpsRequest({
    hostname: 'api.github.com',
    path,
    method: 'GET',
    headers: {
      'Authorization': `token ${GH_TOKEN}`,
      'User-Agent': 'yt-dashboard/1.0',
      'Accept': 'application/vnd.github.v3+json',
    }
  });
  return res.body;
}

async function githubPost(path, body) {
  const bodyStr = JSON.stringify(body);
  const res = await httpsRequest({
    hostname: 'api.github.com',
    path,
    method: 'POST',
    headers: {
      'Authorization': `token ${GH_TOKEN}`,
      'User-Agent': 'yt-dashboard/1.0',
      'Accept': 'application/vnd.github.v3+json',
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(bodyStr),
    }
  }, bodyStr);
  return res;
}

// ── Data Fetchers ─────────────────────────────────────────────────────────
async function getRailwayEnvVars() {
  const data = await railwayGQL(`
    query {
      variables(
        projectId: "${RAILWAY_PROJECT_ID}"
        serviceId: "${RAILWAY_SERVICE_ID}"
        environmentId: "${RAILWAY_ENV_ID}"
      )
    }
  `);
  return data?.data?.variables || {};
}

async function getRailwayServiceStatus() {
  const data = await railwayGQL(`
    query {
      deployments(
        input: {
          projectId: "${RAILWAY_PROJECT_ID}"
          serviceId: "${RAILWAY_SERVICE_ID}"
          environmentId: "${RAILWAY_ENV_ID}"
        }
      ) {
        edges {
          node {
            id
            status
            createdAt
            url
          }
        }
      }
    }
  `);
  const edges = data?.data?.deployments?.edges || [];
  if (edges.length === 0) return { status: 'UNKNOWN', deployment: null };
  const latest = edges[0].node;
  return { status: latest.status, deployment: latest };
}

async function getGitHubRuns() {
  const data = await githubGet(`/repos/${GH_REPO}/actions/runs?per_page=5`);
  const runs = data?.workflow_runs || [];
  const successCount = runs.filter(r => r.conclusion === 'success').length;
  const failCount = runs.filter(r => r.conclusion === 'failure').length;
  return { runs: runs.slice(0, 5), successCount, failCount };
}

// Cache to reduce API calls
let cache = { data: null, at: 0 };
const CACHE_TTL = 25000; // 25s cache

async function getDashboardData() {
  if (cache.data && Date.now() - cache.at < CACHE_TTL) return cache.data;

  const [envVars, serviceStatus, ghData] = await Promise.allSettled([
    getRailwayEnvVars(),
    getRailwayServiceStatus(),
    getGitHubRuns(),
  ]);

  const vars = envVars.value || {};
  const svc = serviceStatus.value || { status: 'ERROR' };
  const gh = ghData.value || { runs: [], successCount: 0, failCount: 0 };

  const videoId = vars.VIDEO_ID || 'unknown';
  const workers = parseInt(vars.WORKERS || '10');
  const watchTime = parseInt(vars.WATCH_TIME || '3960');

  // Estimate views: if service is running, calculate from deployment time
  const deployedAt = svc.deployment?.createdAt ? new Date(svc.deployment.createdAt) : null;
  const uptimeSeconds = deployedAt ? Math.floor((Date.now() - deployedAt.getTime()) / 1000) : 0;
  const viewsPerWorkerPerHour = 3600 / (watchTime + 30); // +30 for overhead
  const totalViews = Math.floor((uptimeSeconds / 3600) * viewsPerWorkerPerHour * workers);
  const watchHours = Math.floor((totalViews * watchTime) / 3600);

  cache.data = {
    videoId,
    workers,
    watchTime,
    svcStatus: svc.status,
    deployment: svc.deployment,
    uptimeSeconds,
    totalViews,
    watchHours,
    ghRuns: gh.runs,
    ghSuccess: gh.successCount,
    ghFail: gh.failCount,
    allVars: vars,
    fetchedAt: new Date().toISOString(),
  };
  cache.at = Date.now();
  return cache.data;
}

// ── Format helpers ────────────────────────────────────────────────────────
function fmtUptime(s) {
  if (!s) return '—';
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function fmtNum(n) {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
  return n.toString();
}

function statusColor(s) {
  const map = {
    'SUCCESS': '#22c55e',
    'ACTIVE': '#22c55e',
    'DEPLOYING': '#f59e0b',
    'BUILDING': '#f59e0b',
    'INITIALIZING': '#f59e0b',
    'FAILED': '#ef4444',
    'ERROR': '#ef4444',
    'CRASHED': '#ef4444',
    'REMOVED': '#6b7280',
    'UNKNOWN': '#6b7280',
  };
  return map[s] || '#6b7280';
}

function statusEmoji(s) {
  const map = {
    'SUCCESS': '🟢',
    'ACTIVE': '🟢',
    'DEPLOYING': '🟡',
    'BUILDING': '🟡',
    'INITIALIZING': '🟡',
    'FAILED': '🔴',
    'ERROR': '🔴',
    'CRASHED': '🔴',
    'REMOVED': '⚫',
    'UNKNOWN': '⚪',
  };
  return map[s] || '⚪';
}

function ghRunBadge(run) {
  const conc = run.conclusion;
  const status = run.status;
  let color = '#6b7280';
  let label = status;
  if (conc === 'success') { color = '#22c55e'; label = '✓ success'; }
  else if (conc === 'failure') { color = '#ef4444'; label = '✗ failed'; }
  else if (conc === 'cancelled') { color = '#f59e0b'; label = '⊘ cancelled'; }
  else if (status === 'in_progress') { color = '#3b82f6'; label = '⟳ running'; }
  return `<span style="background:${color}22;color:${color};padding:2px 8px;border-radius:12px;font-size:12px;font-weight:600;">${label}</span>`;
}

function timeAgo(dateStr) {
  const d = new Date(dateStr);
  const s = Math.floor((Date.now() - d) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

// ── HTML Template ─────────────────────────────────────────────────────────
function renderLogin(error = '') {
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>YT Viewer — Login</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>body{background:#0a0a0f;}</style>
</head>
<body class="min-h-screen flex items-center justify-center bg-gray-950">
  <div class="w-full max-w-sm p-8 rounded-2xl" style="background:#13131a;border:1px solid #1f1f2e;">
    <div class="text-center mb-8">
      <div class="text-4xl mb-3">📺</div>
      <h1 class="text-2xl font-bold text-white">YT Viewer Dashboard</h1>
      <p class="text-gray-500 text-sm mt-1">Railway Control Panel</p>
    </div>
    ${error ? `<div class="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm text-center">${error}</div>` : ''}
    <form method="POST" action="/login">
      <div class="mb-4">
        <label class="block text-gray-400 text-sm mb-2">Password</label>
        <input type="password" name="password" autofocus
          class="w-full px-4 py-3 rounded-xl text-white text-sm outline-none"
          style="background:#1a1a26;border:1px solid #2a2a3e;"
          placeholder="Enter password">
      </div>
      <button type="submit"
        class="w-full py-3 rounded-xl font-semibold text-white transition-all"
        style="background:linear-gradient(135deg,#6366f1,#8b5cf6);">
        Sign In →
      </button>
    </form>
  </div>
</body>
</html>`;
}

function renderDashboard(d) {
  const svcColor = statusColor(d.svcStatus);
  const isRunning = ['SUCCESS', 'ACTIVE', 'DEPLOYING', 'BUILDING', 'INITIALIZING'].includes(d.svcStatus);

  const ghRunsHtml = d.ghRuns.length === 0
    ? '<p class="text-gray-500 text-sm">No runs found</p>'
    : d.ghRuns.map(r => `
        <div class="flex items-center justify-between py-2" style="border-bottom:1px solid #1f1f2e;">
          <div>
            <p class="text-sm text-gray-200 font-medium">${(r.display_title || r.head_commit?.message || 'Run').substring(0, 40)}</p>
            <p class="text-xs text-gray-500">${timeAgo(r.created_at)} · ${r.head_branch}</p>
          </div>
          <div>${ghRunBadge(r)}</div>
        </div>`).join('');

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>YT Viewer Dashboard</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
  * { box-sizing: border-box; }
  body { background: #0a0a0f; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
  .card { background: #13131a; border: 1px solid #1f1f2e; border-radius: 16px; padding: 20px; }
  .stat-card { background: #13131a; border: 1px solid #1f1f2e; border-radius: 16px; padding: 20px; position: relative; overflow: hidden; }
  .stat-card::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px; }
  .stat-card.green::before { background: linear-gradient(90deg, #22c55e, #16a34a); }
  .stat-card.blue::before { background: linear-gradient(90deg, #3b82f6, #6366f1); }
  .stat-card.purple::before { background: linear-gradient(90deg, #8b5cf6, #d946ef); }
  .stat-card.amber::before { background: linear-gradient(90deg, #f59e0b, #ef4444); }
  input, select { background: #1a1a26 !important; border: 1px solid #2a2a3e !important; color: #e2e8f0; outline: none; }
  input:focus, select:focus { border-color: #6366f1 !important; }
  .btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 10px 20px; border-radius: 10px; font-weight: 600; font-size: 14px; cursor: pointer; transition: all 0.2s; border: none; }
  .btn:hover { opacity: 0.85; transform: translateY(-1px); }
  .btn:active { transform: translateY(0); }
  .btn-primary { background: linear-gradient(135deg, #6366f1, #8b5cf6); color: white; }
  .btn-success { background: linear-gradient(135deg, #22c55e, #16a34a); color: white; }
  .btn-danger { background: linear-gradient(135deg, #ef4444, #dc2626); color: white; }
  .btn-warning { background: linear-gradient(135deg, #f59e0b, #d97706); color: white; }
  .btn-ghost { background: #1a1a26; border: 1px solid #2a2a3e !important; color: #94a3b8; }
  .badge { display: inline-flex; align-items: center; padding: 4px 12px; border-radius: 100px; font-size: 12px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; }
  .toast { position: fixed; bottom: 24px; right: 24px; padding: 14px 20px; border-radius: 12px; font-size: 14px; font-weight: 600; z-index: 9999; transform: translateY(100px); opacity: 0; transition: all 0.3s; max-width: 320px; }
  .toast.show { transform: translateY(0); opacity: 1; }
  .toast.success { background: #22c55e22; border: 1px solid #22c55e44; color: #22c55e; }
  .toast.error { background: #ef444422; border: 1px solid #ef444444; color: #ef4444; }
  .toast.info { background: #6366f122; border: 1px solid #6366f144; color: #818cf8; }
  .spinner { width: 16px; height: 16px; border: 2px solid transparent; border-top-color: currentColor; border-radius: 50%; animation: spin 0.7s linear infinite; display: none; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .pulse { animation: pulse 2s infinite; }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
  .refresh-bar { height: 3px; background: #6366f1; border-radius: 2px; animation: refill 30s linear infinite; transform-origin: left; }
  @keyframes refill { from { transform: scaleX(0); } to { transform: scaleX(1); } }
  .thumbnail-container { position: relative; border-radius: 12px; overflow: hidden; aspect-ratio: 16/9; background: #1a1a26; }
  .thumbnail-container img { width: 100%; height: 100%; object-fit: cover; }
  .play-icon { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); width: 56px; height: 56px; background: rgba(255,0,0,0.9); border-radius: 50%; display: flex; align-items: center; justify-content: center; box-shadow: 0 4px 20px rgba(255,0,0,0.4); }
  details summary { cursor: pointer; user-select: none; list-style: none; }
  details summary::-webkit-details-marker { display: none; }
  @media (max-width: 640px) { .grid-cols-2 { grid-template-columns: 1fr !important; } .grid-cols-4 { grid-template-columns: 1fr 1fr !important; } }
</style>
</head>
<body class="min-h-screen">

<!-- Refresh bar -->
<div style="position:fixed;top:0;left:0;right:0;z-index:100;">
  <div class="refresh-bar" id="refreshBar"></div>
</div>

<!-- Toast -->
<div class="toast" id="toast"></div>

<!-- Header -->
<div style="background:#13131a;border-bottom:1px solid #1f1f2e;" class="sticky top-0 z-50">
  <div class="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
    <div class="flex items-center gap-3">
      <span class="text-2xl">📺</span>
      <div>
        <h1 class="text-white font-bold text-lg leading-tight">YT Viewer</h1>
        <p class="text-gray-500 text-xs">Railway Dashboard</p>
      </div>
    </div>
    <div class="flex items-center gap-3">
      <div class="text-xs text-gray-500 hidden sm:block">
        Updated <span id="lastUpdated">just now</span>
      </div>
      <div style="width:8px;height:8px;border-radius:50%;background:${svcColor};" class="${isRunning ? 'pulse' : ''}"></div>
      <span class="text-xs font-bold" style="color:${svcColor};">${d.svcStatus}</span>
      <a href="/logout" class="btn btn-ghost text-xs px-3 py-2">Sign Out</a>
    </div>
  </div>
</div>

<!-- Main -->
<div class="max-w-6xl mx-auto px-4 py-6">

  <!-- Stats row -->
  <div class="grid gap-4 mb-6" style="grid-template-columns: repeat(4, 1fr);">
    <div class="stat-card blue">
      <p class="text-gray-500 text-xs font-semibold uppercase tracking-wider mb-2">👁 Est. Views</p>
      <p class="text-3xl font-bold text-white">${fmtNum(d.totalViews)}</p>
      <p class="text-gray-600 text-xs mt-1">since last deploy</p>
    </div>
    <div class="stat-card green">
      <p class="text-gray-500 text-xs font-semibold uppercase tracking-wider mb-2">⏱ Watch Hours</p>
      <p class="text-3xl font-bold text-white">${fmtNum(d.watchHours)}h</p>
      <p class="text-gray-600 text-xs mt-1">generated</p>
    </div>
    <div class="stat-card purple">
      <p class="text-gray-500 text-xs font-semibold uppercase tracking-wider mb-2">👷 Workers</p>
      <p class="text-3xl font-bold text-white">${d.workers}</p>
      <p class="text-gray-600 text-xs mt-1">parallel viewers</p>
    </div>
    <div class="stat-card amber">
      <p class="text-gray-500 text-xs font-semibold uppercase tracking-wider mb-2">⏳ Uptime</p>
      <p class="text-3xl font-bold text-white">${fmtUptime(d.uptimeSeconds)}</p>
      <p class="text-gray-600 text-xs mt-1">current deploy</p>
    </div>
  </div>

  <!-- Main content grid -->
  <div class="grid gap-4 mb-4" style="grid-template-columns: 1fr 1fr;">
    
    <!-- Left: Video + Controls -->
    <div class="flex flex-col gap-4">
      
      <!-- Current Video -->
      <div class="card">
        <div class="flex items-center justify-between mb-4">
          <h2 class="font-bold text-white text-base">🎬 Current Video</h2>
          <span class="badge" style="background:#ef444422;color:#ef4444;">TARGETING</span>
        </div>
        <div class="thumbnail-container mb-4">
          <img src="https://img.youtube.com/vi/${d.videoId}/maxresdefault.jpg" 
               onerror="this.src='https://img.youtube.com/vi/${d.videoId}/0.jpg'"
               alt="Video thumbnail" id="videoThumb">
          <div class="play-icon">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="white"><path d="M8 5v14l11-7z"/></svg>
          </div>
        </div>
        <div class="flex items-center gap-2 mb-4">
          <code class="flex-1 text-sm font-mono text-purple-400 bg-purple-500/10 px-3 py-2 rounded-lg" id="videoIdDisplay">${d.videoId}</code>
          <a href="https://youtube.com/watch?v=${d.videoId}" target="_blank" 
             class="btn btn-ghost text-xs px-3 py-2">▶ Watch</a>
        </div>
        
        <!-- Change Video Form -->
        <form id="changeVideoForm">
          <p class="text-xs text-gray-500 mb-2 font-semibold uppercase tracking-wider">Change Video</p>
          <div class="flex gap-2">
            <input type="text" id="newVideoId" placeholder="Enter YouTube video ID..." 
                   class="flex-1 px-3 py-2 rounded-lg text-sm">
            <button type="submit" class="btn btn-primary text-sm px-4">
              <div class="spinner" id="videoSpinner"></div>
              Update
            </button>
          </div>
          <p class="text-xs text-gray-600 mt-1">Updates Railway env var and redeploys automatically</p>
        </form>
      </div>

      <!-- Worker Control -->
      <div class="card">
        <h2 class="font-bold text-white text-base mb-4">👷 Worker Control</h2>
        <div class="flex items-center gap-3 mb-3">
          <span class="text-3xl font-bold text-white" id="workerDisplay">${d.workers}</span>
          <span class="text-gray-500 text-sm">workers</span>
          <span class="ml-auto text-xs text-gray-500">Rate: ~${Math.round((3600 / (d.watchTime + 30)) * d.workers)}/hr views</span>
        </div>
        <input type="range" id="workerSlider" min="1" max="200" value="${d.workers}"
               class="w-full mb-3 accent-purple-500" style="background:transparent;">
        <div class="flex justify-between text-xs text-gray-600 mb-4">
          <span>1</span><span>50</span><span>100</span><span>150</span><span>200</span>
        </div>
        <button onclick="updateWorkers()" class="btn btn-primary w-full text-sm">
          <div class="spinner" id="workerSpinner"></div>
          Apply Worker Count
        </button>
      </div>
      
    </div>

    <!-- Right: Status + GH Actions -->
    <div class="flex flex-col gap-4">

      <!-- Service Controls -->
      <div class="card">
        <h2 class="font-bold text-white text-base mb-4">🚀 Service Controls</h2>
        <div class="p-3 rounded-xl mb-4" style="background:#1a1a26;border:1px solid #2a2a3e;">
          <div class="flex items-center justify-between">
            <div>
              <p class="text-sm font-semibold text-gray-300">Railway Service</p>
              <p class="text-xs text-gray-500 mt-1">yt-viewer · production</p>
            </div>
            <span class="badge" style="background:${svcColor}22;color:${svcColor};">${statusEmoji(d.svcStatus)} ${d.svcStatus}</span>
          </div>
          ${d.deployment ? `
          <div class="mt-3 pt-3" style="border-top:1px solid #2a2a3e;">
            <p class="text-xs text-gray-600">Deployed: ${timeAgo(d.deployment.createdAt)}</p>
            ${d.deployment.url ? `<p class="text-xs text-blue-400 mt-1 truncate">${d.deployment.url}</p>` : ''}
          </div>` : ''}
        </div>
        
        <div class="grid gap-2" style="grid-template-columns: 1fr 1fr;">
          <button onclick="redeploy()" class="btn btn-success text-sm">
            <div class="spinner" id="deploySpinner"></div>
            🚀 Redeploy
          </button>
          <button onclick="stopService()" class="btn btn-danger text-sm">
            <div class="spinner" id="stopSpinner"></div>
            ⏹ Stop
          </button>
        </div>
      </div>

      <!-- GitHub Actions -->
      <div class="card">
        <div class="flex items-center justify-between mb-4">
          <h2 class="font-bold text-white text-base">⚙️ GitHub Actions</h2>
          <div class="flex items-center gap-2">
            <span class="text-xs text-green-400">✓ ${d.ghSuccess}</span>
            <span class="text-gray-600 text-xs">|</span>
            <span class="text-xs text-red-400">✗ ${d.ghFail}</span>
          </div>
        </div>
        
        <div class="mb-4">
          ${ghRunsHtml}
        </div>

        <button onclick="triggerWorkflow()" class="btn btn-warning w-full text-sm">
          <div class="spinner" id="workflowSpinner"></div>
          ▶ Trigger viewer.yml
        </button>
      </div>

      <!-- Watch Time Control -->
      <div class="card">
        <h2 class="font-bold text-white text-base mb-4">⏱ Watch Time Config</h2>
        <p class="text-xs text-gray-500 mb-2">Current: <strong class="text-white">${d.watchTime}s</strong> (${Math.floor(d.watchTime / 60)}m ${d.watchTime % 60}s per view)</p>
        <form id="watchTimeForm">
          <div class="flex gap-2">
            <input type="number" id="newWatchTime" placeholder="Seconds (e.g. 3960)" 
                   class="flex-1 px-3 py-2 rounded-lg text-sm" min="60" max="7200" value="${d.watchTime}">
            <button type="submit" class="btn btn-primary text-sm px-4">
              <div class="spinner" id="watchSpinner"></div>
              Set
            </button>
          </div>
        </form>
      </div>

    </div>
  </div>

  <!-- All Env Vars (collapsible) -->
  <details class="card">
    <summary class="flex items-center justify-between">
      <h2 class="font-bold text-white text-base">⚙️ Environment Variables</h2>
      <span class="text-gray-500 text-sm">▼ expand</span>
    </summary>
    <div class="mt-4 overflow-x-auto">
      <table class="w-full text-sm">
        <thead>
          <tr style="border-bottom:1px solid #1f1f2e;">
            <th class="text-left text-gray-500 pb-2 pr-4 font-semibold text-xs uppercase">Variable</th>
            <th class="text-left text-gray-500 pb-2 font-semibold text-xs uppercase">Value</th>
          </tr>
        </thead>
        <tbody>
          ${Object.entries(d.allVars).map(([k, v]) => `
            <tr style="border-bottom:1px solid #1a1a26;">
              <td class="py-2 pr-4 font-mono text-purple-400 text-xs whitespace-nowrap">${k}</td>
              <td class="py-2 font-mono text-gray-300 text-xs">${k.toLowerCase().includes('token') || k.toLowerCase().includes('pass') || k.toLowerCase().includes('secret') ? '••••••••' : v}</td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>
  </details>

  <!-- Footer -->
  <div class="text-center mt-6 text-gray-600 text-xs">
    <p>YT Viewer Dashboard · Auto-refresh in <span id="countdown">30</span>s · Last fetch: ${new Date(d.fetchedAt).toLocaleTimeString()}</p>
  </div>

</div>

<script>
// ── Toast ──
function showToast(msg, type = 'info') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast ' + type + ' show';
  setTimeout(() => { t.className = 'toast ' + type; }, 3500);
}

// ── Auto-refresh countdown ──
let remaining = 30;
let autoRefreshInterval;
const countdownEl = document.getElementById('countdown');
const lastUpdatedEl = document.getElementById('lastUpdated');
let lastUpdateTime = Date.now();

function startCountdown() {
  remaining = 30;
  clearInterval(autoRefreshInterval);
  autoRefreshInterval = setInterval(() => {
    remaining--;
    if (countdownEl) countdownEl.textContent = remaining;
    if (remaining <= 0) {
      clearInterval(autoRefreshInterval);
      location.reload();
    }
    const secs = Math.floor((Date.now() - lastUpdateTime) / 1000);
    if (lastUpdatedEl) lastUpdatedEl.textContent = secs < 5 ? 'just now' : secs + 's ago';
  }, 1000);
}
startCountdown();

// ── Worker slider ──
const slider = document.getElementById('workerSlider');
const workerDisplay = document.getElementById('workerDisplay');
if (slider) {
  slider.addEventListener('input', () => {
    workerDisplay.textContent = slider.value;
  });
}

// ── API call helper ──
async function apiCall(endpoint, data) {
  try {
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    return await res.json();
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

function setLoading(spinnerId, loading) {
  const s = document.getElementById(spinnerId);
  if (s) s.style.display = loading ? 'block' : 'none';
}

// ── Change video ──
document.getElementById('changeVideoForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const vid = document.getElementById('newVideoId').value.trim();
  if (!vid) return showToast('Enter a video ID', 'error');
  setLoading('videoSpinner', true);
  const r = await apiCall('/api/update-env', { VIDEO_ID: vid });
  setLoading('videoSpinner', false);
  if (r.ok) {
    showToast('✅ Video ID updated! Redeploying...', 'success');
    setTimeout(() => location.reload(), 3000);
  } else {
    showToast('❌ ' + (r.error || 'Failed to update'), 'error');
  }
});

// ── Update workers ──
async function updateWorkers() {
  const workers = document.getElementById('workerSlider').value;
  setLoading('workerSpinner', true);
  const r = await apiCall('/api/update-env', { WORKERS: workers });
  setLoading('workerSpinner', false);
  if (r.ok) {
    showToast(\`✅ Workers set to \${workers}! Redeploying...\`, 'success');
    setTimeout(() => location.reload(), 3000);
  } else {
    showToast('❌ ' + (r.error || 'Failed'), 'error');
  }
}

// ── Watch time ──
document.getElementById('watchTimeForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const wt = document.getElementById('newWatchTime').value.trim();
  if (!wt) return;
  setLoading('watchSpinner', true);
  const r = await apiCall('/api/update-env', { WATCH_TIME: wt });
  setLoading('watchSpinner', false);
  if (r.ok) {
    showToast('✅ Watch time updated! Redeploying...', 'success');
    setTimeout(() => location.reload(), 3000);
  } else {
    showToast('❌ ' + (r.error || 'Failed'), 'error');
  }
});

// ── Redeploy ──
async function redeploy() {
  if (!confirm('Redeploy yt-viewer service?')) return;
  setLoading('deploySpinner', true);
  const r = await apiCall('/api/deploy', {});
  setLoading('deploySpinner', false);
  if (r.ok) {
    showToast('🚀 Redeploy triggered!', 'success');
    setTimeout(() => location.reload(), 5000);
  } else {
    showToast('❌ ' + (r.error || 'Failed'), 'error');
  }
}

// ── Stop ──
async function stopService() {
  if (!confirm('⚠️ Stop the yt-viewer service? This will stop all views!')) return;
  setLoading('stopSpinner', true);
  const r = await apiCall('/api/stop', {});
  setLoading('stopSpinner', false);
  if (r.ok) {
    showToast('⏹ Service stopped', 'info');
    setTimeout(() => location.reload(), 3000);
  } else {
    showToast('❌ ' + (r.error || 'Failed'), 'error');
  }
}

// ── Trigger workflow ──
async function triggerWorkflow() {
  setLoading('workflowSpinner', true);
  const r = await apiCall('/api/trigger-workflow', {});
  setLoading('workflowSpinner', false);
  if (r.ok) {
    showToast('⚙️ Workflow triggered!', 'success');
    setTimeout(() => location.reload(), 5000);
  } else {
    showToast('❌ ' + (r.error || 'Failed to trigger workflow'), 'error');
  }
}
</script>
</body>
</html>`;
}

// ── Routes ────────────────────────────────────────────────────────────────

// Auth middleware
function requireAuth(req, res, next) {
  const token = req.headers.cookie?.match(/session=([^;]+)/)?.[1];
  if (isValidSession(token)) return next();
  res.redirect('/login');
}

// Login page
app.get('/login', (req, res) => {
  res.setHeader('Content-Type', 'text/html');
  res.send(renderLogin());
});

app.post('/login', (req, res) => {
  const { password } = req.body;
  if (password === DASHBOARD_PASS) {
    const token = createSession();
    res.setHeader('Set-Cookie', `session=${token}; HttpOnly; Path=/; Max-Age=86400`);
    res.redirect('/');
  } else {
    res.setHeader('Content-Type', 'text/html');
    res.send(renderLogin('Wrong password. Try again.'));
  }
});

app.get('/logout', (req, res) => {
  const token = req.headers.cookie?.match(/session=([^;]+)/)?.[1];
  if (token) sessions.delete(token);
  res.setHeader('Set-Cookie', 'session=; HttpOnly; Path=/; Max-Age=0');
  res.redirect('/login');
});

// Main dashboard
app.get('/', requireAuth, async (req, res) => {
  try {
    const data = await getDashboardData();
    res.setHeader('Content-Type', 'text/html');
    res.send(renderDashboard(data));
  } catch (e) {
    console.error('[dashboard error]', e);
    res.status(500).send(`<pre style="color:red;background:#111;padding:20px;">Error: ${e.message}</pre>`);
  }
});

// API: Update env vars + redeploy
app.post('/api/update-env', requireAuth, async (req, res) => {
  try {
    const vars = req.body;
    const keys = Object.keys(vars);
    if (keys.length === 0) return res.json({ ok: false, error: 'No vars provided' });

    // Build variables array for upsert
    const variables = keys.map(k => ({ name: k, value: String(vars[k]) }));

    const result = await railwayGQL(`
      mutation {
        variableCollectionUpsert(input: {
          projectId: "${RAILWAY_PROJECT_ID}"
          serviceId: "${RAILWAY_SERVICE_ID}"
          environmentId: "${RAILWAY_ENV_ID}"
          variables: {${variables.map(v => `${v.name}: "${v.value}"`).join(', ')}}
        })
      }
    `);

    if (result?.errors) {
      return res.json({ ok: false, error: result.errors[0]?.message || 'GQL error' });
    }

    // Trigger redeploy
    await railwayGQL(`
      mutation {
        serviceInstanceRedeploy(
          serviceId: "${RAILWAY_SERVICE_ID}"
          environmentId: "${RAILWAY_ENV_ID}"
        )
      }
    `);

    cache = { data: null, at: 0 }; // Bust cache
    res.json({ ok: true });
  } catch (e) {
    console.error('[update-env error]', e);
    res.json({ ok: false, error: e.message });
  }
});

// API: Deploy
app.post('/api/deploy', requireAuth, async (req, res) => {
  try {
    const result = await railwayGQL(`
      mutation {
        serviceInstanceRedeploy(
          serviceId: "${RAILWAY_SERVICE_ID}"
          environmentId: "${RAILWAY_ENV_ID}"
        )
      }
    `);

    if (result?.errors) {
      return res.json({ ok: false, error: result.errors[0]?.message || 'Deploy failed' });
    }
    cache = { data: null, at: 0 };
    res.json({ ok: true });
  } catch (e) {
    res.json({ ok: false, error: e.message });
  }
});

// API: Stop
app.post('/api/stop', requireAuth, async (req, res) => {
  try {
    // Get latest deployment ID first
    const depData = await railwayGQL(`
      query {
        deployments(input: {
          projectId: "${RAILWAY_PROJECT_ID}"
          serviceId: "${RAILWAY_SERVICE_ID}"
          environmentId: "${RAILWAY_ENV_ID}"
        }) {
          edges { node { id status } }
        }
      }
    `);

    const edges = depData?.data?.deployments?.edges || [];
    const activeDeployment = edges.find(e => ['SUCCESS', 'ACTIVE'].includes(e.node.status));

    if (!activeDeployment) {
      return res.json({ ok: false, error: 'No active deployment found' });
    }

    const result = await railwayGQL(`
      mutation {
        deploymentStop(id: "${activeDeployment.node.id}")
      }
    `);

    if (result?.errors) {
      return res.json({ ok: false, error: result.errors[0]?.message || 'Stop failed' });
    }
    cache = { data: null, at: 0 };
    res.json({ ok: true });
  } catch (e) {
    res.json({ ok: false, error: e.message });
  }
});

// API: Trigger GitHub workflow
app.post('/api/trigger-workflow', requireAuth, async (req, res) => {
  try {
    const result = await githubPost(
      `/repos/${GH_REPO}/actions/workflows/${GH_WORKFLOW}/dispatches`,
      { ref: 'main' }
    );

    if (result.status === 204 || result.status === 200) {
      cache = { data: null, at: 0 };
      res.json({ ok: true });
    } else {
      res.json({ ok: false, error: `GitHub returned ${result.status}` });
    }
  } catch (e) {
    res.json({ ok: false, error: e.message });
  }
});

// Health check
app.get('/health', (req, res) => res.json({ ok: true, ts: Date.now() }));

// ── Start ─────────────────────────────────────────────────────────────────
app.listen(PORT, () => {
  console.log(`[yt-dashboard] Server running on port ${PORT}`);
  console.log(`[yt-dashboard] Dashboard pass: ${DASHBOARD_PASS ? '(set)' : '(not set!)'}`);
});
