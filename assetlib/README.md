# FREEBUFF ASSET — Reusable Asset & Source Library

Dedicated, self-contained library for the FREEBUFF ASSET workstream. This tree
never touches AV (AudioVido) or AL (AvaLive) project content: all acquisitions,
generated content, index data, test projects, and proof live under `assetlib/`.

## Layout

```
assetlib/
  README.md            this charter
  tools/               reusable host-side + in-app automation (Python/PS1)
  content/             ready assets organized by UE category (catalogued)
  source/              original downloads/extracts used to build content
  downloads/           large installer / content archives (rare, checked-in-free)
  projects/            separate UE source projects (City Sample, samples, ...)
  tests/               temporary test areas (Blender smoke, UE import smoke)
  proof/               screenshots + reports
  catalog/             ready-asset index (catalog.json + natural-language router)
```

## Conventions

- **Scale**: Blender scenes are metric meters (1 BU = 1 m). FBX exports use
  `apply_unit_scale=True` (writes cm = Unreal units). GLB is meter-based and
  Unreal's glTF importer converts on import. Unreal read-back (bounds cm) is
  the authoritative verification.
- **Exports**: FBX with `-Z` forward / `Y` up, textures embedded; GLB Y-up.
  Reuses the proven `blender_agent` export settings via import, never a copy.
- **Unreal isolation**: disposable UE projects under `assetlib/tests/ue/` are
  hand-written and DO NOT include the UnrealAgentBridge plugin, its Python
  bootstrap, or fixed-port listeners. We never stop or modify AV/AL editors.
- **Licensing**: every catalogued asset records source + license. Only
  official / free redistributable resources are acquired. No scraping of
  copyrighted models.

## Pipeline

request -> classify -> query/score ready assets -> modify only if needed ->
Blender only if required -> Unreal migration/import -> validate/screenshot

Milestone reports: `assetlib/reports/`.
