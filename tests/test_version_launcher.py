"""Tests for the multi-version Python launcher."""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

# Import the launcher module
from hypernix.version_launcher import (
    VERSION_PRIORITY,
    PythonVersion,
    check_hypernix_installed,
    find_best_python,
    main,
)


class TestPythonVersion:
    """Tests for the PythonVersion named tuple."""

    def test_version_creation(self):
        """Test creating a PythonVersion instance."""
        pv = PythonVersion(3, 12)
        assert pv.major == 3
        assert pv.minor == 12
        assert pv.version_tuple == (3, 12)

    def test_exe_name_format(self):
        """Test that exe_name returns correct format."""
        pv = PythonVersion(3, 12)
        assert pv.exe_name == "python3.12"
        
        pv = PythonVersion(3, 13)
        assert pv.exe_name == "python3.13"
        
        pv = PythonVersion(3, 14)
        assert pv.exe_name == "python3.14"

    def test_version_priority_order(self):
        """Test that VERSION_PRIORITY is in correct order."""
        assert len(VERSION_PRIORITY) == 3
        assert VERSION_PRIORITY[0].version_tuple == (3, 12)
        assert VERSION_PRIORITY[1].version_tuple == (3, 13)
        assert VERSION_PRIORITY[2].version_tuple == (3, 14)


class TestCheckHypernixInstalled:
    """Tests for check_hypernix_installed function."""

    @patch("hypernix.version_launcher.subprocess.run")
    def test_returns_true_when_installed(self, mock_run):
        """Test that function returns True when hypernix is installed."""
        mock_run.return_value = MagicMock(returncode=0, stdout="1.0.0", stderr="")
        
        result = check_hypernix_installed("python3.12")
        
        assert result is True
        mock_run.assert_called_once_with(
            ["python3.12", "-c", "import hypernix; print(hypernix.__version__)"],
            capture_output=True,
            text=True,
            timeout=5,
        )

    @patch("hypernix.version_launcher.subprocess.run")
    def test_returns_false_when_not_installed(self, mock_run):
        """Test that function returns False when hypernix is not installed."""
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="ModuleNotFoundError")
        
        result = check_hypernix_installed("python3.12")
        
        assert result is False

    @patch("hypernix.version_launcher.subprocess.run")
    def test_returns_false_on_timeout(self, mock_run):
        """Test that function returns False on timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="python3.12", timeout=5)
        
        result = check_hypernix_installed("python3.12")
        
        assert result is False

    @patch("hypernix.version_launcher.subprocess.run")
    def test_returns_false_on_file_not_found(self, mock_run):
        """Test that function returns False when executable not found."""
        mock_run.side_effect = FileNotFoundError("python3.12")
        
        result = check_hypernix_installed("python3.12")
        
        assert result is False

    @patch("hypernix.version_launcher.subprocess.run")
    def test_returns_false_on_os_error(self, mock_run):
        """Test that function returns False on OS error."""
        mock_run.side_effect = OSError("Permission denied")
        
        result = check_hypernix_installed("python3.12")
        
        assert result is False


class TestFindBestPython:
    """Tests for find_best_python function."""

    @patch("hypernix.version_launcher.check_hypernix_installed")
    def test_prefers_3_12_when_available(self, mock_check):
        """Test that 3.12 is preferred when hypernix is installed there."""
        # Mock: 3.12 has hypernix, others don't matter
        mock_check.side_effect = lambda x: x == "python3.12"
        
        result = find_best_python()
        
        assert result == "python3.12"
        # Should check 3.12 first and return immediately
        mock_check.assert_called_with("python3.12")

    @patch("hypernix.version_launcher.check_hypernix_installed")
    def test_falls_back_to_3_13_if_3_12_missing(self, mock_check):
        """Test fallback to 3.13 when 3.12 doesn't have hypernix."""
        # Mock: 3.12 doesn't have it, 3.13 does
        def side_effect(exe):
            if exe == "python3.12":
                return False
            elif exe == "python3.13":
                return True
            return False
        
        mock_check.side_effect = side_effect
        
        result = find_best_python()
        
        assert result == "python3.13"

    @patch("hypernix.version_launcher.check_hypernix_installed")
    def test_falls_back_to_3_14_if_3_12_and_3_13_missing(self, mock_check):
        """Test fallback to 3.14 when 3.12 and 3.13 don't have hypernix."""
        # Mock: only 3.14 has hypernix
        def side_effect(exe):
            return exe == "python3.14"
        
        mock_check.side_effect = side_effect
        
        result = find_best_python()
        
        assert result == "python3.14"

    @patch("hypernix.version_launcher.check_hypernix_installed")
    @patch("hypernix.version_launcher.sys.executable", "/usr/bin/python3")
    def test_falls_back_to_current_python_if_none_have_hypernix(self, mock_check):
        """Test fallback to current Python if no versioned Python has hypernix."""
        # Mock: no versioned Python has hypernix
        mock_check.return_value = False
        
        # Mock import of hypernix in current Python
        with patch.dict("sys.modules", {"hypernix": MagicMock()}):
            result = find_best_python()
            
            assert result == "/usr/bin/python3"

    @patch("hypernix.version_launcher.check_hypernix_installed")
    def test_returns_none_if_no_python_has_hypernix_and_current_doesnt_either(
        self, mock_check
    ):
        """Test returns None if no Python version has hypernix installed."""
        # Mock: no versioned Python has hypernix
        mock_check.return_value = False
        
        # Mock: current Python also doesn't have hypernix by patching the import
        with patch("hypernix.version_launcher.sys.modules", {}):
            with patch("builtins.__import__", side_effect=ImportError("No module named 'hypernix'")):
                result = find_best_python()
                
                assert result is None

    @patch("hypernix.version_launcher.sys.platform", "win32")
    @patch("hypernix.version_launcher.check_hypernix_installed")
    def test_checks_windows_format_on_windows(self, mock_check):
        """Test that Windows-specific executable names are checked."""
        # Mock: python3.12 fails, but python312 (Windows format) succeeds
        def side_effect(exe):
            if exe == "python312":
                return True
            return False
        
        mock_check.side_effect = side_effect
        
        result = find_best_python()
        
        assert result == "python312"
        # Should have checked both python3.12 and python312
        assert mock_check.call_count >= 2


class TestMainLauncher:
    """Tests for the main launcher entry point."""

    def test_skips_version_check_when_env_var_set(self, monkeypatch):
        """Test that version check is skipped when HYPERNIX_NO_VERSION_CHECK is set."""
        # Set the environment variable
        monkeypatch.setenv("HYPERNIX_NO_VERSION_CHECK", "1")
        
        with patch("hypernix.cli.main", return_value=0) as mock_cli_main:
            result = main([])
            
            assert result == 0
            mock_cli_main.assert_called_once_with([])

    @patch("hypernix.cli.main", return_value=0)
    def test_uses_current_python_when_running_as_module(self, mock_cli_main):
        """Test that current Python is used when running as __main__.py."""
        with patch("hypernix.version_launcher.sys.argv", ["hypernix/__main__.py"]):
            result = main([])
        
        assert result == 0
        mock_cli_main.assert_called_once_with([])

    @patch("hypernix.version_launcher.run_with_selected_python", return_value=0)
    def test_uses_version_selection_for_console_scripts(self, mock_run_selected):
        """Test that version selection is used for console script entry points."""
        with patch("hypernix.version_launcher.sys.argv", ["hypernix"]):
            result = main([])
        
        assert result == 0
        mock_run_selected.assert_called_once_with([])

    @patch("hypernix.version_launcher.subprocess.run")
    @patch("hypernix.version_launcher.find_best_python")
    def test_re_invokes_with_selected_python(self, mock_find_best, mock_subprocess_run):
        """Test that launcher re-invokes with selected Python version."""
        mock_find_best.return_value = "python3.12"
        mock_subprocess_run.return_value = MagicMock(returncode=0)
        
        from hypernix.version_launcher import run_with_selected_python
        
        result = run_with_selected_python(["--version"])
        
        assert result == 0
        mock_subprocess_run.assert_called_once_with(
            ["python3.12", "-m", "hypernix", "--version"],
            check=False,
        )

    @patch("hypernix.version_launcher.find_best_python")
    def test_falls_back_to_current_when_selected_not_found(
        self, mock_find_best
    ):
        """Test fallback to current Python when selected executable not found."""
        mock_find_best.return_value = "python3.12"
        
        with patch("hypernix.version_launcher.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("python3.12")
            
            with patch("hypernix.cli.main", return_value=0) as mock_cli_main:
                from hypernix.version_launcher import run_with_selected_python
                
                result = run_with_selected_python(["--version"])
                
                assert result == 0
                mock_cli_main.assert_called_once_with(["--version"])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
