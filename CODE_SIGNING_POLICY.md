# Code Signing Policy

## Scope

This policy applies to official BODAQS Desktop releases published from the
[BODAQS GitHub repository](https://github.com/benconnor1972/BODAQS).

Official release artifacts are built from the public source code and build
configuration in that repository. BODAQS does not sign third-party projects or
artifacts not built from BODAQS-controlled source code.

## Signing provider

BODAQS has applied, or intends to apply, for free code signing through SignPath.io and the SignPath Foundation. No BODAQS artifact is currently represented as SignPath-signed unless its GitHub Release explicitly identifies it as such and the signature verifies successfully.

## Signing status

Windows: BODAQS intends to use SignPath.io code signing provided through the SignPath Foundation, subject to application approval and project configuration.  
macOS: BODAQS intends to sign direct-distribution releases with an Apple Developer ID certificate and submit them to Apple for notarization, subject to Apple Developer Program enrolment and workflow configuration.  
Linux: BODAQS intends to publish integrity-verifiable release artifacts, initially using signed release metadata and/or Sigstore keyless signing, subject to workflow configuration.  
Until a platform’s signing process is configured and active, its releases may be unsigned. Each GitHub Release will state the signing and verification status of its artifacts.

## Release process

Official BODAQS Desktop releases are created from versioned release tags and
built by GitHub-hosted GitHub Actions runners.

Before signing, the release workflow:

1. checks out the tagged BODAQS source;
2. runs the applicable automated tests and packaged smoke tests;
3. builds the Windows release artifact; and
4. submits the unsigned artifact to SignPath for origin verification and
   approval.

The signed artifact is verified before it is published as an official GitHub
Release.

Only artifacts published through the BODAQS GitHub Releases page are official
BODAQS release downloads.

## Roles

- Committers and reviewers: Ben Connor, George Connor, and David Staley
- Signing approver: Ben Connor

All BODAQS maintainers with repository write access and all SignPath users must
use multi-factor authentication.

Changes proposed by contributors who do not have commit access must be reviewed
by a project maintainer before merging.

## Reporting a concern

To report a suspected compromised, incorrectly signed, or malicious BODAQS
release, open a private GitHub security advisory for this repository or contact
the project maintainer through the repository.
