from pathlib import Path

p = Path('frontend/src/components/EvidenceGraphExplorer.test.tsx')
s = p.read_text(encoding='utf-8')
replacements = [
    (
        "expect(screen.getByText('【도판 45】')).toBeInTheDocument();",
        "expect(screen.getByText('[도판 패널] 조사 전')).toBeInTheDocument();",
    ),
    (
        "expect(screen.getByText('【도판 45】')).toBeInTheDocument();",
        "expect(screen.getByText('[도판 45] 1지점 청동기시대 6호 석관묘')).toBeInTheDocument();",
    ),
]
for old, new in replacements:
    if old not in s:
        raise SystemExit('semantic test patch guard failed')
    s = s.replace(old, new, 1)
p.write_text(s, encoding='utf-8')
