"""abbicus.py — Automatic token regulation and curriculum tuning.

v0.70.0: New module. Modifies and regulates tokens from datasets
based on the model's size, context length, and dataset complexity.
"""
from __future__ import annotations

import math
from typing import Any

import torch


class AbbicusConfig:
    """Configuration for Abbicus token regulation."""
    def __init__(
        self,
        model_size: str = "7B",
        base_context_length: int = 4096,
        dataset_type: str = "text",
        curriculum_steps: int = 10000,
        dynamic_padding: bool = True,
    ) -> None:
        self.model_size = model_size.upper()
        self.base_context_length = base_context_length
        self.dataset_type = dataset_type
        self.curriculum_steps = curriculum_steps
        self.dynamic_padding = dynamic_padding

        self.size_multiplier = self._get_size_multiplier()

    def _get_size_multiplier(self) -> float:
        s = self.model_size
        if "1B" in s or "0.5B" in s or "0.8B" in s:
            return 0.5
        if "3B" in s or "4B" in s:
            return 0.8
        if "7B" in s or "8B" in s or "9B" in s:
            return 1.0
        if "14B" in s or "20B" in s or "27B" in s:
            return 1.5
        if "70B" in s or "72B" in s:
            return 2.0
        return 1.0


class Abbicus:
    """The Abbicus Token Regulator.
    
    Dynamically modifies the max sequence length and token padding/truncation
    strategies during training, depending on the current global step and model size.
    """

    def __init__(self, config: AbbicusConfig) -> None:
        self.config = config
        self._current_step = 0
        self._max_allowed_len = self._compute_allowed_len()

    def _compute_allowed_len(self) -> int:
        """Compute allowed context length based on curriculum."""
        progress = min(1.0, self._current_step / max(1, self.config.curriculum_steps))
        # Start at 25% of context, grow to 100% (or more if multiplier > 1)
        start_ratio = 0.25
        end_ratio = 1.0 * self.config.size_multiplier
        
        current_ratio = start_ratio + (end_ratio - start_ratio) * progress
        return int(self.config.base_context_length * current_ratio)

    def step(self, global_step: int) -> None:
        """Update curriculum step."""
        self._current_step = global_step
        self._max_allowed_len = self._compute_allowed_len()

    def regulate(self, batch: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
        """Regulate the batch by truncating or dynamically padding."""
        if "input_ids" not in batch:
            return batch
            
        input_ids = batch["input_ids"]
        seq_len = input_ids.shape[1]
        
        # Truncate if exceeding allowed length
        if seq_len > self._max_allowed_len:
            for k in ["input_ids", "attention_mask", "labels"]:
                if k in batch:
                    batch[k] = batch[k][:, :self._max_allowed_len].contiguous()
        
        # If dynamic padding is enabled and the batch is shorter than allowed len,
        # we might just leave it to save compute.
        # But if the dataset_type is "math" or "code", we ensure we pad to a multiple of 8
        # for tensor core efficiency.
        if self.config.dynamic_padding and self.config.dataset_type in ["math", "code"]:
            current_len = batch["input_ids"].shape[1]
            rem = current_len % 8
            if rem != 0:
                pad_len = 8 - rem
                if "input_ids" in batch:
                    pad_val = 0 # Assume 0 is pad token for now
                    batch["input_ids"] = torch.nn.functional.pad(batch["input_ids"], (0, pad_len), value=pad_val)
                if "attention_mask" in batch:
                    batch["attention_mask"] = torch.nn.functional.pad(batch["attention_mask"], (0, pad_len), value=0)
                if "labels" in batch:
                    batch["labels"] = torch.nn.functional.pad(batch["labels"], (0, pad_len), value=-100)
                    
        return batch

    @property
    def current_max_length(self) -> int:
        return self._max_allowed_len
