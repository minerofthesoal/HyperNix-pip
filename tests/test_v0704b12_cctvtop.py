import subprocess
import sys
from pathlib import Path

def test_cli_aliases_exist():
    # We just run --help or import them to verify they are registered
    import hypernix.cctvtop
    import hypernix.tv
    import hypernix.tvtop_plus_plus

def test_cctvtop_finds_logs(tmp_path: Path):
    from hypernix.cctvtop import cli_main
    
    # Run in a directory with no logs should exit 1
    import os
    orig_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        try:
            cli_main()
            assert False, "Should have exited"
        except SystemExit as e:
            assert e.code == 1
    finally:
        os.chdir(orig_cwd)
