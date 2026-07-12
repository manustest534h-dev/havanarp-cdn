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
  --target .custom3
```

Verify every published part, the reconstructed ZIP, and the final VFS:

```sh
python3 tools/verify_multipart.py files/707/multipart/707/*
```

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
