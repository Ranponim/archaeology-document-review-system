from pathlib import Path

def R(p,o,n):
 f=Path(p); s=f.read_text(encoding='utf-8')
 if o not in s: raise SystemExit('guard failed '+p)
 f.write_text(s.replace(o,n,1),encoding='utf-8')
R('backend/app/domain/models.py','''@dataclass(frozen=True, slots=True)\nclass Project:\n    id: str\n    name: str\n    internal_code: str | None\n''','''@dataclass(frozen=True, slots=True)\nclass Project:\n    id: str\n    name: str\n    internal_code: str | None\n    created_at: str | None = None\n    updated_at: str | None = None\n''')
R('backend/app/api/schemas.py','''class ProjectResponse(ApiModel):\n    id: str\n    name: str\n    internal_code: str | None = Field(alias="internalCode")\n''','''class ProjectResponse(ApiModel):\n    id: str\n    name: str\n    internal_code: str | None = Field(alias="internalCode")\n    created_at: str | None = Field(default=None, alias="createdAt")\n    updated_at: str | None = Field(default=None, alias="updatedAt")\n''')
p='backend/app/api/projects.py'
R(p,'from collections.abc import Callable\n','from collections.abc import Callable\nfrom pathlib import Path\n')
R(p,'''            internal_code=project.internal_code,\n        )\n        for project in projects\n''','''            internal_code=project.internal_code,\n            created_at=project.created_at,\n            updated_at=project.updated_at,\n        )\n        for project in projects\n''')
R(p,'''        internal_code=project.internal_code,\n    )\n\n\n@router.post(\n    "/{project_id}/documents",\n''','''        internal_code=project.internal_code,\n        created_at=project.created_at,\n        updated_at=project.updated_at,\n    )\n\n\n@router.post(\n    "/{project_id}/documents",\n''')
R(p,'''    normalized_project_id = str(project_id)\n    # Validate project existence before accepting original bytes. The write\n''','''    normalized_project_id = str(project_id)\n    if Path(file.filename or "").suffix.lower() != ".pdf":\n        raise ValueError("Publication document uploads must be PDF")\n    # Validate project existence before accepting original bytes. The write\n''')
R(p,'''        internal_code=project.internal_code,\n        documents=[\n''','''        internal_code=project.internal_code,\n        created_at=project.created_at,\n        updated_at=project.updated_at,\n        documents=[\n''')
R('backend/tests/test_projects_api.py','''        "internalCode": "NONSAN-001",\n    }\n''','''        "internalCode": "NONSAN-001",\n        "createdAt": None,\n        "updatedAt": None,\n    }\n''')
