# FREEBUFF ASSET — Reusable Asset & Source Library

Dedicated, self-contained library for the FREEBUFF ASSET workstream. This tree
never touches AV (AudioVideo) or AL (AvaLive) project content: all acquisitions,
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

## Task 4 — Asset Discovery, Indexing, and Routing

### Catalog Indexing

The catalog (`assetlib/catalog/assets.json`) is the single source of truth
for all ready assets. It is built by `assetlib/tools/catalog.build_catalog()`:

1. **SPEC entries** — 6 core assets (cesium_milk_truck, black_suv, cesium_man,
   fox, modern_building, lantern) are defined with id, category, name, license,
   source path, path on disk, preview, tags, description, format, materials,
   and validation_status. Paths are verified to exist at build time.

2. **D: bulk indexing** — Assets placed in configured D: storage roots
  (`D:/AI/_Assets/<category>`, `D:/BlenderAssets/SourceAssets`, etc.) are
  automatically scanned and indexed without being copied into the active project.
  Each discovered asset receives an `id` prefixed with `d_`, derives its format
  from the file extension, and records `validation_status: "indexed"`.

3. **Duplicate detection** — During build, entry IDs are checked for
  uniqueness. Duplicate IDs are logged as `problems` and the entry is skipped.

4. **Backward compatibility** — `load_catalog()` backfills new metadata fields
  (`format`, `materials`, `validation_status`) for older catalog JSON entries
  that lack them.

### Supported Metadata Fields

| Field | Type | Description |
|---|---|---|
| `id` | str | Unique asset identifier |
| `category` | str | One of: Vehicles, Characters, Animations, Buildings, Props, Nature, etc. |
| `name` | str | Human-readable asset name |
| `license` | str | License text (CC-BY, CC0, etc.) |
| `source` | str | Original source file path |
| `path` | str | UE-ready asset path on disk |
| `preview` | str | Preview image path |
| `tags` | list[str] | Free-text tags for search indexing |
| `format` | str | File format: `fbx`, `glb`, `obj`, etc. (derived from extension) |
| `materials` | list[str] | Associated material names |
| `validation_status` | str | `indexed` < `pending` < `valid` < `verified` |
| `ue_class` | str | Unreal class: `StaticMesh`, `SkeletalMesh`, or `None` |
| `size_cm` | list[float] | Bounds in cm from Unreal read-back |
| `animations` | list[str] | Animation sequence names |
| `ue_compatible` | str | Target UE engine version (e.g. `5.8`) |
| `display_scale` | float | Placement scale factor |
| `lod` | str | Level-of-detail description |
| `collision` | str | Collision setup description |

### Validation States

Assets progress through four validation states:

- **indexed** — Asset found on D: disk or in source; metadata complete enough for
  search but not yet verified via Unreal import.
- **pending** — Asset has been through a transformation step (e.g. Blender tint)
  but UE import metrics not yet attached.
- **valid** — Asset has been successfully imported into Unreal; class, size,
  skeleton, and animations verified from acceptance marker.
- **verified** — Asset placement scale and materials confirmed via downstream
  quality check (currently used for fox: 0.0201, lantern: 0.1304).

The router's `score()` function accepts `min_validation` to filter results:
`score(cat, "vehicle", min_validation="valid")` returns only entries with
`validation_status` of `valid` or `verified`.

### Duplicate Handling

During `build_catalog()`, each SPEC entry's `id` is checked against previously
seen IDs. If a duplicate is found, a problem is recorded:
`f"duplicate entry id: {entry['id']}"` and the entry is not added. This prevents
silent data corruption when the same asset appears in multiple places.

### Router Selection Behavior

The natural-language router (`assetlib/tools/router`) translates a user query
into an ordered list of matching assets:

1. **Classify** — Query terms are mapped to intents (`place` vs `query`) and
   categories (Vehicles, Characters, Animations, Props, Buildings).

2. **Score** — Each catalog entry is scored based on:
   - Tag/keyword matches in id, name, and tags
   - Exact ID substring nudge (+2 points)
   - Black-SUV derived override (+3 pts if query contains "black")
   - GLB type preference (+1 pt for `.glb` paths)
   - Validation and compatibility filters applied first

3. **Plan** — Top-ranked assets are selected for actions:
   - `place` — spawn asset in Unreal at display_scale
   - `modify_blender` — run tint_black.py for derived variants
   - `import` — import geometry into disposable UE project
   - `validate` — check class, size_cm, materials, collision
   - `screenshot` — capture viewport

4. **Unmatched categories** — If the query targets Buildings or Interiors
   and no indexed assets exist, a note is added: "no indexed asset (Sponza
   rejected: Cryengine license, not CC)".

### How Aivido Finds and Uses Ready Assets

Aivido's asset pipeline works as follows:

1. **Receive request** — Natural-language command (e.g. "spawn a black SUV")
2. **Classify** — Router identifies intent and relevant categories
3. **Query catalog** — `score()` returns ranked assets with metadata
4. **Filter** — `min_validation` and `engine_compat` filters narrow results
5. **Select** — Top-ranked valid asset is chosen
6. **Route** — Plan generates actions: blender modify → Unreal import → place → validate → screenshot
7. **Validate** — Placement verification checks class, bounds, materials
8. **Proof** — Screenshot + read-back confirms asset in level

### Problem Reporting

Catalog build problems are recorded in `assets.json["problems"]` and include:
- Missing source/file on disk
- Duplicate entry IDs
- Unrecognized categories
- Format/material mismatches
