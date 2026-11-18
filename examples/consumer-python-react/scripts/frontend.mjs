import * as esbuild from 'esbuild';
import { parse } from 'dotenv';
import { expand } from 'dotenv-expand';
import { fileURLToPath } from 'node:url';
import { frontendMain } from '../../../tools/react-preview.mjs';

await frontendMain({ root: fileURLToPath(new URL('..', import.meta.url)), esbuild, parse, expand,
  defaultPort: 5174, routes: ['/auth', '/api', '/healthz'] });
