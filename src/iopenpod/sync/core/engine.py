"""Typed SyncEngine facade.

This module is the public boundary for sync planning, execution, and quick
database writes.  It centralizes request normalization, progress, diagnostics,
and transaction policy while delegating device-format work to the specialized
planner, executor, and database writer modules.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, cast

from iopenpod.sync_progress_stages import (
    classify_execution_stage_value,
    classify_planning_stage_value,
)

from .context import EnginePlanContext
from .models import (
    EngineDiagnostic,
    EngineOperation,
    EngineOutcome,
    EngineProgress,
    EngineRequest,
    EngineStage,
    EngineTransactionPolicy,
)

logger = logging.getLogger(__name__)


class SyncEngine:
    """Single typed entrypoint for sync planning, execution, and DB writes."""

    def run(self, request: EngineRequest) -> EngineOutcome:
        diagnostics: list[EngineDiagnostic] = []
        self._emit(request, EngineStage.LOAD, message="Starting sync")
        try:
            self._migrate(request, diagnostics)
            if request.operation == EngineOperation.PLAN:
                result = self.compute_plan(request)
            elif request.operation == EngineOperation.EXECUTE:
                result = self.execute_plan(request)
            elif request.operation == EngineOperation.QUICK_WRITE:
                result = self.quick_write(request)
            else:
                raise ValueError(f"Unsupported engine operation: {request.operation}")
        except Exception as exc:
            logger.exception("SyncEngine operation failed")
            diagnostics.append(
                EngineDiagnostic(
                    stage=EngineStage.COMPLETE,
                    code="engine_exception",
                    message=str(exc),
                    fatal=True,
                )
            )
            return EngineOutcome(
                operation=request.operation,
                success=False,
                result=None,
                diagnostics=tuple(diagnostics),
            )

        success = bool(getattr(result, "success", True))
        if hasattr(result, "errors"):
            for stage, message in getattr(result, "errors", []) or []:
                diagnostics.append(
                    EngineDiagnostic(
                        stage=EngineStage.COMPLETE,
                        code=str(stage),
                        message=str(message),
                        fatal=not success,
                    )
                )
        self._emit(request, EngineStage.COMPLETE, message="Sync complete")
        return EngineOutcome(
            operation=request.operation,
            success=success and not any(d.fatal for d in diagnostics),
            result=result,
            diagnostics=tuple(diagnostics),
        )

    def compute_plan(self, request: EngineRequest):
        """Compute a sync plan from a typed engine request."""

        from iopenpod.sync.fingerprint_diff_engine import FingerprintDiffEngine
        from iopenpod.sync.pc_library import PCLibrary

        context = EnginePlanContext.from_request(cast(Any, request))
        self._emit(request, EngineStage.SCAN, message="Scanning media folders")
        pc_library = PCLibrary(context.pc_folders)
        diff_engine = FingerprintDiffEngine(
            pc_library,
            context.ipod_path,
            supports_video=request.options.supports_video,
            supports_podcast=request.options.supports_podcast,
            supports_photo=request.options.supports_photo,
            fpcalc_path=request.options.fpcalc_path,
            photo_sync_settings=context.photo_sync_settings,
            transcode_options=request.options.transcode_options,
        )

        def on_progress(stage: str, current: int, total: int, message: str) -> None:
            self._emit(
                request,
                self._planning_stage(stage),
                current=current,
                total=total,
                message=message,
                legacy_event=(stage, current, total, message),
            )

        self._emit(request, EngineStage.IDENTIFY, message="Resolving track identities")
        plan = diff_engine.compute_diff(
            list(context.ipod_tracks),
            progress_callback=on_progress,
            is_cancelled=request.is_cancelled,
            track_edits=dict(context.track_edits),
            photo_edits=request.photo_edits,
            sync_workers=request.options.sync_workers,
            rating_strategy=request.options.rating_strategy,
            allowed_paths=context.allowed_path_keys,
            selected_playlist_paths=context.selected_playlist_source_keys,
            existing_playlists=list(context.existing_playlists),
        )
        self._emit(request, EngineStage.PLAN, message="Sync plan ready")
        return plan

    def execute_plan(self, request: EngineRequest):
        """Execute a previously computed sync plan."""

        from iopenpod.sync.contracts import SyncRequest
        from iopenpod.sync.mapping import MappingManager
        from iopenpod.sync.sync_executor import SyncExecutor

        if request.plan is None:
            raise ValueError("EXECUTE operation requires EngineRequest.plan")

        self._emit(request, EngineStage.VALIDATE, message="Preparing sync")
        cache_dir = self._transcode_cache_dir(request)
        executor = SyncExecutor(
            str(request.ipod_path),
            cache_dir=cache_dir,
            max_workers=request.options.sync_workers,
            max_device_write_workers=request.options.device_write_workers,
            max_cache_size_gb=request.options.max_cache_size_gb,
            fpcalc_path=request.options.fpcalc_path,
            transcode_options=request.options.transcode_options,
            device_info=request.device_info,
            device_capabilities=request.device_capabilities,
            device_storage=request.device_storage,
            expected_database_generation=request.expected_database_generation,
            photo_sync_settings=dict(request.options.photo_sync_settings or {}),
        )

        mapping = request.mapping
        if mapping is None:
            mapping = MappingManager(str(request.ipod_path)).load()

        def on_progress(progress: Any) -> None:
            self._emit(
                request,
                self._execution_stage(getattr(progress, "stage", "")),
                current=int(getattr(progress, "current", 0) or 0),
                total=int(getattr(progress, "total", 0) or 0),
                message=str(getattr(progress, "message", "") or ""),
                legacy_event=progress,
            )

        sync_request = SyncRequest(
            plan=request.plan,
            mapping=mapping,
            progress_callback=on_progress,
            dry_run=request.options.dry_run,
            is_cancelled=request.is_cancelled,
            write_back_to_pc=request.options.write_back_to_pc,
            on_sync_complete=request.on_sync_complete,
            compute_sound_check=request.options.compute_sound_check,
            scrobble_on_sync=request.options.scrobble_on_sync,
            listenbrainz_token=request.options.listenbrainz_token,
            listenbrainz_username=request.options.listenbrainz_username,
            lastfm_api_key=request.options.lastfm_api_key,
            lastfm_api_secret=request.options.lastfm_api_secret,
            lastfm_session_key=request.options.lastfm_session_key,
            lastfm_username=request.options.lastfm_username,
            is_scrobble_cancelled=request.is_scrobble_cancelled,
            on_cancel_with_partial=request.on_cancel_with_partial,
            sync_until_full=request.options.sync_until_full,
        )
        self._emit(request, EngineStage.EXECUTE_FILES, message="Applying file changes")
        return executor.execute_request(sync_request)

    def quick_write(self, request: EngineRequest):
        """Write cached DB state through the engine facade."""

        from iopenpod.sync.quick_writes import write_cached_itunesdb

        self._emit(request, EngineStage.ASSEMBLE_COMMIT, message="Preparing database write")

        def on_progress(progress: Any) -> None:
            self._emit(
                request,
                EngineStage.COMMIT,
                current=int(getattr(progress, "current", 0) or 0),
                total=int(getattr(progress, "total", 0) or 0),
                message=str(getattr(progress, "message", "") or ""),
                legacy_event=progress,
            )

        return write_cached_itunesdb(
            request.ipod_path,
            tracks_data=[dict(track) for track in request.tracks_data],
            playlists_data=[dict(playlist) for playlist in request.playlists_data],
            artwork_sources=request.artwork_sources,
            progress_callback=on_progress,
            expected_database_generation=request.expected_database_generation,
            reported_volume_format=str(
                getattr(request.device_storage, "reported_volume_format", "") or ""
            ),
            expected_volume_identity_key=str(
                getattr(request.device_storage, "volume_identity_key", "") or ""
            ),
        )

    def _migrate(
        self,
        request: EngineRequest,
        diagnostics: list[EngineDiagnostic],
    ) -> None:
        self._emit(request, EngineStage.MIGRATE, message="Checking sync data")
        if request.options.transaction_policy == EngineTransactionPolicy.ALL_OR_NOTHING:
            diagnostics.append(
                EngineDiagnostic(
                    stage=EngineStage.MIGRATE,
                    code="unsupported_transaction_policy",
                    message=(
                        "All-or-nothing transactions are not available for device "
                        "file mutations; using consistency-preserving behavior."
                    ),
                    fatal=False,
                )
            )
        self._emit(request, EngineStage.NORMALIZE, message="Preparing sync inputs")

    def _emit(
        self,
        request: EngineRequest,
        stage: EngineStage | str,
        *,
        current: int = 0,
        total: int = 0,
        message: str = "",
        legacy_event: Any = None,
    ) -> None:
        if request.progress_callback is None:
            return
        request.progress_callback(
            EngineProgress(
                stage=stage,
                current=current,
                total=total,
                message=message,
                legacy_event=legacy_event,
            )
        )

    @staticmethod
    def _transcode_cache_dir(request: EngineRequest) -> Path | None:
        value = request.options.transcode_cache_dir
        return Path(value) if value else None

    @staticmethod
    def _planning_stage(stage: str) -> EngineStage:
        return EngineStage(classify_planning_stage_value(stage))

    @staticmethod
    def _execution_stage(stage: str) -> EngineStage:
        return EngineStage(classify_execution_stage_value(stage))
