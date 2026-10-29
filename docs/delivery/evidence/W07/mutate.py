import subprocess, sys, pathlib
root=pathlib.Path('/home/user/overwatch-wt/W07/frontend')
M=[
 ('M1 pending shown on last known','components/board/Tile.tsx',"const pending = lastKnown ? 0 : entry.pending;","const pending = entry.pending;"),
 ('M2 pressure banner shown while last known','components/board/Board.tsx',"{lastKnown ? null : <PressureBanner board={board} />}","<PressureBanner board={board} />"),
 ('M3 banner counts out-of-hours','components/board/PressureBanner.tsx',"board.entries.filter((e) => e.status !== 'out-of-hours').length","board.entries.length"),
 ('M4 banner ignores the flag','components/board/PressureBanner.tsx',"if (!board.allLimitedOrWorse) return null;",""),
 ('M5 banner with no service in hours','components/board/PressureBanner.tsx',"if (inHours === 0) return null;",""),
 ('M6 banner singular dropped','components/board/PressureBanner.tsx',"inHours === 1 ?","inHours === 99 ?"),
 ('M7 tenant id allowed','lib/board/parse.ts',"if (TENANT_PARTS.some((name) => parts.has(name))) fail('an entry carries a tenant id');",""),
 ('M8 foreign org allowed','lib/board/parse.ts',"if (entryOrganisation !== null && entryOrganisation !== organisation) {","if (false) {"),
 ('M9 out of hours shows free count','components/board/Tile.tsx',"return { big: '0', unit: entry.unitLabel,","return { big: String(entry.effectiveAvailable ?? 0), unit: entry.unitLabel,"),
 ('M10 out of hours shows comment','components/board/Tile.tsx',"entry.nextDueAt === null ? null : (","entry.comment === 'zzz' ? null : ("),
 ('M11 bar label drops pending','components/board/Tile.tsx',"pending > 0 ? `${figure.bar.label} · ${pending} pending` : figure.bar.label","figure.bar.label"),
 ('M12 tomorrow word wrong','lib/board/format.ts',"if (days === 1) return ' tomorrow';","if (days === 2) return ' tomorrow';"),
 ('M13 out-of-hours bar not full','components/board/Tile.tsx',"bar: { label: OUT_OF_HOURS_LABEL, percent: 100 }","bar: { label: OUT_OF_HOURS_LABEL, percent: 0 }"),
 ('M14 pending reduces number','components/board/Tile.tsx',"{figure.big}\n        </p>","{pending > 0 && /^\\d+$/.test(figure.big) ? String(Math.max(0, Number(figure.big) - pending)) : figure.big}\n        </p>"),
 ('M15 Closed overnight removed','lib/board/format.ts',"if (entry.status === 'out-of-hours') return 'Closed overnight';",""),
 ('M16 reopens uses UTC','lib/board/format.ts',"return `Reopens ${londonTime(nextDueAt)}${dayWord(nextDueAt, now)}`;","return `Reopens ${new Date(nextDueAt).toISOString().slice(11,16)}${dayWord(nextDueAt, now)}`;"),
]
for name,f,old,new in M:
    p=root/f; src=p.read_text()
    assert src.count(old)==1,(name,src.count(old))
    p.write_text(src.replace(old,new))
    try:
        r=subprocess.run(['pnpm','exec','vitest','run','components/board','lib/board','app'],cwd=root,capture_output=True,text=True)
        out=r.stdout+r.stderr
        line=[l for l in out.splitlines() if l.strip().startswith('Tests')]
        print(('KILLED  ' if r.returncode!=0 else 'SURVIVED'),name,line[-1].strip() if line else '')
    finally:
        p.write_text(src)
