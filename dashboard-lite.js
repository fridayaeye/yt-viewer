const http = require('http');
const https = require('https');
const { URL } = require('url');

const PORT = process.env.PORT || 3000;
const RAILWAY_TOKEN = process.env.RAILWAY_TOKEN || '';
const GH_TOKEN = process.env.GH_TOKEN || '';
const PASS = process.env.DASHBOARD_PASS || 'stark369';
const VIEWER_SID = process.env.RAILWAY_SERVICE_ID || '5e96b607-29b4-4025-a148-2c6b3eb59899';
const PID = process.env.RAILWAY_PROJECT_ID || 'fb557282-4585-4e58-9856-584b783fa593';
const EID = process.env.RAILWAY_ENV_ID || 'e3b643e5-4811-4797-8cf0-86df8633efeb';

function gql(query, vars) {
  return new Promise((res, rej) => {
    const body = JSON.stringify({query, variables: vars});
    const req = https.request('https://backboard.railway.app/graphql/v2', {
      method: 'POST', headers: {'Authorization': `Bearer ${RAILWAY_TOKEN}`, 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body)}
    }, r => { let d=''; r.on('data',c=>d+=c); r.on('end',()=>{ try{res(JSON.parse(d))}catch(e){res({error:d})} }); });
    req.on('error', rej); req.write(body); req.end();
  });
}

function ghApi(path, method='GET', body=null) {
  return new Promise((res, rej) => {
    const opts = {method, headers: {'Authorization': `token ${GH_TOKEN}`, 'User-Agent': 'yt-dash', 'Accept': 'application/vnd.github.v3+json'}};
    if (body) { const b = JSON.stringify(body); opts.headers['Content-Type'] = 'application/json'; opts.headers['Content-Length'] = Buffer.byteLength(b); }
    const req = https.request(`https://api.github.com${path}`, opts, r => { let d=''; r.on('data',c=>d+=c); r.on('end',()=>{ try{res(JSON.parse(d))}catch(e){res({raw:d})} }); });
    req.on('error', rej); if(body) req.write(JSON.stringify(body)); req.end();
  });
}

async function getStatus() {
  const [svc, gh] = await Promise.all([
    gql(`query { service(id: "${VIEWER_SID}") { name deployments(first:1) { edges { node { status createdAt } } } serviceInstances { edges { node { startCommand source { image } } } } } }`),
    ghApi('/repos/fridayaeye/yt-viewer/actions/runs?per_page=5').catch(()=>({}))
  ]);
  
  // Get env vars for video_id and workers
  const vars = await gql(`query { variablesForServiceInstance(serviceId: "${VIEWER_SID}", environmentId: "${EID}") }`);
  
  return { svc, gh, vars };
}

const HTML = (data) => `<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>YT Viewer Dashboard</title>
<link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
<style>body{background:#0f172a;color:#e2e8f0}select,input{background:#1e293b;color:#e2e8f0;border:1px solid #334155;padding:8px 12px;border-radius:6px}</style>
</head><body class="p-4 md:p-8 max-w-4xl mx-auto">
<h1 class="text-3xl font-bold mb-2">🎬 YT Viewer Dashboard</h1>
<p class="text-gray-400 mb-6">Control panel for YouTube view automation</p>

<div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
  <div class="bg-gray-800 rounded-xl p-4">
    <div class="text-gray-400 text-sm">Current Video</div>
    <div class="text-xl font-bold mt-1">${data.videoId || 'N/A'}</div>
    <img src="https://img.youtube.com/vi/${data.videoId || 'dQw4w9WgXcQ'}/mqdefault.jpg" class="rounded mt-2 w-full"/>
  </div>
  <div class="space-y-4">
    <div class="bg-gray-800 rounded-xl p-4">
      <div class="text-gray-400 text-sm">Workers</div>
      <div class="text-3xl font-bold text-green-400">${data.workers || '?'}</div>
    </div>
    <div class="bg-gray-800 rounded-xl p-4">
      <div class="text-gray-400 text-sm">Railway Status</div>
      <div class="text-xl font-bold ${data.railwayStatus === 'SUCCESS' ? 'text-green-400' : 'text-red-400'}">${data.railwayStatus || '?'}</div>
    </div>
    <div class="bg-gray-800 rounded-xl p-4">
      <div class="text-gray-400 text-sm">Watch Time / View</div>
      <div class="text-xl font-bold text-blue-400">${Math.round((data.watchTime||0)/60)} min</div>
    </div>
  </div>
</div>

<div class="bg-gray-800 rounded-xl p-4 mb-6">
  <div class="text-gray-400 text-sm mb-2">GitHub Actions (last 5 runs)</div>
  <div class="space-y-1">${(data.ghRuns||[]).map(r => 
    `<div class="flex justify-between text-sm"><span>${r.status === 'completed' && r.conclusion === 'success' ? '✅' : r.status === 'in_progress' ? '🔄' : '❌'} ${r.name}</span><span class="text-gray-500">${new Date(r.created_at).toLocaleString()}</span></div>`
  ).join('') || '<div class="text-gray-500">No runs</div>'}</div>
</div>

<div class="bg-gray-800 rounded-xl p-4 mb-6">
  <h2 class="text-lg font-bold mb-3">⚙️ Controls</h2>
  <form method="POST" action="/update" class="space-y-3">
    <div><label class="text-gray-400 text-sm">Video ID</label><input name="video_id" value="${data.videoId||''}" class="w-full mt-1"/></div>
    <div><label class="text-gray-400 text-sm">Workers (1-200)</label><input name="workers" type="number" min="1" max="200" value="${data.workers||50}" class="w-full mt-1"/></div>
    <div><label class="text-gray-400 text-sm">Watch Time (seconds)</label><input name="watch_time" type="number" value="${data.watchTime||3960}" class="w-full mt-1"/></div>
    <button type="submit" class="bg-blue-600 hover:bg-blue-700 px-6 py-2 rounded-lg font-bold w-full">Update & Redeploy</button>
  </form>
  <div class="flex gap-2 mt-3">
    <a href="/trigger-gh" class="bg-purple-600 hover:bg-purple-700 px-4 py-2 rounded-lg text-center flex-1">🚀 Trigger GitHub Actions</a>
    <a href="/redeploy" class="bg-green-600 hover:bg-green-700 px-4 py-2 rounded-lg text-center flex-1">🔄 Redeploy Railway</a>
  </div>
</div>
<script>setTimeout(()=>location.reload(), 30000)</script>
</body></html>`;

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  
  // Simple auth via query param
  const auth = url.searchParams.get('p') || '';
  const cookie = (req.headers.cookie||'').includes('auth=ok');
  if (!cookie && auth !== PASS && url.pathname !== '/health') {
    if (url.pathname === '/login' || auth) {
      res.writeHead(302, {'Set-Cookie': 'auth=ok; Path=/; Max-Age=86400', 'Location': '/'});
      return res.end();
    }
    res.writeHead(200, {'Content-Type': 'text/html'});
    return res.end('<html><body style="background:#0f172a;color:#e2e8f0;display:flex;justify-content:center;align-items:center;height:100vh"><form method="GET"><input name="p" type="password" placeholder="Password" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;padding:12px;border-radius:8px;font-size:18px"/><button style="background:#3b82f6;color:white;padding:12px 24px;border-radius:8px;border:none;margin-left:8px;font-size:18px">Login</button></form></body></html>');
  }
  if (auth === PASS) {
    res.writeHead(302, {'Set-Cookie': 'auth=ok; Path=/; Max-Age=86400', 'Location': '/'});
    return res.end();
  }

  if (url.pathname === '/health') { res.writeHead(200); return res.end('ok'); }
  
  if (url.pathname === '/trigger-gh') {
    await ghApi('/repos/fridayaeye/yt-viewer/actions/workflows/viewer.yml/dispatches', 'POST', {ref:'main'});
    res.writeHead(302, {'Location': '/'}); return res.end();
  }
  
  if (url.pathname === '/redeploy') {
    await gql(`mutation { serviceInstanceDeploy(serviceId: "${VIEWER_SID}", environmentId: "${EID}") }`);
    res.writeHead(302, {'Location': '/'}); return res.end();
  }
  
  if (req.method === 'POST' && url.pathname === '/update') {
    let body = ''; req.on('data', c => body += c); req.on('end', async () => {
      const params = new URLSearchParams(body);
      const vars = {};
      if (params.get('video_id')) vars.VIDEO_ID = params.get('video_id');
      if (params.get('workers')) vars.WORKERS = params.get('workers');
      if (params.get('watch_time')) vars.WATCH_TIME = params.get('watch_time');
      await gql('mutation($i: VariableCollectionUpsertInput!) { variableCollectionUpsert(input: $i) }', 
        {i: {projectId: PID, serviceId: VIEWER_SID, environmentId: EID, variables: vars}});
      await gql(`mutation { serviceInstanceDeploy(serviceId: "${VIEWER_SID}", environmentId: "${EID}") }`);
      res.writeHead(302, {'Location': '/'}); res.end();
    }); return;
  }

  try {
    const {svc, gh, vars} = await getStatus();
    const envVars = vars?.data?.variablesForServiceInstance || {};
    const deploy = svc?.data?.service?.deployments?.edges?.[0]?.node;
    const ghRuns = (gh?.workflow_runs || []).map(r => ({name: r.name, status: r.status, conclusion: r.conclusion, created_at: r.created_at}));
    
    const data = {
      videoId: envVars.VIDEO_ID || 'RouUT5ZgA7Q',
      workers: envVars.WORKERS || '50',
      watchTime: envVars.WATCH_TIME || '3960',
      railwayStatus: deploy?.status || 'UNKNOWN',
      ghRuns
    };
    res.writeHead(200, {'Content-Type': 'text/html'}); res.end(HTML(data));
  } catch(e) {
    res.writeHead(500); res.end('Error: ' + e.message);
  }
});

server.listen(PORT, () => console.log(`Dashboard running on port ${PORT}`));
