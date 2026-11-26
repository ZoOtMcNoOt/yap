use std::{sync::mpsc, thread};

// A CoreAudio stream contains a thread-local property listener. Build, play and
// destroy it on one thread. Only the packet worker's handle crosses this boundary.
pub(super) struct StreamOwner {
    stop: mpsc::Sender<()>,
    owner: thread::JoinHandle<Result<(), String>>,
}

impl StreamOwner {
    pub(super) fn open<S: 'static>(
        open: impl FnOnce() -> Result<(S, thread::JoinHandle<()>), String> + Send + 'static,
    ) -> Result<(Self, thread::JoinHandle<()>), String> {
        let (started, ready) = mpsc::sync_channel(0);
        let (stop, stopped) = mpsc::channel();
        let owner = thread::Builder::new()
            .name("yap-coreaudio-stream".into())
            .spawn(move || {
                let (stream, worker) = open()?;
                if let Err(unsent) = started.send(worker) {
                    drop(stream);
                    let _ = unsent.0.join();
                    return Ok(());
                }
                let _ = stopped.recv();
                drop(stream);
                Ok(())
            })
            .map_err(|error| format!("Could not start the microphone thread: {error}"))?;
        let stream = Self { stop, owner };
        match ready.recv() {
            Ok(worker) => Ok((stream, worker)),
            Err(_) => {
                stream.shutdown()?;
                Err("Microphone thread stopped before opening the stream.".into())
            }
        }
    }

    pub(super) fn shutdown(self) -> Result<(), String> {
        drop(self.stop);
        self.owner
            .join()
            .map_err(|_| "Microphone stream thread panicked.".to_string())?
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::rc::Rc;

    #[test]
    fn stream_is_retired_on_its_opening_thread_before_the_packet_worker_is_joined() {
        struct Stream {
            owner: thread::ThreadId,
            _local: Rc<()>,
            _packets: mpsc::Sender<()>,
        }
        impl Drop for Stream {
            fn drop(&mut self) {
                assert_eq!(thread::current().id(), self.owner);
            }
        }
        let (owner, worker) = StreamOwner::open(|| {
            let (packets, drained) = mpsc::channel();
            let worker = thread::spawn(move || assert!(drained.recv().is_err()));
            Ok((
                Stream {
                    owner: thread::current().id(),
                    _local: Rc::new(()),
                    _packets: packets,
                },
                worker,
            ))
        })
        .unwrap();
        owner.shutdown().unwrap();
        worker.join().unwrap();
    }

    #[test]
    fn failed_microphone_start_returns_its_original_error() {
        let result = StreamOwner::open::<Rc<()>>(|| Err("device unavailable".into()));
        assert!(matches!(result, Err(message) if message == "device unavailable"));
    }
}
