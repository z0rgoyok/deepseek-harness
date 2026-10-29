# Linux qualification driver

This is an isolated orphan CI branch. Its single workflow runs on a push to
`ci/deepseek-linux-qualification`; it separately checks out source commit
`76b0743e339d78e24680db39747b81e101d2c236` from the operator's fork. The
workflow commit and the source commit are distinct and both enter the build
record. Review the [trigger audit](TRIGGER-AUDIT.md) and current repository
settings before pushing. Do not merge this CI branch into the application PR.

The hosted Ubuntu x86_64 job downloads Node.js 26.12.1 and pnpm 11.28.5 with
fixed archive hashes, installs the locked workspace with scripts disabled,
builds the host native addon and host libraries, and deploys and materializes
the runtime closure. It loads the packaged native flock addon and drives the
packaged ACP profile against loopback-only synthetic model and MCP peers. It
checks model output, MCP authentication and execution, credential environment
isolation, explicit close, resume and prior context. No provider credentials or
production endpoint are configured; dependency and tool downloads still require
network access. There is no Actions shared cache. The job has read-only contents
permission; checkout does not retain its short-lived GitHub credential.

The workflow publishes `runtime.tar`, `manifest.jsonl`, `provenance.json`, and
the exact `qualification-policy.yml` only after these checks pass. The manifest
records file mode, length and SHA-256; links and special files are rejected.
The archive is read back in full and compared with that manifest. The build
record ties the artifact, manifest and qualification policy hashes to the source
commit, workflow commit and GitHub run ID. It is not a signed attestation. The
CI run logs and uploaded artifact must be read back and checked against those
fields before use. Deployment must separately compare its active policy with the
qualified policy and validate any differences.

The test covers the packaged DSH ACP runtime. The Agent Team repository is
private and unavailable to this fork's read-only token without a separate
credential. Therefore the actual Agent Team Go provider and packaged UI remain a
separate downstream qualification after retrieving the Linux artifact. A live
gateway, Linux restricted modes, browser/device acceptance, server deployment,
and production readiness are outside this job's evidence.
