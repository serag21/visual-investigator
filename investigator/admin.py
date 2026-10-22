"""Local operator controls; no browser or public administration service.

Use the host's existing secret environment. Never pass database credentials as
command arguments. Revocation is durable; stale invite configuration cannot undo it.
"""
import argparse
import os
from .storage import Database,ControlStore,StorageUnavailable


def main():
    p=argparse.ArgumentParser(description='Private-beta operator controls. Database URL comes only from environment.')
    p.add_argument('action',choices=['status','revoke','disable','enable','resume-provider'])
    p.add_argument('--member',default='')
    args=p.parse_args()
    target=os.environ.get('VI_DATABASE_URL') or os.environ.get('VI_STATE_PATH')
    if not target:p.error('Set the existing VI_DATABASE_URL or persistent VI_STATE_PATH in this private process environment.')
    try:
        store=ControlStore(Database(target))
        if args.action=='revoke':
            if not args.member:p.error('Choose a member ID with --member.')
            print('Revoked.' if store.revoke(args.member) else 'Member was not found.')
        elif args.action in ('enable','disable'):store.set_enabled(args.action=='enable');print('Access setting saved.')
        elif args.action=='resume-provider':store.resume_provider();print('Provider pause cleared; this does not make a model request.')
        else:
            import json
            print(json.dumps({'enabled':store.enabled(),'members':store.members()},indent=2))
    except StorageUnavailable:raise SystemExit('Durable storage is unavailable. No successful change is assumed.') from None


if __name__=='__main__':main()
