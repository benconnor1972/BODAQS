# BODAQS Study Set Workbench Prototype

Static React/Vite prototype for the BODAQS Library Browser and Study Set
Builder.

The current prototype is fixture-backed. It does not call the BODAQS Library API
yet and does not persist Study Sets to disk.

## Run

```powershell
cd C:\Users\benco\dev\BODAQS\application\cohort-workbench-prototype
npm install
npm run dev
```

If the current terminal does not know where Node.js is, open a fresh terminal or
prepend the Node install path:

```powershell
$env:Path = "C:\Program Files\nodejs;$env:Path"
```

## Checks

```powershell
npm run build
npm run lint
```

## Current Scope

- Select one or more libraries from fixture data.
- Browse, sort, filter, and inspect fixture sessions.
- Add selected sessions to the current Study Set.
- Create overlapping Study Set-local groupings with short names.
- Attach existing fixture tracks to the current Study Set.
- Save/load/view Study Sets in in-memory mock state.
- Use Analyze now to create an unsaved one-session Study Set.

Track creation/editing, saved filter management, real Library API access, and
chart navigation are reserved for later prototype passes.
