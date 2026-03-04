import re
lines=open('app.py','r',encoding='utf-8').read().splitlines()
stack=[]
for i,l in enumerate(lines, start=1):
    s=l.lstrip('\t')
    indent=len(l)-len(s)
    if re.match(r"\s*try:\s*$", l):
        stack.append((i,indent))
    if re.match(r"\s*(except\b|finally\b)", l):
        if stack:
            stack.pop()
        else:
            print('Unmatched except/finally at',i)

if stack:
    print('Unclosed try blocks:')
    for i,ind in stack:
        print(i, 'indent', ind)
else:
    print('All try blocks matched (heuristic)')
