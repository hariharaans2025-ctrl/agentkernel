import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const root = fileURLToPath(new URL('../', import.meta.url));
const input = await new Promise((resolve, reject) => {
  let text = '';
  const terminal = process.stdin.isTTY;
  if (terminal) process.stdin.setRawMode(true);
  process.stderr.write('Ready for private Site token on stdin (input is hidden).\n');
  process.stdin.setEncoding('utf8');
  const finish = () => { process.stdin.removeListener('data', data); if (terminal) process.stdin.setRawMode(false); process.stdin.pause(); };
  const data = chunk => {
    text += chunk;
    if (text.includes('\u0003') || text.length > 16384) { finish(); reject(new Error('Connection launch cancelled.')); }
    else if (/[\r\n]/.test(text)) { finish(); resolve(text.trim()); }
  };
  process.stdin.on('data', data);
  process.stdin.resume();
});
if (!input) throw new Error('A private Site token is required.');
const python = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const child = spawn(python, [path.join(root, 'scripts/sites_connection_agent.py'), '--token-stdin'], {
  cwd: root, windowsHide: true, detached: true, stdio: ['pipe', 'ignore', 'ignore'],
});
await new Promise((resolve, reject) => { child.once('spawn', resolve); child.once('error', reject); });
child.stdin.end(input + '\n');
child.unref();
console.log(JSON.stringify({ pid: child.pid, status: 'started', credentials_saved: false }));
