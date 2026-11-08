import sys
from PIL import Image, ImageDraw
ts=sys.argv[2:]; out=sys.argv[1]
cols=2; w,h=960,540
rows=(len(ts)+1)//2
im=Image.new('RGB',(w*cols,h*rows))
for i,t in enumerate(ts):
    a=Image.open(f'data/fr/s{t}.png').resize((w,h)); im.paste(a,((i%cols)*w,(i//cols)*h)); ImageDraw.Draw(im).text(((i%cols)*w+8,(i//cols)*h+4),t,fill=(255,255,0))
im.save(out)
