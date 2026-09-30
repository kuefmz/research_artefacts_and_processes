#!/usr/bin/env python3
"""Restore original PDF and ZIP from numbered parts; verify SHA-256 before writing."""
import hashlib,json,pathlib
root=pathlib.Path(__file__).resolve().parent
for item in json.loads((root/'CHUNKED_FILES.json').read_text()):
    data=b''.join((root/part).read_bytes() for part in item['parts'])
    if len(data)!=item['bytes'] or hashlib.sha256(data).hexdigest()!=item['sha256']:
        raise ValueError('Integrity check failed: '+item['path'])
    target=root/item['path']
    target.write_bytes(data)
    print('Restored and verified:',target.relative_to(root))
