from pathlib import Path


def test_secret_scanner_reports_location_without_secret_value(tmp_path):
    from RxyCode.RxyCode1_1_0.scripts.scan_secrets import scan

    leaked = "sk-" + "A" * 32
    target = tmp_path / "config.yaml"
    target.write_text(f"api_key: {leaked}\n", encoding="utf-8")

    findings = scan(tmp_path)

    assert findings == [(Path("config.yaml"), 1, "provider-token")]
    assert all(leaked not in str(field) for finding in findings for field in finding)


def test_secret_scanner_checks_runtime_artifacts(tmp_path):
    from RxyCode.RxyCode1_1_0.scripts.scan_secrets import scan

    target = tmp_path / "artifacts" / "runtime-ci-layout-check" / "config.yaml"
    target.parent.mkdir(parents=True)
    target.write_text(
        "api_key: sk-" + "B" * 32 + "\n",
        encoding="utf-8",
    )

    assert scan(tmp_path) == [
        (Path("artifacts/runtime-ci-layout-check/config.yaml"), 1, "provider-token")
    ]


def test_secret_scanner_allows_environment_references_and_placeholders(tmp_path):
    from RxyCode.RxyCode1_1_0.scripts.scan_secrets import scan

    (tmp_path / "config.yaml").write_text(
        "api_key_env: PROVIDER_API_KEY\n"
        "api_key: ${PROVIDER_API_KEY}\n"
        "example: sk-your-key-here\n",
        encoding="utf-8",
    )

    assert scan(tmp_path) == []


def test_secret_scanner_checks_uploaded_report_formats_and_bearer_tokens(tmp_path):
    from RxyCode.RxyCode1_1_0.scripts.scan_secrets import scan

    (tmp_path / "junit.xml").write_text(
        '<property name="authorization" value="Bearer ' + "C" * 40 + '"/>\n',
        encoding="utf-8",
    )
    (tmp_path / "conpty.log").write_text(
        "request Authorization: Bearer " + "D" * 40 + "\n",
        encoding="utf-8",
    )

    assert scan(tmp_path) == [
        (Path("conpty.log"), 1, "bearer-token"),
        (Path("junit.xml"), 1, "bearer-token"),
    ]


def test_secret_scanner_streams_large_files_instead_of_skipping_them(tmp_path):
    from RxyCode.RxyCode1_1_0.scripts.scan_secrets import scan

    target = tmp_path / "large.log"
    target.write_text(
        "x" * 2_100_000 + "\napi_key: sk-" + "E" * 32 + "\n",
        encoding="utf-8",
    )

    assert scan(tmp_path) == [(Path("large.log"), 2, "provider-token")]


def test_secret_scanner_does_not_allow_real_keys_with_placeholder_comments(tmp_path):
    from RxyCode.RxyCode1_1_0.scripts.scan_secrets import scan

    (tmp_path / "config.yaml").write_text(
        "api_key: sk-" + "F" * 32 + "  # example\n"
        "api_key: sk-" + "G" * 32 + "  # secret-scan: allow\n"
        "password: " + "H" * 32 + "  # fake\n",
        encoding="utf-8",
    )

    assert scan(tmp_path) == [
        (Path("config.yaml"), 1, "provider-token"),
        (Path("config.yaml"), 2, "provider-token"),
        (Path("config.yaml"), 3, "credential-assignment"),
    ]
