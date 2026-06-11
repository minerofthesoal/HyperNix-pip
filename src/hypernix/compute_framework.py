"""compute_framework.py — Hardware-agnostic multi-device training framework.

v0.70.0: Abstracts away CUDA, MPS, CPU, and handles DDP / ZeRO wrapping automatically.
"""
from __future__ import annotations

import os

import torch
import torch.nn as nn


class ComputeArch:
    """Hardware architecture type."""
    CUDA = "cuda"
    MPS = "mps"
    CPU = "cpu"
    TPU = "tpu"


class ComputeFramework:
    """A high-level framework for training models on different GPUs/CPUs/architectures.
    
    Automatically handles PyTorch DDP initialization, device placement,
    and fallback logic.
    """

    def __init__(
        self,
        local_rank: int = -1,
        world_size: int = 1,
        use_ddp: bool = False,
        use_fsdp: bool = False,
        zero_stage: int = 0,
    ) -> None:
        self.local_rank = local_rank
        self.world_size = world_size
        self.use_ddp = use_ddp
        self.use_fsdp = use_fsdp
        self.zero_stage = zero_stage
        
        self.arch = self._detect_arch()
        self.device = self._setup_device()
        self.is_main_process = self.local_rank in [-1, 0]

    def _detect_arch(self) -> str:
        if torch.cuda.is_available():
            return ComputeArch.CUDA
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return ComputeArch.MPS
        return ComputeArch.CPU

    def _setup_device(self) -> torch.device:
        if self.use_ddp or self.use_fsdp:
            if "LOCAL_RANK" in os.environ:
                self.local_rank = int(os.environ["LOCAL_RANK"])
            if "WORLD_SIZE" in os.environ:
                self.world_size = int(os.environ["WORLD_SIZE"])
            
            if self.arch == ComputeArch.CUDA and self.local_rank != -1:
                torch.cuda.set_device(self.local_rank)
                torch.distributed.init_process_group(backend="nccl")
                return torch.device(f"cuda:{self.local_rank}")
                
        if self.arch == ComputeArch.CUDA:
            return torch.device("cuda")
        elif self.arch == ComputeArch.MPS:
            return torch.device("mps")
        return torch.device("cpu")

    def prepare_model(self, model: nn.Module) -> nn.Module:
        """Move model to the correct device and wrap it in DDP/FSDP if requested."""
        model = model.to(self.device)
        
        if self.use_fsdp and self.arch == ComputeArch.CUDA:
            from torch.distributed.fsdp import FullyShardedDataParallel as FSDP
            model = FSDP(model, device_id=self.local_rank)
            
        elif self.use_ddp and self.arch == ComputeArch.CUDA and self.local_rank != -1:
            from torch.nn.parallel import DistributedDataParallel as DDP
            model = DDP(model, device_ids=[self.local_rank], output_device=self.local_rank)
            
        return model

    def prepare_optimizer(self, optimizer: torch.optim.Optimizer) -> torch.optim.Optimizer:
        """Hook to wrap optimizer for ZeRO stages if implemented manually."""
        return optimizer

    def cleanup(self) -> None:
        """Destroy distributed process groups if any."""
        if (self.use_ddp or self.use_fsdp) and torch.distributed.is_initialized():
            torch.distributed.destroy_process_group()
