def test_policy_package_imports() -> None:
    import app.policy
    from app.policy.evaluator import ExecutionPermit

    assert ExecutionPermit is not None
