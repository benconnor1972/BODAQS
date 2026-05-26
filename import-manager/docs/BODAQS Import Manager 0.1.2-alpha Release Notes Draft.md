# BODAQS Import Manager 0.1.2-alpha Release Notes Draft

Status: draft  
Release date: TBD

BODAQS Import Manager `0.1.2-alpha` is a small Windows alpha update focused on
Wi-Fi source portability and safer desktop app startup behavior.

## Changes Since 0.1.1-alpha

- Wi-Fi source provisioning now treats fixed logger IP addresses as an explicit
  opt-in.
- Discovered logger addresses are no longer automatically saved unless fixed
  address mode is selected.
- Existing Wi-Fi source settings can be viewed and edited from the source
  context menu.
- Wi-Fi actions can fall back to mDNS discovery when a remembered fixed address
  is stale or unreachable.
- The manager now prevents multiple running instances for the same app
  configuration, avoiding duplicate watchers, duplicate tray icons, and
  competing config edits.

## Installer

The Windows installer output is:

```text
bodaqs-import-manager-setup-0.1.2-alpha.exe
```

The installer remains GUI-only; the standalone CLI utility is not included.

## Validation Suggestions

- Install over `0.1.1-alpha` and confirm existing libraries and sources load.
- Provision a Wi-Fi source from discovery with fixed address mode off and
  confirm no fixed address is saved.
- Edit a Wi-Fi source, enable fixed address mode, save, then clear it again.
- Launch the manager a second time and confirm it reports that the manager is
  already running rather than opening a duplicate instance.
