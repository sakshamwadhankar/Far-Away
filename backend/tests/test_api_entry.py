"""Regression test for the PyInstaller entry point (komvos_api_entry.py).

The packaged backend binary executes only this module, so an import error
here would not be caught by any route-level test.
"""


def test_api_entry_module_imports_and_exposes_app():
    import komvos_api_entry

    assert komvos_api_entry.app is not None
