"""hypernix.cardboard_box — Efficient token packing, reading, and pruning.

A high-performance storage mechanism for tokenized datasets that allows
appending tokens, reading chunks, and logically pruning old data without
immediately rewriting the entire file.

Added in v0.70.4b14.
"""
from __future__ import annotations

import mmap
import os
import struct
from pathlib import Path

import numpy as np

__all__ = ["CardboardBox"]


class CardboardBox:
    """An efficient file-based token storage using memory mapping.
    
    Tokens are stored as int32. The file contains a 16-byte header:
    - offset 0: int64 (head) - The logical start index of valid tokens.
    - offset 8: int64 (tail) - The total number of tokens appended so far.
    
    The physical file size grows as tokens are appended. When `prune` is
    called, the head index is incremented. Defragmentation can be triggered
    manually to reclaim disk space.
    """

    HEADER_FORMAT = "<qq"  # Two 64-bit signed integers (head, tail)
    HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
    TOKEN_DTYPE = np.int32
    TOKEN_SIZE = 4

    def __init__(self, filepath: str | Path, create_if_missing: bool = True) -> None:
        self.filepath = Path(filepath)
        self._head = 0
        self._tail = 0

        if not self.filepath.exists():
            if create_if_missing:
                self._initialize_empty_file()
            else:
                raise FileNotFoundError(f"File not found: {self.filepath}")
        else:
            self._read_header()

    def _initialize_empty_file(self) -> None:
        with open(self.filepath, "wb") as f:
            f.write(struct.pack(self.HEADER_FORMAT, 0, 0))
        self._head = 0
        self._tail = 0

    def _read_header(self) -> None:
        with open(self.filepath, "rb") as f:
            header_data = f.read(self.HEADER_SIZE)
            if len(header_data) < self.HEADER_SIZE:
                raise ValueError(f"Corrupted cardboard box file: {self.filepath}")
            self._head, self._tail = struct.unpack(self.HEADER_FORMAT, header_data)

    def _write_header(self) -> None:
        # We open in 'r+b' to overwrite the header without truncating
        with open(self.filepath, "r+b") as f:
            f.seek(0)
            f.write(struct.pack(self.HEADER_FORMAT, self._head, self._tail))

    def append(self, tokens: list[int] | np.ndarray) -> None:
        """Pack and append tokens to the file."""
        arr = np.asarray(tokens, dtype=self.TOKEN_DTYPE)
        if arr.size == 0:
            return

        # Append data
        with open(self.filepath, "ab") as f:
            f.write(arr.tobytes())

        self._tail += arr.size
        self._write_header()

    def read(self, start_idx: int, length: int) -> np.ndarray:
        """Read a slice of valid tokens."""
        if start_idx < 0:
            raise IndexError("start_idx must be >= 0")
        
        logical_start = self._head + start_idx
        logical_end = logical_start + length

        if logical_start >= self._tail:
            return np.array([], dtype=self.TOKEN_DTYPE)
        
        if logical_end > self._tail:
            logical_end = self._tail
            length = logical_end - logical_start

        byte_offset = self.HEADER_SIZE + (logical_start * self.TOKEN_SIZE)
        
        with open(self.filepath, "r+b") as f:
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                mm.seek(byte_offset)
                data = mm.read(length * self.TOKEN_SIZE)
                
        return np.frombuffer(data, dtype=self.TOKEN_DTYPE).copy()

    def prune(self, count: int) -> None:
        """Delete `count` tokens from the beginning of the valid data."""
        if count <= 0:
            return
            
        valid_count = self.valid_tokens
        if count > valid_count:
            count = valid_count
            
        self._head += count
        self._write_header()

    @property
    def valid_tokens(self) -> int:
        """The number of currently valid (unpruned) tokens."""
        return self._tail - self._head

    def defragment(self) -> None:
        """Reclaim disk space by shifting valid tokens to the start of the file."""
        if self._head == 0:
            return  # Nothing to defrag

        valid_count = self.valid_tokens
        if valid_count == 0:
            self._initialize_empty_file()
            return

        temp_path = self.filepath.with_suffix(".tmp")
        
        # Stream the valid data to a new file to avoid massive RAM usage
        chunk_size_tokens = 1024 * 1024  # 4 MB chunks
        byte_offset = self.HEADER_SIZE + (self._head * self.TOKEN_SIZE)
        
        with open(self.filepath, "rb") as src_f, open(temp_path, "wb") as dst_f:
            # Write new header
            dst_f.write(struct.pack(self.HEADER_FORMAT, 0, valid_count))
            
            # Copy data
            src_f.seek(byte_offset)
            remaining_bytes = valid_count * self.TOKEN_SIZE
            
            while remaining_bytes > 0:
                to_read = min(remaining_bytes, chunk_size_tokens * self.TOKEN_SIZE)
                data = src_f.read(to_read)
                if not data:
                    break
                dst_f.write(data)
                remaining_bytes -= len(data)

        # Atomic replace
        os.replace(temp_path, self.filepath)
        self._head = 0
        self._tail = valid_count
