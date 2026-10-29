# Inherited workflow trigger audit

Snapshot: 29 October 2026. The fork default branch `master` was `f3803c96974ad4a94195fb97e5c637e9c2a3afe3`; its workflow tree matched source commit `76b0743e339d78e24680db39747b81e101d2c236`. The repository reported Actions enabled and zero registered workflows, while the default branch contained 31 workflow files. Registration, fork enablement and schedules must be rechecked before any push.

This proposed CI branch is an orphan containing only its dedicated push-triggered workflow and CI driver. It must not be opened as a PR or merged into the source branch. The seven inherited push triggers all filter to `master`, or `main` and `master`; none names the proposed CI branch. The inherited `workflow_run` filter names `weighted-approval-review-event`, not this workflow. The default branch also contains a scheduled e2e workflow and workflows that request write permissions, external deployment and/or secrets; a new run must not be treated as proof that these cannot activate independently.

The table covers top-level event declarations and explicit workflow/job write permissions. It does not establish repository variables, secret availability, all action behavior or GitHub event-delivery behavior. No action or workflow was enabled, pushed or run as part of this audit.

| Workflow | Events | Explicit write permissions |
| --- | --- | --- |
| build-exe-for-python-sdk.yml | workflow_call, workflow_dispatch | — |
| build-exe-for-ssh-helper.yml | workflow_call, workflow_dispatch | — |
| build-preview-cloudflare.yml | pull_request | workflow: pull-requests |
| ci-master.yml | push, workflow_dispatch | — |
| ci-python.yml | pull_request | — |
| ci-windows.yml | pull_request | — |
| ci.yml | pull_request | — |
| desktop-publish.yml | workflow_dispatch | — |
| docs-pages.yml | workflow_dispatch | deploy: pages, id-token |
| e2e.yml | workflow_dispatch, push, pull_request, schedule | — |
| expected-filenames.yml | pull_request | — |
| issue-lifecycle.yml | issues, pull_request, pull_request_review | — |
| issue-policy.yml | pull_request, pull_request_review | — |
| macos-intel-package.yml | workflow_dispatch | — |
| macos-package.yml | workflow_dispatch | — |
| node-addon-system-release.yml | workflow_dispatch | publish: id-token |
| node-addon-system.yml | pull_request, push, workflow_dispatch | — |
| pi-ai-provider-e2e.yml | workflow_dispatch | — |
| pr-check-after-approve.yml | pull_request_target, pull_request_review | review: checks |
| pr-check-on-base-branch.yml | push, workflow_dispatch | recheck: actions |
| pr-check-on-head-branch.yml | pull_request_target | — |
| publish-ssh-helper.yml | workflow_dispatch | publish: contents |
| python-release.yml | workflow_dispatch | publish-runtime: id-token; publish-sdk: id-token |
| release-publish.yml | workflow_dispatch | — |
| release-vendor-publish.yml | workflow_dispatch | — |
| release-vendor.yml | pull_request, push, workflow_dispatch | — |
| release.yml | pull_request, push, workflow_dispatch | — |
| sandbox.yml | push | — |
| weighted-approval-review-event.yml | pull_request_review | — |
| weighted-approval.yml | pull_request_target, issue_comment, workflow_run | workflow: checks, pull-requests, statuses |
| windows-package.yml | workflow_dispatch | — |
