"""Bake portable Qt shader packages for the Synesthesia QRhi adapter."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import QByteArray
from PySide6.QtGui import QShader

ROOT = Path(__file__).resolve().parents[1]
SHADER_ROOT = ROOT / "src" / "iOpenPod" / "GUI" / "synesthesia" / "shader_sources"
SHADER_SOURCES = (
    "field_sim.comp",
    "particles.vert",
    "particles.frag",
    "comets.vert",
    "comets.frag",
    "filaments.vert",
    "filaments.frag",
    "fullscreen.vert",
    "scenes.frag",
    "events.frag",
    "feedback.frag",
    "present.frag",
)


def main() -> None:
    compiler = shutil.which("pyside6-qsb")
    if compiler is None:
        raise RuntimeError("pyside6-qsb is unavailable; run this script through UV")
    for source_name in SHADER_SOURCES:
        source = SHADER_ROOT / source_name
        output = source.with_suffix(f"{source.suffix}.qsb")
        # Synesthesia requires compute fields, so its OpenGL graphics shaders must
        # target the same minimum APIs as the compute shader.  ``--qt6`` includes
        # GLSL ES 100, which QRhi selects for its OpenGLES2 backend even when the
        # context is ES 3.2; vertex-index-based draws cannot compile in that
        # language version.
        targets = ["--glsl", "310 es,430", "--hlsl", "50", "--msl", "12"]
        result = subprocess.run(
            [compiler, *targets, "-o", str(output), str(source)],
            check=False,
            capture_output=True,
            text=True,
        )
        diagnostics = "\n".join(
            value.strip() for value in (result.stdout, result.stderr) if value.strip()
        )
        if result.returncode or diagnostics:
            raise RuntimeError(
                f"qsb failed for {source.name}: {diagnostics or result.returncode}"
            )
        shader = QShader.fromSerialized(QByteArray(output.read_bytes()))
        if not shader.isValid() or len(shader.availableShaders()) < 5:
            raise RuntimeError(
                f"qsb did not create a portable package for {source.name}"
            )


if __name__ == "__main__":
    main()
