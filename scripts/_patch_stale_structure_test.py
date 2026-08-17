from pathlib import Path
p=Path('frontend/src/components/ProjectStructureExplorer.test.tsx')
s=p.read_text(encoding='utf-8')
old="""    expect(await screen.findByText('RESOLVES_TO')).toBeInTheDocument();\n    expect(screen.getByText('【도판 45】')).toBeInTheDocument();\n"""
new="""    const semanticRelationship = await screen.findByText('인용 대상 연결');\n    expect(semanticRelationship).toBeInTheDocument();\n    expect(semanticRelationship).toHaveAttribute('title', 'RESOLVES_TO');\n    expect(screen.getByText('【도판 45】')).toBeInTheDocument();\n"""
if old not in s: raise SystemExit('stale relationship assertion guard failed')
p.write_text(s.replace(old,new,1),encoding='utf-8')
