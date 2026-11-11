import { spawn } from 'node:child_process';
import { join } from 'node:path';

export function processEnvironment(directory, inherited = process.env) {
  const environment = { ...inherited };
  for (const key of ['PYTHONPATH', 'PYTHONHOME', 'UV_PROJECT', 'UV_WORKING_DIRECTORY', 'UV_NO_SYNC', 'UV_NO_PROJECT', 'GOFLAGS', 'CARGO_BUILD_TARGET', 'MAVEN_ARGS', 'MAVEN_OPTS', 'MAVEN_CONFIG', 'MAVEN_PROJECTBASEDIR', '_JAVA_OPTIONS', 'JAVA_TOOL_OPTIONS', 'JDK_JAVA_OPTIONS']) delete environment[key];
  environment.UV_PROJECT_ENVIRONMENT = join(directory, '.venv');
  environment.PYTHONDONTWRITEBYTECODE = '1';
  environment.CARGO_TARGET_DIR = join(directory, 'target');
  environment.GOWORK = 'off';
  return environment;
}

/** Stop only the process group we created, never an inherited server or listener. */
export function stop(child, signal = 'SIGTERM') {
  if (!Number.isInteger(child?.pid)) return;
  try {
    if (process.platform === 'win32') child.kill(signal);
    else process.kill(-child.pid, signal);
  } catch (error) { if (error.code !== 'ESRCH') throw error; }
}

export async function stopAndWait(child) {
  if (!child) return;
  stop(child);
  if (child.exitCode === null && child.signalCode === null) {
    await new Promise(resolveExit => {
      const timer = setTimeout(() => { stop(child, 'SIGKILL'); resolveExit(); }, 3000);
      child.once('exit', () => { clearTimeout(timer); resolveExit(); });
    });
  }
  stop(child, 'SIGKILL');
}

export async function command(program, args, directory, environment, { capture = false, timeout = 300000 } = {}) {
  const child = spawn(program, args, { cwd: directory, env: environment, stdio: capture ? ['ignore', 'pipe', 'pipe'] : 'inherit', detached: process.platform !== 'win32' });
  let output = '';
  let overflow = false;
  if (capture) {
    child.stdout.setEncoding('utf8');
    child.stdout.on('data', chunk => {
      output += chunk;
      if (output.length > 8 * 1024 * 1024) { overflow = true; stop(child, 'SIGKILL'); }
    });
    // Drain diagnostic output without logging environment values or returning it in receipts.
    child.stderr.resume();
  }
  let interrupted = false;
  const interrupt = () => { interrupted = true; stop(child); };
  process.once('SIGINT', interrupt); process.once('SIGTERM', interrupt);
  const timer = timeout > 0 ? setTimeout(() => stop(child, 'SIGKILL'), timeout) : undefined;
  try {
    await new Promise((resolveCommand, reject) => {
      child.once('error', () => reject(new Error('required-core-command-unavailable: ' + program)));
      // A process may exit while descendants still hold stdout. Only close
      // guarantees that the complete captured SDK metadata has been drained.
      child.once('close', code => code === 0 && !overflow && !interrupted ? resolveCommand() : reject(new Error('core-command-failed: ' + program)));
    });
    return output;
  } finally {
    clearTimeout(timer);
    process.removeListener('SIGINT', interrupt); process.removeListener('SIGTERM', interrupt);
    await stopAndWait(child);
  }
}
