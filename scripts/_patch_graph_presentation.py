from pathlib import Path
p=Path('frontend/src/components/EvidenceGraphExplorer.tsx')
s=p.read_text(encoding='utf-8')
needle="} from '../api';\n"
if needle not in s: raise SystemExit('import guard')
s=s.replace(needle, needle+"import { relationshipLabel, semanticNodeTitle } from '../graphPresentation';\n",1)
start=s.index('function canonicalTitleForLabel(')
end=s.index('\nfunction canonicalSubtitleForLabel', start)
s=s[:start]+'''function canonicalTitleForLabel(\n  label: string | undefined,\n  props: Record<string, unknown>,\n): string {\n  return semanticNodeTitle(label, props);\n}\n'''+s[end:]
repls={
"title: `후보: ${candId.slice(0, 14)}`,":"title: semanticNodeTitle('CorrectionCandidate', { ...(candProps ?? {}), rule_category: candProps?.rule_category ?? candidate.rule_category ?? candidate.category }),",
"title: archObj.id.slice(0, 14),":"title: semanticNodeTitle('ArchaeologyObject', archObj as unknown as Record<string, unknown>),",
"title: canonical.printedIdentifier ?? canonical.regionId ?? '표준 자산',":"title: semanticNodeTitle(assetTypeTag[canonical.assetType], { number: canonical.printedIdentifier?.replace(/[^0-9]/g, ''), caption: canonical.caption, title: canonical.caption }),",
"title: evId.slice(0, 14),":"title: `[근거] ${ev.kind ?? ev.method ?? '검수 근거'}`,",
"title: pageId.slice(0, 14),":"title: `[페이지] ${page.physical_page ?? '?'}`,",
"title: dvId.slice(0, 14),":"title: `[문서 버전] ${docVer.stage ?? 'source'}`,",
"title: decId.slice(0, 14),":"title: `[검수 결정] ${dec.decision_status ?? dec.decision ?? '대기'}`,",
"<span className=\"edge-label\">[:{label}]</span>":"<span className=\"edge-label\" title={label}>[{relationshipLabel(label)}]</span>",
}
for old,new in repls.items():
 if old not in s: raise SystemExit('replace guard: '+old[:50])
 s=s.replace(old,new,1)
p.write_text(s,encoding='utf-8')
