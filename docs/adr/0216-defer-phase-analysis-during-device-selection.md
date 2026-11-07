# ADR-0216: Defer Phase analysis during device selection

- Status: Accepted
- Date: 2026-10-30
- Clarifies: ADR-0100, ADR-0215
- Ordinary-save upgrade policy superseded by [ADR-0239](0239-gate-and-skip-phase-analysis.md).

Selection-time playback-sidecar reconciliation uses the normal Library transaction
but must not regenerate Phase charts. Model analysis under the selection lock can
keep the application on Loading iPod, and a newly created cancellation token made
shutdown wait for the entire analysis rather than stopping it.

The selection save preserves Phase companions and carries the captured Phase
Library precondition into its transaction. Ordinary saves and Sync retain Phase
preparation and cache-version invalidation. If Smart Playlist membership changes
during selection, the Phase companion index catches up on the next ordinary save.
This keeps playback-history reconciliation independent of optional model and
network availability without weakening its verified Storage transaction.

DeviceController signals its selection cancellation event before waiting for
workers at shutdown. DeviceCoordinator passes that same event through selection's
history preparation and save. Cancellation follows existing transaction safety
rules; native operations may still need to return before observing it.

The fixed Demucs checkpoint resolves through RemoteRepo directly, retaining
Torch's cached-file reuse and hash check. It does not pass through the model-alias
resolver, which attempted an unnecessary Hugging Face request and logged 401.
The model identity and chart algorithm are unchanged by this resolution fix.

A live stack captured the main thread waiting in shutdown and the selection worker
inside Demucs inference through the history-save path. Virtual-device regression
tests cover deferred Phase preparation, preserved companions, history commitment,
ordinary-save preparation, and shutdown cancellation. A provider test prevents
reintroduction of the Hub alias lookup.
