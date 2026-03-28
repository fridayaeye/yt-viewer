const https = require('https');
const fs = require('fs');
const { execSync } = require('child_process');

console.log('Installing express...');
execSync('npm init -y && npm install express', { cwd: '/tmp', stdio: 'inherit' });

console.log('Downloading dashboard...');
const file = fs.createWriteStream('/tmp/dashboard.js');
https.get('https://raw.githubusercontent.com/fridayaeye/yt-viewer/main/dashboard.js', (res) => {
  res.pipe(file);
  file.on('finish', () => {
    file.close();
    console.log('Starting dashboard...');
    require('/tmp/dashboard.js');
  });
}).on('error', (e) => {
  console.error('Download failed:', e.message);
  process.exit(1);
});
