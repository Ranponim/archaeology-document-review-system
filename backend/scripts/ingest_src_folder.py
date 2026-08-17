from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from neo4j import GraphDatabase

from app.config import DATA_ROOT
from app.graph.source_asset_repository import SourceAssetRepository
from app.services.file_store import FileStore
from app.services.source_import_service import SourceImportService


def main() -> int:
    parser = argparse.ArgumentParser(description='Import raw archaeology source files as provenance-only OriginalAsset nodes.')
    parser.add_argument('--project-id', required=True)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--manifest', type=Path)
    args = parser.parse_args()

    uri = os.environ.get('NEO4J_URI', 'bolt://localhost:7687')
    user = os.environ.get('NEO4J_USER', 'neo4j')
    password = os.environ.get('NEO4J_PASSWORD', 'password')
    database = os.environ.get('NEO4J_DATABASE') or None

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        service = SourceImportService(
            FileStore(DATA_ROOT),
            SourceAssetRepository(driver, database=database),
        )
        result = service.import_folder(
            args.project_id,
            args.source_root,
            manifest_path=args.manifest,
        )
        print(json.dumps({
            'importBatchId': result.import_batch_id,
            'imported': len(result.imported),
            'errors': list(result.errors),
        }, ensure_ascii=False, indent=2))
        return 0
    finally:
        driver.close()


if __name__ == '__main__':
    raise SystemExit(main())
