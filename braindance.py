#!/usr/bin/env python3
"""Source launcher for the local BrainDance viewer and its offline checks."""
from pathlib import Path
import sys

SCRIPTS=Path(__file__).resolve().parent/'.claude/skills/aris-research-council/scripts'
sys.path.insert(0,str(SCRIPTS))

if __name__=='__main__':
    if sys.argv[1:]==['--test']:
        import unittest
        result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.discover(str(SCRIPTS),pattern='test_*.py'))
        raise SystemExit(0 if result.wasSuccessful() else 1)
    from viewer import main
    main()
