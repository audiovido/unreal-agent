import sys, struct, zlib
def decode(path):
    d=open(path,'rb').read()
    pos=8; idat=b''; w=h=colort=0
    while pos<len(d):
        ln=struct.unpack('>I',d[pos:pos+4])[0]; typ=d[pos+4:pos+8]; data=d[pos+8:pos+8+ln]
        if typ==b'IHDR': w,h,_,colort,_,_,_=struct.unpack('>IIBBBBB',data)
        elif typ==b'IDAT': idat+=data
        elif typ==b'IEND': break
        pos+=12+ln
    raw=zlib.decompress(idat); chans={2:3,6:4}.get(colort,3); bpp=chans
    stride=w*bpp; out=bytearray(w*h*3); prev=bytearray(stride)
    for y in range(h):
        ft=raw[y*(stride+1)]; line=bytearray(raw[y*(stride+1)+1:(y+1)*(stride+1)])
        for x in range(stride):
            a=line[x-bpp] if x>=bpp else 0; b=prev[x]; c=prev[x-bpp] if x>=bpp else 0
            if ft==1: line[x]=(line[x]+a)&255
            elif ft==2: line[x]=(line[x]+b)&255
            elif ft==3: line[x]=(line[x]+(a+b)//2)&255
            elif ft==4:
                p=a+b-c; pa,pb,pc=abs(p-a),abs(p-b),abs(p-c)
                pr=a if (pa<=pb and pa<=pc) else (b if pb<=pc else c)
                line[x]=(line[x]+pr)&255
        for x in range(w):
            for c in range(3): out[(y*w+x)*3+c]=line[x*bpp+c]
        prev=line
    return w,h,out
def region_mean(w,h,pix,x0,y0,x1,y1):
    tot=n=0
    for y in range(int(y0),int(y1)):
        for x in range(int(x0),int(x1)):
            i=(y*w+x)*3
            tot+=(pix[i]+pix[i+1]+pix[i+2])/3; n+=1
    return round(tot/n,1) if n else 0
w,h,pix=decode(sys.argv[1])
W,H=w,h
print(f"{w}x{h}")
for label,(x0,y0,x1,y1) in {
    "top-left":(0,0,W*0.5,H*0.5),"top-right":(W*0.5,0,W,H*0.5),
    "mid-left":(0,H*0.35,W*0.5,H*0.7),"mid-right":(W*0.5,H*0.35,W,H*0.7),
    "bottom-left":(0,H*0.6,W*0.5,H),"bottom-right":(W*0.5,H*0.6,W,H),
    "right-edge":(W*0.68,0,W,H),
}.items():
    print(label, region_mean(w,h,pix,x0,y0,x1,y1))
