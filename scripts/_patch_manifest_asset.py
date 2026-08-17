from pathlib import Path
p=Path('backend/app/services/source_import_service.py')
s=p.read_text(encoding='utf-8')
o='''                Path(manifest_path),\n                assets_by_relative,\n                imported,\n                errors,\n'''
n='''                Path(manifest_path),\n                batch_id,\n                assets_by_relative,\n                imported,\n                errors,\n'''
if o not in s: raise SystemExit('call guard')
s=s.replace(o,n,1)
o='''        manifest_path: Path,\n        assets: dict[str, OriginalAssetData],\n'''
n='''        manifest_path: Path,\n        import_batch_id: str,\n        assets: dict[str, OriginalAssetData],\n'''
if o not in s: raise SystemExit('signature guard')
s=s.replace(o,n,1)
o="""            if payload.get('version') != 1 or not isinstance(payload.get('mappings'), list):\n                raise ValueError('Unsupported provenance manifest')\n"""
n="""            if payload.get('version') != 1 or not isinstance(payload.get('mappings'), list):\n                raise ValueError('Unsupported provenance manifest')\n            relative_manifest = self._normalized_relative(resolved_manifest.relative_to(boundary))\n            stored_manifest = self.file_store.store_bytes(\n                project_id, resolved_manifest.name, raw, 'application/json'\n            )\n            manifest_asset = OriginalAssetData(\n                id=self._asset_id(project_id, relative_manifest, stored_manifest.sha256),\n                project_id=project_id, uri=stored_manifest.uri, sha256=stored_manifest.sha256,\n                size_bytes=stored_manifest.size_bytes, mime_type=stored_manifest.mime_type,\n                original_name=stored_manifest.original_name, relative_path=relative_manifest,\n                asset_kind='provenance_manifest', source_root_name=boundary.name,\n                import_batch_id=import_batch_id, parse_status='parsed',\n                provenance_status='declared', source_metadata={'manifestVersion': 1},\n            )\n            self.repository.save_original_asset(manifest_asset)\n            imported.append(manifest_asset)\n"""
if o not in s: raise SystemExit('manifest guard')
p.write_text(s.replace(o,n,1),encoding='utf-8')
