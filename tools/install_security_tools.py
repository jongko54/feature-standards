"""Install pinned scanner binaries into a new, explicitly selected directory."""

import argparse
import hashlib
import io
import json
import platform
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def install(destination: Path) -> None:
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    config = json.loads((ROOT / "security/tools.json").read_text())["tools"]
    machine = f"{platform.system()}-{platform.machine()}"
    for name in ("osv-scanner", "gitleaks"):
        tool = config[name]
        asset = tool["assets"].get(machine)
        if asset is None:
            raise ValueError("unsupported scanner platform")
        url = f"https://github.com/{tool['repository']}/releases/download/v{tool['version']}/{asset['name']}"
        with urllib.request.urlopen(url, timeout=90) as response:
            content = response.read(100_000_001)
        if (
            len(content) > 100_000_000
            or hashlib.sha256(content).hexdigest() != asset["sha256"]
        ):
            raise ValueError("scanner download checksum mismatch")
        if name == "gitleaks":
            with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
                member = archive.getmember("gitleaks")
                if not member.isfile():
                    raise ValueError("invalid scanner archive")
                content = archive.extractfile(member).read()
        target = destination / name
        with target.open("xb") as output:
            output.write(content)
        target.chmod(0o700)
        print(f"Installed checksum-verified {name} {tool['version']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", required=True, type=Path)
    install(parser.parse_args().dest)
