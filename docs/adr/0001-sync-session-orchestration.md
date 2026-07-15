# Sync Session owns orchestration

The desktop GUI keeps ownership of presentation concerns such as dialogs, page navigation, and user-facing copy, while the Sync Session module owns PC-to-iPod sync orchestration after the user has chosen a sync intent. This gives the codebase one deep module for readiness checks, worker lifecycle, planning, podcast plan merging, execution, cancellation, and stale-worker protection without making app-core depend on the GUI widget tree.

Existing sync workers remain behind the Sync Session seam for the first refactor. We considered leaving worker orchestration in `MainWindow`, extracting only request construction, moving the folder dialog into the Sync Session module, and replacing the workers immediately; those alternatives were rejected because they either preserve the shallow GUI interface, mix presentation into app-core, or turn the architectural refactor into a riskier thread-behavior rewrite.
