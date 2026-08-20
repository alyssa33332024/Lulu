import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const agentRoot = path.resolve(here, '../../../lulu-agent');
const venvPy = path.join(agentRoot, '.venv', 'Scripts', 'python.exe');
const py = fs.existsSync(venvPy) ? venvPy : 'python';

const child = spawn(
  py,
  ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'],
  { cwd: agentRoot, stdio: 'inherit', windowsHide: true },
);
child.on('exit', (code) => process.exit(code ?? 1));
