// Starts the POS against the demo database created by `npm run demo`.
import { fileURLToPath } from 'node:url';

process.env.WB_DATA_DIR ||= fileURLToPath(new URL('../data-demo', import.meta.url));
await import('../server/index.js');
