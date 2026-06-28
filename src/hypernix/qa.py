"""qa.py — Q&A dataset formatter and shaker processor.

v0.70.4: New module. Formats raw dataset entries into templated question-answer
prompts for language model training, with optional integrated salt/pepper seasoning.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from .salt_shaker import Shaker


class QAProcessor:
    """Formatter and seasoning processor for Q&A datasets.
    
    Turns structured datasets (JSONL, dicts, etc.) into raw text strings for
    causal language model training, allowing the AI to learn to predict next text
    or answer questions.
    """

    def __init__(
        self,
        source: Path | str | Iterable[dict[str, str]] | Iterable[str],
        salt_shaker: Shaker | None = None,
        pepper_shaker: Shaker | None = None,
        format_mode: str = "question_answer",  # "question_answer" or "predict_next"
        question_key: str = "question",
        answer_key: str = "answer",
        season_target: str = "both",  # "question", "answer", or "both"
    ) -> None:
        self.source = source
        self.salt_shaker = salt_shaker
        self.pepper_shaker = pepper_shaker
        self.format_mode = format_mode
        self.question_key = question_key
        self.answer_key = answer_key
        self.season_target = season_target

    def _apply_seasoning(self, text: str) -> str:
        """Apply shakers to the text directly for efficiency and templates protection."""
        if not text:
            return text
        if self.pepper_shaker is not None:
            text = self.pepper_shaker.season(text)
        if self.salt_shaker is not None:
            text = self.salt_shaker.season(text)
        return text

    def _parse_entry(self, entry: Any) -> tuple[str, str] | None:
        """Extract question and answer from an entry (dict or string)."""
        if isinstance(entry, dict):
            # Try specified keys
            q = entry.get(self.question_key)
            a = entry.get(self.answer_key)
            
            # Fallbacks for common instruction/prompt keys
            if q is None:
                for k in ["prompt", "instruction", "input", "q"]:
                    if k in entry:
                        q = entry[k]
                        break
            if a is None:
                for k in ["completion", "response", "output", "a"]:
                    if k in entry:
                        a = entry[k]
                        break
            
            if q is not None and a is not None:
                return str(q), str(a)
                
        elif isinstance(entry, str):
            # Parse JSON line if possible
            try:
                data = json.loads(entry)
                if isinstance(data, dict):
                    return self._parse_entry(data)
            except json.JSONDecodeError:
                pass
                
            # If plain string, split by first tab, colon, or question mark
            for delim in ["\t", "::", " | "]:
                if delim in entry:
                    parts = entry.split(delim, 1)
                    return parts[0].strip(), parts[1].strip()
                    
        return None

    def _iter_raw_source(self) -> Iterator[Any]:
        if isinstance(self.source, (str, Path)):
            with Path(self.source).open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    yield line.strip()
        else:
            yield from self.source

    def process(self) -> Iterator[str]:
        """Process the dataset and yield raw training text strings."""
        for entry in self._iter_raw_source():
            parsed = self._parse_entry(entry)
            if parsed is None:
                # If entry cannot be parsed, yield it raw (maybe after seasoning)
                if isinstance(entry, str):
                    yield self._apply_seasoning(entry)
                continue
                
            q, a = parsed
            
            # Apply seasoning selectively for templates safety and efficiency
            if self.season_target == "question":
                q = self._apply_seasoning(q)
            elif self.season_target == "answer":
                a = self._apply_seasoning(a)
            elif self.season_target == "both":
                q = self._apply_seasoning(q)
                a = self._apply_seasoning(a)
                
            # Format according to mode
            if self.format_mode == "question_answer":
                formatted = f"Question: {q}\nAnswer: {a}"
            else:  # predict_next / concatenation
                formatted = f"{q} {a}"
                
            yield formatted

    def __iter__(self) -> Iterator[str]:
        yield from self.process()
