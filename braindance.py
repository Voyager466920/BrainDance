#!/usr/bin/env python3
"""BrainDance terminal, local service and offline checks."""
from pathlib import Path
import sys

SCRIPTS=Path(__file__).resolve().parent/'.claude/skills/aris-research-council/scripts'
sys.path.insert(0,str(SCRIPTS))

if __name__=='__main__':
    if sys.argv[1:]==['--test']:
        import unittest
        result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.discover(str(SCRIPTS),pattern='test_*.py'))
        raise SystemExit(0 if result.wasSuccessful() else 1)
    force_cli=sys.argv[1:2]==['cli']
    if force_cli:sys.argv.pop(1)
    if not force_cli and sys.argv[1:2]==['serve']:
        sys.argv.pop(1)
        from viewer import main
        main()
    elif not force_cli and '--db' in sys.argv and '--port' in sys.argv and all(arg in {'--db','--port','--max-depth'} or (i and sys.argv[i-1] in {'--db','--port','--max-depth'}) for i,arg in enumerate(sys.argv[1:],1)):
        # Preserve the original source-server invocation.
        from viewer import main
        main()
    else:
        from terminal import main
        raise SystemExit(main())
