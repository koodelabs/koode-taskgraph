"""Allow ``python -m taskgraph`` to start the Qt application."""

from taskgraph.app import main

raise SystemExit(main())
