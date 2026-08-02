//! Common utilities shared across crates

#![cfg_attr(not(feature = "std"), no_std)]

pub mod types;
pub mod ringbuf;
pub mod can_frames;

/// Common result type
pub type Result<T> = core::result::Result<T, Error>;

/// Common error type
#[derive(Debug, Clone, Copy)]
pub enum Error {
    InvalidParameter,
    NotReady,
    Timeout,
    BufferFull,
}
