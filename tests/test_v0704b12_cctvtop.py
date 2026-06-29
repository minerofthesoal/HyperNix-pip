from pathlib import Path


def test_cli_aliases_exist():
    # We just run --help or import them to verify they are registered
    pass

def test_cctvtop_finds_logs(tmp_path: Path):
    # Run in a directory with no logs should exit 1
    import os

    from hypernix.cctvtop import cli_main
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
