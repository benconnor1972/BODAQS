# BODAQS Demo Library 0.2.2-beta Release Notes

Release date: TBD

The BODAQS Demo Library provides a ready-to-browse local library for exploring
BODAQS Desktop and the Workbench without importing data from a logger.

## Download

- Archive: `BODAQS-Demo-Library-0.2.2-beta.zip`
- Archive manifest: `BODAQS-Demo-Library-0.2.2-beta.manifest.json`
- Archive SHA-256:

  ```text
  570cb4b6887710a046b4d85077ba03b084712a7cdcb9686fdf97b46c58a81012
  ```

The manifest records a SHA-256 checksum for the archive and for every packaged
file.

## Install the Demo Library

Unpack the archive into the **BODAQS workspace root**—the folder containing
your `libraries` and `sources` folders. Do not unpack it into the `libraries`
folder itself.

For example, if the Import Manager is configured with:

```text
Workspace root: C:\Users\your-name\BODAQS
Libraries root: C:\Users\your-name\BODAQS\libraries
```

extract the archive to:

```text
C:\Users\your-name\BODAQS\
```

After extraction, the workspace should contain this shape:

```text
BODAQS\
  libraries\
    bodaqs-demo\
      library_definition.json
      runs\
      ...
  study_sets\
  tracks\
  bookmarks\
  session_filters\
  demo_manifest.json
```

The archive does not include an extra enclosing folder. If your extraction tool
offers to create a folder named after the zip automatically, open that folder
and move its contents into the workspace root instead.

Then open the Import Manager and either:

- select the existing workspace in the first-run setup; or
- use **Provision** to select the workspace's existing Libraries root, then
  refresh/synchronise the managed workspace.

`BODAQS Demo Library` should then appear in the Import Manager and Workbench.

## Existing Demo Library

Do not extract this archive over an existing `libraries\bodaqs-demo` folder.
Either keep the existing demo library, or first move/delete that folder and the
companion demo items you want to replace (`study_sets`, `tracks`, `bookmarks`,
and `session_filters`). This avoids a mixed-version library.

## Contents and Deliberate Omissions

This archive includes the library’s processed sessions, tracks, study sets,
bookmarks, session filters, recipes, and `demo_manifest.json`.

To keep the download practical, it deliberately excludes:

- video files;
- video attachment records; and
- generated `.bodaqs_library_api_cache` data.

The Library Service rebuilds its cache when the demo is opened. Video workflows
will not be available from this archive.
