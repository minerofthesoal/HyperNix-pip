"""stml.py — Short Term Memory Loss (STML) context management and calculator.

v0.70.4: New module. Manages trained and untrained max contexts using segment folding,
and estimates allowed context lengths using VRAM capacity.
"""
from __future__ import annotations

from typing import Any

import torch


def calculate_vram_context(
    vram_gb: float,
    model_size_params: float,  # in billions, e.g. 4.0 for 4B
    batch_size: int,
    precision: str = "fp16",
    num_layers: int = 32,
    num_heads: int = 32,
    head_dim: int = 128,
) -> int:
    """Calculate the maximum trained context sequence length that can fit in available VRAM."""
    # Convert VRAM to bytes
    total_vram = vram_gb * 1024 * 1024 * 1024
    
    # Estimate memory overheads
    # Model weights, gradients, optimizer states (assuming AdamW)
    params_count = model_size_params * 1e9
    
    if precision == "fp32":
        param_overhead = 16.0  # 4 (weights) + 4 (grad) + 8 (optimizer)
    elif precision == "fp16":
        param_overhead = 12.0  # 2 (weights) + 2 (grad) + 8 (optimizer)
    elif precision == "int8":
        # Assume QLoRA: weights in int8, optimizer for 2% active adapter params
        param_overhead = 1.0 + (0.02 * 12.0)
    elif precision == "int4":
        # Assume QLoRA: weights in int4, optimizer for 2% active adapter params
        param_overhead = 0.5 + (0.02 * 12.0)
    else:
        param_overhead = 12.0
        
    model_mem = params_count * param_overhead
    
    # Leftover VRAM for KV cache and activations
    available_vram = total_vram - model_mem
    
    # Reserve 15% safety margin or at least 1GB for PyTorch/CUDA context overhead
    safety_margin = max(1.0 * 1024 * 1024 * 1024, total_vram * 0.15)
    available_vram -= safety_margin
    
    if available_vram <= 0:
        # Model doesn't even fit in VRAM! Return a minimum safe default context
        return 128
        
    # KV cache size per token per sequence:
    # 2 * num_layers * num_heads * head_dim * precision_bytes * batch_size
    precision_bytes = 2.0 if precision in ["fp16", "int8", "int4"] else 4.0
    kv_bytes_per_token = 2.0 * num_layers * num_heads * head_dim * precision_bytes * batch_size
    
    # Activation memory estimation (heuristics based on transformer activation size)
    hidden_dim = num_heads * head_dim
    activation_bytes_per_token = 10.0 * num_layers * batch_size * hidden_dim * precision_bytes
    
    total_bytes_per_token = kv_bytes_per_token + activation_bytes_per_token
    
    max_seq_len = int(available_vram // total_bytes_per_token)
    
    # Clip context length to typical powers of 2 / reasonable boundaries
    if max_seq_len < 128:
        return 128
    
    # Find nearest multiple of 128
    return (max_seq_len // 128) * 128


class STML:
    """Short Term Memory Loss (STML) context management tool.
    
    Manages both a trained context and a larger untrained max context. Can also
    fold sequence data into segments of a usable context that is trained but in segments.
    """

    def __init__(
        self,
        trained_context: int = 2048,
        untrained_max_context: int = 8192,
        segment_length: int = 512,
        regulator: Any = None,
    ) -> None:
        self.trained_context = trained_context
        self.untrained_max_context = untrained_max_context
        self.segment_length = segment_length
        self.regulator = regulator

    def regulate(self, batch: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
        """Regulate context length by first running the curriculum regulator,

        and then folding/segmenting sequences that exceed the segment length.
        """
        # 1. Apply curriculum regulation (Abbicus/TurboAbbicus) if present
        if self.regulator is not None:
            batch = self.regulator.regulate(batch)
            
        if "input_ids" not in batch:
            return batch
            
        input_ids = batch["input_ids"]
        seq_len = input_ids.shape[1]
        
        # 2. Enforce the untrained max context hard cap by truncating
        if seq_len > self.untrained_max_context:
            for k in ["input_ids", "attention_mask", "labels"]:
                if k in batch:
                    batch[k] = batch[k][:, :self.untrained_max_context].contiguous()
            seq_len = self.untrained_max_context
            
        # 3. Fold the sequence into segments of segment_length
        if seq_len > self.segment_length:
            # Pad to multiple of segment_length first
            rem = seq_len % self.segment_length
            if rem != 0:
                pad_len = self.segment_length - rem
                if "input_ids" in batch:
                    batch["input_ids"] = torch.nn.functional.pad(batch["input_ids"], (0, pad_len), value=0)
                if "attention_mask" in batch:
                    batch["attention_mask"] = torch.nn.functional.pad(batch["attention_mask"], (0, pad_len), value=0)
                if "labels" in batch:
                    batch["labels"] = torch.nn.functional.pad(batch["labels"], (0, pad_len), value=-100)
                seq_len += pad_len
                
            num_segments = seq_len // self.segment_length
            bsz = input_ids.shape[0]
            
            # Reshape tensors to fold sequence length into the batch dimension
            for k in ["input_ids", "attention_mask", "labels"]:
                if k in batch:
                    batch[k] = batch[k].view(bsz * num_segments, self.segment_length).contiguous()
                    
        return batch
