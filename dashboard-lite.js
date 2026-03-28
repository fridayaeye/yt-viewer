const http = require('http');
const https = require('https');
const { URL } = require('url');
const crypto = require('crypto');

const PORT = process.env.PORT || 3000;
const RAILWAY_TOKEN = process.env.RAILWAY_TOKEN || '';
const GH_TOKEN = process.env.GH_TOKEN || '';
const PASS = process.env.DASHBOARD_PASS || 'stark369';
// Use VIEWER_SERVICE_ID — Railway auto-injects RAILWAY_SERVICE_ID as dashboard's own ID
const VIEWER_SID = process.env.VIEWER_SERVICE_ID || '5e96b607-29b4-4025-a148-2c6b3eb59899';
const PID = process.env.RAILWAY_PROJECT_ID || process.env.PROJECT_ID || 'fb557282-4585-4e58-9856-584b783fa593';
const EID = process.env.RAILWAY_ENV_ID || process.env.ENV_ID || 'e3b643e5-4811-4797-8cf0-86df8633efeb';
const GH_REPO = process.env.GH_REPO || 'fridayaeye/yt-viewer';
const GH_WORKFLOW = process.env.GH_WORKFLOW || 'viewer.yml';

console.log('[boot] VIEWER_SID:', VIEWER_SID);
console.log('[boot] PID:', PID);
console.log('[boot] EID:', EID);
console.log('[boot] PORT:', PORT);

// --- HTTP Helpers ---
function gql(query, vars) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({ query, variables: vars });
    const req = https.request({
      hostname: 'backboard.railway.app',
      path: '/graphql/v2',
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${RAILWAY_TOKEN}`,
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(body)
      }
    }, res => {
      let d = '';
      res.on('data', c => d += c);
      res.on('end', () => {
        try { resolve(JSON.parse(d)); }
        catch (e) { resolve({ error: d }); }
      });
    });
    req.on('error', e => { console.error('[gql error]', e.message); resolve({ error: e.message }); });
    req.setTimeout(10000, () => { req.destroy(); resolve({ error: 'timeout' }); });
    req.write(body);
    req.end();
  });
}

function ghApi(path, method = 'GET', body = null) {
  return new Promise((resolve, reject) => {
    const opts = {
      hostname: 'api.github.com',
      path,
      method,
      headers: {
        'Authorization': `token ${GH_TOKEN}`,
        'User-Agent': 'yt-dashboard/1.0',
        'Accept': 'application/vnd.github.v3+json'
      }
    };
    if (body) {
      const b = JSON.stringify(body);
      opts.headers['Content-Type'] = 'application/json';
      opts.headers['Content-Length'] = Buffer.byteLength(b);
    }
    const req = https.request(opts, res => {
      let d = '';
      res.on('data', c => d += c);
      res.on('end', () => {
        try { resolve({ status: res.statusCode, data: JSON.parse(d) }); }
        catch (e) { resolve({ status: res.statusCode, data: d }); }
      });
    });
    req.on('error', e => { console.error('[gh error]', e.message); resolve({ error: e.message }); });
    req.setTimeout(10000, () => { req.destroy(); resolve({ error: 'timeout' }); });
    if (body) req.write(JSON.stringify(body));
    req.end();
  });
}

// --- Session management ---
const sessions = {};
function makeToken() { return crypto.randomBytes(24).toString('hex'); }
function isAuthed(req) {
  const cookies = (req.headers.cookie || '').split(';').map(c => c.trim());
  const sess = cookies.find(c => c.startsWith('sess='));
  if (!sess) return false;
  const token = sess.split('=')[1];
  return sessions[token] && (Date.now() - sessions[token] < 86400000);
}

// --- Data fetch ---
let cache = { data: null, ts: 0 };

async function getData() {
  if (cache.data && Date.now() - cache.ts < 20000) return cache.data;

  const [varsRes, deployRes, ghRes] = await Promise.all([
    gql(`query { variables(projectId: "${PID}", serviceId: "${VIEWER_SID}", environmentId: "${EID}") }`),
    gql(`query { deployments(input: { projectId: "${PID}", serviceId: "${VIEWER_SID}", environmentId: "${EID}" }) { edges { node { id status createdAt } } } }`),
    ghApi(`/repos/${GH_REPO}/actions/runs?per_page=5`).catch(() => ({ data: {} }))
  ]);

  const vars = varsRes?.data?.variables || {};
  const edges = deployRes?.data?.deployments?.edges || [];
  const latestDeploy = edges[0]?.node || null;
  const ghRuns = ghRes?.data?.workflow_runs || [];

  const videoId = vars.VIDEO_ID || 'unknown';
  const workers = parseInt(vars.WORKERS || '10');
  const watchTime = parseInt(vars.WATCH_TIME || '3960');

  // Estimate stats from deploy time
  const deployedAt = latestDeploy?.createdAt ? new Date(latestDeploy.createdAt) : null;
  const uptimeSec = deployedAt ? Math.floor((Date.now() - deployedAt.getTime()) / 1000) : 0;
  const viewsPerWorkerPerHr = 3600 / (watchTime + 30);
  const estViews = Math.floor((uptimeSec / 3600) * viewsPerWorkerPerHr * workers);
  const estWatchHrs = Math.round((estViews * watchTime) / 3600);

  const uptimeStr = uptimeSec > 3600
    ? `${Math.floor(uptimeSec / 3600)}h ${Math.floor((uptimeSec % 3600) / 60)}m`
    : `${Math.floor(uptimeSec / 60)}m`;

  cache.data = {
    videoId, workers, watchTime,
    status: latestDeploy?.status || 'UNKNOWN',
    deployedAt: latestDeploy?.createdAt || null,
    uptimeStr, estViews, estWatchHrs,
    ghRuns: ghRuns.slice(0, 5),
    ghSuccess: ghRuns.filter(r => r.conclusion === 'success').length,
    ghFail: ghRuns.filter(r => r.conclusion === 'failure').length,
  };
  cache.ts = Date.now();
  return cache.data;
}

// --- Formatting helpers ---
function fmtNum(n) {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
  return String(n);
}

function timeAgo(iso) {
  if (!iso) return '—';
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return s + 's ago';
  if (s < 3600) return Math.floor(s / 60) + 'm ago';
  if (s < 86400) return Math.floor(s / 3600) + 'h ago';
  return Math.floor(s / 86400) + 'd ago';
}

function statusDot(s) {
  if (['SUCCESS', 'ACTIVE'].includes(s)) return '🟢';
  if (['DEPLOYING', 'BUILDING', 'INITIALIZING'].includes(s)) return '🟡';
  if (['FAILED', 'CRASHED', 'ERROR'].includes(s)) return '🔴';
  return '⚪';
}

function ghIcon(r) {
  if (r.conclusion === 'success') return '✅';
  if (r.conclusion === 'failure') return '❌';
  if (r.status === 'in_progress') return '🔄';
  if (r.conclusion === 'cancelled') return '⊘';
  return '⏳';
}

// --- HTML ---
function loginPage(err) {
  return `<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>YT Viewer — Login</title>
<style>*{margin:0;box-sizing:border-box}body{background:#0a0a12;color:#e2e8f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center}
.card{background:#12121e;border:1px solid #1e1e32;border-radius:20px;padding:40px;width:100%;max-width:380px;text-align:center}
h1{font-size:28px;margin:12px 0 4px}p{color:#64748b;font-size:14px;margin-bottom:24px}
input{width:100%;padding:14px 18px;border-radius:12px;border:1px solid #2a2a42;background:#1a1a2e;color:#e2e8f0;font-size:16px;outline:none;margin-bottom:12px}
input:focus{border-color:#6366f1}
button{width:100%;padding:14px;border:none;border-radius:12px;background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff;font-size:16px;font-weight:700;cursor:pointer}
button:hover{opacity:.9}.err{background:#ef444420;border:1px solid #ef444440;color:#ef4444;padding:10px;border-radius:10px;font-size:14px;margin-bottom:16px}
</style></head><body><div class="card"><div style="font-size:48px;margin-bottom:8px">📺</div><h1>YT Viewer</h1><p>Railway Dashboard</p>
${err ? `<div class="err">${err}</div>` : ''}
<form method="POST" action="/login"><input type="password" name="pw" placeholder="Password" autofocus><button>Sign In →</button></form></div></body></html>`;
}

function dashPage(d) {
  const sColor = ['SUCCESS','ACTIVE'].includes(d.status) ? '#22c55e' : ['FAILED','CRASHED','ERROR'].includes(d.status) ? '#ef4444' : '#f59e0b';
  const rate = Math.round((3600 / (d.watchTime + 30)) * d.workers);

  const ghRows = d.ghRuns.length === 0 ? '<div style="color:#64748b;font-size:13px">No workflow runs found</div>'
    : d.ghRuns.map(r => `<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #1e1e32">
      <div><span style="margin-right:6px">${ghIcon(r)}</span><span style="font-size:13px;color:#cbd5e1">${(r.display_title||r.name||'Run').substring(0,35)}</span></div>
      <span style="font-size:12px;color:#64748b">${timeAgo(r.created_at)}</span></div>`).join('');

  return `<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>YT Viewer Dashboard</title>
<style>
*{margin:0;box-sizing:border-box}
body{background:#0a0a12;color:#e2e8f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
.hdr{background:#12121e;border-bottom:1px solid #1e1e32;padding:12px 20px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:50}
.main{max-width:960px;margin:0 auto;padding:20px}
.grid{display:grid;gap:16px;margin-bottom:20px}
.g4{grid-template-columns:repeat(4,1fr)}
.g2{grid-template-columns:repeat(2,1fr)}
@media(max-width:768px){.g4{grid-template-columns:repeat(2,1fr)}.g2{grid-template-columns:1fr}}
.card{background:#12121e;border:1px solid #1e1e32;border-radius:16px;padding:20px}
.stat{position:relative;overflow:hidden}.stat::before{content:'';position:absolute;top:0;left:0;right:0;height:2px}
.stat.g::before{background:#22c55e}.stat.b::before{background:#6366f1}.stat.p::before{background:#a855f7}.stat.a::before{background:#f59e0b}
.stat .lbl{font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.05em;font-weight:700;margin-bottom:8px}
.stat .val{font-size:28px;font-weight:800;color:#fff}
.stat .sub{font-size:11px;color:#4a4a6a;margin-top:4px}
.thumb{border-radius:12px;overflow:hidden;position:relative;aspect-ratio:16/9;background:#1a1a2e}
.thumb img{width:100%;height:100%;object-fit:cover}
.play{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:52px;height:52px;background:rgba(255,0,0,.9);border-radius:50%;display:flex;align-items:center;justify-content:center;box-shadow:0 4px 20px rgba(255,0,0,.3)}
input[type=text],input[type=number],input[type=password]{width:100%;padding:10px 14px;border-radius:10px;border:1px solid #2a2a42;background:#1a1a2e;color:#e2e8f0;font-size:14px;outline:none}
input:focus{border-color:#6366f1}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:10px 20px;border-radius:10px;font-weight:700;font-size:13px;cursor:pointer;border:none;color:#fff;transition:all .15s}
.btn:hover{opacity:.85;transform:translateY(-1px)}
.btn-p{background:linear-gradient(135deg,#6366f1,#8b5cf6)}
.btn-g{background:linear-gradient(135deg,#22c55e,#16a34a)}
.btn-r{background:linear-gradient(135deg,#ef4444,#dc2626)}
.btn-w{background:linear-gradient(135deg,#f59e0b,#d97706)}
.btn-o{background:#1a1a2e;border:1px solid #2a2a42!important;color:#94a3b8}
.badge{display:inline-block;padding:3px 10px;border-radius:99px;font-size:11px;font-weight:700;letter-spacing:.04em}
.sep{border-top:1px solid #1e1e32;margin:12px 0}
.toast{position:fixed;bottom:20px;right:20px;padding:12px 20px;border-radius:12px;font-size:13px;font-weight:700;z-index:999;transform:translateY(80px);opacity:0;transition:all .3s}
.toast.show{transform:translateY(0);opacity:1}
.toast.ok{background:#22c55e22;border:1px solid #22c55e44;color:#22c55e}
.toast.err{background:#ef444422;border:1px solid #ef444444;color:#ef4444}
.toast.info{background:#6366f122;border:1px solid #6366f144;color:#818cf8}
.rbar{height:3px;background:#6366f1;border-radius:2px;animation:fill 30s linear infinite;transform-origin:left;position:fixed;top:0;left:0;right:0;z-index:100}
@keyframes fill{from{transform:scaleX(0)}to{transform:scaleX(1)}}
.pulse{animation:pulse 2s infinite}@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
input[type=range]{width:100%;accent-color:#8b5cf6;background:transparent}
</style></head><body>
<div class="rbar"></div>
<div class="toast" id="toast"></div>
<div class="hdr">
  <div style="display:flex;align-items:center;gap:10px">
    <span style="font-size:24px">📺</span>
    <div><div style="font-weight:800;color:#fff;font-size:16px">YT Viewer</div><div style="font-size:11px;color:#64748b">Railway Dashboard</div></div>
  </div>
  <div style="display:flex;align-items:center;gap:12px">
    <div style="width:8px;height:8px;border-radius:50%;background:${sColor}" class="${['SUCCESS','ACTIVE'].includes(d.status)?'pulse':''}"></div>
    <span style="font-size:12px;font-weight:700;color:${sColor}">${d.status}</span>
    <a href="/logout" class="btn btn-o" style="padding:6px 12px;font-size:11px">Sign Out</a>
  </div>
</div>
<div class="main">
  <!-- Stats -->
  <div class="grid g4">
    <div class="card stat b"><div class="lbl">👁 Est. Views</div><div class="val">${fmtNum(d.estViews)}</div><div class="sub">since deploy</div></div>
    <div class="card stat g"><div class="lbl">⏱ Watch Hours</div><div class="val">${fmtNum(d.estWatchHrs)}h</div><div class="sub">generated</div></div>
    <div class="card stat p"><div class="lbl">👷 Workers</div><div class="val">${d.workers}</div><div class="sub">~${rate}/hr views</div></div>
    <div class="card stat a"><div class="lbl">⏳ Uptime</div><div class="val">${d.uptimeStr}</div><div class="sub">current deploy</div></div>
  </div>
  <!-- Main grid -->
  <div class="grid g2">
    <!-- Left column -->
    <div style="display:flex;flex-direction:column;gap:16px">
      <!-- Video card -->
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
          <span style="font-weight:800;color:#fff">🎬 Current Video</span>
          <span class="badge" style="background:#ef444422;color:#ef4444">TARGETING</span>
        </div>
        <div class="thumb" style="margin-bottom:12px">
          <img src="https://img.youtube.com/vi/${d.videoId}/maxresdefault.jpg" onerror="this.src='https://img.youtube.com/vi/${d.videoId}/0.jpg'">
          <div class="play"><svg width="18" height="18" viewBox="0 0 24 24" fill="#fff"><path d="M8 5v14l11-7z"/></svg></div>
        </div>
        <div style="display:flex;gap:8px;align-items:center;margin-bottom:12px">
          <code style="flex:1;font-size:13px;color:#a78bfa;background:#a78bfa15;padding:8px 12px;border-radius:8px;font-family:monospace">${d.videoId}</code>
          <a href="https://youtube.com/watch?v=${d.videoId}" target="_blank" class="btn btn-o" style="padding:8px 12px;font-size:12px">▶ Watch</a>
        </div>
        <div class="sep"></div>
        <div style="font-size:11px;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:.04em;margin-bottom:8px">Change Video</div>
        <form id="fVideo" style="display:flex;gap:8px">
          <input type="text" id="iVideo" placeholder="Enter video ID (e.g. dQw4w9WgXcQ)" style="flex:1">
          <button type="submit" class="btn btn-p" style="white-space:nowrap">Update</button>
        </form>
        <div style="font-size:11px;color:#4a4a6a;margin-top:6px">Updates env var & redeploys</div>
      </div>
      <!-- Worker card -->
      <div class="card">
        <div style="font-weight:800;color:#fff;margin-bottom:12px">👷 Worker Control</div>
        <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:8px">
          <span id="wDisp" style="font-size:32px;font-weight:800;color:#fff">${d.workers}</span>
          <span style="color:#64748b;font-size:13px">workers</span>
        </div>
        <input type="range" id="wSlider" min="1" max="200" value="${d.workers}">
        <div style="display:flex;justify-content:space-between;font-size:11px;color:#4a4a6a;margin:4px 0 12px">
          <span>1</span><span>50</span><span>100</span><span>150</span><span>200</span>
        </div>
        <button onclick="doWorkers()" class="btn btn-p" style="width:100%">Apply Workers</button>
      </div>
    </div>
    <!-- Right column -->
    <div style="display:flex;flex-direction:column;gap:16px">
      <!-- Service controls -->
      <div class="card">
        <div style="font-weight:800;color:#fff;margin-bottom:12px">🚀 Service Controls</div>
        <div style="background:#1a1a2e;border:1px solid #2a2a42;border-radius:12px;padding:14px;margin-bottom:12px">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <div><div style="font-size:14px;font-weight:600;color:#cbd5e1">yt-viewer</div><div style="font-size:12px;color:#64748b;margin-top:2px">production</div></div>
            <span class="badge" style="background:${sColor}22;color:${sColor}">${statusDot(d.status)} ${d.status}</span>
          </div>
          ${d.deployedAt ? `<div class="sep"></div><div style="font-size:11px;color:#4a4a6a">Deployed: ${timeAgo(d.deployedAt)}</div>` : ''}
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
          <button onclick="doRedeploy()" class="btn btn-g">🚀 Redeploy</button>
          <button onclick="doStop()" class="btn btn-r">⏹ Stop</button>
        </div>
      </div>
      <!-- GitHub Actions -->
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
          <span style="font-weight:800;color:#fff">⚙️ GitHub Actions</span>
          <div style="display:flex;gap:8px;font-size:12px"><span style="color:#22c55e">✓ ${d.ghSuccess}</span><span style="color:#4a4a6a">|</span><span style="color:#ef4444">✗ ${d.ghFail}</span></div>
        </div>
        <div style="margin-bottom:12px">${ghRows}</div>
        <button onclick="doTrigger()" class="btn btn-w" style="width:100%">▶ Trigger ${GH_WORKFLOW}</button>
      </div>
      <!-- Watch time -->
      <div class="card">
        <div style="font-weight:800;color:#fff;margin-bottom:12px">⏱ Watch Time</div>
        <div style="font-size:13px;color:#64748b;margin-bottom:8px">Current: <strong style="color:#fff">${d.watchTime}s</strong> (${Math.floor(d.watchTime/60)}m ${d.watchTime%60}s / view)</div>
        <form id="fWatch" style="display:flex;gap:8px">
          <input type="number" id="iWatch" value="${d.watchTime}" min="60" max="7200" style="flex:1">
          <button type="submit" class="btn btn-p">Set</button>
        </form>
      </div>
    </div>
  </div>
  <div style="text-align:center;color:#4a4a6a;font-size:12px;margin-top:16px">Auto-refresh in <span id="cd">30</span>s</div>
</div>
<script>
function toast(m,t){const e=document.getElementById('toast');e.textContent=m;e.className='toast '+t+' show';setTimeout(()=>e.className='toast '+t,3500)}
let cd=30;setInterval(()=>{cd--;document.getElementById('cd').textContent=cd;if(cd<=0)location.reload()},1000);
document.getElementById('wSlider').oninput=function(){document.getElementById('wDisp').textContent=this.value};
async function api(u,b){try{const r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});return r.json()}catch(e){return{ok:false,error:e.message}}}
document.getElementById('fVideo').onsubmit=async function(e){e.preventDefault();const v=document.getElementById('iVideo').value.trim();if(!v)return toast('Enter a video ID','err');const r=await api('/api/env',{VIDEO_ID:v});r.ok?toast('✅ Updated! Redeploying...','ok'):toast('❌ '+r.error,'err');setTimeout(()=>location.reload(),3000)};
document.getElementById('fWatch').onsubmit=async function(e){e.preventDefault();const v=document.getElementById('iWatch').value;const r=await api('/api/env',{WATCH_TIME:v});r.ok?toast('✅ Watch time updated!','ok'):toast('❌ '+r.error,'err');setTimeout(()=>location.reload(),3000)};
async function doWorkers(){const v=document.getElementById('wSlider').value;const r=await api('/api/env',{WORKERS:v});r.ok?toast('✅ Workers set to '+v,'ok'):toast('❌ '+r.error,'err');setTimeout(()=>location.reload(),3000)}
async function doRedeploy(){if(!confirm('Redeploy yt-viewer?'))return;const r=await api('/api/deploy',{});r.ok?toast('🚀 Redeployed!','ok'):toast('❌ '+r.error,'err');setTimeout(()=>location.reload(),4000)}
async function doStop(){if(!confirm('Stop yt-viewer? This stops all views!'))return;const r=await api('/api/stop',{});r.ok?toast('⏹ Stopped','info'):toast('❌ '+r.error,'err');setTimeout(()=>location.reload(),3000)}
async function doTrigger(){const r=await api('/api/trigger',{});r.ok?toast('⚙️ Workflow triggered!','ok'):toast('❌ '+r.error,'err');setTimeout(()=>location.reload(),4000)}
</script></body></html>`;
}

// --- Parse POST body ---
function parseBody(req) {
  return new Promise(resolve => {
    let body = '';
    req.on('data', c => body += c);
    req.on('end', () => {
      try {
        if (req.headers['content-type']?.includes('json')) resolve(JSON.parse(body));
        else resolve(Object.fromEntries(new URLSearchParams(body)));
      } catch { resolve({}); }
    });
  });
}

// --- Server ---
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const path = url.pathname;

  // Health check (no auth)
  if (path === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    return res.end(JSON.stringify({ ok: true, ts: Date.now() }));
  }

  // Login page
  if (path === '/login' && req.method === 'GET') {
    res.writeHead(200, { 'Content-Type': 'text/html' });
    return res.end(loginPage());
  }

  // Login POST
  if (path === '/login' && req.method === 'POST') {
    const body = await parseBody(req);
    if (body.pw === PASS) {
      const token = makeToken();
      sessions[token] = Date.now();
      res.writeHead(302, { 'Set-Cookie': `sess=${token}; HttpOnly; Path=/; Max-Age=86400`, 'Location': '/' });
      return res.end();
    }
    res.writeHead(200, { 'Content-Type': 'text/html' });
    return res.end(loginPage('Wrong password'));
  }

  // Logout
  if (path === '/logout') {
    res.writeHead(302, { 'Set-Cookie': 'sess=; HttpOnly; Path=/; Max-Age=0', 'Location': '/login' });
    return res.end();
  }

  // Auth check for all other routes
  if (!isAuthed(req)) {
    res.writeHead(302, { 'Location': '/login' });
    return res.end();
  }

  // --- API endpoints ---
  if (path === '/api/env' && req.method === 'POST') {
    try {
      const vars = await parseBody(req);
      const keys = Object.keys(vars).filter(k => k && vars[k]);
      if (keys.length === 0) return res.end(JSON.stringify({ ok: false, error: 'No vars' }));

      const varStr = keys.map(k => `${k}: "${String(vars[k]).replace(/"/g, '\\"')}"`).join(', ');
      const result = await gql(`mutation { variableCollectionUpsert(input: { projectId: "${PID}", serviceId: "${VIEWER_SID}", environmentId: "${EID}", variables: { ${varStr} } }) }`);

      if (result?.errors) {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        return res.end(JSON.stringify({ ok: false, error: result.errors[0]?.message || 'GQL error' }));
      }

      // Trigger redeploy
      await gql(`mutation { serviceInstanceRedeploy(serviceId: "${VIEWER_SID}", environmentId: "${EID}") }`);
      cache = { data: null, ts: 0 };
      res.writeHead(200, { 'Content-Type': 'application/json' });
      return res.end(JSON.stringify({ ok: true }));
    } catch (e) {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      return res.end(JSON.stringify({ ok: false, error: e.message }));
    }
  }

  if (path === '/api/deploy' && req.method === 'POST') {
    const r = await gql(`mutation { serviceInstanceRedeploy(serviceId: "${VIEWER_SID}", environmentId: "${EID}") }`);
    cache = { data: null, ts: 0 };
    res.writeHead(200, { 'Content-Type': 'application/json' });
    return res.end(JSON.stringify({ ok: !r?.errors, error: r?.errors?.[0]?.message }));
  }

  if (path === '/api/stop' && req.method === 'POST') {
    // Find active deployment and stop it
    const deps = await gql(`query { deployments(input: { projectId: "${PID}", serviceId: "${VIEWER_SID}", environmentId: "${EID}" }) { edges { node { id status } } } }`);
    const active = deps?.data?.deployments?.edges?.find(e => ['SUCCESS', 'ACTIVE'].includes(e.node.status));
    if (!active) {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      return res.end(JSON.stringify({ ok: false, error: 'No active deployment' }));
    }
    const r = await gql(`mutation { deploymentStop(id: "${active.node.id}") }`);
    cache = { data: null, ts: 0 };
    res.writeHead(200, { 'Content-Type': 'application/json' });
    return res.end(JSON.stringify({ ok: !r?.errors, error: r?.errors?.[0]?.message }));
  }

  if (path === '/api/trigger' && req.method === 'POST') {
    const r = await ghApi(`/repos/${GH_REPO}/actions/workflows/${GH_WORKFLOW}/dispatches`, 'POST', { ref: 'main' });
    res.writeHead(200, { 'Content-Type': 'application/json' });
    return res.end(JSON.stringify({ ok: r.status === 204 || r.status === 200, error: r.status > 204 ? `HTTP ${r.status}` : undefined }));
  }

  // --- Dashboard page ---
  if (path === '/') {
    try {
      const data = await getData();
      res.writeHead(200, { 'Content-Type': 'text/html' });
      return res.end(dashPage(data));
    } catch (e) {
      console.error('[dash error]', e);
      res.writeHead(500, { 'Content-Type': 'text/plain' });
      return res.end('Error: ' + e.message);
    }
  }

  res.writeHead(404);
  res.end('Not Found');
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`[yt-dashboard] Running on port ${PORT}`);
  console.log(`[yt-dashboard] Viewer service: ${VIEWER_SID}`);
});
