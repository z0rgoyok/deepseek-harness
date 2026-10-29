#!/usr/bin/env python3
"""Package a qualified Linux runtime and bind its hashes to this CI run."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys
import tarfile


SOURCE = "76b0743e339d78e24680db39747b81e101d2c236"
REPOSITORY = "https://github.com/z0rgoyok/deepseek-harness"
LOCK = "349ecef16eae1c2166b74661fdff552b9825945894b89461b3a29f825daa6f76"
POLICY = "4482da18064697ce24688fb04123ac882605d66eb510f5b74ef2979d3e4344f7"


def hash_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_archive(archive, records):
    expected = {item["path"]: item for item in records}
    seen = set()
    with tarfile.open(archive, "r:") as tar:
        for member in tar:
            if not member.name.startswith("runtime/"):
                raise RuntimeError("archive contains an unexpected root")
            name = member.name[len("runtime/"):].rstrip("/")
            item = expected.get(name)
            if item is None or name in seen or member.mode != item["mode"]:
                raise RuntimeError("archive path or mode differs from manifest")
            seen.add(name)
            if item["type"] == "directory":
                if member.type != tarfile.DIRTYPE or member.size != 0:
                    raise RuntimeError("archive directory differs from manifest")
                continue
            if member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE) or member.size != item["bytes"]:
                raise RuntimeError("archive file type or size differs from manifest")
            stream = tar.extractfile(member)
            if stream is None:
                raise RuntimeError("archive file is unreadable")
            digest = hashlib.sha256()
            with stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != item["sha256"]:
                raise RuntimeError("archive file hash differs from manifest")
    if seen != set(expected):
        raise RuntimeError("archive is incomplete")


def main():
    source, stage, output, policy = (Path(value).resolve(strict=True) for value in sys.argv[1:])
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    remote = subprocess.check_output(["git", "remote", "get-url", "origin"], cwd=source, text=True).strip()
    if commit != SOURCE or remote.removesuffix(".git") != REPOSITORY:
        raise RuntimeError("source identity differs from pinned repository or commit")
    if hash_file(source / "pnpm-lock.yaml") != LOCK:
        raise RuntimeError("source lockfile differs")
    if hash_file(policy) != POLICY:
        raise RuntimeError("qualification policy differs from the reviewed Agent Team policy")
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise RuntimeError("expected a native Linux x86_64 runner")
    node = subprocess.check_output(["node", "--version"], text=True).strip()
    pnpm = subprocess.check_output(["pnpm", "--version"], text=True).strip()
    if node != "v26.12.1" or pnpm != "11.28.5":
        raise RuntimeError("toolchain versions differ")
    if os.environ.get("GITHUB_REPOSITORY") != "z0rgoyok/deepseek-harness":
        raise RuntimeError("unexpected CI repository")
    workflow_commit = os.environ["GITHUB_SHA"]
    if len(workflow_commit) != 40 or any(c not in "0123456789abcdef" for c in workflow_commit):
        raise RuntimeError("invalid workflow commit")
    records = []
    for path in sorted(stage.rglob("*"), key=lambda value: value.relative_to(stage).as_posix()):
        relative = path.relative_to(stage).as_posix()
        info = path.lstat()
        mode = stat.S_IMODE(info.st_mode)
        if stat.S_ISDIR(info.st_mode):
            records.append({"path": relative, "type": "directory", "mode": mode})
        elif stat.S_ISREG(info.st_mode):
            records.append({"path": relative, "type": "file", "mode": mode, "bytes": info.st_size, "sha256": hash_file(path)})
        else:
            raise RuntimeError("packaged runtime contains a symlink or special entry")
    if not any(item["path"] == "node_modules/@deepseek-ai/dsh/lib/bin.js" and item["type"] == "file" for item in records):
        raise RuntimeError("packaged ACP executable is missing")
    manifest = output / "manifest.jsonl"
    manifest.write_text("".join(json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n" for item in records))
    archive = output / "runtime.tar"
    with tarfile.open(archive, "w", format=tarfile.PAX_FORMAT) as tar:
        for item in records:
            path = stage / item["path"]
            info = tarfile.TarInfo("runtime/" + item["path"])
            info.mode, info.uid, info.gid, info.mtime = item["mode"], 0, 0, 0
            info.uname, info.gname = "", ""
            if item["type"] == "directory":
                info.type = tarfile.DIRTYPE
                tar.addfile(info)
            else:
                info.size = item["bytes"]
                with path.open("rb") as stream:
                    tar.addfile(info, stream)
    with manifest.open(encoding="utf8") as stream:
        readback = [json.loads(line) for line in stream]
    if readback != records:
        raise RuntimeError("manifest changed during packaging")
    verify_archive(archive, readback)
    # The original files are read a second time after the archive was written.
    # A changed file or symlink prevents publication of a mismatched manifest.
    for item in records:
        path = stage / item["path"]
        info = path.lstat()
        if stat.S_IMODE(info.st_mode) != item["mode"]:
            raise RuntimeError("staged mode changed during packaging")
        if item["type"] == "file" and (not stat.S_ISREG(info.st_mode) or info.st_size != item["bytes"] or hash_file(path) != item["sha256"]):
            raise RuntimeError("staged file changed during packaging")
        if item["type"] == "directory" and not stat.S_ISDIR(info.st_mode):
            raise RuntimeError("staged directory changed during packaging")
    if {value.relative_to(stage).as_posix() for value in stage.rglob("*")} != {item["path"] for item in records}:
        raise RuntimeError("staged entries changed during packaging")
    published_policy = output / "qualification-policy.yml"
    shutil.copyfile(policy, published_policy)
    if hash_file(published_policy) != POLICY:
        raise RuntimeError("qualification policy changed during packaging")
    provenance = {
        "schema": 1,
        "repository": REPOSITORY,
        "source_commit": SOURCE,
        "pnpm_lock_sha256": LOCK,
        "node": node,
        "node_archive_sha256": "6170b2d474e1c626f43cff3adc118df9fe3b573258a4fc3d850c8dbc6b079bbd",
        "package_manager": "pnpm@" + pnpm,
        "pnpm_archive_integrity": "sha512-SEVj0wtMKtJ8tIqpT/KzAtvOvI/2vyiBbCWJiG4UbOf3bzVPO8GkOOb16XaMMCqgpvet2CMpA81M+BQmy8FNng==",
        "platform": "Linux-x86_64",
        "compiler": subprocess.check_output(["cc", "--version"], text=True).splitlines()[0],
        "libc": " ".join(platform.libc_ver()),
        "python": platform.python_version(),
        "artifact": archive.name,
        "artifact_sha256": hash_file(archive),
        "manifest": manifest.name,
        "manifest_sha256": hash_file(manifest),
        "qualification_policy": published_policy.name,
        "qualification_policy_sha256": POLICY,
        "qualification": "CI synthetic ACP/model/MCP; Agent Team provider qualification pending",
        "ci": {
            "repository": os.environ["GITHUB_REPOSITORY"],
            "workflow_commit": workflow_commit,
            "run_id": os.environ["GITHUB_RUN_ID"],
            "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
            "run_url": os.environ["GITHUB_SERVER_URL"] + "/" + os.environ["GITHUB_REPOSITORY"] + "/actions/runs/" + os.environ["GITHUB_RUN_ID"],
            "runner_image_os": os.environ.get("ImageOS"),
            "runner_image_version": os.environ.get("ImageVersion"),
        },
    }
    (output / "provenance.json").write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    print(json.dumps(provenance, sort_keys=True))


if __name__ == "__main__":
    main()
