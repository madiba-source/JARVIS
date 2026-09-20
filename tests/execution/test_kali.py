from app.execution.kali import KaliToolRegistry


def test_kali_registry_only_reports_available_executables(monkeypatch) -> None:
    monkeypatch.setattr("app.execution.kali.shutil.which", lambda name: "/usr/bin/" + name if name == "nmap" else None)
    result = KaliToolRegistry(cache_ttl_seconds=60).discover()

    assert result["code"] == "success"
    assert result["data"]["count"] == 1
    assert result["data"]["capabilities"][0]["category"] == "information_gathering"


def test_kali_registry_refreshes_explicitly(monkeypatch) -> None:
    paths = {"nmap": "/usr/bin/nmap"}
    monkeypatch.setattr("app.execution.kali.shutil.which", lambda name: paths.get(name))
    registry = KaliToolRegistry(cache_ttl_seconds=60)
    assert registry.discover()["data"]["count"] == 1
    paths["sqlmap"] = "/usr/bin/sqlmap"
    assert registry.discover()["data"]["count"] == 1
    assert registry.discover(refresh=True)["data"]["count"] == 2