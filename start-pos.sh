#!/usr/bin/env bash
# Start the Waffle Bros POS on macOS / Linux.
cd "$(dirname "$0")"
[ -d node_modules ] || npm run setup
[ -d client/dist ] || npm run build
( sleep 2; (command -v open >/dev/null && open http://localhost:4000) || (command -v xdg-open >/dev/null && xdg-open http://localhost:4000) ) &
npm start
