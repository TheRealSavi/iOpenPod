# ADR-0225: Install optional Phase analysis with safe fallbacks

- Status: Accepted
- Date: 2026-11-02
- Supersedes: ADR-0215's stop-on-provider-failure policy

At the user's request, optional Phase instrument analysis can be downloaded after
installation. Native downloads and Microsoft Store packages retain the acoustic
baseline. Settings > Media Tools > Set Up Phase Analysis starts nothing until
Download and Install is selected.

Setup downloads a size- and SHA-256-pinned UV executable from Astral's release,
installs private Python 3.12.14, resolves pinned analysis requirements against
PyPI and an official PyTorch index, and installs the resulting hashed lock.
The lock remains with the environment. Python, packages and model data stay
beneath iOpenPod's Host user-data directory. No application bundle, system Python,
PATH, or media-tool override is modified. Setup holds a Host lease; incomplete
environments are cleaned up. Real model inference must succeed before a receipt
atomically selects the new environment. Earlier successful environments remain
retained rather than being removed while another app process could use them.

Private Python installation disables both executable links and Windows registry
registration. Interpreter discovery selects the pinned version and exact platform
key within the private directory, allowing earlier versions and architectures to
coexist. An x64 Windows app running under ARM64 emulation selects x64 tools using
the interpreter's build architecture; native Windows ARM64 builds remain unsupported.
If CUDA package setup or
its health check fails, setup retries a fresh CPU environment before reporting
failure; cancellation prevents that retry.
Native dependencies must have compatible binary wheels; only Demucs, dora-search
and antlr4-python3-runtime may build their pure-Python source distributions.
This avoids requiring a compiler on end-user machines.

Windows and Linux select CUDA 13 wheels only for observed Turing-or-newer GPUs
and R580-or-newer drivers; otherwise they use CPU wheels. Apple Silicon selects
Torch 2.11 for macOS 12.3–13 and Torch 2.14 for macOS 14+. Intel Macs select
Torch/Torchaudio 2.2.2, Demucs 4.0.1, NumPy 1.26.4 and Numba 0.62.1.
These are installation candidates, not platform acceptance: resolution and real
inference must pass. Unsupported configurations retain acoustic analysis.

Downloaded analysis runs in a bounded, cancellable child Python process. Its
worker imports the same source-measurement modules shipped as resources, reads
temporary PCM, and returns validated Phase Parts plus its actual backend.
It receives no iPod path or Filesystem Session. Optional native-library failures
are isolated from the GUI. Settings-aware FFmpeg decoding and transactional
Storage publication remain in the application.

Available CUDA or MPS acceleration is preferred. Failed inference restarts the
complete Track on CPU, avoiding mixed backend evidence. Optional import, model,
network, process or CPU-inference failures use measured acoustic analysis for
the rest of that preparation. Later preparations retry available providers.
Provenance is recomputed after analysis and records the producer of the bytes.
Checkpoint failures, device disconnection, invalid audio and decoding errors
still stop preparation; fabricated charts or substituted FFmpeg executables
cannot make those conditions safe.

The setup dialog reads installation state each time it opens, disables setup on
unsupported hosts, and retains cancellation feedback until the worker stops.
Detailed failures are available in a scrollable field and in the application log.
Every native release smoke test exercises acoustic chart generation and native
serialization. A separate opt-in smoke check exercises the bundled worker with
an already installed optional runtime.

PCM finite-value validation uses cancellable ten-second blocks, bounding its
temporary Boolean mask independently of Track duration. GPU-to-CPU retries leave
the failed exception handler before restarting, releasing its retained tensors.
These changes preserve the existing analysis algorithm and parameter mapping.

The explicit setup can use several gigabytes without enlarging the standard
dependency closure. On 2026-11-02 all seven dependency profiles resolved with
hashed locks and the binary-wheel policy. Windows x64 setup, CUDA inference and
the actual worker launched from the frozen executable passed locally. The
unsigned MSIX payload passed manifest, integrity, embedded-resource and acoustic
runtime checks. The source distribution and wheel built and the wheel matched
the source tree. Mac/Linux native execution, Windows ARM64 emulation execution,
installed-MSIX acceptance, Store certification of this download flow, and physical
Phase gameplay remain separate acceptance tasks. The optional release-workflow
check runs real setup and frozen-worker acceptance on each native CI platform.
