# havanarp-cdn
HavanaRP game update CDN assets

## VFS validation

Validate an unpacked VFS archive before publishing:

```sh
python3 tools/vfs_archive.py path/to/.custom3
```

If an inner file was enlarged, repair its outer VFS record sizes using the
matching unmodified archive:

```sh
python3 tools/vfs_archive.py modified/.custom3 \
  --base original/.custom3 \
  --output fixed/.custom3
```

Rebuild the deterministic multipart payload:

```sh
python3 tools/build_multipart.py fixed/.custom3 \
  files/707/multipart/707/custom3 \
  --target .custom3 \
  --marker .live_russia_skins_17515
```

Verify every published part, the reconstructed ZIP, and the final VFS:

```sh
python3 tools/verify_multipart.py files/707/multipart/707/*
```

Launcher v726 pins multipart downloads to an older CDN commit. Publish the
verified update 707 outputs as `default.custom3*.zip` and `default.data` assets
on the `data-flags-707-test` release, then route the manifest through the
launcher's direct release fallback:

```sh
python3 tools/direct_release.py api/update/705/update_705.json
```

The five direct targets must remain at version 707 because that is the version
the launcher maps to the release asset URLs.

Move object definitions that were appended after the IDE sections back into
the `objs` section and add minimal valid collision records for those models:

```sh
python3 tools/ide_sections.py fixed/.data fixed/.data.repaired
```

If a migrated texture database has more `.txt`/`.toc` entries than `.tmb`
records, add valid format-specific thumbnails before rebuilding its archive:

```sh
python3 tools/texture_thumbnails.py fixed/.custom3_etc \
  --output repaired/.custom3_etc
```

## Live Russia skins

The Live Russia skin builder requires Python 3, Pillow, `texture2ddecoder`, and
`PVRTexToolCLI`. It preserves the existing VFS records and adds a separate
`lr_skins` IMG, IDE, and DXT/ETC/PVR texture database:

```sh
PYTHONPATH=tools python3 tools/build_live_russia_skins.py \
  --source-dir path/to/current-archives \
  --source-img path/to/lr_skins.img \
  --source-astc path/to/lr_skins.astc_arc \
  --ped-models path/to/ped_models.json \
  --pvrtex-tool path/to/PVRTexToolCLI \
  --output-dir path/to/output
```

The generated model IDs are `17083–17495` and `17497–17515`. ID `17496`
remains reserved, and the existing flag IDs `17000–17082` are not changed.
