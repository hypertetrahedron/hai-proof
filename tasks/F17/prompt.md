Feature request for PDM:

We lock with `exclude-newer` (in `[tool.pdm.resolution]` or `pdm lock --exclude-newer`) so that our lockfile only picks up releases older than a cutoff. That works well, except for the handful of packages where we need something newer than the cutoff (an urgent security release, our own internal packages) or, occasionally, need a particular package held further back than everyone else.

Please add per-package exceptions to the `exclude-newer` cutoff. I have particular views on how they should be configured and how they combine with the existing option, so talk the design through with me before you build it. Add tests and keep the existing tests passing.
