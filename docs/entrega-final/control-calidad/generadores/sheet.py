import sys,glob
from PIL import Image
files=sorted(glob.glob(sys.argv[1]+"/p*.png")); per=int(sys.argv[3]) if len(sys.argv)>3 else 8
for k in range(0,len(files),per):
    ims=[Image.open(f) for f in files[k:k+per]]; w,h=ims[0].size; cols=4; rows=(len(ims)+cols-1)//cols
    sh=Image.new("RGB",(w*cols,h*rows),"white")
    for i,im in enumerate(ims): sh.paste(im,((i%cols)*w,(i//cols)*h))
    sh.save(f"{sys.argv[2]}_{k//per+1:02d}.png")
