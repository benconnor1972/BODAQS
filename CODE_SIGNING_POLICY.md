# Code Signing Policy

## Scope

This policy applies to official BODAQS Desktop releases published from the
[BODAQS GitHub repository](https://github.com/benconnor1972/BODAQS).

Official release artifacts are built from the public source code and build
configuration in that repository. BODAQS does not sign third-party projects or
artifacts not built from BODAQS-controlled source code.

## Signing status

- Windows: BODAQS release candidates are manually signed by the release approver
  with a Certum Open Source Code Signing in Cloud certificate stored in
  SimplySign, after certificate issuance and activation. The final installer is
  timestamped and verified before publication.
- macOS: BODAQS `Desktop-v*` releases are signed with an Apple Developer ID
  certificate, notarized by Apple, and stapled before publication.
- Linux: BODAQS release tags use Sigstore keyless signing for the Linux archive.
  The associated Sigstore bundle identifies the GitHub Actions release workflow
  and tag that produced the artifact.
Until a platform's signing process is configured and active, its releases may be unsigned. Each GitHub Release will state the signing and verification status of its artifacts.

## Release process

Official BODAQS Desktop releases are created from versioned release tags and
built by GitHub-hosted GitHub Actions runners.

Before signing, the release workflow:

1. checks out the tagged BODAQS source;
2. runs the applicable automated tests and packaged smoke tests;
3. builds a Windows installer candidate, a macOS DMG, and a Linux archive;
4. signs, notarizes, staples, and verifies the macOS DMG; and
5. keylessly signs and verifies the Linux archive with Sigstore.

The Windows installer candidate is downloaded only by the release approver,
checked against the workflow-generated SHA-256 manifest, signed with Certum
through SimplySign, timestamped, and verified with `signtool` before it is
published. The signed Windows installer and a newly generated SHA-256 checksum
are retained as the release files.

Only artifacts published through the BODAQS GitHub Releases page are official
BODAQS release downloads.

## Roles

- Committers and reviewers: Ben Connor, George Connor, and David Staley
- Signing approver: Ben Connor

All BODAQS maintainers with repository write access, Apple Developer users, and
the Certum/SimplySign signing user must use multi-factor authentication.

Changes proposed by contributors who do not have commit access must be reviewed
by a project maintainer before merging.

## Reporting a concern

To report a suspected compromised, incorrectly signed, or malicious BODAQS
release, open a private GitHub security advisory for this repository or contact
the project maintainer through the repository.
