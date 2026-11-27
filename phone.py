"""Stage-one touch check against the running local dashboard."""
import argparse
import json
import os
from urllib.parse import quote
from urllib.request import Request, urlopen

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['list','next','previous'])
    parser.add_argument('--phone',help='Device ID printed by list')
    args=parser.parse_args()
    base='http://127.0.0.1:'+os.getenv('PORT','8766')
    with urlopen(base+'/api/phones',timeout=5) as response:
        phones=json.load(response)['phones']
    if args.action=='list':
        for p in phones:
            print(p['id'],p['name'],'live' if p['live'] else 'offline')
        return
    eligible=[p for p in phones if p['live'] and (p['id']==args.phone if args.phone else not p['demo'])]
    if len(eligible)!=1:
        parser.error('Select one live phone with --phone ID.')
    p=eligible[0]
    y1,y2=(.75,.30) if args.action=='next' else (.30,.75)
    body=json.dumps({'action':'drag','points':[.5,y1,.5,y2],'duration':.3}).encode()
    url=base+'/api/'+quote(p['id'],safe='')+'/touch?session='+p['session']
    req=Request(url,data=body,headers={'Content-Type':'application/json','Origin':base})
    with urlopen(req,timeout=20) as response:
        print(response.read().decode())

if __name__=='__main__':
    main()
