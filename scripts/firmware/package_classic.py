"""Package the complete pinned, device-independent Classic release image."""

import argparse
import zlib
from pathlib import Path

from iOpenPod.app.firmware.shared_release import validate_release


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("firmware", type=Path)
    args = parser.parse_args()
    image = args.firmware.read_bytes()
    validate_release(image)
    destination = (
        Path(__file__).resolve().parents[2]
        / "src/iOpenPod/assets/firmware/classic-shared/firmware.zlib"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(zlib.compress(image, 9))
    print(f"Packaged {destination.stat().st_size:,} bytes: {destination}")


if __name__ == "__main__":
    main()
