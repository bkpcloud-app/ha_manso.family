"""Static regression tests for Home Assistant managed session ownership.

These checks deliberately do not contact Vestibulare or require a running HA.
"""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "vestibulare_elshaday"


class SessionLifecycle(unittest.TestCase):
    def test_managed_client_sessions_not_entered_or_closed_locally(self):
        for filename in ("__init__.py", "config_flow.py"):
            with self.subTest(filename=filename):
                tree = ast.parse((ROOT / filename).read_text())
                creators = [
                    node for node in ast.walk(tree)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "async_create_clientsession"
                ]
                self.assertTrue(creators, "Each module should create a private session")
                for node in creators:
                    self.assertFalse(any(
                        key.arg == "auto_cleanup" and isinstance(key.value, ast.Constant)
                        and key.value.value is False for key in node.keywords
                    ))
                for node in ast.walk(tree):
                    if isinstance(node, (ast.With, ast.AsyncWith)):
                        for item in node.items:
                            call = item.context_expr
                            self.assertFalse(isinstance(call, ast.Call)
                                and isinstance(call.func, ast.Name)
                                and call.func.id == "async_create_clientsession")
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                        self.assertFalse(node.func.attr in ("close", "detach") and
                            isinstance(node.func.value, ast.Name) and node.func.value.id == "session")
