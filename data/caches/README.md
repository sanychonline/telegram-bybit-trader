# caches

This directory stores generated cache files used by local tools.

Typical contents:
- `backtest_klines_cache.json`

What goes here:
- downloaded historical market data;
- temporary backtest acceleration files;
- other rebuildable caches.

What to do with it:
- safe to delete if you want a clean rebuild;
- tools will recreate needed cache files automatically;
- do not rely on these files as source-of-truth data.

This directory is intentionally kept in git only as a documented placeholder.
