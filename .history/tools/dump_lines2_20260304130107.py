lines=open('app.py','r',encoding='utf-8').read().splitlines()
for i in range(132,172):
    print(f"{i+1:04d}: {repr(lines[i])}")
