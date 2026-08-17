from pathlib import Path
p=Path('backend/app/graph/project_repository.py')
s=p.read_text(encoding='utf-8')
o='''            MATCH (project:Project {id: $project_id})\n            SET project.updatedAt = datetime()\n            OPTIONAL MATCH (project)-[:HAS_REVIEW_ROUND]->(existing:ReviewRound)\n'''
n='''            MATCH (project:Project {id: $project_id})\n            SET project.updatedAt = datetime()\n            WITH project\n            OPTIONAL MATCH (project)-[:HAS_REVIEW_ROUND]->(existing:ReviewRound)\n'''
if o not in s: raise SystemExit('guard failed')
p.write_text(s.replace(o,n,1),encoding='utf-8')
