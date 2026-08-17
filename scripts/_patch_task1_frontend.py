from pathlib import Path

def R(p,o,n):
 f=Path(p); s=f.read_text(encoding='utf-8')
 if o not in s: raise SystemExit('guard failed '+p)
 f.write_text(s.replace(o,n,1),encoding='utf-8')
R('frontend/src/api.ts','''  internalCode: string | null;\n};\n''','''  internalCode: string | null;\n  createdAt?: string | null;\n  updatedAt?: string | null;\n};\n''')
p='frontend/src/pages/ProjectsPage.tsx'
R(p,'''type Props = {\n  onCreated: (project: Project) => void;\n  onSelect?: (project: Project) => void;\n};\n\nexport function ProjectsPage''','''type Props = {\n  onCreated: (project: Project) => void;\n  onSelect?: (project: Project) => void;\n};\n\nfunction formatProjectCreatedAt(value?: string | null): string {\n  if (!value) return '생성일 기록 없음';\n  const parsed = new Date(value);\n  if (Number.isNaN(parsed.getTime())) return '생성일 기록 없음';\n  return `생성일 ${new Intl.DateTimeFormat('ko-KR', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(parsed)}`;\n}\n\nexport function ProjectsPage''')
R(p,'''                  </p>\n                </div>\n                <button\n''','''                  </p>\n                  <p className="muted" style={{ margin: '4px 0 0', fontSize: '0.78rem' }}>\n                    {formatProjectCreatedAt(p.createdAt)}\n                  </p>\n                </div>\n                <button\n''')
