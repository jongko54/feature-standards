use std::process::Command;

fn executable() -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_feature-standards-core-consumer-rust"));
    for (key, _) in std::env::vars_os() {
        if key.to_string_lossy().starts_with("AUTH_") || key == "PORT" {
            command.env_remove(key);
        }
    }
    command
}

#[test]
fn fixture_executable_requires_explicit_demo_mode() {
    let output = executable().output().unwrap();
    assert!(!output.status.success());
    assert!(output.stdout.is_empty());
    assert!(String::from_utf8_lossy(&output.stderr).contains("requires explicit AUTH_DEMO=true"));
}

#[test]
fn fixture_executable_rejects_invalid_port_before_starting() {
    for port in ["0", "-1", "65536", "not-a-port"] {
        let output = executable()
            .env("AUTH_DEMO", "true")
            .env("AUTH_COOKIE_SECURE", "false")
            .env("PORT", port)
            .output()
            .unwrap();
        assert!(!output.status.success());
        assert!(output.stdout.is_empty());
        assert!(
            String::from_utf8_lossy(&output.stderr).contains("PORT must be between 1 and 65535")
        );
    }
}
