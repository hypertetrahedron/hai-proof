I want the polling observer to keep watching through a temporary failure instead of stopping for good, because our share is sometimes unreachable for a few seconds.

The design I want:

- Keep watching through transient errors rather than stop. That is the main choice; the rest follow from it.
- Which errors count as "the directory is gone" and which as transient:
  - Only `FileNotFoundError` and `NotADirectoryError` mean the watched directory was deleted. As today, that queues a `DirDeletedEvent` for the watched path and stops the emitter.
  - Any other `OSError` while reading the directory is transient: for example `EACCES`, `EBUSY`, `EHOSTDOWN`, `ESTALE` or `EIO`. No `DirDeletedEvent`, and the emitter keeps running.
  - An outage that the OS happens to report as `ENOENT` still looks like a deletion. I accept that, and don't want it special-cased.
- On a transient error, keep the last good snapshot and try again on the next poll. Retry forever: no give-up limit and no back-off setting.
- Changes made while the directory was unreadable must be reported once it can be read again, as normal events against the last good snapshot (a file created during the outage arrives as a created event after recovery).
- Logging, through the module's logger:
  - exactly one warning per outage, however many polls fail in a row, naming the path and the error;
  - an info line when polling resumes after the outage;
  - a later, separate outage gets its own warning.
- It applies equally when the error comes from listing a subdirectory of a recursive watch rather than the root: the same keep-the-snapshot-and-retry behaviour, and no `DirDeletedEvent` for the root.
- Note the behaviour in the `PollingObserver` docstring and add a line to `changelog.rst`.
