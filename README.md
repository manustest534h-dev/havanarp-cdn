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
