use std::env;
use std::fs::OpenOptions;
use std::io::{ErrorKind, Read, Write};
use std::net::{Ipv4Addr, SocketAddrV4, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::thread;
use std::time::{Duration, Instant};

struct Arguments {
    port: u16,
    model: String,
    counter_file: PathBuf,
    exit_after: Option<Duration>,
    unhealthy: bool,
    ignore_termination: bool,
    ignored_descendant_pid_file: Option<PathBuf>,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let arguments = parse_arguments()?;
    configure_termination(arguments.ignore_termination)?;
    if let Some(path) = arguments.ignored_descendant_pid_file.as_ref() {
        spawn_ignored_descendant(path)?;
    }
    let mut counter = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&arguments.counter_file)?;
    writeln!(counter, "{}", std::process::id())?;
    counter.sync_all()?;

    let listener = TcpListener::bind(SocketAddrV4::new(Ipv4Addr::LOCALHOST, arguments.port))?;
    listener.set_nonblocking(true)?;
    let started_at = Instant::now();
    loop {
        if arguments
            .exit_after
            .is_some_and(|deadline| started_at.elapsed() >= deadline)
        {
            return Ok(());
        }
        match listener.accept() {
            Ok((mut stream, _peer)) => {
                let _ = respond(&mut stream, &arguments.model, arguments.unhealthy);
            }
            Err(error) if error.kind() == ErrorKind::WouldBlock => {
                thread::sleep(Duration::from_millis(5));
            }
            Err(error) => return Err(error.into()),
        }
    }
}

fn respond(
    stream: &mut TcpStream,
    model: &str,
    unhealthy: bool,
) -> Result<(), Box<dyn std::error::Error>> {
    stream.set_read_timeout(Some(Duration::from_secs(1)))?;
    stream.set_write_timeout(Some(Duration::from_secs(1)))?;
    let mut request = [0_u8; 2048];
    let count = stream.read(&mut request)?;
    let request = std::str::from_utf8(&request[..count])?;
    let target = request
        .lines()
        .next()
        .and_then(|line| line.split_whitespace().nth(1))
        .unwrap_or("");
    let (status, body) = match target {
        "/health" if unhealthy => ("503 Service Unavailable", "{}".to_owned()),
        "/health" => ("200 OK", "{}".to_owned()),
        "/v1/models" => (
            "200 OK",
            serde_json::json!({"data": [{"id": model}]}).to_string(),
        ),
        _ => ("404 Not Found", "{}".to_owned()),
    };
    write!(
        stream,
        "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    )?;
    stream.flush()?;
    Ok(())
}

fn parse_arguments() -> Result<Arguments, Box<dyn std::error::Error>> {
    let mut values = env::args_os().skip(1);
    let mut port = None;
    let mut model = None;
    let mut counter_file = None;
    let mut exit_after = None;
    let mut unhealthy = false;
    let mut ignore_termination = false;
    let mut ignored_descendant_pid_file = None;
    while let Some(flag) = values.next() {
        match flag.to_str() {
            Some("--port") => {
                port = Some(
                    values
                        .next()
                        .and_then(|value| value.to_str().and_then(|text| text.parse().ok()))
                        .ok_or("fixture port is invalid")?,
                );
            }
            Some("--model") => {
                model = Some(
                    values
                        .next()
                        .and_then(|value| value.into_string().ok())
                        .ok_or("fixture model is invalid")?,
                );
            }
            Some("--counter-file") => {
                counter_file = Some(
                    values
                        .next()
                        .map(PathBuf::from)
                        .ok_or("fixture counter path is missing")?,
                );
            }
            Some("--exit-after-ready-ms") => {
                let milliseconds = values
                    .next()
                    .and_then(|value| value.to_str().and_then(|text| text.parse().ok()))
                    .ok_or("fixture exit deadline is invalid")?;
                exit_after = Some(Duration::from_millis(milliseconds));
            }
            Some("--unhealthy") => unhealthy = true,
            Some("--ignore-termination") => ignore_termination = true,
            Some("--ignored-descendant-pid-file") => {
                ignored_descendant_pid_file = Some(
                    values
                        .next()
                        .map(PathBuf::from)
                        .ok_or("fixture descendant PID path is missing")?,
                );
            }
            _ => return Err("fixture argument is invalid".into()),
        }
    }
    Ok(Arguments {
        port: port.ok_or("fixture port is required")?,
        model: model.ok_or("fixture model is required")?,
        counter_file: counter_file.ok_or("fixture counter path is required")?,
        exit_after,
        unhealthy,
        ignore_termination,
        ignored_descendant_pid_file,
    })
}

#[cfg(unix)]
fn spawn_ignored_descendant(path: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let process_id = unsafe { libc::fork() };
    if process_id < 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    if process_id == 0 {
        unsafe {
            libc::signal(libc::SIGTERM, libc::SIG_IGN);
            libc::signal(libc::SIGHUP, libc::SIG_IGN);
            libc::signal(libc::SIGINT, libc::SIG_IGN);
            loop {
                libc::pause();
            }
        }
    }
    std::fs::write(path, format!("{process_id}\n"))?;
    Ok(())
}

#[cfg(not(unix))]
fn spawn_ignored_descendant(_path: &Path) -> Result<(), Box<dyn std::error::Error>> {
    Err("ignored descendant fixture requires Unix".into())
}

#[cfg(unix)]
fn configure_termination(ignore_termination: bool) -> Result<(), Box<dyn std::error::Error>> {
    if ignore_termination {
        let previous = unsafe { libc::signal(libc::SIGTERM, libc::SIG_IGN) };
        if previous == libc::SIG_ERR {
            return Err(std::io::Error::last_os_error().into());
        }
    }
    Ok(())
}

#[cfg(not(unix))]
fn configure_termination(_ignore_termination: bool) -> Result<(), Box<dyn std::error::Error>> {
    Ok(())
}
