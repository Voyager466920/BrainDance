#!/usr/bin/env python3
"""Generate original chamfered, oblique terminal lettering. No font/runtime dependency."""
from math import ceil
from pathlib import Path

ASSETS=Path(__file__).resolve().parents[1]/'.claude/skills/aris-research-council/assets'
QUADRANTS=' ▘▝▀▖▌▞▛▗▚▐▜▄▙▟▉'
# All letters share a 12-unit cap height and 3-unit strokes. Corners are
# deliberately cut, rather than rounded or expanded from a tiny bitmap font.
GLYPHS={
 'B':([[(0,0),(7,0),(9,2),(9,5),(8,6),(9,7),(9,10),(7,12),(0,12)]],
      [[(3,3),(6,3),(6,5),(3,5)],[(3,7),(6,7),(6,9),(3,9)]]),
 'R':([[(0,0),(7,0),(9,2),(9,5),(7,7),(9,12),(6,12),(4,7),(3,7),(3,12),(0,12)]],
      [[(3,3),(6,3),(6,5),(3,5)]]),
 'A':([[(2,0),(7,0),(9,2),(9,12),(6,12),(6,8),(3,8),(3,12),(0,12),(0,2)]],
      [[(3,3),(6,3),(6,5),(3,5)]]),
 'I':([[(0,0),(3,0),(3,12),(0,12)]],[]),
 'N':([[(0,0),(3,0),(6,7),(6,0),(9,0),(9,12),(6,12),(3,5),(3,12),(0,12)]],[]),
 'D':([[(0,0),(6,0),(9,3),(9,9),(6,12),(0,12)]],
      [[(3,3),(5,3),(6,4),(6,8),(5,9),(3,9)]]),
 'C':([[(2,0),(9,0),(9,3),(3,3),(3,9),(9,9),(9,12),(2,12),(0,10),(0,2)]],[]),
 'E':([[(0,0),(9,0),(9,3),(3,3),(3,5),(8,5),(8,7),(3,7),(3,9),(9,9),(9,12),(0,12)]],[]),
}


def inside(x,y,polygon):
    hit=False
    for (ax,ay),(bx,by) in zip(polygon,polygon[1:]+polygon[:1]):
        if (ay>y)!=(by>y) and x<(bx-ax)*(y-ay)/(by-ay)+ax:hit=not hit
    return hit


def lettering(word,scale):
    shapes=[];offset=0
    for letter in word:
        if letter==' ':offset+=3;continue
        shapes.append((offset,*GLYPHS[letter]));offset+=(3 if letter=='I' else 9)+1.5
    columns=ceil((offset+1.5)*scale)
    def filled(px,py):
        y=py
        x=px/(2*scale)-(12-y)/4
        return any(any(inside(x-left,y,p) for p in outer) and not any(inside(x-left,y,p) for p in holes) for left,outer,holes in shapes)
    rows=[]
    for y in range(0,12,2):
        row=''
        for x in range(columns):
            bits=sum(1<<(dy*2+dx) for dy in range(2) for dx in range(2) if filled(2*x+dx+.5,y+dy+.5))
            row+=QUADRANTS[bits]
        rows.append(row.rstrip())
    return rows


def main():
    for name,words,scale in [('wide',['BRAIN DANCE'],1.2),('regular',['BRAIN','DANCE'],1.35),('small',['BRAIN','DANCE'],.65)]:
        blocks=[lettering(word,scale) for word in words]
        width=max(len(row) for block in blocks for row in block)
        lines=[]
        for block in blocks:
            block_width=max(map(len,block));padding=' '*((width-block_width)//2)
            if lines:lines.append('')
            lines.extend(padding+row for row in block)
        text='\n'.join(lines)+'\n'
        (ASSETS/('terminal-logo-'+name+'.txt')).write_text(text,encoding='utf-8')
        print(name,width,'columns\n'+text)


if __name__=='__main__':main()
