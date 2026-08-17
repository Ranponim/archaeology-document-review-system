from pathlib import Path
p=Path('backend/app/services/file_store.py')
s=p.read_text(encoding='utf-8')
old='''    ".ai": frozenset(\n        {\n            "application/postscript",\n            "application/illustrator",\n            "image/vnd.adobe.illustrator",\n        }\n    ),\n}\n'''
new='''    ".ai": frozenset(\n        {\n            "application/postscript",\n            "application/illustrator",\n            "image/vnd.adobe.illustrator",\n        }\n    ),\n    ".indd": frozenset({"application/x-indesign"}),\n    ".json": frozenset({"application/json"}),\n}\n'''
if old not in s: raise SystemExit('mime map guard')
s=s.replace(old,new,1)
old='''    ".ai": "application/postscript",\n}\n'''
new='''    ".ai": "application/postscript",\n    ".indd": "application/x-indesign",\n    ".json": "application/json",\n}\n'''
if old not in s: raise SystemExit('default mime guard')
p.write_text(s.replace(old,new,1),encoding='utf-8')
