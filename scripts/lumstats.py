import struct, sys, zlib
def lum_stats(path):
    d=open(path,'rb').read()
    assert d[:8]==b'\x89PNG\r\n\x1a\n'
    pos=8; idat=b''; w=h=bitd=colort=0
    while pos<len(d):
        ln=struct.unpack('>I',d[pos:pos+4])[0]; typ=d[pos+4:pos+8]; data=d[pos+8:pos+8+ln]
        if typ==b'IHDR': w,h,bitd,colort,_,_,_=struct.unpack('>IIBBBBB',data)
        elif typ==b'IDAT': idat+=data
        elif typ==b'IEND': break
        pos+=12+ln
    raw=zlib.decompress(idat); chans={2:3,6:4}.get(colort, 3); bpp=chans*(bitd//8)
    stride=w*bpp
    out=bytearray(w*h)
    prev=bytearray(stride)
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
        # store luminance of first channel approx (good enough)
        for x in range(w): out[y*w+x]=line[x*bpp]
        prev=line
    lum=[v for v in out]
    import statistics
    mn=min(lum); mx=max(lum); mean=sum(lum)/len(lum)
    dark=sum(1 for v in lum if v<30)/len(lum); bright=sum(1 for v in lum if v>=200)/len(lum)
    print(f"size {w}x{h} chans={chans} min={mn} max={mx} mean={mean:.0f} dark%={dark*100:.1f} bright%={bright*100:.1f}")
lum_stats(sys.argv[1])
