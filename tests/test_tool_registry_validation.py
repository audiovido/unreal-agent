import unittest

from core.tool_registry import ToolSpec, validate_args


def sample_tool(required_value, timeout=120):
    return required_value, timeout


class ValidateArgsTests(unittest.TestCase):
    def setUp(self):
        self.spec = ToolSpec(
            name="sample_tool",
            description="Validation fixture",
            args={
                "required_value": "Required value",
                "timeout": "Optional timeout",
            },
            func=sample_tool,
        )

    def test_accepts_omitted_optional_argument(self):
        self.assertEqual(
            validate_args(self.spec, {"required_value": "ok"}),
            (True, ""),
        )

    def test_accepts_provided_optional_argument(self):
        self.assertEqual(
            validate_args(
                self.spec,
                {"required_value": "ok", "timeout": 5},
            ),
            (True, ""),
        )

    def test_rejects_missing_required_argument(self):
        valid, error = validate_args(self.spec, {})
        self.assertFalse(valid)
        self.assertIn("required_value", error)

    def test_rejects_unknown_argument(self):
        valid, error = validate_args(
            self.spec,
            {"required_value": "ok", "extra": True},
        )
        self.assertFalse(valid)
        self.assertIn("extra", error)


if __name__ == "__main__":
    unittest.main()
