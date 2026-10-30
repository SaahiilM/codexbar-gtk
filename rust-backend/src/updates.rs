//! Read-only client update check. This service only reads the public VERSION
//! marker; it never downloads or installs executable content.

use std::{cmp::Ordering, fmt, future::Future, time::Duration};

pub const VERSION_URL: &str =
    "https://raw.githubusercontent.com/SaahiilM/codexbar-gtk/main/VERSION";
pub const MAX_BYTES: usize = 4096;
pub const MAX_TIMEOUT: Duration = Duration::from_secs(300);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum UpdateError {
    InvalidMarker,
    Oversized,
    Network,
    Timeout,
}

impl fmt::Display for UpdateError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::InvalidMarker => "the public version marker is invalid",
            Self::Oversized => "the public version marker exceeds 4096 bytes",
            Self::Network => "the public version check failed",
            Self::Timeout => "the public version check timed out",
        })
    }
}

impl std::error::Error for UpdateError {}

/// Version components are strings so comparison does not overflow for a
/// syntactically valid release marker with very large numeric components.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Version {
    pub marketing: String,
    pub build: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum UpdateRelation {
    Available,
    Current,
    Ahead,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UpdateCheckRequest {
    pub current: Version,
    pub version_url: String,
    pub timeout: Duration,
}

impl UpdateCheckRequest {
    pub fn new(current: Version, version_url: impl Into<String>, timeout: Duration) -> Self {
        Self {
            current,
            version_url: version_url.into(),
            timeout,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UpdateCheck {
    pub current: Version,
    pub latest: Version,
    pub relation: UpdateRelation,
}

// Unicode 15.0 Nd block starts. Python int() accepts Unicode decimal digits,
// including Arabic-Indic and fullwidth forms; keep that behavior without
// applying compatibility normalization to superscripts or circled digits.
const DECIMAL_ZEROES: &[u32] = &[
    0x0030, 0x0660, 0x06F0, 0x07C0, 0x0966, 0x09E6, 0x0A66, 0x0AE6, 0x0B66, 0x0BE6, 0x0C66, 0x0CE6,
    0x0D66, 0x0DE6, 0x0E50, 0x0ED0, 0x0F20, 0x1040, 0x1090, 0x17E0, 0x1810, 0x1946, 0x19D0, 0x1A80,
    0x1A90, 0x1B50, 0x1BB0, 0x1C40, 0x1C50, 0xA620, 0xA8D0, 0xA900, 0xA9D0, 0xA9F0, 0xAA50, 0xABF0,
    0xFF10, 0x104A0, 0x10D30, 0x11066, 0x110F0, 0x11136, 0x111D0, 0x112F0, 0x11450, 0x114D0,
    0x11650, 0x116C0, 0x11730, 0x118E0, 0x11950, 0x11C50, 0x11D50, 0x11DA0, 0x11F50, 0x16A60,
    0x16AC0, 0x16B50, 0x1D7CE, 0x1E140, 0x1E2F0, 0x1E4F0, 0x1E950, 0x1FBF0,
];

fn decimal_digit(ch: char) -> Option<u8> {
    let cp = ch as u32;
    DECIMAL_ZEROES.iter().find_map(|zero| {
        let offset = cp.checked_sub(*zero)?;
        (offset < 10).then_some(offset as u8)
    })
}

fn decimal_value(text: &str) -> Result<Vec<u8>, UpdateError> {
    if text.is_empty() {
        return Err(UpdateError::InvalidMarker);
    }
    text.chars()
        .map(|ch| decimal_digit(ch).ok_or(UpdateError::InvalidMarker))
        .collect()
}

fn compare_digits(left: &[u8], right: &[u8]) -> Ordering {
    let left = left
        .iter()
        .skip_while(|digit| **digit == 0)
        .copied()
        .collect::<Vec<_>>();
    let right = right
        .iter()
        .skip_while(|digit| **digit == 0)
        .copied()
        .collect::<Vec<_>>();
    left.len().cmp(&right.len()).then_with(|| left.cmp(&right))
}

impl Version {
    pub fn new(
        marketing: impl Into<String>,
        build: impl Into<String>,
    ) -> Result<Self, UpdateError> {
        let version = Self {
            marketing: marketing.into(),
            build: build.into(),
        };
        version.numeric_parts()?;
        decimal_value(&version.build)?;
        Ok(version)
    }

    fn numeric_parts(&self) -> Result<Vec<Vec<u8>>, UpdateError> {
        let parts = self
            .marketing
            .split('.')
            .map(decimal_value)
            .collect::<Result<Vec<_>, _>>()?;
        if parts.is_empty() {
            return Err(UpdateError::InvalidMarker);
        }
        Ok(parts)
    }

    pub fn compare(&self, other: &Self) -> Result<Ordering, UpdateError> {
        let left = self.numeric_parts()?;
        let right = other.numeric_parts()?;
        let marketing = left
            .iter()
            .zip(&right)
            .map(|(a, b)| compare_digits(a, b))
            .find(|order| *order != Ordering::Equal)
            .unwrap_or_else(|| left.len().cmp(&right.len()));
        Ok(marketing.then_with(|| {
            // Construction validates both build values, so these parses cannot fail.
            compare_digits(
                &decimal_value(&self.build).expect("validated build"),
                &decimal_value(&other.build).expect("validated build"),
            )
        }))
    }
}

pub fn parse(contents: &[u8]) -> Result<Version, UpdateError> {
    if contents.len() > MAX_BYTES {
        return Err(UpdateError::Oversized);
    }
    let text = std::str::from_utf8(contents).map_err(|_| UpdateError::InvalidMarker)?;
    let (mut marketing, mut build) = (None, None);
    for line in text.lines() {
        if let Some((key, value)) = line.split_once('=') {
            match key.trim() {
                "MARKETING_VERSION" => marketing = Some(value.trim()),
                "CURRENT_PROJECT_VERSION" => build = Some(value.trim()),
                _ => (),
            }
        }
    }
    Version::new(
        marketing.ok_or(UpdateError::InvalidMarker)?,
        build.ok_or(UpdateError::InvalidMarker)?,
    )
}

pub fn relation(current: &Version, latest: &Version) -> Result<UpdateRelation, UpdateError> {
    Ok(match latest.compare(current)? {
        Ordering::Greater => UpdateRelation::Available,
        Ordering::Equal => UpdateRelation::Current,
        Ordering::Less => UpdateRelation::Ahead,
    })
}

/// The closure is the service seam used by deterministic callers and tests.
pub async fn check_with<F, Fut>(
    request: UpdateCheckRequest,
    fetcher: F,
) -> Result<UpdateCheck, UpdateError>
where
    F: FnOnce() -> Fut,
    Fut: Future<Output = Result<Version, UpdateError>>,
{
    let latest = fetcher().await?;
    let relation = relation(&request.current, &latest)?;
    Ok(UpdateCheck {
        current: request.current,
        latest,
        relation,
    })
}

/// Production operation; deterministic callers can inject a fetcher through
/// `check_with` without changing comparison or error policy.
pub async fn check(request: UpdateCheckRequest) -> Result<UpdateCheck, UpdateError> {
    let UpdateCheckRequest {
        current,
        version_url,
        timeout,
    } = request;
    check_with(
        UpdateCheckRequest {
            current,
            version_url: version_url.clone(),
            timeout,
        },
        move || async move { fetch(&version_url, timeout).await },
    )
    .await
}

/// Fetch the public text marker with a total timeout and bounded body read.
pub async fn fetch(url: &str, timeout: Duration) -> Result<Version, UpdateError> {
    if timeout.is_zero() {
        return Err(UpdateError::Timeout);
    }
    let client = reqwest::Client::builder()
        .timeout(timeout.min(MAX_TIMEOUT))
        .redirect(reqwest::redirect::Policy::limited(3))
        .build()
        .map_err(|_| UpdateError::Network)?;
    let mut response = client
        .get(url)
        .header("User-Agent", "CodexBar-GTK-update-check")
        .header("Accept", "text/plain")
        .send()
        .await
        .map_err(|error| {
            if error.is_timeout() {
                UpdateError::Timeout
            } else {
                UpdateError::Network
            }
        })?
        .error_for_status()
        .map_err(|error| {
            if error.is_timeout() {
                UpdateError::Timeout
            } else {
                UpdateError::Network
            }
        })?;
    if response
        .content_length()
        .is_some_and(|size| size > MAX_BYTES as u64)
    {
        return Err(UpdateError::Oversized);
    }
    let mut body = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(|error| {
        if error.is_timeout() {
            UpdateError::Timeout
        } else {
            UpdateError::Network
        }
    })? {
        if chunk.len() > MAX_BYTES - body.len() {
            return Err(UpdateError::Oversized);
        }
        body.extend_from_slice(&chunk);
    }
    parse(&body)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::{
        io::{AsyncReadExt, AsyncWriteExt},
        net::TcpListener,
    };

    fn version(marketing: &str, build: &str) -> Version {
        Version::new(marketing, build).expect("fixture version is valid")
    }

    async fn fixture(response: Vec<u8>) -> String {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();
            let mut request = [0_u8; 1024];
            let _ = stream.read(&mut request).await;
            stream.write_all(&response).await.unwrap();
        });
        format!("http://{address}/VERSION")
    }

    #[test]
    fn parses_and_compares_unicode_decimal_digits_without_overflow() {
        let arabic =
            parse("MARKETING_VERSION=٠.٨٢.٠\nCURRENT_PROJECT_VERSION=٤\n".as_bytes()).unwrap();
        let fullwidth =
            parse("MARKETING_VERSION=０.８２.０\nCURRENT_PROJECT_VERSION=４\n".as_bytes()).unwrap();
        assert_eq!(arabic.compare(&fullwidth), Ok(Ordering::Equal));
        assert_eq!(
            version("0.100000000000000000000000000000", "8")
                .compare(&version("0.9", "999999999999999999999999999")),
            Ok(Ordering::Greater)
        );
        assert_eq!(Version::new("0.⁸².0", "4"), Err(UpdateError::InvalidMarker));
        assert_eq!(Version::new("0.82.0", "⁴"), Err(UpdateError::InvalidMarker));
    }

    #[test]
    fn rejects_bad_utf8_invalid_numbers_and_oversized_marker() {
        let mut at_limit = b"MARKETING_VERSION=1\nCURRENT_PROJECT_VERSION=1\n".to_vec();
        at_limit.resize(MAX_BYTES, b'#');
        assert!(parse(&at_limit).is_ok());
        assert_eq!(parse(&[0xff]), Err(UpdateError::InvalidMarker));
        assert_eq!(
            parse(b"MARKETING_VERSION=1.x\nCURRENT_PROJECT_VERSION=1"),
            Err(UpdateError::InvalidMarker)
        );
        assert_eq!(
            parse(&vec![b'x'; MAX_BYTES + 1]),
            Err(UpdateError::Oversized)
        );
        assert_eq!(
            parse("MARKETING_VERSION=1\nCURRENT_PROJECT_VERSION=⁴".as_bytes()),
            Err(UpdateError::InvalidMarker)
        );
    }

    #[tokio::test]
    async fn typed_check_uses_injected_fetcher_for_relation() {
        let current = version("0.82.0", "7");
        let check = check_with(
            UpdateCheckRequest {
                current: current.clone(),
                version_url: "http://fixture.invalid/VERSION".to_owned(),
                timeout: Duration::from_secs(1),
            },
            || async { Ok(version("0.82.0", "8")) },
        )
        .await
        .unwrap();
        assert_eq!(check.current, current);
        assert_eq!(check.relation, UpdateRelation::Available);
        let current = check_with(
            UpdateCheckRequest {
                current: version("1.0", "1"),
                version_url: "http://fixture.invalid/VERSION".to_owned(),
                timeout: Duration::from_secs(1),
            },
            || async { Ok(version("0.9", "99")) },
        )
        .await
        .unwrap();
        assert_eq!(current.relation, UpdateRelation::Ahead);
    }

    #[tokio::test]
    async fn fetches_valid_loopback_response_and_rejects_http_and_size_errors() {
        let valid = fixture(b"HTTP/1.1 200 OK\r\nContent-Length: 51\r\nConnection: close\r\n\r\nMARKETING_VERSION=0.83.0\nCURRENT_PROJECT_VERSION=1\n".to_vec()).await;
        assert_eq!(
            fetch(&valid, Duration::from_secs(2)).await.unwrap(),
            version("0.83.0", "1")
        );

        let checked_url = fixture(b"HTTP/1.1 200 OK\r\nContent-Length: 51\r\nConnection: close\r\n\r\nMARKETING_VERSION=0.83.0\nCURRENT_PROJECT_VERSION=1\n".to_vec()).await;
        let checked = check(UpdateCheckRequest::new(
            version("0.82.0", "36"),
            checked_url,
            Duration::from_secs(2),
        ))
        .await
        .unwrap();
        assert_eq!(checked.relation, UpdateRelation::Available);

        let oversized = fixture(
            b"HTTP/1.1 200 OK\r\nContent-Length: 4097\r\nConnection: close\r\n\r\n".to_vec(),
        )
        .await;
        assert_eq!(
            fetch(&oversized, Duration::from_secs(2)).await,
            Err(UpdateError::Oversized)
        );

        let mut chunked =
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n1001\r\n"
                .to_vec();
        chunked.extend(vec![b'x'; MAX_BYTES + 1]);
        chunked.extend_from_slice(b"\r\n0\r\n\r\n");
        let chunked = fixture(chunked).await;
        assert_eq!(
            fetch(&chunked, Duration::from_secs(2)).await,
            Err(UpdateError::Oversized)
        );

        let status = fixture(
            b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                .to_vec(),
        )
        .await;
        assert_eq!(
            fetch(&status, Duration::from_secs(2)).await,
            Err(UpdateError::Network)
        );

        assert_eq!(
            fetch("http://127.0.0.1:0/VERSION", Duration::from_millis(100)).await,
            Err(UpdateError::Network)
        );
        assert_eq!(
            fetch(&valid, Duration::ZERO).await,
            Err(UpdateError::Timeout)
        );
    }
}
