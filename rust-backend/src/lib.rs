//! Headless asynchronous services shared by the transitional and native UIs.
//!
//! This crate deliberately has no GTK or Python dependency. Domain data types
//! are introduced in `codexbar-core`; service integrations can then expose
//! `BackendHandle<Snapshot>` to either frontend without moving policy into it.

use std::{future::Future, sync::Arc, time::SystemTime};

use tokio::{sync::watch, task::JoinHandle};

/// Stable, non-sensitive categories for errors crossing the service boundary.
///
/// The backend intentionally does not carry subprocess output, URLs, arbitrary
/// error strings, or credentials in this type. Detailed diagnostics belong in
/// local logs with explicit redaction at the point where they are produced.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BackendErrorKind {
    Cancelled,
    Configuration,
    Network,
    Protocol,
    Process,
    Storage,
    Timeout,
    Internal,
}

/// A safe error summary suitable for state snapshots and frontend display.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BackendError {
    pub kind: BackendErrorKind,
    /// Static operation identifier; callers must not put user data here.
    pub operation: &'static str,
}

impl BackendError {
    pub const fn new(kind: BackendErrorKind, operation: &'static str) -> Self {
        Self { kind, operation }
    }
}

/// Lifecycle state published to a frontend. A failed refresh retains the most
/// recent successful snapshot rather than replacing it with fabricated data.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BackendStatus {
    Idle,
    Refreshing,
    Ready,
    Failed,
    Stopped,
}

/// Immutable, versioned service state. `watch` coalesces updates intentionally:
/// frontends need the latest snapshot, not an unbounded queue of stale frames.
#[derive(Clone, Debug)]
pub struct BackendState<T> {
    pub sequence: u64,
    pub changed_at: SystemTime,
    pub status: BackendStatus,
    pub snapshot: Option<Arc<T>>,
    pub last_error: Option<BackendError>,
}

impl<T> BackendState<T> {
    fn initial() -> Self {
        Self {
            sequence: 0,
            changed_at: SystemTime::now(),
            status: BackendStatus::Idle,
            snapshot: None,
            last_error: None,
        }
    }
}

/// Cancellation signal passed to long-lived backend work and subprocess tasks.
#[derive(Clone, Debug)]
pub struct Cancellation {
    receiver: watch::Receiver<bool>,
}

impl Cancellation {
    /// Resolves once shutdown has been requested. Cancellation is cooperative;
    /// implementations must also configure timeouts for uninterruptible I/O.
    pub async fn cancelled(mut self) {
        loop {
            if *self.receiver.borrow() {
                return;
            }
            if self.receiver.changed().await.is_err() {
                return;
            }
        }
    }

    pub fn is_cancelled(&self) -> bool {
        *self.receiver.borrow()
    }
}

/// Publication side of the backend state contract, owned by the service task.
#[derive(Debug)]
pub struct StatePublisher<T> {
    sender: watch::Sender<BackendState<T>>,
}

impl<T> Clone for StatePublisher<T> {
    fn clone(&self) -> Self {
        Self {
            sender: self.sender.clone(),
        }
    }
}

impl<T> StatePublisher<T> {
    fn update(&self, f: impl FnOnce(&mut BackendState<T>)) {
        self.sender.send_modify(|state| {
            state.sequence = state.sequence.wrapping_add(1);
            state.changed_at = SystemTime::now();
            f(state);
        });
    }

    /// Mark a refresh in progress while retaining the previous successful data.
    pub fn refreshing(&self) {
        self.update(|state| {
            state.status = BackendStatus::Refreshing;
            state.last_error = None;
        });
    }

    /// Publish a complete successful snapshot.
    pub fn publish(&self, snapshot: T) {
        self.update(|state| {
            state.status = BackendStatus::Ready;
            state.snapshot = Some(Arc::new(snapshot));
            state.last_error = None;
        });
    }

    /// Publish a failure without discarding the last successful snapshot.
    pub fn fail(&self, error: BackendError) {
        self.update(|state| {
            state.status = BackendStatus::Failed;
            state.last_error = Some(error);
        });
    }
}

/// Frontend-facing handle for a headless backend task.
///
/// The UI subscribes to `state()` and marshals changes onto its own main
/// context. Calling `shutdown` requests cooperative cancellation and joins the
/// task; dropping the handle also requests cancellation but cannot await it.
pub struct BackendHandle<T> {
    state: watch::Receiver<BackendState<T>>,
    cancel: watch::Sender<bool>,
    task: Option<JoinHandle<Result<(), BackendError>>>,
}

impl<T: Send + Sync + 'static> BackendHandle<T> {
    /// Start a backend task on the caller's Tokio runtime.
    ///
    /// Keeping runtime construction outside the library lets applications own
    /// their shutdown policy and makes tests use a deterministic headless
    /// runtime. No GTK callback or Python interpreter is required.
    pub fn spawn<F, Fut>(task: F) -> Self
    where
        F: FnOnce(Cancellation, StatePublisher<T>) -> Fut + Send + 'static,
        Fut: Future<Output = Result<(), BackendError>> + Send + 'static,
    {
        let (state_tx, state_rx) = watch::channel(BackendState::initial());
        let (cancel_tx, cancel_rx) = watch::channel(false);
        let cancellation = Cancellation {
            receiver: cancel_rx,
        };
        let publisher = StatePublisher { sender: state_tx };
        let task_publisher = publisher.clone();
        let task = tokio::spawn(async move {
            match task(cancellation, publisher).await {
                Ok(()) => {
                    task_publisher.update(|state| state.status = BackendStatus::Stopped);
                    Ok(())
                }
                Err(error) => {
                    task_publisher.fail(error);
                    Err(error)
                }
            }
        });

        Self {
            state: state_rx,
            cancel: cancel_tx,
            task: Some(task),
        }
    }

    /// Subscribe to the latest immutable state. Consumers should check the
    /// current value before awaiting `changed()` to avoid missing initial data.
    pub fn state(&self) -> watch::Receiver<BackendState<T>> {
        self.state.clone()
    }

    /// Signal cancellation and wait for the backend task to finish.
    pub async fn shutdown(mut self) -> Result<(), BackendError> {
        self.cancel.send_replace(true);
        match self.task.take().expect("backend task already joined").await {
            Ok(result) => result,
            Err(_) => Err(BackendError::new(
                BackendErrorKind::Internal,
                "backend_task_join",
            )),
        }
    }
}

impl<T> Drop for BackendHandle<T> {
    fn drop(&mut self) {
        self.cancel.send_replace(true);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::time::{timeout, Duration};

    #[tokio::test]
    async fn cancellation_stops_worker_and_shutdown_joins_it() {
        let handle = BackendHandle::<u8>::spawn(|cancel, _| async move {
            cancel.cancelled().await;
            Ok(())
        });
        let state = handle.state();

        timeout(Duration::from_secs(1), handle.shutdown())
            .await
            .expect("worker should observe cancellation")
            .expect("worker should stop cleanly");
        assert_eq!(state.borrow().status, BackendStatus::Stopped);
    }

    #[tokio::test]
    async fn failed_refresh_retains_last_successful_snapshot() {
        let handle = BackendHandle::spawn(|_cancel, publisher| async move {
            publisher.refreshing();
            publisher.publish(vec![10, 20]);
            publisher.refreshing();
            let error = BackendError::new(BackendErrorKind::Network, "usage_refresh");
            publisher.fail(error);
            Ok(())
        });
        let mut state = handle.state();

        timeout(Duration::from_secs(1), async {
            while state.borrow().status != BackendStatus::Stopped {
                state
                    .changed()
                    .await
                    .expect("backend state sender remains open");
            }
        })
        .await
        .expect("worker should publish terminal state");

        let final_state = state.borrow();
        assert_eq!(final_state.status, BackendStatus::Stopped);
        assert_eq!(final_state.snapshot.as_deref(), Some(&vec![10, 20]));
        assert_eq!(
            final_state.last_error,
            Some(BackendError::new(
                BackendErrorKind::Network,
                "usage_refresh",
            ))
        );
        assert!(final_state.sequence >= 5);
        drop(final_state);
        handle.shutdown().await.expect("worker should join");
    }

    #[tokio::test]
    async fn task_error_is_safe_and_visible_in_state() {
        let expected = BackendError::new(BackendErrorKind::Timeout, "cli_usage");
        let handle =
            BackendHandle::<()>::spawn(move |_cancel, _publisher| async move { Err(expected) });
        let mut state = handle.state();

        timeout(Duration::from_secs(1), async {
            while state.borrow().status != BackendStatus::Failed {
                state
                    .changed()
                    .await
                    .expect("backend state sender remains open");
            }
        })
        .await
        .expect("failure should be published");
        assert_eq!(state.borrow().last_error, Some(expected));
        drop(state);
        assert_eq!(handle.shutdown().await, Err(expected));
    }
}
