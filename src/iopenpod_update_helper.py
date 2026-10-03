"""Small separately frozen updater entry point, also the stable Linux launcher."""

import sys
from pathlib import Path

from iOpenPod.app.updates.helper import install, launch_managed, recover
from iOpenPod.app.updates.installation import running_installation
from storage.host_installation import durable_write, require_plain_path


def main() -> int:
    args = sys.argv[1:]
    if args == ["--smoke-test"]:
        from Crypto.Signature import eddsa

        if running_installation() is None:
            raise ValueError("Missing embedded update identity")
        key = eddsa.import_private_key(bytes(32))
        signature = eddsa.new(key, "rfc8032").sign(b"iOpenPod updater runtime test")
        eddsa.new(key.public_key(), "rfc8032").verify(
            b"iOpenPod updater runtime test", signature
        )
        return 0
    if len(args) == 2 and args[0] in ("--install", "--recover"):
        directory = require_plain_path(Path(args[1]))
        installation = running_installation()
        if installation is None or not installation.public_keys:
            raise ValueError("The update helper has no embedded release trust key")
        try:
            (install if args[0] == "--install" else recover)(
                directory, installation.public_keys
            )
        except Exception as error:
            durable_write(directory / "error.txt", str(error).encode())
            return 1
        return 0
    if sys.platform == "linux":
        return launch_managed(Path(sys.executable).parent, args)
    raise ValueError("Use --install or --recover with an existing update operation")


if __name__ == "__main__":
    raise SystemExit(main())
