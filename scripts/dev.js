// Runs the API (auto-restart on change) and the Vite dev server together, on any OS.
import { spawn } from 'node:child_process';

const run = (cmd, args) => spawn(cmd, args, { stdio: 'inherit', shell: process.platform === 'win32' });
const procs = [
  run(process.execPath, ['--watch', '--disable-warning=ExperimentalWarning', 'server/index.js']),
  run('npx', ['vite']),
];
const stop = () => { procs.forEach((p) => p.kill()); process.exit(); };
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
procs.forEach((p) => p.on('exit', stop));
