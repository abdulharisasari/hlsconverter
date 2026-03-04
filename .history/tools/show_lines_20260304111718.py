import sys
lines=open('app.py','r',encoding='utf-8').read().splitlines()
start= int(sys.argv[1]) if len(sys.argv)>1 else 1
end= int(sys.argv[2]) if len(sys.argv)>2 else start+40
for i in range(start-1,end):
    print(f"{i+1:04d}: {lines[i]}")
