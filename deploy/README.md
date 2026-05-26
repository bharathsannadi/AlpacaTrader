# deploy/

OS-level scheduling and process supervision configs. **These are templates** —
the absolute paths inside them are hardcoded for the original development Mac.
Edit before installing on another machine.

```
deploy/
└── launchd/
    ├── com.alpacatrader.plist               # main app process (auto-restart)
    └── com.spy_auto_trader.watchdog.plist   # /health monitor (kills hung app)
```

See [`../docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md) for install steps.
